from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError

from consts import (
    COMMUNICATION_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
    SWITCH_DATA_TIMEOUT,
    SY_ALARM_DELAY,
    SY_ALARM_MEANINGS,
    TOPOLOGY_TIMEOUT,
)


RUNTIME_CONFIG_CACHE_KEY = "sy_runtime_config_payload"
RUNTIME_CONFIG_SINGLETON_PK = 1
ALARM_DELAY_FIELD_KEY = "SY_ALARM_DELAY"


def _jwt_days(setting_key: str) -> int:
    lifetime = settings.SIMPLE_JWT[setting_key]
    if hasattr(lifetime, "total_seconds"):
        total_seconds = int(lifetime.total_seconds())
        return max(total_seconds // 86400, 1)
    return 1


FIELD_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "COMMUNICATION_TIMEOUT",
        "label": "通信超时（秒）",
        "type": "integer",
        "group": "runtime",
        "min": 1,
        "max": 86400,
        "default": COMMUNICATION_TIMEOUT,
    },
    {
        "key": "TOPOLOGY_TIMEOUT",
        "label": "拓扑缓存时长（秒）",
        "type": "integer",
        "group": "runtime",
        "min": 1,
        "max": 86400,
        "default": TOPOLOGY_TIMEOUT,
    },
    {
        "key": "SWITCH_DATA_TIMEOUT",
        "label": "开关量缓存时长（秒）",
        "type": "integer",
        "group": "runtime",
        "min": 1,
        "max": 86400,
        "default": SWITCH_DATA_TIMEOUT,
    },
    {
        "key": "HEARTBEAT_TIMEOUT",
        "label": "接收心跳超时（秒）",
        "type": "integer",
        "group": "runtime",
        "min": 1,
        "max": 86400,
        "default": HEARTBEAT_TIMEOUT,
    },
    {
        "key": "PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL",
        "label": "设备缓存刷新间隔（秒）",
        "type": "integer",
        "group": "runtime",
        "min": 1,
        "max": 86400,
        "default": PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
    },
    {
        "key": ALARM_DELAY_FIELD_KEY,
        "label": "告警延时（秒）",
        "type": "alarm_delay_map",
        "group": "runtime",
        "min": 0,
        "max": 86400,
        "default": SY_ALARM_DELAY,
        "alarm_meanings": SY_ALARM_MEANINGS,
    },
    {
        "key": "JWT_ACCESS_TOKEN_LIFETIME_DAYS",
        "label": "Access Token 有效期（天）",
        "type": "integer",
        "group": "auth",
        "min": 1,
        "max": 999999,
        "default": _jwt_days("ACCESS_TOKEN_LIFETIME"),
    },
    {
        "key": "JWT_REFRESH_TOKEN_LIFETIME_DAYS",
        "label": "Refresh Token 有效期（天）",
        "type": "integer",
        "group": "auth",
        "min": 1,
        "max": 999999,
        "default": _jwt_days("REFRESH_TOKEN_LIFETIME"),
    },
)


def _field_map() -> dict[str, dict[str, Any]]:
    return {field["key"]: field for field in FIELD_DEFINITIONS}


def _default_values() -> dict[str, Any]:
    return {
        field["key"]: deepcopy(field["default"])
        for field in FIELD_DEFINITIONS
    }


def _normalize_int(value: Any, *, field: dict[str, Any]) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field['label']}必须是整数。")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field['label']}必须是整数。") from exc

    min_value = field.get("min")
    max_value = field.get("max")
    if min_value is not None and parsed < min_value:
        raise ValueError(f"{field['label']}不能小于{min_value}。")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"{field['label']}不能大于{max_value}。")
    return parsed


