import json
from django.core.cache import cache
from django.conf import settings
from celery import shared_task
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from myapp.models import SwitchData, AnalogData, AlarmData, RelayAction, UserOperation

def cleanup_old_data(model, days, date_field='timestamp'):
    threshold_date = timezone.now() - timedelta(days=days)
    batch_size = 100  # 定义每批次删除的记录数量，防止一次删除过多造成程序卡顿
    total_deleted = 0  # 初始化删除的记录总数

    while True:  # 循环删除记录，直到没有符合条件的记录为止
        with transaction.atomic():
            records_to_delete = model.objects.filter(**{f"{date_field}__lt": threshold_date})[:batch_size]
            records_ids = list(records_to_delete.values_list('id', flat=True))
            deleted_count = len(records_ids)
            
            if deleted_count == 0:
                break
            
            model.objects.filter(id__in=records_ids).delete()
            total_deleted += deleted_count

    return f'Successfully deleted {total_deleted} old records from {model.__name__} in batches of {batch_size}'

@shared_task
def cleanup_switch_data(days):
    return cleanup_old_data(SwitchData, days, 'timestamp')

@shared_task
def cleanup_analog_data(days):
    return cleanup_old_data(AnalogData, days, 'timestamp')

@shared_task
def cleanup_alarm_data(days):
    return cleanup_old_data(AlarmData, days, 'timestamp')

@shared_task
def cleanup_relay_action(days):
    return cleanup_old_data(RelayAction, days, 'timestamp')

@shared_task
def cleanup_user_operation(days):
    return cleanup_old_data(UserOperation, days, 'timestamp')