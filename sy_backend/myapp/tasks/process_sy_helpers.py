# process_sy_helpers.py

def get_sy_bit_value(data: bytes, byte_index: int, bit_index: int) -> int:
    """
    data       : A1 状态字的 4 个字节（B4~B7，对应 d1~d4）
    byte_index : 字节号，和文档一致，用 4/5/6/7 表示 B4/B5/B6/B7
    bit_index  : 位序号 0..7，对应 D0..D7（LSB 为 D0）
    """
    # B4 -> data[0], B5 -> data[1], B6 -> data[2], B7 -> data[3]
    idx = byte_index - 4
    if idx < 0 or idx >= len(data):
        return 0

    byte_value = data[idx]
    return (byte_value >> bit_index) & 1
