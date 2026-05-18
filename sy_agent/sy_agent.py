#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
sy_agent.py (Redis Streams) - Receiver Threads + Frame Queues (生产版：最小侵入补丁)

在你当前版本基础上做了“现场生产必备”的最小改动：

✅ [PROD] 0) 修复响应帧分包被误丢的致命问题（F7/F7 分包）
✅ [PROD] 1) 命令去重（防重复执行）
✅ [PROD] 2) DLQ 死信流（防 pending 永久堆积）
✅ [PROD] 3) 日志默认收敛（现场不刷屏、不打爆磁盘）
✅ [PROD] 4) 降低 RX 空转 CPU（timeout=0 时靠 idle sleep 降载）
✅ [PROD] 5) watchdog 参数放宽（减少抖动式重连）

------------------------------------------------------------
本次按建议补丁（合并版）：

✅ [FIX] A) after_sleep 不再持有 ser_lock（避免 RX 线程被锁死导致丢字节/假 NO_RESP）
✅ [OBS] B) RX out_q 满时不再静默：新增 drop_q_full 计数，并在 STATUS 里输出，方便现场定位“拥塞丢帧”
✅ [SAFE] C) 新建 cmd stream group 默认从“现在”开始（xgroup_create id="$"），避免首次上线误消费历史命令
✅ [OBS] D) DLQ 额外携带 agent 侧信息（host/consumer/pid），便于排障定位是哪台采集机写入

✅ [FIX] E) 命令消费线程增加 in-flight 去重（避免 pending XAUTOCLAIM 反复 enqueue 导致重复执行）
✅ [SAFE] F) 命令重试次数上限：超过阈值 => DLQ + ACK（避免 pending 永久堆积）

------------------------------------------------------------
【本次额外合并的 3 个最小改动（按你确认的建议）】：
✅ [SAFE] 1) 命令收到 RESP_OK 后：先 mark_done（至少本地）再 report/ack，防 Redis 抖动导致命令重复执行
✅ [ROBUST] 2) frame_hex 容错更强：支持 0x 前缀/空格/冒号等分隔
✅ [FIX] 3) _clear_side 只清当前 side 的 stash，不误伤另一侧匹配缓存

