from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import timedelta
import ipaddress
import json
import logging
import re
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError

from consts import (
    ALARM_DELAY,
    ALARM_MEANINGS,
    COMMUNICATION_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL,
    SWITCH_DATA_TIMEOUT,
    TOPOLOGY_TIMEOUT,
)


RUNTIME_CONFIG_CACHE_KEY = "bt_runtime_config_payload"
RUNTIME_CONFIG_SINGLETON_PK = 1
logger = logging.getLogger(__name__)
ALARM_DELAY_FIELD_KEY = "ALARM_DELAY"
CLEANUP_TASK_NAME = "My Daily Task"
CLEANUP_SCHEDULE_TIME_KEY = "CLEANUP_SCHEDULE_TIME"
CLEANUP_DEFAULT_SCHEDULE_TIME = "03:00"
CLEANUP_TIME_PATTERN = re.compile(r"^(?P<hour>\d{2}):(?P<minute>\d{2})$")
CLEANUP_DEFAULT_ARGS = {
    "CLEANUP_SWITCH_DATA_DAYS": 3,
    "CLEANUP_ANALOG_DATA_DAYS": 3,
    "CLEANUP_ALARM_DATA_DAYS": 30,
    "CLEANUP_RELAY_ACTION_DAYS": 30,
    "CLEANUP_USER_OPERATION_DAYS": 30,
}
CLEANUP_DAY_FIELD_KEYS = tuple(CLEANUP_DEFAULT_ARGS.keys())
CLEANUP_AUTO_EXPORT_DEFAULTS = {
    key.replace("_DAYS", "_AUTO_EXPORT"): True
    for key in CLEANUP_DAY_FIELD_KEYS
}
CLEANUP_AUTO_EXPORT_FIELD_KEYS = tuple(CLEANUP_AUTO_EXPORT_DEFAULTS.keys())
DEPLOY_HOST_IP_FIELD_KEY = "DEPLOY_HOST_IPS"
DEPLOY_HOST_IP_HELP_TEXT = "支持写一个或多个，多个可用逗号、分号或换行分隔"
DEPLOY_HOST_IP_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "、": ",",
        "；": ";",
        "。": ".",
        "．": ".",
        "｡": ".",
        "：": ":",
        "　": " ",
    }
)
DEPLOY_HOST_IP_NORMALIZED_HELP_TEXT = DEPLOY_HOST_IP_HELP_TEXT.translate(
    DEPLOY_HOST_IP_PUNCTUATION_TRANSLATION
)
DEPLOY_HOST_IP_LEGACY_HINT_LINES = {
    DEPLOY_HOST_IP_HELP_TEXT,
    f"# {DEPLOY_HOST_IP_HELP_TEXT}",
    DEPLOY_HOST_IP_NORMALIZED_HELP_TEXT,
    f"# {DEPLOY_HOST_IP_NORMALIZED_HELP_TEXT}",
}


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
        "default": ALARM_DELAY,
        "alarm_meanings": ALARM_MEANINGS,
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
    {
        "key": CLEANUP_SCHEDULE_TIME_KEY,
        "label": "清理执行时间",
        "type": "time",
        "group": "cleanup",
        "default": CLEANUP_DEFAULT_SCHEDULE_TIME,
    },
    {
        "key": "CLEANUP_SWITCH_DATA_DAYS",
        "label": "SwitchData 保留天数",
        "type": "integer",
        "group": "cleanup",
        "min": 1,
        "max": 999999,
        "default": CLEANUP_DEFAULT_ARGS["CLEANUP_SWITCH_DATA_DAYS"],
    },
    {
        "key": "CLEANUP_SWITCH_DATA_AUTO_EXPORT",
        "label": "SwitchData 自动导出",
        "type": "boolean",
        "group": "cleanup",
        "default": CLEANUP_AUTO_EXPORT_DEFAULTS["CLEANUP_SWITCH_DATA_AUTO_EXPORT"],
    },
    {
        "key": "CLEANUP_ANALOG_DATA_DAYS",
        "label": "AnalogData 保留天数",
        "type": "integer",
        "group": "cleanup",
        "min": 1,
        "max": 999999,
        "default": CLEANUP_DEFAULT_ARGS["CLEANUP_ANALOG_DATA_DAYS"],
    },
    {
        "key": "CLEANUP_ANALOG_DATA_AUTO_EXPORT",
        "label": "AnalogData 自动导出",
        "type": "boolean",
        "group": "cleanup",
        "default": CLEANUP_AUTO_EXPORT_DEFAULTS["CLEANUP_ANALOG_DATA_AUTO_EXPORT"],
    },
    {
        "key": "CLEANUP_ALARM_DATA_DAYS",
        "label": "AlarmData 保留天数",
        "type": "integer",
        "group": "cleanup",
        "min": 1,
        "max": 999999,
        "default": CLEANUP_DEFAULT_ARGS["CLEANUP_ALARM_DATA_DAYS"],
    },
    {
        "key": "CLEANUP_ALARM_DATA_AUTO_EXPORT",
        "label": "AlarmData 自动导出",
        "type": "boolean",
        "group": "cleanup",
        "default": CLEANUP_AUTO_EXPORT_DEFAULTS["CLEANUP_ALARM_DATA_AUTO_EXPORT"],
    },
    {
        "key": "CLEANUP_RELAY_ACTION_DAYS",
        "label": "RelayAction 保留天数",
        "type": "integer",
        "group": "cleanup",
        "min": 1,
        "max": 999999,
        "default": CLEANUP_DEFAULT_ARGS["CLEANUP_RELAY_ACTION_DAYS"],
    },
    {
        "key": "CLEANUP_RELAY_ACTION_AUTO_EXPORT",
        "label": "RelayAction 自动导出",
        "type": "boolean",
        "group": "cleanup",
        "default": CLEANUP_AUTO_EXPORT_DEFAULTS["CLEANUP_RELAY_ACTION_AUTO_EXPORT"],
    },
    {
        "key": "CLEANUP_USER_OPERATION_DAYS",
        "label": "UserOperation 保留天数",
        "type": "integer",
        "group": "cleanup",
        "min": 1,
        "max": 999999,
        "default": CLEANUP_DEFAULT_ARGS["CLEANUP_USER_OPERATION_DAYS"],
    },
    {
        "key": "CLEANUP_USER_OPERATION_AUTO_EXPORT",
        "label": "UserOperation 自动导出",
        "type": "boolean",
        "group": "cleanup",
        "default": CLEANUP_AUTO_EXPORT_DEFAULTS["CLEANUP_USER_OPERATION_AUTO_EXPORT"],
    },
)


