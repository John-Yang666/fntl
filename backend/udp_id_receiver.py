import os
import sys

# 添加项目根路径（根据容器中映射的路径而定）
sys.path.append('/app')  # 容器中 /app 是 Django 项目根目录

# 设置 Django 配置模块
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

# 启动 Django 环境（只需最小 ORM 初始化）
import django
django.setup()

import json
import threading
import logging
import time
from datetime import datetime, timezone
from celery import Celery
import redis
import hashlib
from confluent_kafka import Consumer
from myapp.models import Device
from consts import LAST_COMMUNICATION_TIME_TIMEOUT, SWITCH_DATA_TIMEOUT, HEARTBEAT_TIMEOUT, PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL

# 日志设置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

# Celery 配置
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery(broker=CELERY_BROKER_URL)

# Redis 连接参数
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# 连接 Redis
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=False)  # 缓存
redis_client2 = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)  # 时间记录

# Kafka 连接参数
KAFKA_BOOTSTRAP_SERVERS = "kafka:9092"
KAFKA_TOPIC = "udp-packets"

# 全局变量
packet_count = 0
packet_count_lock = threading.Lock()
device_cache = set()
last_packet_time = datetime.now(timezone.utc)
should_exit = threading.Event()

# === 加载设备缓存 ===
def load_device_cache():
    try:
        devices = Device.objects.all()
        return {d.device_id for d in devices}
    except Exception as e:
        logger.error(f"Failed to load device info from DB: {e}")
        return set()

# === 周期性刷新设备缓存 ===
def periodic_device_cache_refresher(interval=PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL):
    global device_cache
    last_device_ids_hash = None
    while not should_exit.is_set():
        time.sleep(interval)
        new_cache = load_device_cache()
        new_hash = hash(frozenset(new_cache))
        if new_hash != last_device_ids_hash:
            device_cache = new_cache
            last_device_ids_hash = new_hash
            logger.info(f"[device_cache] Refreshed {len(device_cache)} device IDs from DB")

# === 发送任务到 Celery ===
def send_task_to_celery(device_id, data, timestamp, task_name):
    try:
        if isinstance(data, dict):
            data = json.dumps(data).encode('utf-8')
        celery_app.send_task(
            task_name,
            args=[device_id, data, timestamp.isoformat()]
        )
        logger.info(f"Task sent to Celery for device {device_id} using {task_name}")
    except Exception as e:
        logger.error(f"Failed to send task to Celery: {e}")

# === 计算数据包哈希值 ===
def calculate_packet_hash(data):
    return hashlib.sha256(data).hexdigest()

# === 数据包处理 ===
def handle_packet(data):
    global packet_count
    device_id = int.from_bytes(data[2:3], byteorder='big')
    if device_id not in device_cache:
        logger.error(f"Device ID {device_id} not found in cache. Ignoring packet.")
        return

    frame_head = data[0:2]
    frame_tail = data[-2:]

    if frame_head == b'\x7F\x7F' and frame_tail == b'\xF7\xF7':
        current_time = datetime.now(timezone.utc)
        packet_hash = calculate_packet_hash(data)

        global last_packet_time
        last_packet_time = current_time
        redis_key_time = f"device_{device_id}_last_communication_time"
        redis_client2.set(redis_key_time, current_time.isoformat(), ex=LAST_COMMUNICATION_TIME_TIMEOUT)

        with packet_count_lock:
            packet_count += 1

        if len(data) == 54:
            redis_key_hash = f"device_{device_id}_last_switch_packet_hash"
            redis_client.set(redis_key_hash, packet_hash.encode(), ex=SWITCH_DATA_TIMEOUT)
            send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_switch_data.process_switch_data")
            logger.info(f"Switch data from device {device_id} sent to Celery.")
        elif len(data) == 20:
            send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_analog_data.process_analog_data")
            logger.info(f"Analog data from device {device_id} sent to Celery.")
        else:
            logger.error(f"Unknown data length ({len(data)}) from device_id {device_id}")
    else:
        logger.error(f"Unknown packet type from device_id {device_id}")

# === 包处理计数打印 ===
def print_packet_count():
    global packet_count
    while not should_exit.is_set():
        time.sleep(1)
        with packet_count_lock:
            logger.info(f"Received {packet_count} packets in the last second")
            packet_count = 0

# === Kafka 消息监听器 ===
def kafka_packet_listener():
    try:
        consumer = Consumer({
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'auto.offset.reset': 'latest',
            'enable.auto.commit': True,
            'group.id': 'udp-id-receiver',
            'client.id': 'udp-consumer',  # 添加这一行避免配置污染
            'log.connection.close': False
        })
        consumer.subscribe([KAFKA_TOPIC])
        logger.info(f"Subscribed to Kafka topic '{KAFKA_TOPIC}'")
        while not should_exit.is_set():
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error(f"Kafka consumer error: {msg.error()}")
                continue
            data = msg.value()
            handle_packet(data)
    except Exception as e:
        logger.error(f"Kafka packet listener encountered an error: {e}")
        should_exit.set()
        exit(1)

# === 主程序入口 ===
def receiver():
    global device_cache
    device_cache = load_device_cache()
    logger.info(f"Initial preload of {len(device_cache)} devices")

    threading.Thread(target=periodic_device_cache_refresher, daemon=True).start()
    threading.Thread(target=print_packet_count, daemon=True).start()
    threading.Thread(target=kafka_packet_listener, daemon=True).start()

    while not should_exit.is_set():
        time.sleep(1)
        if (datetime.now(timezone.utc) - last_packet_time).total_seconds() > HEARTBEAT_TIMEOUT:
            logger.error("Heartbeat timeout! Exiting UDP receiver...")
            should_exit.set()
            exit(1)

    logger.info("UDP Receiver is shutting down.")

if __name__ == "__main__":
    receiver()