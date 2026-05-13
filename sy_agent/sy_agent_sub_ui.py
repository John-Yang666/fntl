#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import json
import os
import pprint
import queue
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import redis
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QInputDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from protected_runtime import (
    agent_config_path,
    load_json_file,
    lock_path,
    resolve_launch_command,
    runtime_config_path,
    sqlite_path,
    write_json_file,
)

from sy_agent_ui import (
    ALARM_WAV_PATH,
    AlarmSoundPlayer,
    CollapsibleSection,
    DISK_ALARM_WAV_PATH,
    EDITOR_PANEL_MIN_HEIGHT,
    LOG_COLORS,
    LOG_RE,
    REMOTE_APPLY_ROLLBACK_GRACE_SEC,
    ToggleSwitch,
    UNEXPECTED_RESTART_DELAY_MS,
    OPEN_RE,
    OVERVIEW_PANEL_MIN_HEIGHT,
    PORT_FAIL_RE,
    RESP_OK_RE,
    STATUS_RE,
    _apply_status_style,
    _age_text,
    build_template_config,
    _decode_geometry,
    _encode_geometry,
    _load_py_config,
    _new_line_runtime_state,
    _now_iso,
    _parse_dashboard_payload,
    _parse_status_payload,
    _plain_log_lines,
    _format_redis_state_text,
    _redis_alarm_active,
    _split_pair_text,
    _summarize_link_pair,
    UI_TEMPLATE_BASE,
    acquire_single_instance_lock,
    collect_disk_alerts,
    collect_disk_usage,
    default_disk_alert_config,
    disk_monitor_specs,
    normalize_disk_alert_config,
    normalize_config,
)


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
CONFIG_PY_PATH = BASE_DIR / "config.py"
CONFIG_JSON_PATH = agent_config_path("sy_agent")
DB_PATH = sqlite_path("sy_agent", "sy_agent_sub_ui.sqlite3")
RUNTIME_CONFIG_PATH = runtime_config_path("sy_agent", "runtime_sub_agent_config.json")
SY_AGENT_PATH = BASE_DIR / "sy_agent.py"
CONFIG_JSON_ENV = "SY_AGENT_CONFIG_JSON"
SUBAGENT_CONTROL_STREAM = "sy-subagent-control"
STATUS_TTL_SEC = 15
STATUS_REFRESH_SEC = 3.0
DETAIL_SNAPSHOT_TTL_SEC = 8
SETTINGS_LOCK_PASSWORD = "whbt"
DISK_CHECK_SEC = 30.0
DISK_THRESHOLD_OPTIONS = [5, 10, 15, 20, 25, 30]


def desired_config_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:desired_config"


def desired_meta_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:desired_meta"


def applied_meta_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:applied_meta"


def status_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:status"


def detail_snapshot_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:detail_snapshot"


def _load_json_config(path: Path) -> dict:
    loaded = load_json_file(path)
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return loaded


def detect_private_ipv4() -> str:
    candidates: list[str] = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = str(item[4][0])
            if ip and ip not in candidates:
                candidates.append(ip)
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = str(sock.getsockname()[0])
            if ip and ip not in candidates:
                candidates.insert(0, ip)
        finally:
            sock.close()
    except Exception:
        pass
    for ip in candidates:
        if ip.startswith(("10.", "192.168.", "172.")) and ip != "127.0.0.1":
            return ip
    for ip in candidates:
        if ip != "127.0.0.1":
            return ip
    return "127.0.0.1"