def _field_map() -> dict[str, dict[str, Any]]:
    return {field["key"]: field for field in FIELD_DEFINITIONS}


def _default_values() -> dict[str, Any]:
    return {
        field["key"]: deepcopy(field["default"])
        for field in FIELD_DEFINITIONS
    }


def _cleanup_field_keys() -> set[str]:
    return {field["key"] for field in FIELD_DEFINITIONS if field["group"] == "cleanup"}


def _runtime_field_keys() -> set[str]:
    return {field["key"] for field in FIELD_DEFINITIONS if field["group"] != "cleanup"}


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


def _normalize_alarm_delay_map(
    value: Any,
    *,
    field: dict[str, Any],
    fill_missing: bool = False,
) -> dict[int, int]:
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

    if fill_missing:
        for code in expected_codes - set(normalized.keys()):
            normalized[code] = _normalize_int(value=field["default"][code], field=field)

    if set(normalized.keys()) != expected_codes:
        missing_codes = sorted(expected_codes - set(normalized.keys()))
        raise ValueError(f"{field['label']}缺少告警码：{', '.join(str(code) for code in missing_codes)}")

    return normalized


def _normalize_time(value: Any, *, field: dict[str, Any]) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field['label']}必须是HH:mm格式。")

    match = CLEANUP_TIME_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"{field['label']}必须是HH:mm格式。")

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if hour > 23 or minute > 59:
        raise ValueError(f"{field['label']}必须是合法时间。")
    return f"{hour:02d}:{minute:02d}"


def _normalize_bool(value: Any, *, field: dict[str, Any]) -> bool:
    if isinstance(value, bool):
        return value
    if value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field['label']}必须是布尔值。")


def validate_runtime_config_values(
    values: Mapping[str, Any] | None,
    *,
    fill_missing_alarm_delay: bool = False,
) -> dict[str, Any]:
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
        elif field["type"] == "time":
            validated[key] = _normalize_time(values[key], field=field)
        elif field["type"] == "boolean":
            validated[key] = _normalize_bool(values[key], field=field)
        elif field["type"] == "alarm_delay_map":
            validated[key] = _normalize_alarm_delay_map(
                values[key],
                field=field,
                fill_missing=fill_missing_alarm_delay,
            )
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


