from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from myapp.models import ChangeBitEvent, Device, RelayAction, SwitchData
from myapp.tasks.extract_sy_alarms_task import build_sy_alarm_state
from sy_receiver import SyFrameMessage, process_message_batch
import sy_receiver


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "sy-tests",
    }
}


class FakeRedisPipeline:
    def __init__(self, store: dict):
        self.store = store
        self.commands = []

    def set(self, key, value, ex=None):
        self.commands.append(("set", key, value))
        return self

    def execute(self):
        for _, key, value in self.commands:
            self.store[key] = value
        self.commands = []


class FakeRedisClient:
    def __init__(self):
        self.store = {}

    def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def pipeline(self, transaction=False):
        return FakeRedisPipeline(self.store)

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


@override_settings(CACHES=TEST_CACHES)
class SyAlarmExtractionTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_cable_linkage_reads_neighbor_bytes_cache(self):
        Device.objects.create(
            device_id=1,
            name="本站设备",
            depot="A",
            line="L1",
            ip_address="10.0.0.1",
            direction1_cable_alarm_linkage=True,
            direction1_neighbor_id=2,
            direction1_neighbor_direction=1,
        )
        Device.objects.create(
            device_id=2,
            name="邻站设备",
            depot="A",
            line="L1",
            ip_address="10.0.0.2",
        )

        cache.set("device_2_switch_status", bytes([0x00, 0x00, 0x02, 0x00]), timeout=None)
        cache.set("device_2_switch_status_updated_at", "2026-03-17T10:00:00+08:00", timeout=None)

        current_time = timezone.make_aware(datetime(2026, 3, 17, 10, 0, 30))
        with patch("myapp.tasks.extract_sy_alarms_task.timezone.now", return_value=current_time):
            alarms = build_sy_alarm_state(
                device_id=1,
                status_bytes=bytes([0x00, 0x00, 0x02, 0x00]),
                previous_alarms={},
                current_time=current_time,
            )

        self.assertEqual(alarms[62]["bit_value"], 1)

@override_settings(CACHES=TEST_CACHES)
class SyReceiverBatchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.fake_redis = FakeRedisClient()
        self.redis_patcher = patch.object(sy_receiver, "redis_client2", self.fake_redis)
        self.redis_patcher.start()
        self.device = Device.objects.create(
            device_id=1,
            name="测试设备",
            depot="A",
            line="L1",
            ip_address="10.0.0.1",
        )
        sy_receiver.device_context_map = {
            1: {
                "device_id": 1,
                "name": "测试设备",
                "alarm_filters": set(),
                "direction1_enabled": True,
                "direction2_enabled": True,
                "direction3_enabled": False,
                "direction1_neighbor_id": 0,
                "direction1_neighbor_direction": 2,
                "direction2_neighbor_id": 0,
                "direction2_neighbor_direction": 1,
                "direction1_cable_alarm_linkage": False,
                "direction2_cable_alarm_linkage": False,
            }
        }

    def tearDown(self):
        self.redis_patcher.stop()

    def _message(self, *, cmd: str, payload: bytes, monotonic: float):
        from django.utils import timezone

        return SyFrameMessage(
            entry_id=f"id-{monotonic}",
            nms_id=1,
            serial_id=1,
            line_id="L1",
            port="P1",
            frame_bytes=b"\x7F\x7F\x01" + (b"\xA1" if cmd == "A1" else b"\xA2") + payload + b"\xF7\xF7",
            cmd=cmd,
            payload=payload,
            received_at=timezone.now(),
            received_monotonic=monotonic,
        )

    def test_a1_dedup_within_batch(self):
        payload = bytes([0x00, 0x00, 0x00, 0x00])
        metrics = process_message_batch(
            [
                self._message(cmd="A1", payload=payload, monotonic=1.0),
                self._message(cmd="A1", payload=payload, monotonic=1.1),
            ]
        )

        self.assertEqual(SwitchData.objects.count(), 1)
        self.assertEqual(metrics["dedup"], 1)
        self.assertEqual(cache.get("device_1_switch_status"), payload)

    def test_a2_updates_snapshot_and_logs_change(self):
        cache.set("device_1_switch_status", b"\x00\x00\x00\x00", timeout=None)
        payload = bytes([0x84, 0x00])

        metrics = process_message_batch([self._message(cmd="A2", payload=payload, monotonic=2.0)])

        self.assertEqual(metrics["switch_rows"], 1)
        self.assertEqual(SwitchData.objects.count(), 1)
        self.assertEqual(ChangeBitEvent.objects.count(), 1)
        self.assertEqual(RelayAction.objects.count(), 1)
        self.assertEqual(cache.get("device_1_switch_status"), b"\x10\x00\x00\x00")
