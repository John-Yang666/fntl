import time
from typing import Callable, Dict, Tuple

StreamFields = Dict[bytes, bytes]


def latest_stream_id(redis_client, stream_name: str) -> str:
    rows = redis_client.xrevrange(stream_name, count=1)
    if not rows:
        return "0-0"
    entry_id = rows[0][0]
    return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)


def find_stream_entry(
    redis_client,
    *,
    stream_name: str,
    start_id: str,
    predicate: Callable[[StreamFields], bool],
    timeout_sec: float,
    block_ms: int = 500,
) -> Tuple[bytes, StreamFields]:
    deadline = time.monotonic() + timeout_sec
    next_id = start_id
    while time.monotonic() < deadline:
        response = redis_client.xread({stream_name: next_id}, count=20, block=block_ms)
        if not response:
            continue
        for _stream, entries in response:
            for entry_id, fields in entries:
                next_id = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                if predicate(fields):
                    return entry_id, fields
    raise TimeoutError(f"no matching entry in {stream_name} after {start_id}")


def xadd_packet(redis_client, *, stream_name: str, device_id: int, ip_address: str, packet: bytes) -> bytes:
    fields = {
        b"type": b"packet",
        b"src": b"bt_test_agent",
        b"ts": str(int(time.time() * 1000)).encode(),
        b"ip": ip_address.encode(),
        b"device_id": str(int(device_id)).encode(),
        b"data_hex": packet.hex().encode(),
    }
    return redis_client.xadd(stream_name, fields, maxlen=200000, approximate=True)

