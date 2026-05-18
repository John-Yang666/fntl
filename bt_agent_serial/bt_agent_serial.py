from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if os.name == "nt":
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

try:
    import redis
except Exception:  # pragma: no cover - surfaced at runtime.
    redis = None

try:
    import serial
except Exception:  # pragma: no cover - surfaced at runtime.
    serial = None

import bt_agent_serial.config as agent_config
from bt_agent_serial.protocol import ProtocolParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class AgentStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._state: dict[str, Any] = {
            "serial_ok": False,
            "redis_ok": False,
            "valid_frames": 0,
            "parse_errors": 0,
            "redis_publish_errors": 0,
            "comm_lost_events": 0,
            "last_frame_at": None,
            "last_error": "",
            "serial_status": "未启动",
            "uptime_sec": 0.0,
        }

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            self._state.update(kwargs)

    def inc(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._state[key] = int(self._state.get(key, 0)) + amount

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snap = dict(self._state)
            snap["uptime_sec"] = round(time.monotonic() - self._started, 1)
            return snap


class StatusEmitter(threading.Thread):
    def __init__(self, stats: AgentStats, stop_event: threading.Event, config: dict[str, Any]) -> None:
        super().__init__(daemon=True)
        self._stats = stats
        self._stop_event = stop_event
        self._config = config

    def run(self) -> None:
        while not self._stop_event.is_set():
            payload = self._stats.snapshot()
            payload["config_path"] = str(agent_config.CONFIG_PATH)
            payload["nms_id"] = int(self._config["device"]["nms_id"])
            payload["port"] = str(self._config["serial"]["port"])
            print(f"[BT_SERIAL_STATUS] {json.dumps(payload, ensure_ascii=False)}", flush=True)
            self._stop_event.wait(1.0)


class RedisPublisher:
    def __init__(self, config: dict[str, Any], stats: AgentStats) -> None:
        if redis is None:
            raise RuntimeError("redis-py 未安装/不可用（pip install redis）")
        redis_config = config["redis"]
        self._stream_config = config["stream"]
        self._nms_id = int(config["device"]["nms_id"])
        self._stats = stats
        self._client = redis.Redis(
            host=str(redis_config["host"]),
            port=int(redis_config["port"]),
            db=int(redis_config.get("db", 0)),
            decode_responses=False,
        )
        self._client.ping()
        self._stats.update(redis_ok=True)

    def publish(self, frame: bytes) -> None:
        ts_ms = int(time.time() * 1000)
        fields = {
            b"type": b"packet",
            b"src": b"bt_agent_serial",
            b"ts": str(ts_ms).encode(),
            b"ip": b"0.0.0.0",
            b"data_hex": frame.hex().encode(),
            b"device_id": str(self._nms_id).encode(),
            b"nms_id": str(self._nms_id).encode(),
        }
        self._client.xadd(
            name=str(self._stream_config["packet_stream_key"]),
            fields=fields,
            maxlen=int(self._stream_config["packet_maxlen"]),
            approximate=True,
        )
        self._stats.update(redis_ok=True)


def _open_serial(config: dict[str, Any]):
    if serial is None:
        raise RuntimeError("pyserial 未安装/不可用（pip install pyserial）")
    serial_config = config["serial"]
    return serial.Serial(
        port=str(serial_config["port"]),
        baudrate=int(serial_config["baudrate"]),
        parity=str(serial_config.get("parity", "O")),
        bytesize=int(serial_config.get("bytesize", 8)),
        stopbits=int(serial_config.get("stopbits", 1)),
        timeout=float(serial_config.get("timeout", 0.0)),
        write_timeout=float(serial_config.get("write_timeout", 0.0)),
    )


def run_agent(config: dict[str, Any], stop_event: threading.Event) -> int:
    stats = AgentStats()
    status_emitter = StatusEmitter(stats, stop_event, config)
    status_emitter.start()

    redis_retry_sec = float(config["redis"].get("startup_retry_sec", 2.0))
    publisher: RedisPublisher | None = None
    while not stop_event.is_set() and publisher is None:
        try:
            publisher = RedisPublisher(config, stats)
        except Exception as exc:
            stats.update(redis_ok=False, last_error=f"Redis连接失败: {exc}")
            logger.error("Redis连接失败: %s", exc)
            stop_event.wait(redis_retry_sec)

    if publisher is None:
        return 1

    parser = ProtocolParser(frame_len=int(config["serial"].get("frame_len", 44)))
    miss_count = 0
    max_miss = int(config["serial"].get("comm_lost_miss_count", 20))
    idle_sleep = float(config["serial"].get("idle_sleep_sec", 0.05))
    ser = None

    try:
        ser = _open_serial(config)
        stats.update(serial_ok=True, serial_status=f"{config['serial']['port']} @ {config['serial']['baudrate']}")
        logger.info("串口已打开: %s @ %s", config["serial"]["port"], config["serial"]["baudrate"])

        while not stop_event.is_set():
            try:
                waiting = int(getattr(ser, "in_waiting", 0))
                data = ser.read(waiting) if waiting > 0 else b""
            except Exception as exc:
                stats.update(serial_ok=False, serial_status=f"串口读取失败: {exc}", last_error=str(exc))
                logger.error("串口读取失败: %s", exc)
                break

            if data:
                miss_count = 0
                for result in parser.feed(data):
                    if result.raw_data is None:
                        stats.inc("parse_errors")
                        stats.update(last_error=result.error or "parse error")
                        logger.warning("串口帧解析失败: %s", result.error)
                        continue
                    try:
                        publisher.publish(result.frame)
                        stats.inc("valid_frames")
                        stats.update(last_frame_at=time.time(), redis_ok=True)
                    except Exception as exc:
                        stats.inc("redis_publish_errors")
                        stats.update(redis_ok=False, last_error=f"Redis发布失败: {exc}")
                        logger.error("Redis发布失败: %s", exc, exc_info=False)
            else:
                miss_count += 1
                if miss_count > max_miss:
                    stats.inc("comm_lost_events")
                    stats.update(serial_status="等待串口数据", serial_ok=True)
                    miss_count = 0
            time.sleep(idle_sleep)
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        stats.update(serial_ok=False, serial_status="串口已关闭")
        stop_event.set()
        status_emitter.join(timeout=2.0)
    return 0


def main() -> int:
    config = agent_config.load_config()
    stop_event = threading.Event()

    def _request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    return run_agent(config, stop_event)


if __name__ == "__main__":
    raise SystemExit(main())
