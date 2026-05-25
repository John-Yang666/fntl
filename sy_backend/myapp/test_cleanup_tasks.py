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
        with self.settings(DATA_DIR=self.temp_dir.name):
            old_row = RawFrameLog.objects.create(device=self.device, cmd="A1", note="old", raw_frame=b"\x7f\x7f")
            self._set_old_timestamp(RawFrameLog, old_row.pk)
            new_row = RawFrameLog.objects.create(device=self.device, cmd="A2", note="new", raw_frame=b"\xf7\xf7")

            result = cleanup_tasks.cleanup_raw_frame_log(30)

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["exported_count"], 1)
        self.assertFalse(RawFrameLog.objects.filter(pk=old_row.pk).exists())
        self.assertTrue(RawFrameLog.objects.filter(pk=new_row.pk).exists())

        export_file = Path(result["export_path"])
        self.assertTrue(export_file.exists())
        self.assertEqual(export_file.parent, Path(self.temp_dir.name) / "cleanup_exports")
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

        with self.settings(DATA_DIR=self.temp_dir.name), patch.object(
            cleanup_tasks,
            "export_cleanup_snapshot_to_csv",
            side_effect=RuntimeError("boom"),
        ):
            result = cleanup_tasks.cleanup_change_bit_event(30)

        self.assertEqual(result["status"], "failed")
        self.assertIn("boom", result["error"])
        self.assertTrue(ChangeBitEvent.objects.filter(pk=old_row.pk).exists())

    def test_cleanup_raw_frame_log_can_delete_without_export(self):
        old_row = RawFrameLog.objects.create(device=self.device, cmd="A1", note="old", raw_frame=b"\x7f\x7f")
        self._set_old_timestamp(RawFrameLog, old_row.pk)

        with self.settings(DATA_DIR=self.temp_dir.name):
            result = cleanup_tasks.cleanup_raw_frame_log(30, auto_export=False)

        self.assertEqual(result["status"], "deleted")
        self.assertFalse(result["export_enabled"])
        self.assertEqual(result["export_path"], "")
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["exported_count"], 0)
        self.assertFalse(RawFrameLog.objects.filter(pk=old_row.pk).exists())
        export_dir = Path(self.temp_dir.name) / "cleanup_exports"
        self.assertFalse(export_dir.exists())

    def test_cleanup_switch_data_freezes_snapshot_ids(self):
        original_row = SwitchData.objects.create(device=self.device, switch_status=b"\xAA\xBB\xCC\xDD", version="v4")
        self._set_old_timestamp(SwitchData, original_row.pk)
        original_export = cleanup_tasks.export_cleanup_snapshot_to_csv

        def delayed_export(**kwargs):
            injected_row = SwitchData.objects.create(device=self.device, switch_status=b"\x11\x22\x33\x44", version="v4")
            self._set_old_timestamp(SwitchData, injected_row.pk)
            delayed_export.injected_pk = injected_row.pk
            return original_export(**kwargs)

        with self.settings(DATA_DIR=self.temp_dir.name), patch.object(
            cleanup_tasks,
            "export_cleanup_snapshot_to_csv",
            side_effect=delayed_export,
        ):
            first_result = cleanup_tasks.cleanup_switch_data(30)

        self.assertEqual(first_result["status"], "deleted")
        self.assertEqual(first_result["candidate_count"], 1)
        self.assertFalse(SwitchData.objects.filter(pk=original_row.pk).exists())
        self.assertTrue(SwitchData.objects.filter(pk=delayed_export.injected_pk).exists())

        with self.settings(DATA_DIR=self.temp_dir.name):
            second_result = cleanup_tasks.cleanup_switch_data(30)

        self.assertEqual(second_result["status"], "deleted")
        self.assertEqual(second_result["candidate_count"], 1)
        self.assertFalse(SwitchData.objects.filter(pk=delayed_export.injected_pk).exists())

    def test_cleanup_raw_frame_log_streams_export_and_delete_in_batches(self):
        old_rows = [
            RawFrameLog.objects.create(device=self.device, cmd=f"A{idx}", note="old", raw_frame=bytes([idx]) * 2)
            for idx in range(1, 4)
        ]
        for row in old_rows:
            self._set_old_timestamp(RawFrameLog, row.pk)
        new_row = RawFrameLog.objects.create(device=self.device, cmd="A9", note="new", raw_frame=b"\x09\x09")

        with self.settings(DATA_DIR=self.temp_dir.name), patch.object(
            cleanup_tasks,
            "EXPORT_BATCH_SIZE",
            2,
        ), patch.object(
            cleanup_tasks,
            "DELETE_BATCH_SIZE",
            2,
        ), patch.object(
            cleanup_tasks,
            "MAX_EXPORT_ROWS_PER_FILE",
            2,
        ):
            result = cleanup_tasks.cleanup_raw_frame_log(30)

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["exported_count"], 3)
        self.assertEqual(result["export_file_count"], 2)
        self.assertEqual(result["deleted_count"], 3)
        self.assertFalse(RawFrameLog.objects.filter(pk__in=[row.pk for row in old_rows]).exists())
        self.assertTrue(RawFrameLog.objects.filter(pk=new_row.pk).exists())

        export_files = [Path(path) for path in result["export_paths"]]
        self.assertTrue(all(path.exists() for path in export_files))
        self.assertTrue(export_files[0].name.endswith("_part0001.csv"))
        self.assertTrue(export_files[1].name.endswith("_part0002.csv"))
        line_counts = []
        for export_file in export_files:
            content = export_file.read_text(encoding="utf-8-sig")
            self.assertEqual(content.count("HEX帧"), 1)
            line_counts.append(len([line for line in content.splitlines() if line.strip()]))
        self.assertEqual(line_counts, [3, 2])
