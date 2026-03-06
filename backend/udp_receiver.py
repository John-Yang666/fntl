from __future__ import annotations

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

# Kafka（仅在 MSG_BUS_BACKEND=kafka 时需要）
try:
    from confluent_kafka import Consumer
except Exception:
    Consumer = None

# 添加 Django 项目路径
sys.path.append("/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa
django.setup()  # noqa

from myapp.models import Device  # noqa
from consts import (  # noqa
    LAST_COMMUNICATION_TIME_TIMEOUT,
    SWITCH_DATA_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
)

# 日志设置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

# ============================
# 回滚开关：默认 redis
# ============================
MSG_BUS_BACKEND = os.getenv("MSG_BUS_BACKEND", "redis").strip().lower()  # redis | kafka

# ============================
# Celery 配置
# ============================
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery(broker=CELERY_BROKER_URL)

# ============================
# 业务 Redis（你原来的 redis：db1/db2）
# ============================
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=False)
redis_client2 = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)

# ============================
# ✅ Redis Streams（双 stream）
# ============================
REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))

# ✅ 关键：从 stream:udp:bus 改为 stream:udp:packets
REDIS_PACKET_STREAM_KEY = os.getenv("REDIS_PACKET_STREAM_KEY", "stream:udp:packets")

# receiver 消费组配置（只针对 packet stream）
REDIS_PACKET_GROUP = os.getenv("REDIS_PACKET_GROUP", "udp-receiver-packet")
REDIS_PACKET_CONSUMER = os.getenv("REDIS_PACKET_CONSUMER", "udp-receiver-packet-0")
REDIS_STREAM_BLOCK_MS = int(os.getenv("REDIS_STREAM_BLOCK_MS", "2000"))
REDIS_STREAM_COUNT = int(os.getenv("REDIS_STREAM_COUNT", "200"))

# ============================
# Kafka 配置（回滚用）
# ============================
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "udp-packets")
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


def get_device_id_by_ip(ip_address):
    return device_cache.get(ip_address)


def send_task_to_celery(device_id, data, timestamp, task_name):
    try:
        if isinstance(data, dict):
            data = json.dumps(data).encode("utf-8")
        celery_app.send_task(task_name, args=[device_id, data, timestamp.isoformat()])
        logger.info(f"Task sent to Celery for device {device_id} using {task_name}")
    except Exception as e:
        logger.error(f"Failed to send task to Celery: {e}")


def calculate_packet_hash(data):
    return hashlib.sha256(data).hexdigest()


def handle_packet(json_data: bytes):
    """
    json_data: b'{"ip":"...","data":"<hex>"}'
    """
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

    # 设备ID获取策略：优先取地址字节；为0/1则用IP映射；非0需存在缓存
    try:
        device_id = int.from_bytes(data[2:3], byteorder="big")
    except Exception:
        logger.error("解析设备ID失败，跳过处理")
        return

    if device_id in [0, 1]:
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
    if not (frame_head == b"\x7F\x7F" and frame_tail == b"\xF7\xF7"):
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
            ex=LAST_COMMUNICATION_TIME_TIMEOUT,
        )
    except Exception as e:
        logger.warning(f"更新最后通信时间失败：{e}")

    # === 上一帧去重 ===
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
            logger.info(
                f"[dedup] same as last packet -> counted & heartbeat refreshed, skip processing | "
                f"device={device_id}, len={len(data)}"
            )
            return
        redis_client.set(last_raw_key, data, ex=last_ttl)
    except Exception as e:
        logger.warning(f"[dedup] Redis 读写异常：{e}")

    # === 业务分发（仅对“非重复包”执行） ===
    if len(data) == 54:
        try:
            packet_hash = calculate_packet_hash(data)
            redis_client.set(
                f"device_{device_id}_last_switch_packet_hash",
                packet_hash.encode(),
                ex=SWITCH_DATA_TIMEOUT,
            )
        except Exception as e:
            logger.debug(f"写入last_switch_packet_hash失败：{e}")
        send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_switch_data.process_switch_data")
    elif len(data) == 20:
        send_task_to_celery(device_id, data, current_time, "myapp.tasks.process_analog_data.process_analog_data")
    else:
        logger.warning(f"未知长度数据（{len(data)}）来自设备 {device_id}")


def print_packet_count():
    global packet_count
    while not should_exit.is_set():
        time.sleep(1)
        with packet_count_lock:
            logger.info(f"Received {packet_count} packets in the last second")
            packet_count = 0


