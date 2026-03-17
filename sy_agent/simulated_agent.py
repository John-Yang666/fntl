import time
import random
import redis
import threading

# 配置参数
SAME_PACKET_COUNT = 10  # 每个下位机发送相同数据包的次数
PACKET_INTERVAL = 1  # 每个下位机发送数据包的间隔时间（秒）
HEARTBEAT_INTERVAL = 2  # 心跳包发送间隔（秒）

# Redis 配置
REDIS_HOST = 'localhost'
REDIS_PORT = 6380
REDIS_CHANNEL = 'udp_packets'  # 数据包存储的 Redis 频道
HEARTBEAT_CHANNEL = 'heartbeat'  # 心跳包存储的 Redis 频道

# 固定的 IP 地址列表，用于模拟下位机
DEVICE_IPS = [
    "127.0.0.1",
    "172.21.0.1	",
    "192.168.31.167",
    "192.168.1.12",
    "192.168.1.13",
    "192.168.1.14",
    "192.168.1.15",
    "192.168.1.16",
    "192.168.29.84",
    "192.168.29.92",
    "192.168.29.100",
    "0.0.0.0",
    "0.0.0.1",
    "192.168.27.101",
    "192.168.27.93",
    "192.168.29.108",
    "0.0.0.2",
    "192.168.29.116",
    "192.168.28.181",
    "192.168.28.182",
    "192.168.29.126",
    "192.168.27.221",
    "192.168.27.213",
    "192.168.27.205",
    "192.168.27.197",
    "192.168.29.132",
    "192.168.29.140",
    "0.0.0.3",
    "192.168.27.123",
    "192.168.27.229",
    "192.168.27.237",
    "192.168.27.253",
    "192.168.27.245",
    "192.168.29.148",
    "192.168.29.156",
    "192.168.29.164",
    "192.168.29.172",
    "192.168.29.180",
    "192.168.29.188",
    "192.168.29.206",
    "192.168.29.196",
    "192.168.29.204",
    "192.168.29.212",
    "192.168.29.220",
    "192.168.29.228",
    "192.168.29.141",
    "192.168.31.140"
]


# 计算校验和
def calculate_checksum(data):
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder='little')

# 发送开关量数据包到 Redis
def send_switch_data_to_redis(source_ip, switch_data, count):
    frame_header = b'\x7f\x7f'  # 帧头
    frame_footer = b'\xf7\xf7'  # 帧尾
    address = b'\x01'
    function_code = b'\x00'  # 开关量数据包的功能码是 0x00
    checksum = calculate_checksum(address + function_code + switch_data)
    packet = frame_header + address + function_code + switch_data + checksum + frame_footer
    
    # 将数据包发布到 Redis 频道
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
    for _ in range(count):
        forward_packet = f"{source_ip}\n".encode() + packet  # 使用 source_ip
        redis_client.publish(REDIS_CHANNEL, forward_packet)
        print(f"Sent switch data from IP: {source_ip} to Redis")
        time.sleep(PACKET_INTERVAL)  # 等待指定间隔时间

# 发送心跳包到 Redis（定期发送）
def send_heartbeat_to_redis():
    heartbeat_identifier = b'\xAA\xBB'  # 心跳包标识符
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
    while True:
        redis_client.publish(HEARTBEAT_CHANNEL, heartbeat_identifier)
        print("Sent heartbeat to Redis")
        time.sleep(HEARTBEAT_INTERVAL)  # 等待指定的心跳包发送间隔时间

# 模拟下位机生成开关量数据包
def simulate_device(source_ip):
    while True:
        # 随机生成开关量数据包（46字节的数据）
        switch_data = random.getrandbits(368).to_bytes(46, byteorder='big')  # 46字节的开关量数据
        send_switch_data_to_redis(source_ip, switch_data, SAME_PACKET_COUNT)
        
        # 等待一定时间后继续生成数据包
        time.sleep(PACKET_INTERVAL)

def main():
    # 创建心跳包发送线程
    heartbeat_thread = threading.Thread(target=send_heartbeat_to_redis, daemon=True)
    heartbeat_thread.start()

    # 根据列表中的 IP 地址数量模拟下位机
    threads = []

    for source_ip in DEVICE_IPS:
        thread = threading.Thread(target=simulate_device, args=(source_ip,))
        threads.append(thread)
        thread.start()

    # 等待所有线程完成
    for thread in threads:
        thread.join()

if __name__ == "__main__":
    main()
