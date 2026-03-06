import os
import random
import struct
import threading
import time

import redis

# 配置参数
SAME_PACKET_COUNT = 100  # 每个下位机发送相同开关量数据包的次数
PACKET_INTERVAL = 1  # 每个下位机发送数据包的间隔时间（秒）
ANALOG_INTERVAL = 20  # 20字节模拟包发送间隔（秒）

# Redis Stream 配置（与 udp_receiver 对齐）
REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "127.0.0.1")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "36379"))
REDIS_PACKET_STREAM_KEY = os.getenv("REDIS_PACKET_STREAM_KEY", "stream:udp:packets")
REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "200000"))

# 固定的 IP 地址列表，用于模拟下位机
DEVICE_IPS = [f"192.168.10.{i}" for i in range(1, 201)]

redis_client = redis.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, db=0, decode_responses=False)


def calculate_checksum(data):
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder="little")


def publish_packet_to_stream(source_ip, packet):
    ts_ms = int(time.time() * 1000)
    fields = {
        b"type": b"packet",
        b"src": b"simulated_agent",
        b"ts": str(ts_ms).encode(),
        b"ip": source_ip.encode(),
        b"data_hex": packet.hex().encode(),
    }
    redis_client.xadd(
        name=REDIS_PACKET_STREAM_KEY,
        fields=fields,
        maxlen=REDIS_STREAM_MAXLEN,
        approximate=True,
    )


def build_switch_packet():
    frame_header = b"\x7f\x7f"
    frame_footer = b"\xf7\xf7"
    address = b"\x01"
    function_code = b"\x00"
    switch_data = random.getrandbits(368).to_bytes(46, byteorder="big")
    checksum = calculate_checksum(address + function_code + switch_data)
    return frame_header + address + function_code + switch_data + checksum + frame_footer


def build_analog_packet():
    frame_header = b"\x7f\x7f"
    frame_footer = b"\xf7\xf7"
    address = b"\x01"
    function_code = b"\x01"
    voltage_1 = random.randint(22000, 24000)
    current_1 = random.randint(-500, 500)
    voltage_2 = random.randint(22000, 24000)
    current_2 = random.randint(-500, 500)
    reserved = random.getrandbits(32).to_bytes(4, byteorder="big")
    analog_data = struct.pack(">hhhh", voltage_1, current_1, voltage_2, current_2) + reserved
    checksum = calculate_checksum(address + function_code + analog_data)
    return frame_header + address + function_code + analog_data + checksum + frame_footer


def send_switch_data(source_ip, count):
    packet = build_switch_packet()
    for _ in range(count):
        publish_packet_to_stream(source_ip, packet)
        time.sleep(PACKET_INTERVAL)


def simulate_device(source_ip):
    last_analog_ts = 0.0
    while True:
        send_switch_data(source_ip, SAME_PACKET_COUNT)

        now_ts = time.time()
        if now_ts - last_analog_ts >= ANALOG_INTERVAL:
            analog_packet = build_analog_packet()
            publish_packet_to_stream(source_ip, analog_packet)
            last_analog_ts = now_ts

        time.sleep(PACKET_INTERVAL)


def main():
    redis_client.ping()
    threads = []

    for source_ip in DEVICE_IPS:
        thread = threading.Thread(target=simulate_device, args=(source_ip,), daemon=True)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
