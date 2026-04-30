#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import html
import importlib.util
import json
import os
import pprint
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import signal
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import redis
from PySide6.QtCore import QByteArray, QLockFile, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QCloseEvent, QFont, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QInputDialog,
    QFormLayout,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QSizePolicy,
    QToolButton,
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

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows runtime
    winsound = None


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
CURRENT_APP_DIR = Path(sys.argv[0]).resolve().parent
CONFIG_PY_PATH = BASE_DIR / "config.py"
CONFIG_JSON_PATH = agent_config_path("sy_agent")
DB_PATH = sqlite_path("sy_agent", "sy_agent_ui.sqlite3")
RUNTIME_CONFIG_PATH = runtime_config_path("sy_agent", "runtime_config.json")
SY_AGENT_PATH = BASE_DIR / "sy_agent.py"
CONFIG_JSON_ENV = "SY_AGENT_CONFIG_JSON"
MACOS_ALERT_SOUND = "/System/Library/Sounds/Glass.aiff"
ALARM_REPEAT_SEC = 3.0
MACOS_SAY_RATE = "185"
WINDOWS_TTS_RATE = "0"
MACOS_TTS_VOICE = "Flo (中文（中国大陆）)"
SETTINGS_LOCK_PASSWORD = "whbt"
EDITOR_PANEL_MIN_HEIGHT = 360
OVERVIEW_PANEL_MIN_HEIGHT = 210
UNEXPECTED_RESTART_DELAY_MS = 3000
REMOTE_APPLY_ROLLBACK_GRACE_SEC = 20.0
REMOTE_DETAIL_REQUEST_SEC = 3.0
DISK_CHECK_SEC = 30.0
DISK_THRESHOLD_OPTIONS = [5, 10, 15, 20, 25, 30]

STATUS_LABEL_STYLES = {
    "good": "color: #166534; background: #dcfce7; border: 1px solid #86efac; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
    "bad": "color: #991b1b; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
    "warn": "color: #92400e; background: #fef3c7; border: 1px solid #fcd34d; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
    "neutral": "color: #374151; background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
}
FORM_TAB_GROUPS = [
    ("基础参数", ["redis", "stream", "cmd"]),
    ("轮询串口", ["time_sync", "a2_burst", "serial", "probe", "ui"]),
    ("调试参数", ["debug_tuning"]),
]
SECTION_TITLES = {
    "redis": "Redis",
    "stream": "Stream",
    "cmd": "命令",
    "time_sync": "时间同步",
    "a2_burst": "A2 突发",
    "serial": "串口默认",
    "probe": "探测",
    "ui": "终端界面",
    "debug_tuning": "调试参数",
}
UI_TEMPLATE_BASE = {
    "agent": {
        "ip": "",
        "name": "",
        "role": "main",
    },
    "redis": {
        "host": "localhost",
        "port": 36380,
        "db": 0,
    },
    "stream": {
        "raw_stream": "sy.raw",
        "raw_stream_maxlen": 200000,
        "cmd_stream": "sy-serial-commands",
        "cmd_group": "sy_agent_cmd_group",
        "cmd_consumer": "sy-agent-1",
        "cmd_block_ms": 1000,
        "cmd_count": 10,
    },
    "cmd": {
        "dlq_stream": "sy-serial-commands.dlq",
        "dlq_maxlen": 50000,
        "done_key_prefix": "sy:cmd_done:",
        "done_ttl_sec": 3600,
        "done_local_ttl_sec": 600,
        "dlq_dedupe_prefix": "sy:cmd_dlq:",
        "dlq_dedupe_ttl_sec": 600,
        "try_key_prefix": "sy:cmd_try:",
        "try_ttl_sec": 3600,
        "max_tries": 20,
        "inflight_ttl_sec": 3.0,
        "no_resp_enable": True,
        "confirm_delay_sec": 0.08,
        "confirm_timeout_sec": 0.25,
        "confirm_a1": True,
        "bb_cmd_retries": 3,
        "no_resp_cmds": ["CC"],
    },
    "time_sync": {
        "enable": False,
        "interval_sec": 3600,
    },
    "a2_burst": {
        "enable": True,
        "max": 3,
        "timeout_sec": 0.06,
        "budget_sec": 0.16,
    },
    "serial": {
        "default_baudrate": 19200,
        "timeout": 0.0,
    },
    "probe": {
        "enable": True,
        "interval_sec": 45.0,
        "timeout_sec": 0.12,
        "queue_threshold": 32,
        "cooldown_after_fault_sec": 15.0,
    },
    "ui": {
        "mode": "dashboard",
        "refresh_sec": 1.0,
        "event_buffer_size": 20,
        "ansi": "auto",
    },
    "debug_tuning": {
        "AFTER_WRITE_SLEEP_SEC": 0.035,
        "ENABLE_AFTER_WRITE_SLEEP": True,
        "WAIT_RESPONSE_TIMEOUT_SEC": 0.20,
        "RX_IDLE_SLEEP_SEC": 0.002,
        "AUTO_SLEEP_ENABLE": True,
        "AUTO_SLEEP_WINDOW": 80,
        "AUTO_SLEEP_PCTL": 95,
        "AUTO_SLEEP_MARGIN_SEC": 0.005,
        "AUTO_SLEEP_MIN_SEC": 0.010,
        "AUTO_SLEEP_MAX_SEC": 0.080,
        "AUTO_SLEEP_UPDATE_EVERY": 8,
        "AUTO_SLEEP_PRINT_EVERY_SEC": 5.0,
        "AUTO_SLEEP_NO_RESP_BUMP_SEC": 0.005,
        "AUTO_SLEEP_NO_RESP_STREAK": 2,
        "AUTO_SLEEP_NO_RESP_COOLDOWN_SEC": 0.8,
        "AUTO_SLEEP_DECAY_OK_STREAK": 40,
        "AUTO_SLEEP_DECAY_STEP_SEC": 0.002,
        "RTS_TOGGLE": False,
        "RTS_TX_LEVEL": 1,
        "RTS_RX_LEVEL": 0,
        "RTS_PRE_DELAY_SEC": 0.001,
        "RTS_POST_DELAY_SEC": 0.002,
        "REDIS_RETRY_MIN_SEC": 1.0,
        "REDIS_RETRY_MAX_SEC": 10.0,
        "REDIS_DOWN_PAUSE_SEC": 0.5,
        "SERIAL_RETRY_MIN_SEC": 1.0,
        "SERIAL_RETRY_MAX_SEC": 30.0,
        "SERIAL_RX_ERROR_LIMIT": 5,
        "RX_THREAD_DEAD_REOPEN": True,
        "STALL_WATCHDOG_ENABLE": True,
        "STALL_NOFRAME_SEC": 15.0,
        "STALL_GRACE_AFTER_OPEN_SEC": 2.0,
        "STALL_COOLDOWN_SEC": 15.0,
        "LOG_SEND": False,
        "LOG_RECV_OK": False,
        "LOG_NO_RESP": True,
        "LOG_RX_STATS": True,
        "LOG_MATCH_DETAIL": False,
        "LOG_REDIS_STATE": True,
        "LOG_PORT_STATE": True,
        "STATUS_PRINT_EVERY_SEC": 10.0,
        "MAX_READ_ONCE": 4096,
        "MAX_SOFTBUF": 8192,
        "PENDING_RETRY_ENABLE": True,
        "PENDING_MIN_IDLE_MS": 5000,
        "PENDING_CLAIM_EVERY_SEC": 2.0,
        "PENDING_CLAIM_COUNT": 20,
    },
    "lines": [],
}

LOG_RE = re.compile(
    r"^(?P<ts>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"\[(?P<category>[^\]]+)\]"
    r"(?:\s+line=(?P<line_id>\d+)(?:/(?P<line_name>[^\s]+))?)?"
    r"(?:\s+port=(?P<port>[^\s]+))?\s+"
    r"(?P<message>.*)$"
)
STATUS_RE = re.compile(r"redis=(UP|DOWN).*ports\(head/tail\)=([A-Za-z]+)/([A-Za-z]+)")
OPEN_RE = re.compile(r"\[PORT\]\s+(HEAD|TAIL|head|tail)\s+opened:")
PORT_FAIL_RE = re.compile(
    r"\[PORT\]\s+(HEAD|TAIL|head|tail)\s+"
    r"(open failed|schedule reopen|RX fatal|STALL|write error|RX thread dead)"
)
RESP_OK_RE = re.compile(r"recv\((head|tail)\)\s+RESP_OK")

LOG_COLORS = {
    "INFO": "#1f2937",
    "WARN": "#b45309",
    "ERROR": "#b91c1c",
    "port": "#7c3aed",
    "redis": "#2563eb",
    "cmd": "#0f766e",
    "dlq": "#be123c",
    "ui": "#4b5563",
}
SUBAGENT_STATUS_PATTERN = "sy:subagent:*:status"
SUBAGENT_CONTROL_STREAM = "sy-subagent-control"
NMS_ROUTE_KEY_PREFIX = "sy:route:nms:"
LOCAL_AGENT_KEY = "__local__"


def _first_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


ASSETS_DIR = _first_existing_path(
    BASE_DIR / "assets",
    CURRENT_APP_DIR / "assets",
    CURRENT_APP_DIR / "sy_agent" / "assets",
)
ALARM_WAV_PATH = _first_existing_path(
    ASSETS_DIR / "serial_fault_alarm.wav",
    CURRENT_APP_DIR / "serial_fault_alarm.wav",
)
DISK_ALARM_WAV_PATH = _first_existing_path(
    ASSETS_DIR / "disk_space_alarm.wav",
    CURRENT_APP_DIR / "disk_space_alarm.wav",
)


def desired_config_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:desired_config"


def desired_meta_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:desired_meta"


def applied_meta_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:applied_meta"


