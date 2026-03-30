# sy_command_sender.py
"""
SY 设备串口命令打帧 & 通过 Redis Streams 发送到 sy_agent。

约定：
- 这里只负责构造“协议帧 + 转义”，不直接操作串口。
- 发送到 Redis Streams 的是 JSON 字符串（放在字段 data 里），sy_agent 消费后：
    - json.loads(data)
    - 解析 frame_hex -> bytes
    - 根据 addr/device_id/line 信息找到对应线路和串口
    - serial.write(frame_bytes)
"""

import os
import json
import time
from datetime import datetime, timezone

import redis

# =========================
# Redis Streams 部分（懒加载 client）
# =========================

# Streams Redis（建议独立容器 redis_stream）
STREAM_REDIS_HOST = os.getenv("STREAM_REDIS_HOST", os.getenv("REDIS_HOST", "redis_stream"))
STREAM_REDIS_PORT = int(os.getenv("STREAM_REDIS_PORT", os.getenv("REDIS_PORT", "6379")))
SY_STREAM_DB = int(os.getenv("SY_STREAM_DB", "0"))

# 专门给 sy 串口命令用的 stream
SY_CMD_STREAM = os.getenv("SY_CMD_STREAM", "sy-serial-commands")
SY_CMD_STREAM_MAXLEN = int(os.getenv("SY_CMD_STREAM_MAXLEN", "200000"))

_stream_client = None


def get_stream_client() -> redis.Redis:
    global _stream_client
    if _stream_client is None:
        _stream_client = redis.StrictRedis(
            host=STREAM_REDIS_HOST,
            port=STREAM_REDIS_PORT,
            db=SY_STREAM_DB,
            decode_responses=True,
        )
    return _stream_client


def send_sy_frame_via_redis_stream(
    *,
    device_id: int,
    addr: int,
    frame: bytes,
    command: str,
    extra_meta: dict | None = None,
):
    """
    统一的发送入口（Streams）：
    - device_id: 网管数据库中设备 ID（方便 sy_agent 做映射）
    - addr: 协议中的 X 地址（单个地址，0xFF 为广播）
    - frame: 已经转义好的完整帧（可以直接写串口）
    - command: 命令名（例如 "A1", "A2", "AA", "BB_0x05"）
    - extra_meta: 可放 line_id、方向等附加信息
    """
    r = get_stream_client()

    payload = {
        "device_id": device_id,
        "addr": int(addr) & 0xFF,
        "command": command,
        "frame_hex": frame.hex(),  # sy_agent 再转回 bytes
        "ts": int(time.time()),
        "meta": extra_meta or {},
    }

    try:
        msg_id = r.xadd(
            SY_CMD_STREAM,
            fields={"data": json.dumps(payload, ensure_ascii=False)},
            maxlen=SY_CMD_STREAM_MAXLEN,
            approximate=True,
        )
        print(f"[sy_command_sender] ✅ XADD OK: stream={SY_CMD_STREAM}, id={msg_id}")
    except Exception as e:
        print(f"[sy_command_sender] ❌ XADD FAILED: {e}")
        raise


# 兼容旧调用入口：统一保留 Redis Streams 发送函数
def send_sy_frame_via_redis(*, device_id: int, addr: int, frame: bytes, command: str, extra_meta: dict | None = None):
    return send_sy_frame_via_redis_stream(
        device_id=device_id,
        addr=addr,
        frame=frame,
        command=command,
        extra_meta=extra_meta,
    )


# =========================
# 协议打帧 & 转义部分
# =========================

ESCAPE_MAP = {
    0x7F: bytes([0x10, 0x81]),
    0xF7: bytes([0x10, 0x83]),
    0x10: bytes([0x10, 0x90]),
}


def escape_body(body: bytes) -> bytes:
    out = bytearray()
    for b in body:
        mapped = ESCAPE_MAP.get(b)
        if mapped is None:
            out.append(b)
        else:
            out.extend(mapped)
    return bytes(out)


def build_frame(addr: int, func: int, payload: bytes = b"") -> bytes:
    addr &= 0xFF
    func &= 0xFF
    body = bytes([addr, func]) + payload
    escaped = escape_body(body)
    return b"\x7F\x7F" + escaped + b"\xF7"


def build_frame_with_checksum(addr: int, func: int, data_bytes: bytes) -> bytes:
    addr &= 0xFF
    func &= 0xFF
    checksum = (addr + func + sum(data_bytes)) & 0xFF
    body = bytes([addr, func]) + data_bytes + bytes([checksum])
    escaped = escape_body(body)
    return b"\x7F\x7F" + escaped + b"\xF7"


def make_cmd_a1(addr: int) -> bytes:
    return build_frame(addr, 0xA1)


def make_cmd_a2(addr: int) -> bytes:
    return build_frame(addr, 0xA2)


def make_cmd_a9(addr: int) -> bytes:
    return build_frame(addr, 0xA9)


def seconds_since_2010(now: datetime | None = None) -> int:
    if now is None:
        now = datetime.now(timezone.utc)
    base = datetime(2010, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return int((now - base).total_seconds())


def make_cmd_aa(now: datetime | None = None) -> bytes:
    sec = seconds_since_2010(now)
    time_bytes = sec.to_bytes(4, byteorder="big", signed=False)
    return build_frame_with_checksum(0xFF, 0xAA, time_bytes)


def make_cmd_b2(addr: int) -> bytes:
    return build_frame(addr, 0xB2)


def make_cmd_cc(addr: int) -> bytes:
    return build_frame(addr, 0xCC)


def make_cmd_bb(addr: int, code: int) -> bytes:
    code &= 0xFF
    payload = bytes([code, code, code, code, code])
    return build_frame(addr, 0xBB, payload)


BB_CODES = {
    "REMOTE_START_LOCAL": 0x37,
    "FORCE_A_DROP": 0x12,
    "FORCE_B_DROP": 0x24,
    "REMOTE_START_UP_FAULT1": 0x32,
    "REMOTE_START_UP_FAULT2": 0x38,
    "REMOTE_START_DOWN_FAULT1": 0x82,
    "REMOTE_START_DOWN_FAULT2": 0x88,
    "UP_AUTO": 0x03,
    "UP_FORCE_CABLE": 0x05,
    "DOWN_AUTO": 0x17,
    "DOWN_FORCE_CABLE": 0x18,
}


def make_cmd_bb_named(addr: int, name: str) -> bytes:
    return make_cmd_bb(addr, BB_CODES[name])
