# summarize_alarms_container.py —— sy 版带详细日志
import os
import sys
import time
import logging
from datetime import datetime

# ---- Django 环境 ----
sys.path.append('/app')  # 容器路径，按需调整
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
import django
django.setup()

from django.utils import timezone
from django.core.cache import cache
from django.db.models import Q

import redis

from myapp.models import Device, AlarmActive, AlarmData
from myapp.tasks.topology_processing import process_topology_status
from consts import SY_ALARM_DELAY, COMMUNICATION_TIMEOUT, SY_ALARM_CODES  # 这里的 ALARM_CODES 建议在 consts 里给 sy 赋值为 SY_ALARM_CODES

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 直接让 print 也及时 flush，方便 docker logs 看
def log(msg):
    print(msg, flush=True)
    logger.info(msg)

# Redis（通信时间等，跟 sy_receiver 里的配置保持一致）
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)


# ---------- 工具函数 ----------
def parse_iso_aware(s: str):
    """将 ISO 字符串转为 aware datetime（UTC）"""
    dt = datetime.fromisoformat(s)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone=timezone.utc)
    return dt


def get_comm_status(device_id: int, now: datetime):
    """
    返回 (comm_ok: bool | None, last_comm_time: datetime|None)
    None 表示拿不到通信时间（未知）
    """
    key = f"device_{device_id}_last_communication_time"
    s = redis_client.get(key)
    if not s:
        # 没有 key，说明 sy_receiver 那边还没收到这个设备的任何帧
        return None, None
    try:
        last_comm = parse_iso_aware(s)
    except Exception as e:
        log(f"[comm] parse error for device {device_id}: {e}")
        return None, None
    comm_ok = (now - last_comm).total_seconds() <= COMMUNICATION_TIMEOUT
    return comm_ok, last_comm


def hydrate_cache_from_db(device_id: int):
    """
    当缓存缺失时，从 AlarmActive 回灌完整 0/1 状态到缓存（不含 0 号）
    - 处于活跃的非0号告警：bit=1, starttime=active.timestamp_start
    - 其余 ALARM_CODES（排除 0）写 bit=0
    返回 alarms_state 字典
    """
    alarms_state = {}
    actives = (AlarmActive.objects
               .filter(device_id=device_id)
               .values('alarm_code', 'timestamp_start'))
    active_codes = set()
    for a in actives:
        code = a['alarm_code']
        if code == 0:
            continue  # 0 号不用写在位图缓存里
        active_codes.add(code)
        alarms_state[code] = {
            'bit_value': 1,
            'starttime': a['timestamp_start'],
        }

    # 其余写 0
    for code in SY_ALARM_CODES:
        if code == 0:
            continue
        if code not in alarms_state:
            alarms_state[code] = {'bit_value': 0}

    cache.set(f'device_{device_id}_alarms', alarms_state, timeout=None)
    return alarms_state


