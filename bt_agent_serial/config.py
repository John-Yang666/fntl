from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from protected_runtime import agent_config_path, write_json_file

CONFIG_JSON_ENV = "BT_AGENT_SERIAL_CONFIG_JSON"
APP_NAME = "bt_agent_serial"
CONFIG_PATH: Path

DEFAULT_CONFIG: dict[str, Any] = {
    "device": {"nms_id": 1},
    "serial": {
        "port": "COM5",
        "baudrate": 57600,
        "parity": "O",
        "bytesize": 8,
        "stopbits": 1,
        "timeout": 0.0,
        "write_timeout": 0.0,
        "frame_len": 44,
        "idle_sleep_sec": 0.05,
        "comm_lost_miss_count": 20,
    },
    "redis": {
        "host": "127.0.0.1",
        "port": 36379,
        "db": 0,
        "startup_retry_sec": 2.0,
    },
    "stream": {
        "packet_stream_key": "stream:udp:packets",
        "packet_maxlen": 200000,
    },
    "ui": {"auto_start": False},
}


def deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_json_config(path: Path) -> dict:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return loaded


def load_config() -> dict:
    global CONFIG_PATH
    runtime_config = str(os.environ.get(CONFIG_JSON_ENV, "")).strip()
    if runtime_config:
        CONFIG_PATH = Path(runtime_config).expanduser().resolve()
        loaded = load_json_config(CONFIG_PATH)
    else:
        CONFIG_PATH = agent_config_path(APP_NAME)
        if not CONFIG_PATH.exists():
            write_json_file(CONFIG_PATH, copy.deepcopy(DEFAULT_CONFIG))
        loaded = load_json_config(CONFIG_PATH)
    return deep_merge(copy.deepcopy(DEFAULT_CONFIG), loaded)


def normalize_config(config: dict) -> dict:
    return deep_merge(copy.deepcopy(DEFAULT_CONFIG), copy.deepcopy(config or {}))
