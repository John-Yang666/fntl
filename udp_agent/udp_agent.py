from __future__ import annotations

import asyncio
import os
import threading
import logging
import socket
import queue
import time
from typing import TYPE_CHECKING

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Redis 依赖：宿主机跑 redis_stream 时需要
try:
    import redis as redis_lib
except Exception:
    redis_lib = None

if TYPE_CHECKING:
    from redis import Redis as RedisClient


# =======================
# ✅ 宿主机固定配置（不使用环境变量）
# =======================

# UDP
HOST_IP = "0.0.0.0"
HOST_PORT = 38315

# Redis Stream（双 stream）
REDIS_STREAM_HOST = "127.0.0.1"
REDIS_STREAM_PORT = 36379

REDIS_PACKET_STREAM_KEY = "stream:udp:packets"
REDIS_CMD_STREAM_KEY = "stream:udp:cmd"

# cmd stream 的消费组/consumer
REDIS_CMD_GROUP = "udp-agent-cmd"
REDIS_CMD_CONSUMER = "udp-agent-cmd-0"

# 性能参数
REDIS_STREAM_BLOCK_MS = 2000
REDIS_STREAM_COUNT = 100

# 裁剪：packet 高频，cmd 低频
REDIS_PACKET_MAXLEN = 200000   # packet stream 近似裁剪
REDIS_CMD_MAXLEN = 50000       # cmd stream 近似裁剪（够用了）


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


def load_blocked_ips():
    blocked_ips = set()
    try:
        with open("blocked_ips.txt", "r") as f:
            for line in f:
                ip = line.strip()
                if ip and not ip.startswith("#"):
                    blocked_ips.add(ip)
    except FileNotFoundError:
        logger.warning("blocked_ips.txt 未找到，已创建空文件")
        open("blocked_ips.txt", "w").close()
    except Exception as e:
        logger.error(f"加载屏蔽IP文件失败: {e}")
    return blocked_ips


blocked_ips = load_blocked_ips()


class BlockedIPsHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith("blocked_ips.txt"):
            global blocked_ips
            blocked_ips = load_blocked_ips()
            logger.info("检测到 blocked_ips.txt 更新，已重新加载 IP 列表")


# =======================
# 工具函数
# =======================
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

    def close(self) -> None:
        try:
            self._cmd_thread_stop.set()
            if self._cmd_thread:
                self._cmd_thread.join(timeout=2)
        except Exception:
            pass


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
                except OSError as e:
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
                logger.error(f"接收数据时出错: {e}", exc_info=False)
                continue

            source_ip, source_port = addr

            global udp_packet_count
            udp_packet_count += 1
            logger.info(f"收到来自 {source_ip}:{source_port} 的数据包")

            if source_ip in blocked_ips:
                logger.info(f"忽略被屏蔽的IP: {source_ip}")
                continue

            frame_head = data[:2]
            frame_tail = data[-2:]
            if frame_head != b"\x7f\x7f" or frame_tail != b"\xf7\xf7":
                logger.error("丢弃了一个格式错误的数据包：帧头或帧尾无效")
                continue

            payload = data[2:-4]
            checksum = data[-4:-2]
            calculated_checksum = calculate_checksum(payload)
            if checksum != calculated_checksum:
                logger.error(
                    f"校验和错误：接收的校验和 {checksum.hex()}，计算的校验和 {calculated_checksum.hex()}"
                )
                continue

            function_code = data[3]
            if function_code == 0x01:
                self.handle_analog_data(data, addr)

            # 发布 packet -> packet stream
            try:
                self.bus.publish_packet(source_ip, data)
            except Exception as e:
                logger.error(f"发布数据包失败(redis): {e}", exc_info=True)

    def stop(self):
        self.running = False
        try:
            self.socket.close()
        except Exception:
            pass
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
            except Exception as e:
                msg = str(e)
                if "NOGROUP" in msg:
                    logger.warning(f"[redis] group missing (NOGROUP), recreate then retry: {msg}")
                    try:
                        self._ensure_group()
                    except Exception as ee:
                        logger.error(f"[redis] recreate group failed: {ee}")
                    time.sleep(0.2)
                    continue

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
                            continue

                        if target_ip in blocked_ips:
                            logger.info(f"[redis] 忽略被屏蔽的IP: {target_ip}")
                            self.r.xack(self.stream_key, self.group, entry_id)
                            continue

                        self.send_queue.put((target_ip, payload))
                        logger.info(f"[redis] 收到 CMD，目标IP: {target_ip}，数据大小: {len(payload)} 字节")

                        self.r.xack(self.stream_key, self.group, entry_id)

                    except Exception as e:
                        logger.error(f"[redis] 处理 CMD 失败: {e}", exc_info=True)
                        # 不 ack：留 pending（需要时可加 XCLAIM 超时转移）


# =======================
# 主异步函数
# =======================
async def main():
    logger.info("启动主程序...")

    bus = MessageBus()
    logger.info("MessageBus backend = redis")

    send_queue: queue.Queue = queue.Queue()

    observer = Observer()
    observer.schedule(BlockedIPsHandler(), path=".", recursive=False)
    observer.start()

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

        try:
            observer.unschedule_all()
            observer.stop()
            observer.join()
        except Exception:
            pass

        logger.info("程序退出，已清理资源。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("退出 UDP 监控工具。")