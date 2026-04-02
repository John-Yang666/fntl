from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from myapp.models import AlarmActive, ChangeBitEvent, Device, RelayAction, SwitchData
from myapp.tasks.extract_sy_alarms_task import build_sy_alarm_state
from sy_receiver import SyFrameMessage, process_message_batch
import sy_receiver
import sy_summarize_alarms_container as sy_summarize


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
        sy_receiver.worker_state["switch_status_by_device"].clear()
        sy_receiver.worker_state["loaded_switch"].clear()
        sy_receiver.worker_state["last_a1_by_device"].clear()
        sy_receiver.worker_state["loaded_a1"].clear()

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
        with patch("myapp.tasks.extract_sy_alarms_task.build_sy_alarm_state") as build_alarm_mock, patch(
            "myapp.tasks.topology_processing.process_topology_status"
        ) as topology_mock:
            metrics = process_message_batch(
                [
                    self._message(cmd="A1", payload=payload, monotonic=1.0),
                    self._message(cmd="A1", payload=payload, monotonic=1.1),
                ]
            )

        self.assertEqual(SwitchData.objects.count(), 1)
        self.assertEqual(metrics["dedup"], 1)
        self.assertEqual(cache.get("device_1_switch_status"), payload)
        build_alarm_mock.assert_not_called()
        topology_mock.assert_not_called()

    def test_a2_updates_snapshot_and_logs_change(self):
        cache.set("device_1_switch_status", b"\x00\x00\x00\x00", timeout=None)
        payload = bytes([0x84, 0x00])

        metrics = process_message_batch([self._message(cmd="A2", payload=payload, monotonic=2.0)])

        self.assertEqual(metrics["switch_rows"], 1)
        self.assertEqual(SwitchData.objects.count(), 1)
        self.assertEqual(ChangeBitEvent.objects.count(), 1)
        self.assertEqual(RelayAction.objects.count(), 1)
        self.assertEqual(cache.get("device_1_switch_status"), b"\x10\x00\x00\x00")


@override_settings(CACHES=TEST_CACHES)
class SySummarizeIterationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.fake_redis = FakeRedisClient()
        self.redis_patcher = patch.object(sy_summarize, "redis_client", self.fake_redis)
        self.redis_patcher.start()
        Device.objects.create(
            device_id=1,
            name="测试设备",
            depot="A",
            line="L1",
            ip_address="10.0.0.1",
        )

    def tearDown(self):
        self.redis_patcher.stop()

    def test_switch_status_change_recomputes_alarm_cache_and_pushes_topology(self):
        now = timezone.make_aware(datetime(2026, 3, 24, 12, 0, 10))
        switch_status = bytes([0x00, 0x00, 0x00, 0x00])
        cache.set("device_1_switch_status", switch_status, timeout=None)
        cache.set("device_1_switch_status_updated_at", now.isoformat(), timeout=None)
        self.fake_redis.set("device_1_last_communication_time", now.isoformat())
        self.fake_redis.set("device_1_last_communication_monotonic", "100.0")

        with patch.object(sy_summarize, "SUMMARY_DEVICE_CACHE_REFRESH_SEC", 30), patch(
            "sy_summarize_alarms_container.timezone.now", return_value=now
        ), patch("sy_summarize_alarms_container.time.monotonic", return_value=105.0), patch(
            "sy_summarize_alarms_container.process_topology_status",
            return_value={"device_id": 1, "device_status": "good"},
        ) as topology_mock:
            state = sy_summarize.summarize_alarms_iteration({})

        self.assertIsNotNone(cache.get("device_1_alarms"))
        self.assertIsNotNone(cache.get("device_1_alarms_updated_at"))
        self.assertEqual(state["last_switch_updated_at_by_device"][1], now.isoformat())
        topology_mock.assert_called_once()

    def test_no_switch_change_skips_recompute_on_next_iteration(self):
        now = timezone.make_aware(datetime(2026, 3, 24, 12, 0, 10))
        switch_status = bytes([0x00, 0x00, 0x00, 0x00])
        cache.set("device_1_switch_status", switch_status, timeout=None)
        cache.set("device_1_switch_status_updated_at", now.isoformat(), timeout=None)
        self.fake_redis.set("device_1_last_communication_time", now.isoformat())
        self.fake_redis.set("device_1_last_communication_monotonic", "100.0")

        with patch.object(sy_summarize, "SUMMARY_DEVICE_CACHE_REFRESH_SEC", 30), patch(
            "sy_summarize_alarms_container.timezone.now", return_value=now
        ), patch("sy_summarize_alarms_container.time.monotonic", return_value=105.0), patch(
            "sy_summarize_alarms_container.process_topology_status",
            return_value={"device_id": 1, "device_status": "good"},
        ):
            state = sy_summarize.summarize_alarms_iteration({})
        cache.set("device_1_topology_status", {"device_id": 1, "device_status": "good"}, timeout=None)

        later = timezone.make_aware(datetime(2026, 3, 24, 12, 0, 11))
        with patch.object(sy_summarize, "SUMMARY_DEVICE_CACHE_REFRESH_SEC", 30), patch(
            "sy_summarize_alarms_container.timezone.now", return_value=later
        ), patch("sy_summarize_alarms_container.time.monotonic", return_value=106.0), patch(
            "sy_summarize_alarms_container.build_sy_alarm_state"
        ) as build_alarm_mock, patch(
            "sy_summarize_alarms_container.process_topology_status",
            return_value={"device_id": 1, "device_status": "good"},
        ) as topology_mock:
            sy_summarize.summarize_alarms_iteration(state)

        build_alarm_mock.assert_not_called()
        topology_mock.assert_not_called()

    def test_comm_timeout_raises_alarm_zero_and_bad_topology(self):
        stale_time = timezone.make_aware(datetime(2026, 3, 24, 12, 0, 0))
        now = timezone.make_aware(datetime(2026, 3, 24, 12, 5, 0))
        self.fake_redis.set("device_1_last_communication_time", stale_time.isoformat())
        self.fake_redis.set("device_1_last_communication_monotonic", "0.0")

        with patch.object(sy_summarize, "SUMMARY_DEVICE_CACHE_REFRESH_SEC", 30), patch(
            "sy_summarize_alarms_container.timezone.now", return_value=now
        ), patch("sy_summarize_alarms_container.time.monotonic", return_value=400.0), patch(
            "sy_summarize_alarms_container.process_topology_status",
            return_value={"device_id": 1, "device_status": "offline"},
        ) as topology_mock:
            sy_summarize.summarize_alarms_iteration({})

        self.assertTrue(AlarmActive.objects.filter(device_id=1, alarm_code=0).exists())
        topology_mock.assert_called_once()
        self.assertEqual(self.fake_redis.get("device_1_last_communication_time"), stale_time.isoformat())
        self.assertEqual(self.fake_redis.get("device_1_last_communication_monotonic"), "0.0")


