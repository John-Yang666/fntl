def get_switch_bit_value(data, byte_index, bit_index):
    byte_value = data[byte_index-4]
    return (byte_value >> bit_index) & 1