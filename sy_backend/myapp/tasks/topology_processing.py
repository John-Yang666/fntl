from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from consts import TOPOLOGY_TIMEOUT
from myapp.models import Device


def process_topology_status(device_id, alarms_of_this_device):
    """
    sy 网管拓扑状态汇总：
    - device_status: 只分 good / bad
        - 只要有任何告警(
              0,  # 设备网管连接中断
              40, 50, 60,  # 各方向总故障
              70, 71,      # 主机/备机告警
              72, 73, 74, 75, 76  # 同步/通道/励磁/系统等
          中任意一个 bit=1) => bad
        - 否则 good

    - directionX_line_status: good / blink / bad / null
        - direction=1: 使用告警码 42, 43
        - direction=2: 使用告警码 52, 53
        - direction=3: 使用告警码 62, 63
        - 规则：
            * 两个通道码都为 1 -> 'bad'
            * 只有一个通道码为 1 -> 'blink'
            * 两个通道码都为 0 -> 'good'
        - 其它告警码不参与 get_direction_line_status 判断
        - 根据 Device 中 directionX_enabled / direction3_enabled 判断是否参与拓扑
    """

    # 默认拓扑状态
    topology_status = {
        "device_id": device_id,
        "device_status": "good",
        "direction1_line_status": "null",
        "direction2_line_status": "null",
        "direction3_line_status": "null",  # sy 比 bt 多一个方向
    }

    # --- 设备状态判断 ---
    # 参与设备级判断的告警码
    device_level_alarm_codes_for_device_status = {
        0,   # 设备网管连接中断
        40,  # 一方向故障
        50,  # 二方向故障
        60,  # 三方向故障
        70,  # 主机告警
        71,  # 备机告警
        72,  # 同步故障
        73,  # 备机未同步
        74,  # 通道故障
        75,  # 励磁故障
        76,  # 系统故障
    }

    has_any_alarm = any(
        alarm_code in device_level_alarm_codes_for_device_status
        and alarm_status.get("bit_value") == 1
        for alarm_code, alarm_status in alarms_of_this_device.items()
    )
    if has_any_alarm:
        topology_status["device_status"] = "bad"

    # 取设备的方向启用信息
    try:
        device = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        device = None

    # --- 线路状态判断：一方向 ---
    if device is None or getattr(device, "direction1_enabled", False):
        topology_status["direction1_line_status"] = get_direction_line_status(
            alarms_of_this_device,
            direction=1,
        )
    else:
        topology_status["direction1_line_status"] = "null"

    # --- 线路状态判断：二方向 ---
    if device is None or getattr(device, "direction2_enabled", False):
        topology_status["direction2_line_status"] = get_direction_line_status(
            alarms_of_this_device,
            direction=2,
        )
    else:
        topology_status["direction2_line_status"] = "null"

    # --- 线路状态判断：三方向（sy 特有） ---
    if device is not None and getattr(device, "direction3_enabled", False):
        topology_status["direction3_line_status"] = get_direction_line_status(
            alarms_of_this_device,
            direction=3,
        )
    else:
        topology_status["direction3_line_status"] = "null"

    # 将拓扑状态存入缓存
    topology_key = f"device_{device_id}_topology_status"
    cache.set(topology_key, topology_status, timeout=TOPOLOGY_TIMEOUT)

    # 发送给 WebSocket 前端
    send_topology_update(topology_status)

    return topology_status


def get_direction_line_status(alarms_of_this_device, direction: int) -> str:
    """
    sy 每个方向的线路状态逻辑（只看本方向 A/B 通道故障码）：

    - direction == 1 -> 使用告警码 42, 43
        * 42: 一方向通道B故障
        * 43: 一方向通道A故障
    - direction == 2 -> 使用告警码 52, 53
        * 52: 二方向通道A故障
        * 53: 二方向通道B故障
    - direction == 3 -> 使用告警码 62, 63
        * 62: 三方向通道A故障(电缆测试时反映上行电缆故障)
        * 63: 三方向通道B故障(电缆测试时反映下行电缆故障)

    判断规则：
    1) 两个通道告警码 bit_value 都为 1 => 'bad'
    2) 只有一个通道告警码 bit_value 为 1 => 'blink'
    3) 两个通道告警码 bit_value 都为 0 或不存在 => 'good'

    备注：
    - 其它告警码（如 40, 50, 60, 70-76 等）不参与本函数判断；
      它们只用于 device_status。
    """

    # 每个方向对应的 (A 通道码, B 通道码)
    direction_channel_alarm_map = {
        1: (43, 42),  # 一方向：A=43, B=42
        2: (52, 53),  # 二方向：A=52, B=53
        3: (62, 63),  # 三方向：A=62, B=63
    }

    if direction not in direction_channel_alarm_map:
        return "null"

    code_a, code_b = direction_channel_alarm_map[direction]

    status_a = alarms_of_this_device.get(code_a, {})
    status_b = alarms_of_this_device.get(code_b, {})

    has_a_alarm = status_a.get("bit_value") == 1
    has_b_alarm = status_b.get("bit_value") == 1

    if has_a_alarm and has_b_alarm:
        return "bad"
    elif has_a_alarm or has_b_alarm:
        return "blink"
    else:
        return "good"


def send_topology_update(topology_status):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "topology_updates",  # 和 consumer 中 group_add 的 group 名字一致
        {
            "type": "topology.update",
            "data": topology_status,
        },
    )
