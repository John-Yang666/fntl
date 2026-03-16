from .cleanup_tasks import *
from .my_daily_task import my_daily_task
from .sy_ingest_tasks import _save_a1_frame_sync, _save_a2_change_sync  # ← 新增这一行20251119
from .process_alarm import handle_alarm_async  # ← 新增这一行20251124
from celery import shared_task
