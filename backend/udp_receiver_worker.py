from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid

import redis
from psycopg2.extras import execute_values

sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa

django.setup()  # noqa

from django.core.cache import cache  # noqa: E402
from django.db import connection, transaction  # noqa: E402

from myapp.models import AnalogData, RelayAction, SwitchData  # noqa: E402
from consts import (  # noqa: E402
    HEARTBEAT_TIMEOUT,
    LAST_COMMUNICATION_TIME_TIMEOUT,
    PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
    SWITCH_DATA_TIMEOUT,
)
from ingest_common import (  # noqa: E402
    build_alarms_state,
    ensure_stream_group,
    extract_relay_actions,
    get_pending_count,
    load_device_cache,
    parse_analog_payload,
    parse_worker_entry,
    read_stream_entries,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("udp_receiver_worker")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=False)
redis_client2 = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)

REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_PACKET_SHARD_STREAM_PREFIX = os.getenv("REDIS_PACKET_SHARD_STREAM_PREFIX", "stream:udp:packets:shard")
PACKET_SHARD_COUNT = int(os.getenv("PACKET_SHARD_COUNT", "4"))
PACKET_SHARD_INDEX = int(os.getenv("PACKET_SHARD_INDEX", "0"))
REDIS_PACKET_STREAM_KEY = os.getenv(
    "REDIS_PACKET_STREAM_KEY",
    f"{REDIS_PACKET_SHARD_STREAM_PREFIX}:{PACKET_SHARD_INDEX}",
)
REDIS_PACKET_WORKER_GROUP = os.getenv(
    "REDIS_PACKET_WORKER_GROUP",
    f"udp-receiver-packet-shard-{PACKET_SHARD_INDEX}",
)
REDIS_PACKET_CONSUMER = os.getenv(
    "REDIS_PACKET_CONSUMER",
    f"udp-receiver-packet-shard-{PACKET_SHARD_INDEX}-0",
)
REDIS_STREAM_BLOCK_MS = int(os.getenv("REDIS_STREAM_BLOCK_MS", "2000"))
REDIS_STREAM_COUNT = int(os.getenv("REDIS_STREAM_COUNT", "500"))

INGEST_BATCH_MS = int(os.getenv("INGEST_BATCH_MS", "200"))
INGEST_MAX_BATCH = int(os.getenv("INGEST_MAX_BATCH", "500"))
INGEST_LOG_INTERVAL_SEC = int(os.getenv("INGEST_LOG_INTERVAL_SEC", "1"))

should_exit = threading.Event()
device_alarm_filters: dict[int, set[int]] = {}
SQL_INSERT_PAGE_SIZE = int(os.getenv("SQL_INSERT_PAGE_SIZE", "1000"))
SWITCH_TABLE = SwitchData._meta.db_table
ANALOG_TABLE = AnalogData._meta.db_table
RELAY_TABLE = RelayAction._meta.db_table

worker_state = {
    "last_raw_by_device": {},
    "loaded_last_raw": set(),
    "switch_status_by_device": {},
    "loaded_switch": set(),
    "alarms_state_by_device": {},
    "loaded_alarms": set(),
    "relay_status_by_device": {},
    "loaded_relay": set(),
}


def apply_device_cache(snapshot) -> bool:
    global device_alarm_filters
    if snapshot is None:
        return False
    device_alarm_filters = snapshot.alarm_filter_map
    return True


def periodic_device_cache_refresher(interval=PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL):
    last_hash = None
    while not should_exit.is_set():
        snapshot = load_device_cache(logger)
        if snapshot is None:
            logger.warning("[device_cache] refresh skipped due to DB read failure, keep previous snapshot")
            if should_exit.wait(interval):
                break
            continue

        new_hash = hash(frozenset((k, tuple(sorted(v))) for k, v in snapshot.alarm_filter_map.items()))
        if new_hash != last_hash:
            apply_device_cache(snapshot)
            last_hash = new_hash
            logger.info("[device_cache] refreshed alarm_filters=%s shard=%s", len(device_alarm_filters), PACKET_SHARD_INDEX)

        if should_exit.wait(interval):
            break


