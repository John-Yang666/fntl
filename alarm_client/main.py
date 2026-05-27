from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false")

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QLockFile, QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QStyle, QSystemTrayIcon

from alarm_client.api import ApiClient, ApiError
from alarm_client.audio import AlarmSoundPlayer
from alarm_client.state import (
    AppConfig,
    AlertRuntimeState,
    LOCK_PATH,
    LOG_PATH,
    SYSTEM_LABELS,
    SYSTEMS,
    load_config,
    save_config,
)
from alarm_client.ui import AlarmPopup, DeviceSelectionDialog, LoginDialog, SettingsDialog

LOGGER = logging.getLogger("alarm_client")


def configure_logging(log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == log_path for handler in root.handlers):
        return
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def acquire_single_instance_lock(lock_path: Path = LOCK_PATH) -> QLockFile | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(100):
        return None
    return lock


def should_show_current_alerts_for_tray_reason(reason: QSystemTrayIcon.ActivationReason) -> bool:
    return False


def should_open_tray_menu_for_reason(reason: QSystemTrayIcon.ActivationReason) -> bool:
    return False


class PollWorker(QThread):
    result_ready = Signal(dict, dict)

    def __init__(self, clients: dict[str, ApiClient]):
        super().__init__()
        self.clients = dict(clients)

    def run(self) -> None:
        alerts_by_system: dict[str, list[dict[str, Any]]] = {system: [] for system in SYSTEMS}
        errors: dict[str, str] = {}
        for system, client in self.clients.items():
            try:
                alerts_by_system[system] = client.list_active_alarms()
            except Exception as exc:
                LOGGER.warning("poll %s active alarms failed: %s", system, exc)
                errors[system] = str(exc)
        self.result_ready.emit(alerts_by_system, errors)


