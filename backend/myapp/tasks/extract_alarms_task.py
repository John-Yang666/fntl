# tasks/extract_alarms_task.py
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache
from .process_tasks_helpers import get_switch_bit_value
from django.conf import settings
from myapp.models import Device

ALARM_CODES = settings.ALARM_CODES

@shared_task
def extract_alarms(device_id, switch_status):
    current_time = timezone.now()
    if isinstance(switch_status, str):
        switch_status = bytes(switch_status, 'utf-8')

    previous_alarms = cache.get(f'device_{device_id}_alarms', {})
    alarms_of_this_device = {}

    # Fetch the device and its alarm filters
    try:
        device = Device.objects.get(device_id=device_id)
        alarm_filters = set(device.alarm_filters)
    except Device.DoesNotExist:
        alarm_filters = set()

    for alarm_code in ALARM_CODES:
        if alarm_code in alarm_filters:
            continue  # Skip filtered alarms

        if alarm_code == 70:
            byte_index = 7
            bit_value_0_self = get_switch_bit_value(switch_status, byte_index, 0)
            byte_index = 9
            bit_value_0_neighbor = get_switch_bit_value(switch_status, byte_index, 0)
            bit_value = 0 if (bit_value_0_self == bit_value_0_neighbor) else 1
        elif alarm_code == 72:
            byte_index = 7
            bit_value_2_self = get_switch_bit_value(switch_status, byte_index, 2)
            bit_value_3_self = get_switch_bit_value(switch_status, byte_index, 3)
            byte_index = 9
            bit_value_2_neighbor = get_switch_bit_value(switch_status, byte_index, 2)
            bit_value_3_neighbor = get_switch_bit_value(switch_status, byte_index, 3)
            if (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0):#邻站切换模式为无效
                bit_value = 0
            elif (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):#本站或邻站切换模式为自动
                bit_value = 0
            else:
                bit_value = 0 if (bit_value_2_self == bit_value_2_neighbor) and (bit_value_3_self == bit_value_3_neighbor) else 1#本站与邻站切换模式不一致则为1
        elif alarm_code == 110:
            byte_index = 11
            bit_value_0_self = get_switch_bit_value(switch_status, byte_index, 0)
            byte_index = 13
            bit_value_0_neighbor = get_switch_bit_value(switch_status, byte_index, 0)
            bit_value = 0 if (bit_value_0_self == bit_value_0_neighbor) else 1
        elif alarm_code == 112:
            byte_index = 11
            bit_value_2_self = get_switch_bit_value(switch_status, byte_index, 2)
            bit_value_3_self = get_switch_bit_value(switch_status, byte_index, 3)
            byte_index = 13
            bit_value_2_neighbor = get_switch_bit_value(switch_status, byte_index, 2)
            bit_value_3_neighbor = get_switch_bit_value(switch_status, byte_index, 3)
            if (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0):
                bit_value = 0
            elif (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):
                bit_value = 0
            else:
                bit_value = 0 if (bit_value_2_self == bit_value_2_neighbor) and (bit_value_3_self == bit_value_3_neighbor) else 1
        elif alarm_code in {190, 280, 370, 460}:
            byte_index = alarm_code // 10
            bit_value_0 = get_switch_bit_value(switch_status, byte_index, 0)
            bit_value_3 = get_switch_bit_value(switch_status, byte_index, 3)
            bit_value = bit_value_0 & bit_value_3
        else:
            byte_index = alarm_code // 10
            bit_index = alarm_code % 10
            bit_value = get_switch_bit_value(switch_status, byte_index, bit_index)

        if bit_value == 1:
            alarms_of_this_device[alarm_code] = {
                'bit_value': bit_value,
                'starttime': current_time if previous_alarms.get(alarm_code, {}).get('bit_value') != 1 else previous_alarms[alarm_code]['starttime']
            }

    cache.set(f'device_{device_id}_alarms', alarms_of_this_device, timeout=None)