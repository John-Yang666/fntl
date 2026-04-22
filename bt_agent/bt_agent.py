from __future__ import annotations

import asyncio
from collections import deque
import json
import os
import threading
import logging
import socket
import queue
import time
from typing import TYPE_CHECKING, Any
from pathlib import Path
import copy

from protected_runtime import agent_config_path, write_json_file

# Redis 依赖：宿主机跑 redis_stream 时需要
try:
    import redis as redis_lib
except Exception:
    redis_lib = None

if TYPE_CHECKING:
    from redis import Redis as RedisClient


CONFIG_JSON_ENV = "BT_AGENT_CONFIG_JSON"
CONFIG_PATH: Path

DEFAULT_CONFIG = {
    "udp": {
        "host": "0.0.0.0",
        "port": 38315,
    },
    "redis": {
        "host": "127.0.0.1",
        "port": 36379,
        "packet_stream_key": "stream:udp:packets",
        "cmd_stream_key": "stream:udp:cmd",
        "cmd_group": "udp-agent-cmd",
        "cmd_consumer": "udp-agent-cmd-0",
        "startup_retry_sec": 2.0,
    },
    "stream": {
        "block_ms": 2000,
        "count": 100,
        "packet_maxlen": 200000,
        "cmd_maxlen": 50000,
    },
    "filters": {
        "blocked_ips": [],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_json_config(path: Path) -> dict:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return loaded


def _load_config() -> dict:
    global CONFIG_PATH
    runtime_config = str(os.environ.get(CONFIG_JSON_ENV, "")).strip()
    if runtime_config:
        CONFIG_PATH = Path(runtime_config)
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"missing runtime config file: {CONFIG_PATH}")
        loaded = _load_json_config(CONFIG_PATH)
    else:
        CONFIG_PATH = agent_config_path("bt_agent")
        if not CONFIG_PATH.exists():
            write_json_file(CONFIG_PATH, copy.deepcopy(DEFAULT_CONFIG))
        loaded = _load_json_config(CONFIG_PATH)
    config = copy.deepcopy(DEFAULT_CONFIG)
    return _deep_merge(config, loaded)


CONFIG = _load_config()

UDP_CONFIG = CONFIG["udp"]
REDIS_CONFIG = CONFIG["redis"]
STREAM_CONFIG = CONFIG["stream"]
FILTERS_CONFIG = CONFIG.get("filters", {})

HOST_IP = str(UDP_CONFIG["host"])
HOST_PORT = int(UDP_CONFIG["port"])

REDIS_STREAM_HOST = str(REDIS_CONFIG["host"])
REDIS_STREAM_PORT = int(REDIS_CONFIG["port"])
REDIS_PACKET_STREAM_KEY = str(REDIS_CONFIG["packet_stream_key"])
REDIS_CMD_STREAM_KEY = str(REDIS_CONFIG["cmd_stream_key"])
REDIS_CMD_GROUP = str(REDIS_CONFIG["cmd_group"])
REDIS_CMD_CONSUMER = str(REDIS_CONFIG["cmd_consumer"])
REDIS_STARTUP_RETRY_SEC = float(REDIS_CONFIG["startup_retry_sec"])

REDIS_STREAM_BLOCK_MS = int(STREAM_CONFIG["block_ms"])
REDIS_STREAM_COUNT = int(STREAM_CONFIG["count"])
REDIS_PACKET_MAXLEN = int(STREAM_CONFIG["packet_maxlen"])
REDIS_CMD_MAXLEN = int(STREAM_CONFIG["cmd_maxlen"])

BLOCKED_IPS = frozenset(
    str(ip).strip()
    for ip in FILTERS_CONFIG.get("blocked_ips", [])
    if str(ip).strip()
)


# =======================
# 日志配置
# =======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# =======================
# 全局变量
# =======================
udp_packet_count = 0


# =======================
# 工具函数
# =======================
def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def calculate_checksum(data: bytes) -> bytes:
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder="little")


