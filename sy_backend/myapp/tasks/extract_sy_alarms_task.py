# myapp/tasks/extract_sy_alarms_task.py

from celery import shared_task
from django.utils import timezone
from datetime import datetime
from django.core.cache import cache

from myapp.models import Device
from .process_sy_helpers import get_sy_bit_value
from consts import SY_ALARM_CODES  # ✅ 直接从 consts 用统一的告警集合


def _coerce_status_bytes(obj):
    """
    把各种可能的缓存/传入格式统一成 bytes/bytearray。
    支持：
      - bytes / bytearray
      - hex 字符串（bytes.fromhex）
      - latin1 字符串（退一步）
      - dict 中常见字段（status_bytes / data / frame / raw 等）
    """
    if obj is None:
        return None

    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj)

    if isinstance(obj, str):
        try:
            return bytes.fromhex(obj)
        except ValueError:
            return obj.encode("latin1")

    if isinstance(obj, dict):
        for k in ("status_bytes", "data", "frame", "raw", "bytes", "payload"):
            if k in obj:
                return _coerce_status_bytes(obj.get(k))
        return None

    return None


def _get_neighbor_status_bytes(nei_device_id: int, *, max_age_seconds: int = 180):
    """
    从 cache 读取邻站最新快照：
      key: device_{id}_switch_status
      value: {"timestamp": "...", "version": "...", "hex": "..."}
    max_age_seconds: 邻站快照最大允许年龄，超时则认为未知（防误告警）
    """
    key = f"device_{nei_device_id}_switch_status"
    v = cache.get(key) or {}
    if not isinstance(v, dict):
        return None, None

    # 新鲜度判断
    ts = v.get("timestamp")  # "YYYY-MM-DD HH:MM:SS"
    if ts:
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            age = (timezone.now() - dt).total_seconds()
            if age > max_age_seconds:
                return None, None
        except Exception:
            # 解析失败就按未知处理（更保守）
            return None, None

    status_hex = v.get("hex") or ""
    b = _coerce_status_bytes(status_hex)
    if b:
        return b, key
    return None, None