@override_settings(CACHES=TEST_CACHES)
class SyTopologyProcessingTests(TestCase):
    def test_offline_alarm_maps_to_offline_topology(self):
        with patch("myapp.tasks.topology_processing.send_topology_update"), patch(
            "myapp.tasks.topology_processing.cache.set"
        ):
            from myapp.tasks.topology_processing import process_topology_status

            topology = process_topology_status(
                1,
                {
                    "device_id": 1,
                    "device_status": "offline",
                    "direction1_line_status": "bad",
                    "direction2_line_status": "bad",
                    "direction3_line_status": "bad",
                },
                device_context={
                    "direction1_enabled": True,
                    "direction2_enabled": True,
                    "direction3_enabled": True,
                },
            )

        self.assertEqual(topology["device_status"], "offline")
        self.assertEqual(topology["direction1_line_status"], "null")
        self.assertEqual(topology["direction2_line_status"], "null")
        self.assertEqual(topology["direction3_line_status"], "null")

    def test_non_direction3_device_maps_code_62_to_direction1_bad(self):
        topology = sy_summarize.build_topology_status_payload(
            device_id=1,
            device_context={
                "direction1_enabled": True,
                "direction2_enabled": True,
                "direction3_enabled": False,
            },
            alarms_of_this_device={62: {"bit_value": 1}},
            comm_ok=True,
        )

        self.assertEqual(topology["device_status"], "good")
        self.assertEqual(topology["direction1_line_status"], "bad")
        self.assertEqual(topology["direction2_line_status"], "good")
        self.assertEqual(topology["direction3_line_status"], "null")

    def test_non_direction3_device_maps_code_63_to_direction2_bad(self):
        topology = sy_summarize.build_topology_status_payload(
            device_id=1,
            device_context={
                "direction1_enabled": True,
                "direction2_enabled": True,
                "direction3_enabled": False,
            },
            alarms_of_this_device={63: {"bit_value": 1}},
            comm_ok=True,
        )

        self.assertEqual(topology["direction1_line_status"], "good")
        self.assertEqual(topology["direction2_line_status"], "bad")
        self.assertEqual(topology["direction3_line_status"], "null")

    def test_non_direction3_device_maps_62_and_63_to_two_bad_lines(self):
        topology = sy_summarize.build_topology_status_payload(
            device_id=1,
            device_context={
                "direction1_enabled": True,
                "direction2_enabled": True,
                "direction3_enabled": False,
            },
            alarms_of_this_device={
                62: {"bit_value": 1},
                63: {"bit_value": 1},
            },
            comm_ok=True,
        )

        self.assertEqual(topology["direction1_line_status"], "bad")
        self.assertEqual(topology["direction2_line_status"], "bad")
        self.assertEqual(topology["direction3_line_status"], "null")

    def test_direction3_device_keeps_62_63_on_direction3(self):
        topology = sy_summarize.build_topology_status_payload(
            device_id=1,
            device_context={
                "direction1_enabled": True,
                "direction2_enabled": True,
                "direction3_enabled": True,
            },
            alarms_of_this_device={62: {"bit_value": 1}},
            comm_ok=True,
        )

        self.assertEqual(topology["direction1_line_status"], "good")
        self.assertEqual(topology["direction2_line_status"], "good")
        self.assertEqual(topology["direction3_line_status"], "blink")

    def test_channel_fault_mapping_still_works_for_direction1_and_direction2(self):
        topology = sy_summarize.build_topology_status_payload(
            device_id=1,
            device_context={
                "direction1_enabled": True,
                "direction2_enabled": True,
                "direction3_enabled": False,
            },
            alarms_of_this_device={
                43: {"bit_value": 1},
                52: {"bit_value": 1},
            },
            comm_ok=True,
        )

        self.assertEqual(topology["direction1_line_status"], "blink")
        self.assertEqual(topology["direction2_line_status"], "blink")
        self.assertEqual(topology["direction3_line_status"], "null")


class SyAnalogApiRemovalTests(TestCase):
    def test_analog_api_routes_are_removed(self):
        self.assertEqual(self.client.get("/api/analog-data/").status_code, 404)
        self.assertEqual(self.client.get("/api/analog-status/1/").status_code, 404)
