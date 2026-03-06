from __future__ import annotations

# udp_sender.py
import struct
import time
import os
from typing import TYPE_CHECKING, Optional

# =======================
# 回滚开关：默认 redis
# =======================
MSG_BUS_BACKEND = os.getenv("MSG_BUS_BACKEND", "redis").strip().lower()  # redis | kafka

# =======================
# Kafka 依赖：仅在 MSG_BUS_BACKEND=kafka 时需要
# =======================
try:
    from confluent_kafka import Producer as KafkaProducer
except Exception:
    KafkaProducer = None

if TYPE_CHECKING:
    from confluent_kafka import Producer as KafkaProducerType

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC_SUB", "udp-commands")

# =======================
# Redis 依赖：仅在 MSG_BUS_BACKEND=redis 时需要
# =======================
try:
    import redis as redis_lib
except Exception:
    redis_lib = None

REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_CMD_STREAM_KEY = "stream:udp:cmd"
REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "200000"))

# =======================
# 懒初始化（关键：import 阶段不触网）
# =======================
_kafka_producer: Optional["KafkaProducerType"] = None
_redis = None


def _get_kafka_producer() -> "KafkaProducerType":
    global _kafka_producer
    if _kafka_producer is None:
        if KafkaProducer is None:
            raise RuntimeError("MSG_BUS_BACKEND=kafka 但 confluent_kafka 未安装/不可用")
        _kafka_producer = KafkaProducer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    return _kafka_producer


def _get_redis():
    global _redis
    if _redis is None:
        if redis_lib is None:
            raise RuntimeError("MSG_BUS_BACKEND=redis 但 redis-py 未安装/不可用（pip install redis）")
        _redis = redis_lib.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
    return _redis


def create_packet(address, function_code, unix_time, operation) -> bytes:
    packet = bytearray(16)
    packet[0:2] = b"\x7F\x7F"
    packet[2] = address
    packet[3] = function_code
    packet[4:8] = struct.pack("<I", unix_time)
    packet[8] = operation
    packet[9:12] = b"\xFF\xFF\xFF"
    checksum = sum(packet[2:12]) & 0xFFFF
    packet[12:14] = struct.pack("<H", checksum)
    packet[14:16] = b"\xF7\xF7"
    return bytes(packet)


def create_forward_packet(packet: bytes, target_ip: str) -> bytes:
    return f"{target_ip}\n".encode() + packet


def delivery_report(err, msg):
    if err is not None:
        print(f"❌ Kafka 发送失败: {err}")
    else:
        print(f"✅ Kafka 发送成功: topic={msg.topic()}, partition={msg.partition()}, offset={msg.offset()}")


def send_packet(packet: bytes, target_ip: str) -> None:
    """
    统一发送接口：
      - MSG_BUS_BACKEND=kafka -> 发到 Kafka topic udp-commands（兼容旧格式 ip\\n + payload）
      - MSG_BUS_BACKEND=redis -> 写 Redis Stream（type=cmd, ip, payload）
    注意：不在 import 阶段连接任何外部服务。
    """
    backend = MSG_BUS_BACKEND

    if backend == "kafka":
        producer = _get_kafka_producer()
        forward_packet = create_forward_packet(packet, target_ip)

        for _ in range(3):
            producer.produce(KAFKA_TOPIC, value=forward_packet, callback=delivery_report)
            producer.poll(0)
            print(f"📤 已发送至 Kafka topic '{KAFKA_TOPIC}'，目标: {target_ip}")
            time.sleep(0.2)

        producer.flush()
        return

    if backend == "redis":
        r = _get_redis()

        # 可选：这里再 ping（失败只影响发送，不影响 Django/Celery 启动）
        # 如果你嫌每次发送都 ping 慢，可以注释掉这行
        r.ping()

        ts_ms = int(time.time() * 1000)
        fields = {
            b"type": b"cmd",
            b"src": b"udp_sender",
            b"ts": str(ts_ms).encode(),
            b"ip": target_ip.encode(),
            b"payload": packet,
        }
        r.xadd(
            name=REDIS_CMD_STREAM_KEY,
            fields=fields,
            maxlen=REDIS_STREAM_MAXLEN,
            approximate=True,
        )
        print(f"📤 已发送至 Redis stream '{REDIS_CMD_STREAM_KEY}'，目标: {target_ip}")
        return

    raise ValueError(f"未知 MSG_BUS_BACKEND={backend}，只能是 redis 或 kafka")


# 兼容旧名字：你 views.py / 老代码不需要改
def send_packet_via_kafka(packet: bytes, target_ip: str) -> None:
    return send_packet(packet, target_ip)


if __name__ == "__main__":
    target_ip = os.getenv("TARGET_IP", "192.168.1.100")
    address = int(os.getenv("ADDRESS", "1"))
    function_code = int(os.getenv("FUNCTION_CODE", "2"))
    unix_time = int(time.time())
    operation = int(os.getenv("OPERATION", "16"))

    packet = create_packet(address, function_code, unix_time, operation)
    send_packet(packet, target_ip)
