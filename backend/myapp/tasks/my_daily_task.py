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
    
    # Clean up old SwitchData
    result_switch_data = cleanup_switch_data(switch_data_days)
    print(f"Cleanup SwitchData result: {result_switch_data}")

    # Clean up old AnalogData
    result_analog_data = cleanup_analog_data(analog_data_days)
    print(f"Cleanup AnalogData result: {result_analog_data}")

    # Clean up old AlarmData
    result_alarm_data = cleanup_alarm_data(alarm_data_days)
    print(f"Cleanup AlarmData result: {result_alarm_data}")

    # Clean up old RelayAction
    result_relay_action = cleanup_relay_action(relay_action_days)
    print(f"Cleanup RelayAction result: {result_relay_action}")

    # Clean up old UserOperation
    result_user_operation = cleanup_user_operation(user_operation_days)
    print(f"Cleanup UserOperation result: {result_user_operation}")

    return "my daily task completed."