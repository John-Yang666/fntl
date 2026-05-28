import unittest
from pathlib import Path
from unittest.mock import patch

from alarm_client.audio import AlarmSoundPlayer, resolve_resource_path


class AlarmSoundPlayerTests(unittest.TestCase):
    def test_audio_backend_is_initialized_lazily(self):
        player = AlarmSoundPlayer()

        self.assertIsNone(player._player)
        self.assertIsNone(player._audio_output)

    def test_resource_path_uses_pyinstaller_bundle_dir_when_available(self):
        with patch("sys._MEIPASS", "/tmp/alarm-client-bundle", create=True):
            self.assertEqual(
                resolve_resource_path("frontend/public/audio/alert.mp3"),
                Path("/tmp/alarm-client-bundle/frontend/public/audio/alert.mp3"),
            )


if __name__ == "__main__":
    unittest.main()