class SubAgentStateStore:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    bootstrap_json TEXT NOT NULL,
                    applied_config_json TEXT NOT NULL,
                    disk_alert_json TEXT NOT NULL DEFAULT '{}',
                    sound_enabled INTEGER NOT NULL,
                    auto_start INTEGER NOT NULL,
                    settings_locked INTEGER NOT NULL DEFAULT 0,
                    applied_at TEXT NOT NULL DEFAULT '',
                    window_geometry TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(app_state)").fetchall()}
            if "disk_alert_json" not in columns:
                conn.execute("ALTER TABLE app_state ADD COLUMN disk_alert_json TEXT NOT NULL DEFAULT '{}'")
            if "settings_locked" not in columns:
                conn.execute("ALTER TABLE app_state ADD COLUMN settings_locked INTEGER NOT NULL DEFAULT 0")
            if "applied_at" not in columns:
                conn.execute("ALTER TABLE app_state ADD COLUMN applied_at TEXT NOT NULL DEFAULT ''")
            conn.commit()

    def load_or_init(self, template_config: dict) -> dict:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM app_state WHERE id = 1").fetchone()
            if row is not None:
                applied_config = normalize_config(json.loads(row["applied_config_json"]), template_config)
                if CONFIG_JSON_PATH.exists():
                    try:
                        applied_config = normalize_config(_load_json_config(CONFIG_JSON_PATH), template_config)
                    except Exception:
                        pass
                return {
                    "bootstrap": json.loads(row["bootstrap_json"]),
                    "applied_config": applied_config,
                    "disk_alert": normalize_disk_alert_config(json.loads(row["disk_alert_json"] or "{}")),
                    "sound_enabled": bool(row["sound_enabled"]),
                    "auto_start": bool(row["auto_start"]),
                    "settings_locked": bool(row["settings_locked"]),
                    "applied_at": str(row["applied_at"] or "-"),
                    "window_geometry": row["window_geometry"] or "",
                }

        state = {
            "bootstrap": {
                "redis": copy.deepcopy(template_config.get("redis", {})),
                "agent_ip": detect_private_ipv4(),
                "agent_name": socket.gethostname(),
            },
            "applied_config": normalize_config({"lines": []}, template_config),
            "disk_alert": default_disk_alert_config(),
            "sound_enabled": True,
            "auto_start": True,
            "settings_locked": False,
            "applied_at": "-",
            "window_geometry": "",
        }
        if CONFIG_JSON_PATH.exists():
            try:
                state["applied_config"] = normalize_config(_load_json_config(CONFIG_JSON_PATH), template_config)
            except Exception:
                state["applied_config"] = normalize_config({"lines": []}, template_config)
        else:
            write_json_file(CONFIG_JSON_PATH, state["applied_config"])
        self.save(
            bootstrap=state["bootstrap"],
            applied_config=state["applied_config"],
            disk_alert=state["disk_alert"],
            sound_enabled=state["sound_enabled"],
            auto_start=state["auto_start"],
            settings_locked=state["settings_locked"],
            applied_at=state["applied_at"],
            window_geometry=state["window_geometry"],
        )
        return state

    def save(
        self,
        *,
        bootstrap: dict,
        applied_config: dict,
        disk_alert: dict,
        sound_enabled: bool,
        auto_start: bool,
        settings_locked: bool,
        applied_at: str,
        window_geometry: str,
    ) -> None:
        disk_alert_payload = json.dumps(normalize_disk_alert_config(disk_alert), ensure_ascii=False, indent=2)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(id, bootstrap_json, applied_config_json, disk_alert_json, sound_enabled, auto_start, settings_locked, applied_at, window_geometry, updated_at)
                VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    bootstrap_json=excluded.bootstrap_json,
                    applied_config_json=excluded.applied_config_json,
                    disk_alert_json=excluded.disk_alert_json,
                    sound_enabled=excluded.sound_enabled,
                    auto_start=excluded.auto_start,
                    settings_locked=excluded.settings_locked,
                    applied_at=excluded.applied_at,
                    window_geometry=excluded.window_geometry,
                    updated_at=excluded.updated_at
                """,
                (
                    json.dumps(bootstrap, ensure_ascii=False, indent=2),
                    json.dumps(applied_config, ensure_ascii=False, indent=2),
                    disk_alert_payload,
                    1 if sound_enabled else 0,
                    1 if auto_start else 0,
                    1 if settings_locked else 0,
                    applied_at or "-",
                    window_geometry or "",
                    _now_iso(),
                ),
            )
            conn.commit()


class SyUISubAgentWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SY串口通信分机程序")
        self.resize(1180, 860)
        self.setMinimumSize(1000, 720)

        self.template_config = build_template_config(copy.deepcopy(UI_TEMPLATE_BASE))
        self.store = SubAgentStateStore(DB_PATH)
        state = self.store.load_or_init(self.template_config)

        self.bootstrap = copy.deepcopy(state["bootstrap"])
        self.applied_config = copy.deepcopy(state["applied_config"])
        self.disk_alert_config = normalize_disk_alert_config(state.get("disk_alert"))
        self._disk_specs = disk_monitor_specs()
        self.sound_enabled = bool(state["sound_enabled"])
        self.auto_start = bool(state["auto_start"])
        self._settings_locked = bool(state["settings_locked"])
        self.applied_at = str(state.get("applied_at") or "-")
        self.process_state = "已停止"
        self.redis_state = "未知"
        self.alarm_state = "静默"
        self.last_alert_text = "-"
        self.desired_version = "-"
        self.applied_version = "-"
        self.apply_state = "-"

        self._proc: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_thread: Optional[threading.Thread] = None
        self._manual_stop_requested = False
        self._unexpected_restart_pending = False
        self._remote_apply_rollback: Optional[dict[str, Any]] = None
        self._remote_apply_deadline_mono = 0.0
        self._control_thread: Optional[threading.Thread] = None
        self._control_redis_client: Optional[redis.Redis] = None
        self._control_stop_evt = threading.Event()
        self._control_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._log_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._log_lines: "deque[str]" = deque(maxlen=8)
        self._log_dirty = False
        self._overview_detail_text_cache = ""
        self._agent_dashboard_text_cache = ""
        self._drop_runtime_lines = False
        self._line_status: dict[int, dict[str, Any]] = {}
        self._active_port_alerts: dict[tuple[int, str], str] = {}
        self._recent_runtime_events: "deque[str]" = deque(maxlen=12)
        self._active_disk_alerts: list[str] = []
        self._sound_loop_active = False
        self._alarm_paused_until_clear = False
        self._settings_lock_targets: list[QWidget] = []

        self._alarm_player = AlarmSoundPlayer()
        self._alarm_player.start()

        self._build_ui()
        self._load_bootstrap_into_ui()
        self._reset_runtime_state()
        self._update_static_labels()

        if state["window_geometry"]:
            geometry = _decode_geometry(state["window_geometry"])
            if not geometry.isEmpty():
                self.restoreGeometry(geometry)

        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._poll_runtime_queues)
        self._queue_timer.start(150)

        self._summary_timer = QTimer(self)
        self._summary_timer.timeout.connect(self._refresh_runtime_summary)
        self._summary_timer.start(1000)

        self._disk_timer = QTimer(self)
        self._disk_timer.timeout.connect(self._check_disk_alerts)
        self._disk_timer.start(int(DISK_CHECK_SEC * 1000))

        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.timeout.connect(self._flush_log_view)
        self._log_flush_timer.start(1000)

        self._control_thread = threading.Thread(target=self._remote_control_loop, daemon=True)
        self._control_thread.start()

        if self.auto_start:
            QTimer.singleShot(500, self.start_agent)

    def _build_ui(self) -> None:
        content = QWidget(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.top_section = CollapsibleSection("控制", self._build_top_panel(), expanded=True, parent=self)
        self.overview_section = CollapsibleSection("线路状态", self._build_overview_panel(), expanded=True, parent=self)
        self.config_section = CollapsibleSection("配置", self._build_config_panel(), expanded=True, parent=self)
        self.log_section = CollapsibleSection("日志", self._build_log_panel(), expanded=True, parent=self)

        root.addWidget(self.top_section)
        root.addWidget(self.overview_section)
        root.addWidget(self.config_section)
        root.addWidget(self.log_section)
        root.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        self._rebuild_settings_lock_targets()

    def _build_top_panel(self) -> QWidget:
        top = QWidget(self)
        layout = QGridLayout(top)

        self.primary_button = QPushButton("启动")
        self.primary_button.clicked.connect(self._on_primary_button)
        self.lock_button = QPushButton("锁定")
        self.lock_button.clicked.connect(self._toggle_settings_lock)
        self.pause_alarm_button = QPushButton("暂停告警声")
        self.pause_alarm_button.clicked.connect(self._pause_alarm_sound)
        self.sound_checkbox = ToggleSwitch(self)
        self.sound_checkbox.toggled.connect(self._on_sound_toggle)
        self.sound_label = QLabel("声音")
        self.test_alarm_button = QPushButton("试音")
        self.test_alarm_button.clicked.connect(self._test_alarm_sound)
        self.auto_start_checkbox = QCheckBox("自动启动")
        self.auto_start_checkbox.toggled.connect(self._on_auto_start_toggle)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(10)
        actions_row.addWidget(self.primary_button)
        actions_row.addWidget(self.auto_start_checkbox)
        actions_row.addWidget(self.lock_button)
        actions_row.addWidget(self.pause_alarm_button)
        actions_row.addWidget(self.sound_label)
        actions_row.addWidget(self.sound_checkbox)
        actions_row.addWidget(self.test_alarm_button)
        actions_row.addStretch(1)
        layout.addLayout(actions_row, 0, 0, 1, 8)

        layout.addWidget(QLabel("进程状态："), 0, 8)
        self.process_value = QLabel("-")
        layout.addWidget(self.process_value, 0, 9)

        layout.addWidget(QLabel("远程配置："), 1, 0)
        self.version_value = QLabel("-")
        layout.addWidget(self.version_value, 1, 1)
        layout.addWidget(QLabel("应用结果："), 1, 2)
        self.apply_value = QLabel("-")
        layout.addWidget(self.apply_value, 1, 3)
        layout.addWidget(QLabel("应用时间："), 1, 4)
        self.applied_at_value = QLabel("-")
        layout.addWidget(self.applied_at_value, 1, 5)
        layout.addWidget(QLabel("Redis连接状态："), 1, 8)
        self.redis_value = QLabel("-")
        layout.addWidget(self.redis_value, 1, 9)

        layout.addWidget(QLabel("最近告警："), 2, 0)
        self.last_alert_value = QLabel("-")
        self.last_alert_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.last_alert_value, 2, 1, 1, 9)
        layout.setColumnStretch(1, 1)
        return top

    def _build_config_panel(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)

        toolbar = QHBoxLayout()
        self.save_button = QPushButton("保存并应用")
        self.save_button.clicked.connect(self.save_and_apply_settings)
        self.import_button = QPushButton("导入 JSON 配置")
        self.import_button.clicked.connect(self.import_from_json_file)
        self.export_button = QPushButton("导出 JSON 配置")
        self.export_button.clicked.connect(self.export_to_json_config)
        self.import_py_button = QPushButton("导入 .py(开发)")
        self.import_py_button.clicked.connect(self.import_from_py_file)
        self.export_py_button = QPushButton("导出 .py(开发)")
        self.export_py_button.clicked.connect(self.export_to_py_config)
        self.export_diag_button = QPushButton("导出诊断包")
        self.export_diag_button.clicked.connect(self.export_diagnostic_bundle)
        toolbar.addWidget(self.save_button)
        toolbar.addWidget(self.import_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.import_py_button)
        toolbar.addWidget(self.export_py_button)
        toolbar.addWidget(self.export_diag_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        tabs = QTabWidget(self)

        settings_page = QWidget(self)
        settings_page_layout = QVBoxLayout(settings_page)
        settings_page_layout.setContentsMargins(0, 0, 0, 0)
        settings_page_layout.setSpacing(8)

        settings_box = QGroupBox("本机设置")
        settings_form = QFormLayout(settings_box)
        self.redis_host_edit = QLineEdit(self)
        self.redis_port_edit = QLineEdit(self)
        self.redis_db_edit = QLineEdit(self)
        self.agent_ip_edit = QLineEdit(self)
        self.agent_name_edit = QLineEdit(self)
        settings_form.addRow("Redis Host", self.redis_host_edit)
        settings_form.addRow("Redis Port", self.redis_port_edit)
        settings_form.addRow("Redis DB", self.redis_db_edit)
        settings_form.addRow("Agent IP", self.agent_ip_edit)
        settings_form.addRow("Agent 名称", self.agent_name_edit)
        settings_box.setMaximumWidth(520)
        settings_page_layout.addWidget(settings_box, alignment=Qt.AlignLeft)
        settings_page_layout.addStretch(1)

        disk_page = QWidget(self)
        disk_page_layout = QVBoxLayout(disk_page)
        disk_page_layout.setContentsMargins(0, 0, 0, 0)
        disk_page_layout.setSpacing(8)
        disk_box = QGroupBox("磁盘告警")
        disk_form = QFormLayout(disk_box)
        self.disk_c_checkbox = QCheckBox("C盘", self)
        self.disk_d_checkbox = QCheckBox("D盘", self)
        self.disk_c_checkbox.setText(self._disk_specs[0]["label"])
        self.disk_d_checkbox.setText(self._disk_specs[1]["label"])
        self.disk_threshold_combo = QComboBox(self)
        for value in DISK_THRESHOLD_OPTIONS:
            self.disk_threshold_combo.addItem(f"{value}%", value)
        self.disk_c_checkbox.toggled.connect(lambda _checked: self._on_disk_alert_ui_changed())
        self.disk_d_checkbox.toggled.connect(lambda _checked: self._on_disk_alert_ui_changed())
        self.disk_threshold_combo.currentIndexChanged.connect(lambda _index: self._on_disk_alert_ui_changed())
        disk_form.addRow("监控", self._wrap_disk_checks())
        disk_form.addRow("阈值", self.disk_threshold_combo)
        disk_box.setMaximumWidth(520)
        disk_page_layout.addWidget(disk_box, alignment=Qt.AlignLeft)

        usage_box = QGroupBox("磁盘使用情况")
        usage_form = QFormLayout(usage_box)
        self.disk_usage_c_value = QLabel("-")
        self.disk_usage_d_value = QLabel("-")
        self.disk_usage_c_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.disk_usage_d_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        usage_form.addRow(self._disk_specs[0]["label"], self.disk_usage_c_value)
        usage_form.addRow(self._disk_specs[1]["label"], self.disk_usage_d_value)
        usage_box.setMaximumWidth(520)
        disk_page_layout.addWidget(usage_box, alignment=Qt.AlignLeft)
        disk_page_layout.addStretch(1)

        tabs.addTab(settings_page, "本机设置")
        tabs.addTab(disk_page, "磁盘告警")
        layout.addWidget(tabs)
        layout.addStretch(1)
        return box

    def _build_overview_panel(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)

        self.line_status_tabs = QTabWidget(self)
        self.overview_table = QTableWidget(0, 7, self)
        self.overview_table.setHorizontalHeaderLabels(["线路ID", "名称", "头端口", "尾端口", "通信状态", "最近成功", "告警"])
        self.overview_table.verticalHeader().setVisible(False)
        self.overview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.overview_table.setSelectionMode(QTableWidget.NoSelection)
        self.overview_table.horizontalHeader().setStretchLastSection(True)
        self.overview_table.setMinimumHeight(OVERVIEW_PANEL_MIN_HEIGHT)

        self.overview_detail_text = QPlainTextEdit(self)
        self.overview_detail_text.setReadOnly(True)
        self.overview_detail_text.setMinimumHeight(OVERVIEW_PANEL_MIN_HEIGHT)
        self.overview_detail_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        detail_font = QFont("Menlo")
        detail_font.setStyleHint(QFont.Monospace)
        self.overview_detail_text.setFont(detail_font)

        self.line_status_tabs.addTab(self.overview_table, "概览")
        self.line_status_tabs.addTab(self.overview_detail_text, "详情")
        layout.addWidget(self.line_status_tabs)
        return box

    def _build_log_panel(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)

        self.log_text = QTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(EDITOR_PANEL_MIN_HEIGHT)
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.Monospace)
        self.log_text.setFont(mono)
        layout.addWidget(self.log_text)
        return box

    def _wrap_disk_checks(self) -> QWidget:
        box = QWidget(self)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.disk_c_checkbox)
        layout.addWidget(self.disk_d_checkbox)
        layout.addStretch(1)
        return box

    def _load_bootstrap_into_ui(self) -> None:
        redis_cfg = self.bootstrap.get("redis", {})
        self.redis_host_edit.setText(str(redis_cfg.get("host", "localhost")))
        self.redis_port_edit.setText(str(redis_cfg.get("port", 6379)))
        self.redis_db_edit.setText(str(redis_cfg.get("db", 0)))
        self.agent_ip_edit.setText(str(self.bootstrap.get("agent_ip", detect_private_ipv4())))
        self.agent_name_edit.setText(str(self.bootstrap.get("agent_name", socket.gethostname())))
        self.disk_c_checkbox.setChecked(bool(self.disk_alert_config.get("c_enabled", False)))
        self.disk_d_checkbox.setChecked(bool(self.disk_alert_config.get("d_enabled", False)))
        idx = self.disk_threshold_combo.findData(int(self.disk_alert_config.get("threshold_percent", 10)))
        self.disk_threshold_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._refresh_disk_usage_view()

    def _pull_bootstrap_from_ui(self) -> dict:
        return {
            "redis": {
                "host": self.redis_host_edit.text().strip() or "localhost",
                "port": int(self.redis_port_edit.text().strip()),
                "db": int(self.redis_db_edit.text().strip()),
            },
            "agent_ip": self.agent_ip_edit.text().strip() or detect_private_ipv4(),
            "agent_name": self.agent_name_edit.text().strip() or socket.gethostname(),
        }

    def _pull_disk_alert_from_ui(self) -> dict[str, Any]:
        threshold = self.disk_threshold_combo.currentData()
        try:
            threshold_int = int(threshold)
        except Exception:
            threshold_int = int(self.disk_alert_config.get("threshold_percent", 10))
        return normalize_disk_alert_config(
            {
                "c_enabled": self.disk_c_checkbox.isChecked(),
                "d_enabled": self.disk_d_checkbox.isChecked(),
                "threshold_percent": threshold_int,
            }
        )

    def _refresh_disk_usage_view(self) -> None:
        usage_items = collect_disk_usage(self.disk_alert_config)
        usage_map = {str(item.get("slot", "")).lower(): item for item in usage_items if isinstance(item, dict)}
        threshold_percent = int(self.disk_alert_config.get("threshold_percent", 10))
        self._apply_disk_usage_label(self.disk_usage_c_value, usage_map.get("c"), threshold_percent)
        self._apply_disk_usage_label(self.disk_usage_d_value, usage_map.get("d"), threshold_percent)

    def _apply_disk_usage_label(self, label: QLabel, item: Optional[dict[str, Any]], threshold_percent: int) -> None:
        if not item:
            _apply_status_style(label, "不可用", kind="bad")
            return
        text = str(item.get("text", "-"))
        if not bool(item.get("enabled")):
            _apply_status_style(label, text, kind="neutral")
            return
        free_pct = item.get("free_pct")
        if isinstance(free_pct, (int, float)):
            kind = "bad" if float(free_pct) <= float(threshold_percent) else "good"
            _apply_status_style(label, text, kind=kind)
            return
        _apply_status_style(label, text, kind="bad")

    def _on_disk_alert_ui_changed(self) -> None:
        self.disk_alert_config = self._pull_disk_alert_from_ui()
        self._refresh_disk_usage_view()

    def _make_stream_redis(self) -> redis.Redis:
        redis_cfg = self.bootstrap.get("redis", {})
        return redis.StrictRedis(
            host=str(redis_cfg.get("host", "localhost")),
            port=int(redis_cfg.get("port", 6379)),
            db=int(redis_cfg.get("db", 0)),
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        )

    def _build_runtime_config(self) -> dict:
        config = copy.deepcopy(self.applied_config)
        config["redis"] = copy.deepcopy(self.bootstrap.get("redis", {}))
        config.setdefault("agent", {})
        config["agent"]["ip"] = str(self.bootstrap.get("agent_ip", detect_private_ipv4()))
        config["agent"]["name"] = str(self.bootstrap.get("agent_name", socket.gethostname()))
        config["agent"]["role"] = "sub"
        config.setdefault("ui", {})
        config["ui"]["mode"] = "plain"
        config.setdefault("debug_tuning", {})
        config["debug_tuning"]["STATUS_PRINT_EVERY_SEC"] = 1.0
        config["debug_tuning"]["LOG_PORT_STATE"] = True
        return config

    def _write_runtime_config(self) -> Path:
        runtime_config = self._build_runtime_config()
        write_json_file(RUNTIME_CONFIG_PATH, runtime_config)
        return RUNTIME_CONFIG_PATH

    def save_settings(self) -> bool:
        try:
            self.bootstrap = self._pull_bootstrap_from_ui()
        except Exception as exc:
            QMessageBox.critical(self, "设置无效", str(exc))
            return False
        self.sound_enabled = self.sound_checkbox.isChecked()
        self.auto_start = self.auto_start_checkbox.isChecked()
        self.disk_alert_config = self._pull_disk_alert_from_ui()
        self._refresh_disk_usage_view()
        write_json_file(CONFIG_JSON_PATH, self.applied_config)
        self.store.save(
            bootstrap=self.bootstrap,
            applied_config=self.applied_config,
            disk_alert=self.disk_alert_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            applied_at=self.applied_at,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        self._append_log(f"[ui] bootstrap settings saved to sqlite and {CONFIG_JSON_PATH}", level="INFO", category="ui")
        return True

    def save_and_apply_settings(self) -> None:
        if not self.save_settings():
            return
        self.applied_at = _now_iso()
        self.store.save(
            bootstrap=self.bootstrap,
            applied_config=self.applied_config,
            disk_alert=self.disk_alert_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            applied_at=self.applied_at,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        if self._proc is not None and self._proc.poll() is None:
            self._append_log("[ui] saved settings, restarting local sy_agent", level="INFO", category="ui")
            self.stop_agent()
            QTimer.singleShot(900, self.start_agent)
            return
        self._append_log("[ui] saved settings, starting local sy_agent", level="INFO", category="ui")
        self.start_agent()

    def import_from_json_file(self) -> None:
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 JSON 配置",
            str(CONFIG_JSON_PATH.parent),
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not source_path:
            return
        try:
            imported = normalize_config(_load_json_config(Path(source_path)), self.template_config)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        self.applied_config = copy.deepcopy(imported)
        write_json_file(CONFIG_JSON_PATH, self.applied_config)
        self.store.save(
            bootstrap=self.bootstrap,
            applied_config=self.applied_config,
            disk_alert=self.disk_alert_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            applied_at=self.applied_at,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        self._reset_runtime_state()
        self._append_log(f"[ui] imported json config: {source_path}", level="INFO", category="ui")
        QMessageBox.information(self, "导入成功", f"已导入并保存到本地：\n{source_path}")

    def import_from_py_file(self) -> None:
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 Python 配置(开发)",
            str(BASE_DIR),
            "Python 文件 (*.py);;所有文件 (*)",
        )
        if not source_path:
            return
        try:
            imported = normalize_config(_load_py_config(Path(source_path)), self.template_config)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        self.applied_config = copy.deepcopy(imported)
        write_json_file(CONFIG_JSON_PATH, self.applied_config)
        self.store.save(
            bootstrap=self.bootstrap,
            applied_config=self.applied_config,
            disk_alert=self.disk_alert_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            applied_at=self.applied_at,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        self._reset_runtime_state()
        self._append_log(f"[ui] imported python config for development: {source_path}", level="INFO", category="ui")
        QMessageBox.information(self, "导入成功", f"已导入并保存到本地：\n{source_path}")

    def export_to_json_config(self) -> None:
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 JSON 配置",
            str(CONFIG_JSON_PATH),
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not target_path:
            return
        try:
            write_json_file(Path(target_path), self.applied_config)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self._append_log(f"[ui] exported json config: {target_path}", level="INFO", category="ui")
        QMessageBox.information(self, "导出成功", f"已导出到：\n{target_path}")

    def export_to_py_config(self) -> None:
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Python 配置(开发)",
            str(CONFIG_PY_PATH),
            "Python 文件 (*.py);;所有文件 (*)",
        )
        if not target_path:
            return
        content = (
            "#!/usr/bin/env python\n"
            "# -*- coding: utf-8 -*-\n\n"
            "CONFIG = "
            + pprint.pformat(self.applied_config, sort_dicts=False, width=100)
            + "\n"
        )
        try:
            Path(target_path).write_text(content, encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self._append_log(f"[ui] exported python config for development: {target_path}", level="INFO", category="ui")
        QMessageBox.information(self, "导出成功", f"已导出到：\n{target_path}")

    def _test_alarm_sound(self) -> None:
        self._alarm_player.set_audio_file(ALARM_WAV_PATH)
        self._alarm_player.set_message("半自动闭塞站间安全传输系统串口故障")
        self._alarm_player.set_active(True)
        QTimer.singleShot(2500, lambda: self._alarm_player.set_active(False))

    def _check_disk_alerts(self) -> None:
        alerts = collect_disk_alerts(self.disk_alert_config)
        if alerts != self._active_disk_alerts:
            self._active_disk_alerts = alerts
            if alerts:
                self.last_alert_text = "；".join(alerts)
            self._update_alarm_state()

    def export_diagnostic_bundle(self) -> None:
        default_name = f"sy_agent_sub_ui_diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        target_path, _ = QFileDialog.getSaveFileName(self, "导出诊断包", str(BASE_DIR / default_name), "ZIP 文件 (*.zip)")
        if not target_path:
            return
        summary = {
            "exported_at": _now_iso(),
            "process_state": self.process_state,
            "redis_state": self.redis_state,
            "alarm_state": self.alarm_state,
            "desired_version": self.desired_version,
            "applied_version": self.applied_version,
            "apply_state": self.apply_state,
            "applied_at": self.applied_at,
            "sound_enabled": self.sound_enabled,
            "auto_start": self.auto_start,
            "settings_locked": self._settings_locked,
            "bootstrap": self.bootstrap,
            "line_status": self._line_status,
        }
        try:
            with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
                zf.writestr("bootstrap.json", json.dumps(self.bootstrap, ensure_ascii=False, indent=2))
                zf.writestr("applied_config.json", json.dumps(self.applied_config, ensure_ascii=False, indent=2))
                zf.writestr("recent_logs.txt", _plain_log_lines(self._log_lines))
                if DB_PATH.exists():
                    zf.write(DB_PATH, arcname=DB_PATH.name)
                if RUNTIME_CONFIG_PATH.exists():
                    zf.write(RUNTIME_CONFIG_PATH, arcname=RUNTIME_CONFIG_PATH.name)
                if CONFIG_JSON_PATH.exists():
                    zf.write(CONFIG_JSON_PATH, arcname=CONFIG_JSON_PATH.name)
            self._append_log(f"[ui] exported diagnostic bundle: {target_path}", level="INFO", category="ui")
            QMessageBox.information(self, "导出成功", f"已导出诊断包：\n{target_path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _update_static_labels(self) -> None:
        self.sound_checkbox.setChecked(self.sound_enabled)
        self.auto_start_checkbox.setChecked(self.auto_start)
        _apply_status_style(self.process_value, self.process_state)
        redis_raw = str(self.redis_state).strip().lower()
        if redis_raw in ("正常", "normal", "ok"):
            _apply_status_style(self.redis_value, "正常", kind="good")
        elif _redis_alarm_active(self.redis_state) or redis_raw in ("", "-", "未知", "unknown"):
            _apply_status_style(self.redis_value, "断开", kind="bad")
        else:
            _apply_status_style(self.redis_value, "断开", kind="bad")
        self.version_value.setText(f"{self.desired_version} / {self.applied_version}")
        _apply_status_style(self.apply_value, self.apply_state)
        self.applied_at_value.setText(self.applied_at)
        self.last_alert_value.setText(self.last_alert_text)
        self.last_alert_value.setStyleSheet("")
        self.lock_button.setText("解锁" if self._settings_locked else "锁定")
        self.pause_alarm_button.setEnabled((bool(self._active_port_alerts) or _redis_alarm_active(self.redis_state) or bool(self._active_disk_alerts)) and self.sound_enabled)
        self.primary_button.setText("停止" if self.process_state == "运行中" else ("停止中…" if self.process_state == "停止中" else "启动"))
        self.primary_button.setEnabled(self.process_state != "停止中")
        self._apply_settings_lock_state()

    def _rebuild_settings_lock_targets(self) -> None:
        self._settings_lock_targets = [
            self.primary_button,
            self.save_button,
            self.import_button,
            self.export_button,
            self.import_py_button,
            self.export_py_button,
            self.export_diag_button,
            self.redis_host_edit,
            self.redis_port_edit,
            self.redis_db_edit,
            self.agent_ip_edit,
            self.agent_name_edit,
            self.auto_start_checkbox,
            self.disk_c_checkbox,
            self.disk_d_checkbox,
            self.disk_threshold_combo,
        ]

    def _apply_settings_lock_state(self) -> None:
        for widget in self._settings_lock_targets:
            if self._settings_locked:
                if widget.property("_enabled_before_settings_lock") is None:
                    widget.setProperty("_enabled_before_settings_lock", widget.isEnabled())
                widget.setEnabled(False)
            else:
                prev_enabled = widget.property("_enabled_before_settings_lock")
                if prev_enabled is not None:
                    widget.setEnabled(bool(prev_enabled))
                widget.setProperty("_enabled_before_settings_lock", None)
        self.lock_button.setEnabled(True)

    def _toggle_settings_lock(self) -> None:
        if not self._settings_locked:
            self._settings_locked = True
            self._apply_settings_lock_state()
            self._update_static_labels()
            self.save_settings()
            self._append_log("[ui] settings locked", level="INFO", category="ui")
            return

        password, ok = QInputDialog.getText(self, "解锁设置", "请输入解锁密码：", QLineEdit.Password)
        if not ok:
            return
        if password != SETTINGS_LOCK_PASSWORD:
            QMessageBox.warning(self, "解锁失败", "密码错误，设置保持锁定。")
            return
        self._settings_locked = False
        self._apply_settings_lock_state()
        self._update_static_labels()
        self.save_settings()
        self._append_log("[ui] settings unlocked", level="INFO", category="ui")

    def _append_log(self, line: str, *, level: str = "INFO", category: str = "general") -> None:
        color = LOG_COLORS.get(category.lower(), LOG_COLORS.get(level.upper(), "#1f2937"))
        self._log_lines.append(f'<span style="color:{color}">{line}</span>')
        self._log_dirty = True

    def _flush_log_view(self) -> None:
        if not self._log_dirty:
            return
        self.log_text.setHtml(
            "<div style=\"font-family: Menlo, monospace; white-space: pre;\">"
            + "<br/>".join(self._log_lines)
            + "</div>"
        )
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
        self._log_dirty = False

    def _reset_runtime_state(self) -> None:
        self._line_status = {}
        self._agent_dashboard_text_cache = ""
        for line in self.applied_config.get("lines", []):
            line_id = int(line["line_id"])
            self._line_status[line_id] = _new_line_runtime_state(line_id, str(line["name"]), devices=len(line.get("devices", [])))
        self._active_port_alerts.clear()
        self._recent_runtime_events.clear()
        self.last_alert_text = "-"
        self._refresh_overview()
        self._update_alarm_state()

    def _record_resp_ok(self, payload: dict[str, Any]) -> None:
        line_id = payload.get("line_id")
        if line_id is None:
            return
        state = self._line_status.setdefault(
            int(line_id),
            _new_line_runtime_state(int(line_id), payload.get("line_name") or f"Line-{line_id}"),
        )
        state["last_ok_mono"] = float(payload.get("nowt", time.monotonic()))
        state["last_ok"] = _age_text(state["last_ok_mono"], time.monotonic())

    def _parse_runtime_log(self, line: str) -> None:
        match = LOG_RE.match(line.strip())
        if not match:
            return
        category = str(match.group("category") or "general").lower()
        line_id = int(match.group("line_id")) if match.group("line_id") else None
        line_name = match.group("line_name") or ""
        port = str(match.group("port") or "").lower()
        message = match.group("message") or ""
        nowt = time.monotonic()

        dashboard_text = _parse_dashboard_payload(message)
        if dashboard_text is not None:
            self._agent_dashboard_text_cache = dashboard_text
            self._refresh_overview()
            return

        status_payload = _parse_status_payload(message)
        if category == "redis" or "[Redis]" in message or status_payload is not None:
            if status_payload:
                self.redis_state = str(status_payload.get("redis", self.redis_state)).lower()
                if line_id is not None:
                    state = self._line_status.setdefault(line_id, _new_line_runtime_state(line_id, line_name or f"Line-{line_id}"))
                    head_port, tail_port = _split_pair_text(status_payload.get("port"), "unknown")
                    state["head_port"] = head_port.lower()
                    state["tail_port"] = tail_port.lower()
                    state["port"] = f"{state['head_port']}/{state['tail_port']}"
                    state["preferred"] = str(status_payload.get("preferred", state["preferred"]))
                    state["link_pair"] = str(status_payload.get("link", state["link_pair"]))
                    state["link"] = _summarize_link_pair(state["link_pair"], state["link"])
                    state["down_for"] = str(status_payload.get("down_for", state["down_for"]))
                    state["devices"] = int(status_payload.get("devices", state["devices"]))
                    state["a1_timeout"] = str(status_payload.get("a1_timeout", state["a1_timeout"]))
                    state["a2_timeout"] = str(status_payload.get("a2_timeout", state["a2_timeout"]))
                    state["cmd_timeout"] = str(status_payload.get("cmd_timeout", state["cmd_timeout"]))
                    state["unmatched"] = str(status_payload.get("unmatched", state["unmatched"]))
                    state["qfull"] = str(status_payload.get("qfull", state["qfull"]))
                    state["queue"] = str(status_payload.get("queue", state["queue"]))
                    state["last_ok"] = str(status_payload.get("last_ok", state["last_ok"]))
                    if state["last_ok"] != "-":
                        state["last_ok_mono"] = nowt
            elif STATUS_RE.search(message):
                status_match = STATUS_RE.search(message)
                self.redis_state = status_match.group(1).lower()
                if line_id is not None:
                    state = self._line_status.setdefault(line_id, _new_line_runtime_state(line_id, line_name or f"Line-{line_id}"))
                    state["head_port"] = status_match.group(2).lower()
                    state["tail_port"] = status_match.group(3).lower()
            elif "down" in message.lower():
                self.redis_state = "断开"
            elif "connected" in message.lower() or "ready" in message.lower():
                self.redis_state = "正常"

        if line_id is not None:
            state = self._line_status.setdefault(line_id, _new_line_runtime_state(line_id, line_name or f"Line-{line_id}"))
            open_match = OPEN_RE.search(message)
            if open_match:
                which = open_match.group(1).lower()
                state[f"{which}_port"] = "open"
                self._active_port_alerts.pop((line_id, which), None)
            else:
                fail_match = PORT_FAIL_RE.search(message)
                if fail_match:
                    which = fail_match.group(1).lower()
                    state[f"{which}_port"] = "down"
                    self._active_port_alerts[(line_id, which)] = message
                    self.last_alert_text = f"line={line_id} {which}: {message}"
                elif "[PORT]" in message and port in ("head", "tail"):
                    if "opened" in message.lower():
                        state[f"{port}_port"] = "open"
                        self._active_port_alerts.pop((line_id, port), None)
                    elif any(token in message.lower() for token in ("reopen", "failed", "fatal", "stall", "write error")):
                        state[f"{port}_port"] = "down"
                        self._active_port_alerts[(line_id, port)] = message
                        self.last_alert_text = f"line={line_id} {port}: {message}"

            if RESP_OK_RE.search(message):
                state["last_ok_mono"] = nowt
                state["last_ok"] = _age_text(state["last_ok_mono"], nowt)
            active_alerts = [msg for (lid, _which), msg in self._active_port_alerts.items() if lid == line_id]
            state["alert"] = active_alerts[-1] if active_alerts else "-"
        if "[STATUS]" not in message and not RESP_OK_RE.search(message):
            self._recent_runtime_events.append(line.strip())

    def _refresh_runtime_summary(self) -> None:
        for state in self._line_status.values():
            pair_summary = _summarize_link_pair(state.get("link_pair", state.get("link", "unknown")), state.get("link", "unknown"))
            state["link"] = "unknown" if pair_summary in ("unknown", "-", "") else pair_summary
        self._refresh_overview()
        self._update_alarm_state()
        self._update_static_labels()

    def _refresh_overview(self) -> None:
        rows = sorted(self._line_status.items())
        self.overview_table.setRowCount(len(rows))
        nowt = time.monotonic()
        for row_idx, (line_id, state) in enumerate(rows):
            values = [
                str(line_id),
                str(state.get("name", f"Line-{line_id}")),
                str(state.get("head_port", "unknown")),
                str(state.get("tail_port", "unknown")),
                str(state.get("link", "unknown")),
                _age_text(state.get("last_ok_mono", 0.0), nowt),
                str(state.get("alert", "-")),
            ]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col_idx == 4:
                    v = str(value).lower()
                    if v in ("good", "正常"):
                        item.setForeground(Qt.GlobalColor.darkGreen)
                    elif v in ("bad", "down", "异常"):
                        item.setForeground(Qt.GlobalColor.red)
                elif col_idx == 6 and value != "-":
                    item.setForeground(Qt.GlobalColor.red)
                self.overview_table.setItem(row_idx, col_idx, item)
        detail_text = self._agent_dashboard_text_cache or self._build_overview_detail_text(rows, nowt, list(self._recent_runtime_events)[-10:])
        if detail_text != self._overview_detail_text_cache:
            self.overview_detail_text.setPlainText(detail_text)
            self._overview_detail_text_cache = detail_text

    def _build_overview_detail_text(
        self,
        rows: list[tuple[int, dict[str, Any]]],
        nowt: float,
        detail_events: list[str],
    ) -> str:
        headers = [
            ("ID", 4),
            ("Name", 12),
            ("Pref(H/T)", 10),
            ("Port(H/T)", 14),
            ("通信状态(H/T)", 14),
            ("DownFor(H/T)", 14),
            ("Devs", 6),
            ("A1超时(T/5m)", 14),
            ("A2超时(T/5m)", 14),
            ("命令超时(T/5m)", 16),
            ("Unmatch(T/5m)", 14),
            ("QFull(H/T)", 12),
            ("Queue(H/T)", 12),
            ("LastOK", 10),
        ]
        lines = []
        header_line = " ".join(title.ljust(width) for title, width in headers)
        lines.append(header_line)
        lines.append("-" * len(header_line))
        for line_id, state in rows:
            values = [
                str(line_id),
                str(state.get("name", f"Line-{line_id}")),
                str(state.get("preferred", "-")),
                str(state.get("port", f"{state.get('head_port', 'unknown')}/{state.get('tail_port', 'unknown')}")),
                str(state.get("link_pair", state.get("link", "unknown"))),
                str(state.get("down_for", "-/-")),
                str(state.get("devices", 0)),
                str(state.get("a1_timeout", "0/0")),
                str(state.get("a2_timeout", "0/0")),
                str(state.get("cmd_timeout", "0/0")),
                str(state.get("unmatched", "0/0")),
                str(state.get("qfull", "0/0")),
                str(state.get("queue", "0/0")),
                str(state.get("last_ok", _age_text(state.get("last_ok_mono", 0.0), nowt))),
            ]
            lines.append(" ".join(value[:width].ljust(width) for value, (_t, width) in zip(values, headers)))
        if detail_events:
            lines.append("")
            lines.append("Recent events")
            lines.append("-" * 80)
            lines.extend(detail_events)
        return "\n".join(lines)

    def _build_alarm_speech_text(self) -> str:
        if self._active_port_alerts:
            return "半自动闭塞站间安全传输系统串口故障"
        if _redis_alarm_active(self.redis_state):
            return "半自动闭塞站间安全传输系统Redis通信故障"
        if self._active_disk_alerts:
            return "半自动闭塞站间安全传输系统磁盘空间告警"
        return ""

    def _on_sound_toggle(self, checked: bool) -> None:
        self.sound_enabled = bool(checked)
        if not self.sound_enabled:
            self._alarm_paused_until_clear = False
        self._alarm_player.set_enabled(self.sound_enabled)
        self._update_alarm_state()

    def _on_auto_start_toggle(self, checked: bool) -> None:
        self.auto_start = bool(checked)

    def _update_alarm_state(self) -> None:
        port_alarm_active = bool(self._active_port_alerts)
        redis_alarm_active = _redis_alarm_active(self.redis_state)
        disk_alarm_active = bool(self._active_disk_alerts)
        alarm_active = port_alarm_active or redis_alarm_active or disk_alarm_active
        if not alarm_active:
            self._alarm_paused_until_clear = False
        if not self.sound_enabled:
            self.alarm_state = "已静音"
            self._alarm_player.set_message("")
            self._alarm_player.set_audio_file(ALARM_WAV_PATH)
            self._alarm_player.set_active(False)
            return
        if alarm_active and self._alarm_paused_until_clear:
            self.alarm_state = "已暂停"
            self._alarm_player.set_message("")
            self._alarm_player.set_audio_file(ALARM_WAV_PATH)
            self._alarm_player.set_active(False)
            return
        if alarm_active:
            self.alarm_state = "告警中"
            self._alarm_player.set_audio_file(ALARM_WAV_PATH if (port_alarm_active or redis_alarm_active) else DISK_ALARM_WAV_PATH)
            self._alarm_player.set_message(self._build_alarm_speech_text())
            self._alarm_player.set_active(True)
            return
        self.alarm_state = "正常"
        self._alarm_player.set_message("")
        self._alarm_player.set_audio_file(ALARM_WAV_PATH)
        self._alarm_player.set_active(False)

    def _pause_alarm_sound(self) -> None:
        self._alarm_paused_until_clear = True
        self._alarm_player.set_active(False)
        self._update_alarm_state()
        self._update_static_labels()

    def _clear_remote_apply_rollback(self) -> None:
        self._remote_apply_rollback = None
        self._remote_apply_deadline_mono = 0.0

    def _handle_agent_exit(self, code: int) -> None:
        manual_stop = self._manual_stop_requested or self.process_state == "停止中"
        self._proc = None
        self._reader_thread = None
        self._drop_runtime_lines = False
        self._manual_stop_requested = False

        rollback_pending = self._remote_apply_rollback is not None and time.monotonic() <= self._remote_apply_deadline_mono
        if rollback_pending and not manual_stop:
            self.process_state = f"异常退出 ({code})"
            self._append_log(f"[ui] remote config failed to stay up, rolling back: exit={code}", level="ERROR", category="ui")
            self._rollback_remote_config(f"exit={code}")
            self._update_static_labels()
            return

        if manual_stop:
            self.process_state = f"已停止 ({code})"
            self._append_log(f"[ui] sy_agent exited with code {code}", level="WARN", category="ui")
            self._update_static_labels()
            return

        self.process_state = f"异常退出 ({code})"
        self._append_log(f"[ui] sy_agent exited unexpectedly with code {code}", level="ERROR", category="ui")
        self._update_static_labels()
        if not self._unexpected_restart_pending:
            self._unexpected_restart_pending = True
            QTimer.singleShot(UNEXPECTED_RESTART_DELAY_MS, self._restart_after_unexpected_exit)

    def _restart_after_unexpected_exit(self) -> None:
        self._unexpected_restart_pending = False
        if self._proc is not None and self._proc.poll() is None:
            return
        self._append_log("[ui] restarting sy_agent after unexpected exit", level="WARN", category="ui")
        self.start_agent()

    def _rollback_remote_config(self, reason: str) -> None:
        ctx = self._remote_apply_rollback
        if ctx is None:
            return
        self.applied_config = copy.deepcopy(ctx["config"])
        self.disk_alert_config = normalize_disk_alert_config(ctx.get("disk_alert"))
        self._load_bootstrap_into_ui()
        self.applied_version = str(ctx["version"])
        self.apply_state = f"rollback: {reason}"
        self.applied_at = _now_iso()
        self.store.save(
            bootstrap=self.bootstrap,
            applied_config=self.applied_config,
            disk_alert=self.disk_alert_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            applied_at=self.applied_at,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        try:
            client = self._make_stream_redis()
            client.set(
                applied_meta_key(str(self.bootstrap.get("agent_ip", ""))),
                json.dumps(
                    {
                        "config_version": ctx["target_version"],
                        "applied_at": self.applied_at,
                        "state": "rolled_back",
                        "error": reason,
                        "restored_version": ctx["version"],
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception:
            pass
        self._clear_remote_apply_rollback()
        self._reset_runtime_state()
        self.start_agent()

    def _on_primary_button(self) -> None:
        if self.process_state == "运行中":
            self.stop_agent()
            return
        if self.process_state != "停止中":
            self.start_agent()

    def start_agent(self) -> None:
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
            launch_cmd, launch_cwd = resolve_launch_command("sy_agent", SY_AGENT_PATH)
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
            QMessageBox.critical(self, "启动失败", str(exc))
            self._proc = None
            if self._remote_apply_rollback is not None:
                self._rollback_remote_config(f"startup failed: {exc}")
            return False
        self._manual_stop_requested = False
        self._unexpected_restart_pending = False
        self._drop_runtime_lines = False
        self.process_state = "运行中"
        self._reset_runtime_state()
        self._append_log(f"[ui] started sy_agent pid={self._proc.pid}", level="INFO", category="ui")
        self._reader_thread = threading.Thread(target=self._read_child_output, daemon=True)
        self._reader_thread.start()
        self._update_static_labels()
        return True

    def _read_child_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self._drop_runtime_lines:
                    continue
                raw = line.rstrip("\n")
                match = LOG_RE.match(raw)
                if match and RESP_OK_RE.search(match.group("message") or ""):
                    self._log_queue.put(("resp_ok", {"line_id": int(match.group("line_id")) if match.group("line_id") else None, "line_name": match.group("line_name") or "", "nowt": time.monotonic()}))
                    continue
                self._log_queue.put(("line", raw))
        finally:
            code = proc.wait()
            self._log_queue.put(("exit", code))

    def stop_agent(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if self._stop_thread is not None and self._stop_thread.is_alive():
            return
        self._manual_stop_requested = True
        self.process_state = "停止中"
        self._drop_runtime_lines = True
        self._update_static_labels()
        self._stop_thread = threading.Thread(target=self._stop_process_worker, args=(proc,), daemon=True)
        self._stop_thread.start()

    def _stop_process_worker(self, proc: subprocess.Popen[str]) -> None:
        try:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2.5)
                return
            except Exception:
                pass
            try:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2.5)
            except Exception:
                pass
        finally:
            self._stop_thread = None

    def _remote_control_loop(self) -> None:
        last_id = "$"
        next_status = 0.0
        while not self._control_stop_evt.is_set():
            try:
                client = self._control_redis_client
                if client is None:
                    client = self._make_stream_redis()
                    client.ping()
                    self._control_redis_client = client
                self._control_queue.put(("redis_state", "正常"))
                nowt = time.monotonic()
                if nowt >= next_status:
                    desired_version = "-"
                    try:
                        raw_meta = client.get(desired_meta_key(str(self.bootstrap.get("agent_ip", ""))))
                        if raw_meta:
                            desired_version = str(json.loads(raw_meta).get("config_version") or "-")
                    except Exception:
                        desired_version = self.desired_version
                    self._control_queue.put(("desired_version", desired_version))
                    self._publish_status(client, desired_version)
                    next_status = nowt + STATUS_REFRESH_SEC

                resp = client.xread({SUBAGENT_CONTROL_STREAM: last_id}, count=10, block=1000)
                if not resp:
                    continue
                for _stream_name, entries in resp:
                    for msg_id, fields in entries:
                        last_id = msg_id
                        raw = fields.get("data")
                        if not raw:
                            continue
                        try:
                            data = json.loads(raw)
                        except Exception:
                            continue
                        target = str(data.get("target_agent_ip") or "").strip()
                        if target and target != str(self.bootstrap.get("agent_ip", "")).strip():
                            continue
                        op = str(data.get("op") or "").strip()
                        if op == "apply_config":
                            self._control_queue.put(("apply_config", str(data.get("config_version") or "-")))
                        elif op == "start_agent":
                            self._control_queue.put(("start_agent", None))
                        elif op == "stop_agent":
                            self._control_queue.put(("stop_agent", None))
                        elif op == "restart_agent":
                            self._control_queue.put(("restart_agent", None))
                        elif op == "get_detail_snapshot":
                            self._publish_detail_snapshot(client)
                        elif op == "ping":
                            self._control_queue.put(("desired_version", str(data.get("config_version") or self.desired_version)))
            except Exception:
                self._control_redis_client = None
                self._control_queue.put(("redis_state", "断开"))
                time.sleep(1.0)

    def _publish_status(self, client: redis.Redis, desired_version: str) -> None:
        payload = {
            "agent_ip": str(self.bootstrap.get("agent_ip", "")),
            "agent_name": str(self.bootstrap.get("agent_name", "")),
            "online": True,
            "last_seen": _now_iso(),
            "desired_version": desired_version,
            "applied_version": self.applied_version,
            "apply_state": self.apply_state,
            "applied_at": self.applied_at,
            "redis_state": self.redis_state,
            "local_agent_state": self.process_state,
            "disk_alert": copy.deepcopy(self.disk_alert_config),
            "disk_usage": collect_disk_usage(self.disk_alert_config),
            "lines_summary": self._current_lines_summary(),
        }
        client.set(status_key(str(self.bootstrap.get("agent_ip", ""))), json.dumps(payload, ensure_ascii=False), ex=STATUS_TTL_SEC)

    def _publish_detail_snapshot(self, client: redis.Redis) -> None:
        payload = {
            "agent_ip": str(self.bootstrap.get("agent_ip", "")),
            "agent_name": str(self.bootstrap.get("agent_name", "")),
            "published_at": _now_iso(),
            "disk_alert": copy.deepcopy(self.disk_alert_config),
            "disk_usage": collect_disk_usage(self.disk_alert_config),
            "lines_summary": self._current_lines_summary(),
            "dashboard_text": self._agent_dashboard_text_cache,
            "recent_events": list(self._recent_runtime_events)[-10:],
        }
        client.set(
            detail_snapshot_key(str(self.bootstrap.get("agent_ip", ""))),
            json.dumps(payload, ensure_ascii=False),
            ex=DETAIL_SNAPSHOT_TTL_SEC,
        )

    def _current_lines_summary(self) -> list[dict[str, Any]]:
        nowt = time.monotonic()
        out = []
        for line_id, state in sorted(self._line_status.items()):
            out.append(
                {
                    "line_id": line_id,
                    "name": str(state.get("name", f"Line-{line_id}")),
                    "preferred": str(state.get("preferred", "-")),
                    "port": str(state.get("port", f"{state.get('head_port', 'unknown')}/{state.get('tail_port', 'unknown')}")),
                    "link": str(state.get("link_pair", state.get("link", "unknown"))),
                    "down_for": str(state.get("down_for", "-/-")),
                    "devices": int(state.get("devices", 0)),
                    "a1_timeout": str(state.get("a1_timeout", "0/0")),
                    "a2_timeout": str(state.get("a2_timeout", "0/0")),
                    "cmd_timeout": str(state.get("cmd_timeout", "0/0")),
                    "unmatched": str(state.get("unmatched", "0/0")),
                    "qfull": str(state.get("qfull", "0/0")),
                    "queue": str(state.get("queue", "0/0")),
                    "last_ok": str(state.get("last_ok", _age_text(state.get("last_ok_mono", 0.0), nowt))),
                    "alert": str(state.get("alert", "-")),
                }
            )
        return out

    def _poll_runtime_queues(self) -> None:
        latest_lines: "deque[str]" = deque(maxlen=8)
        while True:
            try:
                kind, payload = self._log_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                latest_lines.append(str(payload))
                self._parse_runtime_log(payload)
            elif kind == "resp_ok":
                self._record_resp_ok(payload)
            elif kind == "exit":
                self._handle_agent_exit(int(payload))
        for payload in latest_lines:
            self._append_log(payload, level="INFO", category="general")
        while True:
            try:
                kind, payload = self._control_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "redis_state":
                self.redis_state = str(payload)
            elif kind == "desired_version":
                self.desired_version = str(payload or "-")
            elif kind == "apply_config":
                self._apply_remote_config(str(payload or "-"))
            elif kind == "start_agent":
                self._append_log("[ui] remote start requested", level="INFO", category="ui")
                if self._proc is None or self._proc.poll() is not None:
                    self.start_agent()
            elif kind == "stop_agent":
                self._append_log("[ui] remote stop requested", level="WARN", category="ui")
                if self._proc is not None and self._proc.poll() is None:
                    self.stop_agent()
            elif kind == "restart_agent":
                self._append_log("[ui] remote restart requested", level="WARN", category="ui")
                self.stop_agent()
                QTimer.singleShot(800, self.start_agent)
        self._refresh_overview()
        self._update_alarm_state()
        if self._remote_apply_rollback is not None and self._proc is not None and self._proc.poll() is None:
            if time.monotonic() > self._remote_apply_deadline_mono:
                self._clear_remote_apply_rollback()
        self._update_static_labels()

    def _apply_remote_config(self, version: str) -> None:
        try:
            client = self._make_stream_redis()
            raw = client.get(desired_config_key(str(self.bootstrap.get("agent_ip", ""))))
            meta_raw = client.get(desired_meta_key(str(self.bootstrap.get("agent_ip", ""))))
            if not raw:
                raise RuntimeError("missing desired_config")
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "config" in parsed:
                config = normalize_config(parsed.get("config"), self.template_config)
                disk_alert = normalize_disk_alert_config(parsed.get("disk_alert"))
            else:
                config = normalize_config(parsed, self.template_config)
                disk_alert = self.disk_alert_config
            meta = json.loads(meta_raw) if meta_raw else {}
            config_version = str(meta.get("config_version") or version or "-")
            previous_config = copy.deepcopy(self.applied_config)
            previous_disk_alert = copy.deepcopy(self.disk_alert_config)
            previous_version = self.applied_version or "-"
            self._remote_apply_rollback = {
                "config": previous_config,
                "disk_alert": previous_disk_alert,
                "version": previous_version,
                "target_version": config_version,
            }
            self._remote_apply_deadline_mono = time.monotonic() + REMOTE_APPLY_ROLLBACK_GRACE_SEC
            self.applied_config = config
            self.disk_alert_config = normalize_disk_alert_config(disk_alert)
            self._load_bootstrap_into_ui()
            self.applied_version = config_version
            self.apply_state = "ok"
            self.applied_at = _now_iso()
            self.store.save(
                bootstrap=self.bootstrap,
                applied_config=self.applied_config,
                disk_alert=self.disk_alert_config,
                sound_enabled=self.sound_enabled,
                auto_start=self.auto_start,
                settings_locked=self._settings_locked,
                applied_at=self.applied_at,
                window_geometry=_encode_geometry(self.saveGeometry()),
            )
            client.set(
                applied_meta_key(str(self.bootstrap.get("agent_ip", ""))),
                json.dumps({"config_version": config_version, "applied_at": self.applied_at, "state": "ok"}, ensure_ascii=False),
            )
            self._append_log(f"[ui] applied remote config version={config_version}", level="INFO", category="ui")
            self._reset_runtime_state()
            if self._proc is not None and self._proc.poll() is None:
                self.stop_agent()
                QTimer.singleShot(1000, self.start_agent)
            else:
                self.start_agent()
        except Exception as exc:
            self.apply_state = f"failed: {exc}"
            self._clear_remote_apply_rollback()
            try:
                client = self._make_stream_redis()
                client.set(
                    applied_meta_key(str(self.bootstrap.get("agent_ip", ""))),
                    json.dumps({"config_version": version, "applied_at": _now_iso(), "state": "failed", "error": str(exc)}, ensure_ascii=False),
                )
            except Exception:
                pass
            self._append_log(f"[ui] apply remote config failed: {exc}", level="ERROR", category="ui")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._settings_locked:
            event.ignore()
            self._append_log("[ui] close ignored because settings are locked", level="INFO", category="ui")
            return
        try:
            self.save_settings()
        except Exception:
            pass
        self._control_stop_evt.set()
        self._unexpected_restart_pending = False
        self.stop_agent()
        if self._stop_thread is not None:
            self._stop_thread.join(timeout=6.0)
        if self._control_thread is not None:
            self._control_thread.join(timeout=2.0)
        self._alarm_player.stop()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    lock, error = acquire_single_instance_lock(lock_path("sy_agent", "sy_agent_sub_ui.lock"), "SY串口通信分机程序")
    if error:
        QMessageBox.warning(None, "无法启动", error)
        return 1
    window = SyUISubAgentWindow()
    window._single_instance_lock = lock
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
