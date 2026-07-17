from __future__ import annotations

from copy import deepcopy
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from consts import SY_ALARM_DELAY
from myapp.models import RuntimeConfig, UserOperation
from myapp.runtime_config import (
    build_runtime_config_payload,
    get_alarm_delay_map,
    get_communication_timeout,
    save_runtime_config_values,
)


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "sy-runtime-config-tests",
    }
}


@override_settings(CACHES=TEST_CACHES)
class RuntimeConfigApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="admin123",
        )
        self.user = user_model.objects.create_user(
            username="user",
            email="user@example.com",
            password="user123",
        )
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="3",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        self.periodic_task, _ = PeriodicTask.objects.get_or_create(
            name="My Daily Task",
            defaults={
                "task": "myapp.tasks.my_daily_task.my_daily_task",
                "crontab": schedule,
                "args": "[7, 30, 30, 90, 90, 366]",
            },
        )
        if self.periodic_task.crontab_id != schedule.id or self.periodic_task.args != "[7, 30, 30, 90, 90, 366]":
            self.periodic_task.task = "myapp.tasks.my_daily_task.my_daily_task"
            self.periodic_task.crontab = schedule
            self.periodic_task.args = "[7, 30, 30, 90, 90, 366]"
            self.periodic_task.save(update_fields=["task", "crontab", "args"])

    def test_runtime_config_requires_superuser(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("runtime_config"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_runtime_config_put_updates_helper_values(self):
        payload = build_runtime_config_payload(force_refresh=True)["values"]
        updated_values = deepcopy(payload)
        updated_values["COMMUNICATION_TIMEOUT"] = 30
        updated_values["SY_ALARM_DELAY"][42] = 18

        self.client.force_authenticate(user=self.superuser)
        response = self.client.put(
            reverse("runtime_config"),
            {"values": updated_values},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_communication_timeout(), 30)
        self.assertEqual(get_alarm_delay_map()[42], 18)
        operations = list(UserOperation.objects.order_by("operation"))
        expected_operations = sorted(
            [
                f"修改SY系统设置（COMMUNICATION_TIMEOUT: {payload['COMMUNICATION_TIMEOUT']}->30）",
                f"修改SY系统设置（SY_ALARM_DELAY[42]: {payload['SY_ALARM_DELAY'][42]}->18）",
            ]
        )
        self.assertEqual([operation.operation for operation in operations], expected_operations)
        for operation in operations:
            self.assertIsNone(operation.device)
            self.assertEqual(operation.function_code, "runtime_config_update")
            self.assertEqual(operation.username, self.superuser.username)

    def test_runtime_config_get_returns_cleanup_values(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.get(reverse("runtime_config"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["values"]["CLEANUP_SCHEDULE_TIME"], "03:00")
        self.assertEqual(response.data["values"]["CLEANUP_RAW_FRAME_LOG_DAYS"], 7)
        self.assertIs(response.data["values"]["CLEANUP_RAW_FRAME_LOG_AUTO_EXPORT"], True)

    def test_runtime_config_includes_actual_cleanup_export_dir(self):
        with override_settings(
            CLEANUP_EXPORT_DISPLAY_DIR="D:/bt_nms_data/cleanup_exports",
            CLEANUP_EXPORT_DIR="/data/cleanup_exports",
        ):
            cache.clear()
            self.client.force_authenticate(user=self.superuser)
            response = self.client.get(reverse("runtime_config"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["cleanup_export_dir"], "D:/bt_nms_data/cleanup_exports")

    def test_runtime_config_put_updates_cleanup_schedule_and_retention(self):
        payload = build_runtime_config_payload(force_refresh=True)["values"]
        updated_values = deepcopy(payload)
        updated_values["CLEANUP_SCHEDULE_TIME"] = "05:15"
        updated_values["CLEANUP_CHANGE_BIT_EVENT_DAYS"] = 45

        self.client.force_authenticate(user=self.superuser)
        response = self.client.put(
            reverse("runtime_config"),
            {"values": updated_values},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.periodic_task.refresh_from_db()
        self.assertEqual(
            json.loads(self.periodic_task.args),
            [7, 30, 45, 90, 90, 366, True, True, True, True, True, True],
        )
        self.assertEqual(self.periodic_task.crontab.hour, "5")
        self.assertEqual(self.periodic_task.crontab.minute, "15")
        operations = list(UserOperation.objects.order_by("operation"))
        self.assertEqual(
            [operation.operation for operation in operations],
            sorted(
                [
                    "修改SY系统设置（CLEANUP_CHANGE_BIT_EVENT_DAYS: 30->45）",
                    "修改SY系统设置（CLEANUP_SCHEDULE_TIME: 03:00->05:15）",
                ]
            ),
        )

    def test_runtime_config_put_same_values_does_not_create_user_operation(self):
        payload = build_runtime_config_payload(force_refresh=True)["values"]

        self.client.force_authenticate(user=self.superuser)
        response = self.client.put(
            reverse("runtime_config"),
            {"values": payload},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(UserOperation.objects.count(), 0)

    def test_runtime_config_rejects_unknown_keys(self):
        payload = build_runtime_config_payload(force_refresh=True)["values"]
        invalid_values = deepcopy(payload)
        invalid_values["UNKNOWN_KEY"] = 1

        self.client.force_authenticate(user=self.superuser)
        response = self.client.put(
            reverse("runtime_config"),
            {"values": invalid_values},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_runtime_config_fills_missing_alarm_codes_when_loading_stored_values(self):
        payload = build_runtime_config_payload(force_refresh=True)["values"]
        legacy_alarm_delay = deepcopy(payload["SY_ALARM_DELAY"])
        legacy_alarm_delay.pop(42, None)
        RuntimeConfig.objects.update_or_create(
            pk=1,
            defaults={
                "values": {"SY_ALARM_DELAY": legacy_alarm_delay},
                "updated_by": self.superuser,
            },
        )
        cache.clear()

        values = build_runtime_config_payload(force_refresh=True)["values"]

        self.assertEqual(values["SY_ALARM_DELAY"][42], SY_ALARM_DELAY[42])
        self.assertEqual(get_alarm_delay_map()[42], SY_ALARM_DELAY[42])

    def test_runtime_config_rejects_invalid_cleanup_time(self):
        payload = build_runtime_config_payload(force_refresh=True)["values"]
        invalid_values = deepcopy(payload)
        invalid_values["CLEANUP_SCHEDULE_TIME"] = "99:00"

        self.client.force_authenticate(user=self.superuser)
        response = self.client.put(
            reverse("runtime_config"),
            {"values": invalid_values},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_token_obtain_pair_uses_runtime_config_lifetimes(self):
        save_runtime_config_values(
            user=self.superuser,
            values={
                "JWT_ACCESS_TOKEN_LIFETIME_DAYS": 4,
                "JWT_REFRESH_TOKEN_LIFETIME_DAYS": 6,
            },
        )

        response = self.client.post(
            reverse("token_obtain_pair"),
            {"username": self.superuser.username, "password": "admin123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access = AccessToken(response.data["access"])
        refresh = RefreshToken(response.data["refresh"])
        self.assertEqual(int(access["exp"]) - int(access["iat"]), 4 * 86400)
        self.assertEqual(int(refresh["exp"]) - int(refresh["iat"]), 6 * 86400)

    def test_save_runtime_config_values_logs_each_changed_alarm_delay_code(self):
        payload = build_runtime_config_payload(force_refresh=True)["values"]
        save_runtime_config_values(
            user=self.superuser,
            values={
                "SY_ALARM_DELAY": {
                    **payload["SY_ALARM_DELAY"],
                    42: 21,
                    43: 24,
                },
            },
        )

        operations = list(UserOperation.objects.order_by("operation"))
        self.assertEqual(
            [operation.operation for operation in operations],
            sorted(
                [
                    f"修改SY系统设置（SY_ALARM_DELAY[42]: {payload['SY_ALARM_DELAY'][42]}->21）",
                    f"修改SY系统设置（SY_ALARM_DELAY[43]: {payload['SY_ALARM_DELAY'][43]}->24）",
                ]
            ),
        )
