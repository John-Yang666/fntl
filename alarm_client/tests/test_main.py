import os
import tempfile
import unittest
from pathlib import Path

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
