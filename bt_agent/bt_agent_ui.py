#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import copy
import html
import importlib.util
import json
import os
import pprint
import queue
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import wave
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QByteArray, QLockFile, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QCloseEvent, QIntValidator, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
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
CONFIG_JSON_PATH = agent_config_path("bt_agent")
DB_PATH = sqlite_path("bt_agent", "bt_agent_ui.sqlite3")
RUNTIME_CONFIG_PATH = runtime_config_path("bt_agent", "runtime_config.json")
BT_AGENT_PATH = BASE_DIR / "bt_agent.py"
CONFIG_JSON_ENV = "BT_AGENT_CONFIG_JSON"
SETTINGS_LOCK_PASSWORD = "whbt"
UNEXPECTED_RESTART_DELAY_MS = 3000
DISK_CHECK_SEC = 30.0
DISK_THRESHOLD_OPTIONS = [5, 10, 15, 20, 25, 30]
STATUS_PREFIX = "[BT_STATUS] "

STATUS_LABEL_STYLES = {
    "good": "color: #166534; background: #dcfce7; border: 1px solid #86efac; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
    "bad": "color: #991b1b; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
    "warn": "color: #92400e; background: #fef3c7; border: 1px solid #fcd34d; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
    "neutral": "color: #374151; background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 6px; padding: 2px 8px; font-weight: 600;",
}

DEFAULT_TEMPLATE = {
    "udp": {
        "host": "0.0.0.0",
        "port": 38315,
    },
    "redis": {
        "host": "127.0.0.1",
        "port": 36379,
        "packet_stream_key": "stream:udp:packets",
        "cmd_stream_key": "stream:udp:cmd",
        "cmd_group": "udp-agent-cmd",
        "cmd_consumer": "udp-agent-cmd-0",
        "startup_retry_sec": 2.0,
    },
    "stream": {
        "block_ms": 2000,
        "count": 100,
        "packet_maxlen": 200000,
        "cmd_maxlen": 50000,
    },
    "filters": {
        "blocked_ips": [],
    },
}

TOP_STATUS_TOOLTIPS = {
    "进程": "bt_agent.py 子进程当前运行状态。手动停止会显示“已停止（手动）”，异常退出会显示退出码。",
    "通信质量": "综合判断结果，基于进程状态、UDP、Redis、命令线程、发送错误和设备在线情况得出。",
    "UDP": "本机 UDP 监听状态。监听中表示已成功绑定端口并持续收包。",
    "磁盘告警": "磁盘空间告警状态。仅反映 C/D 盘空间是否告警以及告警声音是否被静音。",
    "Redis": "bt_agent 到 Redis 的连接状态。断开时会影响报文写入和命令处理。",
    "最近问题": "当前最主要的一条异常或注意项，便于现场快速定位问题。",
    "运行配置": "UI 启动 bt_agent.py 时写出的临时运行配置文件路径。",
}

SUMMARY_TOOLTIPS = {
    "uptime_sec": "本次 bt_agent.py 进程启动后的连续运行时长。",
    "send_queue_depth": "待发送给设备的队列长度。大于 0 说明存在发送积压。",
    "valid_packets": "有效包：本次进程启动后累计收到、且同时通过帧头帧尾检查和校验和检查的 UDP 报文数。累计值，重启清零。",
    "malformed_packets": "坏帧：本次进程启动后累计收到的帧头或帧尾不正确的报文数。不包含校验和错误，校验和错误单独记在“校验错”。",
    "checksum_errors": "本次进程启动后累计收到的校验和错误报文数。",
    "blocked_packets": "源 IP 命中 filters.blocked_ips 后被直接丢弃的报文累计数。",
    "analog_packets": "本次进程启动后累计识别出的模拟量报文数量。",
    "cmd_received": "本次进程启动后从 Redis 命令流读取到的命令累计数。",
    "cmd_acked": "本次进程启动后已成功处理并写回应答的命令累计数。",
    "send_ok": "本次进程启动后向设备发送成功的累计次数。",
    "send_errors": "本次进程启动后向设备发送失败的累计次数。",
    "redis_publish_errors": "本次进程启动后写入 Redis Stream 失败的累计次数。",
    "last_packet_at": "最近一次收到有效 UDP 报文的时间。",
    "last_send_at": "最近一次向设备发送数据的时间。",
}

IP_TABLE_TOOLTIPS = [
    "设备源 IP 地址。按收到过任意报文的来源自动发现，包括有效包、坏帧和校验错报文。",
    "优先按最近有效包时间判定在线状态；如果该 IP 只有坏帧或校验错而没有有效包，会显示为“异常”。",
    "距离该 IP 最近一次收到任意报文已经过去多久。包括有效包、坏帧和校验错报文。",
    "最近 10 秒内该 IP 有效报文的平均速率。",
    "有效包：该 IP 本次进程启动后累计收到、且同时通过帧头帧尾检查和校验和检查的报文数。累计值，重启清零。",
    "坏帧：该 IP 本次进程启动后累计收到的帧头或帧尾不正确的报文数。不包含校验和错误。",
    "本次进程启动后该 IP 累计校验和错误数量。",
    "本次进程启动后向该 IP 发送成功的累计次数。",
    "本次进程启动后向该 IP 发送失败的累计次数。",
]

FORM_TOOLTIPS = {
    "监听地址": "本机 UDP 绑定地址。填 0.0.0.0 表示监听所有网卡。",
    "监听端口": "本机 UDP 监听端口，设备报文需要发到这里。",
    "Redis主机": "Redis 服务地址。bt_agent 会把报文和命令处理结果写到这里。",
    "Redis端口": "Redis 服务端口。",
    "Packet Stream": "原始报文写入的 Redis Stream key。",
    "CMD Stream": "控制命令读取的 Redis Stream key。",
    "CMD Group": "Redis Stream 消费组名称，用于命令消费。",
    "CMD Consumer": "Redis Stream 消费者名称，用于区分不同实例。",
    "启动重试(秒)": "启动阶段连接 Redis 失败后的重试间隔。",
    "阻塞毫秒": "从 Redis Stream 读取命令时的阻塞等待时长。",
    "读取条数": "单次从 Redis Stream 最多读取的消息条数。",
    "Packet Maxlen": "写入 Packet Stream 时单条报文允许的最大长度。",
    "CMD Maxlen": "命令或应答报文允许的最大长度。",
}

DISK_TOOLTIPS = {
    "C盘": "是否监控 C 盘剩余空间。低于阈值时触发磁盘告警。",
    "D盘": "是否监控 D 盘剩余空间。低于阈值时触发磁盘告警。",
    "阈值": "磁盘剩余空间百分比阈值。剩余空间小于等于该值时进入告警。",
    "C盘用量": "当前 C 盘剩余空间百分比和剩余容量。",
    "D盘用量": "当前 D 盘剩余空间百分比和剩余容量。",
}

QUALITY_TOOLTIPS = {
    "注意阈值(秒)": "某个 IP 最近收包间隔超过该秒数后，状态变为“注意”。",
    "离线阈值(秒)": "某个 IP 最近收包间隔超过该秒数后，状态变为“离线”。必须大于注意阈值。",
}

BLOCKED_IP_TOOLTIPS = {
    "列表": "屏蔽 IP 列表。命中这些源 IP 的报文会被直接丢弃，不进入通信质量设备表。",
    "新增": "手工新增一个要屏蔽的 IPv4 地址。",
    "删除选中": "删除当前选中的屏蔽 IP。",
    "批量粘贴": "每行输入一个 IPv4 地址，自动去重并过滤非法值。",
}


