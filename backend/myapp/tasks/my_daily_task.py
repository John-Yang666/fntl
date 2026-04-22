from celery import shared_task
from .cleanup_tasks import cleanup_switch_data, cleanup_analog_data, cleanup_alarm_data, cleanup_relay_action, cleanup_user_operation

@shared_task
def my_daily_task(
    switch_data_days,
    analog_data_days,
    alarm_data_days,
    relay_action_days,
    user_operation_days
):
    """
    This task runs daily to clean up old data from SwitchData, AnalogData, AlarmData, RelayAction, and UserOperation tables.
    Each type of data can have its own retention period in days.
    """
    
    jobs = [
        ("SwitchData", cleanup_switch_data, switch_data_days),
        ("AnalogData", cleanup_analog_data, analog_data_days),
        ("AlarmData", cleanup_alarm_data, alarm_data_days),
        ("RelayAction", cleanup_relay_action, relay_action_days),
        ("UserOperation", cleanup_user_operation, user_operation_days),
    ]

    summary = {}
    for name, fn, days in jobs:
        try:
            result = fn(days)
            print(f"Cleanup {name} result: {result}")
            summary[name] = result
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            print(msg)
            summary[name] = {
                "status": "failed",
                "model": name,
                "error": msg,
                "candidate_count": 0,
                "deleted_count": 0,
                "export_path": "",
            }

    print(f"Cleanup summary: {summary}")
    return summary
