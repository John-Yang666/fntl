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
    raw_frame_log_auto_export=True,
    switch_data_auto_export=True,
    change_bit_event_auto_export=True,
    alarm_data_auto_export=True,
    relay_action_auto_export=True,
    user_operation_auto_export=True,
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
        ("RawFrameLog", cleanup_raw_frame_log, raw_frame_log_days, raw_frame_log_auto_export),
        ("SwitchData", cleanup_switch_data, switch_data_days, switch_data_auto_export),
        ("ChangeBitEvent", cleanup_change_bit_event, change_bit_event_days, change_bit_event_auto_export),
        ("AlarmData", cleanup_alarm_data, alarm_data_days, alarm_data_auto_export),
        ("RelayAction", cleanup_relay_action, relay_action_days, relay_action_auto_export),
        ("UserOperation", cleanup_user_operation, user_operation_days, user_operation_auto_export),
    ]

    summary = {}

    for model_name, task_func, days, auto_export in cleanup_jobs:
        try:
            result = task_func(days, auto_export)
            print(f"Cleanup {model_name} result: {result}")
            summary[model_name] = result
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            print(f"Cleanup {model_name} failed: {error_msg}")
            summary[model_name] = {
                "status": "failed",
                "model": model_name,
                "error": error_msg,
                "candidate_count": 0,
                "deleted_count": 0,
                "export_path": "",
            }

    print(f"Cleanup summary: {summary}")
    return summary
