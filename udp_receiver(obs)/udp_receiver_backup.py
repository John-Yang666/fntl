import json
import os
import threading
import logging
import time
from datetime import datetime, timezone
import requests
from celery import Celery
import redis
import hashlib

# 日志设置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

# Celery 配置
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery(broker=CELERY_BROKER_URL)

# Redis 连接参数
REDIS_HOST = "host.docker.internal"  # 根据您的实际情况修改
REDIS_HOST2 = "redis"  # 根据您的实际情况修改
REDIS_HOST3 = "127.0.0.1"  # 根据您的实际情况修改
REDIS_PORT = 6379

# 连接 Redis
redis_client = redis.Redis(host=REDIS_HOST2, port=REDIS_PORT, db=1, decode_responses=False)  # 缓存
redis_client2 = redis.Redis(host=REDIS_HOST2, port=REDIS_PORT, db=2, decode_responses=True)  # 时间记录

# 全局变量
packet_count = 0
packet_count_lock = threading.Lock()
device_cache = {}
last_packet_time = datetime.now(timezone.utc)  # 设置为 UTC 时间
should_exit = threading.Event()

# 配置参数
LAST_COMMUNICATION_TIME_TIMEOUT = 3600  # 最后通信时间缓存时长，影响到设备离线告警持续时长
SWITCH_DATA_TIMEOUT = 60  # 模拟量数据缓存 60 秒，即使数据包内容不变也每分钟发一次数据包给 Celery 避免意外故障
HEARTBEAT_TIMEOUT = int(os.getenv("HEARTBEAT_TIMEOUT", 10))
HEARTBEAT_IDENTIFIER = b'\xAA\xBB'

DEVICE_API_URL = os.getenv("DEVICE_API_URL", "http://web:8000/api/devices-list/")

def preload_device_cache():
    """
    从外部 API 加载设备信息，并将设备 ID 缓存到内存中。
    如果加载失败或者设备信息为空，每隔 5 秒重新尝试加载，直到成功为止。
    """
    global device_cache
    while True:
        try:
            response = requests.get(DEVICE_API_URL, timeout=5)
            if response.status_code == 200:
                devices = response.json()
                if isinstance(devices, dict):
                    all_devices = []
                    for line_name, line_devices in devices.items():
                        all_devices.extend(line_devices)
                    device_cache = {device["device_id"] for device in all_devices}
                elif isinstance(devices, list):
                    device_cache = {device["device_id"] for device in devices}
                
                if device_cache:
                    logger.info(f"Preloaded {len(device_cache)} device IDs into memory cache")
                    break  # 设备信息加载成功，跳出循环
                else:
                    logger.warning("Device cache is empty, retrying...")
            else:
                logger.error(f"Failed to load devices from API: {response.status_code}, retrying...")
        except Exception as e:
            logger.error(f"Error loading devices from API: {e}, retrying...")
        
        # 如果加载失败或设备信息为空，等待 5 秒后重试
        time.sleep(5)

def send_task_to_celery(device_id, data, timestamp, task_name):
    """
    通过 Celery 发送任务。根据任务类型发送给不同的 Celery 任务。
    """
    try:
        # 如果 data 是字典类型，确保把它转换成字节流数据
        if isinstance(data, dict):
            data = json.dumps(data).encode('utf-8')  # 将字典转换为字节流
        
        celery_app.send_task(
            task_name,
            args=[device_id, data, timestamp.isoformat()]  # 使用 ISO 格式传递时间戳
        )
        logger.info(f"Task sent to Celery for device {device_id} using {task_name}")
    except Exception as e:
        logger.error(f"Failed to send task to Celery: {e}")

def calculate_packet_hash(data):
    """
    计算数据包的哈希值，用于判断数据包是否重复。
    """
    return hashlib.sha256(data).hexdigest()

