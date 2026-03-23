import json
import logging
import os
import time

import paho.mqtt.client as mqtt
import redis
from myapp.models import Device

logger = logging.getLogger(__name__)

# MQTT broker地址
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_SWITCH = "devices/switch"
MQTT_TOPIC_ANALOG = "devices/analog"

# 与 udp_receiver 一致：写入 packet stream，由 ingest 热路径统一处理
REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_PACKET_RAW_STREAM_KEY = os.getenv(
    "REDIS_PACKET_RAW_STREAM_KEY",
    os.getenv("REDIS_PACKET_STREAM_KEY", "stream:udp:packets"),
)
stream_redis = redis.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)


def enqueue_packet(ip_address: str, data_hex: str):
    ts_ms = int(time.time() * 1000)
    stream_redis.xadd(
        REDIS_PACKET_RAW_STREAM_KEY,
        {
            b"type": b"packet",
            b"src": b"mqtt_client",
            b"ts": str(ts_ms).encode(),
            b"ip": ip_address.encode(),
            b"data_hex": data_hex.encode(),
        },
    )


def on_connect(client, userdata, flags, rc):  # 在客户端连接到MQTT broker时调用，订阅相关主题。
    if rc == 0:
        logger.info("Connected to MQTT Broker!")
        client.subscribe(MQTT_TOPIC_SWITCH)
        client.subscribe(MQTT_TOPIC_ANALOG)
    else:
        logger.error("Failed to connect, return code %s", rc)


def on_message(client, userdata, msg):  # 在接收到消息时调用，解析消息并处理。
    try:
        payload = json.loads(msg.payload)
        ip_address = payload.get("ip_address")
        data_hex = payload.get("data")
        if not ip_address or not data_hex:
            return

        data = bytes.fromhex(data_hex)
        frame_head = data[0:2]
        frame_tail = data[-2:]
        if frame_head != b"\x7F\x7F" or frame_tail != b"\xF7\xF7":
            logger.error("Unknown packet type from IP address %s", ip_address)
            return

        if len(data) not in (20, 54):
            logger.error("Unknown data length (%s) from IP address %s", len(data), ip_address)
            return

        # 仅做轻量校验：若映射里无该设备，直接丢弃
        if not Device.objects.filter(ip_address=ip_address).exists():
            logger.error("No device found for IP address %s", ip_address)
            return

        enqueue_packet(ip_address, data_hex)
    except Exception as exc:
        logger.error("Error processing message: %s", exc)


client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message


def start_mqtt():  # 负责连接到MQTT broker并启动MQTT客户端的循环。
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
    except Exception as exc:
        logger.error("Failed to start MQTT client: %s", exc)
