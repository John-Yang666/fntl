from __future__ import annotations

from collections.abc import Iterable
import json
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false")

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QLockFile, QObject, QThread, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWebSockets import QWebSocket, QWebSocketHandshakeOptions
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


def install_sigint_handler(app: QApplication) -> QTimer:
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(250)
    return timer


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


def is_backend_unready_error(error: ApiError) -> bool:
    return error.status is None or error.status not in {400, 401, 403}


def all_login_failures_are_backend_unready(failures: list[tuple[str, ApiError]]) -> bool:
    return bool(failures) and all(is_backend_unready_error(error) for _, error in failures)


def format_login_status(logged_in_systems: Iterable[str]) -> str:
    logged_in = set(logged_in_systems)
    return " ".join(f"{SYSTEM_LABELS[system]}已登录" for system in SYSTEMS if system in logged_in)


class AlarmDetailsWorker(QThread):
    result_ready = Signal(list, dict)

    def __init__(self, clients: dict[str, ApiClient]):
        super().__init__()
        self.clients = dict(clients)

    def run(self) -> None:
        details: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for system, client in self.clients.items():
            try:
                details.extend(client.list_alarm_details())
            except Exception as exc:
                LOGGER.warning("load %s alarm details failed: %s", system, exc)
                errors[system] = str(exc)
        self.result_ready.emit(details, errors)