def handle_packet(data):
    """
    处理接收到的数据包。
    """
    global packet_count

    # 从 address 字节中提取设备 ID，并转换为整数
    device_id = int.from_bytes(data[2:3], byteorder='big')  # 假设设备ID在data[2]位置
    if device_id not in device_cache:
        logger.error(f"Device ID {device_id} not found in cache. Ignoring packet.")
        return

    # 检查数据帧类型
    frame_head = data[0:2]
    frame_tail = data[-2:]

    if frame_head == b'\x7F\x7F' and frame_tail == b'\xF7\xF7':
        current_time = datetime.now(timezone.utc)  # 使用 UTC 时间
        packet_hash = calculate_packet_hash(data)  # 计算数据包的哈希值

        # 更新最后通信时间
        #global last_packet_time
        #last_packet_time = current_time  # 更新为当前时间
        # 写入 Redis 缓存最后一次通信时间
        redis_key_time = f"device_{device_id}_last_communication_time"
        redis_client2.set(redis_key_time, current_time.isoformat(), ex=LAST_COMMUNICATION_TIME_TIMEOUT)  # 存储 ISO 格式时间

        # 记录包处理计数
        with packet_count_lock:
            packet_count += 1

        # 处理数据包
        if len(data) == 54:
            # 写入 Redis 缓存：更新最后接收到的数据包哈希值
            redis_key_hash = f"device_{device_id}_last_switch_packet_hash"
            redis_client.set(redis_key_hash, packet_hash.encode(), ex=SWITCH_DATA_TIMEOUT)  # 缓存 60 秒
            # 数据送到 Celery Worker 处理开关量数据
            send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_switch_data.process_switch_data")
            logger.info(f"Switch data from device {device_id} sent to Celery.")
        
        elif len(data) == 20:
            # 直接将模拟量数据传递给 process_analog_data
            send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_analog_data.process_analog_data")
            logger.info(f"Analog data from device {device_id} sent to Celery.")
        else:
            logger.error(f"Unknown data length ({len(data)}) from device_id_ {device_id}")
    else:
        logger.error(f"Unknown packet type from device_id_ {device_id}")

def print_packet_count():
    """
    每秒打印一次处理的包数量。
    """
    global packet_count
    while not should_exit.is_set():
        time.sleep(1)
        with packet_count_lock:
            logger.info(f"Received {packet_count} packets in the last second")
            packet_count = 0

def redis_heartbeat_listener():
    """
    监听 Redis 频道 'heartbeat'，接收心跳包并更新 last_packet_time。
    """
    global last_packet_time
    try:
        pubsub = redis_client.pubsub()
        pubsub.subscribe('heartbeat')
        logger.info("Subscribed to Redis channel 'heartbeat' for heartbeats")
        for message in pubsub.listen():
            if message['type'] == 'message':
                data = message['data']
                if data == HEARTBEAT_IDENTIFIER:
                    last_packet_time = datetime.now(timezone.utc)  # 更新心跳时的时间
                    logger.info("Heartbeat received via Redis")
    except Exception as e:
        logger.error(f"Redis heartbeat listener encountered an error: {e}")
        should_exit.set()
        exit(1)

def redis_packet_listener():
    """
    监听 Redis 频道 'packets'，接收数据包并处理
    """
    try:
        pubsub = redis_client.pubsub()
        pubsub.subscribe('udp_packets')
        logger.info("Subscribed to Redis channel 'packets' for UDP packets")
        for message in pubsub.listen():
            if message['type'] == 'message':
                data = message['data']
                # 从数据中提取实际数据包
                handle_packet(data)
    except Exception as e:
        logger.error(f"Redis packet listener encountered an error: {e}")
        should_exit.set()
        exit(1)

def receiver():
    """
    启动 UDP 接收器。
    """
    preload_device_cache()

    # 启动包计数线程
    threading.Thread(target=print_packet_count, daemon=True).start()

    # 启动 Redis 心跳监听线程
    threading.Thread(target=redis_heartbeat_listener, daemon=True).start()

    # 启动 Redis 数据包监听线程
    threading.Thread(target=redis_packet_listener, daemon=True).start()

    # 主线程等待退出事件
    while not should_exit.is_set():
        time.sleep(1)
        # 检查心跳超时
        if (datetime.now(timezone.utc) - last_packet_time).total_seconds() > HEARTBEAT_TIMEOUT:
            logger.error("Heartbeat timeout! Exiting UDP receiver...")
            should_exit.set()
            exit(1)

    logger.info("UDP Receiver is shutting down.")

if __name__ == "__main__":
    receiver()
