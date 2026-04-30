from celery import shared_task
from .cleanup_tasks import cleanup_switch_data, cleanup_analog_data, cleanup_alarm_data, cleanup_relay_action, cleanup_user_operation

@shared_task
def my_daily_task(
    switch_data_days,
    analog_data_days,
    alarm_data_days,
    relay_action_days,
    user_operation_days,
    switch_data_auto_export=True,
    analog_data_auto_export=True,
    alarm_data_auto_export=True,
    relay_action_auto_export=True,
    user_operation_auto_export=True,
):
    """
    This task runs daily to clean up old data from SwitchData, AnalogData, AlarmData, RelayAction, and UserOperation tables.
    Each type of data can have its own retention period in days.
    """
    
    jobs = [
        ("SwitchData", cleanup_switch_data, switch_data_days, switch_data_auto_export),
        ("AnalogData", cleanup_analog_data, analog_data_days, analog_data_auto_export),
        ("AlarmData", cleanup_alarm_data, alarm_data_days, alarm_data_auto_export),
        ("RelayAction", cleanup_relay_action, relay_action_days, relay_action_auto_export),
        ("UserOperation", cleanup_user_operation, user_operation_days, user_operation_auto_export),
    ]

    summary = {}
    for name, fn, days, auto_export in jobs:
        try:
            result = fn(days, auto_export)
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
