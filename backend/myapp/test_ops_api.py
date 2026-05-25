from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

from myapp.models import Depot, Device, Line, SYSTEM_ADMIN_GROUP_NAME, UserOperation
from myapp.ops_audit import log_device_operation, log_system_operation
from myapp.ops_permissions import ensure_ops_access, scoped_depots_for_user, scoped_devices_for_user


class OpsPermissionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.depot_a = Depot.objects.create(name="A车间", ordering=1)
        self.depot_b = Depot.objects.create(name="B车间", ordering=2)
        self.line = Line.objects.create(name="1号线")
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
        self.superuser = user_model.objects.create_superuser("root", "root@example.com", "pw")
        self.ops_user = user_model.objects.create_user("ops", "ops@example.com", "pw")
        self.staff_user = user_model.objects.create_user("staff", "staff@example.com", "pw", is_staff=True)
        self.regular_user = user_model.objects.create_user("regular", "regular@example.com", "pw")
        self.ops_user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME))
        self.ops_user.depots.add(self.depot_a)
        self.staff_user.depots.add(self.depot_a)

    def test_superuser_can_access_all_ops_data(self):
        ensure_ops_access(self.superuser)
        self.assertEqual(set(scoped_depots_for_user(self.superuser)), {self.depot_a, self.depot_b})
        self.assertEqual(set(scoped_devices_for_user(self.superuser)), {self.device_a, self.device_b})

    def test_system_admin_is_scoped_to_assigned_depots(self):
        ensure_ops_access(self.ops_user)
        self.assertEqual(list(scoped_depots_for_user(self.ops_user)), [self.depot_a])
        self.assertEqual(list(scoped_devices_for_user(self.ops_user)), [self.device_a])

    def test_staff_admin_is_scoped_to_assigned_depots(self):
        ensure_ops_access(self.staff_user)
        self.assertEqual(list(scoped_depots_for_user(self.staff_user)), [self.depot_a])
        self.assertEqual(list(scoped_devices_for_user(self.staff_user)), [self.device_a])

    def test_regular_user_cannot_access_ops(self):
        with self.assertRaises(PermissionDenied):
            ensure_ops_access(self.regular_user)

    def test_audit_helpers_create_user_operations(self):
        log_system_operation(user=self.ops_user, function_code="ops_line_update", operation="修改线路：1号线")
        log_device_operation(
            user=self.ops_user,
            device=self.device_a,
            function_code="ops_device_update",
            operation="修改设备：A设备",
        )

        operations = list(UserOperation.objects.order_by("timestamp"))
        self.assertEqual(operations[0].device, None)
        self.assertEqual(operations[0].username, "ops")
        self.assertEqual(operations[0].function_code, "ops_line_update")
        self.assertEqual(operations[1].device, self.device_a)
        self.assertEqual(operations[1].username, "ops")
        self.assertEqual(operations[1].function_code, "ops_device_update")


class OpsApiBase(APITestCase):
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
            x_coordinate=1.5,
            y_coordinate=2.5,
        )
        self.device_b = Device.objects.create(
            device_id=102,
            name="B设备",
            depot=self.depot_b,
            line=self.line,
            ip_address="10.0.0.102",
        )
        self.superuser = user_model.objects.create_superuser("root-api", "root-api@example.com", "pw")
        self.ops_user = user_model.objects.create_user("ops-api", "ops-api@example.com", "pw")
        self.staff_user = user_model.objects.create_user("staff-api", "staff-api@example.com", "pw", is_staff=True)
        self.regular_user = user_model.objects.create_user("regular-api", "regular-api@example.com", "pw")
        self.ops_user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME))
        self.ops_user.depots.add(self.depot_a)
        self.staff_user.depots.add(self.depot_a)


