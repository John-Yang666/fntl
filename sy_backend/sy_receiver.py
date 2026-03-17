from __future__ import annotations

import binascii
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import redis

sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa: E402

django.setup()

from django.core.cache import cache  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from consts import (  # noqa: E402
    HEARTBEAT_TIMEOUT,
    LAST_COMMUNICATION_TIME_TIMEOUT,
    PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
)
from myapp.models import (  # noqa: E402
    ChangeBitEvent,
    Device,
    RawFrameLog,
    RelayAction,
    SwitchData,
)
from myapp.tasks.extract_sy_alarms_task import (  # noqa: E402
    build_sy_alarm_state,
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


def load_device_context_cache():
    try:
        rows = Device.objects.all().values(
            "device_id",
            "name",
            "alarm_filters",
            "direction1_enabled",
            "direction2_enabled",
            "direction3_enabled",
            "direction1_neighbor_id",
            "direction1_neighbor_direction",
            "direction2_neighbor_id",
            "direction2_neighbor_direction",
            "direction1_cable_alarm_linkage",
            "direction2_cable_alarm_linkage",
        )
        new_cache = {}
        for row in rows:
            new_cache[row["device_id"]] = {
                "device_id": row["device_id"],
                "name": row["name"] or "",
                "alarm_filters": set(row["alarm_filters"] or []),
                "direction1_enabled": bool(row["direction1_enabled"]),
                "direction2_enabled": bool(row["direction2_enabled"]),
                "direction3_enabled": bool(row["direction3_enabled"]),
                "direction1_neighbor_id": row["direction1_neighbor_id"] or 0,
                "direction1_neighbor_direction": row["direction1_neighbor_direction"],
                "direction2_neighbor_id": row["direction2_neighbor_id"] or 0,
                "direction2_neighbor_direction": row["direction2_neighbor_direction"],
                "direction1_cable_alarm_linkage": bool(row["direction1_cable_alarm_linkage"]),
                "direction2_cable_alarm_linkage": bool(row["direction2_cable_alarm_linkage"]),
            }
        return new_cache
    except Exception as exc:
        logger.error("[device_cache] load failed: %s", exc)
        return None


def refresh_device_context_cache():
    global device_context_map
    last_hash = None
    while RUNNING:
        snapshot = load_device_context_cache()
        if snapshot is not None:
            new_hash = hash(
                frozenset(
                    (
                        device_id,
                        row["name"],
                        tuple(sorted(row["alarm_filters"])),
                        row["direction1_enabled"],
                        row["direction2_enabled"],
                        row["direction3_enabled"],
                        row["direction1_neighbor_id"],
                        row["direction1_neighbor_direction"],
                        row["direction2_neighbor_id"],
                        row["direction2_neighbor_direction"],
                        row["direction1_cable_alarm_linkage"],
                        row["direction2_cable_alarm_linkage"],
                    )
                    for device_id, row in snapshot.items()
                )
            )
            if new_hash != last_hash:
                device_context_map = snapshot
                last_hash = new_hash
                logger.info("[device_cache] refreshed devices=%s", len(device_context_map))
        time.sleep(PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL)


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
    for device_id in device_ids:
        last_row = (
            SwitchData.objects.filter(device_id=device_id)
            .order_by("-timestamp")
            .values_list("switch_status", flat=True)
            .first()
        )
        status_bytes = _coerce_bytes(last_row)
        if status_bytes is not None:
            hydrated[device_id] = status_bytes
    return hydrated


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
    }
    if not messages:
        return metrics

    unique_device_ids = list(dict.fromkeys(msg.nms_id for msg in messages))

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

    a1_device_ids = list(dict.fromkeys(msg.nms_id for msg in messages if msg.cmd == "A1"))
    last_bytes_raw = []
    last_log_ts_raw = []
    if a1_device_ids:
        a1_keys = []
        for device_id in a1_device_ids:
            a1_keys.append(_last_a1_bytes_key(device_id))
            a1_keys.append(_last_a1_log_ts_key(device_id))
        a1_values = redis_client2.mget(a1_keys)
        last_bytes_raw = a1_values[::2]
        last_log_ts_raw = a1_values[1::2]
    a1_state = {
        device_id: {
            "last_bytes": last_bytes_raw[idx] if idx < len(last_bytes_raw) else None,
            "last_log_ts": _parse_iso(last_log_ts_raw[idx]) if idx < len(last_log_ts_raw) else None,
        }
        for idx, device_id in enumerate(a1_device_ids)
    }

    cache_keys = []
    for device_id in unique_device_ids:
        cache_keys.extend(
            [
                _switch_status_key(device_id),
                _alarm_key(device_id),
            ]
        )
    cache_snapshot = cache.get_many(cache_keys) if cache_keys else {}

    switch_status_state = {
        device_id: _coerce_bytes(cache_snapshot.get(_switch_status_key(device_id)))
        for device_id in unique_device_ids
    }
    previous_alarm_state = {
        device_id: cache_snapshot.get(_alarm_key(device_id), {}) or {}
        for device_id in unique_device_ids
    }

    missing_switch_ids = [device_id for device_id, value in switch_status_state.items() if value is None]
    if missing_switch_ids:
        switch_status_state.update(_hydrate_switch_status_from_db(missing_switch_ids))

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
                RawFrameLog(
                    device_id=msg.nms_id,
                    raw_frame=msg.frame_bytes,
                    cmd=msg.cmd,
                    note=f"serial_id={msg.serial_id}; line_id={msg.line_id}; port={msg.port}",
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
                    ChangeBitEvent(
                        device_id=msg.nms_id,
                        bit_index=bit_index_flat,
                        value=((next_status[bit_index_flat // 8] >> (bit_index_flat % 8)) & 0x01) == 1,
                        source="A2",
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
            SwitchData(
                device_id=msg.nms_id,
                switch_status=next_status,
                version=SWITCH_STATUS_VERSION_DEFAULT,
                timestamp=msg.received_at,
            )
        )

        for relay_label, action_label in _relay_actions_for_status_change(device_context, previous_status, next_status):
            relay_rows.append(
                RelayAction(
                    device_id=msg.nms_id,
                    relay=relay_label,
                    action=action_label,
                    timestamp=msg.received_at,
                )
            )

        alarms_state = build_sy_alarm_state(
            device_id=msg.nms_id,
            status_bytes=next_status,
            previous_alarms=previous_alarm_state.get(msg.nms_id, {}),
            current_time=msg.received_at,
            device_context=device_context,
        )
        if alarms_state:
            previous_alarm_state[msg.nms_id] = alarms_state
            cache_updates[_alarm_key(msg.nms_id)] = alarms_state
            cache_updates[_alarm_updated_at_key(msg.nms_id)] = msg.received_at.isoformat()

        cache_updates[_switch_status_key(msg.nms_id)] = next_status
        cache_updates[_switch_status_updated_at_key(msg.nms_id)] = msg.received_at.isoformat()
        cache_updates[_switch_status_version_key(msg.nms_id)] = SWITCH_STATUS_VERSION_DEFAULT

    with transaction.atomic():
        if switch_rows:
            SwitchData.objects.bulk_create(switch_rows, batch_size=1000)
        if change_rows:
            ChangeBitEvent.objects.bulk_create(change_rows, batch_size=1000)
        if relay_rows:
            RelayAction.objects.bulk_create(relay_rows, batch_size=1000)
        if raw_rows:
            RawFrameLog.objects.bulk_create(raw_rows, batch_size=500)

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


def sy_stream_listener():
    batch_entries = []
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
    }
    last_log_time = time.monotonic()

    while RUNNING:
        if not batch_entries:
            batch_start = time.monotonic()

        remaining = max(1, INGEST_MAX_BATCH - len(batch_entries))
        elapsed_ms = int((time.monotonic() - batch_start) * 1000)
        window_left_ms = max(1, INGEST_BATCH_MS - elapsed_ms)

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
            batch_entries.extend(pending_entries)
        else:
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
                batch_entries.extend(new_entries)

        if not batch_entries:
            now = time.monotonic()
            if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
                logger.info("[ingest] recv=0 valid=0 invalid=0 switch=0 change=0 relay=0 dedup=0")
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
            except Exception as exc:
                logger.error("[ingest] batch failed, messages kept pending: %s", exc, exc_info=True)
                time.sleep(0.2)

        batch_entries = []

        now = time.monotonic()
        if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
            logger.info(
                "[ingest] recv=%s valid=%s invalid=%s ack=%s switch=%s change=%s relay=%s raw=%s dedup=%s hb_dev=%s",
                stats["received"],
                stats["valid"],
                stats["invalid"],
                stats["acked"],
                stats["switch_rows"],
                stats["change_rows"],
                stats["relay_rows"],
                stats["raw_rows"],
                stats["dedup"],
                stats["hb_devices"],
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
        if time.monotonic() - last_packet_monotonic > HEARTBEAT_TIMEOUT:
            logger.error("[sy_receiver] heartbeat timeout, stopping")
            break


if __name__ == "__main__":
    main()
