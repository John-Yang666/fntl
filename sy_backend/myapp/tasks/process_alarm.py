# process_alarm.py
from celery import shared_task
from django.utils import timezone
from myapp.models import AlarmActive, AlarmData

@shared_task
def handle_alarm_async(device_id, alarm_code):
    """
    异步处理告警保存和转移逻辑
    """
    # 1. 创建或更新当前告警
    alarm, created = AlarmActive.objects.get_or_create(
        device_id=device_id, alarm_code=alarm_code,
        defaults={'timestamp_start': timezone.now()}
    )

    # 如果告警已存在，更新其开始时间
    if not created:
        alarm.timestamp_start = timezone.now()
        alarm.save()

    # 2. 如果告警已结束，转移到历史告警表
    if alarm.is_confirmed:
        alarm_end_time = timezone.now()
        # 将当前告警转移到历史告警表
        AlarmData.objects.create(
            device=alarm.device,
            alarm_code=alarm.alarm_code,
            timestamp_start=alarm.timestamp_start,
            timestamp_end=alarm_end_time,
            is_confirmed=True
        )
        # 删除当前告警记录
        alarm.delete()

    return f"告警 {alarm_code} 处理成功"
