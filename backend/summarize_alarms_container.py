# 重写的 summarize_alarms_container.py 脚本，使用 AlarmActive + AlarmData 模型，去除缓存键逻辑
import os
import sys

# 添加项目根路径到 PYTHONPATH，确保 myapp、myproject 可导入
sys.path.append('/app')  # 容器路径，请根据实际路径调整

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
import django
django.setup()

import time
import logging
from datetime import datetime
from django.utils import timezone
from myapp.models import Device, AlarmActive, AlarmData
from myapp.tasks.topology_processing import process_topology_status
from myapp.tasks.extract_alarms_task import ALARM_CODES
import redis
from django.core.cache import cache
from consts import ALARM_DELAY, COMMUNICATION_TIMEOUT

logger = logging.getLogger(__name__)
redis_client = redis.StrictRedis(host='redis', port=6379, db=2, decode_responses=True)

def summarize_alarms():
    while True:
        current_time = timezone.now()
        devices = Device.objects.all()

        for device in devices:
            device_id = device.device_id

            last_communication_key = f"device_{device_id}_last_communication_time"
            last_communication_time_str = redis_client.get(last_communication_key)
            if not last_communication_time_str:
                continue

            try:
                last_communication_time = datetime.fromisoformat(last_communication_time_str)
                if timezone.is_naive(last_communication_time):
                    last_communication_time = timezone.make_aware(last_communication_time, timezone=timezone.utc)

                time_difference = (current_time - last_communication_time).total_seconds()

                if time_difference > COMMUNICATION_TIMEOUT:
                    if not AlarmActive.objects.filter(device_id=device_id, alarm_code=0).exists():
                        AlarmActive.objects.create(
                            device_id=device_id,
                            alarm_code=0,
                            timestamp_start=last_communication_time
                        )
                else:
                    if AlarmActive.objects.filter(device_id=device_id, alarm_code=0).exists():
                        active_alarm = AlarmActive.objects.get(device_id=device_id, alarm_code=0)
                        AlarmData.objects.create(
                            device_id=device_id,
                            alarm_code=0,
                            timestamp_start=active_alarm.timestamp_start,
                            timestamp_end=current_time,
                            is_confirmed=active_alarm.is_confirmed
                        )
                        active_alarm.delete()

                # 处理其他告警码
                alarm_key = f'device_{device_id}_alarms'
                current_alarms = cache.get(alarm_key, {}) or {}
                alarms_of_this_device = {}

                for alarm_code in ALARM_CODES:
                    alarm_status = current_alarms.get(alarm_code)
                    if alarm_status and alarm_status['bit_value'] == 1:
                        alarm_start_time = alarm_status['starttime']
                        if isinstance(alarm_start_time, str):
                            alarm_start_time = datetime.fromisoformat(alarm_start_time)
                        if timezone.is_naive(alarm_start_time):
                            alarm_start_time = timezone.make_aware(alarm_start_time, timezone=timezone.utc)

                        if (current_time - alarm_start_time).total_seconds() > ALARM_DELAY.get(alarm_code, 5):
                            alarms_of_this_device[alarm_code] = {'bit_value': 1}
                            if not AlarmActive.objects.filter(device_id=device_id, alarm_code=alarm_code).exists():
                                AlarmActive.objects.create(
                                    device_id=device_id,
                                    alarm_code=alarm_code,
                                    timestamp_start=alarm_start_time
                                )

                # 更新拓扑状态
                process_topology_status(device_id, alarms_of_this_device)

            except Exception as e:
                logger.error(f"Device {device_id} error: {e}")
                continue

        # 处理已结束的告警：遍历 AlarmActive，确认其在缓存中 bit_value 已为 0
        for active_alarm in AlarmActive.objects.all():
            device_id = active_alarm.device.device_id
            alarm_code = active_alarm.alarm_code
            alarm_key = f'device_{device_id}_alarms'
            current_alarms = cache.get(alarm_key, {}) or {}
            bit_value = current_alarms.get(alarm_code, {}).get('bit_value', 0)
            if bit_value == 0:
                AlarmData.objects.create(
                    device_id=device_id,
                    alarm_code=alarm_code,
                    timestamp_start=active_alarm.timestamp_start,
                    timestamp_end=current_time,
                    is_confirmed=active_alarm.is_confirmed
                )
                active_alarm.delete()

        cache.set("alerts_amount", AlarmActive.objects.count(), timeout=5)
        print('Alarms summarized')
        time.sleep(1)

if __name__ == "__main__":
    summarize_alarms()
