from __future__ import annotations

import unittest
from unittest.mock import patch

from bt_agent_serial.bt_agent_serial import AgentStats, RedisPublisher
from bt_agent_serial.protocol import ProtocolParser, build_test_frame, build_test_payload, validate_frame


def sample_raw_data() -> bytes:
    data = bytearray([0] * 40)
    data[0] = 0x01
    data[1] = 0x22
    data[2] = 0x30
    data[3] = 0x01
    data[6] = 0x01
    data[11] = 0x0A
    data[19] = 0x0A
    data[27] = 0x0A
    data[35] = 0x0A
    return bytes(data)


class ProtocolParserTests(unittest.TestCase):
    def test_parser_discards_noise_and_extracts_frame(self) -> None:
        parser = ProtocolParser(frame_len=44)
        frame = build_test_frame(sample_raw_data())

        results = parser.feed(b"\x00\x55" + frame)

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].frame, frame)
        self.assertEqual(results[0].raw_data, frame[2:-2])

    def test_parser_extracts_multiple_frames_from_chunk(self) -> None:
        parser = ProtocolParser(frame_len=44)
        frame_a = build_test_frame(sample_raw_data())
        raw_b = bytearray(sample_raw_data())
        raw_b[7] = 0x40
        frame_b = build_test_frame(raw_b)

        results = parser.feed(frame_a + b"\x13\x37" + frame_b)

        self.assertEqual(len(results), 2)
        self.assertEqual([item.frame for item in results], [frame_a, frame_b])
        self.assertTrue(all(item.error is None for item in results))

    def test_checksum_error_is_reported(self) -> None:
        payload = bytearray(build_test_payload(sample_raw_data()))
        payload[38] ^= 0xFF
        frame = b"\x7F\x7F" + bytes(payload)

        result = validate_frame(frame)

        self.assertEqual(result.error, "checksum error")

    def test_invalid_tail_is_reported(self) -> None:
        frame = bytearray(build_test_frame(sample_raw_data()))
        frame[-1] = 0x00

        result = validate_frame(bytes(frame))

        self.assertEqual(result.error, "invalid frame tail")

    def test_redis_publisher_writes_required_stream_fields(self) -> None:
        frame = build_test_frame(sample_raw_data())
        fake_client = FakeRedisClient()
        fake_redis_module = FakeRedisModule(fake_client)
        config = {
            "device": {"nms_id": 123},
            "redis": {"host": "127.0.0.1", "port": 6379, "db": 0},
            "stream": {"packet_stream_key": "bt:packet", "packet_maxlen": 1000},
        }

        with patch("bt_agent_serial.bt_agent_serial.redis", fake_redis_module):
            publisher = RedisPublisher(config, AgentStats())
            publisher.publish(frame)

        self.assertEqual(fake_client.ping_count, 1)
        self.assertEqual(fake_client.xadd_calls[0]["name"], "bt:packet")
        self.assertEqual(fake_client.xadd_calls[0]["maxlen"], 1000)
        fields = fake_client.xadd_calls[0]["fields"]
        self.assertEqual(fields[b"type"], b"packet")
        self.assertEqual(fields[b"src"], b"bt_agent_serial")
        self.assertEqual(fields[b"data_hex"], frame.hex().encode())
        self.assertEqual(fields[b"device_id"], b"123")
        self.assertEqual(fields[b"nms_id"], b"123")


class FakeRedisClient:
    def __init__(self) -> None:
        self.ping_count = 0
        self.xadd_calls: list[dict[str, object]] = []

    def ping(self) -> bool:
        self.ping_count += 1
        return True

    def xadd(self, **kwargs):
        self.xadd_calls.append(kwargs)
        return b"1-0"


class FakeRedisModule:
    def __init__(self, client: FakeRedisClient) -> None:
        self.client = client

    def Redis(self, **_kwargs) -> FakeRedisClient:
        return self.client


if __name__ == "__main__":
    unittest.main()
