from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from myapp.models import (
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
        "LOCATION": "sy-records-api-tests",
    }
}


@override_settings(CACHES=TEST_CACHES)
class SyRecordsApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.depot_a = Depot.objects.create(name="A车间", ordering=1)
        self.depot_b = Depot.objects.create(name="B车间", ordering=2)
        self.line = Line.objects.create(name="1号线", ordering=1)
        self.device_a = Device.objects.create(
            device_id=201,
            name="SY-A设备",
            depot=self.depot_a,
            line=self.line,
            ip_address="10.0.1.201",
        )
        self.device_b = Device.objects.create(
            device_id=202,
            name="SY-B设备",
            depot=self.depot_b,
            line=self.line,
            ip_address="10.0.1.202",
        )
        self.ops_user = user_model.objects.create_user("sy-records-ops", "ops@example.com", "pw")
        self.regular_user = user_model.objects.create_user("sy-records-regular", "regular@example.com", "pw")
        self.superuser = user_model.objects.create_superuser("sy-records-root", "root@example.com", "pw")
        self.ops_user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME))
        self.ops_user.depots.add(self.depot_a)

    def test_switch_list_count_and_export_are_scoped(self):
        SwitchData.objects.create(device=self.device_a, switch_status=b"\x0a\x0b", version="v4")
        SwitchData.objects.create(device=self.device_b, switch_status=b"\x0c\x0d", version="v4")
        self.client.force_authenticate(self.ops_user)

        list_response = self.client.get("/api/switch-data/", {"page": 1, "page_size": 20, "include_count": 0})
        count_response = self.client.get("/api/switch-data/count/", {"device__line": "1号线"})
        export_response = self.client.get("/api/switch-data/export/", {"device__line": "1号线"})

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], None)
        self.assertEqual([row["device_id"] for row in list_response.data["results"]], [201])
        self.assertEqual(list_response.data["results"][0]["switch_status_hex"], "0A0B")
        self.assertEqual(count_response.status_code, status.HTTP_200_OK)
        self.assertEqual(count_response.data["count"], 1)
        self.assertRegex(
            export_response["Content-Disposition"],
            r'attachment; filename="sy-switch-data-\d{8}\.csv"',
        )
        content = export_response.content.decode("utf-8-sig")
        self.assertIn("SY-A设备", content)
        self.assertIn("0A0B", content)
        self.assertNotIn("SY-B设备", content)

    def test_common_record_exports_and_counts_are_available(self):
        RelayAction.objects.create(device=self.device_a, relay="一方向", action="吸起", source="A1")
        RelayAction.objects.create(device=self.device_b, relay="二方向", action="落下", source="A2")
        UserOperation.objects.create(device=self.device_a, function_code="f1", operation="A操作", username="ops")
        UserOperation.objects.create(device=self.device_b, function_code="f2", operation="B操作", username="ops")
        self.client.force_authenticate(self.ops_user)

        for endpoint, expected_text, excluded_text in [
            ("relay-actions", "一方向", "二方向"),
            ("user-operations", "A操作", "B操作"),
        ]:
            with self.subTest(endpoint=endpoint):
                count_response = self.client.get(f"/api/{endpoint}/count/", {"device__line": "1号线"})
                export_response = self.client.get(f"/api/{endpoint}/export/", {"device__line": "1号线"})

                self.assertEqual(count_response.status_code, status.HTTP_200_OK)
                self.assertEqual(count_response.data["count"], 1)
                self.assertEqual(export_response.status_code, status.HTTP_200_OK)
                content = export_response.content.decode("utf-8-sig")
                self.assertIn(expected_text, content)
                self.assertNotIn(excluded_text, content)

    def test_alert_bulk_confirm_is_scoped(self):
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
            r'attachment; filename="sy-alerts-\d{8}\.csv"',
        )
        content = export_response.content.decode("utf-8-sig")
        self.assertIn("告警码", content)
        self.assertIn(",40,", content)
        self.assertNotIn(",41,", content)

    def test_regular_user_cannot_write_general_device_and_record_endpoints(self):
        switch_record = SwitchData.objects.create(device=self.device_a, switch_status=b"\x01\x02", version="v4")
        relay_record = RelayAction.objects.create(device=self.device_a, relay="一方向", action="吸起", source="A1")

        cases = [
            (
                "/api/devices/",
                {
                    "device_id": 999,
                    "name": "通用接口新增设备",
                    "ip_address": "10.0.1.250",
                },
                Device,
                self.device_a,
                {"name": "被篡改设备"},
                lambda: self.assertEqual(Device.objects.get(pk=self.device_a.pk).name, "SY-A设备"),
            ),
            (
                "/api/switch-data/",
                {
                    "device": self.device_a.device_id,
                    "switch_status": "0102",
                    "version": "v4",
                },
                SwitchData,
                switch_record,
                {"switch_status": "FFFF"},
                lambda: self.assertEqual(bytes(SwitchData.objects.get(pk=switch_record.pk).switch_status), b"\x01\x02"),
            ),
            (
                "/api/relay-actions/",
                {
                    "device": self.device_a.device_id,
                    "relay": "一方向",
                    "action": "吸起",
                    "source": "A1",
                },
                RelayAction,
                relay_record,
                {"action": "落下"},
                lambda: self.assertEqual(RelayAction.objects.get(pk=relay_record.pk).action, "吸起"),
            ),
        ]

        for user in (self.regular_user, self.ops_user, self.superuser):
            self.client.force_authenticate(user)
            for endpoint, post_payload, model, instance, write_payload, assert_unchanged in cases:
                detail_endpoint = f"{endpoint}{instance.pk}/"
                with self.subTest(user=user.username, endpoint=endpoint, method="post"):
                    before_count = model.objects.count()

                    response = self.client.post(endpoint, post_payload, format="json")

                    self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
                    self.assertEqual(model.objects.count(), before_count)

                for method in ("patch", "put", "delete"):
                    with self.subTest(user=user.username, endpoint=detail_endpoint, method=method):
                        before_count = model.objects.count()

                        request_method = getattr(self.client, method)
                        response = request_method(detail_endpoint, write_payload, format="json")

                        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
                        self.assertEqual(model.objects.count(), before_count)
                        assert_unchanged()
