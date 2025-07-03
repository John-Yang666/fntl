# /Users/yangzijiang/backend-project/myapp/tasks/process_analog_data.py
import json
from django.core.cache import cache
from celery import shared_task
from myapp.models import AnalogData
from django.utils import timezone
from datetime import datetime

@shared_task
def process_analog_data(device_id, payload, timestamp_str=None):
    if timestamp_str:
        # 解析时间戳
        task_timestamp = datetime.fromisoformat(timestamp_str)
        current_time = timezone.now()
        time_difference = (current_time - task_timestamp).total_seconds()

        # 检查时间差，如果超过阈值则跳过任务
        TIMEOUT_THRESHOLD = 10  # 设置超时时间阈值为10秒
        if time_difference > TIMEOUT_THRESHOLD:
            print(f"Analog_data for device {device_id} timed out, skipping execution.")
            return

    try:
        # 确保 payload 是字节流，先检查它的类型
        if isinstance(payload, bytes):
            # 打印 payload 长度来调试
            print(f"Payload length: {len(payload)} bytes")
            # 确保数据的长度足够
            if len(payload) >= 12:
                voltage_1 = int.from_bytes(payload[4:6], byteorder='big') / 100.0
                current_1 = int.from_bytes(payload[6:8], byteorder='big') / 100.0
                voltage_2 = int.from_bytes(payload[8:10], byteorder='big') / 100.0
                current_2 = int.from_bytes(payload[10:12], byteorder='big') / 100.0

                print(f"Analog data: Voltage1: {voltage_1}, Current1: {current_1}, Voltage2: {voltage_2}, Current2: {current_2}")
            else:
                print(f"Payload is too short to process analog data: {len(payload)} bytes")
        else:
            print(f"Invalid payload data type: {type(payload)}")
    except Exception as e:
        print(f"Error processing analog data: {e}")

    VOLTAGE_THRESHOLD = 500

    if voltage_1 > VOLTAGE_THRESHOLD and voltage_2 > VOLTAGE_THRESHOLD:
        print(f"Both voltages too high for device {device_id}, skipping Redis update.")
        return
    if voltage_1 > VOLTAGE_THRESHOLD:
        print(f"Voltage 1 too high for device {device_id}, setting to 0.")
        voltage_1 = 0
    if voltage_2 > VOLTAGE_THRESHOLD:
        print(f"Voltage 2 too high for device {device_id}, setting to 0.")
        voltage_2 = 0
    if voltage_1 <= 1 and voltage_2 <= 1:
        # 如果两个电压都小于等于1V，则不保存到数据库
        print(f"Both voltages too low for device {device_id}, not saving to database.")
        return

    # 保存到数据库
    AnalogData.objects.create(device_id=device_id, voltage_1=voltage_1, current_1=current_1,
                            voltage_2=voltage_2, current_2=current_2)
    print(f"Processed analog data for device {device_id}")

    # 写入 Redis
    value = {
        'voltage_1': voltage_1,
        'current_1': current_1,
        'voltage_2': voltage_2,
        'current_2': current_2,
    }
    redis_key = f'device_{device_id}_analog_status'
    cache.set(redis_key, json.dumps(value), timeout=5)
    print(f"Stored analog data for device {device_id} in Redis")
