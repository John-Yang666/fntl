import struct
from django.core.cache import cache # type: ignore
import time

def create_packet(address, function_code, unix_time, operation):
    packet = bytearray(16)
    packet[0:2] = b'\x7F\x7F'
    packet[2] = address
    packet[3] = function_code
    packet[4:8] = struct.pack('<I', unix_time)
    packet[8] = operation
    packet[9:12] = b'\xFF\xFF\xFF'
    checksum = sum(packet[2:12]) & 0xFFFF
    packet[12:14] = struct.pack('<H', checksum)
    packet[14:16] = b'\xF7\xF7'
    return packet

def send_udp_packet(packet, target_ip, target_port=38316):
    # 将数据放入 Django 缓存
    for _ in range(3):  # 连续发送3次
        cache.set('udp_packet', packet)
        cache.set('udp_target_ip', target_ip)
        cache.set('udp_target_port', target_port)
        time.sleep(0.2)  # 间隔200毫秒