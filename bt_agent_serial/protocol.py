from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FrameResult:
    frame: bytes
    raw_data: bytes | None = None
    error: str | None = None


class ProtocolParser:
    def __init__(self, frame_len: int = 44) -> None:
        self.frame_len = int(frame_len)
        self._count = 0
        self._payload = bytearray()

    def feed(self, data: bytes) -> list[FrameResult]:
        results: list[FrameResult] = []
        for byte in data:
            result = self._feed_byte(byte)
            if result is not None:
                results.append(result)
        return results

    def _feed_byte(self, byte: int) -> FrameResult | None:
        if self._count in (0, 1):
            self._count = self._count + 1 if byte == 0x7F else 0
            return None

        if self._count == 2:
            if byte != 0x01:
                self._reset()
                return None
            self._count += 1
            self._payload.append(byte)
            return None

        self._count += 1
        self._payload.append(byte)
        if self._count < self.frame_len:
            return None

        payload = bytes(self._payload)
        self._reset()
        full_frame = b"\x7F\x7F" + payload
        return validate_frame(full_frame, self.frame_len)

    def _reset(self) -> None:
        self._count = 0
        self._payload.clear()


def validate_frame(frame: bytes, frame_len: int = 44) -> FrameResult:
    if len(frame) != frame_len:
        return FrameResult(frame=frame, error=f"invalid frame length: {len(frame)}")
    if frame[:2] != b"\x7F\x7F":
        return FrameResult(frame=frame, error="invalid frame head")
    if frame[2] != 0x01:
        return FrameResult(frame=frame, error="invalid function byte")
    if frame[-2:] != b"\xF7\xF7":
        return FrameResult(frame=frame, error="invalid frame tail")
    raw_data = frame[2:-2]
    if len(raw_data) != 40:
        return FrameResult(frame=frame, error=f"invalid raw data length: {len(raw_data)}")
    if not checksum_ok(raw_data):
        return FrameResult(frame=frame, error="checksum error")
    return FrameResult(frame=frame, raw_data=raw_data)


def checksum_ok(raw_data: bytes) -> bool:
    if len(raw_data) < 40:
        return False
    expected = raw_data[38] + (raw_data[39] << 8)
    actual = sum(raw_data[:38]) & 0xFFFF
    return expected == actual


def build_test_payload(raw_data: Iterable[int]) -> bytes:
    data = bytearray(raw_data)
    if len(data) != 40:
        raise ValueError("raw_data must contain exactly 40 bytes")
    checksum = sum(data[:38]) & 0xFFFF
    data[38] = checksum & 0xFF
    data[39] = (checksum >> 8) & 0xFF
    return bytes(data) + b"\xF7\xF7"


def build_test_frame(raw_data: Iterable[int]) -> bytes:
    return b"\x7F\x7F" + build_test_payload(raw_data)
