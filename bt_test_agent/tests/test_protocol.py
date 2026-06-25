import struct
import unittest

from bt_test_agent.frames import build_analog_packet, build_switch_packet, decode_analog_values
from bt_test_agent.streams import find_stream_entry


class BtFrameTests(unittest.TestCase):
    def test_switch_packet_uses_bt_frame_checksum_and_function_code(self):
        packet = build_switch_packet(bytes(range(46)))

        self.assertEqual(len(packet), 54)
        self.assertEqual(packet[:2], b"\x7f\x7f")
        self.assertEqual(packet[2], 0x01)
        self.assertEqual(packet[3], 0x00)
        self.assertEqual(packet[-2:], b"\xf7\xf7")
        self.assertEqual(packet[-4:-2], struct.pack("<H", sum(packet[2:-4]) & 0xFFFF))

    def test_analog_packet_encodes_expected_values(self):
        packet = build_analog_packet(
            voltage_1=1210,
            current_1=120,
            voltage_2=1200,
            current_2=110,
        )

        self.assertEqual(len(packet), 20)
        self.assertEqual(packet[3], 0x01)
        self.assertEqual(packet[-4:-2], struct.pack("<H", sum(packet[2:-4]) & 0xFFFF))
        self.assertEqual(
            decode_analog_values(packet),
            {"voltage_1": 12.1, "current_1": 1.2, "voltage_2": 12.0, "current_2": 1.1},
        )


class FakeRedis:
    def __init__(self, responses):
        self.responses = list(responses)
        self.xread_calls = []

    def xread(self, streams, count=None, block=None):
        self.xread_calls.append({"streams": streams, "count": count, "block": block})
        if self.responses:
            return self.responses.pop(0)
        return []


class BtStreamTests(unittest.TestCase):
    def test_find_stream_entry_reads_after_start_id_without_consumer_group(self):
        redis_client = FakeRedis(
            [
                [],
                [
                    (
                        b"stream:udp:cmd",
                        [
                            (b"10-1", {b"type": b"cmd", b"ip": b"192.168.91.101", b"payload": b"abc"}),
                        ],
                    )
                ],
            ]
        )

        entry_id, fields = find_stream_entry(
            redis_client,
            stream_name="stream:udp:cmd",
            start_id="10-0",
            predicate=lambda item: item.get(b"ip") == b"192.168.91.101",
            timeout_sec=0.2,
            block_ms=1,
        )

        self.assertEqual(entry_id, b"10-1")
        self.assertEqual(fields[b"payload"], b"abc")
        self.assertEqual(redis_client.xread_calls[0]["streams"], {"stream:udp:cmd": "10-0"})


if __name__ == "__main__":
    unittest.main()