@shared_task
def extract_sy_alarms(device_id, status_bytes):
    """
    sy 版告警提取任务：
    - 输入：device_id, status_bytes（A1 全部量 或 A2 更新后的快照）
    - 输出：在 Redis 中维护 device_{id}_alarms 的“完整位图状态”
      cache key:
        - device_{id}_alarms            -> {alarm_code: {"bit_value": 0/1, "starttime": ...}}
        - device_{id}_alarms_updated_at -> ISO8601 字符串
    """
    current_time = timezone.now()

    # 1) 兼容几种格式：bytes / hex 字符串
    status_bytes = _coerce_status_bytes(status_bytes)
    if not isinstance(status_bytes, (bytes, bytearray)) or not status_bytes:
        print(f"[SY_ALARM] device={device_id} status_bytes invalid: {type(status_bytes)}")
        return

    # 2) 上一轮告警状态（用于继承 starttime）
    previous_alarms = cache.get(f"device_{device_id}_alarms", {}) or {}
    alarms_state = {}

    # 3) 设备告警过滤（sy_alarm_filters > alarm_filters > []）
    try:
        device = Device.objects.get(device_id=device_id)
        alarm_filters = set(getattr(device, "alarm_filters", None) or [])
    except Device.DoesNotExist:
        alarm_filters = set()
        device = None

    # ✅ 3.1) “备机”抑制逻辑：
    # 设备名称包含“备机”且 get_sy_bit_value(status_bytes, 7, 0) == 1 （主机工作）时，
    # 备机不产生任何告警（所有告警强制为 0）
    dev_name = ""
    if device is not None:
        dev_name = (
            getattr(device, "name", None)
            or ""
        )
    is_backup_device = ("备机" in dev_name)
    backup_gate_block = False
    if is_backup_device:
        try:
            backup_gate_block = (get_sy_bit_value(status_bytes, 7, 0) == 1)
        except Exception:
            backup_gate_block = False

    # 4) 遍历 SY_ALARM_CODES，用 d*10 + D 规则自动映射到字节/位
    for alarm_code in SY_ALARM_CODES:

        # ✅ 4.0) 备机抑制：所有告警强制为 0
        if backup_gate_block:
            alarms_state[alarm_code] = {"bit_value": 0}
            continue

        # 过滤的告警直接写 0
        if alarm_code in alarm_filters:
            alarms_state[alarm_code] = {"bit_value": 0}
            continue

        # d*10 + D 规则：
        byte_index = alarm_code // 10
        bit_index = alarm_code % 10
        bit_value = get_sy_bit_value(status_bytes, byte_index, bit_index)

        # 反向逻辑告警
        if alarm_code in {70, 71, 42, 43, 52, 53}:
            bit_value = 1 - bit_value

        # 60：第三方向不存在则强制不告警
        elif alarm_code == 60:
            if device is None or (not getattr(device, "direction3_enabled", False)):
                bit_value = 0

        # 62/63：电缆告警（支持单边/双边联动）
        elif alarm_code in {62, 63}:
            # 本站：电缆测试功能 d6.D1 = 0 时，不告警
            if get_sy_bit_value(status_bytes, 6, 1) == 0:
                bit_value = 0
            else:
                # 本站电缆告警：对 d6.D2 / d6.D3 做反向（你原本逻辑）
                bit_value = 1 - bit_value

            # ---- 联动（双边才告）逻辑 ----
            if device is not None and bit_value == 1:
                if alarm_code == 62:
                    linkage_on = getattr(device, "direction1_cable_alarm_linkage", False)
                    nei_id = getattr(device, "direction1_neighbor_id", 0) or 0
                    nei_dir = getattr(device, "direction1_neighbor_direction", None)
                else:
                    linkage_on = getattr(device, "direction2_cable_alarm_linkage", False)
                    nei_id = getattr(device, "direction2_neighbor_id", 0) or 0
                    nei_dir = getattr(device, "direction2_neighbor_direction", None)

                if linkage_on:
                    # 取邻站状态（严格防误告警：拿不到/过期即视为未知 -> 不告警）
                    nei_bytes, _ = _get_neighbor_status_bytes(nei_id) if nei_id else (None, None)
                    if not nei_bytes:
                        bit_value = 0
                    else:
                        # 邻站“对本站方向”取值位：1 -> d6.D2, 2 -> d6.D3
                        if nei_dir == 1:
                            nei_cable_bit = get_sy_bit_value(nei_bytes, 6, 2)
                        elif nei_dir == 2:
                            nei_cable_bit = get_sy_bit_value(nei_bytes, 6, 3)
                        else:
                            # 方向不合法：按“双边才告”要求，直接不告警
                            bit_value = 0
                            nei_cable_bit = None

                        if bit_value == 1 and nei_cable_bit is not None:
                            # 邻站同样受“电缆测试功能 d6.D1” gating
                            if get_sy_bit_value(nei_bytes, 6, 1) == 0:
                                nei_alarm = 0
                            else:
                                nei_alarm = 1 - nei_cable_bit

                            # 双边才告
                            bit_value = 1 if (nei_alarm == 1) else 0

        # 66/67：你原来的逻辑保留
        elif alarm_code in {66, 67}:
            if (
                device is not None
                and (not getattr(device, "direction3_enabled", False))
                and get_sy_bit_value(status_bytes, 7, 7) == 1
            ):
                bit_value = 1 - bit_value
            else:
                bit_value = 0

        # 记录 starttime
        if bit_value == 1:
            start = previous_alarms.get(alarm_code, {}).get("starttime", current_time)
            alarms_state[alarm_code] = {"bit_value": 1, "starttime": start}
        else:
            alarms_state[alarm_code] = {"bit_value": 0}

    # 5) 写回缓存：完整位图 + 更新时间
    cache.set(f"device_{device_id}_alarms", alarms_state, timeout=None)
    cache.set(f"device_{device_id}_alarms_updated_at", current_time.isoformat(), timeout=None)

    print(f"[SY_ALARM] updated device_{device_id}_alarms, len={len(alarms_state)}")