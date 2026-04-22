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

from consts import SY_ALARM_CODES  # noqa: E402
from myapp.models import AlarmActive, AlarmData, Device  # noqa: E402
from myapp.runtime_config import get_alarm_delay_map, get_communication_timeout  # noqa: E402
from myapp.tasks.extract_sy_alarms_task import build_sy_alarm_state  # noqa: E402
from myapp.tasks.sy_device_context import (  # noqa: E402
    hash_sy_device_context_cache,
    load_sy_device_context_cache,
)
from myapp.tasks.topology_processing import process_topology_status  # noqa: E402


logger = logging.getLogger("sy_summarize")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
logger.propagate = False

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
SUMMARY_INTERVAL_SEC = float(os.getenv("SUMMARY_INTERVAL_SEC", "1"))
SUMMARY_DEVICE_CACHE_REFRESH_SEC = float(os.getenv("SUMMARY_DEVICE_CACHE_REFRESH_SEC", "30"))
NON_ZERO_ALARM_CODES = sorted(SY_ALARM_CODES)
DEVICE_LEVEL_ALARM_CODES_FOR_DEVICE_STATUS = {
    0,
    40,
    50,
    60,
    70,
    71,
    72,
    73,
    74,
    75,
    76,
}

redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)


def _switch_status_key(device_id: int) -> str:
    return f"device_{device_id}_switch_status"


def _switch_status_updated_at_key(device_id: int) -> str:
    return f"device_{device_id}_switch_status_updated_at"


def _alarm_key(device_id: int) -> str:
    return f"device_{device_id}_alarms"


def _alarm_updated_at_key(device_id: int) -> str:
    return f"device_{device_id}_alarms_updated_at"


def _coerce_status_bytes(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, memoryview):
        return raw_value.tobytes()
    if isinstance(raw_value, bytearray):
        return bytes(raw_value)
    if isinstance(raw_value, bytes):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return bytes.fromhex(raw_value)
        except ValueError:
            return raw_value.encode("latin1")
    return None


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
            return elapsed <= get_communication_timeout(), last_comm
        except (TypeError, ValueError) as exc:
            logger.warning("[comm] invalid monotonic device=%s err=%s", device_id, exc)

    return (now - last_comm).total_seconds() <= get_communication_timeout(), last_comm


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


def _build_channel_line_status(alarms_of_this_device: dict, code_a: int, code_b: int) -> str:
    has_a_alarm = alarms_of_this_device.get(code_a, {}).get("bit_value") == 1
    has_b_alarm = alarms_of_this_device.get(code_b, {}).get("bit_value") == 1

    if has_a_alarm and has_b_alarm:
        return "bad"
    if has_a_alarm or has_b_alarm:
        return "blink"
    return "good"


def build_topology_status_payload(
    *,
    device_id: int,
    device_context: dict | None,
    alarms_of_this_device: dict,
    comm_ok: bool | None,
) -> dict:
    topology_status = {
        "device_id": device_id,
        "device_status": "good",
        "direction1_line_status": "null",
        "direction2_line_status": "null",
        "direction3_line_status": "null",
    }

    has_offline_alarm = (comm_ok is False) or alarms_of_this_device.get(0, {}).get("bit_value") == 1
    if has_offline_alarm:
        topology_status["device_status"] = "offline"
        return topology_status

    has_any_device_alarm = any(
        alarm_code in DEVICE_LEVEL_ALARM_CODES_FOR_DEVICE_STATUS
        and alarm_status.get("bit_value") == 1
        for alarm_code, alarm_status in alarms_of_this_device.items()
    )
    if has_any_device_alarm:
        topology_status["device_status"] = "bad"

    direction1_enabled = device_context is None or device_context.get("direction1_enabled", False)
    direction2_enabled = device_context is None or device_context.get("direction2_enabled", False)
    direction3_enabled = bool(device_context and device_context.get("direction3_enabled", False))

    if direction1_enabled:
        direction1_line_status = _build_channel_line_status(alarms_of_this_device, 43, 42)
        if not direction3_enabled and alarms_of_this_device.get(62, {}).get("bit_value") == 1:
            direction1_line_status = "bad"
        topology_status["direction1_line_status"] = direction1_line_status

    if direction2_enabled:
        direction2_line_status = _build_channel_line_status(alarms_of_this_device, 52, 53)
        if not direction3_enabled and alarms_of_this_device.get(63, {}).get("bit_value") == 1:
            direction2_line_status = "bad"
        topology_status["direction2_line_status"] = direction2_line_status

    if direction3_enabled:
        topology_status["direction3_line_status"] = _build_channel_line_status(alarms_of_this_device, 62, 63)

    return topology_status