def _fmt_payload(b: bytes, max_show: int = 32) -> str:
    try:
        n = len(b)
        if n <= max_show:
            return b.hex()
        head = b[:16].hex()
        tail = b[-16:].hex()
        return f"{head}...{tail}"
    except Exception:
        return "<unprintable-bytes>"


class AgentStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._started_mono = time.monotonic()
        self._started_wall = time.time()
        self._send_queue: queue.Queue | None = None
        self._host: dict[str, Any] = {
            "udp_socket_ok": False,
            "redis_ok": False,
            "cmd_thread_alive": False,
            "send_queue_depth": 0,
            "uptime_sec": 0.0,
            "valid_packets": 0,
            "malformed_packets": 0,
            "checksum_errors": 0,
            "blocked_packets": 0,
            "analog_packets": 0,
            "redis_publish_errors": 0,
            "cmd_received": 0,
            "cmd_acked": 0,
            "send_ok": 0,
            "send_errors": 0,
            "last_packet_at": None,
            "last_send_at": None,
        }
        self._per_ip: dict[str, dict[str, Any]] = {}

    def _ensure_ip(self, ip: str) -> dict[str, Any]:
        state = self._per_ip.get(ip)
        if state is None:
            state = {
                "ip": ip,
                "last_seen": None,
                "last_valid_seen": None,
                "valid_packets": 0,
                "malformed_packets": 0,
                "checksum_errors": 0,
                "analog_packets": 0,
                "send_ok": 0,
                "send_errors": 0,
                "recent_valid": deque(),
            }
            self._per_ip[ip] = state
        return state

    def set_send_queue(self, send_queue_ref: queue.Queue) -> None:
        with self._lock:
            self._send_queue = send_queue_ref

    def set_udp_socket_ok(self, ok: bool) -> None:
        with self._lock:
            self._host["udp_socket_ok"] = bool(ok)

    def set_redis_ok(self, ok: bool) -> None:
        with self._lock:
            self._host["redis_ok"] = bool(ok)

    def set_cmd_thread_alive(self, alive: bool) -> None:
        with self._lock:
            self._host["cmd_thread_alive"] = bool(alive)

    def note_valid_packet(self, ip: str, *, analog: bool = False) -> None:
        now_wall = time.time()
        with self._lock:
            state = self._ensure_ip(ip)
            self._host["valid_packets"] += 1
            self._host["last_packet_at"] = now_wall
            state["last_seen"] = now_wall
            state["last_valid_seen"] = now_wall
            state["valid_packets"] += 1
            state["recent_valid"].append(now_wall)
            if analog:
                self._host["analog_packets"] += 1
                state["analog_packets"] += 1

    def note_malformed_packet(self, ip: str | None = None) -> None:
        with self._lock:
            self._host["malformed_packets"] += 1
            if ip:
                state = self._ensure_ip(ip)
                state["last_seen"] = time.time()
                state["malformed_packets"] += 1

    def note_checksum_error(self, ip: str) -> None:
        with self._lock:
            self._host["checksum_errors"] += 1
            state = self._ensure_ip(ip)
            state["last_seen"] = time.time()
            state["checksum_errors"] += 1

    def note_blocked_packet(self) -> None:
        with self._lock:
            self._host["blocked_packets"] += 1

    def note_send_ok(self, ip: str) -> None:
        now_wall = time.time()
        with self._lock:
            self._host["send_ok"] += 1
            self._host["last_send_at"] = now_wall
            self._ensure_ip(ip)["send_ok"] += 1

    def note_send_error(self, ip: str) -> None:
        now_wall = time.time()
        with self._lock:
            self._host["send_errors"] += 1
            self._host["last_send_at"] = now_wall
            self._ensure_ip(ip)["send_errors"] += 1

    def note_cmd_received(self) -> None:
        with self._lock:
            self._host["cmd_received"] += 1

    def note_cmd_acked(self) -> None:
        with self._lock:
            self._host["cmd_acked"] += 1

    def note_redis_publish_error(self) -> None:
        with self._lock:
            self._host["redis_publish_errors"] += 1

    def snapshot(self) -> dict[str, Any]:
        now_wall = time.time()
        now_mono = time.monotonic()
        with self._lock:
            send_depth = 0
            if self._send_queue is not None:
                try:
                    send_depth = int(self._send_queue.qsize())
                except Exception:
                    send_depth = 0
            host = dict(self._host)
            host["send_queue_depth"] = send_depth
            host["uptime_sec"] = round(now_mono - self._started_mono, 1)
            ips: list[dict[str, Any]] = []
            for ip in sorted(self._per_ip):
                state = self._per_ip[ip]
                recent_valid = state["recent_valid"]
                while recent_valid and (now_wall - float(recent_valid[0])) > 10.0:
                    recent_valid.popleft()
                ips.append(
                    {
                        "ip": ip,
                        "last_seen": state["last_seen"],
                        "last_valid_seen": state["last_valid_seen"],
                        "valid_packets": state["valid_packets"],
                        "malformed_packets": state["malformed_packets"],
                        "checksum_errors": state["checksum_errors"],
                        "analog_packets": state["analog_packets"],
                        "send_ok": state["send_ok"],
                        "send_errors": state["send_errors"],
                        "rate_10s": round(len(recent_valid) / 10.0, 2),
                    }
                )
        return {
            "ts": _now_iso(),
            "host": host,
            "ips": ips,
        }