------------------------------------------------------------
【✅ 本次新增：适配“SY 下位机控制确认”】：
✅ [NO_RESP] 4) 对 CC 等无回帧命令：只下发不等待 RESP_OK
✅ [ACK] 5) BB 远程控制等待 0x05 执行确认帧
✅ [CONFIRM] 6) 对无回帧命令仍可选用 A2/A1 做“在线/变化/对账确认”（best-effort）
✅ [SAFE] 7) 无回帧命令：发送成功即 mark_done + ACK（避免 pending 重复执行造成多次动作）
------------------------------------------------------------
"""

import os
import sys
import time
import json
import signal
import threading
import queue
import socket
import shutil
from typing import Dict, List, Optional, Tuple, Deque, Callable
from collections import deque
from pathlib import Path
import copy

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if os.name == "nt":
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

import serial
from serial import SerialException
import redis

from protected_runtime import agent_config_path, write_json_file


# ============================================================
# ✅✅✅ 顶部调参区（生产默认：更保守、更省资源）
# ============================================================
DEBUG_TUNING = {
    # ---------- 串口/链路时序 ----------
    "AFTER_WRITE_SLEEP_SEC": 0.100,
    "ENABLE_AFTER_WRITE_SLEEP": True,
    "WAIT_RESPONSE_TIMEOUT_SEC": 0.20,     # 现场可略放宽
    "RX_IDLE_SLEEP_SEC": 0.002,            # 生产：降低空转 CPU

    # ---------- 自适应 after_write_sleep ----------
    "AUTO_SLEEP_ENABLE": False,
    "AUTO_SLEEP_WINDOW": 80,
    "AUTO_SLEEP_PCTL": 95,
    "AUTO_SLEEP_MARGIN_SEC": 0.005,
    "AUTO_SLEEP_MIN_SEC": 0.010,
    "AUTO_SLEEP_MAX_SEC": 0.080,
    "AUTO_SLEEP_UPDATE_EVERY": 8,
    "AUTO_SLEEP_PRINT_EVERY_SEC": 5.0,     # 生产：少打印
    "AUTO_SLEEP_NO_RESP_BUMP_SEC": 0.005,
    "AUTO_SLEEP_NO_RESP_STREAK": 2,
    "AUTO_SLEEP_NO_RESP_COOLDOWN_SEC": 0.8,
    "AUTO_SLEEP_DECAY_OK_STREAK": 40,
    "AUTO_SLEEP_DECAY_STEP_SEC": 0.002,

    # ---------- RTS 伪485模式 ----------
    "RTS_TOGGLE": False,
    "RTS_TX_LEVEL": 1,
    "RTS_RX_LEVEL": 0,
    "RTS_PRE_DELAY_SEC": 0.001,
    "RTS_POST_DELAY_SEC": 0.002,

    # ---------- 运行时行为（关键：不退出，自动恢复） ----------
    "REDIS_RETRY_MIN_SEC": 1.0,
    "REDIS_RETRY_MAX_SEC": 10.0,
    "REDIS_DOWN_PAUSE_SEC": 0.5,   # poller 在 redis down 时暂停粒度

    "SERIAL_RETRY_MIN_SEC": 1.0,
    "SERIAL_RETRY_MAX_SEC": 30.0,
    "SERIAL_RX_ERROR_LIMIT": 5,       # 生产：略放宽（减少误判）

    # ---------- RX 线程存活 + 串口假死 watchdog ----------
    "RX_THREAD_DEAD_REOPEN": True,

    # “假死无异常”定义：该口 N 秒内没有产生任何“合法响应帧”
    "STALL_WATCHDOG_ENABLE": True,
    "STALL_NOFRAME_SEC": 15.0,         # 生产：更保守
    "STALL_GRACE_AFTER_OPEN_SEC": 2.0,
    "STALL_COOLDOWN_SEC": 15.0,        # 生产：减少抖动

    # ---------- 详细日志（生产默认收敛） ----------
    "LOG_SEND": False,
    "LOG_RECV_OK": False,
    "LOG_NO_RESP": True,
    "LOG_RX_STATS": True,
    "LOG_MATCH_DETAIL": False,
    "LOG_REDIS_STATE": True,
    "LOG_PORT_STATE": True,
    "STATUS_PRINT_EVERY_SEC": 10.0,    # 生产：更稀疏

    # ---------- 额外：串口 read 行为 ----------
    "MAX_READ_ONCE": 4096,
    "MAX_SOFTBUF": 8192,

    # pending 重试/claim 参数（默认开）
    "PENDING_RETRY_ENABLE": True,
    "PENDING_MIN_IDLE_MS": 5000,
    "PENDING_CLAIM_EVERY_SEC": 2.0,
    "PENDING_CLAIM_COUNT": 20,
}

CONFIG_JSON_ENV = "SY_AGENT_CONFIG_JSON"
CONFIG_PATH: Path

DEFAULT_CONFIG = {
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
        "cc_confirm_delay_sec": 0.08,
        "cc_confirm_timeout_sec": 0.25,
        "cc_confirm_a1": True,
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
        "timeout_sec": 0.08,
        "budget_sec": 0.16,
    },
    "serial": {
        "default_baudrate": 19200,
        "timeout": 0.0,
    },
    "ui": {
        "mode": "dashboard",
        "refresh_sec": 1.0,
        "event_buffer_size": 20,
        "ansi": "auto",
    },
    "lines": [],
    "debug_tuning": DEBUG_TUNING,
}


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_json_config(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RuntimeError(f"unable to load json config: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must define a JSON object")
    return loaded


def _load_config() -> dict:
    global CONFIG_PATH

    env_json = os.environ.get(CONFIG_JSON_ENV, "").strip()
    if env_json:
        CONFIG_PATH = Path(env_json).expanduser().resolve()
        loaded = _load_json_config(CONFIG_PATH)
        if "lines" not in loaded:
            raise KeyError(f"{CONFIG_PATH} must define lines")
        if not isinstance(loaded.get("lines"), list):
            raise TypeError(f"{CONFIG_PATH} lines must be a list")
        config = copy.deepcopy(DEFAULT_CONFIG)
        return _deep_merge(config, loaded)

    CONFIG_PATH = agent_config_path("sy_agent")
    if not CONFIG_PATH.exists():
        write_json_file(CONFIG_PATH, copy.deepcopy(DEFAULT_CONFIG))
    loaded = _load_json_config(CONFIG_PATH)
    if "lines" not in loaded:
        raise KeyError(f"{CONFIG_PATH} must define lines")
    if not isinstance(loaded.get("lines"), list):
        raise TypeError(f"{CONFIG_PATH} lines must be a list")
    config = copy.deepcopy(DEFAULT_CONFIG)
    return _deep_merge(config, loaded)


CONFIG = _load_config()
DEBUG_TUNING = CONFIG["debug_tuning"]
AGENT_CONFIG = CONFIG.get("agent", {})
REDIS_CONFIG = CONFIG["redis"]
STREAM_CONFIG = CONFIG["stream"]
CMD_CONFIG = CONFIG["cmd"]
TIME_SYNC_CONFIG = CONFIG["time_sync"]
A2_BURST_CONFIG = CONFIG["a2_burst"]
SERIAL_CONFIG = CONFIG["serial"]
UI_CONFIG = CONFIG.get("ui", {})

def _safe_agent_token(value: str) -> str:
    text = str(value or "").strip()
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    token = "".join(out).strip("._")
    return token or "agent"


def _detect_private_ipv4() -> str:
    candidates: List[str] = []
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


def _resolve_agent_ip(preferred: Optional[str]) -> str:
    text = str(preferred or "").strip()
    return text or _detect_private_ipv4()


AGENT_IP = _resolve_agent_ip(AGENT_CONFIG.get("ip"))
AGENT_NAME = str(AGENT_CONFIG.get("name", "")).strip() or socket.gethostname()
AGENT_ROLE = str(AGENT_CONFIG.get("role", "main")).strip() or "main"
AGENT_TOKEN = _safe_agent_token(AGENT_IP)


# ============================================================
# Redis Streams 配置
# ============================================================
REDIS_HOST = str(REDIS_CONFIG["host"])
REDIS_PORT = int(REDIS_CONFIG["port"])
SY_STREAM_DB = int(REDIS_CONFIG["db"])

SY_RAW_STREAM = str(STREAM_CONFIG["raw_stream"])
SY_RAW_STREAM_MAXLEN = int(STREAM_CONFIG["raw_stream_maxlen"])

SY_CMD_STREAM = str(STREAM_CONFIG["cmd_stream"])
SY_CMD_GROUP_BASE = str(STREAM_CONFIG["cmd_group"])
SY_CMD_CONSUMER_BASE = str(STREAM_CONFIG["cmd_consumer"])
SY_CMD_GROUP = f"{SY_CMD_GROUP_BASE}:{AGENT_TOKEN}"
SY_CMD_CONSUMER = f"{SY_CMD_CONSUMER_BASE}:{AGENT_TOKEN}"

SY_CMD_BLOCK_MS = int(STREAM_CONFIG["cmd_block_ms"])
SY_CMD_COUNT = int(STREAM_CONFIG["cmd_count"])

# ✅ 生产：DLQ + 去重配置
SY_CMD_DLQ_STREAM = str(CMD_CONFIG["dlq_stream"])
SY_CMD_DLQ_MAXLEN = int(CMD_CONFIG["dlq_maxlen"])

SY_CMD_DONE_KEY_PREFIX = str(CMD_CONFIG["done_key_prefix"])
SY_CMD_DONE_TTL_SEC = int(CMD_CONFIG["done_ttl_sec"])
SY_CMD_DONE_LOCAL_TTL_SEC = int(CMD_CONFIG["done_local_ttl_sec"])

# (可选) DLQ 去重：同一个坏消息/原因短时间只记录一次
SY_CMD_DLQ_DEDUPE_PREFIX = str(CMD_CONFIG["dlq_dedupe_prefix"])
SY_CMD_DLQ_DEDUPE_TTL_SEC = int(CMD_CONFIG["dlq_dedupe_ttl_sec"])

# ✅ 新增：命令重试次数上限（避免 pending 永久堆积）
SY_CMD_TRY_KEY_PREFIX = str(CMD_CONFIG["try_key_prefix"])
SY_CMD_TRY_TTL_SEC = int(CMD_CONFIG["try_ttl_sec"])
SY_CMD_MAX_TRIES = int(CMD_CONFIG["max_tries"])
SY_CMD_INFLIGHT_TTL_SEC = float(CMD_CONFIG["inflight_ttl_sec"])

# ============================================================
# ✅ 新增：无回帧命令（默认仅 CC）适配配置
# ============================================================
SY_CMD_NO_RESP_ENABLE = bool(CMD_CONFIG["no_resp_enable"])
SY_CMD_CC_CONFIRM_DELAY_SEC = float(CMD_CONFIG.get("cc_confirm_delay_sec", CMD_CONFIG.get("confirm_delay_sec", 0.08)))
SY_CMD_CC_CONFIRM_TIMEOUT_SEC = float(CMD_CONFIG.get("cc_confirm_timeout_sec", CMD_CONFIG.get("confirm_timeout_sec", 0.25)))
SY_CMD_CC_CONFIRM_A1 = bool(CMD_CONFIG.get("cc_confirm_a1", CMD_CONFIG.get("confirm_a1", True)))
SY_CMD_BB_CMD_RETRIES = int(CMD_CONFIG.get("bb_cmd_retries", 3))
PRIMARY_A1_FAILOVER_THRESHOLD = 3
SUBAGENT_CONTROL_STREAM = "sy-subagent-control"
SUBAGENT_STATUS_TTL_SEC = 15
SUBAGENT_STATUS_REFRESH_SEC = 5.0
NMS_ROUTE_KEY_PREFIX = "sy:route:nms:"
NMS_ROUTE_TTL_SEC = max(15, int(SUBAGENT_STATUS_REFRESH_SEC * 3))


def _parse_hex_cmd_list(values) -> List[int]:
    """
    支持："BB,CC" / "0xBB 0xCC" / "187,204" / ["BB", "CC"] / [187, 204]
    """
    out: List[int] = []
    if values is None:
        return out
    parts = []
    if isinstance(values, (list, tuple, set)):
        parts = [str(item).strip() for item in values if str(item).strip()]
    else:
        for p in str(values).replace(";", ",").replace("|", ",").split(","):
            p = p.strip()
            if not p:
                continue
            parts.append(p)
    for p in parts:
        pp = p.strip().lower()
        try:
            if pp.startswith("0x"):
                out.append(int(pp, 16) & 0xFF)
            elif all(ch in "0123456789abcdef" for ch in pp) and len(pp) <= 2:
                out.append(int(pp, 16) & 0xFF)
            else:
                out.append(int(pp) & 0xFF)
        except Exception:
            continue
    return out


# ============================================================
# 时间同步（AA）配置
# ============================================================
TIME_SYNC_ENABLE = bool(TIME_SYNC_CONFIG["enable"])
TIME_SYNC_INTERVAL = float(TIME_SYNC_CONFIG["interval_sec"])

# ============================================================
# A2 Burst（保留）
# ============================================================
A2_BURST_ENABLE = bool(A2_BURST_CONFIG["enable"])
A2_BURST_MAX = int(A2_BURST_CONFIG["max"])
A2_BURST_TIMEOUT = float(A2_BURST_CONFIG["timeout_sec"])
A2_BURST_BUDGET = float(A2_BURST_CONFIG["budget_sec"])

# ============================================================
# 串口参数（保留：ODD/2 stop/19200/timeout=0）
# ============================================================
DEFAULT_BAUDRATE = int(SERIAL_CONFIG["default_baudrate"])
DEFAULT_BYTESIZE = serial.EIGHTBITS
DEFAULT_PARITY = serial.PARITY_ODD
DEFAULT_STOPBITS = serial.STOPBITS_TWO
DEFAULT_TIMEOUT = float(SERIAL_CONFIG["timeout"])

# ============================================================
# 控制台 UI 配置
# ============================================================
UI_MODE = str(UI_CONFIG.get("mode", "dashboard")).strip().lower() or "dashboard"
UI_REFRESH_SEC = max(0.2, float(UI_CONFIG.get("refresh_sec", 1.0)))
UI_EVENT_BUFFER_SIZE = max(5, int(UI_CONFIG.get("event_buffer_size", 20)))
UI_ANSI = str(UI_CONFIG.get("ansi", "auto")).strip().lower() or "auto"
NO_RESP_WINDOW_SEC = 300.0
# ============================================================
# 多线路配置（示例）
# ============================================================
LINES_CONFIG = CONFIG["lines"]

# ============================================================
# 控制台输出
# ============================================================
running = True
nms_to_line: Dict[int, "LinePoller"] = {}
CONSOLE = None


def _trim_text(value, max_len: int = 160) -> str:
    text = str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    if len(text) <= max_len:
        return text
    return f"{text[:max_len - 3]}..."


def _append_wrapped(lines: List[str], text: str, width: int, *, indent: str = ""):
    text = str(text).replace("\r", " ").replace("\n", " ")
    if width <= 8:
        lines.append(text[:width])
        return
    if not text:
        lines.append("")
        return

    parts = text.split("  ")
    current = ""
    for part in parts:
        token = part.strip()
        if not token:
            continue
        candidate = token if not current else f"{current}  {token}"
        if len(indent) + len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(_trim_text(f"{indent}{current}", width))
        current = token
    if current:
        lines.append(_trim_text(f"{indent}{current}", width))


def _age_text(last_mono: Optional[float], nowt: float) -> str:
    if not last_mono or last_mono <= 0:
        return "-"
    delta = max(0.0, nowt - float(last_mono))
    if delta < 1.0:
        return f"{delta:.1f}s"
    if delta < 60.0:
        return f"{delta:.0f}s"
    return f"{delta / 60.0:.1f}m"


def _enable_windows_vt_mode() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        if handle in (0, -1):
            return False
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
            return False
        enable_vt = 0x0004
        if kernel32.SetConsoleMode(handle, mode.value | enable_vt) == 0:
            return False
        return True
    except Exception:
        return False


class ConsoleManager:
    def __init__(self):
        self.requested_mode = UI_MODE if UI_MODE in ("dashboard", "plain") else "dashboard"
        self.refresh_sec = float(UI_REFRESH_SEC)
        self.event_capacity = int(UI_EVENT_BUFFER_SIZE)
        self.ansi_setting = UI_ANSI if UI_ANSI in ("auto", "always", "never") else "auto"

        self._lock = threading.Lock()
        self._events: Deque[dict] = deque(maxlen=self.event_capacity)
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._redis_conn = None
        self._pollers: List["LinePoller"] = []
        self._last_plain_dashboard_emit = 0.0

        self.ansi_enabled = self._resolve_ansi_enabled()
        self.mode = "dashboard" if (self.requested_mode == "dashboard" and self.ansi_enabled) else "plain"

    def _resolve_ansi_enabled(self) -> bool:
        if self.ansi_setting == "never":
            return False
        if self.ansi_setting == "always":
            return _enable_windows_vt_mode()
        if not sys.stdout.isatty():
            return False
        return _enable_windows_vt_mode()

    def bind_runtime(self, *, redis_conn=None, pollers: Optional[List["LinePoller"]] = None):
        with self._lock:
            if redis_conn is not None:
                self._redis_conn = redis_conn
            if pollers is not None:
                self._pollers = pollers

    def register_poller(self, poller: "LinePoller"):
        with self._lock:
            if poller not in self._pollers:
                self._pollers.append(poller)

    def start(self):
        if self.mode != "dashboard" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._render_loop, name="sy-dashboard", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        if self.mode == "dashboard" and self.ansi_enabled:
            try:
                sys.stdout.write("\x1b[?25h\n")
                sys.stdout.flush()
            except Exception:
                pass

    def emit(
        self,
        *,
        level: str,
        category: str,
        message: str,
        line_id: Optional[int] = None,
        line_name: Optional[str] = None,
        port: Optional[str] = None,
        record_event: bool = True,
        plain_output: bool = True,
    ):
        event = {
            "ts": time.strftime("%H:%M:%S", time.localtime()),
            "level": (level or "INFO").upper(),
            "category": (category or "general").lower(),
            "message": _trim_text(message, 220),
            "line_id": line_id,
            "line_name": line_name,
            "port": port,
        }
        if record_event:
            with self._lock:
                self._events.append(event)
        if self.mode == "plain" and plain_output:
            print(self._format_plain_event(event), flush=True)

    def _format_plain_event(self, event: dict) -> str:
        parts = [event["ts"], event["level"], f"[{event['category']}]"]
        if event.get("line_id") is not None:
            label = f"line={event['line_id']}"
            if event.get("line_name"):
                label += f"/{event['line_name']}"
            parts.append(label)
        if event.get("port"):
            parts.append(f"port={event['port']}")
        parts.append(event["message"])
        return " ".join(parts)

    def _snapshot(self):
        with self._lock:
            events = list(self._events)
            redis_conn = self._redis_conn
            pollers = list(self._pollers)
        return redis_conn, pollers, events

    def _render_loop(self):
        while not self._stop_evt.is_set():
            self.render_once()
            self._stop_evt.wait(self.refresh_sec)

    def render_once(self):
        if self.mode != "dashboard" or not self.ansi_enabled:
            return
        redis_conn, pollers, events = self._snapshot()
        width = max(100, shutil.get_terminal_size(fallback=(120, 40)).columns)
        payload = self._build_dashboard_payload(redis_conn, pollers, events, width)
        try:
            sys.stdout.write("\x1b[?25l\x1b[H\x1b[2J")
            sys.stdout.write(payload)
            sys.stdout.write("\n")
            sys.stdout.flush()
        except Exception:
            self.mode = "plain"
            self.emit(level="WARN", category="startup", message="dashboard render failed, fallback to plain mode", record_event=True, plain_output=True)

    def maybe_emit_plain_dashboard_status(self):
        if self.mode != "plain":
            return
        nowt = time.monotonic()
        with self._lock:
            if (nowt - self._last_plain_dashboard_emit) < max(0.5, float(self.refresh_sec)):
                return
            self._last_plain_dashboard_emit = nowt
        redis_conn, pollers, events = self._snapshot()
        payload = self._build_dashboard_payload(redis_conn, pollers, events, 120)
        message = "[DASHBOARD] " + json.dumps({"text": payload}, ensure_ascii=False, separators=(",", ":"))
        event = {
            "ts": time.strftime("%H:%M:%S", time.localtime()),
            "level": "INFO",
            "category": "poll",
            "message": message,
            "line_id": None,
            "line_name": None,
            "port": None,
        }
        try:
            print(self._format_plain_event(event), flush=True)
        except Exception:
            pass

    def _build_dashboard_payload(self, redis_conn, pollers, events, width: int) -> str:
        nowt = time.monotonic()
        redis_up = bool(redis_conn and redis_conn.is_ready())
        redis_state = "UP" if redis_up else "DOWN"
        total_a1_req = sum(int(p._side_count_total("a1", no_resp=False)) for p in pollers)
        total_a1_req_5m = sum(int(p.recent_request_count("a1", nowt=nowt)) for p in pollers)
        total_a2_req = sum(int(p._side_count_total("a2", no_resp=False)) for p in pollers)
        total_a2_req_5m = sum(int(p.recent_request_count("a2", nowt=nowt)) for p in pollers)
        total_a1_timeout = sum(int(getattr(p, "a1_no_resp_count", 0) or 0) for p in pollers)
        total_a1_timeout_5m = sum(int(p.recent_no_resp_count("a1", nowt)) for p in pollers)
        total_a2_timeout = sum(int(getattr(p, "a2_no_resp_count", 0) or 0) for p in pollers)
        total_a2_timeout_5m = sum(int(p.recent_no_resp_count("a2", nowt)) for p in pollers)
        total_cmd_timeout = sum(int(getattr(p, "cmd_no_resp_count", 0) or 0) for p in pollers)
        total_cmd_timeout_5m = sum(int(p.recent_no_resp_count("cmd", nowt)) for p in pollers)
        degraded_lines = sum(1 for p in pollers if p.is_degraded())

        lines = []
        _append_wrapped(
            lines,
            f"SY_AGENT  mode={self.mode}  time={time.strftime('%Y-%m-%d %H:%M:%S')}  "
            f"redis={redis_state}  consumer={SY_CMD_CONSUMER}  pid={os.getpid()}",
            width,
        )
        _append_wrapped(
            lines,
            f"target={REDIS_HOST}:{REDIS_PORT}/{SY_STREAM_DB}  raw={SY_RAW_STREAM}  cmd={SY_CMD_STREAM}  "
            f"group={SY_CMD_GROUP}  lines={len(pollers)}  after_sleep={ADAPT.get_sleep():.3f}s  "
            f"degraded_lines={degraded_lines}  a1_req(T/5m)={total_a1_req}/{total_a1_req_5m}  "
            f"a2_req(T/5m)={total_a2_req}/{total_a2_req_5m}  "
            f"a1_timeout(T/5m)={total_a1_timeout}/{total_a1_timeout_5m}  "
            f"a2_timeout(T/5m)={total_a2_timeout}/{total_a2_timeout_5m}  "
            f"cmd_timeout(T/5m)={total_cmd_timeout}/{total_cmd_timeout_5m}",
            width,
        )
        _append_wrapped(
            lines,
            f"wait={float(DEBUG_TUNING['WAIT_RESPONSE_TIMEOUT_SEC']):.3f}s  "
            f"bb_cmd_retries={SY_CMD_BB_CMD_RETRIES}  "
            f"no_resp_cmds={','.join(hex(x) for x in sorted(NO_RESP_REQ_CMDS))}  config={CONFIG_PATH}",
            width,
        )
        lines.append("")
        lines.append("Lines")
        compact_lines = width < 170
        if compact_lines:
            lines.append("-" * min(width, 88))
        else:
            lines.append(_trim_text("ID  Name         Pref(H/T) Port(H/T)   Link(H/T)   DownFor(H/T)   Devs  A1Req(H/T|H5/T5)  A2Req(H/T|H5/T5)  A1Timeout(H/T|H5/T5)  A2Timeout(H/T|H5/T5)  CmdTimeout(H/T|H5/T5)  Unmatch(T/5m)  QFull(H/T)  Queue(H/T)  LastOK", width))
            lines.append("-" * min(width, 220))

        if pollers:
            for poller in pollers:
                snap = poller.get_ui_snapshot(nowt)
                if compact_lines:
                    line_header = (
                        f"{snap['line_id']} {snap['name']}  pref={snap['preferred']}  devs={snap['devices']}  "
                        f"last_ok={snap['last_ok']}"
                    )
                    line_status = (
                        f"port={snap['port']}  link={snap['link']}  down={snap['down_for']}  "
                        f"qfull={snap['qfull']}  queue={snap['queue']}"
                    )
                    line_metrics = (
                        f"a1_req={snap['a1_req']}  a2_req={snap['a2_req']}  "
                        f"a1_to={snap['a1_timeout']}  a2_to={snap['a2_timeout']}  "
                        f"cmd_to={snap['cmd_timeout']}  unmatch={snap['unmatched']}"
                    )
                    _append_wrapped(lines, line_header, width)
                    _append_wrapped(lines, line_status, width, indent="  ")
                    _append_wrapped(lines, line_metrics, width, indent="  ")
                    lines.append("-" * min(width, 88))
                else:
                    row = (
                        f"{snap['line_id']:<3} {snap['name'][:12]:<12} "
                        f"{snap['preferred']:<9} "
                        f"{snap['port']:<11} {snap['link']:<11} {snap['down_for']:<15} "
                        f"{snap['devices']:<5} {snap['a1_req']:<18} {snap['a2_req']:<18} "
                        f"{snap['a1_timeout']:<22} {snap['a2_timeout']:<22} {snap['cmd_timeout']:<23} {snap['unmatched']:<13} "
                        f"{snap['qfull']:<11} {snap['queue']:<11} {snap['last_ok']}"
                    )
                    lines.append(_trim_text(row, width))
        else:
            lines.append("No lines registered.")

        lines.append("")
        lines.append("Devices")
        device_rows = []
        for poller in pollers:
            device_rows.extend(poller.get_device_metric_rows(nowt))
        compact_devices = width < 190
        if compact_devices:
            lines.append("-" * min(width, 88))
        else:
            lines.append(_trim_text("Line             Serial  NMS    Pair  Role     A1Req(H/T|H5/T5)  A2Req(H/T|H5/T5)  A1Timeout(H/T|H5/T5)  A2Timeout(H/T|H5/T5)  BadLen(H/T|H5/T5)  BadChk(H/T|H5/T5)", width))
            lines.append("-" * min(width, 190))

        if device_rows:
            for row in device_rows:
                if compact_devices:
                    header = (
                        f"line={row['line_id']}/{row['line_name']}  "
                        f"serial={row['serial_id']}  nms={row['nms_id']}  "
                        f"pair={row['pair_id']}  role={row['role']}"
                    )
                    metrics = (
                        f"a1_req={row['a1_req']}  a2_req={row['a2_req']}  "
                        f"a1_to={row['a1_timeout']}  a2_to={row['a2_timeout']}  "
                        f"bad_len={row['bad_len']}  bad_chk={row['bad_chk']}"
                    )
                    _append_wrapped(lines, header, width)
                    _append_wrapped(lines, metrics, width, indent="  ")
                    lines.append("-" * min(width, 88))
                else:
                    out = (
                        f"{(str(row['line_id']) + '/' + str(row['line_name']))[:16]:<16} "
                        f"{row['serial_id']:<7} {row['nms_id']:<6} "
                        f"{str(row['pair_id'])[:5]:<5} {str(row['role'])[:8]:<8} "
                        f"{row['a1_req']:<18} {row['a2_req']:<18} "
                        f"{row['a1_timeout']:<22} {row['a2_timeout']:<22} "
                        f"{row['bad_len']:<20} {row['bad_chk']:<20}"
                    )
                    lines.append(_trim_text(out, width))
        else:
            lines.append("No devices registered.")

        lines.append("")
        lines.append("Recent events")
        lines.append("-" * min(width, 110))
        display_events = events[-min(10, self.event_capacity):]
        if display_events:
            for event in display_events:
                prefix = f"{event['ts']} {event['level']:<5} [{event['category']}]"
                if event.get("line_id") is not None:
                    prefix += f" line={event['line_id']}"
                if event.get("port"):
                    prefix += f" port={event['port']}"
                lines.append(_trim_text(f"{prefix} {event['message']}", width))
        else:
            lines.append("No recent events.")

        return "\n".join(lines)


def _infer_level(message: str, default: str = "INFO") -> str:
    msg = str(message).upper()
    if "[FATAL]" in msg or "[ERROR]" in msg:
        return "ERROR"
    if "[WARN]" in msg or "FAILED" in msg or " DOWN" in msg:
        return "WARN"
    return default.upper()


def _infer_category(message: str, default: str = "general") -> str:
    msg = str(message)
    if msg.startswith("[Redis]") or "[Redis]" in msg:
        return "redis"
    if msg.startswith("[PORT]") or "[PORT]" in msg:
        return "port"
    if msg.startswith("[Cmd") or "[Cmd" in msg or msg.startswith("CMD "):
        return "cmd"
    if "[DLQ]" in msg:
        return "dlq"
    if "[STATUS]" in msg:
        return "poll"
    return default


def emit_event(
    message: str,
    *,
    level: str = "INFO",
    category: Optional[str] = None,
    line_id: Optional[int] = None,
    line_name: Optional[str] = None,
    port: Optional[str] = None,
    record_event: bool = True,
    plain_output: bool = True,
):
    final_level = _infer_level(message, default=level)
    final_category = _infer_category(message, default=category or "general")
    if CONSOLE is not None:
        CONSOLE.emit(
            level=final_level,
            category=final_category,
            message=message,
            line_id=line_id,
            line_name=line_name,
            port=port,
            record_event=record_event,
            plain_output=plain_output,
        )
        return
    print(_trim_text(message, 220), flush=True)


CONSOLE = ConsoleManager()

# ============================================================
# 帧常量
# ============================================================
FRAME_HEAD = b"\x7f\x7f"
REQUEST_TAIL = b"\xf7"
RESPONSE_TAIL = b"\xf7\xf7"

CMD_A1 = 0xA1
CMD_A2 = 0xA2
CMD_A9 = 0xA9
CMD_AA = 0xAA
CMD_B2 = 0xB2
CMD_NOCHANGE = 0x05

# ✅ 命令类：BB 控制命令收到 0x05 执行确认；CC 默认无回帧
CMD_BB = 0xBB
CMD_CC = 0xCC

# ✅ 无回帧命令集合：即使旧配置里带了 BB，也强制按“BB 等待 0x05”处理
_NO_RESP_FROM_CONFIG = _parse_hex_cmd_list(CMD_CONFIG.get("no_resp_cmds", ["CC"]))
NO_RESP_REQ_CMDS = set(_NO_RESP_FROM_CONFIG or [CMD_CC])
NO_RESP_REQ_CMDS.discard(CMD_BB)

ESCAPE_MAP = {
    0x7F: bytes([0x10, 0x81]),
    0xF7: bytes([0x10, 0x83]),
    0x10: bytes([0x10, 0x90]),
}
UNESCAPE_MAP = {
    0x81: 0x7F,
    0x83: 0xF7,
    0x90: 0x10,
}


def handle_signal(sig, frame):
    global running
    running = False
    emit_event(f"caught signal {sig}, preparing to exit...", category="startup", record_event=True, plain_output=True)


for _sig in ("SIGINT", "SIGTERM"):
    if hasattr(signal, _sig):
        signal.signal(getattr(signal, _sig), handle_signal)


# ============================================================
# 工具函数
# ============================================================
def now_mono() -> float:
    return time.monotonic()


def frame_to_hex(frame: bytes) -> str:
    return frame.hex()


def is_disabled_port(name: Optional[str]) -> bool:
    if name is None:
        return True
    s = str(name).strip()
    return (s == "") or (s.upper() in ("NONE", "NULL", "DISABLED", "NO"))


def escape_body(body: bytes) -> bytes:
    out = bytearray()
    for b in body:
        mapped = ESCAPE_MAP.get(b)
        if mapped is None:
            out.append(b)
        else:
            out.extend(mapped)
    return bytes(out)


def unescape_body(body_escaped: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(body_escaped)
    while i < n:
        b = body_escaped[i]
        if b == 0x10 and (i + 1) < n:
            nxt = body_escaped[i + 1]
            mapped = UNESCAPE_MAP.get(nxt)
            if mapped is not None:
                out.append(mapped)
                i += 2
                continue
        out.append(b)
        i += 1
    return bytes(out)


def build_request_frame(addr: int, cmd: int, payload: bytes = b"") -> bytes:
    if not (0 <= addr <= 0xFF):
        raise ValueError("addr must be 0..255")
    body = bytes([addr & 0xFF, cmd & 0xFF]) + (payload or b"")
    body_escaped = escape_body(body)
    return FRAME_HEAD + body_escaped + REQUEST_TAIL


def build_a1_request(serial_id: int) -> bytes:
    return build_request_frame(serial_id, CMD_A1)


def build_a2_request(serial_id: int) -> bytes:
    return build_request_frame(serial_id, CMD_A2)


def seconds_since_2010() -> int:
    base_utc = 1262304000
    return int(time.time() - base_utc)


def build_aa_request() -> bytes:
    sec = seconds_since_2010()
    t = sec.to_bytes(4, byteorder="big", signed=False)
    addr = 0xFF
    cmd = CMD_AA
    checksum = (addr + cmd + sum(t)) & 0xFF
    payload = t + bytes([checksum])
    return build_request_frame(addr, cmd, payload=payload)


def normalize_downlink_request_tail(frame: bytes) -> bytes:
    if not frame:
        return frame
    i = len(frame)
    while i > 0 and frame[i - 1] == 0xF7:
        i -= 1
    return frame[:i] + b"\xF7"


def is_double_f7_response(frame: bytes) -> bool:
    return frame.startswith(FRAME_HEAD) and frame.endswith(RESPONSE_TAIL) and len(frame) >= 6


def downlink_cmd_byte(req_frame: bytes) -> Optional[int]:
    """
    从下发请求帧中解析 cmd byte（第二个字节：addr, cmd, ...）
    """
    req_frame = normalize_downlink_request_tail(req_frame or b"")
    if (not req_frame) or (not req_frame.startswith(FRAME_HEAD)) or (not req_frame.endswith(REQUEST_TAIL)):
        return None
    try:
        body_escaped = req_frame[2:-1]
        body = unescape_body(body_escaped)
        if len(body) < 2:
            return None
        return int(body[1]) & 0xFF
    except Exception:
        return None


def rewrite_request_addr(req_frame: bytes, new_addr: int) -> Optional[bytes]:
    """
    把下发请求帧里的 addr（body[0]）改写为 new_addr，并重新做转义封装。
    请求帧格式：7f 7f <escaped(addr,cmd,payload...)> f7
    注意：A1/A2/B2/BB/CC 等请求本身不带校验，所以改 addr 不需要重算 checksum。
    """
    if req_frame is None:
        return None
    new_addr = int(new_addr) & 0xFF
    rf = normalize_downlink_request_tail(req_frame)

    if (not rf) or (not rf.startswith(FRAME_HEAD)) or (not rf.endswith(REQUEST_TAIL)):
        return None

    try:
        body_escaped = rf[2:-1]
        body = unescape_body(body_escaped)
        if len(body) < 2:
            return None

        old_addr = body[0] & 0xFF
        if old_addr == new_addr:
            return rf  # already ok

        body = bytes([new_addr]) + body[1:]
        body_escaped2 = escape_body(body)
        return FRAME_HEAD + body_escaped2 + REQUEST_TAIL
    except Exception:
        return None


def request_addr_byte(req_frame: bytes) -> Optional[int]:
    """仅用于日志/判断：解析请求帧当前 addr。"""
    rf = normalize_downlink_request_tail(req_frame or b"")
    if (not rf) or (not rf.startswith(FRAME_HEAD)) or (not rf.endswith(REQUEST_TAIL)):
        return None
    try:
        body = unescape_body(rf[2:-1])
        if len(body) < 1:
            return None
        return int(body[0]) & 0xFF
    except Exception:
        return None

def is_no_resp_request(req_frame: bytes) -> bool:
    if not SY_CMD_NO_RESP_ENABLE:
        return False
    cmd = downlink_cmd_byte(req_frame)
    if cmd is None:
        return False
    return (cmd & 0xFF) in NO_RESP_REQ_CMDS


def extract_response_frames_and_discard_requests(buf: bytearray) -> Tuple[List[bytes], int]:
    """
    ✅ 生产关键修复：
    - 如果缓冲末尾只有一个 0xF7（第二个 F7 还没到），绝不能当作请求帧丢弃，要等待更多字节。
    - 找不到 0x7f7f 头时，保留尾部一个 0x7f，避免头分包被清空。
    """
    frames: List[bytes] = []
    dropped_req = 0

    while True:
        start = buf.find(FRAME_HEAD)
        if start < 0:
            if len(buf) > 1:
                tail = buf[-1:]
                buf.clear()
                if tail == b"\x7f":
                    buf.extend(tail)
            break

        if start > 0:
            del buf[:start]

        f7_pos = buf.find(REQUEST_TAIL, len(FRAME_HEAD))
        if f7_pos < 0:
            break

        if (f7_pos + 1) >= len(buf):
            break

        if buf[f7_pos + 1] == 0xF7:
            frame_end = f7_pos + 2
            frames.append(bytes(buf[:frame_end]))
            del buf[:frame_end]
            continue

        frame_end = f7_pos + 1
        del buf[:frame_end]
        dropped_req += 1

    return frames, dropped_req


def parse_resp_addr_cmd_and_body(frame: bytes) -> Tuple[int, int, bytes]:
    if not is_double_f7_response(frame):
        raise ValueError("not a double-f7 response")
    body_escaped = frame[2:-2]
    body = unescape_body(body_escaped)
    if len(body) < 2:
        raise ValueError("body too short")
    return body[0], body[1], body


def checksum_ok_strict(frame: bytes) -> bool:
    _addr, cmd, body = parse_resp_addr_cmd_and_body(frame)

    if cmd == CMD_NOCHANGE:
        return len(body) == 2

    if len(body) < 3:
        return False

    data_plus = body[:-1]
    h = body[-1]
    return (sum(data_plus) & 0xFF) == h


def checksum_ok_lenient(frame: bytes) -> bool:
    _addr, cmd, body = parse_resp_addr_cmd_and_body(frame)
    if cmd == CMD_NOCHANGE:
        return len(body) == 2
    if len(body) < 3:
        return True
    data_plus = body[:-1]
    h = body[-1]
    return (sum(data_plus) & 0xFF) == h


def resp_match_expected(frame: bytes, *, expected_serial_id: Optional[int], expected_req_cmd: Optional[str]) -> bool:
    try:
        addr, cmd, _body = parse_resp_addr_cmd_and_body(frame)
    except Exception:
        return False

    if expected_req_cmd in ("A1", "A2", "B2"):
        if expected_serial_id is None:
            return False
        if addr != (int(expected_serial_id) & 0xFF):
            return False

    if expected_req_cmd == "A1" and cmd != CMD_A1:
        return False
    if expected_req_cmd == "A2" and cmd not in (CMD_A2, CMD_NOCHANGE):
        return False
    if expected_req_cmd == "B2" and cmd != CMD_B2:
        return False

    if expected_req_cmd in ("A1", "A2", "B2"):
        if not checksum_ok_strict(frame):
            return False

    return True


def infer_expected_resp_cmds_from_request(req_frame: bytes) -> Optional[Tuple[int, ...]]:
    """
    依据请求帧推断期望响应命令。
    - CC 等 no-resp 命令：返回 None（不等待响应）
    - BB 远程控制：等待 0x05 执行确认帧
    - A2：A2 或 NOCHANGE 都算响应
    """
    req_frame = normalize_downlink_request_tail(req_frame or b"")
    if (not req_frame) or (not req_frame.startswith(FRAME_HEAD)) or (not req_frame.endswith(REQUEST_TAIL)):
        return None
    try:
        body_escaped = req_frame[2:-1]
        body = unescape_body(body_escaped)
        if len(body) < 2:
            return None
        cmd = int(body[1]) & 0xFF

        # ✅ no-resp cmds: do not wait for response
        if SY_CMD_NO_RESP_ENABLE and (cmd in NO_RESP_REQ_CMDS):
            return None

        if cmd == CMD_BB:
            return (CMD_NOCHANGE,)
        if cmd == CMD_A2:
            return (CMD_A2, CMD_NOCHANGE)
        return (cmd,)
    except Exception:
        return None


# ============================================================
# RTS 切换：软件层“伪485模式”
# ============================================================
def _set_rts(ser: serial.Serial, level: int):
    try:
        ser.rts = bool(level)
    except Exception:
        pass


def write_with_optional_rts_toggle(ser: serial.Serial, frame: bytes):
    if not DEBUG_TUNING["RTS_TOGGLE"]:
        ser.write(frame)
        ser.flush()
        return

    _set_rts(ser, int(DEBUG_TUNING["RTS_TX_LEVEL"]))
    pre = float(DEBUG_TUNING["RTS_PRE_DELAY_SEC"])
    post = float(DEBUG_TUNING["RTS_POST_DELAY_SEC"])
    if pre > 0:
        time.sleep(pre)

    ser.write(frame)
    ser.flush()

    if post > 0:
        time.sleep(post)
    _set_rts(ser, int(DEBUG_TUNING["RTS_RX_LEVEL"]))


# ============================================================
# EpochRef：避免 clear 时误删刚回来的正确帧
# ============================================================
class EpochRef:
    def __init__(self):
        self._lock = threading.Lock()
        self._v = 0

    def bump(self):
        with self._lock:
            self._v += 1
            return self._v

    def get(self) -> int:
        with self._lock:
            return self._v


# ============================================================
# ✅ 自适应 after_write_sleep：RTT 统计器 + no-resp 惩罚上调
# ============================================================
class AdaptiveSleep:
    def __init__(self):
        self.enable = bool(DEBUG_TUNING["AUTO_SLEEP_ENABLE"])
        self.window = int(DEBUG_TUNING["AUTO_SLEEP_WINDOW"])
        self.pctl = int(DEBUG_TUNING["AUTO_SLEEP_PCTL"])
        self.margin = float(DEBUG_TUNING["AUTO_SLEEP_MARGIN_SEC"])
        self.min_s = float(DEBUG_TUNING["AUTO_SLEEP_MIN_SEC"])
        self.max_s = float(DEBUG_TUNING["AUTO_SLEEP_MAX_SEC"])
        self.update_every = int(DEBUG_TUNING["AUTO_SLEEP_UPDATE_EVERY"])
        self.print_every = float(DEBUG_TUNING["AUTO_SLEEP_PRINT_EVERY_SEC"])

        self.no_bump = float(DEBUG_TUNING["AUTO_SLEEP_NO_RESP_BUMP_SEC"])
        self.no_streak_th = int(DEBUG_TUNING["AUTO_SLEEP_NO_RESP_STREAK"])
        self.no_cooldown = float(DEBUG_TUNING["AUTO_SLEEP_NO_RESP_COOLDOWN_SEC"])

        self.decay_ok_streak = int(DEBUG_TUNING["AUTO_SLEEP_DECAY_OK_STREAK"])
        self.decay_step = float(DEBUG_TUNING["AUTO_SLEEP_DECAY_STEP_SEC"])

        self._rtts: Deque[float] = deque(maxlen=self.window)  # seconds
        self._lock = threading.Lock()
        self._cur_sleep = float(DEBUG_TUNING["AFTER_WRITE_SLEEP_SEC"])
        self._ok_count = 0
        self._ok_streak = 0
        self._no_streak = 0
        self._last_print = now_mono()
        self._last_no_bump = 0.0

    def get_sleep(self) -> float:
        if not self.enable:
            return float(DEBUG_TUNING["AFTER_WRITE_SLEEP_SEC"])
        with self._lock:
            return float(self._cur_sleep)

    def _clamp(self, x: float) -> float:
        if x < self.min_s:
            return self.min_s
        if x > self.max_s:
            return self.max_s
        return x

    def on_resp_ok(self, rtt_sec: float):
        if not self.enable:
            return
        with self._lock:
            rtt_sec = float(rtt_sec)
            self._rtts.append(rtt_sec)
            self._ok_count += 1
            self._ok_streak += 1
            self._no_streak = 0

            do_update = (self._ok_count % max(1, self.update_every)) == 0

            if do_update and len(self._rtts) >= 8:
                arr = sorted(self._rtts)
                p = max(0, min(100, self.pctl))
                idx = int(round((p / 100.0) * (len(arr) - 1)))
                base = float(arr[idx])
                new_sleep = self._clamp(base + self.margin)
                self._cur_sleep = new_sleep

            if self.decay_ok_streak > 0 and self._ok_streak >= self.decay_ok_streak:
                if len(self._rtts) >= 8:
                    self._cur_sleep = self._clamp(self._cur_sleep - self.decay_step)
                self._ok_streak = 0

            nowt = now_mono()
            if (nowt - self._last_print) >= self.print_every and len(self._rtts) >= 8:
                self._last_print = nowt
                arr = sorted(self._rtts)
                p50 = arr[int(round(0.50 * (len(arr) - 1)))]
                p95 = arr[int(round(0.95 * (len(arr) - 1)))]
                p99 = arr[int(round(0.99 * (len(arr) - 1)))]
                mx = arr[-1]
                cur = self._cur_sleep
                emit_event(
                    f"[TUNE] RTT(p50/p95/p99/max)={p50*1000:.1f}/{p95*1000:.1f}/{p99*1000:.1f}/{mx*1000:.1f}ms "
                    f"=> auto_after_sleep={cur:.3f}s (margin={self.margin:.3f}s)",
                    category="poll",
                    record_event=False,
                )

    def on_no_resp(self):
        if not self.enable:
            return
        with self._lock:
            self._no_streak += 1
            self._ok_streak = 0

            nowt = now_mono()
            if self._no_streak >= self.no_streak_th and (nowt - self._last_no_bump) >= self.no_cooldown:
                self._last_no_bump = nowt
                old = self._cur_sleep
                self._cur_sleep = self._clamp(self._cur_sleep + self.no_bump)
                emit_event(
                    f"[TUNE] no-resp streak={self._no_streak} => bump after_sleep {old:.3f}s -> {self._cur_sleep:.3f}s",
                    category="poll",
                    level="WARN",
                )


ADAPT = AdaptiveSleep()


# ============================================================
# Redis 连接管理：连不上/断线都不退出，自动重连
# ============================================================
class RedisDown(Exception):
    pass


def _b2s(x) -> str:
    if x is None:
        return ""
    if isinstance(x, (bytes, bytearray)):
        return x.decode("utf-8", errors="replace")
    return str(x)


class RedisConn:
    def __init__(self, *, host: str, port: int, db: int):
        self.host = host
        self.port = port
        self.db = db

        self._lock = threading.Lock()
        self._r: Optional[redis.Redis] = None
        self._ready = threading.Event()
        self._last_err = ""
        self._last_change = now_mono()

        self._retry = float(DEBUG_TUNING["REDIS_RETRY_MIN_SEC"])
        self._retry_min = float(DEBUG_TUNING["REDIS_RETRY_MIN_SEC"])
        self._retry_max = float(DEBUG_TUNING["REDIS_RETRY_MAX_SEC"])

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def last_error(self) -> str:
        with self._lock:
            return self._last_err

    def _set_state(self, ready: bool, err: str = ""):
        with self._lock:
            if ready:
                self._last_err = ""
                self._retry = self._retry_min
                self._ready.set()
            else:
                self._last_err = err or self._last_err
                self._ready.clear()
            self._last_change = now_mono()

    def _make_redis(self) -> redis.Redis:
        return redis.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            decode_responses=False,
            socket_timeout=5,
            socket_connect_timeout=5,
            health_check_interval=30,
        )

    def _ensure_group(self, r: redis.Redis, stream: str, group: str):
        """
        ✅ 建议：命令流 group 新建时从“现在”开始（$），避免首次上线误消费历史命令。
        """
        try:
            r.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
            if DEBUG_TUNING["LOG_REDIS_STATE"]:
                emit_event(
                    f"[Redis] xgroup_create OK: stream={stream}, group={group}, id=$",
                    category="redis",
                )
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                return
            raise

    def connect_once(self) -> bool:
        try:
            r = self._make_redis()
            r.ping()
            self._ensure_group(r, SY_CMD_STREAM, SY_CMD_GROUP)

            with self._lock:
                self._r = r

            self._set_state(True)
            if DEBUG_TUNING["LOG_REDIS_STATE"]:
                emit_event(
                    f"[Redis] CONNECTED target={self.host}:{self.port}/{self.db}",
                    category="redis",
                )
            return True
        except Exception as e:
            self._set_state(False, err=str(e))
            if DEBUG_TUNING["LOG_REDIS_STATE"]:
                emit_event(
                    f"[Redis] CONNECT FAILED target={self.host}:{self.port}/{self.db} err={e}",
                    category="redis",
                    level="WARN",
                )
            return False

    def mark_down(self, reason: str):
        with self._lock:
            r = self._r
            self._r = None
        self._set_state(False, err=reason)
        try:
            if r is not None:
                try:
                    r.connection_pool.disconnect()
                except Exception:
                    pass
        except Exception:
            pass
        if DEBUG_TUNING["LOG_REDIS_STATE"]:
            emit_event(f"[Redis] DOWN: {reason}", category="redis", level="WARN")

    def get_client(self) -> redis.Redis:
        if not self.is_ready():
            raise RedisDown(self.last_error() or "redis not ready")
        with self._lock:
            if self._r is None:
                raise RedisDown(self.last_error() or "redis not ready")
            return self._r

    def xadd_json(self, stream: str, data: dict, maxlen: int) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            r = self.get_client()
            r.xadd(stream, {"data": payload}, maxlen=maxlen, approximate=True)
        except Exception as e:
            self.mark_down(str(e))
            raise

    def xreadgroup(self, *, group: str, consumer: str, stream: str, count: int, block_ms: int):
        try:
            r = self.get_client()
            return r.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
        except Exception as e:
            self.mark_down(str(e))
            raise

    def xack(self, stream: str, group: str, msg_id):
        try:
            r = self.get_client()
            r.xack(stream, group, msg_id)
        except Exception as e:
            self.mark_down(str(e))
            raise

    def xautoclaim(self, *, stream: str, group: str, consumer: str, min_idle_ms: int, start_id: str, count: int):
        try:
            r = self.get_client()
            if hasattr(r, "xautoclaim"):
                return r.xautoclaim(stream, group, consumer, min_idle_ms, start_id, count=count)
            return r.execute_command("XAUTOCLAIM", stream, group, consumer, min_idle_ms, start_id, "COUNT", count)
        except Exception as e:
            self.mark_down(str(e))
            raise

    # ✅ 生产：DLQ 写入（可选去重）
    def dlq_push(self, *, reason: str, msg_id, fields: dict, extra: Optional[dict] = None):
        try:
            r = self.get_client()

            dedupe_key = f"{SY_CMD_DLQ_DEDUPE_PREFIX}{_b2s(msg_id)}:{reason}"
            try:
                if SY_CMD_DLQ_DEDUPE_TTL_SEC > 0:
                    ok = r.set(dedupe_key, b"1", ex=int(SY_CMD_DLQ_DEDUPE_TTL_SEC), nx=True)
                    if not ok:
                        return
            except Exception:
                pass

            agent_info = {
                "host": socket.gethostname(),
                "agent_ip": AGENT_IP,
                "agent_name": AGENT_NAME,
                "consumer": SY_CMD_CONSUMER,
                "pid": os.getpid(),
            }

            payload = {
                "reason": reason,
                "msg_id": _b2s(msg_id),
                "fields": {(_b2s(k)): _b2s(v) for k, v in (fields or {}).items()},
                "extra": {**agent_info, **(extra or {})},
                "ts": int(time.time()),
            }
            r.xadd(
                SY_CMD_DLQ_STREAM,
                {"data": json.dumps(payload, ensure_ascii=False).encode("utf-8")},
                maxlen=SY_CMD_DLQ_MAXLEN,
                approximate=True,
            )
        except Exception as e:
            if DEBUG_TUNING["LOG_REDIS_STATE"]:
                emit_event(f"[DLQ] push failed: {e}", category="dlq", level="ERROR")

    # ✅ 生产：命令去重（Redis key）
    def cmd_done_exists(self, key: str) -> bool:
        try:
            r = self.get_client()
            return bool(r.exists(key))
        except Exception as e:
            self.mark_down(str(e))
            raise

    def cmd_done_mark(self, key: str, ttl_sec: int) -> bool:
        try:
            r = self.get_client()
            ok = r.set(key, b"1", ex=int(ttl_sec), nx=True)
            return bool(ok)
        except Exception as e:
            self.mark_down(str(e))
            raise

    # ✅ 新增：计数器 + TTL（用于命令重试上限）
    def incr_with_ttl(self, key: str, ttl_sec: int) -> int:
        try:
            r = self.get_client()
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, int(ttl_sec))
            v, _ = pipe.execute()
            return int(v)
        except Exception as e:
            self.mark_down(str(e))
            raise

    def set_text(self, key: str, value: str, ttl_sec: Optional[int] = None) -> None:
        try:
            r = self.get_client()
            if ttl_sec and int(ttl_sec) > 0:
                r.set(key, str(value), ex=int(ttl_sec))
            else:
                r.set(key, str(value))
        except Exception as e:
            self.mark_down(str(e))
            raise

    def set_json(self, key: str, data: dict, ttl_sec: Optional[int] = None) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        self.set_text(key, payload, ttl_sec=ttl_sec)

    def keepalive_loop(self):
        while running:
            if not self.is_ready():
                ok = self.connect_once()
                if ok:
                    continue
                time.sleep(self._retry)
                self._retry = min(self._retry * 2.0, self._retry_max)
            else:
                try:
                    r = self.get_client()
                    r.ping()
                    time.sleep(1.0)
                except Exception as e:
                    self.mark_down(str(e))
                    time.sleep(self._retry)


# ============================================================
# PortReceiver：每口一个接收线程（唯一读者）
# + last_good_frame_mono：用于 stall watchdog
# ============================================================
class PortReceiver(threading.Thread):
    def __init__(
        self,
        *,
        line_id: int,
        line_name: str,
        which: str,
        ser: serial.Serial,
        ser_lock: threading.Lock,
        out_q: "queue.Queue[dict]",
        epoch_ref: "EpochRef",
        on_fatal: Callable[[str, str], None],
    ):
        super().__init__(daemon=True)
        self.line_id = line_id
        self.line_name = line_name
        self.which = which
        self.ser = ser
        self.ser_lock = ser_lock
        self.out_q = out_q
        self.epoch_ref = epoch_ref
        self.on_fatal = on_fatal

        self.buf = bytearray()
        self.req_clear = threading.Event()
        self.stop_evt = threading.Event()

        # stats
        self.drop_single_f7 = 0
        self.drop_parse_err = 0
        self.drop_bad_checksum = 0
        self.drop_q_full = 0          # ✅ 新增：队列满丢帧计数（用于定位“假 NO_RESP”）
        self.rx_frames_ok = 0
        self._rx_err_streak = 0

        self._last_good_frame_mono = now_mono()
        self._last_good_lock = threading.Lock()

    def last_good_frame_mono(self) -> float:
        with self._last_good_lock:
            return float(self._last_good_frame_mono)

    def _touch_good(self):
        with self._last_good_lock:
            self._last_good_frame_mono = now_mono()

    def _put_bad_frame(self, kind: str, frame: bytes, epoch: int, *, addr: Optional[int] = None, cmd: Optional[int] = None):
        item = {
            "bad_frame": kind,
            "frame": frame,
            "addr": addr,
            "cmd": cmd,
            "tmono": now_mono(),
            "line_id": self.line_id,
            "port": self.which,
            "epoch": epoch,
        }
        try:
            self.out_q.put_nowait(item)
        except queue.Full:
            self.drop_q_full += 1

    def log(self, msg: str):
        emit_event(msg, line_id=self.line_id, line_name=self.line_name, port=self.which)

    def request_clear(self):
        self.req_clear.set()

    def stop(self):
        self.stop_evt.set()

    def _do_clear(self):
        self.epoch_ref.bump()
        self.buf.clear()
        try:
            with self.ser_lock:
                if self.ser and self.ser.is_open:
                    self.ser.reset_input_buffer()
        except Exception:
            pass

    def run(self):
        self.log("receiver thread started.")
        while running and (not self.stop_evt.is_set()):
            if self.req_clear.is_set():
                self.req_clear.clear()
                self._do_clear()

            try:
                with self.ser_lock:
                    if not self.ser or (not self.ser.is_open):
                        raise SerialException("serial not open")
                    try:
                        n = int(getattr(self.ser, "in_waiting", 0) or 0)
                    except Exception:
                        n = 0

                    if n > 0:
                        n = min(n, int(DEBUG_TUNING["MAX_READ_ONCE"]))
                        data = self.ser.read(n)
                    else:
                        data = self.ser.read(1)
            except SerialException as e:
                self._rx_err_streak += 1
                if self._rx_err_streak >= int(DEBUG_TUNING["SERIAL_RX_ERROR_LIMIT"]):
                    self.log(f"[FATAL] RX SerialException streak={self._rx_err_streak}: {e}")
                    try:
                        self.on_fatal(self.which, str(e))
                    except Exception:
                        pass
                    break
                time.sleep(0.01)
                continue
            except Exception:
                self._rx_err_streak += 1
                time.sleep(0.01)
                continue

            self._rx_err_streak = 0

            if not data:
                time.sleep(float(DEBUG_TUNING["RX_IDLE_SLEEP_SEC"]))
                continue

            self.buf.extend(data)

            if len(self.buf) > int(DEBUG_TUNING["MAX_SOFTBUF"]):
                self.log(f"[WARN] softbuf too large ({len(self.buf)}), flushing softbuf")
                self.buf.clear()
                continue

            frames, dropped_req = extract_response_frames_and_discard_requests(self.buf)
            if dropped_req:
                self.drop_single_f7 += dropped_req

            cur_epoch = self.epoch_ref.get()

            for f in frames:
                try:
                    addr, cmd, body = parse_resp_addr_cmd_and_body(f)
                except Exception:
                    self.drop_parse_err += 1
                    self._put_bad_frame("bad_len", f, cur_epoch)
                    continue

                if cmd in (CMD_A1, CMD_A2, CMD_B2):
                    if len(body) < 3:
                        self.drop_parse_err += 1
                        self._put_bad_frame("bad_len", f, cur_epoch, addr=addr, cmd=cmd)
                        continue
                    if not checksum_ok_strict(f):
                        self.drop_bad_checksum += 1
                        self._put_bad_frame("bad_chk", f, cur_epoch, addr=addr, cmd=cmd)
                        continue
                elif cmd == CMD_NOCHANGE:
                    if len(body) != 2:
                        self.drop_parse_err += 1
                        self._put_bad_frame("bad_len", f, cur_epoch, addr=addr, cmd=cmd)
                        continue
                else:
                    if not checksum_ok_lenient(f):
                        self.drop_bad_checksum += 1
                        self._put_bad_frame("bad_chk", f, cur_epoch, addr=addr, cmd=cmd)
                        continue

                self._touch_good()

                item = {
                    "frame": f,
                    "addr": addr,
                    "cmd": cmd,
                    "tmono": now_mono(),
                    "line_id": self.line_id,
                    "port": self.which,
                    "epoch": cur_epoch,
                }
                try:
                    self.out_q.put_nowait(item)
                    self.rx_frames_ok += 1
                except queue.Full:
                    self.drop_q_full += 1

        if DEBUG_TUNING["LOG_RX_STATS"]:
            self.log(
                f"receiver thread stopped. ok={self.rx_frames_ok}, "
                f"drop_single_f7={self.drop_single_f7}, drop_parse_err={self.drop_parse_err}, "
                f"drop_bad_checksum={self.drop_bad_checksum}, drop_q_full={self.drop_q_full}"
            )


# ============================================================
# LinePoller：轮询线程（只写 + 等队列匹配） + 串口自动重连 + Redis down 暂停
# + 命令执行后再 ACK
# + RX 线程死掉重连
# + 串口假死 watchdog
# + ✅ 生产：命令去重 + 本地 done 兜底
# ============================================================
class LinePoller(threading.Thread):
    def __init__(self, cfg: dict, redis_conn: RedisConn):
        super().__init__(daemon=True)

        self.line_id = int(cfg.get("line_id", 0))
        self.name = cfg.get("name", f"Line-{self.line_id}")

        self.head_port_name = cfg.get("head_port")
        self.tail_port_name = cfg.get("tail_port")
        ring_cfg = cfg.get("ring_mode")
        if ring_cfg is None:
            self.ring_mode = (not is_disabled_port(self.head_port_name)) and (not is_disabled_port(self.tail_port_name))
        else:
            self.ring_mode = bool(ring_cfg)

        self.baudrate = int(cfg.get("baudrate", DEFAULT_BAUDRATE))
        self.timeout = float(cfg.get("timeout", DEFAULT_TIMEOUT))
        self.devices_cfg = cfg.get("devices", [])
        self.redis_conn = redis_conn

        self.ser_head: Optional[serial.Serial] = None
        self.ser_tail: Optional[serial.Serial] = None
        self.lock_head = threading.Lock()
        self.lock_tail = threading.Lock()

        self.epoch_head = EpochRef()
        self.epoch_tail = EpochRef()

        self.q_head: "queue.Queue[dict]" = queue.Queue(maxsize=4096)
        self.q_tail: "queue.Queue[dict]" = queue.Queue(maxsize=4096)
        self.rx_head: Optional[PortReceiver] = None
        self.rx_tail: Optional[PortReceiver] = None

        self.command_queue: "queue.Queue[dict]" = queue.Queue()

        self.serial_to_nms: Dict[int, int] = {}
        self.nms_to_serial: Dict[int, int] = {}

        self.dev_state: Dict[int, dict] = {}
        self.device_pair_role: Dict[int, Tuple[str, str]] = {}
        self.pair_state: Dict[str, dict] = {}
        pair_candidates: Dict[str, dict] = {}
        pair_warnings: List[str] = []
        t0 = now_mono()
        for d in self.devices_cfg:
            serial_id = int(d["serial_id"])
            nms_id = int(d.get("nms_id", serial_id))
            d["nms_id"] = nms_id
            self.serial_to_nms[serial_id] = nms_id
            self.nms_to_serial[nms_id] = serial_id
            self.dev_state[serial_id] = {"last_a1_mono": t0, "last_good_side": "head"}
            pair_id = str(d.get("pair_id", "")).strip()
            role = self._normalize_pair_role(d.get("role"))
            if pair_id and role:
                d["pair_id"] = pair_id
                d["role"] = role
                pair_candidates.setdefault(pair_id, {"primary": [], "backup": []})[role].append(serial_id)
            elif pair_id or str(d.get("role", "")).strip():
                pair_warnings.append(
                    f"[PAIR] ignored incomplete pair config serial_id={serial_id} pair_id={pair_id or '-'} role={d.get('role', '-')}"
                )

        for pair_id, roles in pair_candidates.items():
            primaries = roles.get("primary", [])
            backups = roles.get("backup", [])
            if len(primaries) != 1 or len(backups) != 1:
                pair_warnings.append(
                    f"[PAIR] ignored invalid pair_id={pair_id}: primary={primaries or '-'} backup={backups or '-'}"
                )
                continue
            primary_serial = int(primaries[0])
            backup_serial = int(backups[0])
            self.device_pair_role[primary_serial] = (pair_id, "primary")
            self.device_pair_role[backup_serial] = (pair_id, "backup")
            self.pair_state[pair_id] = {
                "primary_serial": primary_serial,
                "backup_serial": backup_serial,
                "primary_a1_fail_streak": 0,
                "active_role": "primary",
            }

        self.next_time_sync_mono = t0 + TIME_SYNC_INTERVAL if TIME_SYNC_ENABLE else float("inf")
        self.dev_idx = 0 if self.devices_cfg else -1

        self.stash: Dict[Tuple[str, int, int, int], List[dict]] = {}
        self.stash_max_per_key = 8
        self.stash_keep_seconds = 1.2

        self.drop_unmatched = 0
        self.unmatched_times: Deque[float] = deque()
        self.last_unmatched_mono = 0.0
        self.seq_send = 0
        self.req_counts = {
            "a1": {"head": 0, "tail": 0},
            "a2": {"head": 0, "tail": 0},
        }
        self.req_times = {
            "a1": {"head": deque(), "tail": deque()},
            "a2": {"head": deque(), "tail": deque()},
        }
        self.no_resp_counts = {
            "a1": {"head": 0, "tail": 0},
            "a2": {"head": 0, "tail": 0},
            "cmd": {"head": 0, "tail": 0},
        }
        self.no_resp_side_times = {
            "a1": {"head": deque(), "tail": deque()},
            "a2": {"head": deque(), "tail": deque()},
            "cmd": {"head": deque(), "tail": deque()},
        }
        self.device_req_counts = {
            "a1": {},
            "a2": {},
        }
        self.device_req_times = {
            "a1": {},
            "a2": {},
        }
        self.device_no_resp_counts = {
            "a1": {},
            "a2": {},
        }
        self.device_no_resp_times = {
            "a1": {},
            "a2": {},
        }
        self.device_bad_frame_counts = {
            "bad_len": {},
            "bad_chk": {},
        }
        self.device_bad_frame_times = {
            "bad_len": {},
            "bad_chk": {},
        }
        self.a1_no_resp_count = 0
        self.a2_no_resp_count = 0
        self.cmd_no_resp_count = 0
        self.a1_no_resp_times: Deque[float] = deque()
        self.a2_no_resp_times: Deque[float] = deque()
        self.cmd_no_resp_times: Deque[float] = deque()
        self.last_a1_no_resp_mono = 0.0
        self.last_a2_no_resp_mono = 0.0
        self.last_cmd_no_resp_mono = 0.0
        self.last_ok_mono = 0.0
        self.last_ok_side = "-"

        self._port_retry = {
            "head": {"next": 0.0, "delay": float(DEBUG_TUNING["SERIAL_RETRY_MIN_SEC"]), "min": float(DEBUG_TUNING["SERIAL_RETRY_MIN_SEC"]), "max": float(DEBUG_TUNING["SERIAL_RETRY_MAX_SEC"])},
            "tail": {"next": 0.0, "delay": float(DEBUG_TUNING["SERIAL_RETRY_MIN_SEC"]), "min": float(DEBUG_TUNING["SERIAL_RETRY_MIN_SEC"]), "max": float(DEBUG_TUNING["SERIAL_RETRY_MAX_SEC"])},
        }

        self._port_open_mono = {"head": 0.0, "tail": 0.0}
        self._port_down_since = {
            "head": 0.0 if is_disabled_port(self.head_port_name) else t0,
            "tail": 0.0 if is_disabled_port(self.tail_port_name) else t0,
        }
        self._last_stall_action_mono = {"head": 0.0, "tail": 0.0}

        self._last_status_print = now_mono()

        # ✅ 生产：本地 done 兜底（短暂 Redis 抖动时避免重复执行）
        self._done_local: Dict[str, float] = {}  # msg_id_str -> expire_mono
        self._done_local_lock = threading.Lock()

        for warning in pair_warnings:
            emit_event(warning, level="WARN", category="poll", line_id=self.line_id, line_name=self.name)

    def log(self, msg: str):
        emit_event(msg, line_id=self.line_id, line_name=self.name)

    @staticmethod
    def _normalize_pair_role(value) -> Optional[str]:
        text = str(value or "").strip().lower()
        if text in ("primary", "main", "master", "主", "主机"):
            return "primary"
        if text in ("backup", "standby", "secondary", "备", "备机"):
            return "backup"
        return None

    def _should_skip_pair_a2(self, serial_id: int) -> bool:
        pair_ref = self.device_pair_role.get(int(serial_id))
        if not pair_ref:
            return False
        pair_id, role = pair_ref
        active_role = str(self.pair_state.get(pair_id, {}).get("active_role", "primary"))
        return role != active_role

    def _effective_a1_interval(self, serial_id: int, base_interval: float) -> float:
        pair_ref = self.device_pair_role.get(int(serial_id))
        if not pair_ref:
            return base_interval
        pair_id, role = pair_ref
        active_role = str(self.pair_state.get(pair_id, {}).get("active_role", "primary"))
        if role == "backup" and active_role == "primary":
            return base_interval * 3.0
        return base_interval

    def _update_pair_after_poll(self, *, serial_id: int, req_cmd: str, responded: bool) -> None:
        pair_ref = self.device_pair_role.get(int(serial_id))
        if not pair_ref:
            return
        pair_id, role = pair_ref
        if role != "primary" or req_cmd != "A1":
            return

        state = self.pair_state.get(pair_id)
        if not state:
            return

        if responded:
            previous_streak = int(state.get("primary_a1_fail_streak", 0) or 0)
            previous_active = str(state.get("active_role", "primary"))
            state["primary_a1_fail_streak"] = 0
            state["active_role"] = "primary"
            if previous_active != "primary" or previous_streak > 0:
                self.log(f"[PAIR] pair_id={pair_id} primary A1 recovered -> active_role=primary")
            return

        streak = int(state.get("primary_a1_fail_streak", 0) or 0) + 1
        state["primary_a1_fail_streak"] = streak
        if streak >= PRIMARY_A1_FAILOVER_THRESHOLD and state.get("active_role") != "backup":
            state["active_role"] = "backup"
            self.log(
                f"[PAIR] pair_id={pair_id} primary A1 failed {streak} times -> active_role=backup"
            )

    @staticmethod
    def _metric_kind(req_cmd: Optional[str]) -> Optional[str]:
        text = str(req_cmd or "").strip().lower()
        if text == "a1":
            return "a1"
        if text == "a2":
            return "a2"
        return None

    @staticmethod
    def _side_name(side: Optional[str]) -> Optional[str]:
        text = str(side or "").strip().lower()
        return text if text in ("head", "tail") else None

    def _prune_metric_times(self, buf: Deque[float], nowt: float) -> int:
        while buf and (nowt - float(buf[0])) > NO_RESP_WINDOW_SEC:
            buf.popleft()
        return len(buf)

    def _ensure_device_metric(self, container: dict, kind: str, serial_id: Optional[int], *, times: bool):
        if kind not in container or serial_id is None:
            return None
        try:
            sid = int(serial_id)
        except Exception:
            return None
        default_value = {"head": deque(), "tail": deque()} if times else {"head": 0, "tail": 0}
        return container[kind].setdefault(sid, default_value)

    def record_request(self, kind: str, side: Optional[str], serial_id: Optional[int] = None):
        side_name = self._side_name(side)
        if kind not in self.req_counts or side_name is None:
            return
        nowt = now_mono()
        self.req_counts[kind][side_name] += 1
        self.req_times[kind][side_name].append(nowt)
        self._prune_metric_times(self.req_times[kind][side_name], nowt)
        dev_counts = self._ensure_device_metric(self.device_req_counts, kind, serial_id, times=False)
        dev_times = self._ensure_device_metric(self.device_req_times, kind, serial_id, times=True)
        if dev_counts is not None and dev_times is not None:
            dev_counts[side_name] += 1
            dev_times[side_name].append(nowt)
            self._prune_metric_times(dev_times[side_name], nowt)

    def recent_request_count(self, kind: str, side: Optional[str] = None, nowt: Optional[float] = None) -> int:
        nowt = time.monotonic() if nowt is None else float(nowt)
        if kind not in self.req_times:
            return 0
        side_name = self._side_name(side)
        if side_name is not None:
            return self._prune_metric_times(self.req_times[kind][side_name], nowt)
        return sum(self._prune_metric_times(self.req_times[kind][item], nowt) for item in ("head", "tail"))

    def _side_count_total(self, kind: str, *, no_resp: bool = True) -> int:
        source = self.no_resp_counts if no_resp else self.req_counts
        if kind not in source:
            return 0
        return int(source[kind].get("head", 0)) + int(source[kind].get("tail", 0))

    def _format_side_metric(self, kind: str, *, no_resp: bool, nowt: Optional[float] = None) -> str:
        nowt = time.monotonic() if nowt is None else float(nowt)
        if no_resp:
            counts = self.no_resp_counts.get(kind, {})
            times = self.no_resp_side_times.get(kind, {})
        else:
            counts = self.req_counts.get(kind, {})
            times = self.req_times.get(kind, {})
        head_total = int(counts.get("head", 0) or 0)
        tail_total = int(counts.get("tail", 0) or 0)
        head_recent = self._prune_metric_times(times.get("head", deque()), nowt) if times else 0
        tail_recent = self._prune_metric_times(times.get("tail", deque()), nowt) if times else 0
        return f"{head_total}/{tail_total} | {head_recent}/{tail_recent}"

    def _format_device_metric(self, kind: str, serial_id: int, *, no_resp: bool, nowt: Optional[float] = None) -> str:
        nowt = time.monotonic() if nowt is None else float(nowt)
        if no_resp:
            counts = self.device_no_resp_counts.get(kind, {}).get(int(serial_id), {})
            times = self.device_no_resp_times.get(kind, {}).get(int(serial_id), {})
        else:
            counts = self.device_req_counts.get(kind, {}).get(int(serial_id), {})
            times = self.device_req_times.get(kind, {}).get(int(serial_id), {})
        head_total = int(counts.get("head", 0) or 0)
        tail_total = int(counts.get("tail", 0) or 0)
        head_recent = self._prune_metric_times(times.get("head", deque()), nowt) if times else 0
        tail_recent = self._prune_metric_times(times.get("tail", deque()), nowt) if times else 0
        return f"{head_total}/{tail_total} | {head_recent}/{tail_recent}"

    def _format_device_bad_frame_metric(self, kind: str, serial_id: int, *, nowt: Optional[float] = None) -> str:
        nowt = time.monotonic() if nowt is None else float(nowt)
        counts = self.device_bad_frame_counts.get(kind, {}).get(int(serial_id), {})
        times = self.device_bad_frame_times.get(kind, {}).get(int(serial_id), {})
        head_total = int(counts.get("head", 0) or 0)
        tail_total = int(counts.get("tail", 0) or 0)
        head_recent = self._prune_metric_times(times.get("head", deque()), nowt) if times else 0
        tail_recent = self._prune_metric_times(times.get("tail", deque()), nowt) if times else 0
        return f"{head_total}/{tail_total} | {head_recent}/{tail_recent}"

    def record_bad_frame(self, kind: str, side: Optional[str], serial_id: Optional[int]) -> None:
        side_name = self._side_name(side)
        if kind not in self.device_bad_frame_counts or side_name is None or serial_id is None:
            return
        try:
            sid = int(serial_id)
        except Exception:
            return
        if sid not in self.dev_state:
            return
        nowt = now_mono()
        dev_counts = self._ensure_device_metric(self.device_bad_frame_counts, kind, sid, times=False)
        dev_times = self._ensure_device_metric(self.device_bad_frame_times, kind, sid, times=True)
        if dev_counts is None or dev_times is None:
            return
        dev_counts[side_name] += 1
        dev_times[side_name].append(nowt)
        self._prune_metric_times(dev_times[side_name], nowt)

    def _record_bad_item_for_window(self, item: dict, *, expected_serial_id: Optional[int]) -> None:
        kind = str(item.get("bad_frame") or "")
        if kind == "bad_len":
            target_serial_id = expected_serial_id
        elif kind == "bad_chk":
            target_serial_id = item.get("addr")
        else:
            return
        self.record_bad_frame(kind, item.get("port"), target_serial_id)

    def get_device_metric_rows(self, nowt: Optional[float] = None) -> List[dict]:
        nowt = time.monotonic() if nowt is None else float(nowt)
        rows = []
        for device in self.devices_cfg:
            serial_id = int(device["serial_id"])
            rows.append(
                {
                    "line_id": self.line_id,
                    "line_name": self.name,
                    "serial_id": serial_id,
                    "nms_id": int(device.get("nms_id", serial_id)),
                    "role": str(device.get("role", "") or "-"),
                    "pair_id": str(device.get("pair_id", "") or "-"),
                    "a1_req": self._format_device_metric("a1", serial_id, no_resp=False, nowt=nowt),
                    "a2_req": self._format_device_metric("a2", serial_id, no_resp=False, nowt=nowt),
                    "a1_timeout": self._format_device_metric("a1", serial_id, no_resp=True, nowt=nowt),
                    "a2_timeout": self._format_device_metric("a2", serial_id, no_resp=True, nowt=nowt),
                    "bad_len": self._format_device_bad_frame_metric("bad_len", serial_id, nowt=nowt),
                    "bad_chk": self._format_device_bad_frame_metric("bad_chk", serial_id, nowt=nowt),
                }
            )
        return rows

    def get_ui_snapshot(self, nowt: Optional[float] = None) -> dict:
        nowt = time.monotonic() if nowt is None else float(nowt)
        rx_h_qfull = self.rx_head.drop_q_full if self.rx_head else 0
        rx_t_qfull = self.rx_tail.drop_q_full if self.rx_tail else 0
        recent_unmatched = self.recent_unmatched_count(nowt)
        pref_head = sum(1 for st in self.dev_state.values() if st.get("last_good_side", "head") == "head")
        pref_tail = max(0, len(self.dev_state) - pref_head)
        return {
            "line_id": self.line_id,
            "name": self.name,
            "preferred": f"{pref_head}/{pref_tail}",
            "port": f"{self.port_state('head')}/{self.port_state('tail')}",
            "link": f"{self.link_state('head', nowt)}/{self.link_state('tail', nowt)}",
            "down_for": f"{self.port_down_for('head', nowt)}/{self.port_down_for('tail', nowt)}",
            "devices": len(self.devices_cfg),
            "a1_req": self._format_side_metric("a1", no_resp=False, nowt=nowt),
            "a2_req": self._format_side_metric("a2", no_resp=False, nowt=nowt),
            "a1_timeout": self._format_side_metric("a1", no_resp=True, nowt=nowt),
            "a2_timeout": self._format_side_metric("a2", no_resp=True, nowt=nowt),
            "cmd_timeout": self._format_side_metric("cmd", no_resp=True, nowt=nowt),
            "unmatched": f"{self.drop_unmatched}/{recent_unmatched}",
            "qfull": f"{rx_h_qfull}/{rx_t_qfull}",
            "queue": f"{self.q_head.qsize()}/{self.q_tail.qsize()}",
            "last_ok": _age_text(self.last_ok_mono, nowt) if self.last_ok_mono > 0 else "-",
        }

    def port_state(self, which: str) -> str:
        port_name = self.head_port_name if which == "head" else self.tail_port_name
        if is_disabled_port(port_name):
            return "dis"
        ser = self.ser_head if which == "head" else self.ser_tail
        return "open" if (ser and ser.is_open) else "down"

    def link_state(self, which: str, nowt: Optional[float] = None) -> str:
        nowt = time.monotonic() if nowt is None else float(nowt)
        port_state = self.port_state(which)
        if port_state == "dis":
            return "dis"
        if port_state == "down":
            return "down"

        rx = self.rx_head if which == "head" else self.rx_tail
        if rx is None:
            return "init"

        age = max(0.0, nowt - float(rx.last_good_frame_mono()))
        ok_window = max(1.0, float(DEBUG_TUNING["WAIT_RESPONSE_TIMEOUT_SEC"]) * 4.0)
        stale_window = max(ok_window, float(DEBUG_TUNING["STALL_NOFRAME_SEC"]))
        if age <= ok_window:
            return "good"
        return "bad"

    def port_down_for(self, which: str, nowt: Optional[float] = None) -> str:
        nowt = time.monotonic() if nowt is None else float(nowt)
        port_name = self.head_port_name if which == "head" else self.tail_port_name
        if is_disabled_port(port_name):
            return "dis"
        down_since = float(self._port_down_since.get(which, 0.0) or 0.0)
        if down_since <= 0:
            return "-"
        return _age_text(down_since, nowt)

    def health_label(self) -> str:
        head_bad = (not is_disabled_port(self.head_port_name)) and (self.ser_head is None or (not self.ser_head.is_open))
        tail_bad = (not is_disabled_port(self.tail_port_name)) and (self.ser_tail is None or (not self.ser_tail.is_open))
        if head_bad or tail_bad:
            return "DEGRADED"
        return "OK"

    def is_degraded(self) -> bool:
        return self.health_label() != "OK"

    def preferred_side_majority(self) -> str:
        pref_head = sum(1 for st in self.dev_state.values() if st.get("last_good_side", "head") == "head")
        pref_tail = max(0, len(self.dev_state) - pref_head)
        return "head" if pref_head >= pref_tail else "tail"

    def recent_no_resp_count(self, kind: str, nowt: Optional[float] = None, side: Optional[str] = None) -> int:
        nowt = time.monotonic() if nowt is None else float(nowt)
        side_name = self._side_name(side)
        if side_name is not None and kind in self.no_resp_side_times:
            return self._prune_metric_times(self.no_resp_side_times[kind][side_name], nowt)
        if kind == "a1":
            buf = self.a1_no_resp_times
        elif kind == "a2":
            buf = self.a2_no_resp_times
        else:
            buf = self.cmd_no_resp_times
        while buf and (nowt - float(buf[0])) > NO_RESP_WINDOW_SEC:
            buf.popleft()
        return len(buf)

    def record_no_resp(self, kind: str, side: Optional[str] = None, serial_id: Optional[int] = None):
        nowt = now_mono()
        side_name = self._side_name(side)
        if side_name is not None and kind in self.no_resp_counts:
            self.no_resp_counts[kind][side_name] += 1
            self.no_resp_side_times[kind][side_name].append(nowt)
            self._prune_metric_times(self.no_resp_side_times[kind][side_name], nowt)
            dev_counts = self._ensure_device_metric(self.device_no_resp_counts, kind, serial_id, times=False)
            dev_times = self._ensure_device_metric(self.device_no_resp_times, kind, serial_id, times=True)
            if dev_counts is not None and dev_times is not None:
                dev_counts[side_name] += 1
                dev_times[side_name].append(nowt)
                self._prune_metric_times(dev_times[side_name], nowt)
        if kind == "a1":
            self.a1_no_resp_count += 1
            self.last_a1_no_resp_mono = nowt
            self.a1_no_resp_times.append(nowt)
        elif kind == "a2":
            self.a2_no_resp_count += 1
            self.last_a2_no_resp_mono = nowt
            self.a2_no_resp_times.append(nowt)
        else:
            self.cmd_no_resp_count += 1
            self.last_cmd_no_resp_mono = nowt
            self.cmd_no_resp_times.append(nowt)
        self.recent_no_resp_count(kind, nowt)

    def recent_unmatched_count(self, nowt: Optional[float] = None) -> int:
        nowt = time.monotonic() if nowt is None else float(nowt)
        while self.unmatched_times and (nowt - float(self.unmatched_times[0])) > NO_RESP_WINDOW_SEC:
            self.unmatched_times.popleft()
        return len(self.unmatched_times)

    def record_unmatched(self):
        nowt = now_mono()
        self.drop_unmatched += 1
        self.last_unmatched_mono = nowt
        self.unmatched_times.append(nowt)
        self.recent_unmatched_count(nowt)

    def enqueue_command(self, item: dict):
        self.command_queue.put(item)

    # -------------------------
    # cmd done (dedupe)
    # -------------------------
    def _done_key(self, msg_id) -> str:
        return f"{SY_CMD_DONE_KEY_PREFIX}{_b2s(msg_id)}"

    def _done_local_cleanup(self):
        nowt = now_mono()
        with self._done_local_lock:
            dead = [k for k, exp in self._done_local.items() if exp <= nowt]
            for k in dead:
                self._done_local.pop(k, None)

    def _done_local_has(self, msg_id) -> bool:
        self._done_local_cleanup()
        mid = _b2s(msg_id)
        with self._done_local_lock:
            exp = self._done_local.get(mid)
            return bool(exp and exp > now_mono())

    def _done_local_mark(self, msg_id):
        """
        ✅ 更稳：本地 done TTL 取 max(local_ttl, redis_ttl)，覆盖“ack 失败导致的短期重投”
        """
        mid = _b2s(msg_id)
        ttl = int(max(SY_CMD_DONE_LOCAL_TTL_SEC, SY_CMD_DONE_TTL_SEC))
        exp = now_mono() + max(1, ttl)
        with self._done_local_lock:
            self._done_local[mid] = exp

    def _cmd_already_done(self, msg_id) -> bool:
        if msg_id is None:
            return False
        if self._done_local_has(msg_id):
            return True
        try:
            key = self._done_key(msg_id)
            if self.redis_conn.is_ready() and self.redis_conn.cmd_done_exists(key):
                return True
        except Exception:
            pass
        return False

    def _cmd_mark_done(self, msg_id) -> bool:
        if msg_id is None:
            return True
        self._done_local_mark(msg_id)
        try:
            if self.redis_conn.is_ready():
                key = self._done_key(msg_id)
                first = self.redis_conn.cmd_done_mark(key, int(SY_CMD_DONE_TTL_SEC))
                return bool(first)
        except Exception:
            pass
        return True

    # -------------------------
    # port open/close + retry
    # -------------------------
    def _schedule_retry(self, which: str, reason: str):
        st = self._port_retry[which]
        delay = float(st["delay"])
        st["next"] = now_mono() + delay
        st["delay"] = min(delay * 2.0, float(st["max"]))
        if DEBUG_TUNING["LOG_PORT_STATE"]:
            self.log(f"[PORT] {which} schedule reopen in {delay:.1f}s (reason={reason})")

    def _reset_retry(self, which: str):
        st = self._port_retry[which]
        st["delay"] = float(st["min"])
        st["next"] = 0.0

    def _close_port(self, which: str, reason: str):
        nowt = now_mono()
        if which == "head":
            rx, ser, lock = self.rx_head, self.ser_head, self.lock_head
            self.rx_head = None
            self.ser_head = None
            self.epoch_head.bump()
        else:
            rx, ser, lock = self.rx_tail, self.ser_tail, self.lock_tail
            self.rx_tail = None
            self.ser_tail = None
            self.epoch_tail.bump()

        try:
            if rx:
                rx.stop()
                rx.join(timeout=0.2)
        except Exception:
            pass

        try:
            with lock:
                if ser and ser.is_open:
                    ser.close()
        except Exception:
            pass

        if not is_disabled_port(self.head_port_name if which == "head" else self.tail_port_name):
            if float(self._port_down_since.get(which, 0.0) or 0.0) <= 0:
                self._port_down_since[which] = nowt

        self._schedule_retry(which, reason)

    def _on_rx_fatal(self, which: str, reason: str):
        self.log(f"[PORT] {which} RX fatal -> reopen: {reason}")
        self._close_port(which, f"rx_fatal:{reason}")

    def _try_open_port(self, which: str, port_name: Optional[str]) -> None:
        if is_disabled_port(port_name):
            return

        try:
            ser = serial.Serial(
                port=str(port_name),
                baudrate=self.baudrate,
                bytesize=DEFAULT_BYTESIZE,
                parity=DEFAULT_PARITY,
                stopbits=DEFAULT_STOPBITS,
                timeout=self.timeout,
                write_timeout=0,
                rtscts=False,
                dsrdtr=False,
            )
            if DEBUG_TUNING["RTS_TOGGLE"]:
                _set_rts(ser, int(DEBUG_TUNING["RTS_RX_LEVEL"]))

            if which == "head":
                self.ser_head = ser
                rx = PortReceiver(
                    line_id=self.line_id,
                    line_name=self.name,
                    which="head",
                    ser=ser,
                    ser_lock=self.lock_head,
                    out_q=self.q_head,
                    epoch_ref=self.epoch_head,
                    on_fatal=self._on_rx_fatal,
                )
                self.rx_head = rx
            else:
                self.ser_tail = ser
                rx = PortReceiver(
                    line_id=self.line_id,
                    line_name=self.name,
                    which="tail",
                    ser=ser,
                    ser_lock=self.lock_tail,
                    out_q=self.q_tail,
                    epoch_ref=self.epoch_tail,
                    on_fatal=self._on_rx_fatal,
                )
                self.rx_tail = rx

            rx.request_clear()
            rx.start()

            self._reset_retry(which)
            self._port_open_mono[which] = now_mono()
            self._port_down_since[which] = 0.0
            self.log(f"[PORT] {which.upper()} opened: {ser.portstr}")

        except Exception as e:
            if float(self._port_down_since.get(which, 0.0) or 0.0) <= 0:
                self._port_down_since[which] = now_mono()
            self.log(f"[PORT] {which.upper()} open failed: {e}")
            self._schedule_retry(which, f"open_failed:{e}")

    def _maybe_reopen_ports(self):
        nowt = now_mono()

        if bool(DEBUG_TUNING["RX_THREAD_DEAD_REOPEN"]):
            if self.rx_head is not None and (not self.rx_head.is_alive()):
                self.log("[PORT] head RX thread dead => reopen")
                self._close_port("head", "rx_thread_dead")
            if self.rx_tail is not None and (not self.rx_tail.is_alive()):
                self.log("[PORT] tail RX thread dead => reopen")
                self._close_port("tail", "rx_thread_dead")

        if self.ser_head is None or (not self.ser_head.is_open):
            if not is_disabled_port(self.head_port_name):
                st = self._port_retry["head"]
                if st["next"] <= 0.0 or nowt >= float(st["next"]):
                    self._try_open_port("head", self.head_port_name)

        if self.ser_tail is None or (not self.ser_tail.is_open):
            if not is_disabled_port(self.tail_port_name):
                st = self._port_retry["tail"]
                if st["next"] <= 0.0 or nowt >= float(st["next"]):
                    self._try_open_port("tail", self.tail_port_name)

    def close_ports(self):
        for which in ("head", "tail"):
            try:
                self._close_port(which, "shutdown")
            except Exception:
                pass

    def _drain_queue(self, q: "queue.Queue[dict]"):
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            return

    def _clear_side(self, which: str):
        if which == "head":
            rx = self.rx_head
            epoch = self.epoch_head
            q = self.q_head
        else:
            rx = self.rx_tail
            epoch = self.epoch_tail
            q = self.q_tail

        if rx:
            prev = epoch.get()
            rx.request_clear()
            deadline = now_mono() + 0.05
            while running and now_mono() < deadline and epoch.get() == prev:
                time.sleep(0.001)

        self._drain_queue(q)

        # ✅ FIX(建议#3)：只清当前 side 的 stash，不误伤另一侧
        for k in list(self.stash.keys()):
            # k = (which, epoch, addr, cmd)
            if k and k[0] == which:
                self.stash.pop(k, None)

    def _other_side(self, which: str) -> str:
        return "tail" if which == "head" else "head"

    def _clear_rx_window_for_send(self, tx_side: str):
        if self.ring_mode:
            self._clear_side("head")
            self._clear_side("tail")
            return
        self._clear_side(tx_side)

    # -------------------------
    # stall watchdog（假死无异常）
    # -------------------------
    def _stall_watchdog(self):
        if not bool(DEBUG_TUNING["STALL_WATCHDOG_ENABLE"]):
            return

        nowt = now_mono()
        stall_sec = float(DEBUG_TUNING["STALL_NOFRAME_SEC"])
        grace = float(DEBUG_TUNING["STALL_GRACE_AFTER_OPEN_SEC"])
        cooldown = float(DEBUG_TUNING["STALL_COOLDOWN_SEC"])

        def check(which: str, ser: Optional[serial.Serial], rx: Optional[PortReceiver]):
            if ser is None or (not ser.is_open) or rx is None:
                return
            opened_at = float(self._port_open_mono.get(which, 0.0) or 0.0)
            if opened_at > 0 and (nowt - opened_at) < grace:
                return

            last_good = rx.last_good_frame_mono()
            if (nowt - last_good) < stall_sec:
                return

            last_act = float(self._last_stall_action_mono.get(which, 0.0) or 0.0)
            if last_act > 0 and (nowt - last_act) < cooldown:
                return

            self._last_stall_action_mono[which] = nowt
            self.log(f"[PORT] {which} STALL(no good frame for {nowt-last_good:.1f}s) => reopen")
            self._close_port(which, "stall_watchdog")

        check("head", self.ser_head, self.rx_head)
        check("tail", self.ser_tail, self.rx_tail)

    # -------------------------
    # stash helpers
    # -------------------------
    def _stash_cleanup(self):
        nowt = now_mono()
        expired_keys = []
        for k, lst in self.stash.items():
            self.stash[k] = [x for x in lst if (nowt - float(x.get("tmono", nowt))) <= self.stash_keep_seconds]
            if not self.stash[k]:
                expired_keys.append(k)
        for k in expired_keys:
            self.stash.pop(k, None)

    def _stash_put(self, item: dict):
        self._stash_cleanup()
        which = str(item.get("port"))
        epoch = int(item.get("epoch", 0))
        addr = int(item.get("addr", -1))
        cmd = int(item.get("cmd", -1))
        key = (which, epoch, addr, cmd)
        lst = self.stash.get(key)
        if lst is None:
            self.stash[key] = [item]
        else:
            lst.append(item)
            if len(lst) > self.stash_max_per_key:
                del lst[0:len(lst) - self.stash_max_per_key]

    def _stash_get(self, which: str, epoch: int, addr: int, allowed_cmds: Tuple[int, ...]) -> Optional[dict]:
        self._stash_cleanup()
        for cmd in allowed_cmds:
            key = (which, epoch, addr, cmd)
            lst = self.stash.get(key)
            if lst:
                return lst.pop(0)
        return None

    def _current_epoch(self, which: str) -> int:
        return self.epoch_head.get() if which == "head" else self.epoch_tail.get()

    def _item_matches_expected(
        self,
        item: dict,
        *,
        expected_serial_id: Optional[int],
        expected_req_cmd: Optional[str],
        expected_cmds: Optional[Tuple[int, ...]] = None,
    ) -> bool:
        frame = item.get("frame") or b""
        if expected_req_cmd in ("A1", "A2", "B2"):
            return resp_match_expected(
                frame,
                expected_serial_id=expected_serial_id,
                expected_req_cmd=str(expected_req_cmd),
            )

        if expected_serial_id is not None:
            addr = int(item.get("addr", -1))
            if addr != (int(expected_serial_id) & 0xFF):
                return False

            if expected_cmds is not None:
                cmd = int(item.get("cmd", -1)) & 0xFF
                if cmd not in expected_cmds:
                    return False
                try:
                    if not checksum_ok_lenient(frame):
                        return False
                except Exception:
                    pass

        return True

    def _purge_side_mirror_frame(self, which: str, *, epoch: int, frame: bytes, min_tmono: float) -> int:
        q = self.q_head if which == "head" else self.q_tail
        kept = []
        dropped = 0

        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break

            item_epoch = int(item.get("epoch", -1))
            item_tmono = float(item.get("tmono", 0.0) or 0.0)
            item_frame = item.get("frame") or b""
            if item_epoch == epoch and item_tmono >= min_tmono and item_frame == frame:
                dropped += 1
                continue
            kept.append(item)

        for item in kept:
            try:
                q.put_nowait(item)
            except queue.Full:
                dropped += 1

        for key in list(self.stash.keys()):
            if not key or key[0] != which or int(key[1]) != epoch:
                continue
            lst = self.stash.get(key) or []
            new_lst = []
            for item in lst:
                item_tmono = float(item.get("tmono", 0.0) or 0.0)
                item_frame = item.get("frame") or b""
                if item_tmono >= min_tmono and item_frame == frame:
                    dropped += 1
                    continue
                new_lst.append(item)
            if new_lst:
                self.stash[key] = new_lst
            else:
                self.stash.pop(key, None)

        return dropped

    def _wait_match_ring(
        self,
        tx_side: str,
        *,
        expected_serial_id: Optional[int],
        expected_req_cmd: Optional[str],
        expected_cmds: Optional[Tuple[int, ...]] = None,
        timeout: float,
        min_tmono: float = 0.0,
        record_unmatched: bool = True,
    ) -> Optional[dict]:
        sides = [tx_side]
        other_side = self._other_side(tx_side)
        if other_side not in sides:
            sides.append(other_side)
        expect_epochs = {side: self._current_epoch(side) for side in sides}
        deadline = now_mono() + max(0.0, timeout)

        while running and now_mono() < deadline:
            progressed = False
            for side in sides:
                q = self.q_head if side == "head" else self.q_tail
                while True:
                    try:
                        item = q.get_nowait()
                    except queue.Empty:
                        break

                    progressed = True
                    item_epoch = int(item.get("epoch", -1))
                    if item_epoch != int(expect_epochs.get(side, -1)):
                        continue

                    item_tmono = float(item.get("tmono", 0.0) or 0.0)
                    if min_tmono > 0.0 and item_tmono < min_tmono:
                        continue

                    if item.get("bad_frame"):
                        self._record_bad_item_for_window(item, expected_serial_id=expected_serial_id)
                        continue

                    if self._item_matches_expected(
                        item,
                        expected_serial_id=expected_serial_id,
                        expected_req_cmd=expected_req_cmd,
                        expected_cmds=expected_cmds,
                    ):
                        mirror_side = self._other_side(side)
                        mirror_epoch = int(expect_epochs.get(mirror_side, -1))
                        if mirror_epoch >= 0:
                            self._purge_side_mirror_frame(
                                mirror_side,
                                epoch=mirror_epoch,
                                frame=item.get("frame") or b"",
                                min_tmono=min_tmono,
                            )
                        return item

                    if record_unmatched:
                        self.record_unmatched()
                    self._stash_put(item)

            if not progressed:
                time.sleep(min(0.002, max(0.0, deadline - now_mono())))

        return None

    # -------------------------
    # send / wait / report
    # -------------------------
    def _send_frame(self, which: str, frame: bytes, meta: dict) -> bool:
        """
        ✅ FIX：after_sleep 不再持有 ser_lock
        - 锁只保护 write/flush（以及可选 RTS toggle 内部的 IO）
        - sleep 放到锁外，让 RX 线程能及时读串口，降低丢字节/假 NO_RESP
        """
        ser = self.ser_head if which == "head" else self.ser_tail
        lock = self.lock_head if which == "head" else self.lock_tail
        if ser is None or (not ser.is_open):
            return False

        self.seq_send += 1
        seq = self.seq_send

        after_sleep = ADAPT.get_sleep() if DEBUG_TUNING["ENABLE_AFTER_WRITE_SLEEP"] else 0.0

        try:
            with lock:
                t0 = now_mono()
                write_with_optional_rts_toggle(ser, frame)

            if after_sleep > 0:
                time.sleep(after_sleep)

            if DEBUG_TUNING["LOG_SEND"]:
                emit_event(
                    f"sent({which}) seq={seq} serial_id={meta.get('serial_id')} cmd={meta.get('req_cmd')} "
                    f"after={after_sleep:.3f}s wait={float(DEBUG_TUNING['WAIT_RESPONSE_TIMEOUT_SEC']):.3f}s "
                    f"hex={frame_to_hex(frame)}",
                    category="poll",
                    line_id=self.line_id,
                    line_name=self.name,
                    port=which,
                    record_event=False,
                )

            meta["_send_seq"] = seq
            meta["_send_tmono"] = t0
            meta["_after_sleep"] = after_sleep
            meta.setdefault("_sent_sides", []).append(which)
            metric_kind = self._metric_kind(meta.get("req_cmd"))
            if metric_kind in ("a1", "a2"):
                self.record_request(metric_kind, which, meta.get("serial_id"))
            return True

        except SerialException as e:
            self.log(f"[PORT] write error on {which}: {e}")
            self._close_port(which, f"write_error:{e}")
            return False
        except Exception as e:
            self.log(f"[PORT] write unknown error on {which}: {e}")
            self._close_port(which, f"write_unknown:{e}")
            return False

    def _wait_match_from_queue(
        self,
        which: str,
        *,
        expected_serial_id: Optional[int],
        expected_req_cmd: Optional[str],
        expected_cmds: Optional[Tuple[int, ...]] = None,
        timeout: float,
        min_tmono: float = 0.0,
        use_stash_first: bool = True,
        record_unmatched: bool = True,
    ) -> Optional[dict]:
        q = self.q_head if which == "head" else self.q_tail
        expect_epoch = self._current_epoch(which)

        if use_stash_first and expected_serial_id is not None and expected_req_cmd in ("A1", "A2", "B2"):
            addr = int(expected_serial_id) & 0xFF
            if expected_req_cmd == "A1":
                allowed = (CMD_A1,)
            elif expected_req_cmd == "A2":
                allowed = (CMD_A2, CMD_NOCHANGE)
            else:
                allowed = (CMD_B2,)
            hit = self._stash_get(which, expect_epoch, addr, allowed)
            if hit and (min_tmono <= 0.0 or float(hit.get("tmono", 0.0) or 0.0) >= min_tmono):
                return hit

        deadline = now_mono() + max(0.0, timeout)
        while running and now_mono() < deadline:
            remain = deadline - now_mono()
            if remain <= 0:
                break
            try:
                item = q.get(timeout=min(0.02, remain))
            except queue.Empty:
                continue

            item_epoch = int(item.get("epoch", -1))
            if item_epoch != expect_epoch:
                continue
            item_tmono = float(item.get("tmono", 0.0) or 0.0)
            if min_tmono > 0.0 and item_tmono < min_tmono:
                continue

            if item.get("bad_frame"):
                self._record_bad_item_for_window(item, expected_serial_id=expected_serial_id)
                continue

            if self._item_matches_expected(
                item,
                expected_serial_id=expected_serial_id,
                expected_req_cmd=expected_req_cmd,
                expected_cmds=expected_cmds,
            ):
                return item

            if record_unmatched:
                self.record_unmatched()
            self._stash_put(item)

        return None

    def _send_and_wait(
        self,
        which: str,
        frame: bytes,
        meta: dict,
        timeout: float,
        *,
        use_stash_first: bool = True,
        record_unmatched: bool = True,
    ) -> Optional[dict]:
        self._clear_rx_window_for_send(which)
        if not self._send_frame(which, frame, meta):
            return None
        min_tmono = float(meta.get("_send_tmono", 0.0) or 0.0)
        if self.ring_mode:
            return self._wait_match_ring(
                which,
                expected_serial_id=meta.get("serial_id"),
                expected_req_cmd=meta.get("req_cmd"),
                expected_cmds=meta.get("_expected_cmds"),
                timeout=timeout,
                min_tmono=min_tmono,
                record_unmatched=record_unmatched,
            )
        return self._wait_match_from_queue(
            which,
            expected_serial_id=meta.get("serial_id"),
            expected_req_cmd=meta.get("req_cmd"),
            expected_cmds=meta.get("_expected_cmds"),
            timeout=timeout,
            min_tmono=min_tmono,
            use_stash_first=use_stash_first,
            record_unmatched=record_unmatched,
        )

    def _report_ok(self, side: str, *, serial_id: Optional[int], nms_id: Optional[int], req_cmd: Optional[str], frame: bytes, send_meta: dict):
        recv_t = now_mono()
        send_t = float(send_meta.get("_send_tmono", recv_t))
        rtt = max(0.0, recv_t - send_t)
        ADAPT.on_resp_ok(rtt)
        self.last_ok_mono = recv_t
        self.last_ok_side = side

        hex_str = frame_to_hex(frame)

        if DEBUG_TUNING["LOG_RECV_OK"]:
            emit_event(
                f"recv({side}) RESP_OK seq={send_meta.get('_send_seq')} serial_id={serial_id} cmd={req_cmd} "
                f"RTT={rtt*1000:.1f}ms after={float(send_meta.get('_after_sleep', 0.0)):.3f}s hex={hex_str}",
                category="poll",
                line_id=self.line_id,
                line_name=self.name,
                port=side,
                record_event=False,
            )

        msg = {
            "payload_hex": hex_str,
            "ts": int(time.time()),
            "agent_ip": AGENT_IP,
            "agent_name": AGENT_NAME,
            "line_id": self.line_id,
            "port": side,
            "serial_id": serial_id,
            "nms_id": nms_id,
            "req_cmd": req_cmd,
            "rtt_ms": int(rtt * 1000),
            "after_sleep_ms": int(float(send_meta.get("_after_sleep", 0.0)) * 1000),
        }

        try:
            self.redis_conn.xadd_json(SY_RAW_STREAM, msg, SY_RAW_STREAM_MAXLEN)
            return True
        except Exception as e:
            self.log(f"[Redis] XADD failed => will pause until redis recovers: {e}")
            return False

    def _a2_burst(self, side: str, *, serial_id: int, nms_id: int):
        if not A2_BURST_ENABLE:
            return

        start = now_mono()
        tries = 0

        while running:
            if not self.redis_conn.is_ready():
                return

            if tries >= max(0, A2_BURST_MAX):
                break
            elapsed = now_mono() - start
            if elapsed >= max(0.0, A2_BURST_BUDGET):
                break

            remaining = max(0.0, A2_BURST_BUDGET - elapsed)
            per_timeout = min(max(0.0, A2_BURST_TIMEOUT), remaining)
            if per_timeout <= 0:
                break

            frame = build_a2_request(serial_id)
            meta = {"serial_id": serial_id, "nms_id": nms_id, "req_cmd": "A2"}
            sent_before = len(meta.get("_sent_sides", []))
            resp_item = self._send_and_wait(
                side,
                frame,
                meta,
                timeout=per_timeout,
                use_stash_first=False,
            )
            if resp_item is None:
                if len(meta.get("_sent_sides", [])) > sent_before:
                    self.record_no_resp("a2", side, serial_id)
                break

            ok = self._report_ok(side, serial_id=serial_id, nms_id=nms_id, req_cmd="A2", frame=resp_item["frame"], send_meta=meta)
            if not ok:
                return

            cmd = int(resp_item.get("cmd", -1))
            if cmd == CMD_NOCHANGE:
                break
            tries += 1

    def _periodic_status(self):
        nowt = now_mono()
        if (nowt - self._last_status_print) < float(DEBUG_TUNING["STATUS_PRINT_EVERY_SEC"]):
            return
        self._last_status_print = nowt

        if DEBUG_TUNING["LOG_PORT_STATE"]:
            h = "UP" if (self.ser_head and self.ser_head.is_open) else "DOWN"
            t = "UP" if (self.ser_tail and self.ser_tail.is_open) else "DOWN"

            snap = self.get_ui_snapshot(nowt)
            status_payload = {
                "redis": "UP" if self.redis_conn.is_ready() else "DOWN",
                "ports": f"{h}/{t}",
                "preferred": snap["preferred"],
                "port": snap["port"],
                "link": snap["link"],
                "down_for": snap["down_for"],
                "devices": snap["devices"],
                "a1_req": snap["a1_req"],
                "a2_req": snap["a2_req"],
                "a1_timeout": snap["a1_timeout"],
                "a2_timeout": snap["a2_timeout"],
                "cmd_timeout": snap["cmd_timeout"],
                "unmatched": snap["unmatched"],
                "qfull": snap["qfull"],
                "queue": snap["queue"],
                "last_ok": snap["last_ok"],
                "after_sleep": f"{ADAPT.get_sleep():.3f}s",
            }

            emit_event(
                f"[STATUS] {json.dumps(status_payload, ensure_ascii=False, separators=(',', ':'))}",
                category="poll",
                line_id=self.line_id,
                line_name=self.name,
                record_event=False,
            )
        CONSOLE.maybe_emit_plain_dashboard_status()

    def _try_ack_cmd(self, msg_id):
        if msg_id is None:
            return
        if not self.redis_conn.is_ready():
            return
        try:
            self.redis_conn.xack(SY_CMD_STREAM, SY_CMD_GROUP, msg_id)
        except Exception as e:
            self.log(f"[CmdACK] ack failed (redis down): {e}")

    def _best_effort_confirm_after_noresp_cmd(self, side: str, *, serial_id: Optional[int], nms_id: Optional[int]) -> bool:
        """
        ✅ 无回帧命令：发送后用 A2/A1 做 best-effort 确认（在线/变化/对账）
        - A2：有变化帧或 NOCHANGE 都算“可读”
        - A1：可选更稳对账
        """
        if serial_id is None:
            return False

        time.sleep(max(0.0, float(SY_CMD_CC_CONFIRM_DELAY_SEC)))
        ok_any = False

        # A2 confirm
        a2_meta = {"serial_id": int(serial_id), "nms_id": nms_id, "req_cmd": "A2"}
        sent_before = len(a2_meta.get("_sent_sides", []))
        a2_item = self._send_and_wait(
            side,
            build_a2_request(int(serial_id)),
            a2_meta,
            timeout=float(SY_CMD_CC_CONFIRM_TIMEOUT_SEC),
            use_stash_first=False,
        )
        if a2_item is not None:
            _ = self._report_ok(side, serial_id=int(serial_id), nms_id=nms_id, req_cmd="A2", frame=a2_item["frame"], send_meta=a2_meta)
            ok_any = True
        elif len(a2_meta.get("_sent_sides", [])) > sent_before:
            self.record_no_resp("a2", side, serial_id)

        # A1 confirm (optional)
        if bool(SY_CMD_CC_CONFIRM_A1):
            a1_meta = {"serial_id": int(serial_id), "nms_id": nms_id, "req_cmd": "A1"}
            sent_before = len(a1_meta.get("_sent_sides", []))
            a1_item = self._send_and_wait(
                side,
                build_a1_request(int(serial_id)),
                a1_meta,
                timeout=float(SY_CMD_CC_CONFIRM_TIMEOUT_SEC),
                use_stash_first=False,
            )
            if a1_item is not None:
                _ = self._report_ok(side, serial_id=int(serial_id), nms_id=nms_id, req_cmd="A1", frame=a1_item["frame"], send_meta=a1_meta)
                ok_any = True
            elif len(a1_meta.get("_sent_sides", [])) > sent_before:
                self.record_no_resp("a1", side, serial_id)

        return ok_any

    def _send_bb_and_wait_ack(self, side: str, frame: bytes, meta: dict) -> Optional[dict]:
        extra_retries = max(0, int(SY_CMD_BB_CMD_RETRIES))
        total_attempts = 1 + extra_retries

        for attempt in range(1, total_attempts + 1):
            resp_item = self._send_and_wait(
                side,
                frame,
                meta,
                timeout=float(DEBUG_TUNING["WAIT_RESPONSE_TIMEOUT_SEC"]),
                use_stash_first=(attempt == 1),
            )
            if resp_item is not None:
                return resp_item

            if attempt < total_attempts:
                self.log(
                    f"[CmdRetry] BB missing 0x05, resend {attempt}/{extra_retries} "
                    f"side={side} meta={meta}"
                )

        return None

    def run(self):
        self.log("thread started.")
        while running:
            self._maybe_reopen_ports()
            self._stall_watchdog()

            if not self.redis_conn.is_ready():
                self._periodic_status()
                time.sleep(float(DEBUG_TUNING["REDIS_DOWN_PAUSE_SEC"]))
                continue

            self._periodic_status()

            # 1) 外部命令
            try:
                item = self.command_queue.get_nowait()
            except queue.Empty:
                item = None

            if item is not None:
                cmd_frame: bytes = item.get("frame") or b""
                meta = item.get("meta") or {}
                msg_id = item.get("msg_id")

                if msg_id is not None and self._cmd_already_done(msg_id):
                    self.log(f"[CmdDEDUP] skip already-done id={_b2s(msg_id)} meta={meta}")
                    self._try_ack_cmd(msg_id)
                    continue

                if meta.get("serial_id") is None and meta.get("nms_id") is not None:
                    sid = self.nms_to_serial.get(int(meta["nms_id"]))
                    if sid is not None:
                        meta["serial_id"] = sid

                cmd_frame = normalize_downlink_request_tail(cmd_frame)

                # 把请求帧地址改成 serial_id（否则会发错设备）
                target_sid = meta.get("serial_id")
                if target_sid is not None:
                    cur_addr = request_addr_byte(cmd_frame)
                    if cur_addr is not None and (cur_addr != (int(target_sid) & 0xFF)):
                        newf = rewrite_request_addr(cmd_frame, int(target_sid))
                        if newf is None:
                            self.log(f"[CmdADDR] rewrite failed, keep original. cur_addr={cur_addr} target_sid={target_sid} meta={meta}")
                        else:
                            if DEBUG_TUNING.get("LOG_SEND", False) or DEBUG_TUNING.get("LOG_PORT_STATE", True):
                                self.log(f"[CmdADDR] rewrite addr {cur_addr:#04x} -> {int(target_sid)&0xFF:#04x} (id={_b2s(msg_id)})")
                            cmd_frame = newf

                # ✅ 根据帧本身判断是否“无回帧命令”
                dl_cmd = downlink_cmd_byte(cmd_frame)
                meta["_dl_cmd"] = dl_cmd
                meta["_no_resp_mode"] = bool(is_no_resp_request(cmd_frame))

                meta["_expected_cmds"] = infer_expected_resp_cmds_from_request(cmd_frame)

                preferred = "head"
                if meta.get("serial_id") is not None:
                    st = self.dev_state.get(int(meta["serial_id"]))
                    if st:
                        preferred = st.get("last_good_side", "head")

                sides = ["head", "tail"] if preferred == "head" else ["tail", "head"]

                sent_ok = False
                cmd_timeout_sides = set()
                for i, side in enumerate(sides):
                    ser = self.ser_head if side == "head" else self.ser_tail
                    if ser is None or (not ser.is_open):
                        continue
                    if i == 1:
                        self._clear_side(side)

                    # ✅ 无回帧命令（当前默认仅 CC）：只发不等
                    if meta.get("_no_resp_mode", False):
                        ok_send = self._send_frame(side, cmd_frame, meta)
                        if not ok_send:
                            continue

                        # ✅ 关键：发送成功就先 mark_done，避免 pending 重放造成多次执行
                        self._cmd_mark_done(msg_id)

                        # ✅ 可选确认（best-effort）：A2/A1
                        confirm_ok = False
                        try:
                            confirm_ok = self._best_effort_confirm_after_noresp_cmd(
                                side,
                                serial_id=meta.get("serial_id"),
                                nms_id=meta.get("nms_id"),
                            )
                        except Exception:
                            confirm_ok = False

                        if (not confirm_ok) and DEBUG_TUNING["LOG_NO_RESP"]:
                            self.log(f"[CmdNoResp] sent OK but confirm weak meta={meta} (id={_b2s(msg_id)})")

                        sent_ok = True
                        self._try_ack_cmd(msg_id)
                        break

                    # ✅ 有回帧命令：原逻辑不变
                    sent_before = len(meta.get("_sent_sides", []))
                    if dl_cmd == CMD_BB:
                        resp_item = self._send_bb_and_wait_ack(side, cmd_frame, meta)
                    else:
                        resp_item = self._send_and_wait(
                            side,
                            cmd_frame,
                            meta,
                            timeout=float(DEBUG_TUNING["WAIT_RESPONSE_TIMEOUT_SEC"]),
                            use_stash_first=True,
                        )
                    if resp_item is None:
                        if len(meta.get("_sent_sides", [])) > sent_before:
                            cmd_timeout_sides.add(side)
                        continue
                    if resp_item is not None:
                        # ✅ SAFE(建议#1)：先 mark_done（至少本地），防 Redis 抖动导致命令重复执行
                        self._cmd_mark_done(msg_id)

                        _ = self._report_ok(
                            side,
                            serial_id=meta.get("serial_id"),
                            nms_id=meta.get("nms_id"),
                            req_cmd=meta.get("req_cmd"),
                            frame=resp_item["frame"],
                            send_meta=meta,
                        )

                        sent_ok = True

                        # 能 ack 就 ack（redis down 时可能失败，但后续重投递会被 dedupe 跳过）
                        self._try_ack_cmd(msg_id)
                        break

                if not sent_ok and cmd_timeout_sides:
                    for side in sorted(cmd_timeout_sides):
                        self.record_no_resp("cmd", side)
                    if DEBUG_TUNING["LOG_NO_RESP"]:
                        ADAPT.on_no_resp()
                        self.log(f"CMD no RESP_OK (cmd_no={self.cmd_no_resp_count}) meta={meta} (id={_b2s(msg_id)})")
                continue

            # 2) AA 校时
            tnow = now_mono()
            if TIME_SYNC_ENABLE and tnow >= self.next_time_sync_mono:
                aa_frame = build_aa_request()
                self.log(f"send AA time-sync: {frame_to_hex(aa_frame)}")

                if self.ser_head and self.ser_head.is_open:
                    self._send_frame("head", aa_frame, {"serial_id": None, "req_cmd": "AA"})
                elif self.ser_tail and self.ser_tail.is_open:
                    self._send_frame("tail", aa_frame, {"serial_id": None, "req_cmd": "AA"})

                self.next_time_sync_mono = tnow + TIME_SYNC_INTERVAL
                continue

            # 3) 轮询
            if not self.devices_cfg:
                time.sleep(0.01)
                continue

            dev_cfg = self.devices_cfg[self.dev_idx]
            serial_id = int(dev_cfg["serial_id"])
            nms_id = int(dev_cfg["nms_id"])
            a1_interval = self._effective_a1_interval(serial_id, float(dev_cfg.get("a1_interval", 5.0)))
            st = self.dev_state[serial_id]

            if (tnow - float(st["last_a1_mono"])) >= a1_interval:
                frame = build_a1_request(serial_id)
                is_a1 = True
                req_cmd = "A1"
            else:
                frame = build_a2_request(serial_id)
                is_a1 = False
                req_cmd = "A2"

            if (not is_a1) and self._should_skip_pair_a2(serial_id):
                self.dev_idx = (self.dev_idx + 1) % len(self.devices_cfg)
                continue

            preferred = st.get("last_good_side", "head")
            sides = ["head", "tail"] if preferred == "head" else ["tail", "head"]

            got_ok = False
            device_responded = False
            send_meta = {"serial_id": serial_id, "nms_id": nms_id, "req_cmd": req_cmd}

            for i, side in enumerate(sides):
                ser = self.ser_head if side == "head" else self.ser_tail
                if ser is None or (not ser.is_open):
                    continue

                if i == 1:
                    self._clear_side(side)

                sent_before = len(send_meta.get("_sent_sides", []))
                resp_item = self._send_and_wait(
                    side,
                    frame,
                    send_meta,
                    timeout=float(DEBUG_TUNING["WAIT_RESPONSE_TIMEOUT_SEC"]),
                    use_stash_first=True,
                )
                if resp_item is None:
                    if len(send_meta.get("_sent_sides", [])) > sent_before:
                        self.record_no_resp("a1" if req_cmd == "A1" else "a2", side, serial_id)
                    continue

                device_responded = True
                ok = self._report_ok(
                    side,
                    serial_id=serial_id,
                    nms_id=nms_id,
                    req_cmd=req_cmd,
                    frame=resp_item["frame"],
                    send_meta=send_meta,
                )
                if not ok:
                    break

                st["last_good_side"] = side
                if is_a1:
                    st["last_a1_mono"] = tnow

                got_ok = True

                if (req_cmd == "A2") and (int(resp_item.get("cmd", -1)) == CMD_A2):
                    self._a2_burst(side, serial_id=serial_id, nms_id=nms_id)

                break

            if is_a1:
                self._update_pair_after_poll(serial_id=serial_id, req_cmd=req_cmd, responded=device_responded)

            if (not got_ok) and send_meta.get("_sent_sides") and DEBUG_TUNING["LOG_NO_RESP"]:
                ADAPT.on_no_resp()
                self.log(
                    f"device no RESP_OK ({req_cmd}_no={self.a1_no_resp_count if req_cmd == 'A1' else self.a2_no_resp_count}) "
                    f"serial_id={serial_id} nms_id={nms_id} "
                    f"after={ADAPT.get_sleep():.3f}s wait={float(DEBUG_TUNING['WAIT_RESPONSE_TIMEOUT_SEC']):.3f}s "
                    f"RTS={int(DEBUG_TUNING['RTS_TOGGLE'])}"
                )

            self.dev_idx = (self.dev_idx + 1) % len(self.devices_cfg)

        self.close_ports()
        self.log(
            f"thread stopped. drop_unmatched={self.drop_unmatched}, a1_timeout={self.a1_no_resp_count}, "
            f"a2_timeout={self.a2_no_resp_count}, cmd_timeout={self.cmd_no_resp_count}"
        )


# ============================================================
# Redis 命令消费者线程（Redis down 自动等待恢复）
# - 不再“入队就 ACK”，而是把 msg_id 带给 poller，poller 成功后 ACK
# - 增加 XAUTOCLAIM：把 idle pending 捞回重试
# ✅ 生产：DLQ + 立即 ACK（对必然无法执行的消息）
# ✅ 新增：in-flight 去重 + 重试上限（超过阈值 => DLQ+ACK）
# ============================================================
def _enqueue_cmd_from_fields(*, msg_id, fields, poller: LinePoller) -> Tuple[bool, str]:
    raw = fields.get(b"data") or fields.get(b"json") or fields.get("data") or fields.get("json")
    if not raw:
        return False, "missing_data_field"

    try:
        data = json.loads(_b2s(raw))
    except Exception:
        return False, "json_parse_failed"

    nms_id = data.get("nms_id")
    if nms_id is None:
        nms_id = data.get("device_id")

    frame_hex = data.get("frame_hex") or data.get("payload_hex") or data.get("raw_hex")
    if frame_hex is None or nms_id is None:
        return False, "missing_frame_hex_or_nms_id"

    # ✅ ROBUST(建议#2)：frame_hex 容错更强（0x/空格/冒号等）
    try:
        s = str(frame_hex).strip().lower()
        s = s.replace("0x", "").replace(":", "").replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", "")
        frame = bytes.fromhex(s)
    except ValueError:
        return False, "invalid_frame_hex"

    meta = {
        "req_cmd": data.get("command") or "CMD",
        "nms_id": int(nms_id),
        "serial_id": data.get("serial_id"),
    }

    frame = normalize_downlink_request_tail(frame)

    poller.enqueue_command({"frame": frame, "meta": meta, "msg_id": msg_id})
    return True, "enqueued"


def _route_key_for_nms(nms_id: int) -> str:
    return f"{NMS_ROUTE_KEY_PREFIX}{int(nms_id)}"


def _publish_route_mappings(redis_conn: RedisConn) -> None:
    if not redis_conn.is_ready():
        return
    for nms_id in sorted(nms_to_line):
        try:
            redis_conn.set_text(_route_key_for_nms(int(nms_id)), AGENT_IP, ttl_sec=NMS_ROUTE_TTL_SEC)
        except Exception:
            return


def route_refresh_thread(redis_conn: RedisConn):
    last_ok = 0.0
    while running:
        if redis_conn.is_ready():
            try:
                _publish_route_mappings(redis_conn)
                nowt = now_mono()
                if (nowt - last_ok) >= 60.0:
                    emit_event(
                        f"[Route] refreshed {len(nms_to_line)} nms routes => {AGENT_IP}",
                        category="startup",
                        record_event=False,
                        plain_output=False,
                    )
                    last_ok = nowt
            except Exception:
                pass
        time.sleep(SUBAGENT_STATUS_REFRESH_SEC)


def _command_target_state(data: dict) -> Tuple[str, Optional[int], str]:
    nms_id = data.get("nms_id")
    if nms_id is None:
        nms_id = data.get("device_id")
    if nms_id is None:
        return "invalid", None, "missing_nms_id"

    try:
        nms_id_int = int(nms_id)
    except Exception:
        return "invalid", None, "invalid_nms_id"

    target_agent_ip = str(data.get("target_agent_ip") or "").strip()
    if target_agent_ip and target_agent_ip != AGENT_IP:
        return "ignore", nms_id_int, f"target_agent_ip={target_agent_ip}"

    poller = nms_to_line.get(nms_id_int)
    if poller is None:
        if target_agent_ip:
            return "invalid", nms_id_int, "targeted_unroutable_nms_id"
        return "ignore", nms_id_int, "not_local_nms_id"

    return "accept", nms_id_int, ""


def redis_command_thread(redis_conn: RedisConn):
    emit_event(
        f"[CmdStream] start. stream={SY_CMD_STREAM}, group={SY_CMD_GROUP}, consumer={SY_CMD_CONSUMER}, agent_ip={AGENT_IP}",
        category="cmd",
    )

    pending_start = "0-0"
    last_claim = 0.0

    # ✅ in-flight 去重：同一 msg_id 短时间只 enqueue 一次（避免 pending 反复入队）
    inflight: Dict[str, float] = {}
    inflight_ttl = SY_CMD_INFLIGHT_TTL_SEC  # 秒，覆盖一次发送+等待

    def inflight_allow(msg_id) -> bool:
        mid = _b2s(msg_id)
        nowt = now_mono()
        dead = [k for k, exp in inflight.items() if exp <= nowt]
        for k in dead:
            inflight.pop(k, None)
        exp = inflight.get(mid, 0.0)
        if exp > nowt:
            return False
        inflight[mid] = nowt + inflight_ttl
        return True

    # ✅ 重试上限：超过阈值 => DLQ + ACK，避免 pending 永久堆积
    def too_many_tries(msg_id) -> bool:
        if msg_id is None:
            return False
        try:
            key = f"{SY_CMD_TRY_KEY_PREFIX}{_b2s(msg_id)}"
            v = redis_conn.incr_with_ttl(key, int(SY_CMD_TRY_TTL_SEC))
            return int(v) > int(SY_CMD_MAX_TRIES)
        except Exception:
            return False

    def dlq_and_ack(msg_id, fields, reason: str, extra: Optional[dict] = None):
        redis_conn.dlq_push(reason=reason, msg_id=msg_id, fields=fields, extra=extra or {})
        try:
            redis_conn.xack(SY_CMD_STREAM, SY_CMD_GROUP, msg_id)
        except Exception as e:
            emit_event(
                f"[CmdStream][DLQ] ack failed id={_b2s(msg_id)} reason={reason} err={e}",
                category="dlq",
                level="ERROR",
                )

    def ack_ignore(msg_id, reason: str, extra: Optional[dict] = None):
        try:
            redis_conn.xack(SY_CMD_STREAM, SY_CMD_GROUP, msg_id)
            if DEBUG_TUNING.get("LOG_REDIS_STATE", True):
                detail = ""
                if extra:
                    detail = " " + " ".join(f"{k}={extra[k]}" for k in sorted(extra))
                emit_event(
                    f"[CmdIgnore] id={_b2s(msg_id)} reason={reason}{detail}",
                    category="cmd",
                    record_event=False,
                    plain_output=False,
                )
        except Exception as e:
            emit_event(
                f"[CmdIgnore] ack failed id={_b2s(msg_id)} reason={reason} err={e}",
                category="cmd",
                level="ERROR",
            )

    while running:
        if not redis_conn.is_ready():
            time.sleep(0.2)
            continue

        if bool(DEBUG_TUNING.get("PENDING_RETRY_ENABLE", True)):
            nowt = now_mono()
            if (nowt - last_claim) >= float(DEBUG_TUNING["PENDING_CLAIM_EVERY_SEC"]):
                last_claim = nowt
                try:
                    res = redis_conn.xautoclaim(
                        stream=SY_CMD_STREAM,
                        group=SY_CMD_GROUP,
                        consumer=SY_CMD_CONSUMER,
                        min_idle_ms=int(DEBUG_TUNING["PENDING_MIN_IDLE_MS"]),
                        start_id=pending_start,
                        count=int(DEBUG_TUNING["PENDING_CLAIM_COUNT"]),
                    )
                    next_start = res[0] if isinstance(res, (list, tuple)) and len(res) >= 1 else None
                    msgs = res[1] if isinstance(res, (list, tuple)) and len(res) >= 2 else []
                    if next_start:
                        pending_start = _b2s(next_start)

                    for msg_id, fields in (msgs or []):
                        try:
                            if not inflight_allow(msg_id):
                                continue

                            if too_many_tries(msg_id):
                                dlq_and_ack(msg_id, fields, "too_many_tries_pending")
                                continue

                            raw = fields.get(b"data") or fields.get("data") or fields.get(b"json") or fields.get("json")
                            if not raw:
                                dlq_and_ack(msg_id, fields, "pending_missing_data")
                                continue
                            try:
                                data = json.loads(_b2s(raw))
                            except Exception:
                                dlq_and_ack(msg_id, fields, "pending_json_parse_failed")
                                continue

                            state, nms_id, reason = _command_target_state(data)
                            if state == "ignore":
                                ack_ignore(msg_id, f"pending_{reason}", extra={"nms_id": nms_id or "-"})
                                continue
                            if state == "invalid" or nms_id is None:
                                dlq_and_ack(msg_id, fields, f"pending_{reason}", extra={"data": data})
                                continue

                            poller = nms_to_line.get(int(nms_id))
                            if not poller:
                                dlq_and_ack(msg_id, fields, "pending_unroutable", extra={"nms_id": nms_id})
                                continue

                            ok, reason = _enqueue_cmd_from_fields(msg_id=msg_id, fields=fields, poller=poller)
                            if not ok:
                                dlq_and_ack(msg_id, fields, f"pending_{reason}")
                        except Exception as e:
                            emit_event(
                                f"[CmdStream][PENDING] process error: {e}, id={_b2s(msg_id)}",
                                category="cmd",
                                level="ERROR",
                            )
                except Exception:
                    pass

        try:
            resp = redis_conn.xreadgroup(
                group=SY_CMD_GROUP,
                consumer=SY_CMD_CONSUMER,
                stream=SY_CMD_STREAM,
                count=SY_CMD_COUNT,
                block_ms=SY_CMD_BLOCK_MS,
            )
        except Exception:
            time.sleep(0.2)
            continue

        if not resp:
            continue

        for _stream_name, entries in resp:
            for msg_id, fields in entries:
                try:
                    if not inflight_allow(msg_id):
                        continue

                    if too_many_tries(msg_id):
                        dlq_and_ack(msg_id, fields, "too_many_tries_new")
                        continue

                    raw = fields.get(b"data") or fields.get(b"json") or fields.get("data") or fields.get("json")
                    if not raw:
                        dlq_and_ack(msg_id, fields, "missing_data_field")
                        continue
                    try:
                        data = json.loads(_b2s(raw))
                    except Exception:
                        dlq_and_ack(msg_id, fields, "json_parse_failed")
                        continue

                    state, nms_id, reason = _command_target_state(data)
                    if state == "ignore":
                        ack_ignore(msg_id, reason, extra={"nms_id": nms_id or "-"})
                        continue
                    if state == "invalid" or nms_id is None:
                        dlq_and_ack(msg_id, fields, reason, extra={"data": data})
                        continue

                    poller = nms_to_line.get(int(nms_id))
                    if not poller:
                        dlq_and_ack(msg_id, fields, "unroutable_nms_id", extra={"nms_id": nms_id})
                        continue

                    ok, reason = _enqueue_cmd_from_fields(msg_id=msg_id, fields=fields, poller=poller)
                    if not ok:
                        dlq_and_ack(msg_id, fields, reason, extra={"nms_id": nms_id})

                except Exception as e:
                    emit_event(
                        f"[CmdStream] process error: {e}, id={_b2s(msg_id)}",
                        category="cmd",
                        level="ERROR",
                    )
                    time.sleep(0.05)


# ============================================================
# 主函数
# ============================================================
def main():
    emit_event(
        f"startup mode={CONSOLE.mode} ansi={int(CONSOLE.ansi_enabled)} target={REDIS_HOST}:{REDIS_PORT}/{SY_STREAM_DB} "
        f"streams raw={SY_RAW_STREAM} cmd={SY_CMD_STREAM} group={SY_CMD_GROUP}",
        category="startup",
    )
    emit_event(
        f"timing wait={float(DEBUG_TUNING['WAIT_RESPONSE_TIMEOUT_SEC']):.3f}s auto_sleep={int(DEBUG_TUNING['AUTO_SLEEP_ENABLE'])} "
        f"after_sleep={ADAPT.get_sleep():.3f}s a2_burst={int(A2_BURST_ENABLE)} "
        f"bb_cmd_retries={SY_CMD_BB_CMD_RETRIES} no_resp_cmds={[hex(x) for x in sorted(NO_RESP_REQ_CMDS)]}",
        category="startup",
    )
    emit_event(
        f"agent host={socket.gethostname()} agent_ip={AGENT_IP} agent_name={AGENT_NAME} role={AGENT_ROLE} "
        f"consumer={SY_CMD_CONSUMER} pid={os.getpid()} config={CONFIG_PATH}",
        category="startup",
    )

    redis_conn = RedisConn(host=REDIS_HOST, port=REDIS_PORT, db=SY_STREAM_DB)
    CONSOLE.bind_runtime(redis_conn=redis_conn, pollers=[])
    CONSOLE.start()
    t_redis = threading.Thread(target=redis_conn.keepalive_loop, daemon=True)
    t_redis.start()

    emit_event("not blocking on redis ready; pollers will pause while redis is DOWN.", category="startup")

    if not running:
        emit_event("exit before start (signal).", category="startup", level="WARN")
        CONSOLE.stop()
        return 0

    pollers: List[LinePoller] = []
    CONSOLE.bind_runtime(pollers=pollers)
    for line_cfg in LINES_CONFIG:
        if not isinstance(line_cfg, dict):
            emit_event(f"skip invalid line cfg: {line_cfg!r}", category="startup", level="WARN")
            continue

        poller = LinePoller(line_cfg, redis_conn)
        poller.start()
        pollers.append(poller)
        CONSOLE.register_poller(poller)

        for d in line_cfg.get("devices", []):
            nms_id = int(d.get("nms_id", d["serial_id"]))
            d["nms_id"] = nms_id
            nms_to_line[nms_id] = poller

        devs = [{"serial_id": d["serial_id"], "nms_id": d.get("nms_id", d["serial_id"])} for d in line_cfg.get("devices", [])]
        emit_event(
            f"line started devices={devs}",
            category="startup",
            line_id=int(line_cfg.get("line_id", 0) or 0),
            line_name=str(line_cfg.get("name", f"Line-{line_cfg.get('line_id')}")),
        )

    t_cmd = threading.Thread(target=redis_command_thread, args=(redis_conn,), daemon=True)
    t_cmd.start()
    t_route = threading.Thread(target=route_refresh_thread, args=(redis_conn,), daemon=True)
    t_route.start()

    try:
        while running:
            time.sleep(0.5)
    finally:
        emit_event("shutting down...", category="startup", level="WARN")
        for p in pollers:
            p.join(timeout=1.0)

    emit_event("bye.", category="startup")
    CONSOLE.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
