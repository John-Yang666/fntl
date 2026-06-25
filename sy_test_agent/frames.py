FRAME_HEADER = b"\x7f\x7f"
FRAME_FOOTER = b"\xf7\xf7"


def _checksum(body: bytes) -> int:
    return sum(body) & 0xFF


def build_a1_response(*, serial_id: int, status: bytes) -> bytes:
    if len(status) != 4:
        raise ValueError("SY A1 status must be exactly 4 bytes")
    body = bytes([serial_id & 0xFF, 0xA1]) + status
    return FRAME_HEADER + body + bytes([_checksum(body)]) + FRAME_FOOTER


def build_a2_response(*, serial_id: int, status: bytes, bit_index: int, new_value: int) -> bytes:
    if len(status) != 4:
        raise ValueError("SY A2 status must be exactly 4 bytes")
    change = ((int(new_value) & 0x01) << 7) | (int(bit_index) & 0x7F)
    body = bytes([serial_id & 0xFF, 0xA2]) + status + bytes([change])
    return FRAME_HEADER + body + bytes([_checksum(body)]) + FRAME_FOOTER

