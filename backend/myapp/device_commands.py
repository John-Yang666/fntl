import os
import time

try:
    import redis as redis_lib
except Exception:
    redis_lib = None

from .udp_sender import create_packet

REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_CMD_STREAM_KEY = os.getenv("REDIS_CMD_STREAM_KEY", "stream:udp:cmd")
REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "200000"))

_redis_cmd = None


def _get_redis_cmd():
    global _redis_cmd
    if _redis_cmd is None:
        if redis_lib is None:
            raise RuntimeError("redis-py 不可用，请 pip install redis")
        _redis_cmd = redis_lib.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
    return _redis_cmd


def build_reconnect_packet() -> bytes:
    return create_packet(address=0x01, function_code=0x0B, unix_time=0, operation=0)


def send_reconnect_packet_to_device(device) -> None:
    if not device.ip_address:
        raise ValueError("设备未配置 IP 地址。")
    fields = {
        b"type": b"cmd",
        b"src": b"ops_reconnect",
        b"ts": str(int(time.time() * 1000)).encode(),
        b"ip": str(device.ip_address).encode(),
        b"payload": build_reconnect_packet(),
    }
    _get_redis_cmd().xadd(
        name=REDIS_CMD_STREAM_KEY,
        fields=fields,
        maxlen=REDIS_STREAM_MAXLEN,
        approximate=True,
    )
