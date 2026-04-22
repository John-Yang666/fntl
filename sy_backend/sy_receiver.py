from __future__ import annotations

import binascii
import json
import logging
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import redis
from psycopg2.extras import execute_values

sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa: E402

django.setup()

from django.core.cache import cache  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from consts import LAST_COMMUNICATION_TIME_TIMEOUT  # noqa: E402
from myapp.models import (  # noqa: E402
    ChangeBitEvent,
    RawFrameLog,
    RelayAction,
    SwitchData,
)
from myapp.runtime_config import (  # noqa: E402
    get_heartbeat_timeout,
    get_periodic_device_cache_refresh_interval,
)
from myapp.tasks.sy_device_context import (  # noqa: E402
    hash_sy_device_context_cache,
    load_sy_device_context_cache,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sy_receiver")


REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_REDIS_HOST = os.getenv("STREAM_REDIS_HOST", REDIS_HOST)
STREAM_REDIS_PORT = int(os.getenv("STREAM_REDIS_PORT", REDIS_PORT))

SY_STREAM_DB = int(os.getenv("SY_STREAM_DB", "0"))
SY_RAW_STREAM = os.getenv("SY_RAW_STREAM", "sy.raw")
SY_RAW_GROUP = os.getenv("SY_RAW_GROUP", "sy_ingestor")
SY_RAW_CONSUMER = os.getenv("SY_RAW_CONSUMER", f"sy-receiver-{os.getpid()}")
SY_RAW_READ_COUNT = int(os.getenv("SY_RAW_READ_COUNT", "200"))
SY_RAW_BLOCK_MS = int(os.getenv("SY_RAW_BLOCK_MS", "1000"))

INGEST_BATCH_MS = int(os.getenv("INGEST_BATCH_MS", "200"))
INGEST_MAX_BATCH = int(os.getenv("INGEST_MAX_BATCH", "500"))
INGEST_LOG_INTERVAL_SEC = int(os.getenv("INGEST_LOG_INTERVAL_SEC", "1"))
A1_HEARTBEAT_SECONDS = int(os.getenv("A1_HEARTBEAT_SECONDS", "60"))

SY_LOG_RAW_FRAMES = str(os.getenv("SY_LOG_RAW_FRAMES", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}

SWITCH_STATUS_VERSION_DEFAULT = "v4"
SQL_INSERT_PAGE_SIZE = int(os.getenv("SQL_INSERT_PAGE_SIZE", "1000"))

SWITCH_TABLE = SwitchData._meta.db_table
CHANGE_TABLE = ChangeBitEvent._meta.db_table
RELAY_TABLE = RelayAction._meta.db_table
RAW_FRAME_TABLE = RawFrameLog._meta.db_table

redis_client2 = redis.StrictRedis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=2,
    decode_responses=True,
)
redis_stream = redis.StrictRedis(
    host=STREAM_REDIS_HOST,
    port=STREAM_REDIS_PORT,
    db=SY_STREAM_DB,
    decode_responses=True,
)

RUNNING = True
last_packet_monotonic = time.monotonic()

device_context_map: dict[int, dict] = {}
worker_state = {
    "switch_status_by_device": {},
    "loaded_switch": set(),
    "last_a1_by_device": {},
    "loaded_a1": set(),
}


SY_RELAY_BITS = {
    4: ("一方向", "FDJ"),
    5: ("一方向", "ZDJ"),
    6: ("一方向", "FXJ"),
    7: ("一方向", "ZXJ"),
    12: ("二方向", "FDJ"),
    13: ("二方向", "ZDJ"),
    14: ("二方向", "FXJ"),
    15: ("二方向", "ZXJ"),
    20: ("三方向", "FDJ"),
    21: ("三方向", "ZDJ"),
    22: ("三方向", "FXJ"),
    23: ("三方向", "ZXJ"),
}


@dataclass
class SyFrameMessage:
    entry_id: str
    nms_id: int
    serial_id: int | None
    line_id: str | None
    port: str | None
    frame_bytes: bytes
    cmd: str
    payload: bytes
    received_at: datetime
    received_monotonic: float


def _switch_status_key(device_id: int) -> str:
    return f"device_{device_id}_switch_status"


def _switch_status_updated_at_key(device_id: int) -> str:
    return f"device_{device_id}_switch_status_updated_at"


def _switch_status_version_key(device_id: int) -> str:
    return f"device_{device_id}_switch_status_version"


def _alarm_key(device_id: int) -> str:
    return f"device_{device_id}_alarms"


def _alarm_updated_at_key(device_id: int) -> str:
    return f"device_{device_id}_alarms_updated_at"


def _last_a1_bytes_key(device_id: int) -> str:
    return f"sy:a1:last_bytes:{device_id}"


def _last_a1_log_ts_key(device_id: int) -> str:
    return f"sy:a1:last_log_ts:{device_id}"


def _last_comm_time_key(device_id: int) -> str:
    return f"device_{device_id}_last_communication_time"


def _last_comm_monotonic_key(device_id: int) -> str:
    return f"device_{device_id}_last_communication_monotonic"


def _coerce_bytes(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, memoryview):
        return raw_value.tobytes()
    if isinstance(raw_value, bytearray):
        return bytes(raw_value)
    if isinstance(raw_value, bytes):
        return raw_value
    return None


def _parse_iso(raw_value: str | None):
    if not raw_value:
        return None
    try:
        dt = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def load_device_context_cache():
    try:
        return load_sy_device_context_cache()
    except Exception as exc:
        logger.error("[device_cache] load failed: %s", exc)
        return None


def refresh_device_context_cache():
    global device_context_map
    last_hash = None
    while RUNNING:
        snapshot = load_device_context_cache()
        if snapshot is not None:
            new_hash = hash_sy_device_context_cache(snapshot)
            if new_hash != last_hash:
                device_context_map = snapshot
                last_hash = new_hash
                logger.info("[device_cache] refreshed devices=%s", len(device_context_map))
        time.sleep(get_periodic_device_cache_refresh_interval())


def ensure_group(r: redis.Redis, stream: str, group: str):
    try:
        r.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
        logger.info("[redis] xgroup_create stream=%s group=%s", stream, group)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def hex_to_bytes(hex_str: str) -> bytes:
    normalized = (hex_str or "").strip()
    if normalized.startswith(("0x", "0X")):
        normalized = normalized[2:]
    normalized = normalized.replace(" ", "")
    if not normalized:
        return b""
    if len(normalized) % 2:
        normalized = normalized[:-1]
    return binascii.unhexlify(normalized)


def parse_sy_frame(frame: bytes):
    if len(frame) < 6:
        raise ValueError("frame too short")
    if not (frame[0] == 0x7F and frame[1] == 0x7F):
        raise ValueError("bad header")
    if not (frame[-2] == 0xF7 and frame[-1] == 0xF7):
        raise ValueError("bad tail")

    serial_id = frame[2]
    cmd_code = frame[3]
    payload = frame[4:-2]

    if cmd_code == 0xA1:
        cmd_name = "A1"
    elif cmd_code == 0xA2:
        cmd_name = "A2"
    elif cmd_code == 0x05:
        cmd_name = "NO_CHANGE"
    else:
        cmd_name = f"0x{cmd_code:02X}"

    return serial_id, cmd_name, payload


def normalize_stream_message(entry_id: str, fields: dict[str, str]):
    raw_payload = fields.get("data") or fields.get("json")
    if not raw_payload:
        return None, "missing_payload"

    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None, "invalid_json"

    hex_str = data.get("payload_hex") or data.get("frame_hex") or data.get("raw_hex")
    if not hex_str:
        return None, "missing_hex"

    try:
        frame_bytes = hex_to_bytes(hex_str)
    except Exception:
        return None, "invalid_hex"

    if not frame_bytes:
        return None, "empty_frame"

    nms_id = data.get("nms_id")
    if nms_id is None:
        return None, "missing_nms_id"

    try:
        nms_id = int(nms_id)
    except (TypeError, ValueError):
        return None, "invalid_nms_id"

    try:
        serial_id, cmd, payload = parse_sy_frame(frame_bytes)
    except Exception:
        return None, "invalid_frame"

    if nms_id not in device_context_map:
        return None, "unknown_device"

    msg_serial_id = data.get("serial_id")
    if msg_serial_id is not None:
        try:
            msg_serial_id = int(msg_serial_id)
        except (TypeError, ValueError):
            msg_serial_id = None

    received_at = timezone.now()
    return (
        SyFrameMessage(
            entry_id=entry_id,
            nms_id=nms_id,
            serial_id=msg_serial_id if msg_serial_id is not None else serial_id,
            line_id=str(data.get("line_id")) if data.get("line_id") is not None else None,
            port=str(data.get("port")) if data.get("port") is not None else None,
            frame_bytes=frame_bytes,
            cmd=cmd,
            payload=payload,
            received_at=received_at,
            received_monotonic=time.monotonic(),
        ),
        None,
    )


def _relay_actions_for_status_change(device_context: dict, previous_status: bytes | None, current_status: bytes):
    previous_status = previous_status or b"\x00\x00\x00\x00"
    if len(previous_status) < len(current_status):
        previous_status = previous_status.ljust(len(current_status), b"\x00")

    actions = []
    for bit_index, (direction_label, relay_type) in SY_RELAY_BITS.items():
        if direction_label == "三方向" and not device_context.get("direction3_enabled", False):
            continue

        byte_index = bit_index // 8
        bit_pos = bit_index % 8
        prev_bit = (previous_status[byte_index] >> bit_pos) & 0x01
        new_bit = (current_status[byte_index] >> bit_pos) & 0x01
        if prev_bit == new_bit:
            continue

        relay_label = f"{direction_label}{relay_type}"
        actions.append((relay_label, "吸起" if new_bit == 1 else "落下"))

    return actions


def _apply_a2_change(previous_status: bytes | None, payload: bytes):
    if len(payload) < 2:
        return None, None, None

    status = bytearray(previous_status or b"\x00\x00\x00\x00")
    if len(status) < 4:
        status.extend(b"\x00" * (4 - len(status)))

    s_byte = payload[-2]
    bit_index_all = s_byte & 0x7F
    new_value = (s_byte >> 7) & 0x01

    byte_index = bit_index_all // 8
    bit_pos = bit_index_all % 8
    if byte_index < 0 or byte_index >= len(status):
        return None, None, None

    bit_mask = 1 << bit_pos
    current_bit = (status[byte_index] >> bit_pos) & 0x01
    if current_bit == new_value:
        return bytes(status), byte_index * 8 + bit_pos, False

    if new_value == 1:
        status[byte_index] |= bit_mask
    else:
        status[byte_index] &= ~bit_mask & 0xFF

    return bytes(status), byte_index * 8 + bit_pos, True


def _hydrate_switch_status_from_db(device_ids):
    hydrated = {}
    if not device_ids:
        return hydrated

    rows = (
        SwitchData.objects.filter(device_id__in=device_ids)
        .order_by("device_id", "-timestamp")
        .values_list("device_id", "switch_status")
    )
    for device_id, raw_status in rows:
        if device_id in hydrated:
            continue
        status_bytes = _coerce_bytes(raw_status)
        if status_bytes is not None:
            hydrated[device_id] = status_bytes
    return hydrated


def ensure_local_device_state(device_ids: list[int]):
    missing_switch = [device_id for device_id in device_ids if device_id not in worker_state["loaded_switch"]]
    missing_a1 = [device_id for device_id in device_ids if device_id not in worker_state["loaded_a1"]]

    cache_keys = []
    for device_id in missing_switch:
        cache_keys.append(_switch_status_key(device_id))
    cache_snapshot = cache.get_many(cache_keys) if cache_keys else {}

    for device_id in missing_switch:
        worker_state["switch_status_by_device"][device_id] = _coerce_bytes(cache_snapshot.get(_switch_status_key(device_id)))
        worker_state["loaded_switch"].add(device_id)

    unresolved_switch_ids = [
        device_id
        for device_id in missing_switch
        if worker_state["switch_status_by_device"].get(device_id) is None
    ]
    if unresolved_switch_ids:
        hydrated = _hydrate_switch_status_from_db(unresolved_switch_ids)
        for device_id, status_bytes in hydrated.items():
            worker_state["switch_status_by_device"][device_id] = status_bytes

    if missing_a1:
        a1_keys = []
        for device_id in missing_a1:
            a1_keys.append(_last_a1_bytes_key(device_id))
            a1_keys.append(_last_a1_log_ts_key(device_id))
        a1_values = redis_client2.mget(a1_keys)
        for idx, device_id in enumerate(missing_a1):
            last_bytes = a1_values[idx * 2] if idx * 2 < len(a1_values) else None
            last_log_ts_raw = a1_values[idx * 2 + 1] if idx * 2 + 1 < len(a1_values) else None
            worker_state["last_a1_by_device"][device_id] = {
                "last_bytes": last_bytes,
                "last_log_ts": _parse_iso(last_log_ts_raw),
            }
            worker_state["loaded_a1"].add(device_id)


def process_message_batch(messages: list[SyFrameMessage]):
    global last_packet_monotonic

    metrics = {
        "received": len(messages),
        "valid": 0,
        "acked": 0,
        "switch_rows": 0,
        "change_rows": 0,
        "relay_rows": 0,
        "raw_rows": 0,
        "dedup": 0,
        "hb_devices": 0,
        "db_ms": 0.0,
    }
    if not messages:
        return metrics

    unique_device_ids = list(dict.fromkeys(msg.nms_id for msg in messages))
    ensure_local_device_state(unique_device_ids)

    latest_hb_by_device = {}
    for msg in messages:
        latest_hb_by_device[msg.nms_id] = msg

    hb_pipe = redis_client2.pipeline(transaction=False)
    for msg in latest_hb_by_device.values():
        hb_pipe.set(_last_comm_time_key(msg.nms_id), msg.received_at.isoformat(), ex=LAST_COMMUNICATION_TIME_TIMEOUT)
        hb_pipe.set(
            _last_comm_monotonic_key(msg.nms_id),
            str(msg.received_monotonic),
            ex=LAST_COMMUNICATION_TIME_TIMEOUT,
        )
    hb_pipe.execute()
    metrics["hb_devices"] = len(latest_hb_by_device)
    last_packet_monotonic = max(last_packet_monotonic, max(msg.received_monotonic for msg in latest_hb_by_device.values()))

    switch_status_state = worker_state["switch_status_by_device"]
    a1_state = worker_state["last_a1_by_device"]

    switch_rows = []
    change_rows = []
    relay_rows = []
    raw_rows = []
    cache_updates = {}
    dedup_pipe = redis_client2.pipeline(transaction=False)

    for msg in messages:
        metrics["valid"] += 1

        if SY_LOG_RAW_FRAMES and msg.cmd != "NO_CHANGE":
            raw_rows.append(
                (
                    uuid.uuid4(),
                    msg.nms_id,
                    msg.frame_bytes,
                    msg.cmd,
                    f"serial_id={msg.serial_id}; line_id={msg.line_id}; port={msg.port}",
                    msg.received_at,
                )
            )

        if msg.cmd == "NO_CHANGE":
            continue

        device_context = device_context_map[msg.nms_id]
        previous_status = switch_status_state.get(msg.nms_id)
        next_status = None

        if msg.cmd == "A1":
            status_bytes = bytes(msg.payload[:4])
            if not status_bytes:
                continue

            cached_a1 = a1_state.setdefault(msg.nms_id, {"last_bytes": None, "last_log_ts": None})
            current_hex = status_bytes.hex()
            changed = cached_a1["last_bytes"] != current_hex
            needs_heartbeat_row = False
            if not changed:
                last_log_ts = cached_a1["last_log_ts"]
                if last_log_ts is None or msg.received_at - last_log_ts >= timedelta(seconds=A1_HEARTBEAT_SECONDS):
                    needs_heartbeat_row = True

            if not changed and not needs_heartbeat_row:
                metrics["dedup"] += 1
                if previous_status != status_bytes:
                    switch_status_state[msg.nms_id] = status_bytes
                    switch_status_state[msg.nms_id] = status_bytes
                    cache_updates[_switch_status_key(msg.nms_id)] = status_bytes
                    cache_updates[_switch_status_updated_at_key(msg.nms_id)] = msg.received_at.isoformat()
                    cache_updates[_switch_status_version_key(msg.nms_id)] = SWITCH_STATUS_VERSION_DEFAULT
                dedup_pipe.set(_last_a1_bytes_key(msg.nms_id), current_hex)
                continue

            next_status = status_bytes
            cached_a1["last_bytes"] = current_hex
            cached_a1["last_log_ts"] = msg.received_at
            dedup_pipe.set(_last_a1_bytes_key(msg.nms_id), current_hex)
            dedup_pipe.set(_last_a1_log_ts_key(msg.nms_id), msg.received_at.isoformat())
        elif msg.cmd == "A2":
            next_status, bit_index_flat, changed = _apply_a2_change(previous_status, msg.payload)
            if next_status is None:
                continue
            if changed:
                change_rows.append(
                    (
                        uuid.uuid4(),
                        msg.nms_id,
                        bit_index_flat,
                        ((next_status[bit_index_flat // 8] >> (bit_index_flat % 8)) & 0x01) == 1,
                        "A2",
                        msg.received_at,
                    )
                )
            else:
                metrics["dedup"] += 1
                continue
        else:
            continue

        if next_status is None:
            continue

        switch_status_state[msg.nms_id] = next_status
        switch_rows.append(
            (
                uuid.uuid4(),
                msg.nms_id,
                next_status,
                SWITCH_STATUS_VERSION_DEFAULT,
                msg.received_at,
            )
        )

        for relay_label, action_label in _relay_actions_for_status_change(device_context, previous_status, next_status):
            relay_rows.append((uuid.uuid4(), msg.nms_id, relay_label, action_label, msg.received_at))

        cache_updates[_switch_status_key(msg.nms_id)] = next_status
        cache_updates[_switch_status_updated_at_key(msg.nms_id)] = msg.received_at.isoformat()
        cache_updates[_switch_status_version_key(msg.nms_id)] = SWITCH_STATUS_VERSION_DEFAULT

    db_begin = time.monotonic()
    with transaction.atomic():
        with connection.cursor() as cursor:
            if switch_rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {SWITCH_TABLE} (id, device_id, switch_status, version, timestamp) VALUES %s",
                    switch_rows,
                    page_size=SQL_INSERT_PAGE_SIZE,
                )
            if change_rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {CHANGE_TABLE} (id, device_id, bit_index, value, source, timestamp) VALUES %s",
                    change_rows,
                    page_size=SQL_INSERT_PAGE_SIZE,
                )
            if relay_rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {RELAY_TABLE} (id, device_id, relay, action, timestamp) VALUES %s",
                    relay_rows,
                    page_size=SQL_INSERT_PAGE_SIZE,
                )
            if raw_rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {RAW_FRAME_TABLE} (id, device_id, raw_frame, cmd, note, timestamp) VALUES %s",
                    raw_rows,
                    page_size=min(SQL_INSERT_PAGE_SIZE, 500),
                )
    metrics["db_ms"] = (time.monotonic() - db_begin) * 1000

    if cache_updates:
        cache.set_many(cache_updates, timeout=None)
    dedup_pipe.execute()

    metrics["switch_rows"] = len(switch_rows)
    metrics["change_rows"] = len(change_rows)
    metrics["relay_rows"] = len(relay_rows)
    metrics["raw_rows"] = len(raw_rows)
    return metrics


