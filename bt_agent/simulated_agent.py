import heapq
import os
import random
import struct
import time

import redis

# 配置参数
SAME_PACKET_COUNT = int(os.getenv("SAME_PACKET_COUNT", "10"))  # 每个下位机发送相同开关量数据包的次数
PACKET_INTERVAL = float(os.getenv("PACKET_INTERVAL", "1"))  # 每个下位机发送数据包的间隔时间（秒）
ANALOG_INTERVAL = float(os.getenv("ANALOG_INTERVAL", "2"))  # 20字节模拟包发送间隔（秒）
SIM_DEVICE_COUNT = int(os.getenv("SIM_DEVICE_COUNT", "200"))
SCHEDULER_MIN_SLEEP = float(os.getenv("SIM_MIN_SLEEP", "0.001"))

# Redis Stream 配置（与 udp_receiver 对齐）
REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "127.0.0.1")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "36379"))
REDIS_PACKET_STREAM_KEY = os.getenv("REDIS_PACKET_STREAM_KEY", "stream:udp:packets")
REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "100000"))

# 固定的 IP 地址列表，用于模拟下位机
DEVICE_IPS = [f"192.168.10.{i}" for i in range(1, SIM_DEVICE_COUNT + 1)]

redis_client = redis.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, db=0, decode_responses=False)


def calculate_checksum(data):
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder="little")


def publish_packet_to_stream(pipe, source_ip, packet):
    ts_ms = int(time.time() * 1000)
    fields = {
        b"type": b"packet",
        b"src": b"simulated_agent",
        b"ts": str(ts_ms).encode(),
        b"ip": source_ip.encode(),
        b"data_hex": packet.hex().encode(),
    }
    pipe.xadd(
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
    voltage_1 = random.randint(-24000, 24000)
    current_1 = random.randint(-500, 500)
    voltage_2 = random.randint(-24000, 24000)
    current_2 = random.randint(-500, 500)
    reserved = random.getrandbits(32).to_bytes(4, byteorder="big")
    analog_data = struct.pack(">hhhh", voltage_1, current_1, voltage_2, current_2) + reserved
    checksum = calculate_checksum(address + function_code + analog_data)
    return frame_header + address + function_code + analog_data + checksum + frame_footer


def init_devices(now):
    devices = []
    switch_heap = []
    analog_heap = []

    for idx, ip in enumerate(DEVICE_IPS):
        device = {
            "ip": ip,
            "switch_packet": build_switch_packet(),
            "remaining_same": SAME_PACKET_COUNT,
        }
        devices.append(device)

        first_switch = now + random.uniform(0, PACKET_INTERVAL)
        first_analog = now + random.uniform(0, ANALOG_INTERVAL)
        heapq.heappush(switch_heap, (first_switch, idx))
        heapq.heappush(analog_heap, (first_analog, idx))

    return devices, switch_heap, analog_heap


def next_switch_packet(device):
    if device["remaining_same"] <= 0:
        device["switch_packet"] = build_switch_packet()
        device["remaining_same"] = SAME_PACKET_COUNT
    device["remaining_same"] -= 1
    return device["switch_packet"]


def main():
    redis_client.ping()
    now = time.monotonic()
    devices, switch_heap, analog_heap = init_devices(now)

    while True:
        now = time.monotonic()
        pipe = redis_client.pipeline(transaction=False)
        queued = 0

        # 处理到期的开关量发送事件
        while switch_heap and switch_heap[0][0] <= now:
            due_at, idx = heapq.heappop(switch_heap)
            device = devices[idx]
            publish_packet_to_stream(pipe, device["ip"], next_switch_packet(device))
            queued += 1
            heapq.heappush(switch_heap, (due_at + PACKET_INTERVAL, idx))

        # 处理到期的模拟量发送事件
        while analog_heap and analog_heap[0][0] <= now:
            due_at, idx = heapq.heappop(analog_heap)
            device = devices[idx]
            publish_packet_to_stream(pipe, device["ip"], build_analog_packet())
            queued += 1
            heapq.heappush(analog_heap, (due_at + ANALOG_INTERVAL, idx))

        if queued:
            pipe.execute()

        next_due = min(switch_heap[0][0], analog_heap[0][0])
        sleep_for = max(SCHEDULER_MIN_SLEEP, next_due - time.monotonic())
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