def status_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:status"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_py_config(path: Path) -> dict:
    spec = importlib.util.spec_from_file_location("sy_agent_ui_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load config module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = getattr(module, "CONFIG", None)
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must define CONFIG = {{...}}")
    return loaded


def _load_json_config(path: Path) -> dict:
    loaded = load_json_file(path)
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return loaded


def _age_text(last_mono: Optional[float], nowt: Optional[float] = None) -> str:
    if not last_mono or last_mono <= 0:
        return "-"
    nowt = time.monotonic() if nowt is None else float(nowt)
    delta = max(0.0, nowt - float(last_mono))
    if delta < 60:
        return f"{delta:.1f}s"
    if delta < 3600:
        return f"{delta / 60:.1f}m"
    return f"{delta / 3600:.1f}h"


def _normalize_device(device: dict) -> dict:
    if not isinstance(device, dict):
        raise ValueError("device item must be an object")
    return {
        "serial_id": int(device["serial_id"]),
        "nms_id": int(device.get("nms_id", device["serial_id"])),
        "a1_interval": float(device.get("a1_interval", 5.0)),
    }


def _normalize_line(line: dict) -> dict:
    if not isinstance(line, dict):
        raise ValueError("line item must be an object")
    if "line_id" not in line:
        raise ValueError("line_id is required")
    devices = line.get("devices")
    if not isinstance(devices, list):
        raise ValueError(f"line {line.get('line_id')} devices must be a list")
    return {
        "line_id": int(line["line_id"]),
        "name": str(line.get("name", f"Line-{int(line['line_id'])}")).strip() or f"Line-{int(line['line_id'])}",
        "head_port": str(line.get("head_port", "NONE")).strip() or "NONE",
        "tail_port": str(line.get("tail_port", "NONE")).strip() or "NONE",
        "ring_mode": bool(line.get("ring_mode", False)),
        "baudrate": int(line.get("baudrate", 19200)),
        "timeout": float(line.get("timeout", 0.0)),
        "devices": [_normalize_device(item) for item in devices],
    }


def normalize_config(raw_config: dict, template_config: dict) -> dict:
    if not isinstance(raw_config, dict):
        raise ValueError("config must be a JSON object")

    config = copy.deepcopy(template_config)
    _deep_merge(config, copy.deepcopy(raw_config))

    if "lines" not in config or not isinstance(config["lines"], list):
        raise ValueError("config.lines must be a list")
    config["lines"] = [_normalize_line(item) for item in config["lines"]]

    for key in ("redis", "stream", "cmd", "time_sync", "a2_burst", "serial", "probe", "ui", "debug_tuning"):
        if key not in config or not isinstance(config[key], dict):
            raise ValueError(f"config.{key} must be an object")

    return config


def build_template_config(raw_config: dict) -> dict:
    return normalize_config(raw_config, UI_TEMPLATE_BASE)


def _encode_geometry(data: QByteArray) -> str:
    return bytes(data.toBase64()).decode("ascii")


def _decode_geometry(text: str) -> QByteArray:
    if not text:
        return QByteArray()
    return QByteArray.fromBase64(text.encode("ascii"))


def _status_kind_from_text(text: str) -> str:
    value = str(text or "").strip().lower()
    if any(token in value for token in ("运行", "在线", "正常", "good", "open", "ok", "local")):
        return "good"
    if any(token in value for token in ("停止中", "告警", "应用中", "applying", "pending", "warn")):
        return "warn"
    if any(token in value for token in ("异常", "失败", "断开", "离线", "bad", "down", "failed", "error", "stopped", "已停止")):
        return "bad"
    return "neutral"


def _apply_status_style(label: QLabel, text: str, kind: Optional[str] = None) -> None:
    label.setText(text)
    label.setStyleSheet(STATUS_LABEL_STYLES.get(kind or _status_kind_from_text(text), STATUS_LABEL_STYLES["neutral"]))


def _plain_log_lines(lines: deque[str]) -> str:
    out: list[str] = []
    for line in lines:
        text = re.sub(r"<[^>]+>", "", line)
        out.append(html.unescape(text))
    return "\n".join(out)


def detail_snapshot_key(agent_ip: str) -> str:
    return f"sy:subagent:{agent_ip}:detail_snapshot"


def default_disk_alert_config() -> dict[str, Any]:
    return {
        "c_enabled": False,
        "d_enabled": False,
        "threshold_percent": 10,
    }


def normalize_disk_alert_config(raw: Any) -> dict[str, Any]:
    cfg = default_disk_alert_config()
    if isinstance(raw, dict):
        cfg["c_enabled"] = bool(raw.get("c_enabled", cfg["c_enabled"]))
        cfg["d_enabled"] = bool(raw.get("d_enabled", cfg["d_enabled"]))
        try:
            threshold = int(raw.get("threshold_percent", cfg["threshold_percent"]))
        except Exception:
            threshold = cfg["threshold_percent"]
        cfg["threshold_percent"] = threshold if threshold in DISK_THRESHOLD_OPTIONS else cfg["threshold_percent"]
    return cfg


def disk_monitor_specs() -> list[dict[str, str]]:
    if os.name == "nt":
        return [
            {"slot": "c", "path": "C:/", "label": "C盘"},
            {"slot": "d", "path": "D:/", "label": "D盘"},
        ]
    if sys.platform == "darwin":
        return [
            {"slot": "c", "path": "/", "label": "系统盘(/)"},
            {"slot": "d", "path": "/Users", "label": "用户盘(/Users)"},
        ]
    return [
        {"slot": "c", "path": "/", "label": "系统盘(/)"},
        {"slot": "d", "path": "/home", "label": "用户盘(/home)"},
    ]


def acquire_single_instance_lock(lock_path: Path, app_name: str) -> tuple[Optional[QLockFile], Optional[str]]:
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(30000)
    if lock.tryLock(100):
        return lock, None
    return None, f"{app_name} 已在运行，请勿重复启动。"


def collect_disk_alerts(config: dict[str, Any]) -> list[str]:
    cfg = normalize_disk_alert_config(config)
    alerts: list[str] = []
    for spec in disk_monitor_specs():
        enabled_key = f"{spec['slot']}_enabled"
        if not cfg.get(enabled_key):
            continue
        path = Path(spec["path"])
        if not path.exists():
            continue
        try:
            usage = shutil.disk_usage(path)
        except Exception:
            continue
        if usage.total <= 0:
            continue
        free_pct = (usage.free / usage.total) * 100.0
        if free_pct <= float(cfg.get("threshold_percent", 10)):
            alerts.append(f"{spec['label']}剩余{free_pct:.1f}%")
    return alerts


def collect_disk_usage(config: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = normalize_disk_alert_config(config)
    out: list[dict[str, Any]] = []
    for spec in disk_monitor_specs():
        enabled_key = f"{spec['slot']}_enabled"
        enabled = bool(cfg.get(enabled_key))
        path = Path(spec["path"])
        item: dict[str, Any] = {
            "slot": spec["slot"],
            "label": spec["label"],
            "path": spec["path"],
            "enabled": enabled,
            "exists": path.exists(),
            "free_pct": None,
            "free_gb": None,
            "total_gb": None,
            "text": "未监控" if not enabled else "不可用",
        }
        if not enabled:
            out.append(item)
            continue
        if not path.exists():
            out.append(item)
            continue
        try:
            usage = shutil.disk_usage(path)
        except Exception:
            out.append(item)
            continue
        if usage.total > 0:
            free_pct = (usage.free / usage.total) * 100.0
            item["free_pct"] = round(free_pct, 1)
            item["free_gb"] = round(usage.free / (1024 ** 3), 1)
            item["total_gb"] = round(usage.total / (1024 ** 3), 1)
            item["text"] = f"剩余{item['free_pct']:.1f}% ({item['free_gb']:.1f}/{item['total_gb']:.1f}GB)"
        out.append(item)
    return out


def _new_line_runtime_state(line_id: int, name: str, devices: int = 0) -> dict[str, Any]:
    return {
        "line_id": int(line_id),
        "name": str(name or f"Line-{line_id}"),
        "preferred": "-",
        "head_port": "unknown",
        "tail_port": "unknown",
        "port": "unknown/unknown",
        "link": "unknown",
        "link_pair": "unknown/unknown",
        "down_for": "-/-",
        "devices": int(devices or 0),
        "a1_timeout": "0/0",
        "a2_timeout": "0/0",
        "cmd_timeout": "0/0",
        "unmatched": "0/0",
        "qfull": "0/0",
        "queue": "0/0",
        "last_ok": "-",
        "last_ok_mono": 0.0,
        "alert": "-",
    }


def _parse_status_payload(message: str) -> Optional[dict[str, Any]]:
    if "[STATUS]" not in message:
        return None
    payload = message.split("[STATUS]", 1)[1].strip()
    if not payload:
        return None
    if payload.startswith("{"):
        try:
            data = json.loads(payload)
        except Exception:
            data = None
        if isinstance(data, dict):
            return data
    status_match = STATUS_RE.search(message)
    if status_match:
        return {
            "redis": status_match.group(1),
            "ports": f"{status_match.group(2)}/{status_match.group(3)}",
        }
    return None


def _split_pair_text(value: Any, default: str = "unknown") -> tuple[str, str]:
    text = str(value or "")
    if "/" in text:
        left, right = text.split("/", 1)
        return left or default, right or default
    return default, default


def _summarize_link_pair(value: Any, fallback: str = "unknown") -> str:
    left, right = _split_pair_text(value, fallback)
    pair = [str(left).lower(), str(right).lower()]
    if any(item == "good" for item in pair):
        return "good"
    if all(item == "dis" for item in pair):
        return "dis"
    if all(item in ("down", "dis") for item in pair):
        return "down"
    if any(item == "bad" for item in pair):
        return "bad"
    return str(fallback)


def _agent_online_label(info: dict[str, Any]) -> str:
    if not bool(info.get("online", False)):
        return "离线"
    local_agent_state = str(info.get("local_agent_state", "")).strip()
    if "运行" in local_agent_state:
        return "在线 已启动"
    if "停止" in local_agent_state:
        return "在线 已停止"
    return "在线"


def _redis_alarm_active(redis_state: Any) -> bool:
    text = str(redis_state or "").strip().lower()
    return text not in ("", "-", "正常", "normal", "ok")


def _format_redis_state_text(redis_state: Any) -> str:
    text = str(redis_state or "").strip().lower()
    if text in ("正常", "normal", "ok"):
        return "Redis连接状态：正常"
    if text in ("断开", "down", "failed", "error", "异常"):
        return "Redis连接状态：断开"
    if text:
        return f"Redis连接状态：{redis_state}"
    return "Redis连接状态：未知"


class ToggleSwitch(QCheckBox):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setText("")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(56, 30)

    def sizeHint(self) -> QSize:
        return QSize(56, 30)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled() and event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled() and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        checked = self.isChecked()
        enabled = self.isEnabled()

        track_color = QColor("#1f8cff" if checked else "#d9deea")
        border_color = QColor("#1f8cff" if checked else "#c7cfdf")
        knob_color = QColor("#ffffff" if enabled else "#f3f4f6")

        painter.setPen(border_color)
        painter.setBrush(track_color)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        knob_d = rect.height() - 4
        knob_y = rect.top() + 2
        knob_x = rect.right() - knob_d - 2 if checked else rect.left() + 2
        painter.setPen(QColor("#d1d5db"))
        painter.setBrush(knob_color)
        painter.drawEllipse(knob_x, knob_y, knob_d, knob_d)
        painter.end()


class AlarmSoundPlayer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop_evt = threading.Event()
        self._wake_evt = threading.Event()
        self._lock = threading.Lock()
        self._enabled = True
        self._active = False
        self._message = ""
        self._audio_file = str(ALARM_WAV_PATH)
        self._proc: Optional[subprocess.Popen[Any]] = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
        if not enabled:
            self._stop_playback()
        self._wake_evt.set()

    def set_active(self, active: bool) -> None:
        with self._lock:
            self._active = bool(active)
        if not active:
            self._stop_playback()
        self._wake_evt.set()

    def set_message(self, message: str) -> None:
        with self._lock:
            self._message = str(message or "").strip()
        self._wake_evt.set()

    def set_audio_file(self, path: Any) -> None:
        with self._lock:
            self._audio_file = str(path) if path else str(ALARM_WAV_PATH)
        self._wake_evt.set()

    def stop(self) -> None:
        self._stop_evt.set()
        self._stop_playback()
        self._wake_evt.set()

    def _snapshot(self) -> tuple[bool, bool, str, str]:
        with self._lock:
            return self._enabled, self._active, self._message, self._audio_file

    def _stop_playback(self) -> None:
        if winsound is not None and sys.platform.startswith("win"):
            try:
                winsound.PlaySound(None, 0)
            except Exception:
                pass
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _play_wav_once(self, audio_file: str) -> bool:
        wav_path = Path(audio_file) if audio_file else ALARM_WAV_PATH
        if not wav_path.exists():
            return False

        if winsound is not None and sys.platform.startswith("win"):
            try:
                winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
                return True
            except Exception:
                return False

        if sys.platform == "darwin":
            try:
                proc = subprocess.Popen(
                    ["/usr/bin/afplay", str(wav_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                return False
            self._proc = proc
            while (not self._stop_evt.is_set()) and proc.poll() is None:
                enabled, active, _message, _audio_file = self._snapshot()
                if not enabled or not active:
                    self._stop_playback()
                    break
                time.sleep(0.1)
            self._proc = None
            return True

        return False

    def _play_once(self, message: str, audio_file: str) -> None:
        if self._play_wav_once(audio_file):
            return

        if winsound is not None and sys.platform.startswith("win") and message:
            try:
                cmd = [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Add-Type -AssemblyName System.Speech; "
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        f"$s.Rate = {WINDOWS_TTS_RATE}; "
                        "$s.Speak([Console]::In.ReadToEnd())"
                    ),
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                self._proc = proc
                try:
                    proc.communicate(message, timeout=20)
                except Exception:
                    self._stop_playback()
                self._proc = None
                return
            except Exception:
                pass

        if sys.platform == "darwin" and message:
            try:
                proc = subprocess.Popen(
                    ["/usr/bin/say", "-v", MACOS_TTS_VOICE, "-r", MACOS_SAY_RATE, message],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                proc = None
            if proc is not None:
                self._proc = proc
                while (not self._stop_evt.is_set()) and proc.poll() is None:
                    enabled, active, current_message, current_audio = self._snapshot()
                    if (not enabled) or (not active) or (current_message != message) or (current_audio != audio_file):
                        self._stop_playback()
                        break
                    time.sleep(0.1)
                self._proc = None
                return

        if sys.platform == "darwin" and os.path.exists(MACOS_ALERT_SOUND):
            try:
                proc = subprocess.Popen(
                    ["/usr/bin/afplay", MACOS_ALERT_SOUND],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                QApplication.beep()
                time.sleep(1.0)
                return
            self._proc = proc
            while (not self._stop_evt.is_set()) and proc.poll() is None:
                enabled, active, _message = self._snapshot()
                if not enabled or not active:
                    self._stop_playback()
                    break
                time.sleep(0.1)
            self._proc = None
            return

        QApplication.beep()
        time.sleep(1.0)

    def run(self) -> None:
        while not self._stop_evt.is_set():
            enabled, active, message, audio_file = self._snapshot()
            if not enabled or not active or not message:
                self._wake_evt.wait(0.2)
                self._wake_evt.clear()
                continue
            self._play_once(message, audio_file)
            enabled, active, current_message, current_audio = self._snapshot()
            if enabled and active and current_message and not self._stop_evt.is_set():
                deadline = time.time() + ALARM_REPEAT_SEC
                while time.time() < deadline and not self._stop_evt.is_set():
                    self._wake_evt.wait(0.2)
                    self._wake_evt.clear()
                    enabled, active, newest_message, newest_audio = self._snapshot()
                    if (not enabled) or (not active) or (newest_message != current_message) or (newest_audio != current_audio):
                        break


class AppStateStore:
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
                    config_json TEXT NOT NULL,
                    disk_alert_json TEXT NOT NULL DEFAULT '{}',
                    sound_enabled INTEGER NOT NULL,
                    auto_start INTEGER NOT NULL,
                    settings_locked INTEGER NOT NULL DEFAULT 0,
                    was_running INTEGER NOT NULL DEFAULT 0,
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
            if "was_running" not in columns:
                conn.execute("ALTER TABLE app_state ADD COLUMN was_running INTEGER NOT NULL DEFAULT 0")
            if "applied_at" not in columns:
                conn.execute("ALTER TABLE app_state ADD COLUMN applied_at TEXT NOT NULL DEFAULT ''")
            conn.commit()

    def load_or_init(self, template_config: dict) -> dict:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM app_state WHERE id = 1").fetchone()
            if row is not None:
                config = normalize_config(json.loads(row["config_json"]), template_config)
                if CONFIG_JSON_PATH.exists():
                    try:
                        config = normalize_config(_load_json_config(CONFIG_JSON_PATH), template_config)
                    except Exception:
                        pass
                return {
                    "config": config,
                    "disk_alert": normalize_disk_alert_config(json.loads(row["disk_alert_json"] or "{}")),
                    "sound_enabled": bool(row["sound_enabled"]),
                    "auto_start": bool(row["auto_start"]),
                    "settings_locked": bool(row["settings_locked"]),
                    "was_running": bool(row["was_running"]),
                    "applied_at": str(row["applied_at"] or "-"),
                    "window_geometry": row["window_geometry"] or "",
                }

        state = {
            "config": normalize_config(copy.deepcopy(template_config), template_config),
            "disk_alert": default_disk_alert_config(),
            "sound_enabled": True,
            "auto_start": False,
            "settings_locked": False,
            "was_running": False,
            "applied_at": "-",
            "window_geometry": "",
        }
        if CONFIG_JSON_PATH.exists():
            try:
                state["config"] = normalize_config(_load_json_config(CONFIG_JSON_PATH), template_config)
            except Exception:
                state["config"] = normalize_config(copy.deepcopy(template_config), template_config)
        else:
            write_json_file(CONFIG_JSON_PATH, state["config"])
        self.save(
            config=state["config"],
            disk_alert=state["disk_alert"],
            sound_enabled=state["sound_enabled"],
            auto_start=state["auto_start"],
            settings_locked=state["settings_locked"],
            was_running=state["was_running"],
            applied_at=state["applied_at"],
            window_geometry=state["window_geometry"],
        )
        return state

    def save(
        self,
        *,
        config: dict,
        disk_alert: dict,
        sound_enabled: bool,
        auto_start: bool,
        settings_locked: bool,
        was_running: bool,
        applied_at: str,
        window_geometry: str,
    ) -> None:
        payload = json.dumps(config, ensure_ascii=False, indent=2)
        disk_alert_payload = json.dumps(normalize_disk_alert_config(disk_alert), ensure_ascii=False, indent=2)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(id, config_json, disk_alert_json, sound_enabled, auto_start, settings_locked, was_running, applied_at, window_geometry, updated_at)
                VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    config_json=excluded.config_json,
                    disk_alert_json=excluded.disk_alert_json,
                    sound_enabled=excluded.sound_enabled,
                    auto_start=excluded.auto_start,
                    settings_locked=excluded.settings_locked,
                    was_running=excluded.was_running,
                    applied_at=excluded.applied_at,
                    window_geometry=excluded.window_geometry,
                    updated_at=excluded.updated_at
                """,
                (
                    payload,
                    disk_alert_payload,
                    1 if sound_enabled else 0,
                    1 if auto_start else 0,
                    1 if settings_locked else 0,
                    1 if was_running else 0,
                    applied_at or "-",
                    window_geometry or "",
                    _now_iso(),
                ),
            )
            conn.commit()

    def reload(self, template_config: dict) -> dict:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM app_state WHERE id = 1").fetchone()
        if row is None:
            return self.load_or_init(template_config)
        config = normalize_config(json.loads(row["config_json"]), template_config)
        if CONFIG_JSON_PATH.exists():
            try:
                config = normalize_config(_load_json_config(CONFIG_JSON_PATH), template_config)
            except Exception:
                pass
        return {
            "config": config,
            "disk_alert": normalize_disk_alert_config(json.loads(row["disk_alert_json"] or "{}")),
            "sound_enabled": bool(row["sound_enabled"]),
            "auto_start": bool(row["auto_start"]),
            "settings_locked": bool(row["settings_locked"]),
            "was_running": bool(row["was_running"]),
            "applied_at": str(row["applied_at"] or "-"),
            "window_geometry": row["window_geometry"] or "",
        }


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: QWidget, expanded: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._content = content
        self._toggle = QToolButton(self)
        self._title = title
        self._toggle.setText(f" {title}")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle.setCursor(Qt.PointingHandCursor)
        self._toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._toggle.setStyleSheet(
            """
            QToolButton {
                text-align: left;
                padding: 8px 12px;
                border: 1px solid #d8e0ec;
                border-radius: 8px;
                background: #ffffff;
                color: #1f2937;
                font-size: 13px;
                font-weight: 600;
            }
            QToolButton:hover {
                background: #f8fbff;
                border-color: #adc6f5;
            }
            QToolButton:checked {
                background: #f3f7fd;
                border-color: #b8c7da;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._toggle)
        layout.addWidget(self._content)

        self._toggle.toggled.connect(self._apply_state)
        self._apply_state(expanded)

    def _apply_state(self, expanded: bool) -> None:
        self._toggle.setText(f" {self._title}")
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._content.setVisible(expanded)
        self._content.setMaximumHeight(16777215 if expanded else 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred if expanded else QSizePolicy.Maximum)
        self.updateGeometry()


class SyUIAgentWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SY串口通信总控程序")
        self.resize(1280, 860)
        self.setMinimumSize(1100, 760)

        self.template_config = build_template_config(copy.deepcopy(UI_TEMPLATE_BASE))
        self.store = AppStateStore(DB_PATH)
        self.state_row = self.store.load_or_init(self.template_config)
        self.local_config = copy.deepcopy(self.state_row["config"])
        self.current_config = copy.deepcopy(self.local_config)
        self.local_disk_alert_config = normalize_disk_alert_config(self.state_row.get("disk_alert"))
        self.disk_alert_config = copy.deepcopy(self.local_disk_alert_config)
        self._disk_specs = disk_monitor_specs()

        self.sound_enabled = bool(self.state_row["sound_enabled"])
        self.auto_start = bool(self.state_row["auto_start"])
        self._settings_locked = bool(self.state_row["settings_locked"])
        self._restore_running = bool(self.state_row.get("was_running"))
        self.local_applied_at = str(self.state_row.get("applied_at") or "-")
        self.process_state = "已停止"
        self.redis_state = "未知"
        self.alarm_state = "静默"
        self.last_alert_text = "-"

        self._log_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._proc: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_thread: Optional[threading.Thread] = None
        self._manual_stop_requested = False
        self._unexpected_restart_pending = False
        self._sound_loop_active = False
        self._alarm_paused_until_clear = False
        self._drop_runtime_lines = False
        self._log_lines: "deque[str]" = deque(maxlen=8)
        self._log_dirty = False
        self._current_line_index: Optional[int] = None
        self._current_device_index: Optional[int] = None
        self._line_status: dict[int, dict[str, Any]] = {}
        self._active_port_alerts: dict[tuple[int, str], str] = {}
        self._active_disk_alerts: list[str] = []
        self._settings_lock_targets: list[QWidget] = []
        self._save_action_buttons: list[QPushButton] = []
        self._apply_action_buttons: list[QPushButton] = []
        self._form_widgets: dict[tuple[str, str], QWidget] = {}
        self._syncing_forms = False
        self._syncing_json_editor = False
        self._syncing_disk_alert_ui = False
        self._subagent_status_by_ip: dict[str, dict[str, Any]] = {}
        self._selected_subagent_ip: Optional[str] = LOCAL_AGENT_KEY
        self._remote_config_cache: dict[str, dict[str, Any]] = {}
        self._remote_disk_alert_cache: dict[str, dict[str, Any]] = {}
        self._remote_detail_cache: dict[str, dict[str, Any]] = {}
        self._dirty_by_agent: dict[str, bool] = {LOCAL_AGENT_KEY: False}
        self._apply_pending_by_agent: dict[str, bool] = {LOCAL_AGENT_KEY: False}
        self._remote_detail_last_request_mono: dict[str, float] = {}
        self._subagent_refresh_errors = 0
        self._subagent_refresh_inflight = False
        self._subagent_refresh_thread: Optional[threading.Thread] = None
        self._subagent_refresh_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._refresh_redis_client: Optional[redis.Redis] = None
        self._runtime_view_dirty = True
        self._subagent_list_signature: tuple[tuple[str, str], ...] = ()
        self._recent_runtime_events: "deque[str]" = deque(maxlen=12)
        self._overview_detail_text_cache = ""

        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._poll_log_queue)
        self._queue_timer.start(250)

        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.timeout.connect(self._flush_log_view)
        self._log_flush_timer.start(1000)

        self._summary_timer = QTimer(self)
        self._summary_timer.timeout.connect(self._refresh_runtime_summary)
        self._summary_timer.start(1000)

        self._disk_timer = QTimer(self)
        self._disk_timer.timeout.connect(self._check_disk_alerts)
        self._disk_timer.start(int(DISK_CHECK_SEC * 1000))

        self._subagent_timer = QTimer(self)
        self._subagent_timer.timeout.connect(self.refresh_subagents)
        self._subagent_timer.start(3000)

        self._alarm_player = AlarmSoundPlayer()
        self._alarm_player.start()

        self._build_ui()
        self._rebuild_settings_lock_targets()
        self._reset_runtime_state()
        self._load_config_into_ui()
        self._update_config_action_labels()
        self._update_static_labels()
        self._apply_subagent_refresh_result(LOCAL_AGENT_KEY, {LOCAL_AGENT_KEY: self._build_local_agent_snapshot()})
        QTimer.singleShot(0, self.refresh_subagents)

        if self.state_row["window_geometry"]:
            geometry = _decode_geometry(self.state_row["window_geometry"])
            if not geometry.isEmpty():
                self.restoreGeometry(geometry)

        if self.auto_start or self._restore_running:
            QTimer.singleShot(500, self.start_agent)

    # -------------------------
    # UI build
    # -------------------------
    def _build_ui(self) -> None:
        content = QWidget(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.top_section = CollapsibleSection("控制", self._build_top_panel(), expanded=True, parent=self)
        self.subagent_section = CollapsibleSection("通信程序管理", self._build_subagent_panel(), expanded=True, parent=self)
        self.overview_section = CollapsibleSection("线路状态（本机）", self._build_overview_panel(), expanded=True, parent=self)
        root.addWidget(self.top_section)
        root.addWidget(self.subagent_section)
        root.addWidget(self.overview_section)

        self.tabs = QTabWidget(self)
        self.tab_json = self._build_config_tab()
        self.tabs.addTab(self.tab_json, "配置文件")
        self.tab_disk_alert = self._build_disk_alert_tab()
        self.tabs.addTab(self.tab_disk_alert, "磁盘告警")
        self.form_tabs: list[QWidget] = []
        for tab_title, sections in FORM_TAB_GROUPS:
            page = self._build_form_tab(tab_title, sections)
            self.form_tabs.append(page)
            self.tabs.addTab(page, tab_title)
        self.tab_lines = self._build_lines_tab()
        self.tabs.addTab(self.tab_lines, "线路编辑")
        self.config_section = CollapsibleSection("配置（本机）", self.tabs, expanded=True, parent=self)
        root.addWidget(self.config_section)

        self.log_section = CollapsibleSection("日志", self._build_log_panel(), expanded=True, parent=self)
        root.addWidget(self.log_section)
        root.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

        save_action = QAction("保存", self)
        save_action.triggered.connect(self.save_settings)
        save_action.setShortcut("Ctrl+S")
        self.addAction(save_action)

    def _build_top_panel(self) -> QWidget:
        box = QWidget(self)
        layout = QGridLayout(box)

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

        layout.addWidget(QLabel("告警："), 1, 0)
        self.alarm_value = QLabel("-")
        layout.addWidget(self.alarm_value, 1, 1)
        layout.addWidget(QLabel("最近告警："), 1, 2)
        self.last_alert_value = QLabel("-")
        self.last_alert_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.last_alert_value, 1, 3)
        layout.addWidget(QLabel("Redis连接状态："), 1, 8)
        self.redis_value = QLabel("-")
        layout.addWidget(self.redis_value, 1, 9)
        layout.setColumnStretch(3, 1)

        return box

    def _build_overview_panel(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)

        info_box = QGroupBox("当前 Agent")
        info_form = QFormLayout(info_box)
        self.line_status_name_value = QLabel("-")
        self.line_status_ip_value = QLabel("-")
        self.line_status_online_value = QLabel("-")
        self.line_status_last_seen_value = QLabel("-")
        self.line_status_version_value = QLabel("-")
        self.line_status_apply_value = QLabel("-")
        self.line_status_applied_at_value = QLabel("-")
        info_form.addRow("名称", self.line_status_name_value)
        info_form.addRow("IP", self.line_status_ip_value)
        info_form.addRow("工作状态", self.line_status_online_value)
        info_form.addRow("最后心跳", self.line_status_last_seen_value)
        info_form.addRow("版本", self.line_status_version_value)
        info_form.addRow("应用结果", self.line_status_apply_value)
        info_form.addRow("应用时间", self.line_status_applied_at_value)
        layout.addWidget(info_box)

        self.line_status_tabs = QTabWidget(self)
        self.overview_table = QTableWidget(0, 7, self)
        self.overview_table.setMinimumHeight(OVERVIEW_PANEL_MIN_HEIGHT)
        self.overview_table.setHorizontalHeaderLabels(["线路ID", "名称", "头端口", "尾端口", "通信状态", "最近成功", "告警"])
        self.overview_table.verticalHeader().setVisible(False)
        self.overview_table.setAlternatingRowColors(True)
        self.overview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.overview_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.overview_table.setSelectionMode(QTableWidget.SingleSelection)
        self.overview_table.setWordWrap(False)
        header = self.overview_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.overview_table.setColumnWidth(0, 70)
        self.overview_table.setColumnWidth(1, 150)
        self.overview_table.setColumnWidth(2, 110)
        self.overview_table.setColumnWidth(3, 110)
        self.overview_table.setColumnWidth(4, 90)
        self.overview_table.setColumnWidth(5, 90)

        self.overview_detail_text = QPlainTextEdit(self)
        self.overview_detail_text.setReadOnly(True)
        self.overview_detail_text.setMinimumHeight(OVERVIEW_PANEL_MIN_HEIGHT)
        self.overview_detail_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        detail_font = QFont("Menlo")
        detail_font.setStyleHint(QFont.Monospace)
        self.overview_detail_text.setFont(detail_font)

        self.line_status_tabs.addTab(self.overview_table, "概览")
        self.line_status_tabs.addTab(self.overview_detail_text, "详情")
        self.line_status_tabs.currentChanged.connect(self._on_line_status_tab_changed)
        layout.addWidget(self.line_status_tabs)
        return box

    def _build_subagent_panel(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)

        toolbar = QHBoxLayout()
        self.refresh_subagents_button = QPushButton("刷新子机")
        self.refresh_subagents_button.clicked.connect(self.refresh_subagents)
        self.load_remote_config_button = QPushButton("读取远程配置")
        self.load_remote_config_button.clicked.connect(self.load_selected_subagent_config)
        self.start_subagent_button = QPushButton("远程启动")
        self.start_subagent_button.clicked.connect(self.start_selected_subagent_agent)
        self.stop_subagent_button = QPushButton("远程停止")
        self.stop_subagent_button.clicked.connect(self.stop_selected_subagent_agent)
        self.restart_subagent_button = QPushButton("远程重启")
        self.restart_subagent_button.clicked.connect(self.restart_selected_subagent_agent)
        toolbar.addWidget(self.refresh_subagents_button)
        toolbar.addWidget(self.load_remote_config_button)
        toolbar.addWidget(self.start_subagent_button)
        toolbar.addWidget(self.stop_subagent_button)
        toolbar.addWidget(self.restart_subagent_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.subagent_list = QListWidget(self)
        self.subagent_list.currentRowChanged.connect(self._on_subagent_selected)
        layout.addWidget(self.subagent_list, stretch=1)
        return box

    def _build_config_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        toolbar = QHBoxLayout()
        self.save_button = self._new_save_action_button()
        self.save_button.clicked.connect(self.save_settings)
        self.import_button = QPushButton("恢复默认模板")
        self.import_button.clicked.connect(self.import_default_template)
        self.import_file_button = QPushButton("导入 JSON 配置")
        self.import_file_button.clicked.connect(self.import_from_json_file)
        self.import_py_button = QPushButton("导入 .py(开发)")
        self.import_py_button.clicked.connect(self.import_from_py_file)
        self.export_button = QPushButton("导出 JSON 配置")
        self.export_button.clicked.connect(self.export_to_json_config)
        self.export_py_button = QPushButton("导出 .py(开发)")
        self.export_py_button.clicked.connect(self.export_to_py_config)
        self.export_diag_button = QPushButton("导出诊断包")
        self.export_diag_button.clicked.connect(self.export_diagnostic_bundle)
        self.format_json_button = QPushButton("格式化 JSON")
        self.format_json_button.clicked.connect(self._format_json_editor)
        self.push_remote_config_button = self._new_apply_action_button()
        self.push_remote_config_button.clicked.connect(self.push_selected_subagent_config)
        self.runtime_config_label = QLabel(str(RUNTIME_CONFIG_PATH))
        self.runtime_config_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        toolbar.addWidget(self.save_button)
        toolbar.addWidget(self.push_remote_config_button)
        toolbar.addWidget(self.import_button)
        toolbar.addWidget(self.import_file_button)
        toolbar.addWidget(self.import_py_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.export_py_button)
        toolbar.addWidget(self.export_diag_button)
        toolbar.addWidget(self.format_json_button)
        toolbar.addWidget(self.runtime_config_label)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.config_text = QPlainTextEdit(self)
        self.config_text.setMinimumHeight(EDITOR_PANEL_MIN_HEIGHT)
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.Monospace)
        self.config_text.setFont(mono)
        self.config_text.textChanged.connect(self._on_config_text_changed)
        layout.addWidget(self.config_text, stretch=1)
        return tab

    def _build_disk_alert_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.addLayout(self._build_page_action_bar())

        disk_box = QGroupBox("磁盘告警")
        disk_layout = QHBoxLayout(disk_box)
        self.disk_c_checkbox = QCheckBox("C盘")
        self.disk_d_checkbox = QCheckBox("D盘")
        self.disk_c_checkbox.setText(self._disk_specs[0]["label"])
        self.disk_d_checkbox.setText(self._disk_specs[1]["label"])
        self.disk_threshold_combo = QComboBox(self)
        for value in DISK_THRESHOLD_OPTIONS:
            self.disk_threshold_combo.addItem(f"{value}%", value)
        self.disk_c_checkbox.toggled.connect(lambda _checked: self._on_disk_alert_ui_changed())
        self.disk_d_checkbox.toggled.connect(lambda _checked: self._on_disk_alert_ui_changed())
        self.disk_threshold_combo.currentIndexChanged.connect(lambda _index: self._on_disk_alert_ui_changed())
        disk_layout.addWidget(self.disk_c_checkbox)
        disk_layout.addWidget(self.disk_d_checkbox)
        disk_layout.addWidget(QLabel("阈值"))
        disk_layout.addWidget(self.disk_threshold_combo)
        disk_layout.addStretch(1)

        usage_box = QGroupBox("磁盘使用情况")
        usage_form = QFormLayout(usage_box)
        self.disk_usage_c_value = QLabel("-")
        self.disk_usage_d_value = QLabel("-")
        self.disk_usage_c_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.disk_usage_d_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        usage_form.addRow(self._disk_specs[0]["label"], self.disk_usage_c_value)
        usage_form.addRow(self._disk_specs[1]["label"], self.disk_usage_d_value)

        layout.addWidget(disk_box)
        layout.addWidget(usage_box)
        layout.addStretch(1)
        return tab

    def _build_form_tab(self, tab_title: str, sections: list[str]) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.addLayout(self._build_page_action_bar())

        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        for section in sections:
            box = QGroupBox(SECTION_TITLES.get(section, section))
            form = QFormLayout(box)
            for key, value in self.template_config.get(section, {}).items():
                widget = self._create_form_widget(section, key, value)
                self._bind_form_widget_sync(section, key, widget)
                self._form_widgets[(section, key)] = widget
                form.addRow(str(key), widget)
            container_layout.addWidget(box)
        container_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)
        return tab

    def _create_form_widget(self, section: str, key: str, value: Any) -> QWidget:
        if isinstance(value, bool):
            return QCheckBox(self)
        if section == "ui" and key == "mode":
            widget = QComboBox(self)
            widget.addItems(["dashboard", "plain"])
            return widget
        if section == "ui" and key == "ansi":
            widget = QComboBox(self)
            widget.addItems(["auto", "always", "never"])
            return widget
        widget = QLineEdit(self)
        return widget

    def _bind_form_widget_sync(self, section: str, key: str, widget: QWidget) -> None:
        if isinstance(widget, QCheckBox):
            widget.stateChanged.connect(lambda _state, s=section, k=key, w=widget: self._sync_form_field(s, k, w))
            return
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(lambda _text, s=section, k=key, w=widget: self._sync_form_field(s, k, w))
            return
        if isinstance(widget, QLineEdit):
            widget.editingFinished.connect(lambda s=section, k=key, w=widget: self._sync_form_field(s, k, w))

    def _sync_form_field(self, section: str, key: str, widget: QWidget) -> None:
        if self._syncing_forms:
            return
        template_value = self.template_config.get(section, {}).get(key)
        try:
            parsed = self._parse_form_widget_value(widget, template_value)
            self.current_config.setdefault(section, {})[key] = parsed
            self.current_config = normalize_config(self.current_config, self.template_config)
        except Exception:
            return
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_config = copy.deepcopy(self.current_config)
        else:
            self._remote_config_cache[str(self._selected_subagent_ip)] = copy.deepcopy(self.current_config)
        self._push_current_config_to_json()
        self._mark_current_target_dirty()

    def _build_lines_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.addLayout(self._build_page_action_bar())
        content = QWidget(self)
        content_layout = QVBoxLayout(content)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self._build_line_panel())
        splitter.addWidget(self._build_device_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 1])
        content_layout.addWidget(splitter, stretch=1)
        layout.addWidget(content, stretch=1)
        return tab

    def _build_line_panel(self) -> QWidget:
        panel = QGroupBox("线路")
        layout = QHBoxLayout(panel)
        layout.setSpacing(12)

        list_panel = QWidget(self)
        list_layout = QVBoxLayout(list_panel)
        self.lines_list = QListWidget(self)
        self.lines_list.currentRowChanged.connect(self._on_line_select)
        list_layout.addWidget(self.lines_list, stretch=1)

        btns = QHBoxLayout()
        self.add_line_button = QPushButton("新增线路")
        self.add_line_button.clicked.connect(self.add_line)
        self.remove_line_button = QPushButton("删除线路")
        self.remove_line_button.clicked.connect(self.remove_line)
        btns.addWidget(self.add_line_button)
        btns.addWidget(self.remove_line_button)
        list_layout.addLayout(btns)

        form_panel = QWidget(self)
        line_form = QFormLayout(form_panel)
        self.line_id_edit = QLineEdit(self)
        self.line_name_edit = QLineEdit(self)
        self.line_head_edit = QLineEdit(self)
        self.line_tail_edit = QLineEdit(self)
        self.line_ring_checkbox = QCheckBox("环形模式", self)
        self.line_baudrate_edit = QLineEdit(self)
        self.line_timeout_edit = QLineEdit(self)
        self.apply_line_button = QPushButton("应用线路")
        self.apply_line_button.clicked.connect(self.apply_line_changes)

        line_form.addRow("线路 ID", self.line_id_edit)
        line_form.addRow("名称", self.line_name_edit)
        line_form.addRow("头端口", self.line_head_edit)
        line_form.addRow("尾端口", self.line_tail_edit)
        line_form.addRow("波特率", self.line_baudrate_edit)
        line_form.addRow("超时", self.line_timeout_edit)
        line_form.addRow("", self.line_ring_checkbox)
        line_form.addRow("", self.apply_line_button)
        line_form.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(list_panel, 1)
        layout.addWidget(form_panel, 1)
        return panel

    def _build_device_panel(self) -> QWidget:
        device_box = QGroupBox("设备")
        device_layout = QHBoxLayout(device_box)
        device_layout.setSpacing(12)

        left = QVBoxLayout()
        self.devices_list = QListWidget(self)
        self.devices_list.currentRowChanged.connect(self._on_device_select)
        left.addWidget(self.devices_list, stretch=1)
        device_buttons = QHBoxLayout()
        self.add_device_button = QPushButton("新增设备")
        self.add_device_button.clicked.connect(self.add_device)
        self.remove_device_button = QPushButton("删除设备")
        self.remove_device_button.clicked.connect(self.remove_device)
        device_buttons.addWidget(self.add_device_button)
        device_buttons.addWidget(self.remove_device_button)
        left.addLayout(device_buttons)

        right_box = QWidget(self)
        right_form = QFormLayout(right_box)
        self.device_serial_edit = QLineEdit(self)
        self.device_nms_edit = QLineEdit(self)
        self.device_a1_interval_edit = QLineEdit(self)
        self.apply_device_button = QPushButton("应用设备")
        self.apply_device_button.clicked.connect(self.apply_device_changes)
        right_form.addRow("设备 ID", self.device_serial_edit)
        right_form.addRow("NMS ID", self.device_nms_edit)
        right_form.addRow("A1 间隔", self.device_a1_interval_edit)
        right_form.addRow("", self.apply_device_button)

        left_frame = QFrame(self)
        left_frame.setLayout(left)
        device_layout.addWidget(left_frame, 1)
        device_layout.addWidget(right_box, 1)
        return device_box

    def _build_log_panel(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)
        self.log_text = QTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(EDITOR_PANEL_MIN_HEIGHT)
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.Monospace)
        self.log_text.setFont(mono)
        layout.addWidget(self.log_text, stretch=1)
        return box

    def _new_save_action_button(self) -> QPushButton:
        button = QPushButton("保存")
        button.clicked.connect(self.save_settings)
        self._save_action_buttons.append(button)
        return button

    def _new_apply_action_button(self) -> QPushButton:
        button = QPushButton("保存并应用")
        button.clicked.connect(self.push_selected_subagent_config)
        self._apply_action_buttons.append(button)
        return button

    def _build_page_action_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(self._new_save_action_button())
        layout.addWidget(self._new_apply_action_button())
        layout.addStretch(1)
        return layout

    # -------------------------
    # UI helpers
    # -------------------------
    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def _current_target_key(self) -> str:
        return str(self._selected_subagent_ip or LOCAL_AGENT_KEY)

    def _mark_current_target_dirty(self) -> None:
        key = self._current_target_key()
        self._dirty_by_agent[key] = True
        self._update_config_action_labels()

    def _mark_current_target_saved(self, *, applied: bool) -> None:
        key = self._current_target_key()
        self._dirty_by_agent[key] = False
        self._apply_pending_by_agent[key] = not applied
        self._update_config_action_labels()

    def _update_config_action_labels(self) -> None:
        key = self._current_target_key()
        is_dirty = bool(self._dirty_by_agent.get(key, False))
        apply_pending = bool(self._apply_pending_by_agent.get(key, False))
        save_text = "*保存" if is_dirty else "保存"
        apply_text = "*保存并应用" if (not is_dirty and apply_pending) else "保存并应用"
        for button in self._save_action_buttons:
            button.setText(save_text)
        for button in self._apply_action_buttons:
            button.setText(apply_text)

    def _test_alarm_sound(self) -> None:
        self._alarm_player.set_audio_file(ALARM_WAV_PATH)
        self._alarm_player.set_message("半自动闭塞站间安全传输系统串口故障")
        self._alarm_player.set_active(True)
        QTimer.singleShot(2500, self._stop_alarm_sound)

    def _check_disk_alerts(self) -> None:
        alerts = collect_disk_alerts(self.disk_alert_config)
        if alerts != self._active_disk_alerts:
            self._active_disk_alerts = alerts
            if alerts:
                self.last_alert_text = "；".join(alerts)
            self._update_alarm_state()
            self._update_static_labels()

    def _on_config_text_changed(self) -> None:
        if self._syncing_json_editor:
            return
        self._mark_current_target_dirty()

    def export_diagnostic_bundle(self) -> None:
        default_name = f"sy_agent_ui_diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        target_path, _ = QFileDialog.getSaveFileName(self, "导出诊断包", str(BASE_DIR / default_name), "ZIP 文件 (*.zip)")
        if not target_path:
            return
        summary = {
            "exported_at": _now_iso(),
            "process_state": self.process_state,
            "redis_state": self.redis_state,
            "alarm_state": self.alarm_state,
            "selected_agent": self._selected_agent_display_name(),
            "selected_agent_ip": self._selected_subagent_ip,
            "sound_enabled": self.sound_enabled,
            "auto_start": self.auto_start,
            "settings_locked": self._settings_locked,
            "applied_at": self.local_applied_at,
            "line_status": self._line_status,
            "subagent_status": self._subagent_status_by_ip,
        }
        try:
            with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
                zf.writestr("local_config.json", json.dumps(self.local_config, ensure_ascii=False, indent=2))
                zf.writestr("current_editor.json", self.config_text.toPlainText())
                zf.writestr("recent_logs.txt", _plain_log_lines(self._log_lines))
                if DB_PATH.exists():
                    zf.write(DB_PATH, arcname=DB_PATH.name)
                if RUNTIME_CONFIG_PATH.exists():
                    zf.write(RUNTIME_CONFIG_PATH, arcname=RUNTIME_CONFIG_PATH.name)
                if CONFIG_JSON_PATH.exists():
                    zf.write(CONFIG_JSON_PATH, arcname=CONFIG_JSON_PATH.name)
            self._append_log(f"[ui] exported diagnostic bundle: {target_path}", level="INFO", category="ui")
            self._show_info("导出成功", f"已导出诊断包：\n{target_path}")
        except Exception as exc:
            self._show_error("导出失败", str(exc))

    def _handle_agent_exit(self, code: int) -> None:
        manual_stop = self._manual_stop_requested or self.process_state == "停止中"
        self._proc = None
        self._reader_thread = None
        self._drop_runtime_lines = False
        self._manual_stop_requested = False
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
            self._append_log(
                f"[ui] scheduling restart in {UNEXPECTED_RESTART_DELAY_MS / 1000:.0f}s",
                level="WARN",
                category="ui",
            )
            QTimer.singleShot(UNEXPECTED_RESTART_DELAY_MS, self._restart_after_unexpected_exit)

    def _restart_after_unexpected_exit(self) -> None:
        self._unexpected_restart_pending = False
        if self._proc is not None and self._proc.poll() is None:
            return
        self._append_log("[ui] restarting sy_agent after unexpected exit", level="WARN", category="ui")
        self.start_agent()

    def _update_static_labels(self) -> None:
        if self.sound_checkbox.isChecked() != self.sound_enabled:
            self.sound_checkbox.setChecked(self.sound_enabled)
        if self.auto_start_checkbox.isChecked() != self.auto_start:
            self.auto_start_checkbox.setChecked(self.auto_start)
        _apply_status_style(self.process_value, self.process_state)
        redis_raw = str(self.redis_state).strip().lower()
        if redis_raw in ("正常", "normal", "ok"):
            _apply_status_style(self.redis_value, "正常", kind="good")
        elif _redis_alarm_active(self.redis_state) or redis_raw in ("", "-", "未知", "unknown"):
            _apply_status_style(self.redis_value, "断开", kind="bad")
        else:
            _apply_status_style(self.redis_value, "断开", kind="bad")
        _apply_status_style(self.alarm_value, self.alarm_state)
        self.last_alert_value.setText(self.last_alert_text)
        self.last_alert_value.setStyleSheet("")
        self.runtime_config_label.setText(str(RUNTIME_CONFIG_PATH))
        self.lock_button.setText("解锁" if self._settings_locked else "锁定")
        self.pause_alarm_button.setEnabled((bool(self._active_port_alerts) or _redis_alarm_active(self.redis_state) or bool(self._active_disk_alerts)) and self.sound_enabled)
        self._update_config_section_title()
        self._update_line_status_section_title()
        is_local_target = self._selected_subagent_ip in (None, LOCAL_AGENT_KEY)
        self.load_remote_config_button.setEnabled(not is_local_target)
        if self.process_state == "运行中":
            self.primary_button.setText("停止")
            self.primary_button.setEnabled(True)
        elif self.process_state == "停止中":
            self.primary_button.setText("停止中…")
            self.primary_button.setEnabled(False)
        else:
            self.primary_button.setText("启动")
            self.primary_button.setEnabled(True)
        can_edit = self.process_state != "停止中"
        for button in self._save_action_buttons:
            button.setEnabled(can_edit)
        for button in self._apply_action_buttons:
            button.setEnabled(can_edit)
        self.import_button.setEnabled(can_edit)
        self.import_file_button.setEnabled(can_edit)
        self.import_py_button.setEnabled(can_edit)
        self.export_button.setEnabled(can_edit)
        self.export_py_button.setEnabled(can_edit)
        self.export_diag_button.setEnabled(can_edit)
        self.auto_start_checkbox.setEnabled(can_edit)
        self._apply_settings_lock_state()

    def _selected_agent_display_name(self) -> str:
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            return "本机"
        info = self._subagent_status_by_ip.get(self._selected_subagent_ip or "", {})
        return str(info.get("agent_name") or self._selected_subagent_ip or "分机")

    def _update_config_section_title(self) -> None:
        title = f"配置（{self._selected_agent_display_name()}）"
        self.config_section._title = title
        self.config_section._toggle.setText(f" {title}")

    def _update_line_status_section_title(self) -> None:
        title = f"线路状态（{self._selected_agent_display_name()}）"
        self.overview_section._title = title
        self.overview_section._toggle.setText(f" {title}")

    def _on_primary_button(self) -> None:
        if self.process_state == "运行中":
            self.stop_agent()
            return
        if self.process_state == "停止中":
            return
        self.start_agent()

    def _rebuild_settings_lock_targets(self) -> None:
        self._settings_lock_targets = [
            self.primary_button,
            self.import_button,
            self.import_file_button,
            self.import_py_button,
            self.export_button,
            self.export_py_button,
            self.export_diag_button,
            self.auto_start_checkbox,
            self.disk_c_checkbox,
            self.disk_d_checkbox,
            self.disk_threshold_combo,
            self.format_json_button,
            self.config_text,
            self.lines_list,
            self.add_line_button,
            self.remove_line_button,
            self.line_id_edit,
            self.line_name_edit,
            self.line_head_edit,
            self.line_tail_edit,
            self.line_ring_checkbox,
            self.line_baudrate_edit,
            self.line_timeout_edit,
            self.apply_line_button,
            self.devices_list,
            self.add_device_button,
            self.remove_device_button,
            self.device_serial_edit,
            self.device_nms_edit,
            self.device_a1_interval_edit,
            self.apply_device_button,
            self.load_remote_config_button,
            self.start_subagent_button,
            self.stop_subagent_button,
            self.restart_subagent_button,
        ]
        self._settings_lock_targets.extend(self._save_action_buttons)
        self._settings_lock_targets.extend(self._apply_action_buttons)
        self._settings_lock_targets.extend(self._form_widgets.values())

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
            self.disk_alert_config = self._pull_disk_alert_from_ui()
            self.local_disk_alert_config = normalize_disk_alert_config(self.disk_alert_config)
            self.store.save(
                config=self.local_config,
                disk_alert=self.local_disk_alert_config,
                sound_enabled=self.sound_enabled,
                auto_start=self.auto_start,
                settings_locked=self._settings_locked,
                was_running=(self._proc is not None and self._proc.poll() is None),
                applied_at=self.local_applied_at,
                window_geometry=_encode_geometry(self.saveGeometry()),
            )
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
        self.disk_alert_config = self._pull_disk_alert_from_ui()
        self.local_disk_alert_config = normalize_disk_alert_config(self.disk_alert_config)
        self.store.save(
            config=self.local_config,
            disk_alert=self.local_disk_alert_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            was_running=(self._proc is not None and self._proc.poll() is None),
            applied_at=self.local_applied_at,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        self._append_log("[ui] settings unlocked", level="INFO", category="ui")

    # -------------------------
    # Config / sqlite
    # -------------------------
    def _load_config_into_ui(self) -> None:
        self._load_disk_alert_into_ui()
        self._push_current_config_to_json()
        self._load_forms_from_current_config()
        self._refresh_line_list()

    def _load_disk_alert_into_ui(self) -> None:
        self._syncing_disk_alert_ui = True
        self.disk_c_checkbox.setChecked(bool(self.disk_alert_config.get("c_enabled", False)))
        self.disk_d_checkbox.setChecked(bool(self.disk_alert_config.get("d_enabled", False)))
        idx = self.disk_threshold_combo.findData(int(self.disk_alert_config.get("threshold_percent", 10)))
        self.disk_threshold_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._syncing_disk_alert_ui = False
        self._refresh_disk_usage_view()

    def _refresh_disk_usage_view(self) -> None:
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            usage_items = collect_disk_usage(self.disk_alert_config)
            threshold_percent = int(self.disk_alert_config.get("threshold_percent", 10))
        else:
            info = self._subagent_status_by_ip.get(str(self._selected_subagent_ip), {})
            usage_items = info.get("disk_usage") or []
            if not isinstance(usage_items, list):
                usage_items = []
            threshold_percent = int(normalize_disk_alert_config(info.get("disk_alert")).get("threshold_percent", 10))
        usage_map = {str(item.get("slot", "")).lower(): item for item in usage_items if isinstance(item, dict)}
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
        if self._syncing_disk_alert_ui:
            return
        self.disk_alert_config = self._pull_disk_alert_from_ui()
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_disk_alert_config = normalize_disk_alert_config(self.disk_alert_config)
        else:
            self._remote_disk_alert_cache[str(self._selected_subagent_ip)] = normalize_disk_alert_config(self.disk_alert_config)
        self._refresh_disk_usage_view()
        self._mark_current_target_dirty()

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

    def _set_current_config(self, config: dict) -> None:
        self.current_config = normalize_config(copy.deepcopy(config), self.template_config)
        self._push_current_config_to_json()
        self._load_forms_from_current_config()
        self._refresh_line_list()
        self._update_static_labels()

    def _commit_current_editor_to_selected_target(self) -> bool:
        current_tab = self.tabs.currentWidget()
        if current_tab == self.tab_json:
            try:
                config = self._pull_config_from_json()
            except Exception as exc:
                self._show_error("配置无效", str(exc))
                return False
        else:
            try:
                self._apply_forms_to_current_config()
                config = copy.deepcopy(self.current_config)
            except Exception as exc:
                self._show_error("表单配置无效", str(exc))
                return False

        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_config = copy.deepcopy(config)
            self.local_disk_alert_config = normalize_disk_alert_config(self._pull_disk_alert_from_ui())
        else:
            self._remote_config_cache[str(self._selected_subagent_ip)] = copy.deepcopy(config)
            self._remote_disk_alert_cache[str(self._selected_subagent_ip)] = normalize_disk_alert_config(self._pull_disk_alert_from_ui())
        self.current_config = copy.deepcopy(config)
        self._push_current_config_to_json()
        self._load_forms_from_current_config()
        self._refresh_line_list()
        return True

    def _stash_current_target_draft(self) -> None:
        try:
            current_tab = self.tabs.currentWidget()
            if current_tab == self.tab_json:
                config = self._pull_config_from_json()
            else:
                self._apply_forms_to_current_config()
                config = copy.deepcopy(self.current_config)
        except Exception:
            return
        disk_alert = self._pull_disk_alert_from_ui()
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_config = copy.deepcopy(config)
            self.local_disk_alert_config = normalize_disk_alert_config(disk_alert)
        else:
            self._remote_config_cache[str(self._selected_subagent_ip)] = copy.deepcopy(config)
            self._remote_disk_alert_cache[str(self._selected_subagent_ip)] = normalize_disk_alert_config(disk_alert)

    def _push_current_config_to_json(self) -> None:
        self._syncing_json_editor = True
        self.config_text.setPlainText(json.dumps(self.current_config, ensure_ascii=False, indent=2))
        self._syncing_json_editor = False

    def _set_form_widget_value(self, widget: QWidget, value: Any) -> None:
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
            return
        if isinstance(widget, QComboBox):
            index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
            elif widget.isEditable():
                widget.setCurrentText(str(value))
            return
        if isinstance(widget, QLineEdit):
            if isinstance(value, list):
                widget.setText(", ".join(str(item) for item in value))
            else:
                widget.setText(str(value))

    def _load_forms_from_current_config(self) -> None:
        self._syncing_forms = True
        for (section, key), widget in self._form_widgets.items():
            value = self.current_config.get(section, {}).get(key, self.template_config.get(section, {}).get(key))
            self._set_form_widget_value(widget, value)
        self._syncing_forms = False

    def _parse_form_widget_value(self, widget: QWidget, template_value: Any) -> Any:
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        if isinstance(widget, QLineEdit):
            text = widget.text().strip()
            if isinstance(template_value, list):
                return [item.strip() for item in text.split(",") if item.strip()]
            if isinstance(template_value, int) and not isinstance(template_value, bool):
                return int(text)
            if isinstance(template_value, float):
                return float(text)
            return text
        return template_value

    def _apply_forms_to_current_config(self) -> None:
        for (section, key), widget in self._form_widgets.items():
            template_value = self.template_config.get(section, {}).get(key)
            parsed = self._parse_form_widget_value(widget, template_value)
            self.current_config.setdefault(section, {})[key] = parsed
        self.current_config = normalize_config(self.current_config, self.template_config)

    def _pull_config_from_json(self) -> dict:
        raw = self.config_text.toPlainText().strip()
        if not raw:
            raise ValueError("config JSON is empty")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        return normalize_config(parsed, self.template_config)

    def _format_json_editor(self) -> None:
        try:
            config = self._pull_config_from_json()
        except Exception as exc:
            self._show_error("配置无效", str(exc))
            return
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_config = copy.deepcopy(config)
        else:
            self._remote_config_cache[str(self._selected_subagent_ip)] = copy.deepcopy(config)
        self._set_current_config(config)

    def save_settings(self) -> bool:
        if not self._commit_current_editor_to_selected_target():
            return False

        dirty_before = bool(self._dirty_by_agent.get(self._current_target_key(), False))
        self.sound_enabled = self.sound_checkbox.isChecked()
        self.auto_start = self.auto_start_checkbox.isChecked()
        self.disk_alert_config = self._pull_disk_alert_from_ui()
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_disk_alert_config = normalize_disk_alert_config(self.disk_alert_config)
            write_json_file(CONFIG_JSON_PATH, self.local_config)
            self.store.save(
                config=self.local_config,
                disk_alert=self.local_disk_alert_config,
                sound_enabled=self.sound_enabled,
                auto_start=self.auto_start,
                settings_locked=self._settings_locked,
                was_running=(self._proc is not None and self._proc.poll() is None),
                applied_at=self.local_applied_at,
                window_geometry=_encode_geometry(self.saveGeometry()),
            )
            self._append_log(
                f"[ui] local settings saved to sqlite and {CONFIG_JSON_PATH}",
                level="INFO",
                category="ui",
            )
        else:
            self._remote_disk_alert_cache[str(self._selected_subagent_ip)] = normalize_disk_alert_config(self.disk_alert_config)
            self._append_log(f"[ui] draft saved for {self._selected_agent_display_name()}", level="INFO", category="ui")
        if dirty_before:
            self._mark_current_target_saved(applied=False)
        return True

    def reload_from_db(self) -> None:
        try:
            row = self.store.reload(self.template_config)
        except Exception as exc:
            self._show_error("重载失败", str(exc))
            return
        self.local_config = copy.deepcopy(row["config"])
        self.local_disk_alert_config = normalize_disk_alert_config(row.get("disk_alert"))
        self.disk_alert_config = copy.deepcopy(self.local_disk_alert_config)
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.current_config = copy.deepcopy(self.local_config)
        self.sound_enabled = bool(row["sound_enabled"])
        self.auto_start = bool(row["auto_start"])
        self._settings_locked = bool(row["settings_locked"])
        self.local_applied_at = str(row.get("applied_at") or "-")
        self._set_current_config(self.local_config if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY) else self.current_config)
        self._reset_runtime_state()
        self._update_static_labels()
        self._append_log("[ui] reloaded settings from sqlite", level="INFO", category="ui")

    def import_default_template(self) -> None:
        imported = normalize_config(copy.deepcopy(self.template_config), self.template_config)
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_config = copy.deepcopy(imported)
            write_json_file(CONFIG_JSON_PATH, self.local_config)
            self._set_current_config(self.local_config)
            self._append_log("[ui] restored local defaults from built-in template", level="INFO", category="ui")
        else:
            self._remote_config_cache[str(self._selected_subagent_ip)] = copy.deepcopy(imported)
            self._set_current_config(imported)
            self._append_log("[ui] restored remote draft defaults from built-in template", level="INFO", category="ui")
        self._mark_current_target_dirty()

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
            self._show_error("导入失败", str(exc))
            return
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_config = copy.deepcopy(imported)
            write_json_file(CONFIG_JSON_PATH, self.local_config)
            self._set_current_config(self.local_config)
        else:
            self._remote_config_cache[str(self._selected_subagent_ip)] = copy.deepcopy(imported)
            self._set_current_config(imported)
        self._append_log(f"[ui] imported json config: {source_path}", level="INFO", category="ui")
        self._show_info("导入成功", f"已从以下文件导入：\n{source_path}")
        self._mark_current_target_dirty()

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
            self._show_error("导入失败", str(exc))
            return
        if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
            self.local_config = copy.deepcopy(imported)
            write_json_file(CONFIG_JSON_PATH, self.local_config)
            self._set_current_config(self.local_config)
        else:
            self._remote_config_cache[str(self._selected_subagent_ip)] = copy.deepcopy(imported)
            self._set_current_config(imported)
        self._append_log(f"[ui] imported python config for development: {source_path}", level="INFO", category="ui")
        self._show_info("导入成功", f"已从以下文件导入：\n{source_path}")
        self._mark_current_target_dirty()

    def export_to_json_config(self) -> None:
        try:
            config = self._pull_config_from_json()
        except Exception as exc:
            self._show_error("配置无效", str(exc))
            return

        default_path = str(CONFIG_JSON_PATH)
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 JSON 配置",
            default_path,
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not target_path:
            return

        try:
            write_json_file(Path(target_path), config)
        except Exception as exc:
            self._show_error("导出失败", str(exc))
            return

        self._append_log(f"[ui] exported json config: {target_path}", level="INFO", category="ui")
        self._show_info("导出成功", f"已导出到：\n{target_path}\n\n可在其他设备用“导入 JSON 配置”加载。")

    def export_to_py_config(self) -> None:
        try:
            config = self._pull_config_from_json()
        except Exception as exc:
            self._show_error("配置无效", str(exc))
            return

        default_path = str(CONFIG_PY_PATH)
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Python 配置(开发)",
            default_path,
            "Python 文件 (*.py);;所有文件 (*)",
        )
        if not target_path:
            return

        content = (
            "#!/usr/bin/env python\n"
            "# -*- coding: utf-8 -*-\n\n"
            "CONFIG = "
            + pprint.pformat(config, sort_dicts=False, width=100)
            + "\n"
        )
        try:
            Path(target_path).write_text(content, encoding="utf-8")
        except Exception as exc:
            self._show_error("导出失败", str(exc))
            return

        self._append_log(f"[ui] exported python config for development: {target_path}", level="INFO", category="ui")
        self._show_info("导出成功", f"已导出到：\n{target_path}\n\n可在其他设备用“导入 .py(开发)”加载。")

    # -------------------------
    # Redis / 子机管理
    # -------------------------
    def _make_stream_redis(self, config: Optional[dict] = None) -> redis.Redis:
        cfg = (config or self.local_config).get("redis", {})
        return redis.StrictRedis(
            host=str(cfg.get("host", "localhost")),
            port=int(cfg.get("port", 6379)),
            db=int(cfg.get("db", 0)),
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        )

    def refresh_subagents(self) -> None:
        if self._subagent_refresh_inflight:
            return
        self._subagent_refresh_inflight = True
        selected_ip = self._selected_subagent_ip
        detail_agent_ip = None
        if selected_ip not in (None, LOCAL_AGENT_KEY) and self.line_status_tabs.currentIndex() == 1:
            detail_agent_ip = str(selected_ip)
        local_snapshot = self._build_local_agent_snapshot()
        self._subagent_status_by_ip[LOCAL_AGENT_KEY] = local_snapshot
        self._refresh_selected_subagent_widgets()
        self._update_static_labels()
        self._subagent_refresh_thread = threading.Thread(
            target=self._fetch_subagents_worker,
            args=(selected_ip, detail_agent_ip, local_snapshot),
            name="sy-ui-agent-subagent-refresh",
            daemon=True,
        )
        self._subagent_refresh_thread.start()

    def _build_local_agent_snapshot(self) -> dict[str, Any]:
        return {
            "agent_ip": LOCAL_AGENT_KEY,
            "agent_name": "本机",
            "online": True,
            "last_seen": _now_iso(),
            "desired_version": "-",
            "applied_version": "-",
            "apply_state": "local",
            "applied_at": self.local_applied_at,
            "local_agent_state": self.process_state,
            "disk_alert": copy.deepcopy(self.local_disk_alert_config),
            "disk_usage": collect_disk_usage(self.local_disk_alert_config),
            "lines_summary": self._build_local_lines_summary(),
        }

    def _fetch_subagents_worker(
        self,
        selected_ip: Optional[str],
        detail_agent_ip: Optional[str],
        local_snapshot: dict[str, Any],
    ) -> None:
        try:
            client = self._refresh_redis_client
            if client is None:
                client = self._make_stream_redis()
                client.ping()
                self._refresh_redis_client = client
            keys = sorted(client.scan_iter(match=SUBAGENT_STATUS_PATTERN))
            found: dict[str, dict[str, Any]] = {}
            found[LOCAL_AGENT_KEY] = local_snapshot
            for key in keys:
                raw = client.get(key)
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                agent_ip = str(data.get("agent_ip") or "").strip()
                if agent_ip:
                    found[agent_ip] = data
            detail_payload = None
            if detail_agent_ip:
                try:
                    client.xadd(
                        SUBAGENT_CONTROL_STREAM,
                        {
                            "data": json.dumps(
                                {
                                    "target_agent_ip": detail_agent_ip,
                                    "op": "get_detail_snapshot",
                                    "config_version": "",
                                },
                                ensure_ascii=False,
                            )
                        },
                        maxlen=5000,
                        approximate=True,
                    )
                    raw_detail = client.get(detail_snapshot_key(detail_agent_ip))
                    if raw_detail:
                        parsed_detail = json.loads(raw_detail)
                        if isinstance(parsed_detail, dict):
                            detail_payload = (detail_agent_ip, parsed_detail)
                except Exception:
                    detail_payload = None
            self._subagent_refresh_queue.put(("ok", (selected_ip, found, detail_payload)))
        except Exception as exc:
            self._refresh_redis_client = None
            self._subagent_refresh_queue.put(("error", str(exc)))

    def _apply_subagent_refresh_result(self, selected_ip: Optional[str], found: dict[str, dict[str, Any]]) -> None:
        self._subagent_status_by_ip = found
        target_row = 0
        ordered_agents = sorted(self._subagent_status_by_ip.items())
        list_signature = tuple(
            (
                agent_ip,
                f"{str(info.get('agent_name') or agent_ip)}|{_agent_online_label(info)}|{agent_ip}",
            )
            for agent_ip, info in ordered_agents
        )

        if list_signature != self._subagent_list_signature or self.subagent_list.count() != len(ordered_agents):
            self.subagent_list.blockSignals(True)
            self.subagent_list.clear()
            for agent_ip, info in ordered_agents:
                name = str(info.get("agent_name") or agent_ip)
                online = _agent_online_label(info)
                label = f"{name} [{online}]" if agent_ip == LOCAL_AGENT_KEY else f"{name} ({agent_ip}) [{online}]"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, agent_ip)
                self.subagent_list.addItem(item)
                if selected_ip and agent_ip == selected_ip:
                    target_row = self.subagent_list.count() - 1
            self.subagent_list.blockSignals(False)
            self._subagent_list_signature = list_signature
        else:
            for row, (agent_ip, _info) in enumerate(ordered_agents):
                if selected_ip and agent_ip == selected_ip:
                    target_row = row
                    break

        if self.subagent_list.count() == 0:
            self._selected_subagent_ip = LOCAL_AGENT_KEY
            self._refresh_selected_subagent_widgets()
            return

        if selected_ip is None:
            selected_ip = LOCAL_AGENT_KEY
        self._selected_subagent_ip = selected_ip if selected_ip in self._subagent_status_by_ip else LOCAL_AGENT_KEY

        if self.subagent_list.currentRow() != target_row:
            self.subagent_list.blockSignals(True)
            self.subagent_list.setCurrentRow(target_row)
            self.subagent_list.blockSignals(False)
        self._refresh_selected_subagent_widgets()

    def _on_subagent_selected(self, row: int) -> None:
        self._stash_current_target_draft()
        if row < 0:
            self._selected_subagent_ip = LOCAL_AGENT_KEY
            self._refresh_selected_subagent_widgets()
            return
        item = self.subagent_list.item(row)
        self._selected_subagent_ip = str(item.data(Qt.UserRole))
        self._refresh_selected_subagent_widgets()
        self.load_selected_subagent_config()

    def _refresh_selected_subagent_widgets(self) -> None:
        agent_ip = self._selected_subagent_ip
        info = self._subagent_status_by_ip.get(agent_ip or "", {})
        self.line_status_name_value.setText(str(info.get("agent_name") or "-"))
        self.line_status_ip_value.setText("-" if agent_ip == LOCAL_AGENT_KEY else (agent_ip or "-"))
        _apply_status_style(self.line_status_online_value, _agent_online_label(info) if agent_ip else "-")
        self.line_status_last_seen_value.setText(str(info.get("last_seen") or "-"))
        desired_version = str(info.get("desired_version") or "-")
        applied_version = str(info.get("applied_version") or "-")
        self.line_status_version_value.setText(f"{desired_version} / {applied_version}")
        _apply_status_style(self.line_status_apply_value, str(info.get("apply_state") or "-"))
        self.line_status_applied_at_value.setText(str(info.get("applied_at") or "-"))
        self._runtime_view_dirty = True
        self._refresh_disk_usage_view()
        self._update_config_action_labels()
        self._update_static_labels()
        self._maybe_request_remote_detail(force=True)

    def _on_line_status_tab_changed(self, _index: int) -> None:
        self._runtime_view_dirty = True
        self._maybe_request_remote_detail(force=True)

    def load_selected_subagent_config(self) -> None:
        agent_ip = self._selected_subagent_ip
        if agent_ip in (None, LOCAL_AGENT_KEY):
            self._set_current_config(self.local_config)
            self.disk_alert_config = copy.deepcopy(self.local_disk_alert_config)
            self._load_disk_alert_into_ui()
            self._append_log("[ui] loaded local config into editor", level="INFO", category="ui")
            return
        try:
            cached = self._remote_config_cache.get(agent_ip)
            cached_disk = self._remote_disk_alert_cache.get(agent_ip)
            if cached is not None:
                config = copy.deepcopy(cached)
                disk_alert = normalize_disk_alert_config(cached_disk)
            else:
                client = self._make_stream_redis()
                raw = client.get(desired_config_key(agent_ip))
                if raw:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and "config" in parsed:
                        config = normalize_config(parsed.get("config"), self.template_config)
                        disk_alert = normalize_disk_alert_config(parsed.get("disk_alert"))
                    else:
                        config = normalize_config(parsed, self.template_config)
                        disk_alert = normalize_disk_alert_config(self._subagent_status_by_ip.get(agent_ip, {}).get("disk_alert"))
                else:
                    config = copy.deepcopy(self.local_config)
                    disk_alert = normalize_disk_alert_config(self._subagent_status_by_ip.get(agent_ip, {}).get("disk_alert"))
                self._remote_config_cache[agent_ip] = copy.deepcopy(config)
                self._remote_disk_alert_cache[agent_ip] = normalize_disk_alert_config(disk_alert)
            self._set_current_config(config)
            self.disk_alert_config = normalize_disk_alert_config(disk_alert)
            self._load_disk_alert_into_ui()
            self._append_log(f"[ui] loaded target config for {agent_ip}", level="INFO", category="ui")
        except Exception as exc:
            self._show_error("读取远程配置失败", str(exc))

    def push_selected_subagent_config(self) -> None:
        agent_ip = self._selected_subagent_ip
        if agent_ip in (None, LOCAL_AGENT_KEY):
            try:
                if not self._commit_current_editor_to_selected_target():
                    return
                self.local_applied_at = _now_iso()
                self.sound_enabled = self.sound_checkbox.isChecked()
                self.auto_start = self.auto_start_checkbox.isChecked()
                self.disk_alert_config = self._pull_disk_alert_from_ui()
                self.local_disk_alert_config = normalize_disk_alert_config(self.disk_alert_config)
                self.store.save(
                    config=self.local_config,
                    disk_alert=self.local_disk_alert_config,
                    sound_enabled=self.sound_enabled,
                    auto_start=self.auto_start,
                    settings_locked=self._settings_locked,
                    was_running=True,
                    applied_at=self.local_applied_at,
                    window_geometry=_encode_geometry(self.saveGeometry()),
                )
                self._append_log("[ui] local config saved, applying to local sy_agent", level="INFO", category="ui")
                self._mark_current_target_saved(applied=True)
                self.refresh_subagents()
                if self._proc is not None and self._proc.poll() is None:
                    self.stop_agent()
                    QTimer.singleShot(900, self.start_agent)
                else:
                    self.start_agent()
            except Exception as exc:
                self._show_error("本机生效失败", str(exc))
            return
        try:
            if not self._commit_current_editor_to_selected_target():
                return
            config = copy.deepcopy(self.current_config)
            disk_alert = normalize_disk_alert_config(self._pull_disk_alert_from_ui())
            client = self._make_stream_redis()
            version = datetime.now().strftime("%Y%m%d%H%M%S")
            meta = {
                "agent_ip": agent_ip,
                "agent_name": self._subagent_status_by_ip.get(agent_ip, {}).get("agent_name", agent_ip),
                "config_version": version,
                "updated_at": _now_iso(),
                "updated_by": "ui_agent",
            }
            client.set(desired_config_key(agent_ip), json.dumps({"config": config, "disk_alert": disk_alert}, ensure_ascii=False))
            client.set(desired_meta_key(agent_ip), json.dumps(meta, ensure_ascii=False))
            client.xadd(
                SUBAGENT_CONTROL_STREAM,
                {
                    "data": json.dumps(
                        {
                            "target_agent_ip": agent_ip,
                            "op": "apply_config",
                            "config_version": version,
                        },
                        ensure_ascii=False,
                    )
                },
                maxlen=5000,
                approximate=True,
            )
            self._remote_config_cache[agent_ip] = copy.deepcopy(config)
            self._remote_disk_alert_cache[agent_ip] = disk_alert
            self._append_log(f"[ui] pushed remote config to {agent_ip} version={version}", level="INFO", category="ui")
            self._mark_current_target_saved(applied=True)
            self.refresh_subagents()
        except Exception as exc:
            self._show_error("推送远程配置失败", str(exc))

    def _send_subagent_control(self, agent_ip: str, op: str, config_version: str = "") -> None:
        client = self._make_stream_redis()
        client.xadd(
            SUBAGENT_CONTROL_STREAM,
            {
                "data": json.dumps(
                    {
                        "target_agent_ip": agent_ip,
                        "op": op,
                        "config_version": config_version or "",
                    },
                    ensure_ascii=False,
                )
            },
            maxlen=5000,
            approximate=True,
        )

    def start_selected_subagent_agent(self) -> None:
        agent_ip = self._selected_subagent_ip
        if agent_ip in (None, LOCAL_AGENT_KEY):
            self.start_agent()
            return
        try:
            self._send_subagent_control(agent_ip, "start_agent")
            self._append_log(f"[ui] sent start_agent to {agent_ip}", level="INFO", category="ui")
        except Exception as exc:
            self._show_error("远程启动失败", str(exc))

    def stop_selected_subagent_agent(self) -> None:
        agent_ip = self._selected_subagent_ip
        if agent_ip in (None, LOCAL_AGENT_KEY):
            self.stop_agent()
            return
        try:
            self._send_subagent_control(agent_ip, "stop_agent")
            self._append_log(f"[ui] sent stop_agent to {agent_ip}", level="WARN", category="ui")
        except Exception as exc:
            self._show_error("远程停止失败", str(exc))

    def restart_selected_subagent_agent(self) -> None:
        agent_ip = self._selected_subagent_ip
        if agent_ip in (None, LOCAL_AGENT_KEY):
            self.stop_agent()
            QTimer.singleShot(800, self.start_agent)
            return
        try:
            self._send_subagent_control(agent_ip, "restart_agent")
            self._append_log(f"[ui] sent restart_agent to {agent_ip}", level="WARN", category="ui")
        except Exception as exc:
            self._show_error("远程重启失败", str(exc))

    def _build_local_lines_summary(self) -> list[dict[str, Any]]:
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

    def _maybe_request_remote_detail(self, *, force: bool = False) -> None:
        agent_ip = self._selected_subagent_ip
        if agent_ip in (None, LOCAL_AGENT_KEY):
            return
        if self.line_status_tabs.currentIndex() != 1:
            return
        nowt = time.monotonic()
        last = self._remote_detail_last_request_mono.get(agent_ip, 0.0)
        if not force and nowt - last < REMOTE_DETAIL_REQUEST_SEC:
            return
        try:
            self._send_subagent_control(agent_ip, "get_detail_snapshot")
            self._remote_detail_last_request_mono[agent_ip] = nowt
        except Exception:
            return

    def _fetch_remote_detail_if_needed(self, client: redis.Redis) -> None:
        agent_ip = self._selected_subagent_ip
        if agent_ip in (None, LOCAL_AGENT_KEY):
            return
        if self.line_status_tabs.currentIndex() != 1:
            return
        self._maybe_request_remote_detail()
        try:
            raw = client.get(detail_snapshot_key(agent_ip))
            if not raw:
                return
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                self._remote_detail_cache[agent_ip] = parsed
                self._runtime_view_dirty = True
        except Exception:
            return

    # -------------------------
    # Line editor
    # -------------------------
    def _refresh_line_list(self) -> None:
        self.lines_list.blockSignals(True)
        self.lines_list.clear()
        for line in self.current_config.get("lines", []):
            self.lines_list.addItem(QListWidgetItem(f"{line['line_id']}: {line['name']}"))
        self.lines_list.blockSignals(False)

        if self.current_config.get("lines"):
            if self._current_line_index is None or self._current_line_index >= len(self.current_config["lines"]):
                self._current_line_index = 0
            self.lines_list.setCurrentRow(self._current_line_index)
        else:
            self._current_line_index = None
            self._current_device_index = None
            self._clear_line_form()
            self._refresh_device_list()

    def _current_line(self) -> Optional[dict]:
        if self._current_line_index is None:
            return None
        lines = self.current_config.get("lines", [])
        if self._current_line_index < 0 or self._current_line_index >= len(lines):
            return None
        return lines[self._current_line_index]

    def _current_device(self) -> Optional[dict]:
        line = self._current_line()
        if line is None or self._current_device_index is None:
            return None
        devices = line.get("devices", [])
        if self._current_device_index < 0 or self._current_device_index >= len(devices):
            return None
        return devices[self._current_device_index]

    def _clear_line_form(self) -> None:
        self.line_id_edit.clear()
        self.line_name_edit.clear()
        self.line_head_edit.clear()
        self.line_tail_edit.clear()
        self.line_ring_checkbox.setChecked(False)
        self.line_baudrate_edit.clear()
        self.line_timeout_edit.clear()
        self._clear_device_form()

    def _clear_device_form(self) -> None:
        self.device_serial_edit.clear()
        self.device_nms_edit.clear()
        self.device_a1_interval_edit.clear()

    def _on_line_select(self, row: int) -> None:
        if row < 0:
            self._current_line_index = None
            self._clear_line_form()
            self._refresh_device_list()
            return
        self._current_line_index = int(row)
        line = self._current_line()
        if line is None:
            return
        self.line_id_edit.setText(str(line["line_id"]))
        self.line_name_edit.setText(str(line["name"]))
        self.line_head_edit.setText(str(line["head_port"]))
        self.line_tail_edit.setText(str(line["tail_port"]))
        self.line_ring_checkbox.setChecked(bool(line.get("ring_mode", False)))
        self.line_baudrate_edit.setText(str(line.get("baudrate", 19200)))
        self.line_timeout_edit.setText(str(line.get("timeout", 0.0)))
        self._current_device_index = 0 if line.get("devices") else None
        self._refresh_device_list()

    def _refresh_device_list(self) -> None:
        self.devices_list.blockSignals(True)
        self.devices_list.clear()
        line = self._current_line()
        if line is None:
            self.devices_list.blockSignals(False)
            self._clear_device_form()
            return
        for device in line.get("devices", []):
            self.devices_list.addItem(QListWidgetItem(f"{device['serial_id']} -> {device['nms_id']} @ {device['a1_interval']}"))
        self.devices_list.blockSignals(False)
        if line.get("devices"):
            if self._current_device_index is None or self._current_device_index >= len(line["devices"]):
                self._current_device_index = 0
            self.devices_list.setCurrentRow(self._current_device_index)
        else:
            self._current_device_index = None
            self._clear_device_form()

    def _on_device_select(self, row: int) -> None:
        if row < 0:
            self._current_device_index = None
            self._clear_device_form()
            return
        self._current_device_index = int(row)
        device = self._current_device()
        if device is None:
            return
        self.device_serial_edit.setText(str(device["serial_id"]))
        self.device_nms_edit.setText(str(device["nms_id"]))
        self.device_a1_interval_edit.setText(str(device["a1_interval"]))

    def add_line(self) -> None:
        line_ids = [int(line["line_id"]) for line in self.current_config.get("lines", [])]
        next_id = max(line_ids, default=0) + 1
        self.current_config.setdefault("lines", []).append(
            {
                "line_id": next_id,
                "name": f"Line-{next_id}",
                "head_port": "COM1",
                "tail_port": "NONE",
                "ring_mode": False,
                "baudrate": 19200,
                "timeout": 0.0,
                "devices": [],
            }
        )
        self._current_line_index = len(self.current_config["lines"]) - 1
        self._push_current_config_to_json()
        self._refresh_line_list()
        self._mark_current_target_dirty()

    def remove_line(self) -> None:
        if self._current_line_index is None:
            return
        lines = self.current_config.get("lines", [])
        if self._current_line_index < len(lines):
            lines.pop(self._current_line_index)
        self._current_line_index = min(self._current_line_index, len(lines) - 1) if lines else None
        self._push_current_config_to_json()
        self._refresh_line_list()
        self._mark_current_target_dirty()

    def apply_line_changes(self) -> None:
        line = self._current_line()
        if line is None:
            return
        try:
            line["line_id"] = int(self.line_id_edit.text().strip())
            line["name"] = self.line_name_edit.text().strip() or f"Line-{line['line_id']}"
            line["head_port"] = self.line_head_edit.text().strip() or "NONE"
            line["tail_port"] = self.line_tail_edit.text().strip() or "NONE"
            line["ring_mode"] = self.line_ring_checkbox.isChecked()
            line["baudrate"] = int(self.line_baudrate_edit.text().strip())
            line["timeout"] = float(self.line_timeout_edit.text().strip())
            self.current_config = normalize_config(self.current_config, self.template_config)
        except Exception as exc:
            self._show_error("线路配置无效", str(exc))
            return
        self._push_current_config_to_json()
        self._refresh_line_list()
        self._mark_current_target_dirty()

    def add_device(self) -> None:
        line = self._current_line()
        if line is None:
            return
        serial_ids = [int(dev["serial_id"]) for dev in line.get("devices", [])]
        next_serial = max(serial_ids, default=0) + 1
        line.setdefault("devices", []).append({"serial_id": next_serial, "nms_id": next_serial, "a1_interval": 5.0})
        self._current_device_index = len(line["devices"]) - 1
        self._push_current_config_to_json()
        self._refresh_device_list()
        self._mark_current_target_dirty()

    def remove_device(self) -> None:
        line = self._current_line()
        if line is None or self._current_device_index is None:
            return
        devices = line.get("devices", [])
        if self._current_device_index < len(devices):
            devices.pop(self._current_device_index)
        self._current_device_index = min(self._current_device_index, len(devices) - 1) if devices else None
        self._push_current_config_to_json()
        self._refresh_device_list()
        self._mark_current_target_dirty()

    def apply_device_changes(self) -> None:
        device = self._current_device()
        if device is None:
            return
        try:
            device["serial_id"] = int(self.device_serial_edit.text().strip())
            device["nms_id"] = int(self.device_nms_edit.text().strip())
            device["a1_interval"] = float(self.device_a1_interval_edit.text().strip())
            self.current_config = normalize_config(self.current_config, self.template_config)
        except Exception as exc:
            self._show_error("设备配置无效", str(exc))
            return
        self._push_current_config_to_json()
        self._refresh_device_list()
        self._refresh_line_list()
        self._mark_current_target_dirty()

    # -------------------------
    # Runtime state and logs
    # -------------------------
    def _reset_runtime_state(self) -> None:
        self._line_status = {}
        for line in self.local_config.get("lines", []):
            line_id = int(line["line_id"])
            self._line_status[line_id] = _new_line_runtime_state(line_id, str(line["name"]), devices=len(line.get("devices", [])))
        self._active_port_alerts.clear()
        self._recent_runtime_events.clear()
        self.last_alert_text = "-"
        self._runtime_view_dirty = True
        self._update_alarm_state()
        self._update_static_labels()

    def _append_log(self, line: str, *, level: str = "INFO", category: str = "general") -> None:
        escaped = html.escape(line.rstrip())
        color = LOG_COLORS.get(str(category).lower(), LOG_COLORS.get(level.upper(), "#1f2937"))
        self._log_lines.append(f'<span style="color:{color}">{escaped}</span>')
        self._log_dirty = True

    def _flush_log_view(self) -> None:
        if not self._log_dirty:
            return
        body = "<br/>".join(self._log_lines)
        self.log_text.setHtml(
            "<div style=\"font-family: Menlo, monospace; white-space: pre;\">"
            f"{body}"
            "</div>"
        )
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
        self._log_dirty = False

    def _discard_pending_runtime_events(self) -> int:
        kept: list[tuple[str, Any]] = []
        dropped = 0
        while True:
            try:
                item = self._log_queue.get_nowait()
            except queue.Empty:
                break
            kind, payload = item
            if kind == "exit":
                kept.append(item)
            else:
                dropped += 1
        for item in kept:
            self._log_queue.put(item)
        return dropped

    def _record_resp_ok(self, payload: dict[str, Any]) -> None:
        line_id = payload.get("line_id")
        if line_id is None:
            return
        nowt = float(payload.get("nowt", time.monotonic()))
        line_name = str(payload.get("line_name") or "")
        state = self._line_status.setdefault(
            int(line_id),
            _new_line_runtime_state(int(line_id), line_name or f"Line-{line_id}"),
        )
        if line_name:
            state["name"] = line_name
        state["last_ok_mono"] = nowt
        state["last_ok"] = _age_text(nowt, nowt)
        self._runtime_view_dirty = True

    def _should_parse_runtime_line(self, raw: str) -> bool:
        match = LOG_RE.match(raw.strip())
        if not match:
            return False
        category = str(match.group("category") or "general").lower()
        if category in ("redis", "port", "cmd", "dlq", "poll"):
            return True
        message = match.group("message") or ""
        return ("[STATUS]" in message) or ("[PORT]" in message) or ("[Redis]" in message)

    def _poll_log_queue(self) -> None:
        while True:
            try:
                kind, payload = self._subagent_refresh_queue.get_nowait()
            except queue.Empty:
                break
            self._subagent_refresh_inflight = False
            if kind == "ok":
                selected_ip, found, detail_payload = payload
                if detail_payload:
                    agent_ip, detail_data = detail_payload
                    self._remote_detail_cache[str(agent_ip)] = detail_data
                self._subagent_refresh_errors = 0
                self._apply_subagent_refresh_result(selected_ip, found)
            elif kind == "error":
                self._subagent_refresh_errors += 1
                if self._subagent_refresh_errors <= 1:
                    self._append_log(f"[ui] refresh subagents failed: {payload}", level="WARN", category="ui")

        latest_lines: "deque[tuple[str, str, str]]" = deque(maxlen=8)
        while True:
            try:
                kind, payload = self._log_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                level = self._infer_level(payload)
                category = self._infer_category(payload)
                latest_lines.append((payload, level, category))
                if self._should_parse_runtime_line(payload):
                    self._parse_runtime_log(payload)
            elif kind == "resp_ok":
                self._record_resp_ok(payload)
            elif kind == "exit":
                self._handle_agent_exit(int(payload))
        if self._proc is not None and self._proc.poll() is not None:
            code = self._proc.poll()
            self._handle_agent_exit(int(code))

        for payload, level, category in latest_lines:
            self._append_log(payload, level=level, category=category)

    def _infer_level(self, line: str) -> str:
        text = line.upper()
        if " ERROR " in text or "[ERROR]" in text or "[FATAL]" in text:
            return "ERROR"
        if " WARN " in text or "[WARN]" in text:
            return "WARN"
        return "INFO"

    def _infer_category(self, line: str) -> str:
        match = LOG_RE.match(line.strip())
        if match:
            return str(match.group("category") or "general").lower()
        return "general"

    def _parse_runtime_log(self, line: str) -> None:
        raw = line.strip()
        match = LOG_RE.match(raw)
        if not match:
            return

        category = str(match.group("category") or "general").lower()
        line_id = int(match.group("line_id")) if match.group("line_id") else None
        line_name = match.group("line_name") or ""
        port = str(match.group("port") or "").lower()
        message = match.group("message") or ""
        nowt = time.monotonic()

        if line_id is not None:
            line_state = self._line_status.setdefault(
                line_id,
                _new_line_runtime_state(line_id, line_name or f"Line-{line_id}"),
            )
            if line_name:
                line_state["name"] = line_name

        status_payload = _parse_status_payload(message)
        if category == "redis" or "[Redis]" in message or status_payload is not None:
            if status_payload:
                self.redis_state = str(status_payload.get("redis", self.redis_state)).lower()
                if line_id is not None:
                    state = self._line_status[line_id]
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
                    ports_state = _split_pair_text(status_payload.get("ports"), "unknown")
                    if state["head_port"] == "unknown":
                        state["head_port"] = ports_state[0].lower()
                    if state["tail_port"] == "unknown":
                        state["tail_port"] = ports_state[1].lower()
            elif STATUS_RE.search(message):
                status_match = STATUS_RE.search(message)
                self.redis_state = status_match.group(1).lower()
                if line_id is not None:
                    state = self._line_status[line_id]
                    state["head_port"] = status_match.group(2).lower()
                    state["tail_port"] = status_match.group(3).lower()
                    state["port"] = f"{state['head_port']}/{state['tail_port']}"
            elif "pause until redis recovers" in message.lower() or "down" in message.lower():
                self.redis_state = "断开"
            elif "connected" in message.lower() or "ready" in message.lower():
                self.redis_state = "正常"

        if line_id is not None:
            state = self._line_status[line_id]
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
            self._recent_runtime_events.append(raw)
        self._runtime_view_dirty = True

    def _refresh_runtime_summary(self) -> None:
        for state in self._line_status.values():
            pair_summary = _summarize_link_pair(state.get("link_pair", state.get("link", "unknown")), state.get("link", "unknown"))
            state["link"] = "unknown" if pair_summary in ("unknown", "-", "") else pair_summary
        if self._runtime_view_dirty:
            self._refresh_overview()
            self._runtime_view_dirty = False
        self._update_alarm_state()
        self._update_static_labels()

    def _refresh_overview(self) -> None:
        is_local_target = self._selected_subagent_ip in (None, LOCAL_AGENT_KEY)
        if is_local_target:
            rows = [(line_id, state) for line_id, state in sorted(self._line_status.items())]
            detail_rows = rows
            detail_events: list[Any] = list(self._recent_runtime_events)
        else:
            info = self._subagent_status_by_ip.get(self._selected_subagent_ip or "", {})
            lines_summary = info.get("lines_summary") or []
            if not isinstance(lines_summary, list):
                lines_summary = []
            rows = [(int(item.get("line_id", idx + 1)), item) for idx, item in enumerate(lines_summary)]
            detail_snapshot = self._remote_detail_cache.get(self._selected_subagent_ip or "", {})
            detail_lines = detail_snapshot.get("lines_summary") if isinstance(detail_snapshot, dict) else []
            if isinstance(detail_lines, list) and detail_lines:
                detail_rows = [(int(item.get("line_id", idx + 1)), item) for idx, item in enumerate(detail_lines)]
            else:
                detail_rows = rows
            detail_events = detail_snapshot.get("recent_events") if isinstance(detail_snapshot, dict) else []
            if not isinstance(detail_events, list):
                detail_events = []

        self.overview_table.setRowCount(len(rows))
        nowt = time.monotonic()
        for row_idx, (line_id, state) in enumerate(rows):
            values = [
                str(line_id),
                str(state.get("name", f"Line-{line_id}")),
                str(state.get("head_port", _split_pair_text(state.get("port"), "unknown")[0])),
                str(state.get("tail_port", _split_pair_text(state.get("port"), "unknown")[1])),
                str(state.get("link", "unknown")),
                str(state.get("last_ok", _age_text(state.get("last_ok_mono", 0.0), nowt))),
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
        detail_text = self._build_overview_detail_text(detail_rows, nowt, is_local_target, detail_events)
        if detail_text != self._overview_detail_text_cache:
            self.overview_detail_text.setPlainText(detail_text)
            self._overview_detail_text_cache = detail_text

    def _build_overview_detail_text(
        self,
        rows: list[tuple[int, dict[str, Any]]],
        nowt: float,
        is_local_target: bool,
        detail_events: list[Any],
    ) -> str:
        if not rows:
            return "暂无线路状态"

        headers = [
            ("ID", 4),
            ("名称", 12),
            ("Pref(H/T)", 10),
            ("端口(H/T)", 14),
            ("通信状态(H/T)", 16),
            ("DownFor(H/T)", 14),
            ("设备", 6),
            ("A1超时", 12),
            ("A2超时", 12),
            ("命令超时", 12),
            ("Unmatch", 12),
            ("QFull(H/T)", 12),
            ("Queue(H/T)", 12),
            ("最近成功", 10),
        ]

        def fmt(cells: list[str]) -> str:
            parts = []
            for (title, width), cell in zip(headers, cells):
                text = str(cell)
                if len(text) > width:
                    text = text[: max(1, width - 1)] + "…"
                parts.append(text.ljust(width))
            return " ".join(parts).rstrip()

        lines = [fmt([title for title, _width in headers]), "-" * 160]
        for line_id, state in rows:
            cells = [
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
            lines.append(fmt(cells))

        lines.append("")
        lines.append("Recent events")
        lines.append("-" * 100)
        if is_local_target:
            events = list(self._recent_runtime_events)
            if events:
                lines.extend(events[-10:])
            else:
                lines.append("暂无事件")
        else:
            if detail_events:
                lines.extend(str(item) for item in detail_events[-10:])
            else:
                lines.append("等待分机详情...")
        return "\n".join(lines)
    # -------------------------
    # Alarm sound
    # -------------------------
    def _on_sound_toggle(self, checked: bool) -> None:
        self.sound_enabled = bool(checked)
        if not self.sound_enabled:
            self._alarm_paused_until_clear = False
        self._alarm_player.set_enabled(self.sound_enabled)
        self._update_alarm_state()
        self._update_static_labels()

    def _on_auto_start_toggle(self, checked: bool) -> None:
        self.auto_start = bool(checked)

    def _build_alarm_speech_text(self) -> str:
        if self._active_port_alerts:
            return "半自动闭塞站间安全传输系统串口故障"
        if _redis_alarm_active(self.redis_state):
            return "半自动闭塞站间安全传输系统Redis通信故障"
        if self._active_disk_alerts:
            return "半自动闭塞站间安全传输系统磁盘空间告警"
        return ""

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
            self._stop_alarm_sound()
            return
        if alarm_active and self._alarm_paused_until_clear:
            self.alarm_state = "已暂停"
            self._alarm_player.set_message("")
            self._alarm_player.set_audio_file(ALARM_WAV_PATH)
            self._stop_alarm_sound()
            return
        if alarm_active:
            self.alarm_state = "告警中"
            self._alarm_player.set_audio_file(ALARM_WAV_PATH if (port_alarm_active or redis_alarm_active) else DISK_ALARM_WAV_PATH)
            self._alarm_player.set_message(self._build_alarm_speech_text())
            self._start_alarm_sound()
            return
        self.alarm_state = "正常"
        self._alarm_player.set_message("")
        self._alarm_player.set_audio_file(ALARM_WAV_PATH)
        self._stop_alarm_sound()

    def _start_alarm_sound(self) -> None:
        if self._sound_loop_active:
            return
        self._sound_loop_active = True
        self._alarm_player.set_active(True)

    def _stop_alarm_sound(self) -> None:
        self._alarm_player.set_active(False)
        self._sound_loop_active = False

    def _pause_alarm_sound(self) -> None:
        self._alarm_paused_until_clear = True
        self._stop_alarm_sound()
        self._update_alarm_state()
        self._update_static_labels()

    # -------------------------
    # Child process
    # -------------------------
    def _build_runtime_config(self) -> dict:
        config = copy.deepcopy(self.local_config)
        config.setdefault("ui", {})
        config["ui"]["mode"] = "plain"
        config.setdefault("debug_tuning", {})
        config["debug_tuning"]["STATUS_PRINT_EVERY_SEC"] = 1.0
        return config

    def _write_runtime_config(self) -> Path:
        runtime_config = self._build_runtime_config()
        write_json_file(RUNTIME_CONFIG_PATH, runtime_config)
        self.runtime_config_label.setText(str(RUNTIME_CONFIG_PATH))
        return RUNTIME_CONFIG_PATH

    def start_agent(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if not self.save_settings():
            return False

        runtime_path = self._write_runtime_config()
        env = os.environ.copy()
        env[CONFIG_JSON_ENV] = str(runtime_path)

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
            self._proc = None
            self._show_error("启动失败", str(exc))
            return False

        self._manual_stop_requested = False
        self._unexpected_restart_pending = False
        self._drop_runtime_lines = False
        self.process_state = "运行中"
        self._reset_runtime_state()
        self._append_log(f"[ui] started sy_agent pid={self._proc.pid}", level="INFO", category="ui")
        self._reader_thread = threading.Thread(target=self._read_child_output, name="sy-ui-agent-log-reader", daemon=True)
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
                    self._log_queue.put(
                        (
                            "resp_ok",
                            {
                                "line_id": int(match.group("line_id")) if match.group("line_id") else None,
                                "line_name": match.group("line_name") or "",
                                "nowt": time.monotonic(),
                            },
                        )
                    )
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
        self._append_log("[ui] stopping sy_agent...", level="WARN", category="ui")
        self._drop_runtime_lines = True
        dropped = self._discard_pending_runtime_events()
        if dropped:
            self._append_log(f"[ui] cleared {dropped} queued runtime log events", level="WARN", category="ui")
        self.process_state = "停止中"
        self._stop_alarm_sound()
        self._update_static_labels()
        self._stop_thread = threading.Thread(
            target=self._stop_process_worker,
            args=(proc,),
            name="sy-ui-agent-stop-worker",
            daemon=True,
        )
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
                return
            except Exception:
                pass

            try:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except Exception:
                pass

            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
        finally:
            self._stop_thread = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._settings_locked:
            event.ignore()
            self._append_log("[ui] close ignored because settings are locked", level="INFO", category="ui")
            return
        try:
            self._stash_current_target_draft()
            self.sound_enabled = self.sound_checkbox.isChecked()
            self.auto_start = self.auto_start_checkbox.isChecked()
            self.disk_alert_config = self._pull_disk_alert_from_ui()
            if self._selected_subagent_ip in (None, LOCAL_AGENT_KEY):
                self.local_disk_alert_config = normalize_disk_alert_config(self.disk_alert_config)
            self.store.save(
                config=self.local_config,
                disk_alert=self.local_disk_alert_config,
                sound_enabled=self.sound_enabled,
                auto_start=self.auto_start,
                settings_locked=self._settings_locked,
                was_running=(self._proc is not None and self._proc.poll() is None),
                applied_at=self.local_applied_at,
                window_geometry=_encode_geometry(self.saveGeometry()),
            )
        except Exception:
            pass
        self._unexpected_restart_pending = False
        self.stop_agent()
        if self._stop_thread is not None:
            self._stop_thread.join(timeout=6.0)
        if self._subagent_refresh_thread is not None:
            self._subagent_refresh_thread.join(timeout=2.0)
        self._alarm_player.stop()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    lock, error = acquire_single_instance_lock(lock_path("sy_agent", "sy_agent_ui.lock"), "SY串口通信总控程序")
    if error:
        QMessageBox.warning(None, "无法启动", error)
        return 1
    window = SyUIAgentWindow()
    window._single_instance_lock = lock
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
