import os
import time

from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from myapp.runtime_config import get_topology_timeout
from myapp.models import Device
from myapp.tasks.sy_device_context import load_sy_device_context_cache

CHANNEL_LAYER = None
_last_pushed_topology_signature = {}
_last_pushed_topology_monotonic = {}
TOPOLOGY_PUSH_HEARTBEAT_SEC = float(os.getenv("TOPOLOGY_PUSH_HEARTBEAT_SEC", "30"))


def _resolve_topology_cache_timeout():
    topology_timeout = get_topology_timeout()
    if topology_timeout is None:
        return None

    try:
        timeout = int(topology_timeout)
    except (TypeError, ValueError):
        return topology_timeout

    if timeout <= 0:
        return None

    heartbeat_floor = int(max(TOPOLOGY_PUSH_HEARTBEAT_SEC, 0)) + 5
    return max(timeout, heartbeat_floor)


def _topology_signature(topology_status):
    return (
        topology_status.get("device_status"),
        topology_status.get("direction1_line_status"),
        topology_status.get("direction2_line_status"),
        topology_status.get("direction3_line_status"),
    )


def _resolve_device_context(device_id, device_context=None):
    if device_context is not None:
        return device_context
    try:
        return load_sy_device_context_cache().get(device_id)
    except Exception:
        try:
            device = Device.objects.only(
                "direction1_enabled",
                "direction2_enabled",
                "direction3_enabled",
            ).get(device_id=device_id)
        except Device.DoesNotExist:
            return None
        return {
            "direction1_enabled": bool(getattr(device, "direction1_enabled", False)),
            "direction2_enabled": bool(getattr(device, "direction2_enabled", False)),
            "direction3_enabled": bool(getattr(device, "direction3_enabled", False)),
        }


def process_topology_status(device_id, topology_status, device_context=None):
    normalized_topology_status = {
        "device_id": device_id,
        "device_status": topology_status.get("device_status", "good"),
        "direction1_line_status": topology_status.get("direction1_line_status", "null"),
        "direction2_line_status": topology_status.get("direction2_line_status", "null"),
        "direction3_line_status": topology_status.get("direction3_line_status", "null"),
    }
    resolved_device_context = _resolve_device_context(device_id, device_context=device_context)
    has_offline_alarm = normalized_topology_status["device_status"] == "offline"

    if has_offline_alarm:
        normalized_topology_status["direction1_line_status"] = "null"
        normalized_topology_status["direction2_line_status"] = "null"
        normalized_topology_status["direction3_line_status"] = "null"
    else:
        if resolved_device_context is not None and not resolved_device_context.get("direction1_enabled", False):
            normalized_topology_status["direction1_line_status"] = "null"
        if resolved_device_context is not None and not resolved_device_context.get("direction2_enabled", False):
            normalized_topology_status["direction2_line_status"] = "null"
        if resolved_device_context is None or not resolved_device_context.get("direction3_enabled", False):
            normalized_topology_status["direction3_line_status"] = "null"

    topology_key = f"device_{device_id}_topology_status"
    cache.set(topology_key, normalized_topology_status, timeout=_resolve_topology_cache_timeout())

    now_monotonic = time.monotonic()
    current_signature = _topology_signature(normalized_topology_status)
    previous_signature = _last_pushed_topology_signature.get(device_id)
    last_push_monotonic = _last_pushed_topology_monotonic.get(device_id, 0.0)
    signature_changed = previous_signature != current_signature
    heartbeat_due = TOPOLOGY_PUSH_HEARTBEAT_SEC <= 0 or (now_monotonic - last_push_monotonic) >= TOPOLOGY_PUSH_HEARTBEAT_SEC

    if signature_changed or heartbeat_due:
        send_topology_update(normalized_topology_status)
        _last_pushed_topology_signature[device_id] = current_signature
        _last_pushed_topology_monotonic[device_id] = now_monotonic

    return normalized_topology_status


def send_topology_update(topology_status):
    global CHANNEL_LAYER
    if CHANNEL_LAYER is None:
        CHANNEL_LAYER = get_channel_layer()
    async_to_sync(CHANNEL_LAYER.group_send)(
        "topology_updates",  # 和 consumer 中 group_add 的 group 名字一致
        {
            "type": "topology.update",
            "data": topology_status,
        },
    )
