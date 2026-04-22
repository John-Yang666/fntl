from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone as dt_timezone

import redis

sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa

django.setup()  # noqa

from ingest_common import (  # noqa: E402
    PacketMessage,
    ensure_stream_group,
    get_pending_count,
    load_device_cache,
    parse_router_entry,
    read_stream_entries,
)
from myapp.runtime_config import get_periodic_device_cache_refresh_interval  # noqa: E402
import udp_receiver_worker as worker_impl  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("udp_receiver")

REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_PACKET_STREAM_KEY = os.getenv("REDIS_PACKET_STREAM_KEY", "stream:udp:packets")
REDIS_PACKET_GROUP = os.getenv("REDIS_PACKET_GROUP", "udp-receiver-packet")
REDIS_PACKET_CONSUMER = os.getenv("REDIS_PACKET_CONSUMER", "udp-receiver-packet-0")
REDIS_STREAM_BLOCK_MS = int(os.getenv("REDIS_STREAM_BLOCK_MS", "2000"))
REDIS_STREAM_COUNT = int(os.getenv("REDIS_STREAM_COUNT", "500"))
INGEST_BATCH_MS = int(os.getenv("INGEST_BATCH_MS", "200"))
INGEST_MAX_BATCH = int(os.getenv("INGEST_MAX_BATCH", "500"))
INGEST_LOG_INTERVAL_SEC = int(os.getenv("INGEST_LOG_INTERVAL_SEC", "1"))

should_exit = threading.Event()
device_ip_map: dict[str, int] = {}
device_id_set: set[int] = set()


def apply_device_cache(snapshot) -> bool:
    global device_ip_map, device_id_set
    if snapshot is None:
        return False
    device_ip_map = snapshot.ip_map
    device_id_set = snapshot.id_set
    worker_impl.apply_device_cache(snapshot)
    return True


def periodic_device_cache_refresher():
    last_hash = None
    while not should_exit.is_set():
        interval = get_periodic_device_cache_refresh_interval()
        snapshot = load_device_cache(logger)
        if snapshot is None:
            logger.warning("[device_cache] refresh skipped due to DB read failure, keep previous snapshot")
            if should_exit.wait(interval):
                break
            continue

        new_hash = hash(
            (
                frozenset(snapshot.ip_map.items()),
                frozenset(snapshot.id_set),
                frozenset((k, tuple(sorted(v))) for k, v in snapshot.alarm_filter_map.items()),
            )
        )
        if new_hash != last_hash:
            apply_device_cache(snapshot)
            last_hash = new_hash
            logger.info("[device_cache] refreshed devices=%s", len(device_id_set))

        if should_exit.wait(interval):
            break


def _to_message(packet: dict) -> PacketMessage:
    now_time = datetime.now(dt_timezone.utc)
    now_monotonic = time.monotonic()
    data = packet["data"]
    return PacketMessage(
        entry_id=packet["entry_id"],
        ip_address=packet["ip_address"],
        data=data,
        length=len(data),
        device_id=packet["device_id"],
        received_at=now_time,
        received_monotonic=now_monotonic,
        source=packet["source"],
        source_ts_ms=packet["source_ts_ms"],
    )


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
    ensure_stream_group(logger, stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)

    logger.info(
        "[receiver] listening stream=%s group=%s consumer=%s batch_ms=%s batch_max=%s",
        REDIS_PACKET_STREAM_KEY,
        REDIS_PACKET_GROUP,
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
                    group_name=REDIS_PACKET_GROUP,
                    consumer_name=REDIS_PACKET_CONSUMER,
                    stream_key=REDIS_PACKET_STREAM_KEY,
                    stream_id=b"0",
                    count=remaining,
                    block_ms=1,
                )
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    ensure_stream_group(logger, stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
                    continue
                logger.error("[receiver] read pending error: %s", exc)
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
                    group_name=REDIS_PACKET_GROUP,
                    consumer_name=REDIS_PACKET_CONSUMER,
                    stream_key=REDIS_PACKET_STREAM_KEY,
                    stream_id=b">",
                    count=remaining,
                    block_ms=block_ms,
                )
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    ensure_stream_group(logger, stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
                    continue
                logger.error("[receiver] read new error: %s", exc)
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
                pending = get_pending_count(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
                logger.info("[ingest] recv=0 valid=0 dedup=0 switch=0 analog=0 relay=0 pending=%s", pending)
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
            packet, marker = parse_router_entry(
                entry_id,
                fields,
                device_ip_map=device_ip_map,
                device_id_set=device_id_set,
            )
            if marker is not None:
                invalid_entry_ids.append(entry_id)
                stats["invalid"] += 1
                continue
            valid_messages.append(_to_message(packet))
            valid_entry_ids.append(entry_id)

        stats["recv"] += len(batch_entries)
        stats["valid"] += len(valid_messages)

        if invalid_entry_ids:
            try:
                stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, *invalid_entry_ids)
                stats["acked"] += len(invalid_entry_ids)
            except Exception as exc:
                logger.error("[receiver] ack invalid failed: %s", exc)

        if valid_messages:
            try:
                metrics = worker_impl.process_packet_batch(valid_messages)
                stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, *valid_entry_ids)
                stats["acked"] += len(valid_entry_ids)
                stats["dedup"] += metrics["dedup"]
                stats["switch_rows"] += metrics["switch_rows"]
                stats["analog_rows"] += metrics["analog_rows"]
                stats["relay_rows"] += metrics["relay_rows"]
                stats["hb_devices"] += metrics["hb_devices"]
                stats["db_ms"] += metrics["db_ms"]
            except Exception as exc:
                logger.error("[receiver] batch process failed, keep pending for retry: %s", exc, exc_info=True)
                time.sleep(0.2)

        batch_entries = []
        batch_entry_ids.clear()
        now = time.monotonic()
        if now - last_log_time >= INGEST_LOG_INTERVAL_SEC:
            pending = get_pending_count(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
            logger.info(
                "[ingest] recv=%s valid=%s dedup=%s switch=%s analog=%s relay=%s acked=%s db_ms=%.1f pending=%s",
                stats["recv"],
                stats["valid"],
                stats["dedup"],
                stats["switch_rows"],
                stats["analog_rows"],
                stats["relay_rows"],
                stats["acked"],
                stats["db_ms"],
                pending,
            )
            stats = {key: 0 if key != "db_ms" else 0.0 for key in stats}
            last_log_time = now


def main():
    snapshot = load_device_cache(logger)
    if not apply_device_cache(snapshot):
        logger.warning("Initial device cache preload failed, receiver will retry in background")
    logger.info("Initial preload of %s devices", len(device_id_set))
    threading.Thread(target=periodic_device_cache_refresher, daemon=True).start()
    receive_packets()


if __name__ == "__main__":
    main()
