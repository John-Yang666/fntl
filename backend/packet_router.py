from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import defaultdict

import redis

sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa

django.setup()  # noqa

from consts import PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL  # noqa: E402
from ingest_common import (  # noqa: E402
    ensure_stream_group,
    get_pending_count,
    get_shard_index,
    load_device_cache,
    parse_router_entry,
    read_stream_entries,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("packet_router")

REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "200000"))
REDIS_PACKET_RAW_STREAM_KEY = os.getenv("REDIS_PACKET_RAW_STREAM_KEY", "stream:udp:packets:raw")
REDIS_PACKET_ROUTER_GROUP = os.getenv("REDIS_PACKET_ROUTER_GROUP", "udp-packet-router")
REDIS_PACKET_ROUTER_CONSUMER = os.getenv("REDIS_PACKET_ROUTER_CONSUMER", "udp-packet-router-0")
REDIS_PACKET_SHARD_STREAM_PREFIX = os.getenv("REDIS_PACKET_SHARD_STREAM_PREFIX", "stream:udp:packets:shard")
PACKET_SHARD_COUNT = int(os.getenv("PACKET_SHARD_COUNT", "4"))

REDIS_STREAM_BLOCK_MS = int(os.getenv("REDIS_STREAM_BLOCK_MS", "2000"))
REDIS_STREAM_COUNT = int(os.getenv("REDIS_STREAM_COUNT", "500"))
ROUTER_BATCH_MS = int(os.getenv("ROUTER_BATCH_MS", "100"))
ROUTER_MAX_BATCH = int(os.getenv("ROUTER_MAX_BATCH", "1000"))
ROUTER_LOG_INTERVAL_SEC = int(os.getenv("ROUTER_LOG_INTERVAL_SEC", "1"))

should_exit = threading.Event()
device_ip_map: dict[str, int] = {}
device_id_set: set[int] = set()


def apply_device_cache(snapshot) -> bool:
    global device_ip_map, device_id_set
    if snapshot is None:
        return False
    device_ip_map = snapshot.ip_map
    device_id_set = snapshot.id_set
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

        new_hash = hash((frozenset(snapshot.ip_map.items()), frozenset(snapshot.id_set)))
        if new_hash != last_hash:
            apply_device_cache(snapshot)
            last_hash = new_hash
            logger.info("[device_cache] refreshed devices=%s", len(device_id_set))

        if should_exit.wait(interval):
            break


