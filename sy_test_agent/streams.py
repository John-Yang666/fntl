import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Tuple


@dataclass
class SyCommand:
    device_id: int
    command: str
    frame: bytes
    meta: Dict[str, Any]


def _field(fields: Dict[Any, Any], name: str):
    return fields.get(name) if name in fields else fields.get(name.encode())


def _text(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def parse_command_payload(fields: Dict[Any, Any]) -> SyCommand:
    raw = _field(fields, "data") or _field(fields, "json")
    if raw is None:
        raise ValueError("missing SY command data field")
    payload = json.loads(_text(raw))
    device_id = payload.get("device_id")
    if device_id is None:
        device_id = payload.get("nms_id")
    frame_hex = str(payload["frame_hex"]).replace("0x", "").replace(":", "").replace(" ", "")
    return SyCommand(
        device_id=int(device_id),
        command=str(payload.get("command") or ""),
        frame=bytes.fromhex(frame_hex),
        meta=dict(payload.get("meta") or {}),
    )


def latest_stream_id(redis_client, stream_name: str) -> str:
    rows = redis_client.xrevrange(stream_name, count=1)
    if not rows:
        return "0-0"
    return _text(rows[0][0])


def find_stream_entry(
    redis_client,
    *,
    stream_name: str,
    start_id: str,
    predicate: Callable[[Dict[Any, Any]], bool],
    timeout_sec: float,
    block_ms: int = 500,
) -> Tuple[Any, Dict[Any, Any]]:
    deadline = time.monotonic() + timeout_sec
    next_id = start_id
    while time.monotonic() < deadline:
        response = redis_client.xread({stream_name: next_id}, count=20, block=block_ms)
        if not response:
            continue
        for _stream, entries in response:
            for entry_id, fields in entries:
                next_id = _text(entry_id)
                if predicate(fields):
                    return entry_id, fields
    raise TimeoutError(f"no matching entry in {stream_name} after {start_id}")


def xadd_raw(redis_client, *, stream_name: str, nms_id: int, serial_id: int, line_id: int, req_cmd: str, frame: bytes):
    payload = {
        "payload_hex": frame.hex(),
        "ts": int(time.time()),
        "line_id": line_id,
        "port": "sy_test_agent",
        "serial_id": serial_id,
        "nms_id": nms_id,
        "req_cmd": req_cmd,
    }
    return redis_client.xadd(stream_name, {"data": json.dumps(payload, ensure_ascii=False)}, maxlen=200000, approximate=True)

