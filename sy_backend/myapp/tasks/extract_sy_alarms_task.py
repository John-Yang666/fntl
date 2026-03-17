from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from myapp.models import Device

from .process_sy_helpers import get_sy_bit_value
from consts import SY_ALARM_CODES


SWITCH_STATUS_UPDATED_AT_SUFFIX = "switch_status_updated_at"
SWITCH_STATUS_VERSION_SUFFIX = "switch_status_version"


def _switch_status_key(device_id: int) -> str:
    return f"device_{device_id}_switch_status"


def _switch_status_updated_at_key(device_id: int) -> str:
    return f"device_{device_id}_{SWITCH_STATUS_UPDATED_AT_SUFFIX}"


def _switch_status_version_key(device_id: int) -> str:
    return f"device_{device_id}_{SWITCH_STATUS_VERSION_SUFFIX}"


def _coerce_status_bytes(obj):
    if obj is None:
        return None

    if isinstance(obj, memoryview):
        return obj.tobytes()

    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj)

    if isinstance(obj, str):
        try:
            return bytes.fromhex(obj)
        except ValueError:
            return obj.encode("latin1")

    if isinstance(obj, Mapping):
        for key in ("status_bytes", "data", "frame", "raw", "bytes", "payload", "hex"):
            if key in obj:
                return _coerce_status_bytes(obj.get(key))
        return None

    return None


def _parse_cache_timestamp(raw_value):
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        try:
            dt = datetime.fromisoformat(str(raw_value))
        except ValueError:
            return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _get_neighbor_status_bytes(nei_device_id: int, *, max_age_seconds: int = 180):
    status_bytes = _coerce_status_bytes(cache.get(_switch_status_key(nei_device_id)))
    if not status_bytes:
        return None, None

    updated_at = _parse_cache_timestamp(cache.get(_switch_status_updated_at_key(nei_device_id)))
    if updated_at is None:
        return None, None

    age = (timezone.now() - updated_at).total_seconds()
    if age > max_age_seconds:
        return None, None

    return status_bytes, _switch_status_key(nei_device_id)


def load_device_alarm_context(device_id: int):
    device = (
        Device.objects.filter(device_id=device_id)
        .only(
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
        .first()
    )
    if device is None:
        return None

    return {
        "device_id": device.device_id,
        "name": device.name or "",
        "alarm_filters": set(device.alarm_filters or []),
        "direction1_enabled": bool(device.direction1_enabled),
        "direction2_enabled": bool(device.direction2_enabled),
        "direction3_enabled": bool(device.direction3_enabled),
        "direction1_neighbor_id": device.direction1_neighbor_id or 0,
        "direction1_neighbor_direction": device.direction1_neighbor_direction,
        "direction2_neighbor_id": device.direction2_neighbor_id or 0,
        "direction2_neighbor_direction": device.direction2_neighbor_direction,
        "direction1_cable_alarm_linkage": bool(device.direction1_cable_alarm_linkage),
        "direction2_cable_alarm_linkage": bool(device.direction2_cable_alarm_linkage),
    }


def build_sy_alarm_state(
    *,
    device_id: int,
    status_bytes,
    previous_alarms=None,
    current_time=None,
    device_context=None,
):
    current_time = current_time or timezone.now()
    status_bytes = _coerce_status_bytes(status_bytes)
    if not isinstance(status_bytes, (bytes, bytearray)) or not status_bytes:
        return {}

    previous_alarms = previous_alarms or {}
    device_context = device_context or load_device_alarm_context(device_id)
    alarm_filters = set((device_context or {}).get("alarm_filters") or [])

    dev_name = (device_context or {}).get("name", "")
    is_backup_device = "备机" in dev_name
    backup_gate_block = False
    if is_backup_device:
        try:
            backup_gate_block = get_sy_bit_value(status_bytes, 7, 0) == 1
        except Exception:
            backup_gate_block = False

    alarms_state = {}

    for alarm_code in SY_ALARM_CODES:
        if backup_gate_block:
            alarms_state[alarm_code] = {"bit_value": 0}
            continue

        if alarm_code in alarm_filters:
            alarms_state[alarm_code] = {"bit_value": 0}
            continue

        byte_index = alarm_code // 10
        bit_index = alarm_code % 10
        bit_value = get_sy_bit_value(status_bytes, byte_index, bit_index)

        if alarm_code in {70, 71, 42, 43, 52, 53}:
            bit_value = 1 - bit_value
        elif alarm_code == 60:
            if device_context is None or not device_context.get("direction3_enabled", False):
                bit_value = 0
        elif alarm_code in {62, 63}:
            if get_sy_bit_value(status_bytes, 6, 1) == 0:
                bit_value = 0
            else:
                bit_value = 1 - bit_value

            if device_context is not None and bit_value == 1:
                if alarm_code == 62:
                    linkage_on = device_context.get("direction1_cable_alarm_linkage", False)
                    nei_id = device_context.get("direction1_neighbor_id", 0) or 0
                    nei_dir = device_context.get("direction1_neighbor_direction")
                else:
                    linkage_on = device_context.get("direction2_cable_alarm_linkage", False)
                    nei_id = device_context.get("direction2_neighbor_id", 0) or 0
                    nei_dir = device_context.get("direction2_neighbor_direction")

                if linkage_on:
                    nei_bytes, _ = _get_neighbor_status_bytes(nei_id) if nei_id else (None, None)
                    if not nei_bytes:
                        bit_value = 0
                    else:
                        if nei_dir == 1:
                            nei_cable_bit = get_sy_bit_value(nei_bytes, 6, 2)
                        elif nei_dir == 2:
                            nei_cable_bit = get_sy_bit_value(nei_bytes, 6, 3)
                        else:
                            bit_value = 0
                            nei_cable_bit = None

                        if bit_value == 1 and nei_cable_bit is not None:
                            if get_sy_bit_value(nei_bytes, 6, 1) == 0:
                                nei_alarm = 0
                            else:
                                nei_alarm = 1 - nei_cable_bit
                            bit_value = 1 if nei_alarm == 1 else 0
        elif alarm_code in {66, 67}:
            if (
                device_context is not None
                and not device_context.get("direction3_enabled", False)
                and get_sy_bit_value(status_bytes, 7, 7) == 1
            ):
                bit_value = 1 - bit_value
            else:
                bit_value = 0

        if bit_value == 1:
            start = previous_alarms.get(alarm_code, {}).get("starttime", current_time)
            alarms_state[alarm_code] = {"bit_value": 1, "starttime": start}
        else:
            alarms_state[alarm_code] = {"bit_value": 0}

    return alarms_state


def write_sy_alarm_cache(*, device_id: int, alarms_state: dict, current_time=None):
    current_time = current_time or timezone.now()
    cache.set(f"device_{device_id}_alarms", alarms_state, timeout=None)
    cache.set(f"device_{device_id}_alarms_updated_at", current_time.isoformat(), timeout=None)


@shared_task
def extract_sy_alarms(device_id, status_bytes):
    current_time = timezone.now()
    previous_alarms = cache.get(f"device_{device_id}_alarms", {}) or {}
    alarms_state = build_sy_alarm_state(
        device_id=device_id,
        status_bytes=status_bytes,
        previous_alarms=previous_alarms,
        current_time=current_time,
    )
    if not alarms_state:
        return

    write_sy_alarm_cache(device_id=device_id, alarms_state=alarms_state, current_time=current_time)
