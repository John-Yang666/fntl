from __future__ import annotations

from datetime import timedelta

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
        self.superuser = user_model.objects.create_superuser("records-root", "root@example.com", "pw")
        self.ops_user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME))
        self.ops_user.depots.add(self.depot_a)

    def export_time_params(self, time_field="timestamp"):
        now = timezone.now()
        return {
            f"{time_field}__gte": (now - timedelta(days=1)).isoformat(),
            f"{time_field}__lte": (now + timedelta(days=1)).isoformat(),
        }

    def streaming_csv_content(self, response):
        return b"".join(response.streaming_content).decode("utf-8-sig")

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
                export_response = self.client.get(
                    f"/api/{endpoint}/export/",
                    {"device__line": "1号线", **self.export_time_params()},
                )

                self.assertEqual(count_response.status_code, status.HTTP_200_OK)
                self.assertEqual(count_response.data["count"], 1)
                self.assertEqual(export_response.status_code, status.HTTP_200_OK)
                self.assertTrue(export_response.streaming)
                self.assertRegex(
                    export_response["Content-Disposition"],
                    rf'attachment; filename="bt-{endpoint}-\d{{8}}\.csv"',
                )
                content = self.streaming_csv_content(export_response)
                self.assertIn("设备ID", content)
                self.assertIn(expected_text, content)
                self.assertNotIn(excluded_text, content)

    def test_analog_csv_export_is_available_for_bt(self):
        AnalogData.objects.create(device=self.device_a, voltage_1=1.1, current_1=2.2, voltage_2=3.3, current_2=4.4)
        AnalogData.objects.create(device=self.device_b, voltage_1=5.5, current_1=6.6, voltage_2=7.7, current_2=8.8)
        self.client.force_authenticate(self.ops_user)

        count_response = self.client.get("/api/analog-data/count/", {"device__line": "1号线"})
        export_response = self.client.get(
            "/api/analog-data/export/",
            {"device__line": "1号线", **self.export_time_params()},
        )

        self.assertEqual(count_response.status_code, status.HTTP_200_OK)
        self.assertEqual(count_response.data["count"], 1)
        self.assertTrue(export_response.streaming)
        content = self.streaming_csv_content(export_response)
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

        export_response = self.client.get(
            "/api/alerts/export/",
            {"alarm_code": 40, "is_confirmed": "false", **self.export_time_params("timestamp_start")},
        )

        self.assertEqual(export_response.status_code, status.HTTP_200_OK)
        self.assertTrue(export_response.streaming)
        self.assertRegex(
            export_response["Content-Disposition"],
            r'attachment; filename="bt-alerts-\d{8}\.csv"',
        )
        content = self.streaming_csv_content(export_response)
        self.assertIn("告警码", content)
        self.assertIn(",40,", content)
        self.assertNotIn(",41,", content)

    def test_regular_user_cannot_export_records(self):
        SwitchData.objects.create(device=self.device_a, switch_status=b"\x01")
        self.client.force_authenticate(self.regular_user)

        response = self.client.get("/api/switch-data/export/", self.export_time_params())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.streaming)
        self.assertNotIn("A设备", self.streaming_csv_content(response))

    def test_record_exports_require_time_range(self):
        self.client.force_authenticate(self.ops_user)

        for endpoint in ("switch-data", "analog-data", "relay-actions", "user-operations", "alerts"):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(f"/api/{endpoint}/export/")

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("缺少导出时间范围", response.data["detail"])

    def test_record_exports_reject_invalid_time_ranges(self):
        now = timezone.now()
        too_old = now - timedelta(days=91)
        cases = [
            (
                "switch-data",
                "timestamp",
                [
                    {
                        "timestamp__gte": "not-a-time",
                        "timestamp__lte": now.isoformat(),
                        "detail": "导出时间格式无效",
                    },
                    {
                        "timestamp__gte": now.isoformat(),
                        "timestamp__lte": (now - timedelta(seconds=1)).isoformat(),
                        "detail": "导出结束时间不能早于开始时间",
                    },
                    {
                        "timestamp__gte": too_old.isoformat(),
                        "timestamp__lte": now.isoformat(),
                        "detail": "导出时间范围不能超过",
                    },
                ],
            ),
            (
                "alerts",
                "timestamp_start",
                [
                    {
                        "timestamp_start__gte": "not-a-time",
                        "timestamp_start__lte": now.isoformat(),
                        "detail": "导出时间格式无效",
                    },
                    {
                        "timestamp_start__gte": now.isoformat(),
                        "timestamp_start__lte": (now - timedelta(seconds=1)).isoformat(),
                        "detail": "导出结束时间不能早于开始时间",
                    },
                    {
                        "timestamp_start__gte": too_old.isoformat(),
                        "timestamp_start__lte": now.isoformat(),
                        "detail": "导出时间范围不能超过",
                    },
                ],
            ),
        ]
        self.client.force_authenticate(self.ops_user)

        for endpoint, _time_field, param_cases in cases:
            for params in param_cases:
                with self.subTest(endpoint=endpoint, detail=params["detail"]):
                    expected_detail = params.pop("detail")

                    response = self.client.get(f"/api/{endpoint}/export/", params)

                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn(expected_detail, response.data["detail"])

    @override_settings(RECORDS_EXPORT_MAX_ROWS=1)
    def test_record_export_rejects_results_over_limit(self):
        SwitchData.objects.create(device=self.device_a, switch_status=b"\x01")
        SwitchData.objects.create(device=self.device_a, switch_status=b"\x02")
        self.client.force_authenticate(self.ops_user)

        response = self.client.get("/api/switch-data/export/", self.export_time_params())

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(getattr(response, "streaming", False))
        self.assertIn("导出结果超过 1 行", response.data["detail"])

    @override_settings(RECORDS_API_MAX_PAGE_SIZE=2)
    def test_record_list_page_size_is_capped_by_setting(self):
        for index in range(3):
            SwitchData.objects.create(device=self.device_a, switch_status=bytes([index + 1]))
        self.client.force_authenticate(self.ops_user)

        response = self.client.get("/api/switch-data/", {"page": 1, "page_size": 10000, "include_count": 0})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_regular_user_cannot_write_general_device_and_record_endpoints(self):
        switch_record = SwitchData.objects.create(device=self.device_a, switch_status=b"\x01\x02")
        analog_record = AnalogData.objects.create(
            device=self.device_a,
            voltage_1=1.1,
            current_1=2.2,
            voltage_2=3.3,
            current_2=4.4,
        )
        relay_record = RelayAction.objects.create(device=self.device_a, relay="一方向", action="吸起")

        cases = [
            (
                "/api/devices/",
                {
                    "device_id": 999,
                    "name": "通用接口新增设备",
                    "ip_address": "10.0.0.250",
                },
                Device,
                self.device_a,
                {"name": "被篡改设备"},
                lambda: self.assertEqual(Device.objects.get(pk=self.device_a.pk).name, "A设备"),
            ),
            (
                "/api/switch-data/",
                {
                    "device": self.device_a.device_id,
                    "switch_status": "0102",
                },
                SwitchData,
                switch_record,
                {"switch_status": "FFFF"},
                lambda: self.assertEqual(bytes(SwitchData.objects.get(pk=switch_record.pk).switch_status), b"\x01\x02"),
            ),
            (
                "/api/analog-data/",
                {
                    "device": self.device_a.device_id,
                    "voltage_1": 1.1,
                    "current_1": 2.2,
                    "voltage_2": 3.3,
                    "current_2": 4.4,
                },
                AnalogData,
                analog_record,
                {"voltage_1": 9.9},
                lambda: self.assertEqual(AnalogData.objects.get(pk=analog_record.pk).voltage_1, 1.1),
            ),
            (
                "/api/relay-actions/",
                {
                    "device": self.device_a.device_id,
                    "relay": "一方向",
                    "action": "吸起",
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