# ---------- 主逻辑 ----------
def summarize_alarms():
    log("[sy_summarize] start summarize_alarms loop.")

    while True:
        current_time = timezone.now()
        log(f"[sy_summarize] tick at {current_time.isoformat()}")

        # ------- 每台设备：生成 0 号/非 0 号告警 -------
        for device in Device.objects.all():
            device_id = device.device_id

            comm_ok, last_comm_time = get_comm_status(device_id, current_time)

            if comm_ok is None:
                # 还没收到任何帧，跳过，但打一行日志方便你确认
                log(f"[sy_summarize] device={device_id} comm_status=UNKNOWN (no last_communication_time yet)")
                continue

            log(f"[sy_summarize] device={device_id} comm_ok={comm_ok}")

            if not comm_ok:
                # 通信超时：拉起 0 号（若未存在）
                if not AlarmActive.objects.filter(device_id=device_id, alarm_code=0).exists():
                    AlarmActive.objects.create(
                        device_id=device_id,
                        alarm_code=0,
                        timestamp_start=last_comm_time,
                    )
                    # 通信中断时可选：清掉 switch_status/last_comm_time
                    cache.delete(f'device_{device_id}_switch_status')
                    redis_client.delete(f'device_{device_id}_last_communication_time')

                    log(f"[sy_summarize] device={device_id} raise alarm 0 (comm timeout)")
                # 不删除 device_{id}_alarms，保持通信中断前的当前告警状态
            else:
                # 通信恢复：若存在 0 号则结束
                active0 = AlarmActive.objects.filter(device_id=device_id, alarm_code=0).first()
                if active0:
                    AlarmData.objects.create(
                        device_id=device_id,
                        alarm_code=0,
                        timestamp_start=active0.timestamp_start,
                        timestamp_end=current_time,
                        is_confirmed=active0.is_confirmed,
                    )
                    active0.delete()
                    log(f"[sy_summarize] device={device_id} clear alarm 0 (comm restored)")

                # 生成非 0 号告警（读取完整位图；缺失则回灌）
                alarm_key = f'device_{device_id}_alarms'
                current_alarms = cache.get(alarm_key, None)
                if current_alarms is None:
                    current_alarms = hydrate_cache_from_db(device_id)
                    log(f"[sy_summarize] device={device_id} cache hydrated from DB")

                alarms_of_this_device = {}

                for alarm_code in SY_ALARM_CODES:
                    if alarm_code == 0:
                        continue
                    alarm_status = current_alarms.get(alarm_code)
                    if not alarm_status:
                        continue

                    if alarm_status.get('bit_value') == 1:
                        alarm_start_time = alarm_status.get('starttime')
                        if isinstance(alarm_start_time, str):
                            alarm_start_time = parse_iso_aware(alarm_start_time)
                        if timezone.is_naive(alarm_start_time):
                            alarm_start_time = timezone.make_aware(alarm_start_time, timezone=timezone.utc)

                        # 延时判定
                        delay = SY_ALARM_DELAY.get(alarm_code, 5)
                        if (current_time - alarm_start_time).total_seconds() > delay:
                            alarms_of_this_device[alarm_code] = {'bit_value': 1}
                            if not AlarmActive.objects.filter(device_id=device_id, alarm_code=alarm_code).exists():
                                AlarmActive.objects.create(
                                    device_id=device_id,
                                    alarm_code=alarm_code,
                                    timestamp_start=alarm_start_time,
                                )
                                log(f"[sy_summarize] device={device_id} raise alarm {alarm_code}")

                # 更新拓扑（可用 alarms_of_this_device）
                if alarms_of_this_device:
                    log(f"[sy_summarize] device={device_id} active alarms in this loop: {sorted(alarms_of_this_device.keys())}")
                process_topology_status(device_id, alarms_of_this_device)

        # ------- 结束告警：仅在通信恢复且明确 bit=0 才结束 -------
        for active_alarm in AlarmActive.objects.select_related('device').all():
            device_id = active_alarm.device.device_id
            alarm_code = active_alarm.alarm_code

            comm_ok, _last_comm_time = get_comm_status(device_id, current_time)
            if comm_ok is None:
                continue

            # 0 号：通信恢复即可结束（上面已经处理，这里再兜一层）
            if alarm_code == 0:
                if comm_ok:
                    AlarmData.objects.create(
                        device_id=device_id,
                        alarm_code=0,
                        timestamp_start=active_alarm.timestamp_start,
                        timestamp_end=current_time,
                        is_confirmed=active_alarm.is_confirmed,
                    )
                    active_alarm.delete()
                    log(f"[sy_summarize] device={device_id} clear alarm 0 in cleanup loop")
                continue

            # 非 0 号：通信未恢复时不结束
            if not comm_ok:
                continue

            alarm_key = f'device_{device_id}_alarms'
            current_alarms = cache.get(alarm_key, None)
            if current_alarms is None:
                current_alarms = hydrate_cache_from_db(device_id)

            bit_info = current_alarms.get(alarm_code)
            if not bit_info:
                continue

            if bit_info.get('bit_value') == 0:
                AlarmData.objects.create(
                    device_id=device_id,
                    alarm_code=alarm_code,
                    timestamp_start=active_alarm.timestamp_start,
                    timestamp_end=current_time,
                    is_confirmed=active_alarm.is_confirmed,
                )
                active_alarm.delete()
                log(f"[sy_summarize] device={device_id} clear alarm {alarm_code} (bit=0)")

        # 结束一轮
        log("[sy_summarize] one loop done.")
        time.sleep(1)


if __name__ == "__main__":
    log("[sy_summarize] Ready to summarize alarms.")
    summarize_alarms()
