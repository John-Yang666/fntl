from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from consts import TOPOLOGY_TIMEOUT
from myapp.models import Device
from myapp.tasks.sy_device_context import load_sy_device_context_cache

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

DIRECTION_CHANNEL_ALARM_MAP = {
    1: (43, 42),
    2: (52, 53),
    3: (62, 63),
}

CHANNEL_LAYER = None


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


def process_topology_status(device_id, alarms_of_this_device, device_context=None):
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
    has_offline_alarm = alarms_of_this_device.get(0, {}).get("bit_value") == 1
    has_any_alarm = any(
        alarm_code in DEVICE_LEVEL_ALARM_CODES_FOR_DEVICE_STATUS
        and alarm_status.get("bit_value") == 1
        for alarm_code, alarm_status in alarms_of_this_device.items()
    )

    if has_offline_alarm:
        topology_status["device_status"] = "offline"
        topology_status["direction1_line_status"] = "null"
        topology_status["direction2_line_status"] = "null"
        topology_status["direction3_line_status"] = "null"
    elif has_any_alarm:
        topology_status["device_status"] = "bad"

    resolved_device_context = _resolve_device_context(device_id, device_context=device_context)

    # --- 线路状态判断：一方向 ---
    if has_offline_alarm:
        topology_status["direction1_line_status"] = "null"
    elif resolved_device_context is None or resolved_device_context.get("direction1_enabled", False):
        topology_status["direction1_line_status"] = get_direction_line_status(
            alarms_of_this_device,
            direction=1,
        )
    else:
        topology_status["direction1_line_status"] = "null"

    # --- 线路状态判断：二方向 ---
    if has_offline_alarm:
        topology_status["direction2_line_status"] = "null"
    elif resolved_device_context is None or resolved_device_context.get("direction2_enabled", False):
        topology_status["direction2_line_status"] = get_direction_line_status(
            alarms_of_this_device,
            direction=2,
        )
    else:
        topology_status["direction2_line_status"] = "null"

    # --- 线路状态判断：三方向（sy 特有） ---
    if has_offline_alarm:
        topology_status["direction3_line_status"] = "null"
    elif resolved_device_context is not None and resolved_device_context.get("direction3_enabled", False):
        topology_status["direction3_line_status"] = get_direction_line_status(
            alarms_of_this_device,
            direction=3,
        )
    else:
        topology_status["direction3_line_status"] = "null"

    # 将拓扑状态存入缓存
    topology_key = f"device_{device_id}_topology_status"
    previous_topology_status = cache.get(topology_key)
    if previous_topology_status == topology_status:
        return topology_status

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
    if direction not in DIRECTION_CHANNEL_ALARM_MAP:
        return "null"

    code_a, code_b = DIRECTION_CHANNEL_ALARM_MAP[direction]

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
