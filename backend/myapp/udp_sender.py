# udp_sender.py（使用 confluent-kafka）
import struct
import time
import os
from confluent_kafka import Producer

# Kafka 配置
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = "udp-commands"

# 初始化 Kafka Producer
producer = Producer({
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS
})

def create_packet(address, function_code, unix_time, operation):
    """
    创建一个自定义格式的数据包
    """
    packet = bytearray(16)
    packet[0:2] = b'\x7F\x7F'  # 固定头部
    packet[2] = address  # 地址
    packet[3] = function_code  # 功能码
    packet[4:8] = struct.pack('<I', unix_time)  # 时间戳，4 字节
    packet[8] = operation  # 操作码
    packet[9:12] = b'\xFF\xFF\xFF'  # 保留字段
    checksum = sum(packet[2:12]) & 0xFFFF  # 计算校验和
    packet[12:14] = struct.pack('<H', checksum)  # 校验和，2 字节
    packet[14:16] = b'\xF7\xF7'  # 固定尾部
    return packet

def create_forward_packet(packet, target_ip):
    """
    创建一个用于转发的封装数据包
    """
    forward_packet = f"{target_ip}\n".encode() + packet
    return forward_packet

def delivery_report(err, msg):
    if err is not None:
        print(f"❌ Kafka 发送失败: {err}")
    else:
        print(f"✅ Kafka 发送成功: topic={msg.topic()}, partition={msg.partition()}, offset={msg.offset()}")

def send_packet_via_kafka(packet, target_ip):
    """
    使用 Kafka 发布消息到指定 topic
    """
    forward_packet = create_forward_packet(packet, target_ip)

    for _ in range(3):  # 连续发送 3 次
        producer.produce(KAFKA_TOPIC, value=forward_packet, callback=delivery_report)
        producer.poll(0)  # 触发回调
        print(f"📤 数据包已发送至 Kafka topic '{KAFKA_TOPIC}'，目标: {target_ip}")
        time.sleep(0.2)

    producer.flush()  # 等待所有消息发送完成

if __name__ == "__main__":
    # 示例：创建并发送一个数据包
    target_ip = "192.168.1.100"  # 目标 IP
    address = 1                  # 地址
    function_code = 2           # 功能码
    unix_time = int(time.time()) # 当前时间戳
    operation = 0x10            # 操作码

    packet = create_packet(address, function_code, unix_time, operation)
    send_packet_via_kafka(packet, target_ip)
