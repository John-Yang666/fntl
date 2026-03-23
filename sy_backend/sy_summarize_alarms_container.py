import os
import sys
import time
import logging
from datetime import datetime

sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa: E402

django.setup()

from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
import redis  # noqa: E402

from consts import COMMUNICATION_TIMEOUT, SY_ALARM_CODES, SY_ALARM_DELAY  # noqa: E402
from myapp.models import AlarmActive, AlarmData, Device  # noqa: E402
from myapp.tasks.topology_processing import process_topology_status  # noqa: E402


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
SUMMARY_INTERVAL_SEC = float(os.getenv("SUMMARY_INTERVAL_SEC", "1"))
SUMMARY_DEVICE_CACHE_REFRESH_SEC = float(os.getenv("SUMMARY_DEVICE_CACHE_REFRESH_SEC", "30"))
NON_ZERO_ALARM_CODES = sorted(SY_ALARM_CODES)

redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)


def parse_iso_aware(raw_value: str):
    dt = datetime.fromisoformat(raw_value)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone=timezone.utc)
    return dt


def get_comm_status_from_raw(
    device_id: int,
    raw_time: str | None,
    raw_monotonic: str | None,
    now: datetime,
    now_monotonic: float,
):
    if not raw_time:
        return None, None

    try:
        last_comm = parse_iso_aware(raw_time)
    except Exception as exc:
        logger.error("[comm] parse error device=%s err=%s", device_id, exc)
        return None, None

    if raw_monotonic is not None:
        try:
            elapsed = now_monotonic - float(raw_monotonic)
            if elapsed < 0:
                elapsed = 0.0
            return elapsed <= COMMUNICATION_TIMEOUT, last_comm
        except (TypeError, ValueError) as exc:
            logger.warning("[comm] invalid monotonic device=%s err=%s", device_id, exc)

    return (now - last_comm).total_seconds() <= COMMUNICATION_TIMEOUT, last_comm


def build_comm_status_map(device_ids: list[int], now: datetime, now_monotonic: float):
    if not device_ids:
        return {}

    raw_time_values = redis_client.mget(
        [f"device_{device_id}_last_communication_time" for device_id in device_ids]
    )
    raw_monotonic_values = redis_client.mget(
        [f"device_{device_id}_last_communication_monotonic" for device_id in device_ids]
    )

    status_map = {}
    for idx, device_id in enumerate(device_ids):
        status_map[device_id] = get_comm_status_from_raw(
            device_id=device_id,
            raw_time=raw_time_values[idx],
            raw_monotonic=raw_monotonic_values[idx],
            now=now,
            now_monotonic=now_monotonic,
        )
    return status_map


def hydrate_cache_from_db_many(device_ids: list[int]):
    if not device_ids:
        return {}

    alarms_state_by_device = {
        device_id: {code: {"bit_value": 0} for code in NON_ZERO_ALARM_CODES}
        for device_id in device_ids
    }
    actives = (
        AlarmActive.objects
        .filter(device_id__in=device_ids)
        .values("device_id", "alarm_code", "timestamp_start")
    )
    for active in actives:
        code = active["alarm_code"]
        if code == 0:
            continue
        alarms_state_by_device[active["device_id"]][code] = {
            "bit_value": 1,
            "starttime": active["timestamp_start"],
        }

    cache.set_many(
        {
            f"device_{device_id}_alarms": alarms_state
            for device_id, alarms_state in alarms_state_by_device.items()
        },
        timeout=None,
    )
    return alarms_state_by_device


def hydrate_cache_from_db(device_id: int):
    return hydrate_cache_from_db_many([device_id]).get(device_id, {})


def safe_alarm_end_time(timestamp_start: datetime):
    timestamp_end = timezone.now()
    if timestamp_end < timestamp_start:
        logger.warning(
            "[alarm_time_guard] end earlier than start start=%s end=%s",
            timestamp_start,
            timestamp_end,
        )
        return timestamp_start
    return timestamp_end


def _active_alarm_dict_from_model(active_alarm: AlarmActive):
    return {
        "id": active_alarm.id,
        "device_id": active_alarm.device_id,
        "alarm_code": active_alarm.alarm_code,
        "timestamp_start": active_alarm.timestamp_start,
        "is_confirmed": active_alarm.is_confirmed,
    }


