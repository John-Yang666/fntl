import json
import unittest

from sy_test_agent.frames import build_a1_response, build_a2_response
from sy_test_agent.streams import find_stream_entry, parse_command_payload


class SyFrameTests(unittest.TestCase):
    def test_a1_response_contains_status_bytes_and_checksum(self):
        frame = build_a1_response(serial_id=5, status=b"\x01\x02\x04\x08")

        self.assertEqual(frame, bytes.fromhex("7f 7f 05 a1 01 02 04 08 b5 f7 f7"))

    def test_a2_response_encodes_changed_bit_and_checksum(self):
        frame = build_a2_response(
            serial_id=5,
            status=b"\x01\x02\x04\x08",
            bit_index=12,
            new_value=1,
        )

        self.assertEqual(frame, bytes.fromhex("7f 7f 05 a2 01 02 04 08 8c 42 f7 f7"))


class FakeRedis:
    def __init__(self, responses):
        self.responses = list(responses)
        self.xread_calls = []

    def xread(self, streams, count=None, block=None):
        self.xread_calls.append({"streams": streams, "count": count, "block": block})
        if self.responses:
            return self.responses.pop(0)
        return []


class SyStreamTests(unittest.TestCase):
    def test_parse_command_payload_accepts_sy_command_json(self):
        payload = {
            "device_id": 9201,
            "addr": 241,
            "command": "BB_UP_FORCE_CABLE",
            "frame_hex": "7f7ff1bb0505050505f7",
            "meta": {"bb_name": "UP_FORCE_CABLE"},
        }

        command = parse_command_payload({"data": json.dumps(payload)})

        self.assertEqual(command.device_id, 9201)
        self.assertEqual(command.command, "BB_UP_FORCE_CABLE")
        self.assertEqual(command.frame, bytes.fromhex("7f7ff1bb0505050505f7"))
        self.assertEqual(command.meta["bb_name"], "UP_FORCE_CABLE")

    def test_find_stream_entry_reads_after_start_id_without_consumer_group(self):
        redis_client = FakeRedis(
            [
                [
                    (
                        "sy-serial-commands",
                        [
                            (
                                "15-1",
                                {"data": json.dumps({"device_id": 9201, "command": "A1", "frame_hex": "7f7ff1a1f7"})},
                            )
                        ],
                    )
                ]
            ]
        )

        entry_id, fields = find_stream_entry(
            redis_client,
            stream_name="sy-serial-commands",
            start_id="15-0",
            predicate=lambda item: parse_command_payload(item).device_id == 9201,
            timeout_sec=0.2,
            block_ms=1,
        )

        self.assertEqual(entry_id, "15-1")
        self.assertEqual(redis_client.xread_calls[0]["streams"], {"sy-serial-commands": "15-0"})


if __name__ == "__main__":
    unittest.main()