def _deploy_host_file() -> Any:
    return settings.BASE_DIR / "deploy_host_ip.txt"


def _read_deploy_host_file_content() -> str:
    deploy_host_file = _deploy_host_file()
    if not deploy_host_file.exists():
        return ""
    return deploy_host_file.read_text(encoding="utf-8")


def _normalize_deploy_host_file_content(value: str) -> str:
    normalized = (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .translate(DEPLOY_HOST_IP_PUNCTUATION_TRANSLATION)
    )
    lines = [
        line.rstrip()
        for line in normalized.split("\n")
        if line.strip() not in DEPLOY_HOST_IP_LEGACY_HINT_LINES
    ]
    return "\n".join(lines)


def _deploy_host_entries(value: str) -> list[str]:
    entries: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        entries.extend(
            item.strip()
            for item in re.split(r"[,;\s]+", line)
            if item.strip()
        )
    return entries


def _validate_deploy_host_file_content(value: str) -> str:
    normalized = _normalize_deploy_host_file_content(value)
    invalid_entries: list[str] = []
    for entry in _deploy_host_entries(normalized):
        try:
            ipaddress.ip_address(entry)
        except ValueError:
            invalid_entries.append(entry)
    if invalid_entries:
        raise ValueError(
            "网管IP格式不正确："
            f"{', '.join(invalid_entries)}。"
            f"{DEPLOY_HOST_IP_HELP_TEXT}。"
        )
    return normalized


def _file_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": DEPLOY_HOST_IP_FIELD_KEY,
            "label": "网管IP",
            "type": "textarea",
            "group": "security",
            "description": "配置文件：backend/deploy_host_ip.txt，保存后重启容器生效",
            "help_text": DEPLOY_HOST_IP_HELP_TEXT,
            "placeholder": "每行填写一个网管电脑 IP，例如 192.168.0.87",
        },
    ]


def _file_values() -> dict[str, str]:
    return {
        DEPLOY_HOST_IP_FIELD_KEY: _read_deploy_host_file_content(),
    }


def _normalize_file_values(file_values: Mapping[str, Any] | None) -> dict[str, str]:
    if file_values is None:
        return {}
    if not isinstance(file_values, Mapping):
        raise ValueError("file_values 必须是对象。")

    allowed_keys = {DEPLOY_HOST_IP_FIELD_KEY}
    unknown_keys = sorted(set(file_values.keys()) - allowed_keys)
    if unknown_keys:
        raise ValueError(f"包含未知配置文件项：{', '.join(unknown_keys)}")

    normalized: dict[str, str] = {}
    for key, value in file_values.items():
        if not isinstance(value, str):
            raise ValueError("网管IP配置文件内容必须是文本。")
        if "\x00" in value:
            raise ValueError("网管IP配置文件内容不能包含空字符。")
        normalized[str(key)] = _validate_deploy_host_file_content(value)
    return normalized


def _save_file_values(file_values: Mapping[str, str]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if DEPLOY_HOST_IP_FIELD_KEY not in file_values:
        return errors
    deploy_host_file = _deploy_host_file()
    try:
        deploy_host_file.parent.mkdir(parents=True, exist_ok=True)
        deploy_host_file.write_text(file_values[DEPLOY_HOST_IP_FIELD_KEY], encoding="utf-8")
    except OSError as exc:
        errors[DEPLOY_HOST_IP_FIELD_KEY] = "无法写入网管IP配置文件，请检查 deploy_host_ip.txt 挂载是否为可写。"
        logger.warning("Unable to write deploy host IP file %s: %s", deploy_host_file, exc)
    return errors


def _settings_list(setting_name: str) -> list[str]:
    value = getattr(settings, setting_name, [])
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _readonly_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "DJANGO_ALLOWED_HOSTS",
            "label": "DJANGO_ALLOWED_HOSTS",
            "type": "text",
            "group": "security",
            "value": _settings_list("ALLOWED_HOSTS"),
            "description": "Django settings.ALLOWED_HOSTS 当前生效值",
        },
        {
            "key": "CORS_ALLOWED_ORIGINS",
            "label": "CORS_ALLOWED_ORIGINS",
            "type": "text",
            "group": "security",
            "value": _settings_list("CORS_ALLOWED_ORIGINS"),
            "description": "Django settings.CORS_ALLOWED_ORIGINS 当前生效值",
        },
        {
            "key": "CSRF_TRUSTED_ORIGINS",
            "label": "CSRF_TRUSTED_ORIGINS",
            "type": "text",
            "group": "security",
            "value": _settings_list("CSRF_TRUSTED_ORIGINS"),
            "description": "Django settings.CSRF_TRUSTED_ORIGINS 当前生效值",
        },
    ]


