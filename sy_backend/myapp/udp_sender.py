"""
历史兼容模块。

SY 下行命令已统一迁移到 `myapp.sy_command_sender` + Redis Streams。
这个旧模块保留包结构，避免外部脚本 import 直接失败，但不再提供 Kafka 发送能力。
"""

import struct


def create_packet(address, function_code, unix_time, operation):
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


def create_forward_packet(packet, target_ip):
    return f"{target_ip}\n".encode() + packet


def send_packet_via_kafka(packet, target_ip):
    raise RuntimeError(
        "Kafka sender has been removed from sy_backend. "
        "Use myapp.sy_command_sender.send_sy_frame_via_redis instead."
    )