class StatusEmitter(threading.Thread):
    def __init__(self, stats: AgentStats, stop_event: threading.Event):
        super().__init__(daemon=True)
        self._stats = stats
        self._stop_event = stop_event

    def run(self) -> None:
        while not self._stop_event.is_set():
            print(f"[BT_STATUS] {json.dumps(self._stats.snapshot(), ensure_ascii=False)}", flush=True)
            self._stop_event.wait(1.0)


AGENT_STATS = AgentStats()


# =======================
# Redis MessageBus
# =======================
class MessageBus:
    """
    Redis 双 stream：
      - packet -> stream:udp:packets
      - cmd    -> stream:udp:cmd
    """

    def __init__(self):
        self._redis: RedisClient | None = None
        self._cmd_thread: threading.Thread | None = None
        self._cmd_thread_stop = threading.Event()

        if redis_lib is None:
            raise RuntimeError("redis-py 未安装/不可用（pip install redis）")

        self._redis = redis_lib.Redis(
            host=REDIS_STREAM_HOST,
            port=REDIS_STREAM_PORT,
            decode_responses=False,
        )
        self._redis.ping()
        AGENT_STATS.set_redis_ok(True)

        # 确保 cmd stream + group 存在（MKSTREAM）
        self._ensure_group(REDIS_CMD_STREAM_KEY, REDIS_CMD_GROUP)

    def _ensure_group(self, stream_key: str, group_name: str) -> None:
        """幂等创建 group：从 $ 开始，只消费新消息"""
        assert self._redis is not None
        try:
            self._redis.xgroup_create(
                name=stream_key,
                groupname=group_name,
                id="$",
                mkstream=True,
            )
            logger.info(f"[redis] created group={group_name} on stream={stream_key}")
        except Exception as e:
            msg = str(e)
            if "BUSYGROUP" in msg or "Consumer Group name already exists" in msg:
                return
            logger.warning(f"[redis] ensure_group got error: {e}")

    def publish_packet(self, source_ip: str, data: bytes) -> None:
        """packet 发布到 packet stream"""
        assert self._redis is not None

        ts_ms = int(time.time() * 1000)
        fields = {
            b"type": b"packet",
            b"src": b"udp_agent",
            b"ts": str(ts_ms).encode(),
            b"ip": source_ip.encode(),
            b"data_hex": data.hex().encode(),
        }
        self._redis.xadd(
            name=REDIS_PACKET_STREAM_KEY,
            fields=fields,
            maxlen=REDIS_PACKET_MAXLEN,
            approximate=True,
        )

    def start_cmd_subscriber(self, send_queue: queue.Queue) -> None:
        """启动 cmd stream 订阅线程"""
        assert self._redis is not None

        self._cmd_thread = RedisCmdSubscriber(
            r=self._redis,
            stream_key=REDIS_CMD_STREAM_KEY,
            group=REDIS_CMD_GROUP,
            consumer=REDIS_CMD_CONSUMER,
            send_queue=send_queue,
            stop_event=self._cmd_thread_stop,
        )
        self._cmd_thread.start()
        AGENT_STATS.set_cmd_thread_alive(True)

    def close(self) -> None:
        try:
            self._cmd_thread_stop.set()
            if self._cmd_thread:
                self._cmd_thread.join(timeout=2)
        except Exception:
            pass
        AGENT_STATS.set_cmd_thread_alive(False)
        AGENT_STATS.set_redis_ok(False)