class OpsDepotLineApiTests(OpsApiBase):
    def test_regular_user_cannot_list_depots(self):
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(reverse("ops-depot-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_system_admin_lists_only_assigned_depots(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.get(reverse("ops-depot-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["name"] for item in response.data["results"]], ["A车间"])

    def test_staff_admin_lists_only_assigned_depots(self):
        self.client.force_authenticate(self.staff_user)
        response = self.client.get(reverse("ops-depot-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["name"] for item in response.data["results"]], ["A车间"])

    def test_system_admin_can_update_assigned_depot(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.patch(
            reverse("ops-depot-detail", args=[self.depot_a.id]),
            {"remark": "已维护", "ordering": 5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.depot_a.refresh_from_db()
        self.assertEqual(self.depot_a.remark, "已维护")
        self.assertEqual(self.depot_a.ordering, 5)
        self.assertTrue(UserOperation.objects.filter(function_code="ops_depot_update").exists())

    def test_system_admin_cannot_update_unassigned_depot(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.patch(
            reverse("ops-depot-detail", args=[self.depot_b.id]),
            {"remark": "越权"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_superuser_can_create_line(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            reverse("ops-line-list"),
            {"name": "2号线", "is_active": True, "ordering": 2, "remark": "新线"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Line.objects.filter(name="2号线").exists())
        self.assertTrue(UserOperation.objects.filter(function_code="ops_line_create").exists())


class OpsDeviceApiTests(OpsApiBase):
    def test_system_admin_lists_only_assigned_depot_devices(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.get(reverse("ops-device-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["device_id"] for item in response.data["results"]], [101])

    def test_system_admin_creates_device_in_assigned_depot(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.post(
            reverse("ops-device-list"),
            {
                "device_id": 103,
                "name": "新设备",
                "depot_id": self.depot_a.id,
                "line_id": self.line.id,
                "ip_address": "10.0.0.103",
                "x_coordinate": 3,
                "y_coordinate": 4,
                "direction1_neighbor_id": 101,
                "direction1_neighbor_direction": 2,
                "direction2_neighbor_id": 0,
                "direction2_neighbor_direction": 1,
                "direction1_enabled": True,
                "direction2_enabled": False,
                "alarm_filters": [40, 41],
                "remark": "新增",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Device.objects.filter(device_id=103, depot=self.depot_a).exists())

    def test_system_admin_cannot_create_device_in_unassigned_depot(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.post(
            reverse("ops-device-list"),
            {"device_id": 104, "name": "越权", "depot_id": self.depot_b.id, "ip_address": "10.0.0.104"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_device_bulk_delete_is_scoped(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.post(
            reverse("ops-device-bulk-delete"),
            {"device_ids": [101, 102]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted"], 1)
        self.assertEqual(response.data["skipped"], 1)
        self.assertFalse(Device.objects.filter(device_id=101).exists())
        self.assertTrue(Device.objects.filter(device_id=102).exists())

    @patch("myapp.device_commands.send_reconnect_packet_to_device")
    def test_reconnect_returns_per_device_results(self, mock_send):
        mock_send.return_value = None
        self.client.force_authenticate(self.ops_user)
        response = self.client.post(
            reverse("ops-device-reconnect"),
            {"device_ids": [101, 102, 999]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], 1)
        self.assertEqual(response.data["skipped"], 2)
        self.assertEqual(mock_send.call_count, 1)
        self.assertTrue(UserOperation.objects.filter(function_code="ops_device_reconnect").exists())


class OpsDeviceImportExportTests(OpsApiBase):
    def test_export_includes_only_scoped_devices(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.get(reverse("ops-device-export"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.content.decode("utf-8-sig")
        self.assertIn("设备ID", content)
        self.assertIn("A设备", content)
        self.assertNotIn("B设备", content)

    def test_import_preview_reports_create_update_and_errors_without_writing(self):
        self.client.force_authenticate(self.ops_user)
        csv_content = (
            "设备ID,设备名称,车间,线路,IP地址,X坐标,Y坐标,一方向邻站ID,一方向邻站方向,"
            "二方向邻站ID,二方向邻站方向,一方向启用,二方向启用,备注,过滤告警码\n"
            "101,A设备改名,A车间,1号线,10.0.0.101,1,2,0,2,0,1,是,否,更新,40;41\n"
            "105,新导入,A车间,1号线,10.0.0.105,3,4,101,2,0,1,是,是,新增,\n"
            "106,越权,B车间,1号线,10.0.0.106,3,4,0,2,0,1,是,是,错误,\n"
        ).encode("utf-8")
        upload = BytesIO(csv_content)
        upload.name = "devices.csv"

        response = self.client.post(reverse("ops-device-import-preview"), {"file": upload}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["summary"]["create"], 1)
        self.assertEqual(response.data["summary"]["update"], 1)
        self.assertEqual(response.data["summary"]["error"], 1)
        self.assertEqual(Device.objects.filter(device_id=105).count(), 0)

    def test_import_commit_writes_valid_rows(self):
        self.client.force_authenticate(self.ops_user)
        rows = [
            {
                "device_id": 105,
                "name": "新导入",
                "depot": "A车间",
                "line": "1号线",
                "ip_address": "10.0.0.105",
                "x_coordinate": 3,
                "y_coordinate": 4,
                "direction1_neighbor_id": 101,
                "direction1_neighbor_direction": 2,
                "direction2_neighbor_id": 0,
                "direction2_neighbor_direction": 1,
                "direction1_enabled": True,
                "direction2_enabled": True,
                "remark": "提交",
                "alarm_filters": [],
            }
        ]

        response = self.client.post(reverse("ops-device-import-commit"), {"rows": rows}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["created"], 1)
        self.assertTrue(Device.objects.filter(device_id=105, depot=self.depot_a).exists())
