import struct
from typing import Dict

FRAME_HEADER = b"\x7f\x7f"
FRAME_FOOTER = b"\xf7\xf7"
DEVICE_ADDRESS = b"\x01"


def checksum(payload: bytes) -> bytes:
    return struct.pack("<H", sum(payload) & 0xFFFF)


def build_switch_packet(switch_status: bytes) -> bytes:
    if len(switch_status) != 46:
        raise ValueError("BT switch_status must be exactly 46 bytes")
    payload = DEVICE_ADDRESS + b"\x00" + switch_status
    return FRAME_HEADER + payload + checksum(payload) + FRAME_FOOTER


def build_analog_packet(
    *,
    voltage_1: int,
    current_1: int,
    voltage_2: int,
    current_2: int,
    reserved: bytes = b"\x00\x00\x00\x00",
) -> bytes:
    if len(reserved) != 4:
        raise ValueError("reserved must be exactly 4 bytes")
    analog_data = struct.pack(">hhhh", voltage_1, current_1, voltage_2, current_2) + reserved
    payload = DEVICE_ADDRESS + b"\x01" + analog_data
    return FRAME_HEADER + payload + checksum(payload) + FRAME_FOOTER


def decode_analog_values(packet: bytes) -> Dict[str, float]:
    if len(packet) < 16:
        raise ValueError("BT analog packet is too short")
    return {
        "voltage_1": int.from_bytes(packet[4:6], "big", signed=True) / 100.0,
        "current_1": int.from_bytes(packet[6:8], "big", signed=True) / 100.0,
        "voltage_2": int.from_bytes(packet[8:10], "big", signed=True) / 100.0,
        "current_2": int.from_bytes(packet[10:12], "big", signed=True) / 100.0,
    }