# =======================
# UDP通信线程
# =======================
class UdpCommunicationThread(threading.Thread):
    def __init__(self, send_queue: queue.Queue, bus: MessageBus):
        super().__init__(daemon=True)
        self.send_queue = send_queue
        self.bus = bus
        self.running = True

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((HOST_IP, HOST_PORT))
        self.socket.settimeout(1.0)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)  # 1MB
        except Exception:
            pass
        AGENT_STATS.set_send_queue(send_queue)
        AGENT_STATS.set_udp_socket_ok(True)

    def run(self):
        logger.info(f"UDP通信线程已启动，监听 {HOST_IP}:{HOST_PORT}")

        MAX_BURST = 1000
        RECV_TIMEOUT_IDLE = 0.5
        RECV_TIMEOUT_BUSY = 0.0

        while self.running:
            # 1) 先突发发送
            sent = 0
            while sent < MAX_BURST:
                try:
                    target_ip, send_data = self.send_queue.get_nowait()
                except queue.Empty:
                    break

                try:
                    # 注意：这里仍按旧逻辑发到 HOST_PORT（38315）
                    self.socket.sendto(send_data, (target_ip, HOST_PORT))
                    sent += 1
                    AGENT_STATS.note_send_ok(target_ip)
                except OSError as e:
                    AGENT_STATS.note_send_error(target_ip)
                    err_no = getattr(e, "errno", None)
                    err_str = os.strerror(err_no) if isinstance(err_no, int) else str(e)
                    logger.error(
                        (
                            "发送数据失败 | 目标=%s:%s | 字节数=%d | 载荷(HEX片段)=%s | "
                            "异常=%s | errno=%s (%s)"
                        ),
                        target_ip,
                        HOST_PORT,
                        len(send_data),
                        _fmt_payload(send_data, 64),
                        type(e).__name__,
                        err_no,
                        err_str,
                        exc_info=False,
                    )
                except Exception as e:
                    AGENT_STATS.note_send_error(target_ip)
                    logger.error(
                        (
                            "发送数据失败(非OSError) | 目标=%s:%s | 字节数=%d | 载荷(HEX片段)=%s | "
                            "异常=%s | 详情=%s"
                        ),
                        target_ip,
                        HOST_PORT,
                        len(send_data),
                        _fmt_payload(send_data, 64),
                        type(e).__name__,
                        str(e),
                        exc_info=False,
                    )

            # 2) 动态设置接收阻塞时间
            has_more_to_send = not self.send_queue.empty()
            self.socket.settimeout(RECV_TIMEOUT_BUSY if has_more_to_send else RECV_TIMEOUT_IDLE)

            # 3) 收包
            try:
                data, addr = self.socket.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception as e:
                AGENT_STATS.set_udp_socket_ok(False)
                logger.error(f"接收数据时出错: {e}", exc_info=False)
                continue

            source_ip, source_port = addr

            global udp_packet_count
            udp_packet_count += 1
            logger.info(f"收到来自 {source_ip}:{source_port} 的数据包")

            if source_ip in BLOCKED_IPS:
                AGENT_STATS.note_blocked_packet()
                logger.info(f"忽略被屏蔽的IP: {source_ip}")
                continue

            frame_head = data[:2]
            frame_tail = data[-2:]
            if frame_head != b"\x7f\x7f" or frame_tail != b"\xf7\xf7":
                AGENT_STATS.note_malformed_packet(source_ip)
                logger.error("丢弃了一个格式错误的数据包：帧头或帧尾无效")
                continue

            payload = data[2:-4]
            checksum = data[-4:-2]
            calculated_checksum = calculate_checksum(payload)
            if checksum != calculated_checksum:
                AGENT_STATS.note_checksum_error(source_ip)
                logger.error(
                    f"校验和错误：接收的校验和 {checksum.hex()}，计算的校验和 {calculated_checksum.hex()}"
                )
                continue

            function_code = data[3]
            if function_code == 0x01:
                AGENT_STATS.note_valid_packet(source_ip, analog=True)
                self.handle_analog_data(data, addr)
            else:
                AGENT_STATS.note_valid_packet(source_ip)

            # 发布 packet -> packet stream
            try:
                self.bus.publish_packet(source_ip, data)
                AGENT_STATS.set_redis_ok(True)
            except Exception as e:
                AGENT_STATS.note_redis_publish_error()
                AGENT_STATS.set_redis_ok(False)
                logger.error(f"发布数据包失败(redis): {e}", exc_info=True)

    def stop(self):
        self.running = False
        try:
            self.socket.close()
        except Exception:
            pass
        AGENT_STATS.set_udp_socket_ok(False)
        logger.info("UDP通信线程已停止。")

    def handle_analog_data(self, data, addr):
        try:
            analog_data = data[4:16]
            logger.info(f"Received analog data from {addr}: {analog_data.hex()}")
        except Exception as e:
            logger.error(f"Error handling analog data: {e}", exc_info=True)


