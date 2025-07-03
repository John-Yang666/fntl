import os
import sys
import json
import threading
import logging
import time
from datetime import datetime, timezone
from celery import Celery
import redis
import hashlib
from confluent_kafka import Consumer

# 添加 Django 项目路径
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
import django
django.setup()

from myapp.models import Device
from consts import LAST_COMMUNICATION_TIME_TIMEOUT, SWITCH_DATA_TIMEOUT, HEARTBEAT_TIMEOUT, PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL

# 日志设置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

# Celery 配置
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery(broker=CELERY_BROKER_URL)

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=False)
redis_client2 = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)

# Kafka 配置
KAFKA_BOOTSTRAP_SERVERS = "kafka:9092"
KAFKA_TOPIC = "udp-packets"
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "udp-id-receiver")

packet_count = 0
packet_count_lock = threading.Lock()
device_cache = {}
last_packet_time = datetime.now(timezone.utc)
should_exit = threading.Event()

# === 加载设备缓存 ===
def load_device_cache():
    try:
        devices = Device.objects.all()
        return {d.ip_address: d.device_id for d in devices}
    except Exception as e:
        logger.error(f"Failed to load device info from DB: {e}")
        return {}

# === 周期性刷新设备缓存 ===
def periodic_device_cache_refresher(interval=PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL):
    global device_cache
    last_hash = None
    while not should_exit.is_set():
        time.sleep(interval)
        new_cache = load_device_cache()
        new_hash = hash(frozenset(new_cache.items()))
        if new_hash != last_hash:
            device_cache = new_cache
            last_hash = new_hash
            logger.info(f"[device_cache] Refreshed {len(device_cache)} devices from DB")

# === 根据 IP 获取设备 ID ===
def get_device_id_by_ip(ip_address):
    return device_cache.get(ip_address)

# === 发送任务到 Celery ===
def send_task_to_celery(device_id, data, timestamp, task_name):
    try:
        if isinstance(data, dict):
            data = json.dumps(data).encode('utf-8')
        celery_app.send_task(task_name, args=[device_id, data, timestamp.isoformat()])
        logger.info(f"Task sent to Celery for device {device_id} using {task_name}")
    except Exception as e:
        logger.error(f"Failed to send task to Celery: {e}")

# === 计算数据包哈希值 ===
def calculate_packet_hash(data):
    return hashlib.sha256(data).hexdigest()

# === 处理数据包 ===
def handle_packet(json_data):
    global packet_count, last_packet_time
    try:
        obj = json.loads(json_data)
        ip_address = obj.get("ip")
        raw_hex = obj.get("data")
        data = bytes.fromhex(raw_hex)
    except Exception as e:
        logger.error(f"JSON解析失败: {e}")
        return

    if len(data) < 3:
        logger.error("数据长度不足，跳过处理")
        return

    device_id = int.from_bytes(data[2:3], byteorder='big')
    if device_id == 0:
        device_id = get_device_id_by_ip(ip_address)
        if not device_id:
            logger.error(f"未在缓存中找到设备IP {ip_address} 对应的设备ID")
            return
    elif device_id not in device_cache.values():
        logger.error(f"设备ID {device_id} 不在缓存中")
        return

    frame_head = data[0:2]
    frame_tail = data[-2:]
    if frame_head == b'\x7F\x7F' and frame_tail == b'\xF7\xF7':
        current_time = datetime.now(timezone.utc)
        packet_hash = calculate_packet_hash(data)
        last_packet_time = current_time
        redis_client2.set(f"device_{device_id}_last_communication_time", current_time.isoformat(), ex=LAST_COMMUNICATION_TIME_TIMEOUT)
        with packet_count_lock:
            packet_count += 1
        if len(data) == 54:
            redis_client.set(f"device_{device_id}_last_switch_packet_hash", packet_hash.encode(), ex=SWITCH_DATA_TIMEOUT)
            send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_switch_data.process_switch_data")
        elif len(data) == 20:
            send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_analog_data.process_analog_data")
        else:
            logger.warning(f"未知长度数据（{len(data)}）来自设备 {device_id}")
    else:
        logger.error(f"格式错误数据来自设备 {device_id}")

# === 每秒打印包数量 ===
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
            'group.id': KAFKA_GROUP_ID,
            'auto.offset.reset': 'latest',
            'enable.auto.commit': True
        })
        consumer.subscribe([KAFKA_TOPIC])
        logger.info(f"Subscribed to Kafka topic '{KAFKA_TOPIC}'")
        while not should_exit.is_set():
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error(f"Kafka error: {msg.error()}")
                continue
            handle_packet(msg.value())
    except Exception as e:
        logger.error(f"Kafka packet listener error: {e}")
        should_exit.set()

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

if __name__ == "__main__":
    receiver()
