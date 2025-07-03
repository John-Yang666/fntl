from datetime import datetime, timezone
from celery import shared_task
from django.core.cache import cache
from myapp.models import SwitchData
from .relay_processing import record_relay_actions
from .extract_alarms_task import extract_alarms
from django.db import transaction
from django.utils.timezone import make_aware, now

@shared_task
def process_switch_data(device_id, payload, timestamp_str=None):
    if timestamp_str:
        try:
            # 使用 datetime.fromisoformat 解析带时区信息的时间戳
            if "+" in timestamp_str or "Z" in timestamp_str:
                task_timestamp = datetime.fromisoformat(timestamp_str)
            else:
                # 如果没有时区信息，假设为 UTC
                naive_task_timestamp = datetime.fromisoformat(timestamp_str)
                task_timestamp = make_aware(naive_task_timestamp, timezone=timezone.utc)

        except ValueError:
            print(f"Invalid timestamp format: {timestamp_str}")
            return

        # 获取当前时间（UTC）
        current_time = now()

        # 计算时间差
        time_difference = (current_time - task_timestamp).total_seconds()

        # 检查时间差
        TIMEOUT_THRESHOLD = 10  # 超时阈值
        if time_difference > TIMEOUT_THRESHOLD:
            print(f"Switch data for device {device_id} timed out for {time_difference} seconds, skipping execution.")
            return

    # 提取并处理开关量数据
    switch_status = payload[4:50]  # 假设开关量数据在 payload 的此位置
    print(f"Processing switch data for device {device_id}")

    # 获取 Redis 缓存的开关量状态
    redis_key = f"device_{device_id}_switch_status"
    previous_switch_status = cache.get(redis_key)

    if previous_switch_status != switch_status:  # 如果状态发生变化
        # 更新 Redis 缓存
        cache.set(redis_key, switch_status, timeout=None)

        # 调用报警提取任务
        extract_alarms.delay(device_id, switch_status)

        print(f"Stored switch data for device {device_id} in Redis")

        # 将数据存储到数据库中
        with transaction.atomic():
            SwitchData.objects.create(device_id=device_id, switch_status=switch_status)

        print(f"Processed switch data for device {device_id}")

        # 记录继电器动作
        record_relay_actions.delay(device_id, switch_status)
        print(f"Recorded relay actions for device {device_id}")