# =======================
# Redis Streams 命令订阅线程（只读 cmd stream）
# =======================
class RedisCmdSubscriber(threading.Thread):
    """
    从 cmd stream 里读命令消息：
      fields:
        - ip=b"..."
        - payload=b"..."
      (可选兼容字段：type=b"cmd")
    """

    def __init__(
        self,
        r: RedisClient,
        stream_key: str,
        group: str,
        consumer: str,
        send_queue: queue.Queue,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True)
        self.r = r
        self.stream_key = stream_key
        self.group = group
        self.consumer = consumer
        self.send_queue = send_queue
        self.stop_event = stop_event

    def _ensure_group(self) -> None:
        """自愈：stream/group 不存在就重建（MKSTREAM）"""
        try:
            self.r.xgroup_create(
                name=self.stream_key,
                groupname=self.group,
                id="$",
                mkstream=True,
            )
            logger.info(f"[redis] created group={self.group} on stream={self.stream_key}")
        except Exception as e:
            msg = str(e)
            if "BUSYGROUP" in msg or "Consumer Group name already exists" in msg:
                return
            raise

    def run(self):
        logger.info(
            f"[redis] 开始监听 CMD stream={self.stream_key} group={self.group} consumer={self.consumer} ..."
        )
        AGENT_STATS.set_cmd_thread_alive(True)

        # 启动先确保一次（避免 NOGROUP）
        try:
            self._ensure_group()
        except Exception as e:
            logger.warning(f"[redis] ensure_group on start failed: {e}")

        while not self.stop_event.is_set():
            try:
                resp = self.r.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer,
                    streams={self.stream_key: b">"},
                    count=REDIS_STREAM_COUNT,
                    block=REDIS_STREAM_BLOCK_MS,
                )
                AGENT_STATS.set_redis_ok(True)
            except Exception as e:
                msg = str(e)
                if "NOGROUP" in msg:
                    AGENT_STATS.set_redis_ok(False)
                    logger.warning(f"[redis] group missing (NOGROUP), recreate then retry: {msg}")
                    try:
                        self._ensure_group()
                    except Exception as ee:
                        logger.error(f"[redis] recreate group failed: {ee}")
                    time.sleep(0.2)
                    continue

                AGENT_STATS.set_redis_ok(False)
                logger.error(f"[redis] xreadgroup error: {e}")
                time.sleep(0.5)
                continue

            if not resp:
                continue

            for _stream, entries in resp:
                for entry_id, fields in entries:
                    try:
                        # 兼容：如果仍写了 type 字段，也能处理
                        msg_type = fields.get(b"type")
                        if msg_type is not None and msg_type != b"cmd":
                            self.r.xack(self.stream_key, self.group, entry_id)
                            continue

                        ip_b = fields.get(b"ip", b"")
                        payload = fields.get(b"payload", b"")

                        if not ip_b or payload is None:
                            self.r.xack(self.stream_key, self.group, entry_id)
                            continue

                        target_ip = ip_b.decode(errors="ignore").strip()
                        if not target_ip:
                            self.r.xack(self.stream_key, self.group, entry_id)
                            AGENT_STATS.note_cmd_acked()
                            continue

                        if target_ip in BLOCKED_IPS:
                            AGENT_STATS.note_cmd_received()
                            logger.info(f"[redis] 忽略被屏蔽的IP: {target_ip}")
                            self.r.xack(self.stream_key, self.group, entry_id)
                            AGENT_STATS.note_cmd_acked()
                            continue

                        AGENT_STATS.note_cmd_received()
                        self.send_queue.put((target_ip, payload))
                        logger.info(f"[redis] 收到 CMD，目标IP: {target_ip}，数据大小: {len(payload)} 字节")

                        self.r.xack(self.stream_key, self.group, entry_id)
                        AGENT_STATS.note_cmd_acked()

                    except Exception as e:
                        logger.error(f"[redis] 处理 CMD 失败: {e}", exc_info=True)
                        # 不 ack：留 pending（需要时可加 XCLAIM 超时转移）
        AGENT_STATS.set_cmd_thread_alive(False)


