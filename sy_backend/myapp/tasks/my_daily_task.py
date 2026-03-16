# myapp/tasks/my_daily_task.py

from celery import shared_task

from .cleanup_tasks import (
    cleanup_raw_frame_log,
    cleanup_switch_data,
    cleanup_change_bit_event,
    cleanup_alarm_data,
    cleanup_relay_action,
    cleanup_user_operation,
)


@shared_task
def my_daily_task(
    raw_frame_log_days,
    switch_data_days,
    change_bit_event_days,
    alarm_data_days,
    relay_action_days,
    user_operation_days,
):
    """
    每日定时清理任务：

    目前清理的表：
    - RawFrameLog
    - SwitchData
    - ChangeBitEvent
    - AlarmData
    - RelayAction
    - UserOperation

    * 每个表可以单独配置保留天数（*_days 参数）。
    """

    cleanup_jobs = [
        ("RawFrameLog", cleanup_raw_frame_log, raw_frame_log_days),
        ("SwitchData", cleanup_switch_data, switch_data_days),
        ("ChangeBitEvent", cleanup_change_bit_event, change_bit_event_days),
        ("AlarmData", cleanup_alarm_data, alarm_data_days),
        ("RelayAction", cleanup_relay_action, relay_action_days),
        ("UserOperation", cleanup_user_operation, user_operation_days),
    ]

    summary = {"success": {}, "failed": {}}

    for model_name, task_func, days in cleanup_jobs:
        try:
            result = task_func(days)
            print(f"Cleanup {model_name} result: {result}")
            summary["success"][model_name] = result
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            print(f"Cleanup {model_name} failed: {error_msg}")
            summary["failed"][model_name] = error_msg

    print(f"Cleanup summary: {summary}")
    return "my daily task completed."
