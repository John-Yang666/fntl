import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QSystemTrayIcon
except Exception:  # pragma: no cover - allows non-GUI environments to run logic tests
    QSystemTrayIcon = None


@unittest.skipIf(QSystemTrayIcon is None, "PySide6 is not installed")
class TrayActivationTests(unittest.TestCase):
    def test_tray_clicks_are_handled_by_native_context_menu_only(self):
        from alarm_client.main import (
            should_open_tray_menu_for_reason,
            should_show_current_alerts_for_tray_reason,
        )

        self.assertFalse(should_open_tray_menu_for_reason(QSystemTrayIcon.ActivationReason.Trigger))
        self.assertFalse(should_open_tray_menu_for_reason(QSystemTrayIcon.ActivationReason.Context))
        self.assertFalse(should_show_current_alerts_for_tray_reason(QSystemTrayIcon.ActivationReason.Trigger))
        self.assertFalse(should_show_current_alerts_for_tray_reason(QSystemTrayIcon.ActivationReason.DoubleClick))
        self.assertFalse(should_show_current_alerts_for_tray_reason(QSystemTrayIcon.ActivationReason.Context))


class LoginStatusDisplayTests(unittest.TestCase):
    def test_formats_only_logged_in_systems(self):
        from alarm_client.main import format_login_status

        self.assertEqual(format_login_status(["bt", "sy"]), "BT已登录 SY已登录")
        self.assertEqual(format_login_status(["sy"]), "SY已登录")
        self.assertEqual(format_login_status([]), "")

    def test_tray_tooltip_includes_logged_in_systems(self):
        from alarm_client.main import AlarmClientApp

        class FakeTray:
            def __init__(self):
                self.tooltip = ""

            def setToolTip(self, tooltip):
                self.tooltip = tooltip

        class FakeStatusAction:
            def __init__(self):
                self.text = ""
                self.visible = None

            def setText(self, text):
                self.text = text

            def setVisible(self, visible):
                self.visible = visible

        controller = AlarmClientApp.__new__(AlarmClientApp)
        controller.clients = {"bt": object()}
        controller.tray = FakeTray()
        controller.login_status_action = FakeStatusAction()

        controller._update_tray_tooltip(2, True)

        self.assertEqual(controller.login_status_action.text, "BT已登录")
        self.assertTrue(controller.login_status_action.visible)
        self.assertIn("BT已登录", controller.tray.tooltip)
        self.assertNotIn("SY已登录", controller.tray.tooltip)


class ShutdownTests(unittest.TestCase):
    def test_shutdown_waits_for_running_poll_worker_before_hiding_tray(self):
        from alarm_client.main import AlarmClientApp

        class FakeTimer:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        class FakeAudio:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        class FakePopup:
            def __init__(self):
                self.closed = False

            def close_without_pause(self):
                self.closed = True

        class FakeTray:
            def __init__(self):
                self.hidden = False

            def hide(self):
                self.hidden = True

        class FakeWorker:
            def __init__(self):
                self.waited = False
                self.running = True

            def isRunning(self):
                return self.running

            def wait(self, timeout_ms):
                self.waited = timeout_ms
                self.running = False
                return True

        controller = AlarmClientApp.__new__(AlarmClientApp)
        controller.timer = FakeTimer()
        controller.audio_player = FakeAudio()
        controller.popup = FakePopup()
        controller.tray = FakeTray()
        controller.poll_worker = FakeWorker()
        controller._shutdown_done = False

        controller.shutdown()

        self.assertTrue(controller.timer.stopped)
        self.assertTrue(controller.audio_player.stopped)
        self.assertTrue(controller.popup.closed)
        self.assertTrue(controller.tray.hidden)
        self.assertEqual(controller.poll_worker, None)