def ensure_stream_group(r: "redis.Redis", stream_key: str, group_name: str):
    try:
        r.xgroup_create(name=stream_key, groupname=group_name, id="$", mkstream=True)
        logger.info(f"[redis] created group={group_name} on stream={stream_key}")
    except Exception as e:
        msg = str(e)
        if "BUSYGROUP" in msg or "Consumer Group name already exists" in msg:
            return
        logger.warning(f"[redis] ensure group error: {e}")


def redis_packet_listener():
    """
    ✅ 双 stream：只读 packet stream（stream:udp:packets）
    兼容两种字段：
      A) udp_agent 写：ip + data_hex
      B) 旧写法：type=packet + ip + data_hex
    """
    try:
        stream_redis = redis.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
        stream_redis.ping()

        ensure_stream_group(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)

        logger.info(
            f"[redis] Listening packet stream='{REDIS_PACKET_STREAM_KEY}' "
            f"group='{REDIS_PACKET_GROUP}' consumer='{REDIS_PACKET_CONSUMER}'"
        )

        while not should_exit.is_set():
            try:
                resp = stream_redis.xreadgroup(
                    groupname=REDIS_PACKET_GROUP,
                    consumername=REDIS_PACKET_CONSUMER,
                    streams={REDIS_PACKET_STREAM_KEY: b">"},
                    count=REDIS_STREAM_COUNT,
                    block=REDIS_STREAM_BLOCK_MS,
                )
            except Exception as e:
                msg = str(e)
                # ✅ 自愈：stream/group 被淘汰或重启后丢了
                if "NOGROUP" in msg:
                    logger.warning(f"[redis] NOGROUP -> recreate group then retry: {msg}")
                    ensure_stream_group(stream_redis, REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP)
                    time.sleep(0.2)
                    continue

                logger.error(f"[redis] xreadgroup error: {e}")
                time.sleep(0.5)
                continue

            if not resp:
                continue

            for _stream, entries in resp:
                for entry_id, fields in entries:
                    try:
                        # 如果存在 type 字段，要求是 packet；如果没有 type 字段，也视为 packet stream 正常消息
                        msg_type = fields.get(b"type", None)
                        if msg_type is not None and msg_type != b"packet":
                            stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, entry_id)
                            continue

                        ip_b = fields.get(b"ip", b"")
                        data_hex_b = fields.get(b"data_hex", b"")
                        if not ip_b or not data_hex_b:
                            stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, entry_id)
                            continue

                        ip_address = ip_b.decode(errors="ignore").strip()
                        raw_hex = data_hex_b.decode(errors="ignore").strip()
                        if not ip_address or not raw_hex:
                            stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, entry_id)
                            continue

                        json_bytes = json.dumps({"ip": ip_address, "data": raw_hex}).encode("utf-8")
                        handle_packet(json_bytes)

                        stream_redis.xack(REDIS_PACKET_STREAM_KEY, REDIS_PACKET_GROUP, entry_id)

                    except Exception as e:
                        logger.error(f"[redis] handle packet failed: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"[redis] packet listener fatal error: {e}")
        should_exit.set()


def kafka_packet_listener():
    if Consumer is None:
        logger.error("MSG_BUS_BACKEND=kafka 但 confluent_kafka 不可用")
        should_exit.set()
        return

    consumer = None
    try:
        consumer = Consumer(
            {
                "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
                "group.id": KAFKA_GROUP_ID,
                "auto.offset.reset": "latest",
                "enable.auto.commit": True,
                "auto.commit.interval.ms": 1000,
                "session.timeout.ms": 6000,
                "heartbeat.interval.ms": 2000,
                "max.poll.interval.ms": 10000,
            }
        )
        consumer.subscribe([KAFKA_TOPIC])
        logger.info(f"[kafka] Subscribed to Kafka topic '{KAFKA_TOPIC}'")

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
                consumer.close()
                logger.info("Kafka consumer closed gracefully.")
            except Exception as close_err:
                logger.warning(f"Error while closing consumer: {close_err}")


def receiver():
    global device_cache
    device_cache = load_device_cache()
    logger.info(f"Initial preload of {len(device_cache)} devices")

    threading.Thread(target=periodic_device_cache_refresher, daemon=True).start()
    threading.Thread(target=print_packet_count, daemon=True).start()

    if MSG_BUS_BACKEND == "kafka":
        threading.Thread(target=kafka_packet_listener, daemon=True).start()
        logger.info("Receiver backend = kafka")
    else:
        threading.Thread(target=redis_packet_listener, daemon=True).start()
        logger.info("Receiver backend = redis")

    while not should_exit.is_set():
        time.sleep(1)
        if (datetime.now(timezone.utc) - last_packet_time).total_seconds() > HEARTBEAT_TIMEOUT:
            logger.error("Heartbeat timeout! Exiting UDP receiver...")
            should_exit.set()


if __name__ == "__main__":
    receiver()