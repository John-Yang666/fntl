from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SYSTEMS = ("bt", "sy")
SYSTEM_LABELS = {"bt": "BT", "sy": "SY"}
CONFIG_DIR = Path.home() / ".bt_nms_alarm_client"
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_PATH = CONFIG_DIR / "alarm_client.log"
LOCK_PATH = CONFIG_DIR / "alarm_client.lock"
_PASSWORD_MASK_KEY = b"BT_NMS_ALARM_CLIENT_STATIC_MASK_V1"


def _xor_bytes(data: bytes) -> bytes:
    return bytes(byte ^ _PASSWORD_MASK_KEY[index % len(_PASSWORD_MASK_KEY)] for index, byte in enumerate(data))


def encode_password(password: str) -> str:
    raw = password.encode("utf-8")
    return base64.urlsafe_b64encode(_xor_bytes(raw)).decode("ascii")


def decode_password(encoded: str) -> str:
    if not encoded:
        return ""
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    return _xor_bytes(raw).decode("utf-8")


@dataclass
class SystemConfig:
    api_base: str
    enabled: bool = True


@dataclass
class Credentials:
    username: str = ""
    password: str = ""


@dataclass
class AppConfig:
    systems: dict[str, SystemConfig] = field(default_factory=dict)
    selected_devices: set[str] = field(default_factory=set)
    credentials: Credentials = field(default_factory=Credentials)
    poll_interval_seconds: int = 3

    @classmethod
    def default(cls) -> "AppConfig":
        return cls(
            systems={
                "bt": SystemConfig(api_base="http://127.0.0.1:8000/api"),
                "sy": SystemConfig(api_base="http://127.0.0.1:8001/api"),
            }
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        default = cls.default()
        raw_systems = data.get("systems") if isinstance(data.get("systems"), dict) else {}
        systems = dict(default.systems)
        for system in SYSTEMS:
            raw = raw_systems.get(system, {})
            if isinstance(raw, dict):
                systems[system] = SystemConfig(
                    api_base=str(raw.get("api_base") or systems[system].api_base).rstrip("/"),
                    enabled=bool(raw.get("enabled", True)),
                )

        credentials_data = data.get("credentials") if isinstance(data.get("credentials"), dict) else {}
        password = ""
        encoded_password = credentials_data.get("password_encoded") if isinstance(credentials_data, dict) else ""
        if encoded_password:
            try:
                password = decode_password(str(encoded_password))
            except Exception:
                password = ""

        raw_selected = data.get("selected_devices", [])
        selected_devices = {str(item) for item in raw_selected if isinstance(item, str)}

        return cls(
            systems=systems,
            selected_devices=selected_devices,
            credentials=Credentials(
                username=str(credentials_data.get("username") or ""),
                password=password,
            ),
            poll_interval_seconds=max(1, int(data.get("poll_interval_seconds") or 3)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "systems": {
                system: {"api_base": config.api_base.rstrip("/"), "enabled": config.enabled}
                for system, config in self.systems.items()
            },
            "selected_devices": sorted(self.selected_devices),
            "credentials": {
                "username": self.credentials.username,
                "password_encoded": encode_password(self.credentials.password),
            },
            "poll_interval_seconds": self.poll_interval_seconds,
        }


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        return AppConfig.default()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return AppConfig.default()
    return AppConfig.from_dict(data)


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@dataclass
class AlertEvaluation:
    alerts: list[dict[str, Any]]
    has_new_unconfirmed_alerts: bool
    has_unconfirmed_alerts: bool
    ended_systems: list[str]
    should_play_sound: bool

    @property
    def count(self) -> int:
        return len(self.alerts)


class AlertRuntimeState:
    def __init__(self, selected_devices: set[str] | None = None):
        self.selected_devices = selected_devices or set()
        self.previous_alert_keys_by_system = {system: set() for system in SYSTEMS}
        self.previous_has_unconfirmed_alerts = False
        self.paused = False

    def set_selected_devices(self, selected_devices: set[str]) -> None:
        self.selected_devices = set(selected_devices)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def reset(self) -> None:
        self.previous_alert_keys_by_system = {system: set() for system in SYSTEMS}
        self.previous_has_unconfirmed_alerts = False
        self.paused = False

    def evaluate(self, alerts_by_system: dict[str, list[dict[str, Any]]]) -> AlertEvaluation:
        filtered_alerts = self._filtered_alerts(alerts_by_system)
        current_keys_by_system = {system: set() for system in SYSTEMS}
        current_unconfirmed_keys_by_system = {system: set() for system in SYSTEMS}

        for alert in filtered_alerts:
            system = str(alert["system"])
            key = self.build_alert_key(system, alert.get("device_id"), alert.get("alarm_code"))
            current_keys_by_system[system].add(key)
            if not bool(alert.get("confirmed")):
                current_unconfirmed_keys_by_system[system].add(key)

        has_new_unconfirmed = False
        ended_systems: list[str] = []
        for system in SYSTEMS:
            previous_keys = self.previous_alert_keys_by_system.get(system, set())
            current_keys = current_keys_by_system[system]
            current_unconfirmed_keys = current_unconfirmed_keys_by_system[system]
            if any(key not in previous_keys for key in current_unconfirmed_keys):
                has_new_unconfirmed = True
            if any(key not in current_keys for key in previous_keys):
                ended_systems.append(system)

        if has_new_unconfirmed:
            self.paused = False

        has_unconfirmed = any(not bool(alert.get("confirmed")) for alert in filtered_alerts)
        all_current_confirmed = bool(filtered_alerts) and not has_unconfirmed
        if self.previous_has_unconfirmed_alerts and all_current_confirmed:
            self.paused = True

        should_play = has_unconfirmed and not self.paused and has_new_unconfirmed

        self.previous_alert_keys_by_system = current_keys_by_system
        self.previous_has_unconfirmed_alerts = has_unconfirmed

        return AlertEvaluation(
            alerts=filtered_alerts,
            has_new_unconfirmed_alerts=has_new_unconfirmed,
            has_unconfirmed_alerts=has_unconfirmed,
            ended_systems=ended_systems,
            should_play_sound=should_play,
        )

    def _filtered_alerts(self, alerts_by_system: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for system in SYSTEMS:
            for raw_alert in alerts_by_system.get(system, []):
                device_id = raw_alert.get("device_id")
                if self.selected_devices and f"{system}:{device_id}" not in self.selected_devices:
                    continue
                alert = dict(raw_alert)
                alert["system"] = system
                result.append(alert)
        return result

    @staticmethod
    def build_alert_key(system: str, device_id: Any, alarm_code: Any) -> str:
        return f"{system}:{device_id}-{alarm_code}"
