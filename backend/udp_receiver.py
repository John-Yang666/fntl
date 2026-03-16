from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone

import redis

# 添加 Django 项目路径
sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa

django.setup()  # noqa

from django.core.cache import cache  # noqa: E402
from django.db import transaction  # noqa: E402

from myapp.models import AnalogData, Device, RelayAction, SwitchData  # noqa: E402
from consts import (  # noqa: E402
    ALARM_CODES,
    HEARTBEAT_TIMEOUT,
    LAST_COMMUNICATION_TIME_TIMEOUT,
    PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
    SWITCH_DATA_TIMEOUT,
)


# 日志设置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

# ============================
# 业务 Redis（db1/db2）
# ============================
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=False)
redis_client2 = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)

# ============================
# Redis Streams
# ============================
REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_PACKET_STREAM_KEY = os.getenv("REDIS_PACKET_STREAM_KEY", "stream:udp:packets")
REDIS_PACKET_GROUP = os.getenv("REDIS_PACKET_GROUP", "udp-receiver-packet")
REDIS_PACKET_CONSUMER = os.getenv("REDIS_PACKET_CONSUMER", "udp-receiver-packet-0")
REDIS_STREAM_BLOCK_MS = int(os.getenv("REDIS_STREAM_BLOCK_MS", "2000"))
REDIS_STREAM_COUNT = int(os.getenv("REDIS_STREAM_COUNT", "500"))

# ============================
# 批处理配置
# ============================
INGEST_BATCH_MS = int(os.getenv("INGEST_BATCH_MS", "200"))
INGEST_MAX_BATCH = int(os.getenv("INGEST_MAX_BATCH", "500"))
INGEST_LOG_INTERVAL_SEC = int(os.getenv("INGEST_LOG_INTERVAL_SEC", "1"))


RELAY_MAPPING = (
    ("一方向本站QHJ", 7, 0),
    ("一方向邻站QHJ", 9, 0),
    ("二方向本站QHJ", 11, 0),
    ("二方向邻站QHJ", 13, 0),
    ("一方向本站ZDJ(A系)", 14, 0),
    ("一方向本站FDJ(A系)", 14, 2),
    ("一方向本站ZXJ(A系)", 14, 4),
    ("一方向本站FXJ(A系)", 14, 6),
    ("一方向邻站ZDJ(A系)", 22, 0),
    ("一方向邻站FDJ(A系)", 22, 2),
    ("一方向邻站ZXJ(A系)", 22, 4),
    ("一方向邻站FXJ(A系)", 22, 6),
    ("二方向本站ZDJ(A系)", 32, 0),
    ("二方向本站FDJ(A系)", 32, 2),
    ("二方向本站ZXJ(A系)", 32, 4),
    ("二方向本站FXJ(A系)", 32, 6),
    ("二方向邻站ZDJ(A系)", 40, 0),
    ("二方向邻站FDJ(A系)", 40, 2),
    ("二方向邻站ZXJ(A系)", 40, 4),
    ("二方向邻站FXJ(A系)", 40, 6),
    ("一方向本站ZDJ(B系)", 23, 0),
    ("一方向本站FDJ(B系)", 23, 2),
    ("一方向本站ZXJ(B系)", 23, 4),
    ("一方向本站FXJ(B系)", 23, 6),
    ("一方向邻站ZDJ(B系)", 31, 0),
    ("一方向邻站FDJ(B系)", 31, 2),
    ("一方向邻站ZXJ(B系)", 31, 4),
    ("一方向邻站FXJ(B系)", 31, 6),
    ("二方向本站ZDJ(B系)", 41, 0),
    ("二方向本站FDJ(B系)", 41, 2),
    ("二方向本站ZXJ(B系)", 41, 4),
    ("二方向本站FXJ(B系)", 41, 6),
    ("二方向邻站ZDJ(B系)", 49, 0),
    ("二方向邻站FDJ(B系)", 49, 2),
    ("二方向邻站ZXJ(B系)", 49, 4),
    ("二方向邻站FXJ(B系)", 49, 6),
)


