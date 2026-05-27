import unittest

from alarm_client.audio import AlarmSoundPlayer


class AlarmSoundPlayerTests(unittest.TestCase):
    def test_audio_backend_is_initialized_lazily(self):
        player = AlarmSoundPlayer()

        self.assertIsNone(player._player)
        self.assertIsNone(player._audio_output)


if __name__ == "__main__":
    unittest.main()
