"""
历史兼容入口。

生产 SY ingestion 已统一切换到 sy_receiver.py + Redis Streams 批处理架构，
本文件仅保留作回溯参考，不再纳入 docker-compose-sy-prod.yml 的生产编排。
"""

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
from consts import (
    LAST_COMMUNICATION_TIME_TIMEOUT,
    SWITCH_DATA_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
)

# 日志设置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

# Celery 配置
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery(broker=CELERY_BROKER_URL)

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
# db=1 存放二进制(原始帧/去重键等)，db=2 存放可读字符串(最后通信时间等)
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

# === 计算数据包哈希值（用于排障/监控，可选） ===
def calculate_packet_hash(data):
    return hashlib.sha256(data).hexdigest()

# === 处理数据包（方案A：上一帧去重；重复包也计数 & 刷新心跳/最后通信时间）===
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

    if len(data) < 4:
        logger.error("数据长度不足，跳过处理")
        return

    # 设备ID获取策略：优先取地址字节；为0则用IP映射；非0需存在缓存
    try:
        device_id = int.from_bytes(data[2:3], byteorder='big')  # 地址字节
    except Exception:
        logger.error("解析设备ID失败，跳过处理")
        return

    if device_id == 0:
        device_id = get_device_id_by_ip(ip_address)
        if not device_id:
            logger.error(f"未在缓存中找到设备IP {ip_address} 对应的设备ID")
            return
    elif device_id not in device_cache.values():
        logger.error(f"设备ID {device_id} 不在缓存中")
        return

    # 帧头/尾校验
    frame_head = data[0:2]
    frame_tail = data[-2:]
    if not (frame_head == b'\x7F\x7F' and frame_tail == b'\xF7\xF7'):
        logger.error(f"格式错误数据来自设备 {device_id}")
        return

    # 计数：无论重复与否，一律 +1
    with packet_count_lock:
        packet_count += 1

    # 刷新心跳时间（无论重复与否）
    current_time = datetime.now(timezone.utc)
    last_packet_time = current_time
    try:
        redis_client2.set(
            f"device_{device_id}_last_communication_time",
            current_time.isoformat(),
            ex=LAST_COMMUNICATION_TIME_TIMEOUT
        )
    except Exception as e:
        logger.warning(f"更新最后通信时间失败：{e}")

    # === 上一帧去重（对整帧原始字节做完全一致比较） ===
    if len(data) == 54:
        last_ttl = SWITCH_DATA_TIMEOUT
    elif len(data) == 20:
        last_ttl = HEARTBEAT_TIMEOUT
    else:
        last_ttl = max(SWITCH_DATA_TIMEOUT, HEARTBEAT_TIMEOUT)

    last_raw_key = f"device:{device_id}:last_raw"
    try:
        prev_raw = redis_client.get(last_raw_key)
        if prev_raw is not None and prev_raw == data:
            # 重复包：到这里为止我们已经计数 & 刷新心跳/最后通信时间，跳过后续业务
            logger.info(f"[dedup] same as last packet -> counted & heartbeat refreshed, skip processing | device={device_id}, len={len(data)}")
            return
        # 新包：覆盖上一帧
        redis_client.set(last_raw_key, data, ex=last_ttl)
    except Exception as e:
        # 去重失败不影响后续处理，仅记录
        logger.warning(f"[dedup] Redis 读写异常：{e}")

    # === 业务分发（仅对“非重复包”执行） ===
    if len(data) == 54:
        # 可选：保留哈希用于排障/监控
        try:
            packet_hash = calculate_packet_hash(data)
            redis_client.set(
                f"device_{device_id}_last_switch_packet_hash",
                packet_hash.encode(),
                ex=SWITCH_DATA_TIMEOUT
            )
        except Exception as e:
            logger.debug(f"写入last_switch_packet_hash失败：{e}")
        send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_switch_data.process_switch_data")
    elif len(data) == 20:
        send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_analog_data.process_analog_data")
    else:
        logger.warning(f"未知长度数据（{len(data)}）来自设备 {device_id}")

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
    consumer = None  # 防止 finally 中未定义
    try:
        consumer = Consumer({
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'group.id': KAFKA_GROUP_ID,
            'auto.offset.reset': 'latest',  # 生产环境
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 1000,
            'session.timeout.ms': 6000,
            'heartbeat.interval.ms': 2000,
            'max.poll.interval.ms': 10000,
            # 'group.instance.id': 'udp-receiver-static',  # 如需静态成员可启用
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
    finally:
        if consumer is not None:
            try:
                consumer.close()   # 发送 LeaveGroup，立即 rebalance
                logger.info("Kafka consumer closed gracefully.")
            except Exception as close_err:
                logger.warning(f"Error while closing consumer: {close_err}")

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