def route_packets():
    stats = {
        "recv": 0,
        "routed": 0,
        "invalid": 0,
        "acked": 0,
    }
    routed_per_shard = defaultdict(int)
    batch_entries: list[tuple[bytes, dict[bytes, bytes]]] = []
    batch_start = 0.0
    last_log_time = time.monotonic()

    stream_redis = redis.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
    stream_redis.ping()
    ensure_stream_group(logger, stream_redis, REDIS_PACKET_RAW_STREAM_KEY, REDIS_PACKET_ROUTER_GROUP)

    logger.info(
        "[router] listening raw_stream=%s group=%s consumer=%s shards=%s",
        REDIS_PACKET_RAW_STREAM_KEY,
        REDIS_PACKET_ROUTER_GROUP,
        REDIS_PACKET_ROUTER_CONSUMER,
        PACKET_SHARD_COUNT,
    )

    while not should_exit.is_set():
        if not batch_entries:
            batch_start = time.monotonic()

        remaining = max(1, ROUTER_MAX_BATCH - len(batch_entries))
        elapsed_ms = int((time.monotonic() - batch_start) * 1000)
        window_left_ms = max(1, ROUTER_BATCH_MS - elapsed_ms)

        try:
            pending_entries = read_stream_entries(
                stream_redis,
                group_name=REDIS_PACKET_ROUTER_GROUP,
                consumer_name=REDIS_PACKET_ROUTER_CONSUMER,
                stream_key=REDIS_PACKET_RAW_STREAM_KEY,
                stream_id=b"0",
                count=remaining,
                block_ms=1,
            )
        except Exception as exc:
            if "NOGROUP" in str(exc):
                ensure_stream_group(logger, stream_redis, REDIS_PACKET_RAW_STREAM_KEY, REDIS_PACKET_ROUTER_GROUP)
                continue
            logger.error("[router] read pending error: %s", exc)
            time.sleep(0.2)
            continue

        if pending_entries:
            batch_entries.extend(pending_entries)
        else:
            block_ms = min(REDIS_STREAM_BLOCK_MS, window_left_ms if batch_entries else REDIS_STREAM_BLOCK_MS)
            try:
                new_entries = read_stream_entries(
                    stream_redis,
                    group_name=REDIS_PACKET_ROUTER_GROUP,
                    consumer_name=REDIS_PACKET_ROUTER_CONSUMER,
                    stream_key=REDIS_PACKET_RAW_STREAM_KEY,
                    stream_id=b">",
                    count=remaining,
                    block_ms=block_ms,
                )
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    ensure_stream_group(logger, stream_redis, REDIS_PACKET_RAW_STREAM_KEY, REDIS_PACKET_ROUTER_GROUP)
                    continue
                logger.error("[router] read new error: %s", exc)
                time.sleep(0.2)
                continue
            if new_entries:
                batch_entries.extend(new_entries)

        if not batch_entries:
            now = time.monotonic()
            if now - last_log_time >= ROUTER_LOG_INTERVAL_SEC:
                pending = get_pending_count(stream_redis, REDIS_PACKET_RAW_STREAM_KEY, REDIS_PACKET_ROUTER_GROUP)
                logger.info("[router] recv=0 routed=0 invalid=0 acked=0 pending=%s per_shard={}", pending)
                last_log_time = now
            continue

        batch_due = (time.monotonic() - batch_start) * 1000 >= ROUTER_BATCH_MS
        batch_full = len(batch_entries) >= ROUTER_MAX_BATCH
        if not batch_due and not batch_full:
            continue

        invalid_entry_ids: list[bytes] = []
        routed_entry_ids: list[bytes] = []
        routed_packets = []

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
            routed_packets.append(packet)
            routed_entry_ids.append(entry_id)

        stats["recv"] += len(batch_entries)

        if invalid_entry_ids:
            try:
                stream_redis.xack(REDIS_PACKET_RAW_STREAM_KEY, REDIS_PACKET_ROUTER_GROUP, *invalid_entry_ids)
                stats["acked"] += len(invalid_entry_ids)
            except Exception as exc:
                logger.error("[router] ack invalid failed: %s", exc)

        if routed_packets:
            route_pipe = stream_redis.pipeline(transaction=False)
            for packet in routed_packets:
                shard_index = get_shard_index(packet["device_id"], PACKET_SHARD_COUNT)
                routed_per_shard[shard_index] += 1
                route_pipe.xadd(
                    name=f"{REDIS_PACKET_SHARD_STREAM_PREFIX}:{shard_index}",
                    fields={
                        b"type": b"packet",
                        b"ip": packet["ip_address"].encode(),
                        b"data_hex": packet["raw_hex"].encode(),
                        b"device_id": str(packet["device_id"]).encode(),
                        b"ts": str(packet["source_ts_ms"]).encode(),
                        b"src": packet["source"].encode(),
                    },
                    maxlen=REDIS_STREAM_MAXLEN,
                    approximate=True,
                )
            try:
                route_pipe.execute()
                stream_redis.xack(REDIS_PACKET_RAW_STREAM_KEY, REDIS_PACKET_ROUTER_GROUP, *routed_entry_ids)
                stats["routed"] += len(routed_packets)
                stats["acked"] += len(routed_entry_ids)
            except Exception as exc:
                logger.error("[router] route batch failed, keep pending for retry: %s", exc, exc_info=True)
                time.sleep(0.2)

        batch_entries = []
        now = time.monotonic()
        if now - last_log_time >= ROUTER_LOG_INTERVAL_SEC:
            pending = get_pending_count(stream_redis, REDIS_PACKET_RAW_STREAM_KEY, REDIS_PACKET_ROUTER_GROUP)
            logger.info(
                "[router] recv=%s routed=%s invalid=%s acked=%s pending=%s per_shard=%s",
                stats["recv"],
                stats["routed"],
                stats["invalid"],
                stats["acked"],
                pending,
                dict(sorted(routed_per_shard.items())),
            )
            stats = {key: 0 for key in stats}
            routed_per_shard = defaultdict(int)
            last_log_time = now


def main():
    snapshot = load_device_cache(logger)
    if not apply_device_cache(snapshot):
        logger.warning("Initial device cache preload failed, router will retry in background")
    logger.info("Initial preload of %s devices", len(device_id_set))
    threading.Thread(target=periodic_device_cache_refresher, daemon=True).start()
    route_packets()


if __name__ == "__main__":
    main()
