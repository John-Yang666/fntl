# myapp/tasks/cleanup_tasks.py

from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from myapp.models import (
    RawFrameLog,
    SwitchData,
    ChangeBitEvent,
    AlarmData,
    RelayAction,
    UserOperation,
)


def cleanup_old_data(model, days, date_field='timestamp'):
    """
    通用按天清理函数：
    - model: 要清理的模型
    - days: 保留天数（删除 days 天之前的数据）
    - date_field: 时间字段名称，默认 'timestamp'
    """
    if not isinstance(days, int):
        raise ValueError(f"Invalid retention days for {model.__name__}: {days!r}")
    if days < 0:
        raise ValueError(f"Retention days must be >= 0 for {model.__name__}, got {days}")

    threshold_date = timezone.now() - timedelta(days=days)
    batch_size = 100  # 每批删除数量，防止一次性删除太多卡顿
    total_deleted = 0

    while True:
        with transaction.atomic():
            # 先查询一批满足条件的 id，再按 id 删除
            records_to_delete = model.objects.filter(
                **{f"{date_field}__lt": threshold_date}
            )[:batch_size]

            records_ids = list(records_to_delete.values_list('id', flat=True))
            deleted_count = len(records_ids)

            if deleted_count == 0:
                break

            model.objects.filter(id__in=records_ids).delete()
            total_deleted += deleted_count

    return (
        f"Successfully deleted {total_deleted} old records from "
        f"{model.__name__} in batches of {batch_size}"
    )


# ========= 下面是对应各个模型的 Celery Task =========

@shared_task
def cleanup_raw_frame_log(days):
    """
    清理 RawFrameLog 表数据。
    默认假设 RawFrameLog 有 timestamp 字段。
    """
    return cleanup_old_data(RawFrameLog, days, 'timestamp')


@shared_task
def cleanup_switch_data(days):
    """
    清理 SwitchData 表数据。
    """
    return cleanup_old_data(SwitchData, days, 'timestamp')


@shared_task
def cleanup_change_bit_event(days):
    """
    清理 ChangeBitEvent 表数据。
    """
    return cleanup_old_data(ChangeBitEvent, days, 'timestamp')


@shared_task
def cleanup_alarm_data(days):
    """
    清理 AlarmData 表数据。
    """
    return cleanup_old_data(AlarmData, days, 'timestamp_start')


@shared_task
def cleanup_relay_action(days):
    """
    清理 RelayAction 表数据。
    """
    return cleanup_old_data(RelayAction, days, 'timestamp')


@shared_task
def cleanup_user_operation(days):
    """
    清理 UserOperation 表数据。
    """
    return cleanup_old_data(UserOperation, days, 'timestamp')
