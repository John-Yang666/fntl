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
    def test_new_unconfirmed_snapshot_requests_playback(self):
        state = AlertRuntimeState()
        evaluation = state.update_snapshot("bt", {
            "revision": 1,
            "total_unconfirmed_count": 1,
            "audible_occurrence_ids": ["alarm-1"],
        })
        self.assertTrue(evaluation.has_new_unconfirmed_alerts)
        self.assertTrue(evaluation.should_play_sound)
        self.assertEqual(evaluation.total_unconfirmed_count, 1)

    def test_pause_silences_current_occurrences_but_not_a_new_one(self):
        state = AlertRuntimeState()
        state.update_snapshot("bt", {
            "revision": 1,
            "total_unconfirmed_count": 1,
            "audible_occurrence_ids": ["alarm-1"],
        })
        state.pause()
        self.assertFalse(state.evaluation().should_play_sound)

        evaluation = state.update_snapshot("bt", {
            "revision": 2,
            "total_unconfirmed_count": 2,
            "audible_occurrence_ids": ["alarm-1", "alarm-2"],
        })
        self.assertTrue(evaluation.has_new_unconfirmed_alerts)
        self.assertTrue(evaluation.should_play_sound)

    def test_current_to_history_with_same_occurrence_id_does_not_look_new(self):
        state = AlertRuntimeState()
        state.update_snapshot("sy", {
            "revision": 1,
            "total_unconfirmed_count": 1,
            "audible_occurrence_ids": ["stable-id"],
        })
        state.pause()
        evaluation = state.update_snapshot("sy", {
            "revision": 2,
            "total_unconfirmed_count": 1,
            "audible_occurrence_ids": ["stable-id"],
        })
        self.assertFalse(evaluation.has_new_unconfirmed_alerts)
        self.assertFalse(evaluation.should_play_sound)


class ConfigDefaultsTests(unittest.TestCase):
    def test_default_config_uses_frontend_api_prefixes(self):
        config = AppConfig.default()

        self.assertEqual(config.systems["bt"].api_base, "http://127.0.0.1:38173/bt-api")
        self.assertEqual(config.systems["sy"].api_base, "http://127.0.0.1:38173/sy-api")
        self.assertIsInstance(config.systems["bt"], SystemConfig)

    def test_legacy_backend_ports_are_migrated_to_frontend_api_prefixes(self):
        config = AppConfig.from_dict({
            "systems": {
                "bt": {"api_base": "http://192.168.1.10:8000/api"},
                "sy": {"api_base": "https://192.168.1.10:8444/api"},
            }
        })

        self.assertEqual(config.systems["bt"].api_base, "http://192.168.1.10:38173/bt-api")
        self.assertEqual(config.systems["sy"].api_base, "https://192.168.1.10:38443/sy-api")


if __name__ == "__main__":
    unittest.main()
