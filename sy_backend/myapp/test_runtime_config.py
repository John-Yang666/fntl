from __future__ import annotations

from copy import deepcopy

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from myapp.models import UserOperation
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