def _first_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DISK_ALARM_WAV_PATH = _first_existing_path(
    ROOT_DIR / "sy_agent" / "assets" / "disk_space_alarm.wav",
    BASE_DIR / "sy_agent" / "assets" / "disk_space_alarm.wav",
    CURRENT_APP_DIR / "assets" / "disk_space_alarm.wav",
    CURRENT_APP_DIR / "sy_agent" / "assets" / "disk_space_alarm.wav",
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_py_config(path: Path) -> dict:
    spec = importlib.util.spec_from_file_location("bt_agent_ui_config", path)
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


def _normalize_blocked_ips(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return out
    for item in values:
        ip = str(item or "").strip()
        if not ip or ip in seen:
            continue
        try:
            socket.inet_aton(ip)
        except OSError:
            continue
        seen.add(ip)
        out.append(ip)
    return out


def normalize_config(raw_config: dict, template_config: dict) -> dict:
    if not isinstance(raw_config, dict):
        raise ValueError("config must be a JSON object")
    config = copy.deepcopy(template_config)
    _deep_merge(config, copy.deepcopy(raw_config))
    for key in ("udp", "redis", "stream", "filters"):
        if key not in config or not isinstance(config[key], dict):
            raise ValueError(f"config.{key} must be an object")
    config["udp"]["host"] = str(config["udp"].get("host", "0.0.0.0")).strip() or "0.0.0.0"
    config["udp"]["port"] = int(config["udp"].get("port", 38315))
    config["redis"]["host"] = str(config["redis"].get("host", "127.0.0.1")).strip() or "127.0.0.1"
    config["redis"]["port"] = int(config["redis"].get("port", 36379))
    config["redis"]["packet_stream_key"] = str(config["redis"].get("packet_stream_key", "stream:udp:packets")).strip() or "stream:udp:packets"
    config["redis"]["cmd_stream_key"] = str(config["redis"].get("cmd_stream_key", "stream:udp:cmd")).strip() or "stream:udp:cmd"
    config["redis"]["cmd_group"] = str(config["redis"].get("cmd_group", "udp-agent-cmd")).strip() or "udp-agent-cmd"
    config["redis"]["cmd_consumer"] = str(config["redis"].get("cmd_consumer", "udp-agent-cmd-0")).strip() or "udp-agent-cmd-0"
    config["redis"]["startup_retry_sec"] = float(config["redis"].get("startup_retry_sec", 2.0))
    config["stream"]["block_ms"] = int(config["stream"].get("block_ms", 2000))
    config["stream"]["count"] = int(config["stream"].get("count", 100))
    config["stream"]["packet_maxlen"] = int(config["stream"].get("packet_maxlen", 200000))
    config["stream"]["cmd_maxlen"] = int(config["stream"].get("cmd_maxlen", 50000))
    config["filters"]["blocked_ips"] = _normalize_blocked_ips(config["filters"].get("blocked_ips", []))
    return config


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


def default_quality_monitor_config() -> dict[str, Any]:
    return {
        "warn_after_sec": 10,
        "offline_after_sec": 30,
    }


def normalize_quality_monitor_config(raw: Any) -> dict[str, Any]:
    cfg = default_quality_monitor_config()
    if isinstance(raw, dict):
        try:
            warn_after = max(1, int(raw.get("warn_after_sec", cfg["warn_after_sec"])))
        except Exception:
            warn_after = cfg["warn_after_sec"]
        try:
            offline_after = max(warn_after + 1, int(raw.get("offline_after_sec", cfg["offline_after_sec"])))
        except Exception:
            offline_after = cfg["offline_after_sec"]
        cfg["warn_after_sec"] = warn_after
        cfg["offline_after_sec"] = max(warn_after + 1, offline_after)
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
            "enabled": enabled,
            "text": "未监控" if not enabled else "不可用",
            "free_pct": None,
        }
        if not enabled or not path.exists():
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
            item["text"] = f"剩余{free_pct:.1f}% ({usage.free / (1024 ** 3):.1f}/{usage.total / (1024 ** 3):.1f}GB)"
        out.append(item)
    return out


def acquire_single_instance_lock(lock_path: Path, app_name: str) -> tuple[Optional[QLockFile], Optional[str]]:
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(30000)
    if lock.tryLock(100):
        return lock, None
    return None, f"{app_name} 已在运行，请勿重复启动。"


def _encode_geometry(data: QByteArray) -> str:
    return bytes(data.toBase64()).decode("ascii")


def _decode_geometry(text: str) -> QByteArray:
    if not text:
        return QByteArray()
    return QByteArray.fromBase64(text.encode("ascii"))


def _status_kind_from_text(text: str) -> str:
    value = str(text or "").strip().lower()
    if any(token in value for token in ("运行", "在线", "正常", "good", "ok", "监听", "healthy")):
        return "good"
    if any(token in value for token in ("注意", "warn", "yellow", "paused")):
        return "warn"
    if any(token in value for token in ("异常", "失败", "断开", "离线", "bad", "down", "error", "stopped", "已停止")):
        return "bad"
    return "neutral"


def _apply_status_style(label: QLabel, text: str, kind: Optional[str] = None) -> None:
    label.setText(text)
    label.setStyleSheet(STATUS_LABEL_STYLES.get(kind or _status_kind_from_text(text), STATUS_LABEL_STYLES["neutral"]))


def _plain_log_lines(lines: deque[str]) -> str:
    return "\n".join(lines)


def _age_text_from_timestamp(ts: Any) -> str:
    if not ts:
        return "-"
    try:
        delta = max(0.0, time.time() - float(ts))
    except Exception:
        return "-"
    if delta < 60:
        return f"{delta:.1f}s"
    if delta < 3600:
        return f"{delta / 60:.1f}m"
    return f"{delta / 3600:.1f}h"


def _format_ts(ts: Any) -> str:
    if not ts:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return "-"


def _dump_config_text(config: dict) -> str:
    body = pprint.pformat(config, width=120, sort_dicts=False)
    return f"CONFIG = {body}\n"


def _wav_duration_ms(path: Path, fallback_ms: int = 5000) -> int:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if frames > 0 and rate > 0:
                return max(1000, int((frames / rate) * 1000))
    except Exception:
        pass
    return fallback_ms


def _bind_tooltip(widget: QWidget, text: str) -> QWidget:
    widget.setToolTip(text)
    widget.setStatusTip(text)
    return widget


def _make_tooltip_label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    _bind_tooltip(label, tooltip)
    return label


def _add_tooltip_row(form: QFormLayout, title: str, field: QWidget, tooltip: str) -> None:
    _bind_tooltip(field, tooltip)
    form.addRow(_make_tooltip_label(title, tooltip), field)


class AlarmSoundPlayer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop_evt = threading.Event()
        self._wake_evt = threading.Event()
        self._lock = threading.Lock()
        self._enabled = True
        self._active = False
        self._message = ""
        self._audio_file = str(DISK_ALARM_WAV_PATH)
        self._proc: Optional[subprocess.Popen[Any]] = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
        self._wake_evt.set()

    def set_active(self, active: bool) -> None:
        with self._lock:
            self._active = bool(active)
        if not active and winsound is not None and sys.platform.startswith("win"):
            try:
                winsound.PlaySound(None, 0)
            except Exception:
                pass
        self._wake_evt.set()

    def set_message(self, message: str) -> None:
        with self._lock:
            self._message = str(message or "").strip()
        self._wake_evt.set()

    def stop(self) -> None:
        self._stop_evt.set()
        self._stop_playback()
        self._wake_evt.set()

    def _snapshot(self) -> tuple[bool, bool, str, str]:
        with self._lock:
            return self._enabled, self._active, self._message, self._audio_file

    def set_audio_file(self, path: Any) -> None:
        with self._lock:
            self._audio_file = str(path) if path else str(DISK_ALARM_WAV_PATH)
        self._wake_evt.set()

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
        wav_path = Path(audio_file) if audio_file else DISK_ALARM_WAV_PATH
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
                enabled, active, _message, current_audio = self._snapshot()
                if not enabled or not active or current_audio != str(wav_path):
                    self._stop_playback()
                    break
                time.sleep(0.1)
            self._proc = None
            return True

        return False

    def run(self) -> None:
        while not self._stop_evt.is_set():
            enabled, active, _message, audio_file = self._snapshot()
            if not enabled or not active:
                self._wake_evt.wait(0.2)
                self._wake_evt.clear()
                continue
            if not self._play_wav_once(audio_file):
                QApplication.beep()
            deadline = time.time() + 3.0
            while time.time() < deadline and not self._stop_evt.is_set():
                self._wake_evt.wait(0.2)
                self._wake_evt.clear()
                enabled, active, _message, _audio_file = self._snapshot()
                if not enabled or not active:
                    break


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


class IPv4SegmentEdit(QLineEdit):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._next_segment: Optional["IPv4SegmentEdit"] = None
        self._prev_segment: Optional["IPv4SegmentEdit"] = None
        self.setMaxLength(3)
        self.setAlignment(Qt.AlignCenter)
        self.setValidator(QIntValidator(0, 255, self))
        self.setPlaceholderText("0")
        self.setMinimumHeight(44)
        self.setMinimumWidth(76)
        self.setMaximumWidth(90)
        self.setStyleSheet(
            "QLineEdit { font-size: 22px; font-weight: 600; padding: 4px 8px; }"
        )
        self.textEdited.connect(self._on_text_edited)

    def set_neighbors(
        self,
        prev_segment: Optional["IPv4SegmentEdit"],
        next_segment: Optional["IPv4SegmentEdit"],
    ) -> None:
        self._prev_segment = prev_segment
        self._next_segment = next_segment

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.selectAll()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Period):
            self._focus_next()
            return
        if event.key() == Qt.Key_Backspace and not self.text() and self._prev_segment is not None:
            self._prev_segment.setFocus()
            self._prev_segment.selectAll()
            return
        super().keyPressEvent(event)

    def _on_text_edited(self, text: str) -> None:
        if len(text) >= 3 and self.hasAcceptableInput():
            self._focus_next()

    def _focus_next(self) -> None:
        if self._next_segment is not None:
            self._next_segment.setFocus()
            self._next_segment.selectAll()


