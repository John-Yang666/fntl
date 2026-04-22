from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from myapp.models import ChangeBitEvent, Depot, Device, Line, RawFrameLog, SwitchData
from myapp.tasks import cleanup_tasks


class SyCleanupTaskTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.depot = Depot.objects.create(name="测试车间")
        self.line = Line.objects.create(name="测试线路")
        self.device = Device.objects.create(
            device_id=1,
            name="测试设备",
            depot=self.depot,
            line=self.line,
            ip_address="10.0.0.1",
        )

    def _set_old_timestamp(self, model, pk, field_name="timestamp", *, days=40):
        old_time = timezone.now() - timedelta(days=days)
        model.objects.filter(pk=pk).update(**{field_name: old_time})
        return old_time

    def test_cleanup_raw_frame_log_exports_then_deletes_snapshot(self):
        with self.settings(CLEANUP_EXPORT_DIR=self.temp_dir.name):
            old_row = RawFrameLog.objects.create(device=self.device, cmd="A1", note="old", raw_frame=b"\x7f\x7f")
            self._set_old_timestamp(RawFrameLog, old_row.pk)
            new_row = RawFrameLog.objects.create(device=self.device, cmd="A2", note="new", raw_frame=b"\xf7\xf7")

            result = cleanup_tasks.cleanup_raw_frame_log(30)

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["deleted_count"], 1)
        self.assertFalse(RawFrameLog.objects.filter(pk=old_row.pk).exists())
        self.assertTrue(RawFrameLog.objects.filter(pk=new_row.pk).exists())

        export_file = Path(result["export_path"])
        self.assertTrue(export_file.exists())
        content = export_file.read_text(encoding="utf-8-sig")
        self.assertIn("HEX帧", content)
        self.assertIn("7F7F", content)

    def test_cleanup_change_bit_event_skips_delete_when_export_fails(self):
        old_row = ChangeBitEvent.objects.create(
            device=self.device,
            bit_index=1,
            value=True,
            source="A2",
        )
        self._set_old_timestamp(ChangeBitEvent, old_row.pk)

        with self.settings(CLEANUP_EXPORT_DIR=self.temp_dir.name), patch.object(
            cleanup_tasks,
            "export_cleanup_queryset_to_csv",
            side_effect=RuntimeError("boom"),
        ):
            result = cleanup_tasks.cleanup_change_bit_event(30)

        self.assertEqual(result["status"], "failed")
        self.assertIn("boom", result["error"])
        self.assertTrue(ChangeBitEvent.objects.filter(pk=old_row.pk).exists())

    def test_cleanup_switch_data_freezes_snapshot_ids(self):
        original_row = SwitchData.objects.create(device=self.device, switch_status=b"\xAA\xBB\xCC\xDD", version="v4")
        self._set_old_timestamp(SwitchData, original_row.pk)
        original_export = cleanup_tasks.export_cleanup_queryset_to_csv

        def delayed_export(**kwargs):
            injected_row = SwitchData.objects.create(device=self.device, switch_status=b"\x11\x22\x33\x44", version="v4")
            self._set_old_timestamp(SwitchData, injected_row.pk)
            delayed_export.injected_pk = injected_row.pk
            return original_export(**kwargs)

        with self.settings(CLEANUP_EXPORT_DIR=self.temp_dir.name), patch.object(
            cleanup_tasks,
            "export_cleanup_queryset_to_csv",
            side_effect=delayed_export,
        ):
            first_result = cleanup_tasks.cleanup_switch_data(30)

        self.assertEqual(first_result["status"], "deleted")
        self.assertEqual(first_result["candidate_count"], 1)
        self.assertFalse(SwitchData.objects.filter(pk=original_row.pk).exists())
        self.assertTrue(SwitchData.objects.filter(pk=delayed_export.injected_pk).exists())

        with self.settings(CLEANUP_EXPORT_DIR=self.temp_dir.name):
            second_result = cleanup_tasks.cleanup_switch_data(30)

        self.assertEqual(second_result["status"], "deleted")
        self.assertEqual(second_result["candidate_count"], 1)
        self.assertFalse(SwitchData.objects.filter(pk=delayed_export.injected_pk).exists())