class AlarmClientApp(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = load_config()
        self.runtime_state = AlertRuntimeState()
        self.clients: dict[str, ApiClient] = {}
        self.current_alerts: list[dict[str, Any]] = []
        self.details_worker: AlarmDetailsWorker | None = None
        self._details_refresh_pending = False
        self.alarm_sockets: dict[str, QWebSocket] = {}
        self._show_popup_after_details = False
        self._shutdown_done = False
        self.waiting_for_backend = False
        self._backend_wait_notice_shown = False
        self.audio_player = AlarmSoundPlayer()
        self.popup = AlarmPopup(self.pause_alerts)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_timer)
        self.tray = self._build_tray()

    def start(self) -> None:
        self.tray.show()
        if self.config.credentials.username and self.config.credentials.password:
            self.login_with_config(show_dialog_on_failure=True, wait_for_backend=True)
        else:
            self.start_without_credentials()

    def _build_tray(self) -> QSystemTrayIcon:
        icon = self.app.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        tray = QSystemTrayIcon(icon, self.app)
        tray.setToolTip("BT/SY 告警声音客户端")
        menu = QMenu()
        self.login_status_action = menu.addAction("")
        self.login_status_action.setEnabled(False)
        self.login_status_action.setVisible(False)
        self.login_status_separator = menu.addSeparator()
        self.login_status_separator.setVisible(False)
        menu.addAction("显示告警详情", self.show_current_alerts)
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

    def on_timer(self) -> None:
        if self.waiting_for_backend and self.config.credentials.username and self.config.credentials.password:
            self.login_with_config(show_dialog_on_failure=False, wait_for_backend=True)
            return
        if self.waiting_for_backend:
            self.start_without_credentials()
            return
        return

    def start_without_credentials(self) -> None:
        failures = self.probe_backend_readiness()
        if all_login_failures_are_backend_unready(failures):
            self.waiting_for_backend = True
            self.timer.start(5000)
            self._update_login_status_display()
            self.tray.setToolTip("BT/SY 告警声音客户端 - 后端未就绪，等待重试")
            self.show_backend_waiting_notice(failures)
            return
        self.waiting_for_backend = False
        self.timer.stop()
        self._backend_wait_notice_shown = False
        self.show_login()

    def probe_backend_readiness(self) -> list[tuple[str, ApiError]]:
        failures: list[tuple[str, ApiError]] = []
        for system in SYSTEMS:
            system_config = self.config.systems[system]
            if not system_config.enabled:
                continue
            client = ApiClient(system, system_config.api_base)
            try:
                client.login("__alarm_client_probe__", "__alarm_client_probe__")
            except ApiError as exc:
                LOGGER.warning("%s readiness probe failed: %s", system, exc)
                failures.append((system, exc))
        return failures

    def show_login(self) -> None:
        dialog = LoginDialog(self.config)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        next_config = dialog.build_config(self.config)
        credentials = dialog.login_credentials()
        self.config = next_config
        self.login(username=credentials.username, password=credentials.password, save_credentials=True, wait_for_backend=True)

    def login_with_config(self, *, show_dialog_on_failure: bool = False, wait_for_backend: bool = False) -> None:
        self.login(
            username=self.config.credentials.username,
            password=self.config.credentials.password,
            save_credentials=False,
            show_dialog_on_failure=show_dialog_on_failure,
            wait_for_backend=wait_for_backend,
        )

    def login(
        self,
        *,
        username: str,
        password: str,
        save_credentials: bool,
        show_dialog_on_failure: bool = False,
        wait_for_backend: bool = False,
    ) -> None:
        if not username or not password:
            if show_dialog_on_failure:
                self.show_login()
            return

        clients: dict[str, ApiClient] = {}
        failures: list[tuple[str, ApiError]] = []
        for system in SYSTEMS:
            system_config = self.config.systems[system]
            if not system_config.enabled:
                continue
            client = ApiClient(system, system_config.api_base)
            try:
                client.login(username, password)
            except ApiError as exc:
                LOGGER.warning("%s login failed: %s", system, exc)
                failures.append((system, exc))
                continue
            clients[system] = client

        if not clients:
            if wait_for_backend and all_login_failures_are_backend_unready(failures):
                self.waiting_for_backend = True
                self.timer.start(5000)
                self._update_login_status_display()
                self.tray.setToolTip("BT/SY 告警声音客户端 - 后端未就绪，等待重试")
                self.show_backend_waiting_notice(failures)
                return
            failure_text = self._format_login_failures(failures) or "BT/SY 均未登录成功"
            QMessageBox.warning(None, "登录失败", failure_text)
            if show_dialog_on_failure:
                self.show_login()
            return

        self.clients = clients
        self.waiting_for_backend = False
        self.timer.stop()
        self._backend_wait_notice_shown = False
        if save_credentials:
            self.config.credentials.username = username
            self.config.credentials.password = password
        save_config(self.config)
        LOGGER.info("logged in systems: %s", ",".join(sorted(self.clients)))
        self.runtime_state.reset()
        self._update_tray_tooltip(0, False)
        if failures:
            self.tray.showMessage(
                "部分系统登录失败",
                self._format_login_failures(failures),
                QSystemTrayIcon.MessageIcon.Warning,
                6000,
            )
        self.connect_alarm_websockets()

    def show_backend_waiting_notice(self, failures: list[tuple[str, ApiError]]) -> None:
        if self._backend_wait_notice_shown:
            return
        self._backend_wait_notice_shown = True
        detail = self._format_login_failures(failures)
        message = "后端没有就绪，程序会自动等待并重试。"
        if detail:
            message = f"{message}\n\n{detail}"
        QMessageBox.information(None, "后端没有就绪", message)

    @staticmethod
    def _format_login_failures(failures: list[tuple[str, ApiError]]) -> str:
        return "\n".join(f"{SYSTEM_LABELS[system]}: {error}" for system, error in failures)

    def refresh_alarm_details(self) -> None:
        if not self.clients or (self.details_worker and self.details_worker.isRunning()):
            if self.details_worker and self.details_worker.isRunning():
                self._details_refresh_pending = True
            return
        self._details_refresh_pending = False
        self.details_worker = AlarmDetailsWorker(self.clients)
        self.details_worker.result_ready.connect(self.handle_details_result)
        self.details_worker.finished.connect(self._details_finished)
        self.details_worker.finished.connect(self.details_worker.deleteLater)
        self.details_worker.start()

    def _details_finished(self) -> None:
        self.details_worker = None
        if self._details_refresh_pending:
            self.refresh_alarm_details()

    def handle_details_result(self, details: list, errors: dict) -> None:
        if errors:
            text = "\n".join(f"{SYSTEM_LABELS.get(system, system)}: {message}" for system, message in errors.items())
            self.tray.showMessage("告警详情读取失败", text, QSystemTrayIcon.MessageIcon.Warning, 4000)

        self.current_alerts = details

        if self.popup.isVisible():
            self.popup.set_alerts(self.current_alerts)
        if self._show_popup_after_details:
            self._show_popup_after_details = False
            self.popup.show_alerts(self.current_alerts)

    def connect_alarm_websockets(self) -> None:
        for socket in self.alarm_sockets.values():
            socket.close()
        self.alarm_sockets.clear()
        for system in self.clients:
            self.connect_alarm_websocket(system)

    def connect_alarm_websocket(self, system: str) -> None:
        if self._shutdown_done or system not in self.clients:
            return
        client = self.clients[system]
        if not client.access_token:
            return
        socket = QWebSocket()
        socket.textMessageReceived.connect(lambda message, current_system=system: self.handle_alarm_ws_message(current_system, message))
        socket.disconnected.connect(lambda current_system=system, current_socket=socket: self.handle_alarm_ws_disconnected(current_system, current_socket))
        self.alarm_sockets[system] = socket
        request = QNetworkRequest(QUrl(client.websocket_url()))
        options = QWebSocketHandshakeOptions()
        options.setSubprotocols(["bt-nms", f"jwt.{client.access_token}"])
        socket.open(request, options)

    def handle_alarm_ws_message(self, system: str, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            LOGGER.warning("invalid %s alarm websocket JSON", system)
            return
        if payload.get("type") == "alarm.ping":
            socket = self.alarm_sockets.get(system)
            if socket is not None:
                socket.sendTextMessage('{"type":"alarm.pong"}')
            return
        if payload.get("type") != "alarm.snapshot":
            return
        evaluation = self.runtime_state.update_snapshot(system, payload)
        self._update_tray_tooltip(evaluation.total_unconfirmed_count, evaluation.has_unconfirmed_alerts)
        if evaluation.should_play_sound:
            self.audio_player.play()
        else:
            self.audio_player.stop()
        if evaluation.has_new_unconfirmed_alerts and evaluation.should_play_sound:
            self._show_popup_after_details = True
        self.refresh_alarm_details()

    def handle_alarm_ws_disconnected(self, system: str, socket: QWebSocket) -> None:
        if self.alarm_sockets.get(system) is socket:
            self.alarm_sockets.pop(system, None)
        socket.deleteLater()
        if not self._shutdown_done and system in self.clients:
            QTimer.singleShot(3000, lambda: self.connect_alarm_websocket(system))

    def _update_tray_tooltip(self, count: int, has_unconfirmed: bool) -> None:
        login_status = self._update_login_status_display()
        status = "待确认告警" if has_unconfirmed else "告警"
        status_parts = [part for part in (login_status, f"{status} {count} 条") if part]
        self.tray.setToolTip(f"BT/SY 告警声音客户端 - {' - '.join(status_parts)}")

    def _update_login_status_display(self) -> str:
        login_status = format_login_status(self.clients.keys())
        action = getattr(self, "login_status_action", None)
        if action is not None:
            action.setText(login_status)
            action.setVisible(bool(login_status))
        separator = getattr(self, "login_status_separator", None)
        if separator is not None:
            separator.setVisible(bool(login_status))
        return login_status

    def show_current_alerts(self) -> None:
        self.popup.show_alerts(self.current_alerts)

    def pause_alerts(self) -> None:
        self.runtime_state.pause()
        self.audio_player.stop()

    def resume_alerts(self) -> None:
        self.runtime_state.resume()
        if self.runtime_state.evaluation().has_unconfirmed_alerts:
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
        selected_devices: set[str] = set()
        failures: list[str] = []
        for system, client in self.clients.items():
            try:
                devices_by_system[system] = client.list_devices()
                selected_devices.update(client.get_monitoring_preference())
            except Exception as exc:
                LOGGER.warning("%s device list failed: %s", system, exc)
                failures.append(f"{SYSTEM_LABELS[system]}: {exc}")
        if failures:
            self.tray.showMessage("设备列表读取失败", "\n".join(failures), QSystemTrayIcon.MessageIcon.Warning, 5000)

        dialog = DeviceSelectionDialog(devices_by_system, selected_devices)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_keys = dialog.selected_keys()
        for system, client in self.clients.items():
            available_ids = {int(item["device_id"]) for item in devices_by_system[system]}
            selected_ids = {
                int(key.split(":", 1)[1]) for key in selected_keys if key.startswith(f"{system}:")
            }
            client.save_monitoring_preference(selected_ids, available_ids)

    def quit(self) -> None:
        self.shutdown()
        self.app.quit()

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self.timer.stop()
        for socket in self.alarm_sockets.values():
            socket.close()
        self.alarm_sockets.clear()
        self.audio_player.stop()
        self.popup.close_without_pause()
        worker = self.details_worker
        if worker is not None and worker.isRunning():
            worker.wait(12000)
        self.details_worker = None
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
    sigint_timer = install_sigint_handler(app)
    QTimer.singleShot(0, controller.start)
    try:
        return app.exec()
    finally:
        sigint_timer.stop()
        controller.shutdown()
        instance_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
