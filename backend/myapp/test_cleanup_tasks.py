from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from myapp.models import AnalogData, Depot, Device, Line, SwitchData
from myapp.tasks import cleanup_tasks


class BtCleanupTaskTests(TestCase):
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

    @override_settings()
    def test_cleanup_switch_data_exports_then_deletes_snapshot(self):
        with self.settings(DATA_DIR=self.temp_dir.name):
            old_row = SwitchData.objects.create(device=self.device, switch_status=b"\x01" * 46)
            self._set_old_timestamp(SwitchData, old_row.pk)
            new_row = SwitchData.objects.create(device=self.device, switch_status=b"\x02" * 46)

            result = cleanup_tasks.cleanup_switch_data(30)

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["deleted_count"], 1)
        self.assertFalse(SwitchData.objects.filter(pk=old_row.pk).exists())
        self.assertTrue(SwitchData.objects.filter(pk=new_row.pk).exists())

        export_file = Path(result["export_path"])
        self.assertTrue(export_file.exists())
        self.assertEqual(export_file.parent, Path(self.temp_dir.name) / "cleanup_exports")
        content = export_file.read_text(encoding="utf-8-sig")
        self.assertIn("设备ID", content)
        self.assertIn(str(self.device.device_id), content)

    def test_cleanup_analog_data_skips_delete_when_export_fails(self):
        old_row = AnalogData.objects.create(
            device=self.device,
            voltage_1=1.0,
            current_1=2.0,
            voltage_2=3.0,
            current_2=4.0,
        )
        self._set_old_timestamp(AnalogData, old_row.pk)

        with self.settings(DATA_DIR=self.temp_dir.name), patch.object(
            cleanup_tasks,
            "export_cleanup_queryset_to_csv",
            side_effect=RuntimeError("boom"),
        ):
            result = cleanup_tasks.cleanup_analog_data(30)

        self.assertEqual(result["status"], "failed")
        self.assertIn("boom", result["error"])
        self.assertTrue(AnalogData.objects.filter(pk=old_row.pk).exists())

    def test_cleanup_switch_data_can_delete_without_export(self):
        old_row = SwitchData.objects.create(device=self.device, switch_status=b"\x01" * 46)
        self._set_old_timestamp(SwitchData, old_row.pk)

        with self.settings(DATA_DIR=self.temp_dir.name):
            result = cleanup_tasks.cleanup_switch_data(30, auto_export=False)

        self.assertEqual(result["status"], "deleted")
        self.assertFalse(result["export_enabled"])
        self.assertEqual(result["export_path"], "")
        self.assertEqual(result["deleted_count"], 1)
        self.assertFalse(SwitchData.objects.filter(pk=old_row.pk).exists())
        export_dir = Path(self.temp_dir.name) / "cleanup_exports"
        self.assertFalse(export_dir.exists())

    def test_cleanup_switch_data_freezes_snapshot_ids(self):
        original_row = SwitchData.objects.create(device=self.device, switch_status=b"\x01" * 46)
        self._set_old_timestamp(SwitchData, original_row.pk)
        original_export = cleanup_tasks.export_cleanup_queryset_to_csv

        def delayed_export(**kwargs):
            injected_row = SwitchData.objects.create(device=self.device, switch_status=b"\x03" * 46)
            self._set_old_timestamp(SwitchData, injected_row.pk)
            delayed_export.injected_pk = injected_row.pk
            return original_export(**kwargs)

        with self.settings(DATA_DIR=self.temp_dir.name), patch.object(
            cleanup_tasks,
            "export_cleanup_queryset_to_csv",
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
