import csv
import uuid
from datetime import timedelta
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from myapp.models import AlarmData, ChangeBitEvent, RawFrameLog, RelayAction, SwitchData, UserOperation

from ..cleanup_export_resources import CLEANUP_EXPORT_RESOURCE_MAP


EXPORT_BATCH_SIZE = 5000
DELETE_BATCH_SIZE = 5000
MAX_EXPORT_ROWS_PER_FILE = 1_000_000
SYSTEM_LABEL = "sy"
CLEANUP_EXPORT_TEST_DAYS = 99999


def _validate_days(model, days):
    if not isinstance(days, int):
        raise ValueError(f"Invalid retention days for {model.__name__}: {days!r}")
    if days < 0:
        raise ValueError(f"Retention days must be >= 0 for {model.__name__}, got {days}")


def _get_cleanup_export_dir():
    data_dir = str(getattr(settings, "DATA_DIR", "")).strip() or "/srv/bt_nms_data"
    export_dir = Path(data_dir) / "cleanup_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _build_export_filename(model_name, threshold_date, run_at, *, export_test=False):
    local_threshold = timezone.localtime(threshold_date)
    local_run_at = timezone.localtime(run_at)
    marker = "export_test_before" if export_test else "before"
    return (
        f"{SYSTEM_LABEL}_{model_name}_{marker}_{local_threshold:%Y-%m-%d}"
        f"_run_{local_run_at:%Y%m%d_%H%M%S}.csv"
    )


def _quote_name(name):
    return connection.ops.quote_name(name)


def _model_table_info(model, date_field):
    pk_field = model._meta.pk
    date_model_field = model._meta.get_field(date_field)
    return {
        "table": _quote_name(model._meta.db_table),
        "pk_column": _quote_name(pk_field.column),
        "date_column": _quote_name(date_model_field.column),
    }


def _create_snapshot_table(model, threshold_date, date_field):
    table_info = _model_table_info(model, date_field)
    temp_table = f"cleanup_snapshot_{uuid.uuid4().hex}"
    quoted_temp_table = _quote_name(temp_table)

    with connection.cursor() as cursor:
        id_type = "TEXT" if connection.vendor == "sqlite" else "uuid"
        create_sql = f"CREATE TEMP TABLE {quoted_temp_table} (id {id_type} PRIMARY KEY)"
        if connection.vendor != "sqlite":
            create_sql += " ON COMMIT PRESERVE ROWS"
        cursor.execute(create_sql)
        cursor.execute(
            f"""
            INSERT INTO {quoted_temp_table} (id)
            SELECT {table_info['pk_column']}
            FROM {table_info['table']}
            WHERE {table_info['date_column']} < %s
            """,
            [threshold_date],
        )
        candidate_count = cursor.rowcount
        if candidate_count < 0:
            cursor.execute(f"SELECT COUNT(*) FROM {quoted_temp_table}")
            candidate_count = cursor.fetchone()[0]

    return temp_table, candidate_count


def _drop_snapshot_table(temp_table):
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {_quote_name(temp_table)}")