@dataclass
class PacketMessage:
    entry_id: bytes | None
    ip_address: str
    data: bytes
    length: int
    device_id: int
    received_at: datetime
    received_monotonic: float


packet_count = 0
packet_count_lock = threading.Lock()
last_packet_monotonic = time.monotonic()
should_exit = threading.Event()

# 设备缓存（由刷新线程原子替换）
device_ip_map: dict[str, int] = {}
device_id_set: set[int] = set()
device_alarm_filters: dict[int, set[int]] = {}


def load_device_cache():
    try:
        ip_map: dict[str, int] = {}
        id_set: set[int] = set()
        alarm_filter_map: dict[int, set[int]] = {}
        for device in Device.objects.all().only("ip_address", "device_id", "alarm_filters"):
            ip_map[device.ip_address] = device.device_id
            id_set.add(device.device_id)
            alarm_filter_map[device.device_id] = set(device.alarm_filters or [])
        return ip_map, id_set, alarm_filter_map
    except Exception as exc:
        logger.error("Failed to load device info from DB: %s", exc)
        return None


def apply_device_cache(cache_snapshot):
    global device_ip_map, device_id_set, device_alarm_filters
    if cache_snapshot is None:
        return False

    ip_map, id_set, alarm_filter_map = cache_snapshot
    device_ip_map = ip_map
    device_id_set = id_set
    device_alarm_filters = alarm_filter_map
    return True


def periodic_device_cache_refresher(interval=PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL):
    last_hash = None
    while not should_exit.is_set():
        cache_snapshot = load_device_cache()
        if cache_snapshot is None:
            logger.warning("[device_cache] refresh skipped due to DB read failure, keep previous snapshot")
            if should_exit.wait(interval):
                break
            continue

        ip_map, id_set, alarm_filter_map = cache_snapshot
        new_hash = hash((frozenset(ip_map.items()), frozenset((k, tuple(sorted(v))) for k, v in alarm_filter_map.items())))
        if new_hash != last_hash:
            apply_device_cache(cache_snapshot)
            last_hash = new_hash
            logger.info("[device_cache] refreshed devices=%s", len(device_id_set))

        if should_exit.wait(interval):
            break


