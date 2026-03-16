# summarize_alarms_container.py

import os
import sys

# 添加项目根路径到 PYTHONPATH，确保 myapp、myproject 可导入
sys.path.append('/app')  # 如果容器中是挂载到 /app

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

import django
django.setup()

import time
import logging
from datetime import datetime
from django.utils import timezone
from myapp.models import Device, AlarmData
from myapp.tasks.topology_processing import process_topology_status
from myapp.tasks.extract_alarms_task import ALARM_CODES
import redis
from django.core.cache import cache
from consts import ALARM_DELAY, COMMUNICATION_TIMEOUT

# 初始化日志
logger = logging.getLogger(__name__)

# Redis 客户端连接
redis_client = redis.StrictRedis(host='redis', port=6379, db=2, decode_responses=True)

def summarize_alarms():
    """
    Summarize all current alarms and store them in the 'red_alert' cache key.
    """
    while True:
        red_alerts = []
        current_time = timezone.now()  # 获取当前时间（UTC）

        # 遍历所有设备
        devices = Device.objects.all()

        for device in devices:
            device_id = device.device_id

            # 检查设备的最后通信时间
            last_communication_key = f"device_{device_id}_last_communication_time"
            last_communication_time_str = redis_client.get(last_communication_key)

            if not last_communication_time_str:
                #logger.warning(f"No last communication time for device {device_id}")
                continue

            try:
                # 从 Redis 获取时间，并解析为 datetime 对象
                last_communication_time = datetime.fromisoformat(last_communication_time_str)

                # 确保时间为 timezone-aware
                if timezone.is_naive(last_communication_time):
                    last_communication_time = timezone.make_aware(last_communication_time, timezone=timezone.utc)

                # 计算时间差
                time_difference = (current_time - last_communication_time).total_seconds()
                #print(time_difference)

                # 如果时间差大于设定值，记录 0 号告警
                if time_difference > COMMUNICATION_TIMEOUT:
                    logger.info(f"Device {device_id} communication timeout ({time_difference:.2f}s)")

                    red_alerts.append({
                        'device_id': device_id,
                        'alarm_code': 0,
                        'timestamp': last_communication_time.strftime('%Y-%m-%d %H:%M:%S')
                    })

                    # 清空该设备相关缓存
                    cache.delete(f'device_{device_id}_switch_status')
                    cache.delete(f'device_{device_id}_topology_status')
                    cache.delete(f'device_{device_id}_alarms')

                    # 写入 0 号告警
                    alarm_recorded_key_0 = f'device_{device_id}_alarm_0_started'
                    if not cache.get(alarm_recorded_key_0):
                        AlarmData.objects.create(device_id=device_id, alarm_code=0,
                                                 timestamp=last_communication_time, alarm_start_or_stop='起')
                        cache.set(alarm_recorded_key_0, True, timeout=None)

                else:
                    # 设备通信正常，清除 0 号告警
                    alarm_recorded_key_0 = f'device_{device_id}_alarm_0_started'
                    if cache.get(alarm_recorded_key_0):
                        AlarmData.objects.create(device_id=device_id, alarm_code=0,
                                                 timestamp=current_time, alarm_start_or_stop='止')
                        cache.delete(alarm_recorded_key_0)

                    # 检查设备的其他告警
                    alarm_key = f'device_{device_id}_alarms'
                    current_alarms = cache.get(alarm_key, {})
                    alarms_of_this_device = {}

                    # 处理设备的每个告警
                    for alarm_code in ALARM_CODES:
                        alarm_status = current_alarms.get(alarm_code)
                        alarm_recorded_key = f'device_{device_id}_alarm_{alarm_code}_started'

                        if alarm_status and alarm_status['bit_value'] == 1:
                            alarm_start_time = timezone.make_aware(alarm_status['starttime']) if timezone.is_naive(alarm_status['starttime']) else alarm_status['starttime']

                            # 判断告警是否持续时间超过延时参数
                            if (current_time - alarm_start_time).total_seconds() > ALARM_DELAY.get(alarm_code, 5):
                                alarms_of_this_device[alarm_code] = {'bit_value': 1}
                                red_alerts.append({
                                    'device_id': device_id,
                                    'alarm_code': alarm_code,
                                    'timestamp': alarm_start_time.strftime('%Y-%m-%d %H:%M:%S')
                                })

                                # 写入数据库告警起记录
                                if not cache.get(alarm_recorded_key):
                                    AlarmData.objects.create(device_id=device_id, alarm_code=alarm_code,
                                                                timestamp=alarm_start_time, alarm_start_or_stop='起')
                                    cache.set(alarm_recorded_key, True, timeout=None)

                        elif cache.get(alarm_recorded_key):
                            # 告警停止，记录止记录  
                            AlarmData.objects.create(device_id=device_id, alarm_code=alarm_code,
                                                        timestamp=current_time, alarm_start_or_stop='止')
                            #cache.delete(alarm_recorded_key)
                            cache.set(alarm_recorded_key, False, timeout=None)

                    # 处理拓扑状态
                    process_topology_status(device_id, alarms_of_this_device)

            except ValueError as e:
                logger.error(f"Invalid time format for device {device_id}: {last_communication_time_str}. Error: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error while processing device {device_id}: {e}")
                continue

        # 将 red_alerts 存储到 Cache
        cache.set('red_alert', red_alerts, timeout=5)
        print('Alarms summarized')

        # 每秒执行一次
        time.sleep(1)

if __name__ == "__main__":
    summarize_alarms()