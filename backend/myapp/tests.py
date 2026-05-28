import struct
import unittest

from .udp_sender import create_packet


class CreatePacketTests(unittest.TestCase):
    def test_direction_command_uses_fixed_address_and_operation_byte(self):
        packet = create_packet(address=0x12, function_code=0x01, unix_time=0x12345678, operation=0x03)

        self.assertEqual(packet, bytes.fromhex("7F 7F 01 01 FF FF FF FF 03 00 00 00 01 04 F7 F7"))

    def test_set_time_command_uses_unix_time_and_zeroed_operation_bytes(self):
        packet = create_packet(address=0x12, function_code=0x03, unix_time=0x12345678, operation=0x09)

        self.assertEqual(packet[:4], bytes.fromhex("7F 7F 01 03"))
        self.assertEqual(packet[4:8], struct.pack("<I", 0x12345678))
        self.assertEqual(packet[8:12], bytes.fromhex("00 00 00 00"))
        self.assertEqual(packet[12:14], bytes.fromhex("18 01"))
        self.assertEqual(packet[14:16], bytes.fromhex("F7 F7"))

    def test_set_send_period_command_uses_byte_nine(self):
        packet = create_packet(address=0x12, function_code=0x04, unix_time=0x12345678, operation=0x0A)

        self.assertEqual(packet, bytes.fromhex("7F 7F 01 04 FF FF FF FF 00 0A 00 00 0B 04 F7 F7"))

    def test_reset_network_board_command_uses_protocol_defaults(self):
        packet = create_packet(address=0x12, function_code=0x05, unix_time=0x12345678, operation=0x99)

        self.assertEqual(packet, bytes.fromhex("7F 7F 01 05 FF FF FF FF 00 00 00 00 02 04 F7 F7"))

    def test_reconnect_command_uses_protocol_defaults(self):
        packet = create_packet(address=0x12, function_code=0x0B, unix_time=0x12345678, operation=0x11)

        self.assertEqual(packet, bytes.fromhex("7F 7F 01 0B FF FF FF FF 00 00 00 00 08 04 F7 F7"))

    def test_unknown_function_code_keeps_fixed_address_and_default_payload(self):
        packet = create_packet(address=0x12, function_code=0x21, unix_time=0x12345678, operation=0x7F)

        self.assertEqual(packet[:4], bytes.fromhex("7F 7F 01 21"))
        self.assertEqual(packet[4:8], bytes.fromhex("FF FF FF FF"))
        self.assertEqual(packet[8:12], bytes.fromhex("00 00 00 00"))
        self.assertEqual(packet[14:16], bytes.fromhex("F7 F7"))