def _fetch_snapshot_batch(model, temp_table, date_field, batch_size, last_sort=None):
    table_info = _model_table_info(model, date_field)
    quoted_temp_table = _quote_name(temp_table)
    where_clause = ""
    params = []
    if last_sort is not None:
        last_date, last_id = last_sort
        where_clause = (
            f"WHERE (m.{table_info['date_column']} > %s "
            f"OR (m.{table_info['date_column']} = %s AND m.{table_info['pk_column']} > %s))"
        )
        params.extend([last_date, last_date, last_id])
    params.append(batch_size)

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT m.{table_info['pk_column']}, m.{table_info['date_column']}
            FROM {quoted_temp_table} s
            INNER JOIN {table_info['table']} m ON m.{table_info['pk_column']} = s.id
            {where_clause}
            ORDER BY m.{table_info['date_column']} ASC, m.{table_info['pk_column']} ASC
            LIMIT %s
            """,
            params,
        )
        rows = cursor.fetchall()

    if not rows:
        return [], last_sort
    return [row[0] for row in rows], (rows[-1][1], rows[-1][0])


def _model_has_field(model, field_name):
    try:
        model._meta.get_field(field_name)
    except Exception:
        return False
    return True


def _ordered_snapshot_objects(model, ids):
    pk_field = model._meta.pk
    normalized_ids = [pk_field.to_python(pk) for pk in ids]
    queryset = model.objects.filter(pk__in=normalized_ids)
    if _model_has_field(model, "device"):
        queryset = queryset.select_related("device")
    objects_by_id = {pk_field.to_python(obj.pk): obj for obj in queryset}
    return [objects_by_id[pk] for pk in normalized_ids if pk in objects_by_id]


def export_cleanup_queryset_to_csv(*, queryset, resource_class, export_file):
    resource = resource_class()
    dataset = resource.export(queryset=queryset)
    export_file.write_text(dataset.export("csv"), encoding="utf-8-sig")


def _build_export_part_file(export_file, part_number, split_export):
    if not split_export:
        return export_file
    return export_file.with_name(f"{export_file.stem}_part{part_number:04d}{export_file.suffix}")


def _open_export_part(export_file, export_headers, part_number, split_export):
    final_file = _build_export_part_file(export_file, part_number, split_export)
    tmp_file = final_file.with_name(f"{final_file.name}.tmp")
    handle = tmp_file.open("w", encoding="utf-8-sig", newline="")
    writer = csv.writer(handle)
    writer.writerow(export_headers)
    return final_file, tmp_file, handle, writer


def export_cleanup_snapshot_to_csv(
    *,
    model,
    temp_table,
    date_field,
    resource_class,
    export_file,
    batch_size,
    candidate_count,
    max_rows_per_file,
):
    resource = resource_class()
    export_headers = resource.get_export_headers()
    exported_count = 0
    rows_in_current_file = 0
    part_number = 1
    last_sort = None
    split_export = candidate_count > max_rows_per_file
    export_files = []
    tmp_files = []
    handle = None
    writer = None

    try:
        final_file, tmp_file, handle, writer = _open_export_part(
            export_file,
            export_headers,
            part_number,
            split_export,
        )
        export_files.append(final_file)
        tmp_files.append(tmp_file)

        while True:
            ids, last_sort = _fetch_snapshot_batch(
                model,
                temp_table,
                date_field,
                batch_size,
                last_sort=last_sort,
            )
            if not ids:
                break
            for obj in _ordered_snapshot_objects(model, ids):
                if rows_in_current_file >= max_rows_per_file:
                    handle.close()
                    part_number += 1
                    rows_in_current_file = 0
                    final_file, tmp_file, handle, writer = _open_export_part(
                        export_file,
                        export_headers,
                        part_number,
                        split_export,
                    )
                    export_files.append(final_file)
                    tmp_files.append(tmp_file)
                writer.writerow(resource.export_resource(obj))
                exported_count += 1
                rows_in_current_file += 1

        handle.close()
        handle = None
        for tmp_file, final_file in zip(tmp_files, export_files, strict=True):
            tmp_file.replace(final_file)
    except Exception:
        if handle is not None:
            handle.close()
        for tmp_file in tmp_files:
            tmp_file.unlink(missing_ok=True)
        for final_file in export_files:
            final_file.unlink(missing_ok=True)
        raise

    return exported_count, [str(export_file) for export_file in export_files]


def _next_delete_batch_ids(temp_table, batch_size):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT id FROM {_quote_name(temp_table)} LIMIT %s",
            [batch_size],
        )
        return [row[0] for row in cursor.fetchall()]


def _remove_snapshot_ids(temp_table, snapshot_ids):
    if not snapshot_ids:
        return
    placeholders = ", ".join(["%s"] * len(snapshot_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {_quote_name(temp_table)} WHERE id IN ({placeholders})",
            snapshot_ids,
        )


def _delete_snapshot_ids(model, temp_table):
    total_deleted = 0

    while True:
        batch_ids = _next_delete_batch_ids(temp_table, DELETE_BATCH_SIZE)
        if not batch_ids:
            break
        with transaction.atomic():
            batch_qs = model.objects.filter(id__in=batch_ids)
            batch_count = batch_qs.count()
            if batch_count:
                batch_qs.delete()
                total_deleted += batch_count
            _remove_snapshot_ids(temp_table, batch_ids)

    return total_deleted


def cleanup_old_data(model, days, date_field="timestamp", *, auto_export=True):
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
        "export_enabled": bool(auto_export),
        "export_test": False,
        "export_path": "",
        "export_paths": [],
        "export_file_count": 0,
        "exported_count": 0,
        "export_batch_size": EXPORT_BATCH_SIZE,
        "export_max_rows_per_file": MAX_EXPORT_ROWS_PER_FILE,
        "delete_batch_size": DELETE_BATCH_SIZE,
        "deleted_count": 0,
        "error": "",
    }

    temp_table = None
    try:
        temp_table, candidate_count = _create_snapshot_table(model, threshold_date, date_field)
        result["candidate_count"] = candidate_count
        if not candidate_count:
            return result

        if auto_export:
            resource_class = CLEANUP_EXPORT_RESOURCE_MAP.get(model)
            if resource_class is None:
                result["status"] = "failed"
                result["error"] = f"No cleanup export resource configured for {model.__name__}"
                return result

            try:
                export_dir = _get_cleanup_export_dir()
                export_file = export_dir / _build_export_filename(model.__name__, threshold_date, run_at)
                exported_count, export_paths = export_cleanup_snapshot_to_csv(
                    model=model,
                    temp_table=temp_table,
                    date_field=date_field,
                    resource_class=resource_class,
                    export_file=export_file,
                    batch_size=EXPORT_BATCH_SIZE,
                    candidate_count=candidate_count,
                    max_rows_per_file=MAX_EXPORT_ROWS_PER_FILE,
                )
                result["exported_count"] = exported_count
                result["export_paths"] = export_paths
                result["export_file_count"] = len(export_paths)
                result["export_path"] = export_paths[0] if export_paths else ""
            except Exception as exc:
                result["status"] = "failed"
                result["error"] = f"{type(exc).__name__}: {exc}"
                return result

        result["deleted_count"] = _delete_snapshot_ids(model, temp_table)
        result["status"] = "deleted"
        return result
    finally:
        if temp_table is not None:
            _drop_snapshot_table(temp_table)


def export_cleanup_test(model, days, date_field="timestamp"):
    _validate_days(model, days)

    threshold_date = timezone.now() - timedelta(days=days)
    run_at = timezone.now()
    result = {
        "status": "exported",
        "model": model.__name__,
        "system": SYSTEM_LABEL,
        "days": days,
        "date_field": date_field,
        "threshold": threshold_date.isoformat(),
        "candidate_count": 0,
        "export_enabled": True,
        "export_test": True,
        "export_path": "",
        "export_paths": [],
        "export_file_count": 0,
        "exported_count": 0,
        "export_batch_size": EXPORT_BATCH_SIZE,
        "export_max_rows_per_file": MAX_EXPORT_ROWS_PER_FILE,
        "delete_batch_size": DELETE_BATCH_SIZE,
        "deleted_count": 0,
        "error": "",
    }

    resource_class = CLEANUP_EXPORT_RESOURCE_MAP.get(model)
    if resource_class is None:
        result["status"] = "failed"
        result["error"] = f"No cleanup export resource configured for {model.__name__}"
        return result

    temp_table = None
    try:
        temp_table, candidate_count = _create_snapshot_table(model, threshold_date, date_field)
        result["candidate_count"] = candidate_count

        try:
            export_dir = _get_cleanup_export_dir()
            export_file = export_dir / _build_export_filename(model.__name__, threshold_date, run_at, export_test=True)
            exported_count, export_paths = export_cleanup_snapshot_to_csv(
                model=model,
                temp_table=temp_table,
                date_field=date_field,
                resource_class=resource_class,
                export_file=export_file,
                batch_size=EXPORT_BATCH_SIZE,
                candidate_count=candidate_count,
                max_rows_per_file=MAX_EXPORT_ROWS_PER_FILE,
            )
            result["exported_count"] = exported_count
            result["export_paths"] = export_paths
            result["export_file_count"] = len(export_paths)
            result["export_path"] = export_paths[0] if export_paths else ""
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if temp_table is not None:
            _drop_snapshot_table(temp_table)
    return result


def run_cleanup_export_test():
    return {
        "RawFrameLog": export_cleanup_test(RawFrameLog, CLEANUP_EXPORT_TEST_DAYS, "timestamp"),
        "SwitchData": export_cleanup_test(SwitchData, CLEANUP_EXPORT_TEST_DAYS, "timestamp"),
        "ChangeBitEvent": export_cleanup_test(ChangeBitEvent, CLEANUP_EXPORT_TEST_DAYS, "timestamp"),
        "AlarmData": export_cleanup_test(AlarmData, CLEANUP_EXPORT_TEST_DAYS, "timestamp_start"),
        "RelayAction": export_cleanup_test(RelayAction, CLEANUP_EXPORT_TEST_DAYS, "timestamp"),
        "UserOperation": export_cleanup_test(UserOperation, CLEANUP_EXPORT_TEST_DAYS, "timestamp"),
    }


@shared_task
def cleanup_raw_frame_log(days, auto_export=True):
    return cleanup_old_data(RawFrameLog, days, "timestamp", auto_export=auto_export)


@shared_task
def cleanup_switch_data(days, auto_export=True):
    return cleanup_old_data(SwitchData, days, "timestamp", auto_export=auto_export)


@shared_task
def cleanup_change_bit_event(days, auto_export=True):
    return cleanup_old_data(ChangeBitEvent, days, "timestamp", auto_export=auto_export)


@shared_task
def cleanup_alarm_data(days, auto_export=True):
    return cleanup_old_data(AlarmData, days, "timestamp_start", auto_export=auto_export)


@shared_task
def cleanup_relay_action(days, auto_export=True):
    return cleanup_old_data(RelayAction, days, "timestamp", auto_export=auto_export)


@shared_task
def cleanup_user_operation(days, auto_export=True):
    return cleanup_old_data(UserOperation, days, "timestamp", auto_export=auto_export)
