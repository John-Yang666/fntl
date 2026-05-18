from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
