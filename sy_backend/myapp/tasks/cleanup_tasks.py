# myapp/tasks/cleanup_tasks.py

from datetime import timedelta
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from myapp.models import AlarmData, ChangeBitEvent, RawFrameLog, RelayAction, SwitchData, UserOperation

from ..cleanup_export_resources import CLEANUP_EXPORT_RESOURCE_MAP


DELETE_BATCH_SIZE = 100
SYSTEM_LABEL = "sy"


def _validate_days(model, days):
    if not isinstance(days, int):
        raise ValueError(f"Invalid retention days for {model.__name__}: {days!r}")
    if days < 0:
        raise ValueError(f"Retention days must be >= 0 for {model.__name__}, got {days}")


def _get_cleanup_export_dir():
    configured_path = getattr(settings, "CLEANUP_EXPORT_DIR", "")
    if not configured_path:
        raise ValueError("CLEANUP_EXPORT_DIR is not configured.")

    export_dir = Path(configured_path)
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _build_export_filename(model_name, threshold_date, run_at):
    local_threshold = timezone.localtime(threshold_date)
    local_run_at = timezone.localtime(run_at)
    return (
        f"{SYSTEM_LABEL}_{model_name}_before_{local_threshold:%Y-%m-%d}"
        f"_run_{local_run_at:%Y%m%d_%H%M%S}.csv"
    )


def _snapshot_cleanup_ids(model, threshold_date, date_field):
    queryset = model.objects.filter(**{f"{date_field}__lt": threshold_date}).order_by(date_field, "id")
    return list(queryset.values_list("id", flat=True))


def export_cleanup_queryset_to_csv(*, queryset, resource_class, export_file):
    resource = resource_class()
    dataset = resource.export(queryset=queryset)
    export_file.write_text(dataset.export("csv"), encoding="utf-8-sig")


def _delete_snapshot_ids(model, snapshot_ids):
    total_deleted = 0

    for start in range(0, len(snapshot_ids), DELETE_BATCH_SIZE):
        batch_ids = snapshot_ids[start:start + DELETE_BATCH_SIZE]
        with transaction.atomic():
            batch_qs = model.objects.filter(id__in=batch_ids)
            batch_count = batch_qs.count()
            if batch_count == 0:
                continue
            batch_qs.delete()
            total_deleted += batch_count

    return total_deleted


def cleanup_old_data(model, days, date_field="timestamp"):
    _validate_days(model, days)

    threshold_date = timezone.now() - timedelta(days=days)
    run_at = timezone.now()
    result = {
        "status": "skipped",
        "model": model.__name__,
        "system": SYSTEM_LABEL,
        "days": days,
        "date_field": date_field,
        "threshold": threshold_date.isoformat(),
        "candidate_count": 0,
        "export_path": "",
        "deleted_count": 0,
        "error": "",
    }

    snapshot_ids = _snapshot_cleanup_ids(model, threshold_date, date_field)
    result["candidate_count"] = len(snapshot_ids)
    if not snapshot_ids:
        return result

    resource_class = CLEANUP_EXPORT_RESOURCE_MAP.get(model)
    if resource_class is None:
        result["status"] = "failed"
        result["error"] = f"No cleanup export resource configured for {model.__name__}"
        return result

    try:
        export_dir = _get_cleanup_export_dir()
        export_file = export_dir / _build_export_filename(model.__name__, threshold_date, run_at)
        export_queryset = model.objects.filter(id__in=snapshot_ids).order_by(date_field, "id")
        export_cleanup_queryset_to_csv(
            queryset=export_queryset,
            resource_class=resource_class,
            export_file=export_file,
        )
        result["export_path"] = str(export_file)
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["deleted_count"] = _delete_snapshot_ids(model, snapshot_ids)
    result["status"] = "deleted"
    return result


@shared_task
def cleanup_raw_frame_log(days):
    return cleanup_old_data(RawFrameLog, days, "timestamp")


@shared_task
def cleanup_switch_data(days):
    return cleanup_old_data(SwitchData, days, "timestamp")


@shared_task
def cleanup_change_bit_event(days):
    return cleanup_old_data(ChangeBitEvent, days, "timestamp")


@shared_task
def cleanup_alarm_data(days):
    return cleanup_old_data(AlarmData, days, "timestamp_start")


@shared_task
def cleanup_relay_action(days):
    return cleanup_old_data(RelayAction, days, "timestamp")


@shared_task
def cleanup_user_operation(days):
    return cleanup_old_data(UserOperation, days, "timestamp")