class IPv4InputDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("新增屏蔽 IP")
        self.setModal(True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        prompt = QLabel("请输入 IPv4 地址")
        prompt.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(prompt)

        segment_row = QHBoxLayout()
        segment_row.setSpacing(8)
        self._segments: list[IPv4SegmentEdit] = []
        for index in range(4):
            segment = IPv4SegmentEdit(self)
            self._segments.append(segment)
            segment_row.addWidget(segment)
            if index < 3:
                dot = QLabel(".")
                dot.setAlignment(Qt.AlignCenter)
                dot.setStyleSheet("font-size: 24px; font-weight: 700;")
                segment_row.addWidget(dot)
        segment_row.addStretch(1)
        root.addLayout(segment_row)

        for index, segment in enumerate(self._segments):
            prev_segment = self._segments[index - 1] if index > 0 else None
            next_segment = self._segments[index + 1] if index < len(self._segments) - 1 else None
            segment.set_neighbors(prev_segment, next_segment)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        ok_button = QPushButton("确定")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(ok_button)
        root.addLayout(button_row)

        if self._segments:
            self._segments[0].setFocus()

    def ip_text(self) -> str:
        return ".".join((segment.text().strip() or "0") for segment in self._segments)


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
                    quality_monitor_json TEXT NOT NULL DEFAULT '{}',
                    sound_enabled INTEGER NOT NULL,
                    auto_start INTEGER NOT NULL,
                    settings_locked INTEGER NOT NULL DEFAULT 0,
                    was_running INTEGER NOT NULL DEFAULT 0,
                    window_geometry TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
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
                    "quality_monitor": normalize_quality_monitor_config(json.loads(row["quality_monitor_json"] or "{}")),
                    "sound_enabled": bool(row["sound_enabled"]),
                    "auto_start": bool(row["auto_start"]),
                    "settings_locked": bool(row["settings_locked"]),
                    "was_running": bool(row["was_running"]),
                    "window_geometry": row["window_geometry"] or "",
                }

        state = {
            "config": normalize_config(copy.deepcopy(template_config), template_config),
            "disk_alert": default_disk_alert_config(),
            "quality_monitor": default_quality_monitor_config(),
            "sound_enabled": True,
            "auto_start": False,
            "settings_locked": False,
            "was_running": False,
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
            quality_monitor=state["quality_monitor"],
            sound_enabled=state["sound_enabled"],
            auto_start=state["auto_start"],
            settings_locked=state["settings_locked"],
            was_running=state["was_running"],
            window_geometry=state["window_geometry"],
        )
        return state

    def save(
        self,
        *,
        config: dict,
        disk_alert: dict,
        quality_monitor: dict,
        sound_enabled: bool,
        auto_start: bool,
        settings_locked: bool,
        was_running: bool,
        window_geometry: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(
                    id, config_json, disk_alert_json, quality_monitor_json, sound_enabled,
                    auto_start, settings_locked, was_running, window_geometry, updated_at
                ) VALUES (
                    1, :config_json, :disk_alert_json, :quality_monitor_json, :sound_enabled,
                    :auto_start, :settings_locked, :was_running, :window_geometry, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    config_json=excluded.config_json,
                    disk_alert_json=excluded.disk_alert_json,
                    quality_monitor_json=excluded.quality_monitor_json,
                    sound_enabled=excluded.sound_enabled,
                    auto_start=excluded.auto_start,
                    settings_locked=excluded.settings_locked,
                    was_running=excluded.was_running,
                    window_geometry=excluded.window_geometry,
                    updated_at=excluded.updated_at
                """,
                {
                    "config_json": json.dumps(normalize_config(config, DEFAULT_TEMPLATE), ensure_ascii=False, indent=2),
                    "disk_alert_json": json.dumps(normalize_disk_alert_config(disk_alert), ensure_ascii=False, indent=2),
                    "quality_monitor_json": json.dumps(normalize_quality_monitor_config(quality_monitor), ensure_ascii=False, indent=2),
                    "sound_enabled": 1 if sound_enabled else 0,
                    "auto_start": 1 if auto_start else 0,
                    "settings_locked": 1 if settings_locked else 0,
                    "was_running": 1 if was_running else 0,
                    "window_geometry": window_geometry or "",
                    "updated_at": _now_iso(),
                },
            )
            conn.commit()


class BtAgentUIWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CXG-bt设备网管通信控制程序")
        self.resize(1260, 860)
        self.setMinimumSize(1080, 760)

        self.template_config = normalize_config(copy.deepcopy(DEFAULT_TEMPLATE), DEFAULT_TEMPLATE)
        self.store = AppStateStore(DB_PATH)
        self.state_row = self.store.load_or_init(self.template_config)
        self.local_config = copy.deepcopy(self.state_row["config"])
        self.current_config = copy.deepcopy(self.local_config)
        self.disk_alert_config = normalize_disk_alert_config(self.state_row.get("disk_alert"))
        self.quality_monitor_config = normalize_quality_monitor_config(self.state_row.get("quality_monitor"))
        self.sound_enabled = bool(self.state_row["sound_enabled"])
        self.auto_start = bool(self.state_row["auto_start"])
        self._settings_locked = bool(self.state_row["settings_locked"])
        self._restore_running = bool(self.state_row["was_running"])

        self.process_state = "已停止"
        self.udp_state = "未知"
        self.redis_state = "未知"
        self.quality_state = "未知"
        self.alarm_state = "静默"
        self.last_issue_text = "-"
        self._active_disk_alerts: list[str] = []
        self._alarm_paused_until_clear = False

        self.host_status: dict[str, Any] = {
            "udp_socket_ok": False,
            "redis_ok": False,
            "cmd_thread_alive": False,
            "send_queue_depth": 0,
            "uptime_sec": 0.0,
            "valid_packets": 0,
            "malformed_packets": 0,
            "checksum_errors": 0,
            "blocked_packets": 0,
            "analog_packets": 0,
            "redis_publish_errors": 0,
            "cmd_received": 0,
            "cmd_acked": 0,
            "send_ok": 0,
            "send_errors": 0,
            "last_packet_at": None,
            "last_send_at": None,
        }
        self.ip_status_by_ip: dict[str, dict[str, Any]] = {}
        self._recent_status_ts: Optional[str] = None

        self._log_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._log_lines: "deque[str]" = deque(maxlen=500)
        self._visible_log_lines: "deque[str]" = deque(maxlen=300)
        self._log_dirty = False
        self._syncing_ui = False
        self._proc: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._manual_stop_requested = False
        self._unexpected_restart_pending = False
        self._settings_lock_targets: list[QWidget] = []

        self._alarm_player = AlarmSoundPlayer()
        self._alarm_player.start()
        self._alarm_test_active = False

        self._build_ui()
        self._load_config_into_ui()
        self._load_disk_alert_into_ui()
        self._load_quality_into_ui()
        self._load_blocked_ips_into_ui()
        self._refresh_disk_usage_view()
        self._update_status_labels()
        self._apply_settings_lock_state()

        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._poll_log_queue)
        self._queue_timer.start(250)

        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.timeout.connect(self._flush_log_view)
        self._log_flush_timer.start(500)

        self._disk_timer = QTimer(self)
        self._disk_timer.timeout.connect(self._check_disk_alerts)
        self._disk_timer.start(int(DISK_CHECK_SEC * 1000))

        if self.state_row["window_geometry"]:
            geometry = _decode_geometry(self.state_row["window_geometry"])
            if not geometry.isEmpty():
                self.restoreGeometry(geometry)

        if self.auto_start or self._restore_running:
            QTimer.singleShot(500, self.start_agent)

    def _build_ui(self) -> None:
        content = QWidget(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.top_section = CollapsibleSection("控制", self._build_top_panel(), expanded=True, parent=self)
        self.overview_section = CollapsibleSection("通信质量概览", self._build_overview_panel(), expanded=True, parent=self)
        self.config_section = CollapsibleSection("配置与监控", self._build_config_tabs(), expanded=True, parent=self)
        self.log_section = CollapsibleSection("日志", self._build_log_panel(), expanded=True, parent=self)
        root.addWidget(self.top_section)
        root.addWidget(self.overview_section)
        root.addWidget(self.config_section)
        root.addWidget(self.log_section)
        root.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

    def _build_top_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        actions = QHBoxLayout()
        self.start_button = QPushButton("启动")
        self.start_button.clicked.connect(self._toggle_agent_process)
        self.save_button = QPushButton("保存设置")
        self.save_button.clicked.connect(self.save_settings)
        self.import_button = QPushButton("导入 JSON")
        self.import_button.clicked.connect(self.import_config_json)
        self.export_button = QPushButton("导出 JSON")
        self.export_button.clicked.connect(self.export_config_json)
        self.import_py_button = QPushButton("导入 .py(开发)")
        self.import_py_button.clicked.connect(self.import_config_py)
        self.export_py_button = QPushButton("导出 .py(开发)")
        self.export_py_button.clicked.connect(self.export_config_py)
        self.export_diag_button = QPushButton("导出诊断包")
        self.export_diag_button.clicked.connect(self.export_diagnostic_bundle)
        self.pause_alarm_button = QPushButton("暂停告警声")
        self.pause_alarm_button.clicked.connect(self._pause_alarm_sound)
        self.test_alarm_button = QPushButton("试音")
        self.test_alarm_button.clicked.connect(self._test_alarm_sound)
        self.sound_checkbox = QCheckBox("磁盘告警声音")
        self.sound_checkbox.toggled.connect(self._on_sound_toggled)
        self.auto_start_checkbox = QCheckBox("自动启动")
        self.auto_start_checkbox.toggled.connect(self._on_auto_start_toggled)
        self.lock_button = QPushButton("锁定")
        self.lock_button.clicked.connect(self._toggle_settings_lock)

        for widget in (
            self.start_button,
            self.save_button,
            self.import_button,
            self.export_button,
            self.import_py_button,
            self.export_py_button,
            self.export_diag_button,
            self.pause_alarm_button,
            self.test_alarm_button,
            self.sound_checkbox,
            self.auto_start_checkbox,
            self.lock_button,
        ):
            actions.addWidget(widget)
        actions.addStretch(1)
        layout.addLayout(actions)

        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(18)
        status_grid.setVerticalSpacing(8)
        self.process_value = QLabel("-")
        self.udp_value = QLabel("-")
        self.redis_value = QLabel("-")
        self.quality_value = QLabel("-")
        self.alarm_value = QLabel("-")
        self.issue_value = QLabel("-")
        self.runtime_config_label = QLabel(str(RUNTIME_CONFIG_PATH))
        self.runtime_config_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.runtime_config_label.setWordWrap(True)
        _bind_tooltip(self.process_value, TOP_STATUS_TOOLTIPS["进程"])
        _bind_tooltip(self.quality_value, TOP_STATUS_TOOLTIPS["通信质量"])
        _bind_tooltip(self.udp_value, TOP_STATUS_TOOLTIPS["UDP"])
        _bind_tooltip(self.alarm_value, TOP_STATUS_TOOLTIPS["磁盘告警"])
        _bind_tooltip(self.redis_value, TOP_STATUS_TOOLTIPS["Redis"])
        _bind_tooltip(self.issue_value, TOP_STATUS_TOOLTIPS["最近问题"])
        _bind_tooltip(self.runtime_config_label, TOP_STATUS_TOOLTIPS["运行配置"])
        for value_label in (
            self.process_value,
            self.udp_value,
            self.redis_value,
            self.quality_value,
            self.alarm_value,
            self.issue_value,
        ):
            value_label.setMinimumWidth(200)

        col1_form = QFormLayout()
        col1_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        col1_form.setFormAlignment(Qt.AlignTop)
        _add_tooltip_row(col1_form, "进程", self.process_value, TOP_STATUS_TOOLTIPS["进程"])
        _add_tooltip_row(col1_form, "通信质量", self.quality_value, TOP_STATUS_TOOLTIPS["通信质量"])

        col2_form = QFormLayout()
        col2_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        col2_form.setFormAlignment(Qt.AlignTop)
        _add_tooltip_row(col2_form, "UDP", self.udp_value, TOP_STATUS_TOOLTIPS["UDP"])
        _add_tooltip_row(col2_form, "磁盘告警", self.alarm_value, TOP_STATUS_TOOLTIPS["磁盘告警"])

        col3_form = QFormLayout()
        col3_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        col3_form.setFormAlignment(Qt.AlignTop)
        _add_tooltip_row(col3_form, "Redis", self.redis_value, TOP_STATUS_TOOLTIPS["Redis"])
        _add_tooltip_row(col3_form, "最近问题", self.issue_value, TOP_STATUS_TOOLTIPS["最近问题"])

        status_grid.addLayout(col1_form, 0, 0)
        status_grid.addLayout(col2_form, 0, 1)
        status_grid.addLayout(col3_form, 0, 2)
        status_grid.addWidget(_make_tooltip_label("运行配置", TOP_STATUS_TOOLTIPS["运行配置"]), 1, 0)
        status_grid.addWidget(self.runtime_config_label, 1, 1, 1, 2)
        status_grid.setColumnStretch(0, 1)
        status_grid.setColumnStretch(1, 1)
        status_grid.setColumnStretch(2, 1)
        layout.addLayout(status_grid)
        return panel

    def _toggle_agent_process(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self.stop_agent()
        else:
            self.start_agent()

    def _build_overview_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        summary = QGroupBox("主机状态")
        summary_layout = QGridLayout(summary)
        self.summary_labels: dict[str, QLabel] = {}
        summary_keys = [
            ("uptime_sec", "运行时长"),
            ("send_queue_depth", "发送队列"),
            ("valid_packets", "有效包"),
            ("malformed_packets", "坏帧"),
            ("checksum_errors", "校验错"),
            ("blocked_packets", "屏蔽包"),
            ("analog_packets", "模拟量包"),
            ("cmd_received", "命令接收"),
            ("cmd_acked", "命令应答"),
            ("send_ok", "发送成功"),
            ("send_errors", "发送失败"),
            ("redis_publish_errors", "Redis发布失败"),
            ("last_packet_at", "最近收包"),
            ("last_send_at", "最近发送"),
        ]
        for idx, (key, title) in enumerate(summary_keys):
            row = idx // 4
            col = (idx % 4) * 2
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            tooltip = SUMMARY_TOOLTIPS.get(key, title)
            _bind_tooltip(value, tooltip)
            summary_layout.addWidget(_make_tooltip_label(title, tooltip), row, col)
            summary_layout.addWidget(value, row, col + 1)
            self.summary_labels[key] = value
        layout.addWidget(summary)

        self.ip_table = QTableWidget(self)
        self.ip_table.setColumnCount(9)
        self.ip_table.setHorizontalHeaderLabels(["IP", "状态", "最近收包", "速率", "有效包", "坏帧", "校验错", "发送成功", "发送失败"])
        for index, tooltip in enumerate(IP_TABLE_TOOLTIPS):
            header_item = self.ip_table.horizontalHeaderItem(index)
            if header_item is not None:
                header_item.setToolTip(tooltip)
        self.ip_table.verticalHeader().setVisible(False)
        self.ip_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.ip_table.setEditTriggers(QTableWidget.NoEditTriggers)
        _bind_tooltip(self.ip_table, "设备通信质量表。鼠标悬浮到表头可查看各列含义。")
        layout.addWidget(self.ip_table)
        return panel

    def _build_config_tabs(self) -> QWidget:
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_json_tab(), "配置JSON")
        self.tabs.addTab(self._build_form_tab(), "基础参数")
        self.tabs.addTab(self._build_blocked_ips_tab(), "屏蔽IP")
        self.tabs.addTab(self._build_disk_tab(), "磁盘告警")
        self.tabs.addTab(self._build_quality_tab(), "通信质量规则")
        return self.tabs

    def _build_json_tab(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        self.config_editor = QPlainTextEdit(self)
        self.config_editor.textChanged.connect(self._on_config_editor_changed)
        layout.addWidget(self.config_editor)
        return panel

    def _build_form_tab(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        udp_box = QGroupBox("UDP")
        udp_form = QFormLayout(udp_box)
        self.udp_host_input = QLineEdit(self)
        self.udp_host_input.textChanged.connect(self._on_form_changed)
        self.udp_port_input = QSpinBox(self)
        self.udp_port_input.setRange(1, 65535)
        self.udp_port_input.valueChanged.connect(self._on_form_changed)
        _add_tooltip_row(udp_form, "监听地址", self.udp_host_input, FORM_TOOLTIPS["监听地址"])
        _add_tooltip_row(udp_form, "监听端口", self.udp_port_input, FORM_TOOLTIPS["监听端口"])

        redis_box = QGroupBox("Redis")
        redis_form = QFormLayout(redis_box)
        self.redis_host_input = QLineEdit(self)
        self.redis_host_input.textChanged.connect(self._on_form_changed)
        self.redis_port_input = QSpinBox(self)
        self.redis_port_input.setRange(1, 65535)
        self.redis_port_input.valueChanged.connect(self._on_form_changed)
        self.packet_stream_input = QLineEdit(self)
        self.packet_stream_input.textChanged.connect(self._on_form_changed)
        self.cmd_stream_input = QLineEdit(self)
        self.cmd_stream_input.textChanged.connect(self._on_form_changed)
        self.cmd_group_input = QLineEdit(self)
        self.cmd_group_input.textChanged.connect(self._on_form_changed)
        self.cmd_consumer_input = QLineEdit(self)
        self.cmd_consumer_input.textChanged.connect(self._on_form_changed)
        self.startup_retry_input = QSpinBox(self)
        self.startup_retry_input.setRange(1, 600)
        self.startup_retry_input.valueChanged.connect(self._on_form_changed)
        _add_tooltip_row(redis_form, "Redis主机", self.redis_host_input, FORM_TOOLTIPS["Redis主机"])
        _add_tooltip_row(redis_form, "Redis端口", self.redis_port_input, FORM_TOOLTIPS["Redis端口"])
        _add_tooltip_row(redis_form, "Packet Stream", self.packet_stream_input, FORM_TOOLTIPS["Packet Stream"])
        _add_tooltip_row(redis_form, "CMD Stream", self.cmd_stream_input, FORM_TOOLTIPS["CMD Stream"])
        _add_tooltip_row(redis_form, "CMD Group", self.cmd_group_input, FORM_TOOLTIPS["CMD Group"])
        _add_tooltip_row(redis_form, "CMD Consumer", self.cmd_consumer_input, FORM_TOOLTIPS["CMD Consumer"])
        _add_tooltip_row(redis_form, "启动重试(秒)", self.startup_retry_input, FORM_TOOLTIPS["启动重试(秒)"])

        stream_box = QGroupBox("Stream")
        stream_form = QFormLayout(stream_box)
        self.stream_block_ms_input = QSpinBox(self)
        self.stream_block_ms_input.setRange(100, 60000)
        self.stream_block_ms_input.valueChanged.connect(self._on_form_changed)
        self.stream_count_input = QSpinBox(self)
        self.stream_count_input.setRange(1, 10000)
        self.stream_count_input.valueChanged.connect(self._on_form_changed)
        self.packet_maxlen_input = QSpinBox(self)
        self.packet_maxlen_input.setRange(1000, 10000000)
        self.packet_maxlen_input.valueChanged.connect(self._on_form_changed)
        self.cmd_maxlen_input = QSpinBox(self)
        self.cmd_maxlen_input.setRange(1000, 10000000)
        self.cmd_maxlen_input.valueChanged.connect(self._on_form_changed)
        _add_tooltip_row(stream_form, "阻塞毫秒", self.stream_block_ms_input, FORM_TOOLTIPS["阻塞毫秒"])
        _add_tooltip_row(stream_form, "读取条数", self.stream_count_input, FORM_TOOLTIPS["读取条数"])
        _add_tooltip_row(stream_form, "Packet Maxlen", self.packet_maxlen_input, FORM_TOOLTIPS["Packet Maxlen"])
        _add_tooltip_row(stream_form, "CMD Maxlen", self.cmd_maxlen_input, FORM_TOOLTIPS["CMD Maxlen"])

        layout.addWidget(udp_box)
        layout.addWidget(redis_box)
        layout.addWidget(stream_box)
        layout.addStretch(1)
        return panel

    def _build_blocked_ips_tab(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        controls = QHBoxLayout()
        self.blocked_list = QListWidget(self)
        self.add_blocked_button = QPushButton("新增")
        self.add_blocked_button.clicked.connect(self._add_blocked_ip)
        self.delete_blocked_button = QPushButton("删除选中")
        self.delete_blocked_button.clicked.connect(self._delete_selected_blocked_ips)
        self.paste_blocked_button = QPushButton("批量粘贴")
        self.paste_blocked_button.clicked.connect(self._paste_blocked_ips)
        _bind_tooltip(self.blocked_list, BLOCKED_IP_TOOLTIPS["列表"])
        _bind_tooltip(self.add_blocked_button, BLOCKED_IP_TOOLTIPS["新增"])
        _bind_tooltip(self.delete_blocked_button, BLOCKED_IP_TOOLTIPS["删除选中"])
        _bind_tooltip(self.paste_blocked_button, BLOCKED_IP_TOOLTIPS["批量粘贴"])
        for widget in (
            self.add_blocked_button,
            self.delete_blocked_button,
            self.paste_blocked_button,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)
        layout.addLayout(controls)
        layout.addWidget(self.blocked_list)
        return panel

    def _build_disk_tab(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        controls = QHBoxLayout()
        self.disk_c_checkbox = QCheckBox("C盘")
        self.disk_d_checkbox = QCheckBox("D盘")
        self.disk_threshold_combo = QComboBox(self)
        for value in DISK_THRESHOLD_OPTIONS:
            self.disk_threshold_combo.addItem(f"{value}%", value)
        self.disk_c_checkbox.toggled.connect(self._on_disk_alert_ui_changed)
        self.disk_d_checkbox.toggled.connect(self._on_disk_alert_ui_changed)
        self.disk_threshold_combo.currentIndexChanged.connect(self._on_disk_alert_ui_changed)
        _bind_tooltip(self.disk_c_checkbox, DISK_TOOLTIPS["C盘"])
        _bind_tooltip(self.disk_d_checkbox, DISK_TOOLTIPS["D盘"])
        _bind_tooltip(self.disk_threshold_combo, DISK_TOOLTIPS["阈值"])
        controls.addWidget(self.disk_c_checkbox)
        controls.addWidget(self.disk_d_checkbox)
        controls.addWidget(_make_tooltip_label("阈值", DISK_TOOLTIPS["阈值"]))
        controls.addWidget(self.disk_threshold_combo)
        controls.addStretch(1)
        layout.addLayout(controls)

        usage_form = QFormLayout()
        self.disk_usage_c_value = QLabel("-")
        self.disk_usage_d_value = QLabel("-")
        _add_tooltip_row(usage_form, "C盘", self.disk_usage_c_value, DISK_TOOLTIPS["C盘用量"])
        _add_tooltip_row(usage_form, "D盘", self.disk_usage_d_value, DISK_TOOLTIPS["D盘用量"])
        layout.addLayout(usage_form)
        layout.addStretch(1)
        return panel

    def _build_quality_tab(self) -> QWidget:
        panel = QWidget(self)
        layout = QFormLayout(panel)
        self.warn_after_input = QSpinBox(self)
        self.warn_after_input.setRange(1, 3600)
        self.warn_after_input.valueChanged.connect(self._on_quality_ui_changed)
        self.offline_after_input = QSpinBox(self)
        self.offline_after_input.setRange(2, 7200)
        self.offline_after_input.valueChanged.connect(self._on_quality_ui_changed)
        _add_tooltip_row(layout, "注意阈值(秒)", self.warn_after_input, QUALITY_TOOLTIPS["注意阈值(秒)"])
        _add_tooltip_row(layout, "离线阈值(秒)", self.offline_after_input, QUALITY_TOOLTIPS["离线阈值(秒)"])
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        return panel

    def _append_log(self, line: str) -> None:
        text = str(line or "").rstrip()
        if not text:
            return
        self._log_lines.append(text)
        self._visible_log_lines.append(text)
        self._log_dirty = True

    def _flush_log_view(self) -> None:
        if not self._log_dirty:
            return
        self.log_view.setPlainText(_plain_log_lines(self._visible_log_lines))
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(cursor)
        self._log_dirty = False

    def _build_current_config_from_form(self) -> dict:
        config = copy.deepcopy(self.current_config)
        config.setdefault("udp", {})
        config.setdefault("redis", {})
        config.setdefault("stream", {})
        config.setdefault("filters", {})
        config["udp"]["host"] = self.udp_host_input.text().strip() or "0.0.0.0"
        config["udp"]["port"] = int(self.udp_port_input.value())
        config["redis"]["host"] = self.redis_host_input.text().strip() or "127.0.0.1"
        config["redis"]["port"] = int(self.redis_port_input.value())
        config["redis"]["packet_stream_key"] = self.packet_stream_input.text().strip() or "stream:udp:packets"
        config["redis"]["cmd_stream_key"] = self.cmd_stream_input.text().strip() or "stream:udp:cmd"
        config["redis"]["cmd_group"] = self.cmd_group_input.text().strip() or "udp-agent-cmd"
        config["redis"]["cmd_consumer"] = self.cmd_consumer_input.text().strip() or "udp-agent-cmd-0"
        config["redis"]["startup_retry_sec"] = float(self.startup_retry_input.value())
        config["stream"]["block_ms"] = int(self.stream_block_ms_input.value())
        config["stream"]["count"] = int(self.stream_count_input.value())
        config["stream"]["packet_maxlen"] = int(self.packet_maxlen_input.value())
        config["stream"]["cmd_maxlen"] = int(self.cmd_maxlen_input.value())
        config["filters"]["blocked_ips"] = self._pull_blocked_ips_from_ui()
        return normalize_config(config, self.template_config)

    def _refresh_config_editor(self) -> None:
        self._syncing_ui = True
        self.config_editor.setPlainText(json.dumps(self.current_config, ensure_ascii=False, indent=2))
        self._syncing_ui = False

    def _load_config_into_ui(self) -> None:
        self._syncing_ui = True
        self.udp_host_input.setText(str(self.current_config["udp"]["host"]))
        self.udp_port_input.setValue(int(self.current_config["udp"]["port"]))
        self.redis_host_input.setText(str(self.current_config["redis"]["host"]))
        self.redis_port_input.setValue(int(self.current_config["redis"]["port"]))
        self.packet_stream_input.setText(str(self.current_config["redis"]["packet_stream_key"]))
        self.cmd_stream_input.setText(str(self.current_config["redis"]["cmd_stream_key"]))
        self.cmd_group_input.setText(str(self.current_config["redis"]["cmd_group"]))
        self.cmd_consumer_input.setText(str(self.current_config["redis"]["cmd_consumer"]))
        self.startup_retry_input.setValue(int(float(self.current_config["redis"]["startup_retry_sec"])))
        self.stream_block_ms_input.setValue(int(self.current_config["stream"]["block_ms"]))
        self.stream_count_input.setValue(int(self.current_config["stream"]["count"]))
        self.packet_maxlen_input.setValue(int(self.current_config["stream"]["packet_maxlen"]))
        self.cmd_maxlen_input.setValue(int(self.current_config["stream"]["cmd_maxlen"]))
        self.sound_checkbox.setChecked(self.sound_enabled)
        self.auto_start_checkbox.setChecked(self.auto_start)
        self._syncing_ui = False
        self._refresh_config_editor()

    def _load_blocked_ips_into_ui(self) -> None:
        self._syncing_ui = True
        self.blocked_list.clear()
        for ip in self.current_config["filters"]["blocked_ips"]:
            QListWidgetItem(ip, self.blocked_list)
        self._syncing_ui = False

    def _load_disk_alert_into_ui(self) -> None:
        self._syncing_ui = True
        self.disk_c_checkbox.setChecked(bool(self.disk_alert_config.get("c_enabled")))
        self.disk_d_checkbox.setChecked(bool(self.disk_alert_config.get("d_enabled")))
        idx = self.disk_threshold_combo.findData(int(self.disk_alert_config.get("threshold_percent", 10)))
        self.disk_threshold_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._syncing_ui = False

    def _load_quality_into_ui(self) -> None:
        self._syncing_ui = True
        self.warn_after_input.setValue(int(self.quality_monitor_config.get("warn_after_sec", 10)))
        self.offline_after_input.setValue(int(self.quality_monitor_config.get("offline_after_sec", 30)))
        self._syncing_ui = False

    def _pull_blocked_ips_from_ui(self) -> list[str]:
        values = [self.blocked_list.item(i).text() for i in range(self.blocked_list.count())]
        return _normalize_blocked_ips(values)

    def _on_form_changed(self) -> None:
        if self._syncing_ui:
            return
        self.current_config = self._build_current_config_from_form()
        self._refresh_config_editor()

    def _on_config_editor_changed(self) -> None:
        if self._syncing_ui:
            return
        # JSON 编辑器作为可选高级编辑入口，保存时再做校验和回填。
        pass

    def _on_disk_alert_ui_changed(self) -> None:
        if self._syncing_ui:
            return
        self.disk_alert_config = normalize_disk_alert_config(
            {
                "c_enabled": self.disk_c_checkbox.isChecked(),
                "d_enabled": self.disk_d_checkbox.isChecked(),
                "threshold_percent": int(self.disk_threshold_combo.currentData() or 10),
            }
        )
        self._refresh_disk_usage_view()
        self._check_disk_alerts()

    def _on_quality_ui_changed(self) -> None:
        if self._syncing_ui:
            return
        self.quality_monitor_config = normalize_quality_monitor_config(
            {
                "warn_after_sec": int(self.warn_after_input.value()),
                "offline_after_sec": int(self.offline_after_input.value()),
            }
        )
        self._refresh_ip_table()
        self._update_status_labels()

    def _on_sound_toggled(self, checked: bool) -> None:
        self.sound_enabled = bool(checked)
        self._alarm_player.set_enabled(self.sound_enabled)
        self._update_alarm_state()

    def _on_auto_start_toggled(self, checked: bool) -> None:
        self.auto_start = bool(checked)

    def _toggle_settings_lock(self) -> None:
        if not self._settings_locked:
            self._settings_locked = True
        else:
            password, ok = QInputDialog.getText(self, "解锁", "请输入密码")
            if not ok:
                return
            if password != SETTINGS_LOCK_PASSWORD:
                QMessageBox.warning(self, "解锁失败", "密码错误。")
                return
            self._settings_locked = False
        self._apply_settings_lock_state()

    def _apply_settings_lock_state(self) -> None:
        if not self._settings_lock_targets:
            self._settings_lock_targets = [
                self.start_button,
                self.save_button,
                self.import_button,
                self.export_button,
                self.import_py_button,
                self.export_py_button,
                self.udp_host_input,
                self.udp_port_input,
                self.redis_host_input,
                self.redis_port_input,
                self.packet_stream_input,
                self.cmd_stream_input,
                self.cmd_group_input,
                self.cmd_consumer_input,
                self.startup_retry_input,
                self.stream_block_ms_input,
                self.stream_count_input,
                self.packet_maxlen_input,
                self.cmd_maxlen_input,
                self.add_blocked_button,
                self.delete_blocked_button,
                self.paste_blocked_button,
                self.disk_c_checkbox,
                self.disk_d_checkbox,
                self.disk_threshold_combo,
                self.warn_after_input,
                self.offline_after_input,
                self.config_editor,
                self.sound_checkbox,
                self.auto_start_checkbox,
            ]
        for widget in self._settings_lock_targets:
            widget.setEnabled(not self._settings_locked)
        self.lock_button.setText("解锁" if self._settings_locked else "锁定")

    def _refresh_disk_usage_view(self) -> None:
        usage_map = {item["slot"]: item for item in collect_disk_usage(self.disk_alert_config)}
        for slot, label_widget in (("c", self.disk_usage_c_value), ("d", self.disk_usage_d_value)):
            item = usage_map.get(slot)
            if item is None:
                _apply_status_style(label_widget, "不可用", kind="bad")
                continue
            kind = "neutral"
            if item.get("enabled") and item.get("free_pct") is not None:
                kind = "bad" if float(item["free_pct"]) <= float(self.disk_alert_config.get("threshold_percent", 10)) else "good"
            _apply_status_style(label_widget, str(item["text"]), kind=kind)

    def _parse_editor_config(self) -> dict:
        try:
            parsed = json.loads(self.config_editor.toPlainText())
        except json.JSONDecodeError as exc:
            raise ValueError(f"配置JSON格式错误: {exc}") from exc
        return normalize_config(parsed, self.template_config)

    def save_settings(self) -> bool:
        try:
            config = self._parse_editor_config()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False

        self.current_config = copy.deepcopy(config)
        self.local_config = copy.deepcopy(config)
        write_json_file(CONFIG_JSON_PATH, self.local_config)
        self._load_config_into_ui()
        self._load_blocked_ips_into_ui()
        self.store.save(
            config=self.local_config,
            disk_alert=self.disk_alert_config,
            quality_monitor=self.quality_monitor_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            was_running=self._proc is not None and self._proc.poll() is None,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        self._append_log(f"[ui] local settings saved to sqlite and {CONFIG_JSON_PATH}")
        return True

    def import_config_json(self) -> None:
        target_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 JSON 配置",
            str(CONFIG_JSON_PATH.parent),
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not target_path:
            return
        try:
            config = normalize_config(_load_json_config(Path(target_path)), self.template_config)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.current_config = copy.deepcopy(config)
        self.local_config = copy.deepcopy(config)
        write_json_file(CONFIG_JSON_PATH, self.local_config)
        self._load_config_into_ui()
        self._load_blocked_ips_into_ui()
        self._append_log(f"[ui] imported json config from {target_path}")

    def export_config_json(self) -> None:
        try:
            config = self._parse_editor_config()
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 JSON 配置",
            str(CONFIG_JSON_PATH),
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not target_path:
            return
        try:
            write_json_file(Path(target_path), config)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._append_log(f"[ui] exported json config to {target_path}")

    def import_config_py(self) -> None:
        target_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 Python 配置(开发)",
            str(BASE_DIR),
            "Python 文件 (*.py);;所有文件 (*)",
        )
        if not target_path:
            return
        try:
            config = normalize_config(_load_py_config(Path(target_path)), self.template_config)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.current_config = copy.deepcopy(config)
        self.local_config = copy.deepcopy(config)
        write_json_file(CONFIG_JSON_PATH, self.local_config)
        self._load_config_into_ui()
        self._load_blocked_ips_into_ui()
        self._append_log(f"[ui] imported python config for development from {target_path}")

    def export_config_py(self) -> None:
        try:
            config = self._parse_editor_config()
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Python 配置(开发)",
            str(BASE_DIR / "CXG_bt设备网管通信配置.py"),
            "Python 文件 (*.py);;所有文件 (*)",
        )
        if not target_path:
            return
        try:
            Path(target_path).write_text(_dump_config_text(config), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._append_log(f"[ui] exported python config for development to {target_path}")

    def export_diagnostic_bundle(self) -> None:
        default_name = f"bt_agent_ui_diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        target_path, _ = QFileDialog.getSaveFileName(self, "导出诊断包", str(BASE_DIR / default_name), "ZIP 文件 (*.zip)")
        if not target_path:
            return
        try:
            summary = {
                "exported_at": _now_iso(),
                "process_state": self.process_state,
                "udp_state": self.udp_state,
                "redis_state": self.redis_state,
                "quality_state": self.quality_state,
                "alarm_state": self.alarm_state,
                "host_status": self.host_status,
                "ip_status": self.ip_status_by_ip,
                "disk_alert_config": self.disk_alert_config,
                "quality_monitor_config": self.quality_monitor_config,
            }
            with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
                zf.writestr("config.json", json.dumps(self.local_config, ensure_ascii=False, indent=2))
                if RUNTIME_CONFIG_PATH.exists():
                    zf.writestr("runtime_config.json", RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
                zf.writestr("recent.log", "\n".join(self._log_lines))
            self._append_log(f"[ui] exported diagnostic bundle: {target_path}")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _build_runtime_config(self) -> dict:
        return copy.deepcopy(self.local_config)

    def _write_runtime_config(self) -> Path:
        write_json_file(RUNTIME_CONFIG_PATH, self._build_runtime_config())
        self.runtime_config_label.setText(str(RUNTIME_CONFIG_PATH))
        return RUNTIME_CONFIG_PATH

    def start_agent(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if not self.save_settings():
            return False
        runtime_path = self._write_runtime_config()
        env = os.environ.copy()
        env[CONFIG_JSON_ENV] = str(runtime_path)
        try:
            launch_cmd, launch_cwd = resolve_launch_command("bt_agent", BT_AGENT_PATH)
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
        self._unexpected_restart_pending = False
        self.process_state = "运行中"
        self.host_status = {**self.host_status, "uptime_sec": 0.0}
        self.ip_status_by_ip = {}
        self._append_log(f"[ui] started bt_agent pid={self._proc.pid}")
        self._reader_thread = threading.Thread(target=self._read_child_output, name="bt-ui-log-reader", daemon=True)
        self._reader_thread.start()
        self._update_status_labels()
        return True

    def stop_agent(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self._manual_stop_requested = True
        self.process_state = "停止中"
        self._update_status_labels()
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                proc.terminate()
        except Exception:
            pass

    def restart_agent(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self.stop_agent()
            QTimer.singleShot(1000, self.start_agent)
        else:
            self.start_agent()

    def _read_child_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            if line.startswith(STATUS_PREFIX):
                try:
                    payload = json.loads(line[len(STATUS_PREFIX):].strip())
                except Exception:
                    self._log_queue.put(("log", line))
                    continue
                self._log_queue.put(("status", payload))
                continue
            self._log_queue.put(("log", line))
        code = proc.wait()
        self._log_queue.put(("exit", code))

    def _poll_log_queue(self) -> None:
        while True:
            try:
                kind, payload = self._log_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(str(payload))
            elif kind == "status":
                self._apply_status_payload(payload)
            elif kind == "exit":
                self._handle_agent_exit(int(payload))

    def _handle_agent_exit(self, code: int) -> None:
        manual_stop = self._manual_stop_requested or self.process_state == "停止中"
        self._proc = None
        self._reader_thread = None
        self._manual_stop_requested = False
        if manual_stop:
            self.process_state = "已停止（手动）"
            self._append_log(f"[ui] bt_agent exited with code {code}")
            self._update_status_labels()
            return
        self.process_state = f"异常退出 ({code})"
        self._append_log(f"[ui] bt_agent exited unexpectedly with code {code}")
        self._update_status_labels()
        if not self._unexpected_restart_pending:
            self._unexpected_restart_pending = True
            QTimer.singleShot(UNEXPECTED_RESTART_DELAY_MS, self._restart_after_unexpected_exit)

    def _restart_after_unexpected_exit(self) -> None:
        self._unexpected_restart_pending = False
        if self._proc is not None and self._proc.poll() is None:
            return
        self._append_log("[ui] restarting bt_agent after unexpected exit")
        self.start_agent()

    def _apply_status_payload(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        host = payload.get("host")
        ips = payload.get("ips")
        if isinstance(host, dict):
            self.host_status.update(host)
        if isinstance(ips, list):
            self.ip_status_by_ip = {
                str(item.get("ip")): item
                for item in ips
                if isinstance(item, dict) and str(item.get("ip", "")).strip()
            }
        self._recent_status_ts = str(payload.get("ts") or "")
        self._refresh_overview()
        self._update_status_labels()

    def _refresh_overview(self) -> None:
        host = self.host_status
        value_map = {
            "uptime_sec": f"{float(host.get('uptime_sec', 0.0)):.1f}s",
            "send_queue_depth": str(host.get("send_queue_depth", 0)),
            "valid_packets": str(host.get("valid_packets", 0)),
            "malformed_packets": str(host.get("malformed_packets", 0)),
            "checksum_errors": str(host.get("checksum_errors", 0)),
            "blocked_packets": str(host.get("blocked_packets", 0)),
            "analog_packets": str(host.get("analog_packets", 0)),
            "cmd_received": str(host.get("cmd_received", 0)),
            "cmd_acked": str(host.get("cmd_acked", 0)),
            "send_ok": str(host.get("send_ok", 0)),
            "send_errors": str(host.get("send_errors", 0)),
            "redis_publish_errors": str(host.get("redis_publish_errors", 0)),
            "last_packet_at": _format_ts(host.get("last_packet_at")),
            "last_send_at": _format_ts(host.get("last_send_at")),
        }
        for key, value in value_map.items():
            self.summary_labels[key].setText(value)
        self._refresh_ip_table()

    def _device_status(self, item: dict[str, Any]) -> tuple[str, str]:
        valid_packets = int(item.get("valid_packets", 0) or 0)
        malformed_packets = int(item.get("malformed_packets", 0) or 0)
        checksum_errors = int(item.get("checksum_errors", 0) or 0)
        last_seen = item.get("last_valid_seen")
        try:
            age = time.time() - float(last_seen)
        except Exception:
            age = None
        if valid_packets <= 0 and (malformed_packets > 0 or checksum_errors > 0):
            any_packet_ts = item.get("last_seen")
            try:
                any_packet_age = time.time() - float(any_packet_ts)
            except Exception:
                any_packet_age = None
            offline_after = float(self.quality_monitor_config.get("offline_after_sec", 30))
            if any_packet_age is not None and any_packet_age <= offline_after:
                return "异常", "bad"
            return "离线", "bad"
        if age is None:
            return "离线", "bad"
        warn_after = float(self.quality_monitor_config.get("warn_after_sec", 10))
        offline_after = float(self.quality_monitor_config.get("offline_after_sec", 30))
        if age <= warn_after:
            return "正常", "good"
        if age <= offline_after:
            return "注意", "warn"
        return "离线", "bad"

    def _refresh_ip_table(self) -> None:
        rows = [(ip, item) for ip, item in sorted(self.ip_status_by_ip.items())]
        self.ip_table.setRowCount(len(rows))
        for row, (ip, item) in enumerate(rows):
            status_text, _kind = self._device_status(item)
            values = [
                ip,
                status_text,
                _age_text_from_timestamp(item.get("last_seen")),
                f"{float(item.get('rate_10s', 0.0)):.2f}/s",
                str(item.get("valid_packets", 0)),
                str(item.get("malformed_packets", 0)),
                str(item.get("checksum_errors", 0)),
                str(item.get("send_ok", 0)),
                str(item.get("send_errors", 0)),
            ]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if col < len(IP_TABLE_TOOLTIPS):
                    table_item.setToolTip(IP_TABLE_TOOLTIPS[col])
                self.ip_table.setItem(row, col, table_item)

    def _build_quality_summary(self) -> tuple[str, str, str]:
        host = self.host_status
        issues: list[str] = []
        if self.process_state.startswith("已停止") or self.process_state.startswith("异常退出"):
            issues.append("进程未运行")
        if not bool(host.get("udp_socket_ok")) and self.process_state == "运行中":
            issues.append("UDP监听异常")
        if not bool(host.get("redis_ok")):
            issues.append("Redis断开")
        if not bool(host.get("cmd_thread_alive")) and self.process_state == "运行中":
            issues.append("命令线程异常")
        if int(host.get("send_errors", 0)) > 0:
            issues.append("存在发送失败")
        queue_depth = int(host.get("send_queue_depth", 0))
        has_warn = False
        if queue_depth > 0:
            has_warn = True
            issues.append(f"发送队列堆积({queue_depth})")

        ip_bad = False
        ip_warn = False
        for item in self.ip_status_by_ip.values():
            status_text, kind = self._device_status(item)
            if kind == "bad":
                ip_bad = True
            elif kind == "warn":
                ip_warn = True
        if ip_bad:
            issues.append("存在离线IP")
        elif ip_warn:
            has_warn = True
            issues.append("存在注意IP")

        if issues and ("进程未运行" in issues or "UDP监听异常" in issues or "Redis断开" in issues or "命令线程异常" in issues or "存在发送失败" in issues or ip_bad):
            return "异常", "bad", issues[0]
        if issues or has_warn:
            return "注意", "warn", issues[0] if issues else "-"
        return "正常", "good", "-"

    def _update_status_labels(self) -> None:
        _apply_status_style(self.process_value, self.process_state)
        self.udp_state = "监听中" if self.host_status.get("udp_socket_ok") else ("已停止" if self.process_state.startswith("已停止") else "异常")
        self.redis_state = "正常" if self.host_status.get("redis_ok") else "断开"
        quality_text, quality_kind, issue_text = self._build_quality_summary()
        self.quality_state = quality_text
        self.last_issue_text = issue_text
        _apply_status_style(self.udp_value, self.udp_state, kind="good" if self.udp_state == "监听中" else "bad")
        _apply_status_style(self.redis_value, self.redis_state, kind="good" if self.redis_state == "正常" else "bad")
        _apply_status_style(self.quality_value, self.quality_state, kind=quality_kind)
        self.issue_value.setText(self.last_issue_text)
        self.runtime_config_label.setText(str(RUNTIME_CONFIG_PATH))
        if self.process_state == "停止中":
            self.start_button.setText("停止中")
            process_button_enabled = False
        elif self._proc is not None and self._proc.poll() is None:
            self.start_button.setText("停止")
            process_button_enabled = True
        else:
            self.start_button.setText("启动")
            process_button_enabled = True
        self.start_button.setEnabled(process_button_enabled and (not self._settings_locked))
        self.test_alarm_button.setEnabled(self.sound_enabled)
        self.pause_alarm_button.setEnabled(bool(self._active_disk_alerts) and self.sound_enabled)
        self._update_alarm_state()

    def _check_disk_alerts(self) -> None:
        alerts = collect_disk_alerts(self.disk_alert_config)
        if alerts != self._active_disk_alerts:
            self._active_disk_alerts = alerts
            if not alerts:
                self._alarm_paused_until_clear = False
            self._update_alarm_state()
        self._refresh_disk_usage_view()

    def _update_alarm_state(self) -> None:
        if self._alarm_test_active:
            self.alarm_state = "试音中"
            self._alarm_player.set_enabled(True)
            self._alarm_player.set_audio_file(DISK_ALARM_WAV_PATH)
            self._alarm_player.set_message("CXG-bt设备网管通信控制程序磁盘告警测试")
            self._alarm_player.set_active(True)
            _apply_status_style(self.alarm_value, self.alarm_state, kind="warn")
            return
        disk_alarm_active = bool(self._active_disk_alerts)
        if not disk_alarm_active:
            self.alarm_state = "正常"
            self._alarm_player.set_active(False)
            _apply_status_style(self.alarm_value, self.alarm_state, kind="good")
            return
        if self._alarm_paused_until_clear or not self.sound_enabled:
            self.alarm_state = "已静音"
            self._alarm_player.set_active(False)
            _apply_status_style(self.alarm_value, self.alarm_state, kind="warn")
            return
        self.alarm_state = "告警中"
        self._alarm_player.set_message("BT系统磁盘空间告警")
        self._alarm_player.set_enabled(self.sound_enabled)
        self._alarm_player.set_active(True)
        _apply_status_style(self.alarm_value, self.alarm_state, kind="bad")

    def _pause_alarm_sound(self) -> None:
        self._alarm_paused_until_clear = True
        self._alarm_player.set_active(False)
        self._update_alarm_state()

    def _stop_alarm_sound(self) -> None:
        self._alarm_player.set_active(False)

    def _test_alarm_sound(self) -> None:
        if not self.sound_enabled:
            return
        self._alarm_test_active = True
        self._update_alarm_state()
        QTimer.singleShot(_wav_duration_ms(DISK_ALARM_WAV_PATH) + 200, self._finish_test_alarm_sound)

    def _finish_test_alarm_sound(self) -> None:
        self._alarm_test_active = False
        self._stop_alarm_sound()
        self._update_alarm_state()

    def _add_blocked_ip(self) -> None:
        dialog = IPv4InputDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        ip = dialog.ip_text().strip()
        if not ip:
            return
        if ip in self._pull_blocked_ips_from_ui():
            return
        try:
            socket.inet_aton(ip)
        except OSError:
            QMessageBox.warning(self, "新增失败", "IP 格式无效。")
            return
        QListWidgetItem(ip, self.blocked_list)
        self.current_config = self._build_current_config_from_form()
        self._refresh_config_editor()

    def _delete_selected_blocked_ips(self) -> None:
        for item in self.blocked_list.selectedItems():
            self.blocked_list.takeItem(self.blocked_list.row(item))
        self.current_config = self._build_current_config_from_form()
        self._refresh_config_editor()

    def _paste_blocked_ips(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "批量粘贴屏蔽IP", "每行一个 IPv4 地址")
        if not ok:
            return
        current = self._pull_blocked_ips_from_ui()
        merged = current + [line.strip() for line in str(text or "").splitlines()]
        ips = _normalize_blocked_ips(merged)
        self.blocked_list.clear()
        for ip in ips:
            QListWidgetItem(ip, self.blocked_list)
        self.current_config = self._build_current_config_from_form()
        self._refresh_config_editor()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._proc is not None and self._proc.poll() is None:
            self.stop_agent()
        self._alarm_player.stop()
        self.store.save(
            config=self.local_config,
            disk_alert=self.disk_alert_config,
            quality_monitor=self.quality_monitor_config,
            sound_enabled=self.sound_enabled,
            auto_start=self.auto_start,
            settings_locked=self._settings_locked,
            was_running=False,
            window_geometry=_encode_geometry(self.saveGeometry()),
        )
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    lock, error = acquire_single_instance_lock(lock_path("bt_agent", "bt_agent_ui.lock"), "CXG-bt设备网管通信控制程序")
    if error:
        QMessageBox.warning(None, "无法启动", error)
        return 1
    window = BtAgentUIWindow()
    window._single_instance_lock = lock
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
