from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

from myapp.models import Depot, Device, Line, SYSTEM_ADMIN_GROUP_NAME, UploadedFile, UserOperation


@override_settings(MEDIA_ROOT="/tmp/sy-nms-test-media")
class SySecurityApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.depot_a = Depot.objects.create(name="A车间")
        self.depot_b = Depot.objects.create(name="B车间")
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
        self.ops_user = user_model.objects.create_user("ops-security", password="pw")
        self.ops_user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME))
        self.ops_user.depots.add(self.depot_a)
        self.superuser = user_model.objects.create_superuser("root-security", "root@example.com", "pw")

    @patch("myapp.views.send_sy_frame_via_redis")
    def test_sy_send_command_requires_authentication(self, mock_send_frame):
        response = self.client.post(
            reverse("sy-send-command", args=[self.device_a.device_id]),
            {
                "username": self.ops_user.username,
                "cmd_type": "A1",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        mock_send_frame.assert_not_called()
        self.assertFalse(UserOperation.objects.exists())

    @patch("myapp.views.send_sy_frame_via_redis")
    def test_sy_send_command_rejects_devices_outside_user_scope(self, mock_send_frame):
        self.client.force_authenticate(self.ops_user)

        response = self.client.post(
            reverse("sy-send-command", args=[self.device_b.device_id]),
            {"cmd_type": "A1"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_send_frame.assert_not_called()
        self.assertFalse(UserOperation.objects.exists())

    @patch("myapp.views.send_sy_frame_via_redis")
    def test_sy_send_command_uses_authenticated_user_for_audit(self, mock_send_frame):
        self.client.force_authenticate(self.ops_user)

        response = self.client.post(
            reverse("sy-send-command", args=[self.device_a.device_id]),
            {
                "username": "spoofed-name",
                "cmd_type": "A1",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send_frame.assert_called_once()
        operation = UserOperation.objects.get()
        self.assertEqual(operation.username, self.ops_user.username)

    def test_uploaded_file_list_requires_authentication(self):
        response = self.client.get(reverse("uploadedfile-list"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_download_file_requires_authentication(self):
        uploaded = UploadedFile.objects.create(
            name="manual.txt",
            file=SimpleUploadedFile("manual.txt", b"secret"),
        )

        response = self.client.get(reverse("file-download", args=[uploaded.pk]))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
