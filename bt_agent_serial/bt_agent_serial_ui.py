from __future__ import annotations

import copy
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

try:
    from serial.tools import list_ports
except Exception:  # pragma: no cover - surfaced in UI when pyserial is missing.
    list_ports = None

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from protected_runtime import (
    agent_config_path,
    load_json_file,
    resolve_launch_command,
    runtime_config_path,
    sqlite_path,
    write_json_file,
)
from bt_agent_serial.config import APP_NAME, CONFIG_JSON_ENV, DEFAULT_CONFIG, normalize_config

BASE_DIR = Path(__file__).resolve().parent
AGENT_PATH = BASE_DIR / "bt_agent_serial.py"
CONFIG_JSON_PATH = agent_config_path(APP_NAME)
RUNTIME_CONFIG_PATH = runtime_config_path(APP_NAME, "runtime_config.json")
DB_PATH = sqlite_path(APP_NAME, "bt_agent_serial_ui.sqlite3")


class BtAgentSerialWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BT 串口采集程序")
        self.resize(980, 720)

        self.local_config = self._load_or_init_config()
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._status: dict[str, Any] = {}
        self._manual_stop_requested = False

        self._build_ui()
        self._refresh_serial_ports(preferred_port=str(self.local_config.get("serial", {}).get("port", "")))
        self._load_config_into_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_log_queue)
        self._timer.start(150)

        if bool(self.local_config.get("ui", {}).get("auto_start", False)):
            QTimer.singleShot(500, self.start_agent)

    def _load_or_init_config(self) -> dict:
        if CONFIG_JSON_PATH.exists():
            try:
                loaded = load_json_file(CONFIG_JSON_PATH)
                if isinstance(loaded, dict):
                    return normalize_config(loaded)
            except Exception:
                pass
        config = copy.deepcopy(DEFAULT_CONFIG)
        write_json_file(CONFIG_JSON_PATH, config)
        return config

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        self.primary_button = QPushButton("启动")
        self.primary_button.clicked.connect(self.toggle_agent)
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.save_settings)
        self.apply_button = QPushButton("保存并应用")
        self.apply_button.clicked.connect(self.save_and_apply)
        self.reset_defaults_button = QPushButton("返回默认设置")
        self.reset_defaults_button.clicked.connect(self.reset_to_defaults)
        self.auto_start_checkbox = QCheckBox("自动启动")
        header.addWidget(self.primary_button)
        header.addWidget(self.save_button)
        header.addWidget(self.apply_button)
        header.addWidget(self.reset_defaults_button)
        header.addWidget(self.auto_start_checkbox)
        header.addStretch(1)
        layout.addLayout(header)

        config_row = QHBoxLayout()
        config_row.addWidget(self._build_device_group(), 1)
        config_row.addWidget(self._build_serial_group(), 2)
        config_row.addWidget(self._build_redis_group(), 2)
        layout.addLayout(config_row)

        status_group = QGroupBox("运行状态")
        status_grid = QGridLayout(status_group)
        self.status_labels: dict[str, QLabel] = {}
        fields = [
            ("process", "进程"),
            ("serial_status", "串口"),
            ("redis", "Redis"),
            ("valid_frames", "有效帧"),
            ("parse_errors", "解析错误"),
            ("redis_publish_errors", "发布错误"),
            ("last_frame_at", "最近帧"),
            ("uptime_sec", "运行时长"),
            ("config", "运行配置"),
        ]
        for index, (key, title) in enumerate(fields):
            row = index // 3
            col = (index % 3) * 2
            status_grid.addWidget(QLabel(f"{title}:"), row, col)
            label = QLabel("-")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.status_labels[key] = label
            status_grid.addWidget(label, row, col + 1)
        layout.addWidget(status_group)

        self.log_text = QPlainTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(2000)
        layout.addWidget(self.log_text, 1)

        self.setCentralWidget(root)
        self._refresh_buttons()
        self._refresh_status_labels()

    def _build_device_group(self) -> QGroupBox:
        group = QGroupBox("设备")
        form = QFormLayout(group)
        self.nms_id_spin = QSpinBox(self)
        self.nms_id_spin.setRange(1, 999999)
        form.addRow("网管设备ID", self.nms_id_spin)
        return group

    def _build_serial_group(self) -> QGroupBox:
        group = QGroupBox("串口")
        form = QFormLayout(group)
        port_row = QHBoxLayout()
        self.port_combo = QComboBox(self)
        self.port_combo.setEditable(False)
        self.refresh_ports_button = QPushButton("刷新端口")
        self.refresh_ports_button.clicked.connect(self._refresh_serial_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_ports_button)
        self.baudrate_spin = QSpinBox(self)
        self.baudrate_spin.setRange(1200, 1000000)
        self.parity_edit = QLineEdit(self)
        self.bytesize_spin = QSpinBox(self)
        self.bytesize_spin.setRange(5, 8)
        self.stopbits_edit = QLineEdit(self)
        self.frame_len_spin = QSpinBox(self)
        self.frame_len_spin.setRange(8, 4096)
        form.addRow("串口号", port_row)
        form.addRow("波特率", self.baudrate_spin)
        form.addRow("校验位", self.parity_edit)
        form.addRow("数据位", self.bytesize_spin)
        form.addRow("停止位", self.stopbits_edit)
        form.addRow("帧长度", self.frame_len_spin)
        return group

    def _build_redis_group(self) -> QGroupBox:
        group = QGroupBox("Redis 与数据流")
        form = QFormLayout(group)
        self.redis_host_edit = QLineEdit(self)
        self.redis_port_spin = QSpinBox(self)
        self.redis_port_spin.setRange(1, 65535)
        self.redis_db_spin = QSpinBox(self)
        self.redis_db_spin.setRange(0, 15)
        self.stream_key_edit = QLineEdit(self)
        self.maxlen_spin = QSpinBox(self)
        self.maxlen_spin.setRange(1000, 10000000)
        form.addRow("Redis地址", self.redis_host_edit)
        form.addRow("Redis端口", self.redis_port_spin)
        form.addRow("Redis库", self.redis_db_spin)
        form.addRow("数据流名称", self.stream_key_edit)
        form.addRow("最大长度", self.maxlen_spin)
        return group

    def _load_config_into_ui(self) -> None:
        config = normalize_config(self.local_config)
        self.nms_id_spin.setValue(int(config["device"]["nms_id"]))
        serial_config = config["serial"]
        configured_port = str(serial_config["port"])
        if configured_port:
            index = self.port_combo.findData(configured_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        self.baudrate_spin.setValue(int(serial_config["baudrate"]))
        self.parity_edit.setText(str(serial_config.get("parity", "O")))
        self.bytesize_spin.setValue(int(serial_config.get("bytesize", 8)))
        self.stopbits_edit.setText(str(serial_config.get("stopbits", 1)))
        self.frame_len_spin.setValue(int(serial_config.get("frame_len", 44)))
        redis_config = config["redis"]
        self.redis_host_edit.setText(str(redis_config["host"]))
        self.redis_port_spin.setValue(int(redis_config["port"]))
        self.redis_db_spin.setValue(int(redis_config.get("db", 0)))
        stream_config = config["stream"]
        self.stream_key_edit.setText(str(stream_config["packet_stream_key"]))
        self.maxlen_spin.setValue(int(stream_config["packet_maxlen"]))
        self.auto_start_checkbox.setChecked(bool(config.get("ui", {}).get("auto_start", False)))

    def _pull_config_from_ui(self) -> dict:
        config = normalize_config(self.local_config)
        port = self.port_combo.currentData()
        if not port:
            raise ValueError("未检测到可用串口，请连接设备后点击“刷新端口”")
        config["device"]["nms_id"] = int(self.nms_id_spin.value())
        config["serial"].update(
            {
                "port": str(port),
                "baudrate": int(self.baudrate_spin.value()),
                "parity": self.parity_edit.text().strip() or "O",
                "bytesize": int(self.bytesize_spin.value()),
                "stopbits": _parse_stopbits(self.stopbits_edit.text().strip()),
                "frame_len": int(self.frame_len_spin.value()),
            }
        )
        config["redis"].update(
            {
                "host": self.redis_host_edit.text().strip() or "127.0.0.1",
                "port": int(self.redis_port_spin.value()),
                "db": int(self.redis_db_spin.value()),
            }
        )
        config["stream"].update(
            {
                "packet_stream_key": self.stream_key_edit.text().strip() or "stream:udp:packets",
                "packet_maxlen": int(self.maxlen_spin.value()),
            }
        )
        config.setdefault("ui", {})["auto_start"] = bool(self.auto_start_checkbox.isChecked())
        return config

    def _refresh_serial_ports(self, checked: bool = False, preferred_port: str = "") -> None:
        if isinstance(checked, str) and not preferred_port:
            preferred_port = checked
        previous_port = preferred_port or str(self.port_combo.currentData() or self.local_config.get("serial", {}).get("port", ""))
        self.port_combo.clear()
        ports = _available_serial_ports()
        for port, description in ports:
            label = port if not description else f"{port} - {description}"
            self.port_combo.addItem(label, port)
        if not ports:
            self.port_combo.addItem("未检测到可用串口", "")
            self.port_combo.setEnabled(False)
        else:
            self.port_combo.setEnabled(True)
            index = self.port_combo.findData(previous_port)
            self.port_combo.setCurrentIndex(index if index >= 0 else 0)

    def save_settings(self) -> bool:
        try:
            self.local_config = self._pull_config_from_ui()
            write_json_file(CONFIG_JSON_PATH, self.local_config)
            self._append_log(f"[界面] 已保存配置：{CONFIG_JSON_PATH}")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False

    def save_and_apply(self) -> None:
        if not self.save_settings():
            return
        if self._proc is not None and self._proc.poll() is None:
            self.stop_agent()
            QTimer.singleShot(800, self.start_agent)
        else:
            self.start_agent()

    def reset_to_defaults(self) -> None:
        self.local_config = copy.deepcopy(DEFAULT_CONFIG)
        self._refresh_serial_ports(preferred_port=str(self.local_config["serial"]["port"]))
        self._load_config_into_ui()
        self._append_log("[界面] 已恢复默认设置，点击“保存”或“保存并应用”后生效")

    def _build_runtime_config(self) -> dict:
        return normalize_config(self.local_config)

    def _write_runtime_config(self) -> Path:
        write_json_file(RUNTIME_CONFIG_PATH, self._build_runtime_config())
        return RUNTIME_CONFIG_PATH

    def toggle_agent(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self.stop_agent()
        else:
            self.start_agent()

    def start_agent(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if not self.save_settings():
            return False
        runtime_path = self._write_runtime_config()
        env = os.environ.copy()
        env[CONFIG_JSON_ENV] = str(runtime_path)
        if os.name == "nt":
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
        try:
            launch_cmd, launch_cwd = resolve_launch_command(APP_NAME, AGENT_PATH)
            self._proc = subprocess.Popen(
                launch_cmd,
                cwd=str(launch_cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                start_new_session=(os.name != "nt"),
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
            )
        except Exception as exc:
            self._proc = None
            QMessageBox.warning(self, "启动失败", str(exc))
            return False
        self._manual_stop_requested = False
        self._append_log(f"[界面] 已启动串口采集进程，pid={self._proc.pid}")
        self._reader_thread = threading.Thread(target=self._read_child_output, name="bt-serial-ui-reader", daemon=True)
        self._reader_thread.start()
        self._refresh_buttons()
        self._refresh_status_labels()
        return True

    def stop_agent(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self._manual_stop_requested = True
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._append_log("[界面] 已停止串口采集进程")
        self._refresh_buttons()
        self._refresh_status_labels()

    def _read_child_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self._log_queue.put(line.rstrip("\n"))
        code = proc.poll()
        self._log_queue.put(f"[界面] 串口采集进程已退出，退出码={code}")

    def _poll_log_queue(self) -> None:
        while True:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
            self._parse_status_line(line)
        if self._proc is not None and self._proc.poll() is not None:
            self._refresh_buttons()
        self._refresh_status_labels()

    def _parse_status_line(self, line: str) -> None:
        marker = "[BT_SERIAL_STATUS]"
        if marker not in line:
            return
        raw = line.split(marker, 1)[1].strip()
        try:
            parsed = json.loads(raw)
        except Exception:
            return
        if isinstance(parsed, dict):
            self._status = parsed

    def _append_log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{stamp}] {line}")

    def _refresh_buttons(self) -> None:
        running = self._proc is not None and self._proc.poll() is None
        self.primary_button.setText("停止" if running else "启动")

    def _refresh_status_labels(self) -> None:
        running = self._proc is not None and self._proc.poll() is None
        self.status_labels["process"].setText("运行中" if running else ("已停止（手动）" if self._manual_stop_requested else "已停止"))
        self.status_labels["serial_status"].setText(str(self._status.get("serial_status", "-")))
        self.status_labels["redis"].setText("正常" if self._status.get("redis_ok") else "断开")
        for key in ("valid_frames", "parse_errors", "redis_publish_errors", "uptime_sec"):
            self.status_labels[key].setText(str(self._status.get(key, "-")))
        last_frame_at = self._status.get("last_frame_at")
        self.status_labels["last_frame_at"].setText(_format_ts(last_frame_at))
        self.status_labels["config"].setText(str(RUNTIME_CONFIG_PATH))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.stop_agent()
        super().closeEvent(event)


def _parse_stopbits(value: str) -> float | int:
    if not value:
        return 1
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _format_ts(value: Any) -> str:
    try:
        if not value:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except Exception:
        return str(value)


def _available_serial_ports() -> list[tuple[str, str]]:
    if list_ports is None:
        return []
    ports = []
    for port in list_ports.comports():
        device = str(getattr(port, "device", "") or "").strip()
        if not device:
            continue
        description = str(getattr(port, "description", "") or "").strip()
        ports.append((device, description))
    return ports


def main() -> int:
    app = QApplication(sys.argv)
    window = BtAgentSerialWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
