from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from myapp.alarm_monitoring import build_alarm_snapshot
from myapp.models import AlarmActive, AlarmData, Depot, Device, Line, UserMonitoringPreference


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "bt-alarm-monitoring-tests",
    }
}


@override_settings(CACHES=TEST_CACHES)
class AlarmMonitoringApiTests(APITestCase):
    def setUp(self):
        self.depot = Depot.objects.create(name="监控车间")
        self.other_depot = Depot.objects.create(name="其他车间")
        self.line = Line.objects.create(name="监控线路")
        self.device_a = Device.objects.create(device_id=301, name="设备A", depot=self.depot, line=self.line, ip_address="10.30.0.1")
        self.device_b = Device.objects.create(device_id=302, name="设备B", depot=self.depot, line=self.line, ip_address="10.30.0.2")
        self.device_outside = Device.objects.create(device_id=399, name="越权设备", depot=self.other_depot, line=self.line, ip_address="10.30.0.99")
        self.user = get_user_model().objects.create_user("monitor-user", password="pw")
        self.user.depots.add(self.depot)
        self.client.force_authenticate(self.user)

    def test_default_preference_monitors_all_allowed_devices(self):
        response = self.client.get("/api/monitoring-preference/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"selection_mode": "all", "device_ids": [301, 302]})

    def test_custom_preference_filters_current_and_historical_alarms(self):
        preference_response = self.client.put(
            "/api/monitoring-preference/",
            {"selection_mode": "custom", "device_ids": [301]},
            format="json",
        )
        self.assertEqual(preference_response.status_code, status.HTTP_200_OK)

        current_a = AlarmActive.objects.create(device=self.device_a, alarm_code=40, is_confirmed=False)
        AlarmActive.objects.create(device=self.device_b, alarm_code=41, is_confirmed=False)
        history_a = AlarmData.objects.create(device=self.device_a, alarm_code=42, timestamp_start=timezone.now(), is_confirmed=False)
        AlarmData.objects.create(device=self.device_b, alarm_code=43, timestamp_start=timezone.now(), is_confirmed=False)

        active_response = self.client.get("/api/active-alarms/")
        history_response = self.client.get("/api/alerts/", {"is_confirmed": "false", "monitored": "true"})
        snapshot = build_alarm_snapshot(self.user)

        self.assertEqual([item["id"] for item in active_response.data], [str(current_a.id)])
        self.assertEqual([item["id"] for item in history_response.data["results"]], [str(history_a.id)])
        self.assertEqual(snapshot["current_unconfirmed_count"], 1)
        self.assertEqual(snapshot["historical_unconfirmed_count"], 1)
        self.assertTrue(snapshot["should_play"])

    def test_unified_confirmation_confirms_current_and_history(self):
        current = AlarmActive.objects.create(device=self.device_a, alarm_code=50, is_confirmed=False)
        history = AlarmData.objects.create(device=self.device_a, alarm_code=51, timestamp_start=timezone.now(), is_confirmed=False)

        response = self.client.post(
            "/api/alarm-confirmations/",
            {"alarms": [
                {"source": "current", "occurrence_id": str(current.id)},
                {"source": "history", "occurrence_id": str(history.id)},
            ]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"confirmed": 2, "skipped": 0})
        current.refresh_from_db()
        history.refresh_from_db()
        self.assertTrue(current.is_confirmed)
        self.assertTrue(history.is_confirmed)
        self.assertFalse(build_alarm_snapshot(self.user)["should_play"])

    def test_preference_rejects_devices_outside_user_scope(self):
        response = self.client.put(
            "/api/monitoring-preference/",
            {"selection_mode": "custom", "device_ids": [399]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(UserMonitoringPreference.objects.filter(user=self.user).exists())

    def test_confirmed_current_alarm_remains_visible_without_sound(self):
        alarm = AlarmActive.objects.create(device=self.device_a, alarm_code=60, is_confirmed=True)

        response = self.client.get("/api/active-alarms/")
        snapshot = build_alarm_snapshot(self.user)

        self.assertEqual([item["id"] for item in response.data], [str(alarm.id)])
        self.assertEqual(snapshot["current_count"], 1)
        self.assertEqual(snapshot["total_unconfirmed_count"], 0)
        self.assertFalse(snapshot["should_play"])
