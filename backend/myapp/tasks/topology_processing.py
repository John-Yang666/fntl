import os
import time

from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from myapp.runtime_config import get_topology_timeout

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
        topology_status.get('device_status'),
        topology_status.get('direction1_line_status'),
        topology_status.get('direction2_line_status'),
    )


def process_topology_status(device_id, alarms_of_this_device):
    topology_status = {
        'device_id': device_id,
        'device_status': 'good',
        'direction1_line_status': 'null',
        'direction2_line_status': 'null'
    }

    # 设备状态判断
    this_alarms = [
        alarm_code for alarm_code, alarm_status in alarms_of_this_device.items()
        if alarm_status['bit_value'] == 1
    ]
    has_offline_alarm = 0 in this_alarms
    has_non_zero_alarm = any(alarm_code != 0 for alarm_code in this_alarms)

    if has_offline_alarm:
        # 通信中断优先级最高：设备置灰，线路状态置空
        topology_status['device_status'] = 'offline'
        topology_status['direction1_line_status'] = 'null'
        topology_status['direction2_line_status'] = 'null'
    else:
        if has_non_zero_alarm:
            topology_status['device_status'] = 'bad'

        # 线路状态判断
        topology_status['direction1_line_status'] = get_direction_line_status(alarms_of_this_device, 1)
        topology_status['direction2_line_status'] = get_direction_line_status(alarms_of_this_device, 2)

    # 将拓扑状态存入缓存
    topology_key = f"device_{device_id}_topology_status"
    cache.set(topology_key, topology_status, timeout=_resolve_topology_cache_timeout()) #20250821

    # 仅在状态变化时推送 WebSocket，降低高频重复广播开销。
    now_monotonic = time.monotonic()
    current_signature = _topology_signature(topology_status)
    previous_signature = _last_pushed_topology_signature.get(device_id)
    last_push_monotonic = _last_pushed_topology_monotonic.get(device_id, 0.0)
    signature_changed = previous_signature != current_signature
    heartbeat_due = TOPOLOGY_PUSH_HEARTBEAT_SEC <= 0 or (now_monotonic - last_push_monotonic) >= TOPOLOGY_PUSH_HEARTBEAT_SEC

    if signature_changed or heartbeat_due:
        send_topology_update(topology_status)
        _last_pushed_topology_signature[device_id] = current_signature
        _last_pushed_topology_monotonic[device_id] = now_monotonic

    return topology_status

def get_direction_line_status(alarms_of_this_device, direction):
    if direction == 1:
        a_channel_failure = any(alarm_code in {162, 252} for alarm_code, alarm_status in alarms_of_this_device.items() if alarm_status['bit_value'] == 1)
        b_channel_failure = any(alarm_code in {164, 254} for alarm_code, alarm_status in alarms_of_this_device.items() if alarm_status['bit_value'] == 1)
        cable_failure = any(alarm_code == 71 for alarm_code, alarm_status in alarms_of_this_device.items() if alarm_status['bit_value'] == 1)  # 使用告警码71

        if a_channel_failure and b_channel_failure and cable_failure:
            return 'bad'
        elif not a_channel_failure and not b_channel_failure and not cable_failure:
            return 'good'
        else:
            return 'blink'
    elif direction == 2:
        a_channel_failure = any(alarm_code in {342, 432} for alarm_code, alarm_status in alarms_of_this_device.items() if alarm_status['bit_value'] == 1)
        b_channel_failure = any(alarm_code in {344, 434} for alarm_code, alarm_status in alarms_of_this_device.items() if alarm_status['bit_value'] == 1)
        cable_failure = any(alarm_code == 111 for alarm_code, alarm_status in alarms_of_this_device.items() if alarm_status['bit_value'] == 1)  # 使用告警码111

        if a_channel_failure and b_channel_failure and cable_failure:
            return 'bad'
        elif not a_channel_failure and not b_channel_failure and not cable_failure:
            return 'good'
        else:
            return 'blink'
    return 'null'

def send_topology_update(topology_status):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "topology_updates",  # 和 consumer 中 group_add 的 group 名字一致
        {
            "type": "topology.update",
            "data": topology_status
        }
    )