def _with_fresh_readonly_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    result["file_fields"] = _file_fields()
    result["file_values"] = _file_values()
    result["file_save_errors"] = {}
    result["readonly_fields"] = _readonly_fields()
    return result


def _load_periodic_models():
    try:
        from django_celery_beat.models import CrontabSchedule, PeriodicTask
    except ModuleNotFoundError:
        return None, None
    return PeriodicTask, CrontabSchedule


def _parse_cleanup_schedule_time(schedule) -> str:
    hour = str(getattr(schedule, "hour", "")).strip()
    minute = str(getattr(schedule, "minute", "")).strip()
    if not hour.isdigit() or not minute.isdigit():
        raise ValueError("清理定时任务的执行时间不是固定的 HH:mm。")
    return _normalize_time(f"{int(hour):02d}:{int(minute):02d}", field={"label": "清理执行时间"})


def _cleanup_args_field_order() -> tuple[str, ...]:
    return (*CLEANUP_DAY_FIELD_KEYS, *CLEANUP_AUTO_EXPORT_FIELD_KEYS)


def _default_cleanup_values() -> dict[str, Any]:
    return {
        CLEANUP_SCHEDULE_TIME_KEY: CLEANUP_DEFAULT_SCHEDULE_TIME,
        **CLEANUP_DEFAULT_ARGS,
        **CLEANUP_AUTO_EXPORT_DEFAULTS,
    }


def build_default_cleanup_task_args() -> list[Any]:
    defaults = _default_cleanup_values()
    return [defaults[key] for key in _cleanup_args_field_order()]


def _load_cleanup_config() -> tuple[dict[str, Any], bool, str | None]:
    defaults = _default_cleanup_values()
    PeriodicTask, _CrontabSchedule = _load_periodic_models()
    if PeriodicTask is None:
        return defaults, False, "django_celery_beat 未安装，无法读取数据清理配置。"

    try:
        task = PeriodicTask.objects.filter(name=CLEANUP_TASK_NAME).first()
    except (OperationalError, ProgrammingError):
        return defaults, False, "django_celery_beat 表尚未迁移完成，无法读取数据清理配置。"
    if task is None:
        return defaults, False, f"未找到定时任务 {CLEANUP_TASK_NAME}。"
    if task.crontab is None:
        return defaults, False, f"定时任务 {CLEANUP_TASK_NAME} 未绑定 CrontabSchedule。"

    try:
        args = json.loads(task.args or "[]")
    except json.JSONDecodeError:
        return defaults, False, f"定时任务 {CLEANUP_TASK_NAME} 的 args 不是合法 JSON。"
    legacy_order = CLEANUP_DAY_FIELD_KEYS
    current_order = _cleanup_args_field_order()
    if not isinstance(args, list) or len(args) not in {len(legacy_order), len(current_order)}:
        return defaults, False, f"定时任务 {CLEANUP_TASK_NAME} 的 args 数量不正确。"

    values = defaults.copy()
    try:
        values[CLEANUP_SCHEDULE_TIME_KEY] = _parse_cleanup_schedule_time(task.crontab)
        order = legacy_order if len(args) == len(legacy_order) else current_order
        for key, raw_value in zip(order, args, strict=True):
            field = _field_map()[key]
            if field["type"] == "boolean":
                values[key] = _normalize_bool(raw_value, field=field)
            else:
                values[key] = _normalize_int(raw_value, field=field)
    except ValueError as exc:
        return defaults, False, str(exc)
    return values, True, None