def summarize_alarms():
    device_ids_cache: list[int] = []
    next_device_cache_refresh = 0.0
    last_comm_ok_by_device: dict[int, bool | None] = {}
    last_alarm_updated_at_by_device: dict[int, str | None] = {}

    while True:
        current_time = timezone.now()
        current_monotonic = time.monotonic()

        if not device_ids_cache or current_monotonic >= next_device_cache_refresh:
            device_ids_cache = list(Device.objects.values_list("device_id", flat=True))
            next_device_cache_refresh = current_monotonic + SUMMARY_DEVICE_CACHE_REFRESH_SEC

        comm_status_map = build_comm_status_map(device_ids_cache, current_time, current_monotonic)
        active_alarm_rows = list(
            AlarmActive.objects.values(
                "id",
                "device_id",
                "alarm_code",
                "timestamp_start",
                "is_confirmed",
            )
        )
        active_alarm_by_key = {
            (active_alarm["device_id"], active_alarm["alarm_code"]): active_alarm
            for active_alarm in active_alarm_rows
        }

        alarm_cache_keys = {device_id: f"device_{device_id}_alarms" for device_id in device_ids_cache}
        alarm_updated_at_keys = {
            device_id: f"device_{device_id}_alarms_updated_at" for device_id in device_ids_cache
        }
        cache_snapshot = cache.get_many([*alarm_cache_keys.values(), *alarm_updated_at_keys.values()]) if alarm_cache_keys else {}
        alarm_cache_snapshot = {
            cache_key: cache_snapshot.get(cache_key)
            for cache_key in alarm_cache_keys.values()
        }
        missing_alarm_cache_ids = [
            device_id
            for device_id, cache_key in alarm_cache_keys.items()
            if alarm_cache_snapshot.get(cache_key) is None
        ]
        hydrated_alarm_cache = hydrate_cache_from_db_many(missing_alarm_cache_ids)
        alarm_state_by_device = {
            device_id: (alarm_cache_snapshot.get(cache_key) or hydrated_alarm_cache.get(device_id, {}))
            for device_id, cache_key in alarm_cache_keys.items()
        }
        alarm_updated_at_by_device = {
            device_id: cache_snapshot.get(cache_key)
            for device_id, cache_key in alarm_updated_at_keys.items()
        }

        active_device_ids = {device_id for device_id, _alarm_code in active_alarm_by_key}
        if not last_comm_ok_by_device and not last_alarm_updated_at_by_device:
            devices_to_process = set(device_ids_cache)
        else:
            devices_to_process = set(active_device_ids)
            for device_id in device_ids_cache:
                comm_ok = comm_status_map.get(device_id, (None, None))[0]
                if last_comm_ok_by_device.get(device_id) != comm_ok:
                    devices_to_process.add(device_id)
                if last_alarm_updated_at_by_device.get(device_id) != alarm_updated_at_by_device.get(device_id):
                    devices_to_process.add(device_id)

        alarm_data_to_create: list[AlarmData] = []
        active_alarms_to_create: list[AlarmActive] = []
        active_alarm_ids_to_delete: set[int] = set()
        raised_alarms = 0
        cleared_alarms = 0

        for device_id in device_ids_cache:
            if device_id not in devices_to_process:
                continue

            comm_ok, last_comm_time = comm_status_map.get(device_id, (None, None))
            if comm_ok is None:
                continue

            if not comm_ok:
                if (device_id, 0) not in active_alarm_by_key:
                    active_alarm = AlarmActive(
                        device_id=device_id,
                        alarm_code=0,
                        timestamp_start=last_comm_time,
                    )
                    active_alarms_to_create.append(active_alarm)
                    active_alarm_by_key[(device_id, 0)] = _active_alarm_dict_from_model(active_alarm)
                    cache.delete(f"device_{device_id}_switch_status")
                    cache.delete(f"device_{device_id}_switch_status_updated_at")
                    cache.delete(f"device_{device_id}_switch_status_version")
                    redis_client.delete(f"device_{device_id}_last_communication_time")
                    redis_client.delete(f"device_{device_id}_last_communication_monotonic")
                    raised_alarms += 1
                process_topology_status(device_id, {0: {"bit_value": 1}})
                continue

            active0 = active_alarm_by_key.get((device_id, 0))
            if active0:
                alarm_data_to_create.append(
                    AlarmData(
                        device_id=device_id,
                        alarm_code=0,
                        timestamp_start=active0["timestamp_start"],
                        timestamp_end=safe_alarm_end_time(active0["timestamp_start"]),
                        is_confirmed=active0["is_confirmed"],
                    )
                )
                if active0["id"] is not None:
                    active_alarm_ids_to_delete.add(active0["id"])
                active_alarm_by_key.pop((device_id, 0), None)
                cleared_alarms += 1

            current_alarms = alarm_state_by_device.get(device_id) or {}
            alarms_of_this_device = {}

            for alarm_code in NON_ZERO_ALARM_CODES:
                alarm_status = current_alarms.get(alarm_code)
                if not alarm_status or alarm_status.get("bit_value") != 1:
                    continue

                alarm_start_time = alarm_status.get("starttime")
                if alarm_start_time is None:
                    continue
                if isinstance(alarm_start_time, str):
                    alarm_start_time = parse_iso_aware(alarm_start_time)
                if timezone.is_naive(alarm_start_time):
                    alarm_start_time = timezone.make_aware(alarm_start_time, timezone=timezone.utc)

                delay_seconds = SY_ALARM_DELAY.get(alarm_code, 5)
                if (current_time - alarm_start_time).total_seconds() <= delay_seconds:
                    continue

                alarms_of_this_device[alarm_code] = {"bit_value": 1}
                if (device_id, alarm_code) not in active_alarm_by_key:
                    active_alarm = AlarmActive(
                        device_id=device_id,
                        alarm_code=alarm_code,
                        timestamp_start=alarm_start_time,
                    )
                    active_alarms_to_create.append(active_alarm)
                    active_alarm_by_key[(device_id, alarm_code)] = _active_alarm_dict_from_model(active_alarm)
                    raised_alarms += 1

            process_topology_status(device_id, alarms_of_this_device)

        for (device_id, alarm_code), active_alarm in list(active_alarm_by_key.items()):
            comm_ok, last_comm_time = comm_status_map.get(device_id, (None, None))
            if comm_ok is None:
                comm_ok, last_comm_time = get_comm_status_from_raw(
                    device_id=device_id,
                    raw_time=redis_client.get(f"device_{device_id}_last_communication_time"),
                    raw_monotonic=redis_client.get(f"device_{device_id}_last_communication_monotonic"),
                    now=current_time,
                    now_monotonic=current_monotonic,
                )
                comm_status_map[device_id] = (comm_ok, last_comm_time)

            if comm_ok is None:
                continue

            if alarm_code == 0:
                if comm_ok:
                    alarm_data_to_create.append(
                        AlarmData(
                            device_id=device_id,
                            alarm_code=0,
                            timestamp_start=active_alarm["timestamp_start"],
                            timestamp_end=safe_alarm_end_time(active_alarm["timestamp_start"]),
                            is_confirmed=active_alarm["is_confirmed"],
                        )
                    )
                    if active_alarm["id"] is not None:
                        active_alarm_ids_to_delete.add(active_alarm["id"])
                    active_alarm_by_key.pop((device_id, 0), None)
                    cleared_alarms += 1
                continue

            if not comm_ok:
                continue

            current_alarms = alarm_state_by_device.get(device_id) or {}
            bit_info = current_alarms.get(alarm_code)
            if not bit_info:
                continue

            if bit_info.get("bit_value") == 0:
                alarm_data_to_create.append(
                    AlarmData(
                        device_id=device_id,
                        alarm_code=alarm_code,
                        timestamp_start=active_alarm["timestamp_start"],
                        timestamp_end=safe_alarm_end_time(active_alarm["timestamp_start"]),
                        is_confirmed=active_alarm["is_confirmed"],
                    )
                )
                if active_alarm["id"] is not None:
                    active_alarm_ids_to_delete.add(active_alarm["id"])
                active_alarm_by_key.pop((device_id, alarm_code), None)
                cleared_alarms += 1

        if alarm_data_to_create:
            AlarmData.objects.bulk_create(alarm_data_to_create, batch_size=1000)
        if active_alarms_to_create:
            AlarmActive.objects.bulk_create(active_alarms_to_create, batch_size=1000)
        if active_alarm_ids_to_delete:
            AlarmActive.objects.filter(id__in=active_alarm_ids_to_delete).delete()

        last_comm_ok_by_device = {
            device_id: comm_status_map.get(device_id, (None, None))[0]
            for device_id in device_ids_cache
        }
        last_alarm_updated_at_by_device = {
            device_id: alarm_updated_at_by_device.get(device_id)
            for device_id in device_ids_cache
        }

        logger.info(
            "[sy_summarize] devices=%s dirty=%s active=%s raised=%s cleared=%s",
            len(device_ids_cache),
            len(devices_to_process),
            len(active_alarm_by_key),
            raised_alarms,
            cleared_alarms,
        )
        time.sleep(SUMMARY_INTERVAL_SEC)


if __name__ == "__main__":
    logger.info("[sy_summarize] ready")
    summarize_alarms()