def get_pending_count(stream_redis: redis.Redis) -> int:
    try:
        pending = stream_redis.xpending(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
        if isinstance(pending, dict):
            return int(pending.get("pending", 0))
        if isinstance(pending, (list, tuple)) and pending:
            return int(pending[0])
    except Exception:
        return -1
    return -1


def _get_switch_bit_value(switch_status: bytes, byte_index: int, bit_index: int) -> int:
    idx = byte_index - 4
    if idx < 0 or idx >= len(switch_status):
        return 0
    byte_value = switch_status[idx]
    return (byte_value >> bit_index) & 1


def _compute_alarm_bit(alarm_code: int, switch_status: bytes) -> int:
    if alarm_code == 70:
        bit_value_0_self = _get_switch_bit_value(switch_status, 7, 0)
        bit_value_0_neighbor = _get_switch_bit_value(switch_status, 9, 0)
        return 0 if bit_value_0_self == bit_value_0_neighbor else 1

    if alarm_code == 72:
        bit_value_2_self = _get_switch_bit_value(switch_status, 7, 2)
        bit_value_3_self = _get_switch_bit_value(switch_status, 7, 3)
        bit_value_2_neighbor = _get_switch_bit_value(switch_status, 9, 2)
        bit_value_3_neighbor = _get_switch_bit_value(switch_status, 9, 3)
        if bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0:
            return 0
        if (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):
            return 0
        return 0 if (bit_value_2_self == bit_value_2_neighbor and bit_value_3_self == bit_value_3_neighbor) else 1

    if alarm_code == 110:
        bit_value_0_self = _get_switch_bit_value(switch_status, 11, 0)
        bit_value_0_neighbor = _get_switch_bit_value(switch_status, 13, 0)
        return 0 if bit_value_0_self == bit_value_0_neighbor else 1

    if alarm_code == 112:
        bit_value_2_self = _get_switch_bit_value(switch_status, 11, 2)
        bit_value_3_self = _get_switch_bit_value(switch_status, 11, 3)
        bit_value_2_neighbor = _get_switch_bit_value(switch_status, 13, 2)
        bit_value_3_neighbor = _get_switch_bit_value(switch_status, 13, 3)
        if bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0:
            return 0
        if (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):
            return 0
        return 0 if (bit_value_2_self == bit_value_2_neighbor and bit_value_3_self == bit_value_3_neighbor) else 1

    if alarm_code in {190, 280, 370, 460}:
        bit_value_0 = _get_switch_bit_value(switch_status, alarm_code // 10, 0)
        bit_value_3 = _get_switch_bit_value(switch_status, alarm_code // 10, 3)
        return bit_value_0 & bit_value_3

    return _get_switch_bit_value(switch_status, alarm_code // 10, alarm_code % 10)


def _build_alarms_state(
    device_id: int,
    switch_status: bytes,
    previous_alarms: dict,
    now_time: datetime,
    now_monotonic: float,
) -> dict:
    alarm_filters = device_alarm_filters.get(device_id, set())
    alarms_state = {}

    for alarm_code in ALARM_CODES:
        if alarm_code in alarm_filters:
            alarms_state[alarm_code] = {"bit_value": 0}
            continue

        bit_value = _compute_alarm_bit(alarm_code, switch_status)
        if bit_value == 1:
            prev_state = previous_alarms.get(alarm_code, {}) if isinstance(previous_alarms, dict) else {}
            start = prev_state.get("starttime", now_time)
            start_monotonic = prev_state.get("start_monotonic", now_monotonic)
            alarms_state[alarm_code] = {
                "bit_value": 1,
                "starttime": start,
                "start_monotonic": start_monotonic,
            }
        else:
            alarms_state[alarm_code] = {"bit_value": 0}

    return alarms_state


def _extract_relay_actions(previous_status: dict, switch_status: bytes, current_time: datetime):
    current_status = {}
    actions = []

    for relay_name, byte_index, bit_index in RELAY_MAPPING:
        bit_value = _get_switch_bit_value(switch_status, byte_index, bit_index)
        current_status[relay_name] = bit_value
        if previous_status and previous_status.get(relay_name) != bit_value:
            actions.append((relay_name, "吸起" if bit_value == 1 else "落下", current_time))

    return current_status, actions


def _parse_analog_payload(payload: bytes):
    if len(payload) < 12:
        return None

    voltage_1 = int.from_bytes(payload[4:6], byteorder="big", signed=True) / 100.0
    current_1 = int.from_bytes(payload[6:8], byteorder="big", signed=True) / 100.0
    voltage_2 = int.from_bytes(payload[8:10], byteorder="big", signed=True) / 100.0
    current_2 = int.from_bytes(payload[10:12], byteorder="big", signed=True) / 100.0

    voltage_threshold = 500
    if abs(voltage_1) > voltage_threshold and abs(voltage_2) > voltage_threshold:
        return None

    if abs(voltage_1) > voltage_threshold:
        voltage_1 = 0
    if abs(voltage_2) > voltage_threshold:
        voltage_2 = 0

    if abs(voltage_1) <= 1 and abs(voltage_2) <= 1:
        return None

    payload_json = json.dumps(
        {
            "voltage_1": voltage_1,
            "current_1": current_1,
            "voltage_2": voltage_2,
            "current_2": current_2,
        }
    )

    return voltage_1, current_1, voltage_2, current_2, payload_json


def _resolve_device_id(ip_address: str, data: bytes) -> int | None:
    try:
        device_id = int.from_bytes(data[2:3], byteorder="big")
    except Exception:
        return None

    if device_id in (0, 1):
        return device_ip_map.get(ip_address)

    return device_id if device_id in device_id_set else None


def parse_stream_entry(entry_id: bytes, fields: dict[bytes, bytes]):
    msg_type = fields.get(b"type")
    if msg_type is not None and msg_type != b"packet":
        return None, "skip"

    ip_b = fields.get(b"ip", b"")
    data_hex_b = fields.get(b"data_hex", b"")
    if not ip_b or not data_hex_b:
        return None, "invalid_missing"

    ip_address = ip_b.decode(errors="ignore").strip()
    raw_hex = data_hex_b.decode(errors="ignore").strip()
    if not ip_address or not raw_hex:
        return None, "invalid_missing"

    try:
        data = bytes.fromhex(raw_hex)
    except Exception:
        return None, "invalid_hex"

    if len(data) < 4:
        return None, "invalid_short"

    if not (data[0:2] == b"\x7F\x7F" and data[-2:] == b"\xF7\xF7"):
        return None, "invalid_frame"

    device_id = _resolve_device_id(ip_address, data)
    if not device_id:
        return None, "invalid_device"

    now_time = datetime.now(dt_timezone.utc)
    now_monotonic = time.monotonic()
    return (
        PacketMessage(
            entry_id=entry_id,
            ip_address=ip_address,
            data=data,
            length=len(data),
            device_id=device_id,
            received_at=now_time,
            received_monotonic=now_monotonic,
        ),
        None,
    )


def process_packet_batch(messages: list[PacketMessage]):
    global last_packet_monotonic

    metrics = {
        "received": len(messages),
        "dedup": 0,
        "switch_rows": 0,
        "analog_rows": 0,
        "relay_rows": 0,
        "hb_devices": 0,
        "db_ms": 0.0,
    }

    if not messages:
        return metrics

    # 1) 心跳更新时间（按设备合并写入，减少 Redis 写放大）
    latest_hb_by_device: dict[int, PacketMessage] = {}
    for msg in messages:
        latest_hb_by_device[msg.device_id] = msg

    hb_pipe = redis_client2.pipeline(transaction=False)
    for msg in latest_hb_by_device.values():
        hb_pipe.set(
            f"device_{msg.device_id}_last_communication_time",
            msg.received_at.isoformat(),
            ex=LAST_COMMUNICATION_TIME_TIMEOUT,
        )
        hb_pipe.set(
            f"device_{msg.device_id}_last_communication_monotonic",
            str(msg.received_monotonic),
            ex=LAST_COMMUNICATION_TIME_TIMEOUT,
        )
    hb_pipe.execute()
    metrics["hb_devices"] = len(latest_hb_by_device)

    # 更新全局心跳监控时间
    last_packet_monotonic = max(last_packet_monotonic, max(msg.received_monotonic for msg in latest_hb_by_device.values()))

    # 2) 原始包去重（按设备顺序比较上一帧）
    unique_device_ids = list(dict.fromkeys(msg.device_id for msg in messages))
    raw_keys = [f"device:{device_id}:last_raw" for device_id in unique_device_ids]
    previous_values = redis_client.mget(raw_keys)
    previous_by_device = dict(zip(unique_device_ids, previous_values))

    seen_raw_by_device = dict(previous_by_device)
    non_dedup_messages: list[PacketMessage] = []

    last_raw_updates: dict[int, tuple[bytes, int, bool]] = {}
    for msg in messages:
        current_prev = seen_raw_by_device.get(msg.device_id)
        if current_prev is not None and current_prev == msg.data:
            metrics["dedup"] += 1
            continue

        seen_raw_by_device[msg.device_id] = msg.data
        non_dedup_messages.append(msg)

        if msg.length == 54:
            ttl = SWITCH_DATA_TIMEOUT
        elif msg.length == 20:
            ttl = HEARTBEAT_TIMEOUT
        else:
            ttl = max(SWITCH_DATA_TIMEOUT, HEARTBEAT_TIMEOUT)

        last_raw_updates[msg.device_id] = (msg.data, ttl, msg.length == 54)

    if last_raw_updates:
        dedup_pipe = redis_client.pipeline(transaction=False)
        for device_id, (last_raw, ttl, is_switch_packet) in last_raw_updates.items():
            dedup_pipe.set(f"device:{device_id}:last_raw", last_raw, ex=ttl)
            if is_switch_packet:
                packet_hash = hashlib.sha256(last_raw).hexdigest().encode()
                dedup_pipe.set(f"device_{device_id}_last_switch_packet_hash", packet_hash, ex=SWITCH_DATA_TIMEOUT)
        dedup_pipe.execute()

    if not non_dedup_messages:
        return metrics

    switch_device_ids = list(dict.fromkeys(msg.device_id for msg in non_dedup_messages if msg.length == 54))
    prefetch_keys = []
    for device_id in switch_device_ids:
        prefetch_keys.extend(
            [
                f"device_{device_id}_switch_status",
                f"device_{device_id}_alarms",
                f"device_{device_id}_relay_status",
            ]
        )
    cache_prefetched = cache.get_many(prefetch_keys) if prefetch_keys else {}

    switch_status_state = {
        device_id: cache_prefetched.get(f"device_{device_id}_switch_status") for device_id in switch_device_ids
    }
    alarms_state_cache = {
        device_id: cache_prefetched.get(f"device_{device_id}_alarms", {}) or {} for device_id in switch_device_ids
    }
    relay_status_cache = {
        device_id: cache_prefetched.get(f"device_{device_id}_relay_status", {}) or {} for device_id in switch_device_ids
    }

    cache_updates_no_ttl = {}
    cache_updates_analog = {}
    switch_rows = []
    analog_rows = []
    relay_rows = []

    for msg in non_dedup_messages:
        if msg.length == 54:
            switch_status = msg.data[4:50]
            device_id = msg.device_id
            previous_switch_status = switch_status_state.get(device_id)

            if previous_switch_status == switch_status:
                continue

            switch_status_state[device_id] = switch_status
            cache_updates_no_ttl[f"device_{device_id}_switch_status"] = switch_status

            switch_rows.append(
                SwitchData(
                    device_id=device_id,
                    switch_status=switch_status,
                    timestamp=msg.received_at,
                )
            )

            previous_alarms = alarms_state_cache.get(device_id, {})
            if not isinstance(previous_alarms, dict):
                previous_alarms = {}
            alarms_state = _build_alarms_state(
                device_id=device_id,
                switch_status=switch_status,
                previous_alarms=previous_alarms,
                now_time=msg.received_at,
                now_monotonic=msg.received_monotonic,
            )
            alarms_state_cache[device_id] = alarms_state
            cache_updates_no_ttl[f"device_{device_id}_alarms"] = alarms_state
            cache_updates_no_ttl[f"device_{device_id}_alarms_updated_at"] = msg.received_at.isoformat()

            previous_relay_status = relay_status_cache.get(device_id, {})
            if not isinstance(previous_relay_status, dict):
                previous_relay_status = {}
            current_relay_status, actions = _extract_relay_actions(previous_relay_status, switch_status, msg.received_at)
            relay_status_cache[device_id] = current_relay_status
            cache_updates_no_ttl[f"device_{device_id}_relay_status"] = current_relay_status

            for relay_name, action_name, action_time in actions:
                relay_rows.append(
                    RelayAction(
                        device_id=device_id,
                        relay=relay_name,
                        action=action_name,
                        timestamp=action_time,
                    )
                )

        elif msg.length == 20:
            analog_parsed = _parse_analog_payload(msg.data)
            if analog_parsed is None:
                continue

            voltage_1, current_1, voltage_2, current_2, analog_json = analog_parsed
            analog_rows.append(
                AnalogData(
                    device_id=msg.device_id,
                    voltage_1=voltage_1,
                    current_1=current_1,
                    voltage_2=voltage_2,
                    current_2=current_2,
                    timestamp=msg.received_at,
                )
            )
            cache_updates_analog[f"device_{msg.device_id}_analog_status"] = analog_json

    db_begin = time.monotonic()
    with transaction.atomic():
        if switch_rows:
            SwitchData.objects.bulk_create(switch_rows, batch_size=1000)
        if analog_rows:
            AnalogData.objects.bulk_create(analog_rows, batch_size=1000)
        if relay_rows:
            RelayAction.objects.bulk_create(relay_rows, batch_size=1000)
    metrics["db_ms"] = (time.monotonic() - db_begin) * 1000

    if cache_updates_no_ttl:
        cache.set_many(cache_updates_no_ttl, timeout=None)
    if cache_updates_analog:
        cache.set_many(cache_updates_analog, timeout=5)

    metrics["switch_rows"] = len(switch_rows)
    metrics["analog_rows"] = len(analog_rows)
    metrics["relay_rows"] = len(relay_rows)
    return metrics


def ensure_stream_group(r: redis.Redis, stream_key: str, group_name: str):
    try:
        r.xgroup_create(name=stream_key, groupname=group_name, id="$", mkstream=True)
        logger.info("[redis] created group=%s on stream=%s", group_name, stream_key)
    except Exception as exc:
        msg = str(exc)
        if "BUSYGROUP" in msg or "Consumer Group name already exists" in msg:
            return
        logger.warning("[redis] ensure group error: %s", exc)


def _read_stream_entries(stream_redis: redis.Redis, stream_id: bytes, count: int, block_ms: int):
    response = stream_redis.xreadgroup(
        groupname=REDIS_PACKET_GROUP,
        consumername=REDIS_PACKET_CONSUMER,
        streams={REDIS_PACKET_STREAM_KEY: stream_id},
        count=count,
        block=block_ms,
    )
    if not response:
        return []
    entries = []
    for _stream, rows in response:
        entries.extend(rows)
    return entries


def redis_packet_listener():
    stats = {
        "received": 0,
        "valid": 0,
        "invalid": 0,
        "invalid_device": 0,
        "invalid_frame": 0,
        "invalid_hex": 0,
        "invalid_missing": 0,
        "invalid_short": 0,
        "dedup": 0,
        "switch_rows": 0,
        "analog_rows": 0,
        "relay_rows": 0,
        "hb_devices": 0,
        "acked": 0,
        "batch": 0,
        "db_ms": 0.0,
    }

    last_log_time = time.monotonic()
    batch_entries: list[tuple[bytes, dict[bytes, bytes]]] = []
    batch_start = 0.0

    try:
        stream_redis = redis.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
        stream_redis.ping()
        ensure_stream_group(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)

        logger.info(
            "[redis] listening stream=%s group=%s consumer=%s batch_ms=%s batch_max=%s read_count=%s",
            REDIS_PACKET_STREAM_KEY,
            REDIS_PACKET_GROUP,
            REDIS_PACKET_CONSUMER,
            INGEST_BATCH_MS,
            INGEST_MAX_BATCH,
            REDIS_STREAM_COUNT,
        )

        while not should_exit.is_set():
            if not batch_entries:
                batch_start = time.monotonic()

            remaining = max(1, INGEST_MAX_BATCH - len(batch_entries))
            elapsed_ms = int((time.monotonic() - batch_start) * 1000)
            window_left_ms = max(1, INGEST_BATCH_MS - elapsed_ms)

            # 先尝试消费 pending，保证失败后可恢复处理
            try:
                pending_entries = _read_stream_entries(stream_redis, b"0", remaining, 1)
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    logger.warning("[redis] NOGROUP while reading pending, recreate and retry")
                    ensure_stream_group(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
                    continue
                logger.error("[redis] read pending error: %s", exc)
                time.sleep(0.2)
                continue

            if pending_entries:
                batch_entries.extend(pending_entries)
            else:
                block_ms = min(REDIS_STREAM_BLOCK_MS, window_left_ms if batch_entries else REDIS_STREAM_BLOCK_MS)
                try:
                    new_entries = _read_stream_entries(stream_redis, b">", remaining, block_ms)
                except Exception as exc:
                    if "NOGROUP" in str(exc):
                        logger.warning("[redis] NOGROUP while reading new, recreate and retry")
                        ensure_stream_group(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
                        continue
                    logger.error("[redis] read new error: %s", exc)
                    time.sleep(0.2)
                    continue
                if new_entries:
                    batch_entries.extend(new_entries)

            if not batch_entries:
                now = time.monotonic()
                if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
                    pending_count = get_pending_count(stream_redis)
                    logger.info("[ingest] recv=0 valid=0 dedup=0 switch=0 analog=0 relay=0 pending=%s", pending_count)
                    last_log_time = now
                continue

            batch_due = (time.monotonic() - batch_start) * 1000 >= INGEST_BATCH_MS
            batch_full = len(batch_entries) >= INGEST_MAX_BATCH
            if not batch_due and not batch_full:
                continue

            valid_messages: list[PacketMessage] = []
            valid_entry_ids: list[bytes] = []
            invalid_entry_ids: list[bytes] = []

            for entry_id, fields in batch_entries:
                packet_msg, marker = parse_stream_entry(entry_id, fields)
                if marker in {"skip", "invalid_missing", "invalid_hex", "invalid_short", "invalid_frame", "invalid_device"}:
                    invalid_entry_ids.append(entry_id)
                    stats["invalid"] += 1
                    if marker == "invalid_device":
                        stats["invalid_device"] += 1
                    elif marker == "invalid_frame":
                        stats["invalid_frame"] += 1
                    elif marker == "invalid_hex":
                        stats["invalid_hex"] += 1
                    elif marker == "invalid_missing":
                        stats["invalid_missing"] += 1
                    elif marker == "invalid_short":
                        stats["invalid_short"] += 1
                    continue
                valid_messages.append(packet_msg)
                valid_entry_ids.append(entry_id)

            stats["received"] += len(batch_entries)
            stats["valid"] += len(valid_messages)

            if invalid_entry_ids:
                try:
                    stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, *invalid_entry_ids)
                    stats["acked"] += len(invalid_entry_ids)
                except Exception as exc:
                    logger.error("[redis] ack invalid failed: %s", exc)

            if valid_messages:
                try:
                    metrics = process_packet_batch(valid_messages)
                    stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, *valid_entry_ids)

                    stats["acked"] += len(valid_entry_ids)
                    stats["batch"] += 1
                    stats["dedup"] += metrics["dedup"]
                    stats["switch_rows"] += metrics["switch_rows"]
                    stats["analog_rows"] += metrics["analog_rows"]
                    stats["relay_rows"] += metrics["relay_rows"]
                    stats["hb_devices"] += metrics["hb_devices"]
                    stats["db_ms"] += metrics["db_ms"]

                    with packet_count_lock:
                        global packet_count
                        packet_count += len(valid_messages)
                except Exception as exc:
                    logger.error("[ingest] batch process failed, keep pending for retry: %s", exc, exc_info=True)
                    time.sleep(0.2)

            batch_entries = []

            now = time.monotonic()
            if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
                pending_count = get_pending_count(stream_redis)
                logger.info(
                    "[ingest] recv=%s valid=%s invalid=%s(dev=%s frame=%s hex=%s miss=%s short=%s) dedup=%s switch=%s analog=%s relay=%s hb_dev=%s ack=%s db_ms=%.1f pending=%s",
                    stats["received"],
                    stats["valid"],
                    stats["invalid"],
                    stats["invalid_device"],
                    stats["invalid_frame"],
                    stats["invalid_hex"],
                    stats["invalid_missing"],
                    stats["invalid_short"],
                    stats["dedup"],
                    stats["switch_rows"],
                    stats["analog_rows"],
                    stats["relay_rows"],
                    stats["hb_devices"],
                    stats["acked"],
                    stats["db_ms"],
                    pending_count,
                )
                for key in stats:
                    stats[key] = 0 if key != "db_ms" else 0.0
                last_log_time = now

    except Exception as exc:
        logger.error("[redis] packet listener fatal error: %s", exc, exc_info=True)
        should_exit.set()


def receiver():
    cache_snapshot = load_device_cache()
    if not apply_device_cache(cache_snapshot):
        logger.warning("Initial device cache preload failed, running with last known snapshot and background refresh")
    logger.info("Initial preload of %s devices", len(device_id_set))

    threading.Thread(target=periodic_device_cache_refresher, daemon=True).start()
    threading.Thread(target=redis_packet_listener, daemon=True).start()
    logger.info("Receiver backend=redis")

    while not should_exit.is_set():
        time.sleep(1)
        if time.monotonic() - last_packet_monotonic > HEARTBEAT_TIMEOUT:
            logger.error("Heartbeat timeout! Exiting UDP receiver...")
            should_exit.set()


if __name__ == "__main__":
    receiver()
