from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from myapp import sy_command_sender
from myapp.sy_command_sender import (
    make_cmd_a1,
    make_cmd_a2,
    make_cmd_aa,
    make_cmd_bb,
    make_cmd_bb_named,
    make_cmd_cc,
    send_sy_frame_via_redis_stream,
)


class SyCommandSenderTests(TestCase):
    def test_a1_a2_bb_and_cc_frames_are_built_with_expected_command_bytes(self):
        self.assertEqual(make_cmd_a1(0x05), b"\x7f\x7f\x05\xa1\xf7")
        self.assertEqual(make_cmd_a2(0x05), b"\x7f\x7f\x05\xa2\xf7")
        self.assertEqual(make_cmd_cc(0x05), b"\x7f\x7f\x05\xcc\xf7")
        self.assertEqual(make_cmd_bb(0x05, 0x18), b"\x7f\x7f\x05\xbb\x18\x18\x18\x18\x18\xf7")
        self.assertEqual(make_cmd_bb_named(0x05, "UP_FORCE_CABLE"), b"\x7f\x7f\x05\xbb\x05\x05\x05\x05\x05\xf7")

    def test_aa_frame_includes_big_endian_seconds_and_checksum(self):
        frame = make_cmd_aa(datetime(2010, 1, 1, 0, 0, 2, tzinfo=timezone.utc))

        self.assertEqual(frame, b"\x7f\x7f\xff\xaa\x00\x00\x00\x02\xab\xf7")

    def test_send_sy_frame_via_redis_stream_writes_json_payload(self):
        fake_client = FakeRedisClient()

        with patch.object(sy_command_sender, "get_stream_client", return_value=fake_client), patch.object(
            sy_command_sender,
            "SY_CMD_STREAM",
            "sy-test-commands",
        ), patch.object(sy_command_sender, "SY_CMD_STREAM_MAXLEN", 500):
            send_sy_frame_via_redis_stream(
                device_id=12,
                addr=0x105,
                frame=b"\x7f\x7f\x05\xa1\xf7",
                command="A1",
                extra_meta={"line_id": 3},
            )

        self.assertEqual(fake_client.xadd_calls[0]["stream"], "sy-test-commands")
        self.assertEqual(fake_client.xadd_calls[0]["maxlen"], 500)
        payload = json.loads(fake_client.xadd_calls[0]["fields"]["data"])
        self.assertEqual(payload["device_id"], 12)
        self.assertEqual(payload["addr"], 5)
        self.assertEqual(payload["command"], "A1")
        self.assertEqual(payload["frame_hex"], "7f7f05a1f7")
        self.assertEqual(payload["meta"], {"line_id": 3})


class FakeRedisClient:
    def __init__(self) -> None:
        self.xadd_calls: list[dict[str, object]] = []

    def xadd(self, stream, fields, maxlen, approximate):
        self.xadd_calls.append(
            {
                "stream": stream,
                "fields": fields,
                "maxlen": maxlen,
                "approximate": approximate,
            }
        )
        return "1-0"
