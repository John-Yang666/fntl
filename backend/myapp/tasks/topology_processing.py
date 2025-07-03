from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

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

    if this_alarms:
        topology_status['device_status'] = 'bad'

    # 线路状态判断
    topology_status['direction1_line_status'] = get_direction_line_status(alarms_of_this_device, 1)
    topology_status['direction2_line_status'] = get_direction_line_status(alarms_of_this_device, 2)

    # 将拓扑状态存入缓存
    topology_key = f"device_{device_id}_topology_status"
    cache.set(topology_key, topology_status)

    # 发送给 WebSocket 前端
    send_topology_update(topology_status)

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