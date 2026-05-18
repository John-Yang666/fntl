from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import types
import unittest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_myapp = types.ModuleType("myapp")
fake_models = types.ModuleType("myapp.models")
fake_models.Device = object
fake_myapp.models = fake_models
sys.modules.setdefault("myapp", fake_myapp)
sys.modules.setdefault("myapp.models", fake_models)
fake_redis = types.ModuleType("redis")
fake_redis.Redis = object
sys.modules.setdefault("redis", fake_redis)

from ingest_common import (
    TESTDATA_SOURCE,
    build_testdata_alarms_state,
    decode_packet_fields,
    extract_testdata_relay_actions,
    parse_testdata_switch_status,
)


def sample_frame() -> bytes:
    raw = bytearray([0] * 40)
    raw[0] = 0x01
    raw[1] = 0x22
    raw[2] = 0x01
    raw[3] = 0x01
    raw[6] = 0x01
    raw[7] = 0x04
    raw[11] = 0x0A
    raw[19] = 0x0A
    raw[27] = 0x0A
    raw[35] = 0x0A
    checksum = sum(raw[:38]) & 0xFFFF
    raw[38] = checksum & 0xFF
    raw[39] = checksum >> 8
    return b"\x7F\x7F" + bytes(raw) + b"\xF7\xF7"


class BtAgentSerialIngestTests(unittest.TestCase):
    def test_decode_packet_fields_accepts_explicit_nms_id(self) -> None:
        frame = sample_frame()
        decoded, marker = decode_packet_fields(
            {
                b"type": b"packet",
                b"src": TESTDATA_SOURCE.encode(),
                b"ts": b"1",
                b"ip": b"0.0.0.0",
                b"data_hex": frame.hex().encode(),
                b"nms_id": b"123",
            }
        )

        self.assertIsNone(marker)
        self.assertEqual(decoded["explicit_device_id"], 123)
        self.assertEqual(decoded["source"], TESTDATA_SOURCE)

    def test_testdata_switch_status_and_alarms(self) -> None:
        switch_status = parse_testdata_switch_status(sample_frame())
        self.assertIsNotNone(switch_status)

        alarms = build_testdata_alarms_state(
            device_id=123,
            switch_status=switch_status,
            previous_alarms={},
            now_time=datetime.now(timezone.utc),
            now_monotonic=1.0,
            device_alarm_filters={},
        )

        self.assertEqual(alarms[8000]["bit_value"], 1)
        self.assertEqual(alarms[8010]["bit_value"], 1)
        self.assertEqual(alarms[8202]["bit_value"], 1)

    def test_testdata_relay_actions(self) -> None:
        switch_status = parse_testdata_switch_status(sample_frame())
        _current, actions = extract_testdata_relay_actions(
            {"I-A-ZDJ": 0},
            switch_status,
            datetime.now(timezone.utc),
        )

        self.assertEqual(actions[0][0], "I-A-ZDJ")
        self.assertEqual(actions[0][1], "吸起")


if __name__ == "__main__":
    unittest.main()