def _save_cleanup_config_values(cleanup_values: Mapping[str, Any]) -> None:
    PeriodicTask, _CrontabSchedule = _load_periodic_models()
    if PeriodicTask is None:
        raise ValueError("django_celery_beat 未安装，无法保存数据清理配置。")

    try:
        task = PeriodicTask.objects.select_for_update().filter(name=CLEANUP_TASK_NAME).first()
    except (OperationalError, ProgrammingError) as exc:
        raise ValueError("django_celery_beat 表尚未迁移完成，无法保存数据清理配置。") from exc
    if task is None:
        raise ValueError(f"未找到定时任务 {CLEANUP_TASK_NAME}。")
    if task.crontab is None:
        raise ValueError(f"定时任务 {CLEANUP_TASK_NAME} 未绑定 CrontabSchedule。")

    schedule_time = str(cleanup_values[CLEANUP_SCHEDULE_TIME_KEY])
    hour, minute = schedule_time.split(":")
    schedule = task.crontab
    schedule.hour = str(int(hour))
    schedule.minute = str(int(minute))
    schedule.save(update_fields=["hour", "minute"])

    task.args = json.dumps([cleanup_values[key] for key in _cleanup_args_field_order()])
    task.save(update_fields=["args", "crontab"])
    PeriodicTask.objects.all().update(last_run_at=None)


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
    return f"修改BT系统设置（{detail}）"


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
            return _with_fresh_readonly_fields(cached)

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
    runtime_stored_values = {key: value for key, value in stored_values.items() if key in _runtime_field_keys()}
    values = validate_runtime_config_values(runtime_stored_values, fill_missing_alarm_delay=True)
    cleanup_values, cleanup_ready, cleanup_error = _load_cleanup_config()
    values.update(cleanup_values)
    payload = {
        "schema": _schema(),
        "file_fields": _file_fields(),
        "file_values": _file_values(),
        "file_save_errors": {},
        "readonly_fields": _readonly_fields(),
        "defaults": defaults,
        "values": values,
        "updated_at": record.updated_at.isoformat() if record and record.updated_at else None,
        "updated_by": record.updated_by.username if record and record.updated_by else None,
        "storage_ready": storage_ready,
        "cleanup_ready": cleanup_ready,
        "cleanup_error": cleanup_error,
    }
    cache.set(RUNTIME_CONFIG_CACHE_KEY, payload, timeout=None)
    return deepcopy(payload)


def get_runtime_config_values(*, force_refresh: bool = False) -> dict[str, Any]:
    return build_runtime_config_payload(force_refresh=force_refresh)["values"]


def save_runtime_config_values(
    *,
    values: Mapping[str, Any],
    user,
    file_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise ValueError("values 必须是对象。")
    current_payload = build_runtime_config_payload(force_refresh=True)
    if not current_payload.get("storage_ready", True):
        raise ValueError("运行时配置表尚未迁移完成，当前只能查看默认值，暂时无法保存。")
    if not current_payload.get("cleanup_ready", True):
        raise ValueError(current_payload.get("cleanup_error") or "数据清理任务配置缺失，暂时无法保存。")
    current_values = current_payload["values"]
    merged_values = deepcopy(current_values)
    merged_values.update(dict(values))
    validated = validate_runtime_config_values(merged_values)
    validated_file_values = _normalize_file_values(file_values)
    changes = _describe_runtime_config_changes(current_values, validated)
    runtime_values = {key: validated[key] for key in _runtime_field_keys()}
    cleanup_values = {key: validated[key] for key in _cleanup_field_keys()}
    RuntimeConfig = _load_model()
    file_save_errors: dict[str, str] = {}
    try:
        with transaction.atomic():
            record, _created = RuntimeConfig.objects.select_for_update().get_or_create(
                pk=RUNTIME_CONFIG_SINGLETON_PK,
                defaults={"values": runtime_values, "updated_by": user},
            )
            _save_cleanup_config_values(cleanup_values)
            file_save_errors = _save_file_values(validated_file_values)
            record.values = runtime_values
            record.updated_by = user
            record.save(update_fields=["values", "updated_by", "updated_at"])
            _log_runtime_config_update(user=user, changes=changes)
    except (OperationalError, ProgrammingError) as exc:
        raise ValueError("运行时配置表尚未迁移完成，当前只能查看默认值，暂时无法保存。") from exc

    payload = build_runtime_config_payload(force_refresh=True)
    payload["file_save_errors"] = file_save_errors
    return payload


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
