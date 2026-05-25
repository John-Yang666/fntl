import csv
import json
from io import StringIO

import tablib
from django.db import transaction

from .models import Depot, Device, Line
from .ops_permissions import ensure_depot_allowed
from .ops_serializers import normalize_alarm_filters

EXPORT_HEADERS = [
    "设备ID",
    "设备名称",
    "车间",
    "线路",
    "IP地址",
    "X坐标",
    "Y坐标",
    "一方向邻站ID",
    "一方向邻站方向",
    "二方向邻站ID",
    "二方向邻站方向",
    "一方向启用",
    "二方向启用",
    "备注",
    "过滤告警码",
]


def _bool_to_text(value: bool) -> str:
    return "是" if value else "否"


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "是", "启用"}


def _parse_int(value, default=0):
    if value in (None, ""):
        return default
    return int(float(value))


def _parse_float(value, default=0.0):
    if value in (None, ""):
        return default
    return float(value)


def _parse_alarm_filters(value):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return normalize_alarm_filters(value)

    raw = str(value or "").strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        try:
            return normalize_alarm_filters(json.loads(raw))
        except json.JSONDecodeError:
            raw = raw[1:-1]

    filters = []
    for item in raw.replace(",", ";").replace("，", ";").split(";"):
        item = item.strip()
        if not item:
            continue
        try:
            filters.append(int(item))
        except ValueError:
            continue
    return filters


def export_devices_csv(queryset) -> bytes:
    output = StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(EXPORT_HEADERS)
    for device in queryset:
        writer.writerow(
            [
                device.device_id,
                device.name,
                device.depot_name,
                device.line_name,
                device.ip_address,
                device.x_coordinate,
                device.y_coordinate,
                device.direction1_neighbor_id or "",
                device.direction1_neighbor_direction or "",
                device.direction2_neighbor_id or "",
                device.direction2_neighbor_direction or "",
                _bool_to_text(device.direction1_enabled),
                _bool_to_text(device.direction2_enabled),
                device.remark or "",
                ";".join(str(item) for item in normalize_alarm_filters(device.alarm_filters)),
            ]
        )
    return output.getvalue().encode("utf-8")


def _normalized_row(raw_row):
    return {
        "device_id": _parse_int(raw_row.get("设备ID")),
        "name": str(raw_row.get("设备名称") or "").strip(),
        "depot": str(raw_row.get("车间") or "").strip(),
        "line": str(raw_row.get("线路") or "").strip(),
        "ip_address": str(raw_row.get("IP地址") or "").strip(),
        "x_coordinate": _parse_float(raw_row.get("X坐标")),
        "y_coordinate": _parse_float(raw_row.get("Y坐标")),
        "direction1_neighbor_id": _parse_int(raw_row.get("一方向邻站ID")),
        "direction1_neighbor_direction": _parse_int(raw_row.get("一方向邻站方向"), 2),
        "direction2_neighbor_id": _parse_int(raw_row.get("二方向邻站ID")),
        "direction2_neighbor_direction": _parse_int(raw_row.get("二方向邻站方向"), 1),
        "direction1_enabled": _parse_bool(raw_row.get("一方向启用")),
        "direction2_enabled": _parse_bool(raw_row.get("二方向启用")),
        "remark": str(raw_row.get("备注") or ""),
        "alarm_filters": _parse_alarm_filters(raw_row.get("过滤告警码")),
    }


def _validate_import_row(user, row, row_number):
    errors = []
    try:
        depot = Depot.objects.get(name=row["depot"])
        ensure_depot_allowed(user, depot)
    except Exception:
        errors.append({"row": row_number, "field": "depot", "message": "车间不存在或无权管理该车间"})
        depot = None
    if row["line"] and not Line.objects.filter(name=row["line"]).exists():
        errors.append({"row": row_number, "field": "line", "message": "线路不存在"})
    if not row["device_id"]:
        errors.append({"row": row_number, "field": "device_id", "message": "设备ID不能为空"})
    if not row["ip_address"]:
        errors.append({"row": row_number, "field": "ip_address", "message": "IP地址不能为空"})
    if depot is not None:
        existing_ip = Device.objects.filter(ip_address=row["ip_address"]).exclude(device_id=row["device_id"])
        if existing_ip.exists():
            errors.append({"row": row_number, "field": "ip_address", "message": "IP地址已存在"})
    for field in ("direction1_neighbor_id", "direction2_neighbor_id"):
        neighbor_id = row.get(field)
        if neighbor_id and not Device.objects.filter(device_id=neighbor_id).exists():
            errors.append({"row": row_number, "field": field, "message": "邻站ID不存在"})
    return errors


def preview_device_import(user, uploaded_file):
    content = uploaded_file.read()
    filename = getattr(uploaded_file, "name", "").lower()
    if filename.endswith(".xlsx"):
        dataset = tablib.Dataset().load(content, format="xlsx")
        reader = [dict(zip(dataset.headers, row)) for row in dataset]
    else:
        raw = content.decode("utf-8-sig")
        reader = csv.DictReader(StringIO(raw))
    rows = []
    errors = []
    create_count = 0
    update_count = 0
    for row_number, raw_row in enumerate(reader, start=2):
        row = _normalized_row(raw_row)
        row_errors = _validate_import_row(user, row, row_number)
        if row_errors:
            errors.extend(row_errors)
        else:
            rows.append(row)
            if Device.objects.filter(device_id=row["device_id"]).exists():
                update_count += 1
            else:
                create_count += 1
    return {
        "summary": {"create": create_count, "update": update_count, "error": len(errors)},
        "rows": rows,
        "errors": errors,
    }


@transaction.atomic
def commit_device_import(user, rows):
    created = 0
    updated = 0
    for row in rows:
        depot = Depot.objects.get(name=row["depot"])
        ensure_depot_allowed(user, depot)
        line = Line.objects.filter(name=row.get("line")).first() if row.get("line") else None
        defaults = {
            "name": row["name"],
            "depot": depot,
            "line": line,
            "ip_address": row["ip_address"],
            "x_coordinate": row["x_coordinate"],
            "y_coordinate": row["y_coordinate"],
            "direction1_neighbor_id": row["direction1_neighbor_id"],
            "direction1_neighbor_direction": row["direction1_neighbor_direction"],
            "direction2_neighbor_id": row["direction2_neighbor_id"],
            "direction2_neighbor_direction": row["direction2_neighbor_direction"],
            "direction1_enabled": row["direction1_enabled"],
            "direction2_enabled": row["direction2_enabled"],
            "remark": row["remark"],
            "alarm_filters": row["alarm_filters"],
        }
        _, was_created = Device.objects.update_or_create(device_id=row["device_id"], defaults=defaults)
        if was_created:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated}