def summarize_alarms_iteration(state: dict | None = None) -> dict:
    state = state or {}
    current_time = timezone.now()
    current_monotonic = time.monotonic()
    alarm_delay_map = get_alarm_delay_map()

    device_ids_cache = state.get("device_ids_cache", [])
    next_device_cache_refresh = state.get("next_device_cache_refresh", 0.0)
    device_context_map = state.get("device_context_map", {})
    device_context_hash = state.get("device_context_hash")
    next_context_refresh = state.get("next_context_refresh", 0.0)
    last_comm_ok_by_device = state.get("last_comm_ok_by_device", {})
    last_switch_updated_at_by_device = state.get("last_switch_updated_at_by_device", {})

    if not device_ids_cache or current_monotonic >= next_device_cache_refresh:
        device_ids_cache = list(Device.objects.values_list("device_id", flat=True))
        next_device_cache_refresh = current_monotonic + SUMMARY_DEVICE_CACHE_REFRESH_SEC

    context_dirty = False
    if not device_context_map or current_monotonic >= next_context_refresh:
        device_context_map = load_sy_device_context_cache()
        new_context_hash = hash_sy_device_context_cache(device_context_map)
        context_dirty = device_context_hash is None or device_context_hash != new_context_hash
        device_context_hash = new_context_hash
        next_context_refresh = current_monotonic + SUMMARY_DEVICE_CACHE_REFRESH_SEC

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

    cache_keys = []
    switch_status_keys = {}
    switch_updated_at_keys = {}
    alarm_cache_keys = {}
    alarm_updated_at_keys = {}
    topology_cache_keys = {}
    for device_id in device_ids_cache:
        switch_status_keys[device_id] = _switch_status_key(device_id)
        switch_updated_at_keys[device_id] = _switch_status_updated_at_key(device_id)
        alarm_cache_keys[device_id] = _alarm_key(device_id)
        alarm_updated_at_keys[device_id] = _alarm_updated_at_key(device_id)
        topology_cache_keys[device_id] = f"device_{device_id}_topology_status"
        cache_keys.extend(
            (
                switch_status_keys[device_id],
                switch_updated_at_keys[device_id],
                alarm_cache_keys[device_id],
                alarm_updated_at_keys[device_id],
                topology_cache_keys[device_id],
            )
        )
    cache_snapshot = cache.get_many(cache_keys) if cache_keys else {}

    switch_status_by_device = {
        device_id: _coerce_status_bytes(cache_snapshot.get(cache_key))
        for device_id, cache_key in switch_status_keys.items()
    }
    switch_updated_at_by_device = {
        device_id: cache_snapshot.get(cache_key)
        for device_id, cache_key in switch_updated_at_keys.items()
    }
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

    active_device_ids = {device_id for device_id, _alarm_code in active_alarm_by_key}
    if not last_comm_ok_by_device and not last_switch_updated_at_by_device:
        devices_to_process = set(device_ids_cache)
    else:
        devices_to_process = set(active_device_ids)
        for device_id in device_ids_cache:
            comm_ok = comm_status_map.get(device_id, (None, None))[0]
            if last_comm_ok_by_device.get(device_id) != comm_ok:
                devices_to_process.add(device_id)
            if last_switch_updated_at_by_device.get(device_id) != switch_updated_at_by_device.get(device_id):
                devices_to_process.add(device_id)
            if cache_snapshot.get(alarm_cache_keys[device_id]) is None:
                devices_to_process.add(device_id)
            if cache_snapshot.get(topology_cache_keys[device_id]) is None:
                devices_to_process.add(device_id)
    if context_dirty:
        devices_to_process = set(device_ids_cache)

    alarm_data_to_create: list[AlarmData] = []
    active_alarms_to_create: list[AlarmActive] = []
    active_alarm_ids_to_delete: set[int] = set()
    alarm_cache_updates = {}
    raised_alarms = 0
    cleared_alarms = 0
    topology_pushes = 0
    recalc_devices = 0

    for device_id in device_ids_cache:
        if device_id not in devices_to_process:
            continue

        comm_ok, last_comm_time = comm_status_map.get(device_id, (None, None))
        if comm_ok is None:
            continue

        device_context = device_context_map.get(device_id)
        topology_key = f"device_{device_id}_topology_status"
        previous_topology_status = cache.get(topology_key)

        if not comm_ok:
            if (device_id, 0) not in active_alarm_by_key:
                active_alarm = AlarmActive(
                    device_id=device_id,
                    alarm_code=0,
                    timestamp_start=last_comm_time,
                )
                active_alarms_to_create.append(active_alarm)
                active_alarm_by_key[(device_id, 0)] = _active_alarm_dict_from_model(active_alarm)
                cache.delete(_switch_status_key(device_id))
                cache.delete(_switch_status_updated_at_key(device_id))
                cache.delete(f"device_{device_id}_switch_status_version")
                raised_alarms += 1
            topology_status = build_topology_status_payload(
                device_id=device_id,
                device_context=device_context,
                alarms_of_this_device={0: {"bit_value": 1}},
                comm_ok=comm_ok,
            )
            topology_status = process_topology_status(
                device_id=device_id,
                topology_status=topology_status,
                device_context=device_context,
            )
            if previous_topology_status != topology_status:
                topology_pushes += 1
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
        status_bytes = switch_status_by_device.get(device_id)
        if status_bytes:
            current_alarms = build_sy_alarm_state(
                device_id=device_id,
                status_bytes=status_bytes,
                previous_alarms=current_alarms,
                current_time=current_time,
                device_context=device_context,
            )
            alarm_state_by_device[device_id] = current_alarms
            alarm_cache_updates[_alarm_key(device_id)] = current_alarms
            alarm_cache_updates[_alarm_updated_at_key(device_id)] = current_time.isoformat()
            recalc_devices += 1

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

            delay_seconds = alarm_delay_map.get(alarm_code, 5)
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

        topology_status = build_topology_status_payload(
            device_id=device_id,
            device_context=device_context,
            alarms_of_this_device=alarms_of_this_device,
            comm_ok=comm_ok,
        )
        topology_status = process_topology_status(
            device_id=device_id,
            topology_status=topology_status,
            device_context=device_context,
        )
        if previous_topology_status != topology_status:
            topology_pushes += 1

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

    if alarm_cache_updates:
        cache.set_many(alarm_cache_updates, timeout=None)
    if alarm_data_to_create:
        AlarmData.objects.bulk_create(alarm_data_to_create, batch_size=1000)
    if active_alarms_to_create:
        AlarmActive.objects.bulk_create(active_alarms_to_create, batch_size=1000)
    if active_alarm_ids_to_delete:
        AlarmActive.objects.filter(id__in=active_alarm_ids_to_delete).delete()

    logger.info(
        "[sy_summarize] devices=%s dirty=%s recalc_devices=%s active=%s topology_pushes=%s raised=%s cleared=%s",
        len(device_ids_cache),
        len(devices_to_process),
        recalc_devices,
        len(active_alarm_by_key),
        topology_pushes,
        raised_alarms,
        cleared_alarms,
    )
    return {
        "device_ids_cache": device_ids_cache,
        "next_device_cache_refresh": next_device_cache_refresh,
        "device_context_map": device_context_map,
        "device_context_hash": device_context_hash,
        "next_context_refresh": next_context_refresh,
        "last_comm_ok_by_device": {
            device_id: comm_status_map.get(device_id, (None, None))[0]
            for device_id in device_ids_cache
        },
        "last_switch_updated_at_by_device": {
            device_id: switch_updated_at_by_device.get(device_id)
            for device_id in device_ids_cache
        },
    }


def summarize_alarms():
    state = {}
    while True:
        state = summarize_alarms_iteration(state)
        time.sleep(SUMMARY_INTERVAL_SEC)


if __name__ == "__main__":
    logger.info("[sy_summarize] ready")
    summarize_alarms()