def ensure_local_device_state(device_ids: list[int]):
    missing_last_raw = [device_id for device_id in device_ids if device_id not in worker_state["loaded_last_raw"]]
    if missing_last_raw:
        raw_keys = [f"device:{device_id}:last_raw" for device_id in missing_last_raw]
        for device_id, last_raw in zip(missing_last_raw, redis_client.mget(raw_keys)):
            worker_state["last_raw_by_device"][device_id] = last_raw
            worker_state["loaded_last_raw"].add(device_id)

    missing_switch = [device_id for device_id in device_ids if device_id not in worker_state["loaded_switch"]]
    missing_alarms = [device_id for device_id in device_ids if device_id not in worker_state["loaded_alarms"]]
    missing_relay = [device_id for device_id in device_ids if device_id not in worker_state["loaded_relay"]]

    prefetch_keys = []
    for device_id in missing_switch:
        prefetch_keys.append(f"device_{device_id}_switch_status")
    for device_id in missing_alarms:
        prefetch_keys.append(f"device_{device_id}_alarms")
    for device_id in missing_relay:
        prefetch_keys.append(f"device_{device_id}_relay_status")

    prefetched = cache.get_many(prefetch_keys) if prefetch_keys else {}

    for device_id in missing_switch:
        worker_state["switch_status_by_device"][device_id] = prefetched.get(f"device_{device_id}_switch_status")
        worker_state["loaded_switch"].add(device_id)
    for device_id in missing_alarms:
        worker_state["alarms_state_by_device"][device_id] = prefetched.get(f"device_{device_id}_alarms", {}) or {}
        worker_state["loaded_alarms"].add(device_id)
    for device_id in missing_relay:
        worker_state["relay_status_by_device"][device_id] = prefetched.get(f"device_{device_id}_relay_status", {}) or {}
        worker_state["loaded_relay"].add(device_id)


def process_packet_batch(messages):
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

    latest_hb_by_device = {}
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

    unique_device_ids = list(dict.fromkeys(msg.device_id for msg in messages))
    ensure_local_device_state(unique_device_ids)

    non_dedup_messages = []
    last_raw_updates = {}
    for msg in messages:
        current_prev = worker_state["last_raw_by_device"].get(msg.device_id)
        if current_prev is not None and current_prev == msg.data:
            metrics["dedup"] += 1
            continue

        worker_state["last_raw_by_device"][msg.device_id] = msg.data
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
    ensure_local_device_state(switch_device_ids)

    cache_updates_no_ttl = {}
    cache_updates_analog = {}
    switch_rows = []
    analog_rows = []
    relay_rows = []

    for msg in non_dedup_messages:
        if msg.length == 54:
            switch_status = msg.data[4:50]
            previous_switch_status = worker_state["switch_status_by_device"].get(msg.device_id)
            if previous_switch_status == switch_status:
                continue

            worker_state["switch_status_by_device"][msg.device_id] = switch_status
            cache_updates_no_ttl[f"device_{msg.device_id}_switch_status"] = switch_status

            switch_id = uuid.uuid4()
            switch_rows.append((switch_id, msg.device_id, switch_status, msg.received_at))

            previous_alarms = worker_state["alarms_state_by_device"].get(msg.device_id, {})
            if not isinstance(previous_alarms, dict):
                previous_alarms = {}
            alarms_state = build_alarms_state(
                device_id=msg.device_id,
                switch_status=switch_status,
                previous_alarms=previous_alarms,
                now_time=msg.received_at,
                now_monotonic=msg.received_monotonic,
                device_alarm_filters=device_alarm_filters,
            )
            worker_state["alarms_state_by_device"][msg.device_id] = alarms_state
            cache_updates_no_ttl[f"device_{msg.device_id}_alarms"] = alarms_state
            cache_updates_no_ttl[f"device_{msg.device_id}_alarms_updated_at"] = msg.received_at.isoformat()

            previous_relay_status = worker_state["relay_status_by_device"].get(msg.device_id, {})
            if not isinstance(previous_relay_status, dict):
                previous_relay_status = {}
            current_relay_status, actions = extract_relay_actions(previous_relay_status, switch_status, msg.received_at)
            worker_state["relay_status_by_device"][msg.device_id] = current_relay_status
            cache_updates_no_ttl[f"device_{msg.device_id}_relay_status"] = current_relay_status

            for relay_name, action_name, action_time in actions:
                relay_rows.append((uuid.uuid4(), msg.device_id, relay_name, action_name, action_time))

        elif msg.length == 20:
            analog_parsed = parse_analog_payload(msg.data)
            if analog_parsed is None:
                continue

            voltage_1, current_1, voltage_2, current_2, analog_json = analog_parsed
            analog_rows.append(
                (
                    uuid.uuid4(),
                    msg.device_id,
                    voltage_1,
                    current_1,
                    voltage_2,
                    current_2,
                    msg.received_at,
                )
            )
            cache_updates_analog[f"device_{msg.device_id}_analog_status"] = analog_json

    monitor_updates_by_device = {}
    db_begin = time.monotonic()
    with transaction.atomic():
        with connection.cursor() as cursor:
            if switch_rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {SWITCH_TABLE} (id, device_id, switch_status, timestamp) VALUES %s",
                    switch_rows,
                    page_size=SQL_INSERT_PAGE_SIZE,
                )
            if analog_rows:
                execute_values(
                    cursor,
                    (
                        f"INSERT INTO {ANALOG_TABLE} "
                        "(id, device_id, voltage_1, current_1, voltage_2, current_2, timestamp) VALUES %s"
                    ),
                    analog_rows,
                    page_size=SQL_INSERT_PAGE_SIZE,
                )
            if relay_rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {RELAY_TABLE} (id, device_id, relay, action, timestamp) VALUES %s",
                    relay_rows,
                    page_size=SQL_INSERT_PAGE_SIZE,
                )
    metrics["db_ms"] = (time.monotonic() - db_begin) * 1000

    for row_id, device_id, voltage_1, current_1, voltage_2, current_2, timestamp in analog_rows:
        payload = monitor_updates_by_device.setdefault(device_id, {"device_id": device_id, "analog": [], "relay": []})
        payload["analog"].append(
            {
                "id": str(row_id),
                "device": device_id,
                "timestamp": timestamp.isoformat(),
                "voltage_1": voltage_1,
                "current_1": current_1,
                "voltage_2": voltage_2,
                "current_2": current_2,
            }
        )

    for row_id, device_id, relay_name, action_name, timestamp in relay_rows:
        payload = monitor_updates_by_device.setdefault(device_id, {"device_id": device_id, "analog": [], "relay": []})
        payload["relay"].append(
            {
                "id": str(row_id),
                "device": device_id,
                "timestamp": timestamp.isoformat(),
                "relay": relay_name,
                "action": action_name,
            }
        )

    if cache_updates_no_ttl:
        cache.set_many(cache_updates_no_ttl, timeout=None)
    if cache_updates_analog:
        cache.set_many(cache_updates_analog, timeout=5)
    if monitor_updates_by_device:
        for device_id, payload in monitor_updates_by_device.items():
            redis_client.publish(
                f"device_monitor:{device_id}",
                json.dumps(payload, ensure_ascii=False),
            )

    metrics["switch_rows"] = len(switch_rows)
    metrics["analog_rows"] = len(analog_rows)
    metrics["relay_rows"] = len(relay_rows)
    return metrics