def _normalize_alarm_delay_map(value: Any, *, field: dict[str, Any]) -> dict[int, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field['label']}必须是对象。")

    expected_codes = {int(code) for code in field["default"].keys()}
    normalized: dict[int, int] = {}
    for raw_key, raw_delay in value.items():
        try:
            code = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field['label']}包含无效告警码：{raw_key}") from exc
        if code not in expected_codes:
            raise ValueError(f"{field['label']}包含未知告警码：{code}")
        normalized[code] = _normalize_int(value=raw_delay, field=field)

    if set(normalized.keys()) != expected_codes:
        missing_codes = sorted(expected_codes - set(normalized.keys()))
        raise ValueError(f"{field['label']}缺少告警码：{', '.join(str(code) for code in missing_codes)}")

    return normalized


def validate_runtime_config_values(values: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise ValueError("values 必须是对象。")

    fields = _field_map()
    unknown_keys = sorted(set(values.keys()) - set(fields.keys()))
    if unknown_keys:
        raise ValueError(f"包含未知配置项：{', '.join(unknown_keys)}")

    validated = _default_values()
    for key, field in fields.items():
        if key not in values:
            continue
        if field["type"] == "integer":
            validated[key] = _normalize_int(values[key], field=field)
        elif field["type"] == "alarm_delay_map":
            validated[key] = _normalize_alarm_delay_map(values[key], field=field)
        else:
            raise ValueError(f"不支持的配置类型：{field['type']}")
    return validated


def _schema() -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    for field in FIELD_DEFINITIONS:
        item = {
            "key": field["key"],
            "label": field["label"],
            "type": field["type"],
            "group": field["group"],
            "min": field.get("min"),
            "max": field.get("max"),
            "default": deepcopy(field["default"]),
        }
        if field["type"] == "alarm_delay_map":
            item["codes"] = sorted(int(code) for code in field["default"].keys())
            item["alarm_meanings"] = {
                str(code): meaning for code, meaning in field["alarm_meanings"].items()
            }
        schema.append(item)
    return schema


def _describe_runtime_config_changes(
    previous_values: Mapping[str, Any],
    next_values: Mapping[str, Any],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key, field in _field_map().items():
        previous_value = previous_values.get(key)
        next_value = next_values.get(key)
        if field["type"] == "alarm_delay_map":
            previous_map = previous_value if isinstance(previous_value, Mapping) else {}
            next_map = next_value if isinstance(next_value, Mapping) else {}
            codes = sorted({int(code) for code in previous_map.keys()} | {int(code) for code in next_map.keys()})
            for code in codes:
                old_delay = previous_map.get(code)
                if old_delay is None:
                    old_delay = previous_map.get(str(code))
                new_delay = next_map.get(code)
                if new_delay is None:
                    new_delay = next_map.get(str(code))
                if old_delay != new_delay:
                    changes.append(
                        {
                            "key": key,
                            "code": int(code),
                            "old_value": int(old_delay),
                            "new_value": int(new_delay),
                        }
                    )
            continue
        if previous_value != next_value:
            changes.append(
                {
                    "key": key,
                    "old_value": previous_value,
                    "new_value": next_value,
                }
            )
    return changes


def _format_runtime_config_change(change: Mapping[str, Any]) -> str:
    key = str(change["key"])
    if "code" in change:
        detail = f"{key}[{int(change['code'])}]: {change['old_value']}->{change['new_value']}"
    else:
        detail = f"{key}: {change['old_value']}->{change['new_value']}"
    return f"修改SY系统设置（{detail}）"


def _log_runtime_config_update(*, user, changes: list[dict[str, Any]]) -> None:
    if not changes:
        return

    from myapp.models import UserOperation

    username = getattr(user, "username", None)
    operations = [
        UserOperation(
            device=None,
            function_code="runtime_config_update",
            operation=_format_runtime_config_change(change)[:100],
            username=username,
        )
        for change in changes
    ]
    UserOperation.objects.bulk_create(operations)


def _load_model():
    from myapp.models import RuntimeConfig

    return RuntimeConfig


def _load_runtime_config_record():
    RuntimeConfig = _load_model()
    try:
        return RuntimeConfig.objects.filter(pk=RUNTIME_CONFIG_SINGLETON_PK).first()
    except (OperationalError, ProgrammingError):
        return None


def build_runtime_config_payload(*, force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = cache.get(RUNTIME_CONFIG_CACHE_KEY)
        if cached is not None:
            return deepcopy(cached)

    defaults = _default_values()
    storage_ready = True
    record = _load_runtime_config_record()
    stored_values = record.values if record and isinstance(record.values, Mapping) else {}
    if record is None:
        RuntimeConfig = _load_model()
        try:
            RuntimeConfig.objects.exists()
        except (OperationalError, ProgrammingError):
            storage_ready = False
    values = validate_runtime_config_values(stored_values)
    payload = {
        "schema": _schema(),
        "defaults": defaults,
        "values": values,
        "updated_at": record.updated_at.isoformat() if record and record.updated_at else None,
        "updated_by": record.updated_by.username if record and record.updated_by else None,
        "storage_ready": storage_ready,
    }
    cache.set(RUNTIME_CONFIG_CACHE_KEY, payload, timeout=None)
    return deepcopy(payload)


def get_runtime_config_values(*, force_refresh: bool = False) -> dict[str, Any]:
    return build_runtime_config_payload(force_refresh=force_refresh)["values"]


def save_runtime_config_values(*, values: Mapping[str, Any], user) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise ValueError("values 必须是对象。")
    current_payload = build_runtime_config_payload(force_refresh=True)
    if not current_payload.get("storage_ready", True):
        raise ValueError("运行时配置表尚未迁移完成，当前只能查看默认值，暂时无法保存。")
    current_values = current_payload["values"]
    merged_values = deepcopy(current_values)
    merged_values.update(dict(values))
    validated = validate_runtime_config_values(merged_values)
    changes = _describe_runtime_config_changes(current_values, validated)
    RuntimeConfig = _load_model()
    try:
        with transaction.atomic():
            record, _created = RuntimeConfig.objects.select_for_update().get_or_create(
                pk=RUNTIME_CONFIG_SINGLETON_PK,
                defaults={"values": validated, "updated_by": user},
            )
            record.values = validated
            record.updated_by = user
            record.save(update_fields=["values", "updated_by", "updated_at"])
            _log_runtime_config_update(user=user, changes=changes)
    except (OperationalError, ProgrammingError) as exc:
        raise ValueError("运行时配置表尚未迁移完成，当前只能查看默认值，暂时无法保存。") from exc

    return build_runtime_config_payload(force_refresh=True)


def get_communication_timeout() -> int:
    return int(get_runtime_config_values()["COMMUNICATION_TIMEOUT"])


def get_topology_timeout() -> int | None:
    timeout = get_runtime_config_values()["TOPOLOGY_TIMEOUT"]
    return None if timeout is None else int(timeout)


def get_switch_data_timeout() -> int:
    return int(get_runtime_config_values()["SWITCH_DATA_TIMEOUT"])


def get_heartbeat_timeout() -> int:
    return int(get_runtime_config_values()["HEARTBEAT_TIMEOUT"])


def get_periodic_device_cache_refresh_interval() -> int:
    return int(get_runtime_config_values()["PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL"])


def get_alarm_delay_map() -> dict[int, int]:
    raw_value = get_runtime_config_values()[ALARM_DELAY_FIELD_KEY]
    return {int(code): int(delay) for code, delay in raw_value.items()}


def get_jwt_access_token_lifetime() -> timedelta:
    values = get_runtime_config_values()
    return timedelta(days=int(values["JWT_ACCESS_TOKEN_LIFETIME_DAYS"]))


def get_jwt_refresh_token_lifetime() -> timedelta:
    values = get_runtime_config_values()
    return timedelta(days=int(values["JWT_REFRESH_TOKEN_LIFETIME_DAYS"]))
