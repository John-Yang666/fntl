from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SYSTEMS = ("bt", "sy")
SYSTEM_LABELS = {"bt": "BT", "sy": "SY"}
CONFIG_DIR = Path.home() / ".bt_nms_alarm_client"
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_PATH = CONFIG_DIR / "alarm_client.log"
LOCK_PATH = CONFIG_DIR / "alarm_client.lock"
_PASSWORD_MASK_KEY = b"BT_NMS_ALARM_CLIENT_STATIC_MASK_V1"


DEFAULT_FRONTEND_ORIGIN = "http://127.0.0.1:38173"
DEFAULT_API_BASES = {
    "bt": f"{DEFAULT_FRONTEND_ORIGIN}/bt-api",
    "sy": f"{DEFAULT_FRONTEND_ORIGIN}/sy-api",
}


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
    credentials: Credentials = field(default_factory=Credentials)

    @classmethod
    def default(cls) -> "AppConfig":
        return cls(
            systems={
                "bt": SystemConfig(api_base=DEFAULT_API_BASES["bt"]),
                "sy": SystemConfig(api_base=DEFAULT_API_BASES["sy"]),
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
                    api_base=normalize_api_base(system, str(raw.get("api_base") or systems[system].api_base)),
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

        return cls(
            systems=systems,
            credentials=Credentials(
                username=str(credentials_data.get("username") or ""),
                password=password,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "systems": {
                system: {"api_base": config.api_base.rstrip("/"), "enabled": config.enabled}
                for system, config in self.systems.items()
            },
            "credentials": {
                "username": self.credentials.username,
                "password_encoded": encode_password(self.credentials.password),
            },
        }


def normalize_api_base(system: str, value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return DEFAULT_API_BASES.get(system, raw)

    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw

    hostname = parsed.hostname or ""
    port = parsed.port
    if port in {8000, 8001}:
        port = 38173
    elif port in {8443, 8444}:
        port = 38443

    if parsed.port is None:
        netloc = parsed.netloc
    elif parsed.username or parsed.password:
        auth = parsed.username or ""
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
        netloc = f"{auth}@{host}:{port}"
    else:
        host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
        netloc = f"{host}:{port}"

    expected_path = f"/{system}-api"
    path = parsed.path.rstrip("/")
    if path in {"", "/", "/api"}:
        path = expected_path

    return urlunsplit((parsed.scheme, netloc, path, "", "")).rstrip("/")


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
    total_unconfirmed_count: int
    has_new_unconfirmed_alerts: bool
    has_unconfirmed_alerts: bool
    should_play_sound: bool


class AlertRuntimeState:
    """Combines server snapshots and keeps only the local manual-silence state."""

    def __init__(self):
        self.snapshots: dict[str, dict[str, Any] | None] = {system: None for system in SYSTEMS}
        self.silenced_occurrence_ids: set[str] = set()
        self.previous_audible_ids: set[str] = set()

    def pause(self) -> None:
        self.silenced_occurrence_ids.update(self.audible_occurrence_ids())

    def resume(self) -> None:
        self.silenced_occurrence_ids.clear()

    def reset(self) -> None:
        self.snapshots = {system: None for system in SYSTEMS}
        self.silenced_occurrence_ids.clear()
        self.previous_audible_ids.clear()

    def update_snapshot(self, system: str, snapshot: dict[str, Any]) -> AlertEvaluation:
        if system not in SYSTEMS:
            raise ValueError(f"unknown system: {system}")
        previous = self.snapshots.get(system)
        if previous is not None and int(snapshot.get("revision", 0)) < int(previous.get("revision", 0)):
            return self.evaluation()
        self.snapshots[system] = dict(snapshot)
        audible = self.audible_occurrence_ids()
        has_new = bool(audible - self.previous_audible_ids)
        if not audible:
            self.silenced_occurrence_ids.clear()
        self.previous_audible_ids = audible
        return self.evaluation(has_new=has_new)

    def audible_occurrence_ids(self) -> set[str]:
        result: set[str] = set()
        for system in SYSTEMS:
            snapshot = self.snapshots.get(system) or {}
            for occurrence_id in snapshot.get("audible_occurrence_ids", []):
                result.add(f"{system}:{occurrence_id}")
        return result

    def evaluation(self, *, has_new: bool = False) -> AlertEvaluation:
        audible = self.audible_occurrence_ids()
        total = sum(int((self.snapshots.get(system) or {}).get("total_unconfirmed_count", 0)) for system in SYSTEMS)
        return AlertEvaluation(
            total_unconfirmed_count=total,
            has_new_unconfirmed_alerts=has_new,
            has_unconfirmed_alerts=bool(audible),
            should_play_sound=bool(audible - self.silenced_occurrence_ids),
        )