# =======================
# 主异步函数
# =======================
async def main():
    logger.info("启动主程序...")
    status_stop_event = threading.Event()
    status_emitter = StatusEmitter(AGENT_STATS, status_stop_event)
    status_emitter.start()

    while True:
        try:
            bus = MessageBus()
            break
        except RuntimeError:
            status_stop_event.set()
            raise
        except Exception as e:
            AGENT_STATS.set_redis_ok(False)
            logger.warning(
                "Redis Streams 未就绪，%ss 后重试: host=%s port=%s err=%s",
                REDIS_STARTUP_RETRY_SEC,
                REDIS_STREAM_HOST,
                REDIS_STREAM_PORT,
                e,
            )
            await asyncio.sleep(REDIS_STARTUP_RETRY_SEC)

    logger.info("MessageBus backend = redis")
    logger.info("Config loaded from %s", CONFIG_PATH)
    logger.info("Blocked IP count = %d", len(BLOCKED_IPS))

    send_queue: queue.Queue = queue.Queue()
    AGENT_STATS.set_send_queue(send_queue)

    udp_thread = UdpCommunicationThread(send_queue, bus)
    udp_thread.start()

    bus.start_cmd_subscriber(send_queue)

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        udp_thread.stop()

        try:
            bus.close()
        except Exception:
            pass

        status_stop_event.set()
        status_emitter.join(timeout=2)
        logger.info("程序退出，已清理资源。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("退出 UDP 监控工具。")
