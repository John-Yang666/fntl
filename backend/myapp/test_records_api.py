from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from myapp.models import (
    AnalogData,
    AlarmData,
    Depot,
    Device,
    Line,
    RelayAction,
    SYSTEM_ADMIN_GROUP_NAME,
    SwitchData,
    UserOperation,
)


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "bt-records-api-tests",
    }
}


@override_settings(CACHES=TEST_CACHES)
class RecordsApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.depot_a = Depot.objects.create(name="A车间", ordering=1)
        self.depot_b = Depot.objects.create(name="B车间", ordering=2)
        self.line = Line.objects.create(name="1号线", ordering=1)
        self.device_a = Device.objects.create(
            device_id=101,
            name="A设备",
            depot=self.depot_a,
            line=self.line,
            ip_address="10.0.0.101",
        )
        self.device_b = Device.objects.create(
            device_id=102,
            name="B设备",
            depot=self.depot_b,
            line=self.line,
            ip_address="10.0.0.102",
        )
        self.ops_user = user_model.objects.create_user("records-ops", "ops@example.com", "pw")
        self.regular_user = user_model.objects.create_user("records-regular", "regular@example.com", "pw")
        self.ops_user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME))
        self.ops_user.depots.add(self.depot_a)

    def test_switch_and_analog_lists_include_display_fields_and_are_scoped(self):
        SwitchData.objects.create(device=self.device_a, switch_status=b"\x01\x02")
        SwitchData.objects.create(device=self.device_b, switch_status=b"\x03\x04")
        AnalogData.objects.create(device=self.device_a, voltage_1=1.1, current_1=2.2, voltage_2=3.3, current_2=4.4)
        AnalogData.objects.create(device=self.device_b, voltage_1=5.5, current_1=6.6, voltage_2=7.7, current_2=8.8)
        self.client.force_authenticate(self.ops_user)

        switch_response = self.client.get("/api/switch-data/", {"page": 1, "page_size": 20, "include_count": 0})
        analog_response = self.client.get("/api/analog-data/", {"page": 1, "page_size": 20, "include_count": 0})

        self.assertEqual(switch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(analog_response.status_code, status.HTTP_200_OK)
        self.assertEqual(switch_response.data["count"], None)
        self.assertEqual([row["device_id"] for row in switch_response.data["results"]], [101])
        self.assertEqual(switch_response.data["results"][0]["device_name"], "A设备")
        self.assertEqual(switch_response.data["results"][0]["switch_status_text"], "(4)00000001 (5)00000010")
        self.assertEqual([row["device_id"] for row in analog_response.data["results"]], [101])
        self.assertEqual(analog_response.data["results"][0]["device_name"], "A设备")

    def test_count_and_csv_export_use_same_scoped_filters(self):
        SwitchData.objects.create(device=self.device_a, switch_status=b"\x0a")
        SwitchData.objects.create(device=self.device_b, switch_status=b"\x0b")
        RelayAction.objects.create(device=self.device_a, relay="一方向", action="吸起")
        RelayAction.objects.create(device=self.device_b, relay="二方向", action="落下")
        UserOperation.objects.create(device=self.device_a, function_code="f1", operation="A操作", username="ops")
        UserOperation.objects.create(device=self.device_b, function_code="f2", operation="B操作", username="ops")
        self.client.force_authenticate(self.ops_user)

        for endpoint, expected_text, excluded_text in [
            ("switch-data", "(4)00001010", "(4)00001011"),
            ("relay-actions", "一方向", "二方向"),
            ("user-operations", "A操作", "B操作"),
        ]:
            with self.subTest(endpoint=endpoint):
                count_response = self.client.get(f"/api/{endpoint}/count/", {"device__line": "1号线"})
                export_response = self.client.get(f"/api/{endpoint}/export/", {"device__line": "1号线"})

                self.assertEqual(count_response.status_code, status.HTTP_200_OK)
                self.assertEqual(count_response.data["count"], 1)
                self.assertEqual(export_response.status_code, status.HTTP_200_OK)
                self.assertRegex(
                    export_response["Content-Disposition"],
                    rf'attachment; filename="bt-{endpoint}-\d{{8}}\.csv"',
                )
                content = export_response.content.decode("utf-8-sig")
                self.assertIn("设备ID", content)
                self.assertIn(expected_text, content)
                self.assertNotIn(excluded_text, content)

    def test_analog_csv_export_is_available_for_bt(self):
        AnalogData.objects.create(device=self.device_a, voltage_1=1.1, current_1=2.2, voltage_2=3.3, current_2=4.4)
        AnalogData.objects.create(device=self.device_b, voltage_1=5.5, current_1=6.6, voltage_2=7.7, current_2=8.8)
        self.client.force_authenticate(self.ops_user)

        count_response = self.client.get("/api/analog-data/count/", {"device__line": "1号线"})
        export_response = self.client.get("/api/analog-data/export/", {"device__line": "1号线"})

        self.assertEqual(count_response.status_code, status.HTTP_200_OK)
        self.assertEqual(count_response.data["count"], 1)
        content = export_response.content.decode("utf-8-sig")
        self.assertIn("电压1(V)", content)
        self.assertIn("1.1", content)
        self.assertNotIn("5.5", content)

    def test_alert_bulk_confirm_is_scoped_to_user_depots(self):
        alert_a = AlarmData.objects.create(
            device=self.device_a,
            alarm_code=40,
            timestamp_start=timezone.now(),
            is_confirmed=False,
        )
        alert_b = AlarmData.objects.create(
            device=self.device_b,
            alarm_code=41,
            timestamp_start=timezone.now(),
            is_confirmed=False,
        )
        self.client.force_authenticate(self.ops_user)

        response = self.client.post(
            "/api/alerts/bulk-confirm/",
            {"ids": [str(alert_a.id), str(alert_b.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"confirmed": 1, "skipped": 1})
        alert_a.refresh_from_db()
        alert_b.refresh_from_db()
        self.assertTrue(alert_a.is_confirmed)
        self.assertFalse(alert_b.is_confirmed)

    def test_alert_export_uses_current_filters(self):
        AlarmData.objects.create(
            device=self.device_a,
            alarm_code=40,
            timestamp_start=timezone.now(),
            is_confirmed=False,
        )
        AlarmData.objects.create(
            device=self.device_b,
            alarm_code=41,
            timestamp_start=timezone.now(),
            is_confirmed=False,
        )
        self.client.force_authenticate(self.ops_user)

        export_response = self.client.get("/api/alerts/export/", {"alarm_code": 40, "is_confirmed": "false"})

        self.assertEqual(export_response.status_code, status.HTTP_200_OK)
        self.assertRegex(
            export_response["Content-Disposition"],
            r'attachment; filename="bt-alerts-\d{8}\.csv"',
        )
        content = export_response.content.decode("utf-8-sig")
        self.assertIn("告警码", content)
        self.assertIn("40", content)
        self.assertNotIn("41", content)

    def test_regular_user_cannot_export_records(self):
        SwitchData.objects.create(device=self.device_a, switch_status=b"\x01")
        self.client.force_authenticate(self.regular_user)

        response = self.client.get("/api/switch-data/export/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("A设备", response.content.decode("utf-8-sig"))
