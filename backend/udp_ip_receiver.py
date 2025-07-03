import os
import sys

# 添加 Django 项目路径
sys.path.append('/app')  # 容器中 /app 是 Django 项目根目录
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

# 初始化 Django
import django
django.setup()

import threading
import logging
import time
from datetime import datetime, timezone
from celery import Celery
from confluent_kafka import Consumer, Producer
from myapp.models import Device

# 参数配置
from consts import LAST_COMMUNICATION_TIME_TIMEOUT, SWITCH_DATA_TIMEOUT, HEARTBEAT_TIMEOUT, PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL

# 日志设置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

# Celery 配置
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery(broker=CELERY_BROKER_URL)

# Kafka 配置
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
KAFKA_TOPIC_PUB = 'udp-packets'
KAFKA_TOPIC_SUB = 'udp-commands'

producer = Producer({'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS})
consumer = Consumer({
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'group.id': 'udp-receiver-group',
    'auto.offset.reset': 'earliest'
})

# 全局状态
packet_count = 0
packet_count_lock = threading.Lock()
device_cache = {}
last_packet_time = datetime.now(timezone.utc)
should_exit = threading.Event()

# === 加载设备缓存 ===
def load_device_cache():
    try:
        devices = Device.objects.all()
        return {device.ip_address: device.device_id for device in devices}
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
def send_task_to_celery(device_id, data, timestamp):
    try:
        celery_app.send_task(
            "myapp.tasks.process_switch_data.process_switch_data",
            args=[device_id, data, timestamp.isoformat()]
        )
        logger.info(f"Task sent to Celery for device {device_id}")
    except Exception as e:
        logger.error(f"Failed to send task to Celery: {e}")

# === 处理数据包 ===
def handle_packet(data, addr):
    global packet_count
    ip_address = addr[0]
    device_id = get_device_id_by_ip(ip_address)
    if not device_id:
        logger.error(f"No device found for IP address {ip_address}")
        return

    frame_head = data[0:2]
    frame_tail = data[-2:]

    if frame_head == b'\x7F\x7F' and frame_tail == b'\xF7\xF7':
        current_time = datetime.now(timezone.utc)

        with packet_count_lock:
            packet_count += 1

        if len(data) == 54:
            send_task_to_celery(device_id, data, current_time)
        else:
            logger.error(f"Unknown data length ({len(data)}) from IP {ip_address}")
    else:
        logger.error(f"Unknown packet format from IP {ip_address}")

# === 每秒打印包数量 ===
def print_packet_count():
    global packet_count
    while not should_exit.is_set():
        time.sleep(1)
        with packet_count_lock:
            logger.info(f"Received {packet_count} packets in the last second")
            packet_count = 0

# === Kafka 消息监听 ===
def kafka_packet_listener():
    try:
        consumer.subscribe([KAFKA_TOPIC_PUB])
        logger.info(f"Subscribed to Kafka topic '{KAFKA_TOPIC_PUB}'")
        while not should_exit.is_set():
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error(f"Kafka consumer error: {msg.error()}")
                continue
            data = msg.value()
            if b'\n' not in data:
                logger.error("Malformed data from Kafka")
                continue
            header, payload = data.split(b'\n', 1)
            source_ip = header.decode().strip()
            addr = (source_ip, 0)
            handle_packet(payload, addr)
    except Exception as e:
        logger.error(f"Kafka listener error: {e}")
        should_exit.set()
    finally:
        consumer.close()

# === 主循环 ===
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

    logger.info("UDP Receiver is shutting down.")

if __name__ == "__main__":
    receiver()
