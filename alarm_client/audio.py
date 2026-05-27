from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover - exercised only on machines without PySide6
    QUrl = None
    QAudioOutput = None
    QMediaPlayer = None
    QApplication = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALERT_AUDIO = REPO_ROOT / "frontend" / "public" / "audio" / "alert.mp3"


class AlarmSoundPlayer:
    def __init__(self, audio_file: Path = DEFAULT_ALERT_AUDIO):
        self.audio_file = Path(audio_file)
        self._player = None
        self._audio_output = None
        self._fallback_thread: threading.Thread | None = None
        self._fallback_stop = threading.Event()
        self._fallback_proc: subprocess.Popen | None = None

    def play(self) -> None:
        if self._ensure_qt_player():
            self._fallback_stop.set()
            self._stop_fallback_process()
            self._player.play()
            return
        self._start_fallback_loop()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
        self._fallback_stop.set()
        self._stop_fallback_process()

    def _ensure_qt_player(self) -> bool:
        if self._player is not None:
            return True
        if (
            QMediaPlayer is None
            or QAudioOutput is None
            or QCoreApplication is None
            or QCoreApplication.instance() is None
            or not self.audio_file.exists()
        ):
            return False
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(1.0)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        if hasattr(QMediaPlayer, "Loops"):
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.setSource(QUrl.fromLocalFile(str(self.audio_file)))
        return True

    def _start_fallback_loop(self) -> None:
        if self._fallback_thread and self._fallback_thread.is_alive():
            return
        self._fallback_stop.clear()
        self._fallback_thread = threading.Thread(target=self._fallback_loop, daemon=True)
        self._fallback_thread.start()

    def _fallback_loop(self) -> None:
        while not self._fallback_stop.is_set():
            if sys.platform == "darwin" and self.audio_file.exists():
                self._play_with_afplay()
            elif QApplication is not None:
                QApplication.beep()
                self._fallback_stop.wait(2.0)
            else:
                self._fallback_stop.wait(2.0)

    def _play_with_afplay(self) -> None:
        try:
            proc = subprocess.Popen(
                ["/usr/bin/afplay", str(self.audio_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            if QApplication is not None:
                QApplication.beep()
            self._fallback_stop.wait(2.0)
            return
        self._fallback_proc = proc
        while proc.poll() is None and not self._fallback_stop.is_set():
            time.sleep(0.1)
        if self._fallback_stop.is_set() and proc.poll() is None:
            self._stop_fallback_process()
        self._fallback_proc = None

    def _stop_fallback_process(self) -> None:
        proc = self._fallback_proc
        self._fallback_proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
