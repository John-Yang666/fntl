from __future__ import annotations

# udp_sender.py
import struct
import time
import os
from typing import Optional

# =======================
# Redis 依赖：仅 Redis Streams
# =======================
try:
    import redis as redis_lib
except Exception:
    redis_lib = None

REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_CMD_STREAM_KEY = "stream:udp:cmd"
REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "200000"))

# =======================
# 懒初始化（关键：import 阶段不触网）
# =======================
_redis = None


def _get_redis():
    global _redis
    if _redis is None:
        if redis_lib is None:
            raise RuntimeError("redis-py 未安装/不可用（pip install redis）")
        _redis = redis_lib.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
    return _redis


def create_packet(address, function_code, unix_time, operation) -> bytes:
    packet = bytearray(16)
    packet[0:2] = b"\x7F\x7F"
    packet[2] = address
    packet[3] = function_code
    packet[4:8] = struct.pack("<I", unix_time)
    packet[8] = operation
    packet[9:12] = b"\xFF\xFF\xFF"
    checksum = sum(packet[2:12]) & 0xFFFF
    packet[12:14] = struct.pack("<H", checksum)
    packet[14:16] = b"\xF7\xF7"
    return bytes(packet)


def send_packet(packet: bytes, target_ip: str) -> None:
    """
    统一发送接口（仅 Redis Streams）：
      - 写 Redis Stream（type=cmd, ip, payload）
    注意：不在 import 阶段连接任何外部服务。
    """
    r = _get_redis()

    # 可选：这里再 ping（失败只影响发送，不影响 Django/Celery 启动）
    # 如果你嫌每次发送都 ping 慢，可以注释掉这行
    r.ping()

    ts_ms = int(time.time() * 1000)
    fields = {
        b"type": b"cmd",
        b"src": b"udp_sender",
        b"ts": str(ts_ms).encode(),
        b"ip": target_ip.encode(),
        b"payload": packet,
    }
    r.xadd(
        name=REDIS_CMD_STREAM_KEY,
        fields=fields,
        maxlen=REDIS_STREAM_MAXLEN,
        approximate=True,
    )
    print(f"📤 已发送至 Redis stream '{REDIS_CMD_STREAM_KEY}'，目标: {target_ip}")


# 兼容旧名字：你 views.py / 老代码不需要改
def send_packet_via_kafka(packet: bytes, target_ip: str) -> None:
    return send_packet(packet, target_ip)


if __name__ == "__main__":
    target_ip = os.getenv("TARGET_IP", "192.168.1.100")
    address = int(os.getenv("ADDRESS", "1"))
    function_code = int(os.getenv("FUNCTION_CODE", "2"))
    unix_time = int(time.time())
    operation = int(os.getenv("OPERATION", "16"))

    packet = create_packet(address, function_code, unix_time, operation)
    send_packet(packet, target_ip)