class BackendWaitingTests(unittest.TestCase):
    def test_no_credentials_probe_waits_for_backend_instead_of_showing_login(self):
        from alarm_client.api import ApiError
        from alarm_client.main import AlarmClientApp
        from alarm_client.state import AppConfig

        class FakeApiClient:
            def __init__(self, system, api_base):
                self.system = system
                self.api_base = api_base

            def login(self, username, password):
                raise ApiError(self.system, f"{self.system.upper()} API HTTP 404", status=404)

        class FakeTray:
            def __init__(self):
                self.tooltip = ""

            def setToolTip(self, tooltip):
                self.tooltip = tooltip

        controller = AlarmClientApp.__new__(AlarmClientApp)
        controller.config = AppConfig.default()
        controller.clients = {}
        controller.tray = FakeTray()
        controller.waiting_for_backend = False
        controller._backend_wait_notice_shown = False
        controller.show_login_called = False
        controller.backend_notice_calls = 0

        def show_login():
            controller.show_login_called = True

        def show_backend_waiting_notice(failures):
            controller.backend_notice_calls += 1

        controller.show_login = show_login
        controller.show_backend_waiting_notice = show_backend_waiting_notice

        with patch("alarm_client.main.ApiClient", FakeApiClient), self.assertLogs("alarm_client", level="WARNING"):
            controller.start_without_credentials()

        self.assertTrue(controller.waiting_for_backend)
        self.assertFalse(controller.show_login_called)
        self.assertEqual(controller.backend_notice_calls, 1)
        self.assertIn("后端未就绪", controller.tray.tooltip)

    def test_no_credentials_probe_opens_login_when_backend_is_ready(self):
        from alarm_client.api import ApiError
        from alarm_client.main import AlarmClientApp
        from alarm_client.state import AppConfig

        class FakeApiClient:
            def __init__(self, system, api_base):
                self.system = system
                self.api_base = api_base

            def login(self, username, password):
                raise ApiError(self.system, f"{self.system.upper()} API HTTP 401", status=401)

        controller = AlarmClientApp.__new__(AlarmClientApp)
        controller.config = AppConfig.default()
        controller.clients = {}
        controller.waiting_for_backend = True
        controller._backend_wait_notice_shown = True
        controller.show_login_called = False

        def show_login():
            controller.show_login_called = True

        controller.show_login = show_login

        with patch("alarm_client.main.ApiClient", FakeApiClient), self.assertLogs("alarm_client", level="WARNING"):
            controller.start_without_credentials()

        self.assertFalse(controller.waiting_for_backend)
        self.assertFalse(controller._backend_wait_notice_shown)
        self.assertTrue(controller.show_login_called)

    def test_http_404_login_failure_is_treated_as_backend_unready(self):
        from alarm_client.api import ApiError
        from alarm_client.main import all_login_failures_are_backend_unready

        failures = [
            ("bt", ApiError("bt", "BT API HTTP 404", status=404)),
            ("sy", ApiError("sy", "SY API network error: connection refused")),
        ]

        self.assertTrue(all_login_failures_are_backend_unready(failures))

    def test_auth_failures_are_not_treated_as_backend_unready(self):
        from alarm_client.api import ApiError
        from alarm_client.main import all_login_failures_are_backend_unready

        failures = [
            ("bt", ApiError("bt", "BT API HTTP 401", status=401)),
            ("sy", ApiError("sy", "SY API HTTP 401", status=401)),
        ]

        self.assertFalse(all_login_failures_are_backend_unready(failures))

    def test_timer_retries_saved_login_while_waiting_for_backend(self):
        from alarm_client.main import AlarmClientApp
        from alarm_client.state import AppConfig, Credentials

        controller = AlarmClientApp.__new__(AlarmClientApp)
        controller.config = AppConfig.default()
        controller.config.credentials = Credentials(username="admin", password="secret")
        controller.waiting_for_backend = True
        controller.login_call = None
        controller.poll_called = False

        def login_with_config(**kwargs):
            controller.login_call = kwargs

        def poll_alerts():
            controller.poll_called = True

        controller.login_with_config = login_with_config
        controller.poll_alerts = poll_alerts

        controller.on_timer()

        self.assertEqual(controller.login_call, {"show_dialog_on_failure": False, "wait_for_backend": True})
        self.assertFalse(controller.poll_called)

    def test_saved_login_waits_for_backend_without_showing_login_dialog(self):
        from alarm_client.api import ApiError
        from alarm_client.main import AlarmClientApp
        from alarm_client.state import AppConfig, Credentials

        class FakeApiClient:
            def __init__(self, system, api_base):
                self.system = system
                self.api_base = api_base

            def login(self, username, password):
                raise ApiError(self.system, "network error")

        class FakeTray:
            def __init__(self):
                self.tooltip = ""

            def setToolTip(self, tooltip):
                self.tooltip = tooltip

        controller = AlarmClientApp.__new__(AlarmClientApp)
        controller.config = AppConfig.default()
        controller.config.credentials = Credentials(username="admin", password="secret")
        controller.clients = {}
        controller.tray = FakeTray()
        controller.waiting_for_backend = False
        controller._backend_wait_notice_shown = False
        controller.show_login_called = False
        controller.backend_notice_calls = 0

        def show_login():
            controller.show_login_called = True

        def show_backend_waiting_notice(failures):
            controller.backend_notice_calls += 1

        controller.show_login = show_login
        controller.show_backend_waiting_notice = show_backend_waiting_notice

        with patch("alarm_client.main.ApiClient", FakeApiClient), self.assertLogs("alarm_client", level="WARNING"):
            controller.login_with_config(show_dialog_on_failure=True, wait_for_backend=True)

        self.assertEqual(controller.clients, {})
        self.assertTrue(controller.waiting_for_backend)
        self.assertFalse(controller.show_login_called)
        self.assertEqual(controller.backend_notice_calls, 1)
        self.assertIn("后端未就绪", controller.tray.tooltip)


@unittest.skipIf(QSystemTrayIcon is None, "PySide6 is not installed")
class SingleInstanceTests(unittest.TestCase):
    def test_second_lock_attempt_is_rejected_until_first_releases(self):
        from alarm_client.main import acquire_single_instance_lock

        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "alarm_client.lock"
            first = acquire_single_instance_lock(lock_path)
            self.assertIsNotNone(first)
            second = acquire_single_instance_lock(lock_path)
            self.assertIsNone(second)
            first.unlock()
            third = acquire_single_instance_lock(lock_path)
            self.assertIsNotNone(third)
            third.unlock()


if __name__ == "__main__":
    unittest.main()