def receive_packets():
    stats = {
        "recv": 0,
        "valid": 0,
        "invalid": 0,
        "dedup": 0,
        "switch_rows": 0,
        "analog_rows": 0,
        "relay_rows": 0,
        "hb_devices": 0,
        "acked": 0,
        "db_ms": 0.0,
    }
    batch_entries: list[tuple[bytes, dict[bytes, bytes]]] = []
    batch_entry_ids: set[bytes] = set()
    batch_start = 0.0
    last_log_time = time.monotonic()

    stream_redis = redis.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
    stream_redis.ping()
    ensure_stream_group(logger, stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_WORKER_GROUP)

    logger.info(
        "[worker] shard=%s/%s stream=%s group=%s consumer=%s batch_ms=%s batch_max=%s",
        PACKET_SHARD_INDEX,
        PACKET_SHARD_COUNT,
        REDIS_PACKET_STREAM_KEY,
        REDIS_PACKET_WORKER_GROUP,
        REDIS_PACKET_CONSUMER,
        INGEST_BATCH_MS,
        INGEST_MAX_BATCH,
    )

    while not should_exit.is_set():
        if not batch_entries:
            batch_start = time.monotonic()

        remaining = max(1, INGEST_MAX_BATCH - len(batch_entries))
        elapsed_ms = int((time.monotonic() - batch_start) * 1000)
        window_left_ms = max(1, INGEST_BATCH_MS - elapsed_ms)
        pending_entries = []

        if not batch_entries:
            try:
                pending_entries = read_stream_entries(
                    stream_redis,
                    group_name=REDIS_PACKET_WORKER_GROUP,
                    consumer_name=REDIS_PACKET_CONSUMER,
                    stream_key=REDIS_PACKET_STREAM_KEY,
                    stream_id=b"0",
                    count=remaining,
                    block_ms=1,
                )
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    ensure_stream_group(logger, stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_WORKER_GROUP)
                    continue
                logger.error("[worker] shard=%s read pending error: %s", PACKET_SHARD_INDEX, exc)
                time.sleep(0.2)
                continue

        if pending_entries:
            for entry_id, fields in pending_entries:
                if entry_id in batch_entry_ids:
                    continue
                batch_entries.append((entry_id, fields))
                batch_entry_ids.add(entry_id)

        if not pending_entries:
            block_ms = min(REDIS_STREAM_BLOCK_MS, window_left_ms if batch_entries else REDIS_STREAM_BLOCK_MS)
            try:
                new_entries = read_stream_entries(
                    stream_redis,
                    group_name=REDIS_PACKET_WORKER_GROUP,
                    consumer_name=REDIS_PACKET_CONSUMER,
                    stream_key=REDIS_PACKET_STREAM_KEY,
                    stream_id=b">",
                    count=remaining,
                    block_ms=block_ms,
                )
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    ensure_stream_group(logger, stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_WORKER_GROUP)
                    continue
                logger.error("[worker] shard=%s read new error: %s", PACKET_SHARD_INDEX, exc)
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
                pending = get_pending_count(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_WORKER_GROUP)
                logger.info(
                    "[worker] shard=%s recv=0 valid=0 dedup=0 switch=0 analog=0 relay=0 acked=0 db_ms=0.0 pending=%s",
                    PACKET_SHARD_INDEX,
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
            packet_msg, marker = parse_worker_entry(entry_id, fields)
            if marker is not None:
                invalid_entry_ids.append(entry_id)
                stats["invalid"] += 1
                continue
            valid_messages.append(packet_msg)
            valid_entry_ids.append(entry_id)

        stats["recv"] += len(batch_entries)
        stats["valid"] += len(valid_messages)

        if invalid_entry_ids:
            try:
                stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_WORKER_GROUP, *invalid_entry_ids)
                stats["acked"] += len(invalid_entry_ids)
            except Exception as exc:
                logger.error("[worker] shard=%s ack invalid failed: %s", PACKET_SHARD_INDEX, exc)

        if valid_messages:
            try:
                metrics = process_packet_batch(valid_messages)
                stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_WORKER_GROUP, *valid_entry_ids)
                stats["acked"] += len(valid_entry_ids)
                stats["dedup"] += metrics["dedup"]
                stats["switch_rows"] += metrics["switch_rows"]
                stats["analog_rows"] += metrics["analog_rows"]
                stats["relay_rows"] += metrics["relay_rows"]
                stats["hb_devices"] += metrics["hb_devices"]
                stats["db_ms"] += metrics["db_ms"]
            except Exception as exc:
                logger.error(
                    "[worker] shard=%s batch process failed, keep pending for retry: %s",
                    PACKET_SHARD_INDEX,
                    exc,
                    exc_info=True,
                )
                time.sleep(0.2)

        batch_entries = []
        batch_entry_ids.clear()
        now = time.monotonic()
        if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
            pending = get_pending_count(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_WORKER_GROUP)
            logger.info(
                "[worker] shard=%s recv=%s valid=%s invalid=%s dedup=%s switch=%s analog=%s relay=%s hb_dev=%s acked=%s db_ms=%.1f pending=%s",
                PACKET_SHARD_INDEX,
                stats["recv"],
                stats["valid"],
                stats["invalid"],
                stats["dedup"],
                stats["switch_rows"],
                stats["analog_rows"],
                stats["relay_rows"],
                stats["hb_devices"],
                stats["acked"],
                stats["db_ms"],
                pending,
            )
            stats = {key: 0 if key != "db_ms" else 0.0 for key in stats}
            last_log_time = now


def main():
    snapshot = load_device_cache(logger)
    if not apply_device_cache(snapshot):
        logger.warning("Initial device cache preload failed, worker will retry in background")
    logger.info("Initial preload of %s alarm filter entries for shard=%s", len(device_alarm_filters), PACKET_SHARD_INDEX)
    threading.Thread(target=periodic_device_cache_refresher, daemon=True).start()
    receive_packets()


if __name__ == "__main__":
    main()