class AlarmClientApp(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = load_config()
        self.runtime_state = AlertRuntimeState(self.config.selected_devices)
        self.clients: dict[str, ApiClient] = {}
        self.current_alerts: list[dict[str, Any]] = []
        self.poll_worker: PollWorker | None = None
        self._shutdown_done = False
        self.audio_player = AlarmSoundPlayer()
        self.popup = AlarmPopup(self.pause_alerts)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_alerts)
        self.tray = self._build_tray()

    def start(self) -> None:
        self.tray.show()
        if self.config.credentials.username and self.config.credentials.password:
            self.login_with_config(show_dialog_on_failure=True)
        else:
            self.show_login()
        self.timer.start(self.config.poll_interval_seconds * 1000)

    def _build_tray(self) -> QSystemTrayIcon:
        icon = self.app.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        tray = QSystemTrayIcon(icon, self.app)
        tray.setToolTip("BT/SY 告警声音客户端")
        menu = QMenu()
        menu.addAction("显示当前告警", self.show_current_alerts)
        menu.addAction("暂停告警声", self.pause_alerts)
        menu.addAction("恢复告警声", self.resume_alerts)
        menu.addSeparator()
        menu.addAction("设备选择", self.show_device_selection)
        menu.addAction("接口设置", self.show_settings)
        menu.addAction("重新登录", self.show_login)
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        return tray

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if should_show_current_alerts_for_tray_reason(reason):
            self.show_current_alerts()

    def show_login(self) -> None:
        dialog = LoginDialog(self.config)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        next_config = dialog.build_config(self.config)
        credentials = dialog.login_credentials()
        self.config = next_config
        self.login(username=credentials.username, password=credentials.password, save_credentials=True)

    def login_with_config(self, *, show_dialog_on_failure: bool = False) -> None:
        self.login(
            username=self.config.credentials.username,
            password=self.config.credentials.password,
            save_credentials=False,
            show_dialog_on_failure=show_dialog_on_failure,
        )

    def login(
        self,
        *,
        username: str,
        password: str,
        save_credentials: bool,
        show_dialog_on_failure: bool = False,
    ) -> None:
        if not username or not password:
            if show_dialog_on_failure:
                self.show_login()
            return

        clients: dict[str, ApiClient] = {}
        failures: list[str] = []
        for system in SYSTEMS:
            system_config = self.config.systems[system]
            if not system_config.enabled:
                continue
            client = ApiClient(system, system_config.api_base)
            try:
                client.login(username, password)
            except ApiError as exc:
                LOGGER.warning("%s login failed: %s", system, exc)
                failures.append(f"{SYSTEM_LABELS[system]}: {exc}")
                continue
            clients[system] = client

        if not clients:
            QMessageBox.warning(None, "登录失败", "\n".join(failures) or "BT/SY 均未登录成功")
            if show_dialog_on_failure:
                self.show_login()
            return

        self.clients = clients
        if save_credentials:
            self.config.credentials.username = username
            self.config.credentials.password = password
        save_config(self.config)
        LOGGER.info("logged in systems: %s", ",".join(sorted(self.clients)))
        self.runtime_state.reset()
        self.runtime_state.set_selected_devices(self.config.selected_devices)
        if failures:
            self.tray.showMessage("部分系统登录失败", "\n".join(failures), QSystemTrayIcon.MessageIcon.Warning, 6000)
        self.poll_alerts()

    def poll_alerts(self) -> None:
        if not self.clients or (self.poll_worker and self.poll_worker.isRunning()):
            return
        self.poll_worker = PollWorker(self.clients)
        self.poll_worker.result_ready.connect(self.handle_poll_result)
        self.poll_worker.finished.connect(self._poll_finished)
        self.poll_worker.finished.connect(self.poll_worker.deleteLater)
        self.poll_worker.start()

    def _poll_finished(self) -> None:
        self.poll_worker = None

    def handle_poll_result(self, alerts_by_system: dict, errors: dict) -> None:
        if errors:
            text = "\n".join(f"{SYSTEM_LABELS.get(system, system)}: {message}" for system, message in errors.items())
            self.tray.showMessage("告警轮询失败", text, QSystemTrayIcon.MessageIcon.Warning, 4000)

        evaluation = self.runtime_state.evaluate(alerts_by_system)
        self.current_alerts = evaluation.alerts
        self._update_tray_tooltip(evaluation.count, evaluation.has_unconfirmed_alerts)

        if self.popup.isVisible():
            self.popup.set_alerts(self.current_alerts)

        if evaluation.ended_systems:
            ended = "、".join(SYSTEM_LABELS[system] for system in evaluation.ended_systems)
            self.tray.showMessage("告警结束", f"{ended} 有告警结束，请查看历史告警记录。", QSystemTrayIcon.MessageIcon.Warning, 5000)

        if evaluation.should_play_sound:
            self.popup.show_alerts(self.current_alerts)
            self.audio_player.play()
        elif not evaluation.has_unconfirmed_alerts or self.runtime_state.paused:
            self.audio_player.stop()

    def _update_tray_tooltip(self, count: int, has_unconfirmed: bool) -> None:
        status = "未确认告警" if has_unconfirmed else "当前告警"
        self.tray.setToolTip(f"BT/SY 告警声音客户端 - {status} {count} 条")

    def show_current_alerts(self) -> None:
        self.popup.show_alerts(self.current_alerts)

    def pause_alerts(self) -> None:
        self.runtime_state.pause()
        self.audio_player.stop()

    def resume_alerts(self) -> None:
        self.runtime_state.resume()
        if any(not bool(alert.get("confirmed")) for alert in self.current_alerts):
            self.popup.show_alerts(self.current_alerts)
            self.audio_player.play()

    def show_settings(self) -> None:
        dialog = SettingsDialog(self.config)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.config = dialog.apply_to(self.config)
        save_config(self.config)
        if self.config.credentials.username and self.config.credentials.password:
            self.login_with_config(show_dialog_on_failure=False)

    def show_device_selection(self) -> None:
        if not self.clients:
            QMessageBox.warning(None, "无法选择设备", "请先登录至少一个系统。")
            return
        devices_by_system: dict[str, list[dict[str, Any]]] = {system: [] for system in SYSTEMS}
        failures: list[str] = []
        for system, client in self.clients.items():
            try:
                devices_by_system[system] = client.list_devices()
            except Exception as exc:
                LOGGER.warning("%s device list failed: %s", system, exc)
                failures.append(f"{SYSTEM_LABELS[system]}: {exc}")
        if failures:
            self.tray.showMessage("设备列表读取失败", "\n".join(failures), QSystemTrayIcon.MessageIcon.Warning, 5000)

        dialog = DeviceSelectionDialog(devices_by_system, self.config.selected_devices)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.config.selected_devices = dialog.selected_keys()
        self.runtime_state.set_selected_devices(self.config.selected_devices)
        self.runtime_state.reset()
        save_config(self.config)
        self.poll_alerts()

    def quit(self) -> None:
        self.shutdown()
        self.app.quit()

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self.timer.stop()
        self.audio_player.stop()
        self.popup.close_without_pause()
        worker = self.poll_worker
        if worker is not None and worker.isRunning():
            worker.wait(12000)
        self.poll_worker = None
        self.tray.hide()


def main() -> int:
    configure_logging()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        QMessageBox.information(None, "告警客户端已在运行", "告警声音客户端已经在运行。")
        return 0
    controller = AlarmClientApp(app)
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
    try:
        return app.exec()
    finally:
        controller.shutdown()
        instance_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