def _read_stream_entries(stream_id: str, count: int, block_ms: int):
    response = redis_stream.xreadgroup(
        groupname=SY_RAW_GROUP,
        consumername=SY_RAW_CONSUMER,
        streams={SY_RAW_STREAM: stream_id},
        count=count,
        block=block_ms,
    )
    if not response:
        return []
    entries = []
    for _stream_name, rows in response:
        entries.extend(rows)
    return entries


def _get_pending_count() -> int:
    try:
        pending = redis_stream.xpending(SY_RAW_STREAM, SY_RAW_GROUP)
        if isinstance(pending, dict):
            return int(pending.get("pending", 0))
        if isinstance(pending, (list, tuple)) and pending:
            return int(pending[0])
    except Exception:
        return -1
    return -1


def sy_stream_listener():
    batch_entries = []
    batch_entry_ids: set[str] = set()
    batch_start = 0.0
    stats = {
        "received": 0,
        "invalid": 0,
        "valid": 0,
        "acked": 0,
        "switch_rows": 0,
        "change_rows": 0,
        "relay_rows": 0,
        "raw_rows": 0,
        "dedup": 0,
        "hb_devices": 0,
        "db_ms": 0.0,
    }
    last_log_time = time.monotonic()

    while RUNNING:
        if not batch_entries:
            batch_start = time.monotonic()

        remaining = max(1, INGEST_MAX_BATCH - len(batch_entries))
        elapsed_ms = int((time.monotonic() - batch_start) * 1000)
        window_left_ms = max(1, INGEST_BATCH_MS - elapsed_ms)
        pending_entries = []

        if not batch_entries:
            try:
                pending_entries = _read_stream_entries("0", min(remaining, SY_RAW_READ_COUNT), 1)
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    ensure_group(redis_stream, SY_RAW_STREAM, SY_RAW_GROUP)
                    continue
                logger.error("[stream] read pending failed: %s", exc)
                time.sleep(0.2)
                continue

        if pending_entries:
            for entry_id, fields in pending_entries:
                if entry_id in batch_entry_ids:
                    continue
                batch_entries.append((entry_id, fields))
                batch_entry_ids.add(entry_id)

        if not pending_entries:
            try:
                new_entries = _read_stream_entries(">", min(remaining, SY_RAW_READ_COUNT), min(SY_RAW_BLOCK_MS, window_left_ms))
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    ensure_group(redis_stream, SY_RAW_STREAM, SY_RAW_GROUP)
                    continue
                logger.error("[stream] read new failed: %s", exc)
                time.sleep(0.2)
                continue
            if new_entries:
                for entry_id, fields in new_entries:
                    if entry_id in batch_entry_ids:
                        continue
                    batch_entries.append((entry_id, fields))
                    batch_entry_ids.add(entry_id)

        if not batch_entries:
            now = time.monotonic()
            if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
                pending = _get_pending_count()
                logger.info(
                    "[ingest] recv=0 valid=0 invalid=0 dedup=0 switch=0 change=0 relay=0 acked=0 db_ms=0.0 pending=%s",
                    pending,
                )
                last_log_time = now
            continue

        batch_due = (time.monotonic() - batch_start) * 1000 >= INGEST_BATCH_MS
        batch_full = len(batch_entries) >= INGEST_MAX_BATCH
        if not batch_due and not batch_full:
            continue

        valid_messages = []
        valid_entry_ids = []
        invalid_entry_ids = []

        for entry_id, fields in batch_entries:
            message, marker = normalize_stream_message(entry_id, fields)
            if marker is not None:
                invalid_entry_ids.append(entry_id)
                stats["invalid"] += 1
                continue
            valid_messages.append(message)
            valid_entry_ids.append(entry_id)

        stats["received"] += len(batch_entries)
        stats["valid"] += len(valid_messages)

        if invalid_entry_ids:
            redis_stream.xack(SY_RAW_STREAM, SY_RAW_GROUP, *invalid_entry_ids)
            stats["acked"] += len(invalid_entry_ids)

        if valid_messages:
            try:
                metrics = process_message_batch(valid_messages)
                redis_stream.xack(SY_RAW_STREAM, SY_RAW_GROUP, *valid_entry_ids)
                stats["acked"] += len(valid_entry_ids)
                stats["switch_rows"] += metrics["switch_rows"]
                stats["change_rows"] += metrics["change_rows"]
                stats["relay_rows"] += metrics["relay_rows"]
                stats["raw_rows"] += metrics["raw_rows"]
                stats["dedup"] += metrics["dedup"]
                stats["hb_devices"] += metrics["hb_devices"]
                stats["db_ms"] += metrics["db_ms"]
            except Exception as exc:
                logger.error("[ingest] batch failed, messages kept pending: %s", exc, exc_info=True)
                time.sleep(0.2)

        batch_entries = []
        batch_entry_ids.clear()

        now = time.monotonic()
        if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
            pending = _get_pending_count()
            logger.info(
                "[ingest] recv=%s valid=%s invalid=%s dedup=%s switch=%s change=%s relay=%s acked=%s db_ms=%.1f pending=%s",
                stats["received"],
                stats["valid"],
                stats["invalid"],
                stats["dedup"],
                stats["switch_rows"],
                stats["change_rows"],
                stats["relay_rows"],
                stats["acked"],
                stats["db_ms"],
                pending,
            )
            for key in stats:
                stats[key] = 0
            last_log_time = now


def handle_sigterm(_sig, _frame):
    global RUNNING
    RUNNING = False
    logger.info("[sy_receiver] shutting down")


def main():
    global device_context_map

    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)

    device_context_map = load_device_context_cache() or {}
    logger.info("[device_cache] initial devices=%s", len(device_context_map))

    ensure_group(redis_stream, SY_RAW_STREAM, SY_RAW_GROUP)

    import threading

    threading.Thread(target=refresh_device_context_cache, daemon=True).start()
    threading.Thread(target=sy_stream_listener, daemon=True).start()

    logger.info(
        "[sy_receiver] start stream=%s group=%s consumer=%s batch_ms=%s batch_max=%s read_count=%s raw_log=%s",
        SY_RAW_STREAM,
        SY_RAW_GROUP,
        SY_RAW_CONSUMER,
        INGEST_BATCH_MS,
        INGEST_MAX_BATCH,
        SY_RAW_READ_COUNT,
        SY_LOG_RAW_FRAMES,
    )

    while RUNNING:
        time.sleep(1)
        if time.monotonic() - last_packet_monotonic > get_heartbeat_timeout():
            logger.error("[sy_receiver] heartbeat timeout, stopping")
            break


if __name__ == "__main__":
    main()
