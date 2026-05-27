import tempfile
import unittest
import stat
from pathlib import Path

from alarm_client.state import (
    AlertRuntimeState,
    AppConfig,
    Credentials,
    SystemConfig,
    decode_password,
    encode_password,
    load_config,
    save_config,
)


class PasswordStorageTests(unittest.TestCase):
    def test_password_is_obfuscated_in_config_and_restored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            config = AppConfig(credentials=Credentials(username="alice", password="plain-secret"))

            save_config(config, path)

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("plain-secret", raw)
            restored = load_config(path)
            self.assertEqual(restored.credentials.username, "alice")
            self.assertEqual(restored.credentials.password, "plain-secret")

    def test_config_save_is_private_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            config = AppConfig(credentials=Credentials(username="alice", password="plain-secret"))

            save_config(config, path)

            self.assertEqual(load_config(path).credentials.password, "plain-secret")
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode & 0o077, 0)

    def test_encode_decode_password_round_trip(self):
        encoded = encode_password("abc123!@#")

        self.assertNotEqual(encoded, "abc123!@#")
        self.assertEqual(decode_password(encoded), "abc123!@#")


class AlertRuntimeStateTests(unittest.TestCase):
    def test_new_unconfirmed_alert_clears_pause_and_requests_playback(self):
        state = AlertRuntimeState(selected_devices=set())
        state.paused = True

        evaluation = state.evaluate(
            {
                "bt": [
                    {
                        "device_id": 1,
                        "device_name": "BT-1",
                        "alarm_code": 40,
                        "alarm_meaning": "测试告警",
                        "timestamp": "2026-05-26T10:00:00+08:00",
                        "confirmed": False,
                    }
                ],
                "sy": [],
            }
        )

        self.assertTrue(evaluation.has_new_unconfirmed_alerts)
        self.assertTrue(evaluation.should_play_sound)
        self.assertFalse(state.paused)
        self.assertEqual(evaluation.count, 1)

    def test_closed_popup_pause_blocks_existing_alert_until_new_one(self):
        state = AlertRuntimeState(selected_devices=set())
        first = {
            "bt": [
                {
                    "device_id": 1,
                    "device_name": "BT-1",
                    "alarm_code": 40,
                    "alarm_meaning": "测试告警",
                    "timestamp": "2026-05-26T10:00:00+08:00",
                    "confirmed": False,
                }
            ],
            "sy": [],
        }

        state.evaluate(first)
        state.pause()
        second = state.evaluate(first)

        self.assertFalse(second.has_new_unconfirmed_alerts)
        self.assertFalse(second.should_play_sound)
        self.assertTrue(state.paused)

        third = state.evaluate(
            {
                "bt": [
                    first["bt"][0],
                    {
                        "device_id": 2,
                        "device_name": "BT-2",
                        "alarm_code": 41,
                        "alarm_meaning": "新增告警",
                        "timestamp": "2026-05-26T10:01:00+08:00",
                        "confirmed": False,
                    },
                ],
                "sy": [],
            }
        )

        self.assertTrue(third.has_new_unconfirmed_alerts)
        self.assertTrue(third.should_play_sound)
        self.assertFalse(state.paused)

    def test_selected_devices_filter_alerts(self):
        state = AlertRuntimeState(selected_devices={"sy:8"})

        evaluation = state.evaluate(
            {
                "bt": [
                    {
                        "device_id": 1,
                        "device_name": "BT-1",
                        "alarm_code": 40,
                        "alarm_meaning": "BT 告警",
                        "timestamp": "2026-05-26T10:00:00+08:00",
                        "confirmed": False,
                    }
                ],
                "sy": [
                    {
                        "device_id": 8,
                        "device_name": "SY-8",
                        "alarm_code": 62,
                        "alarm_meaning": "SY 告警",
                        "timestamp": "2026-05-26T10:00:00+08:00",
                        "confirmed": False,
                    }
                ],
            }
        )

        self.assertEqual(evaluation.count, 1)
        self.assertEqual(evaluation.alerts[0]["system"], "sy")
        self.assertEqual(evaluation.alerts[0]["device_id"], 8)


class ConfigDefaultsTests(unittest.TestCase):
    def test_default_config_uses_local_backend_ports(self):
        config = AppConfig.default()

        self.assertEqual(config.systems["bt"].api_base, "http://127.0.0.1:8000/api")
        self.assertEqual(config.systems["sy"].api_base, "http://127.0.0.1:8001/api")
        self.assertIsInstance(config.systems["bt"], SystemConfig)


if __name__ == "__main__":
    unittest.main()
