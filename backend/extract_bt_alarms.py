from __future__ import annotations

from datetime import datetime

from consts import BT_ALARM_CODES, TESTDATA_ALARM_CODES


def get_switch_bit_value(switch_status: bytes, byte_index: int, bit_index: int) -> int:
    idx = byte_index - 4
    if idx < 0 or idx >= len(switch_status):
        return 0
    byte_value = switch_status[idx]
    return (byte_value >> bit_index) & 1


def _compute_alarm_bit(alarm_code: int, switch_status: bytes) -> int:
    if alarm_code == 70:
        bit_value_0_self = get_switch_bit_value(switch_status, 7, 0)
        bit_value_0_neighbor = get_switch_bit_value(switch_status, 9, 0)
        return 0 if bit_value_0_self == bit_value_0_neighbor else 1

    if alarm_code == 72:
        bit_value_2_self = get_switch_bit_value(switch_status, 7, 2)
        bit_value_3_self = get_switch_bit_value(switch_status, 7, 3)
        bit_value_2_neighbor = get_switch_bit_value(switch_status, 9, 2)
        bit_value_3_neighbor = get_switch_bit_value(switch_status, 9, 3)
        if bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0:
            return 0
        if (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):
            return 0
        return 0 if (bit_value_2_self == bit_value_2_neighbor and bit_value_3_self == bit_value_3_neighbor) else 1

    if alarm_code == 110:
        bit_value_0_self = get_switch_bit_value(switch_status, 11, 0)
        bit_value_0_neighbor = get_switch_bit_value(switch_status, 13, 0)
        return 0 if bit_value_0_self == bit_value_0_neighbor else 1

    if alarm_code == 112:
        bit_value_2_self = get_switch_bit_value(switch_status, 11, 2)
        bit_value_3_self = get_switch_bit_value(switch_status, 11, 3)
        bit_value_2_neighbor = get_switch_bit_value(switch_status, 13, 2)
        bit_value_3_neighbor = get_switch_bit_value(switch_status, 13, 3)
        if bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0:
            return 0
        if (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):
            return 0
        return 0 if (bit_value_2_self == bit_value_2_neighbor and bit_value_3_self == bit_value_3_neighbor) else 1

    if alarm_code in {190, 280, 370, 460}:
        bit_value_0 = get_switch_bit_value(switch_status, alarm_code // 10, 0)
        bit_value_3 = get_switch_bit_value(switch_status, alarm_code // 10, 3)
        return bit_value_0 & bit_value_3

    return get_switch_bit_value(switch_status, alarm_code // 10, alarm_code % 10)


def build_alarms_state(
    *,
    device_id: int,
    switch_status: bytes,
    previous_alarms: dict,
    now_time: datetime,
    now_monotonic: float,
    device_alarm_filters: dict[int, set[int]],
) -> dict:
    alarm_filters = device_alarm_filters.get(device_id, set())
    alarms_state = {}

    for alarm_code in BT_ALARM_CODES:
        if alarm_code in alarm_filters:
            alarms_state[alarm_code] = {"bit_value": 0}
            continue

        bit_value = _compute_alarm_bit(alarm_code, switch_status)
        if bit_value == 1:
            prev_state = previous_alarms.get(alarm_code, {}) if isinstance(previous_alarms, dict) else {}
            start = prev_state.get("starttime", now_time)
            start_monotonic = prev_state.get("start_monotonic", now_monotonic)
            alarms_state[alarm_code] = {
                "bit_value": 1,
                "starttime": start,
                "start_monotonic": start_monotonic,
            }
        else:
            alarms_state[alarm_code] = {"bit_value": 0}

    return alarms_state


def build_testdata_alarms_state(
    *,
    device_id: int,
    switch_status: bytes,
    previous_alarms: dict,
    now_time: datetime,
    now_monotonic: float,
    device_alarm_filters: dict[int, set[int]],
) -> dict:
    alarm_filters = device_alarm_filters.get(device_id, set())
    alarms_state = {}
    current_active = _testdata_active_alarm_codes(switch_status)

    for alarm_code in TESTDATA_ALARM_CODES:
        if alarm_code in alarm_filters:
            alarms_state[alarm_code] = {"bit_value": 0}
            continue
        if alarm_code in current_active:
            prev_state = previous_alarms.get(alarm_code, {}) if isinstance(previous_alarms, dict) else {}
            alarms_state[alarm_code] = {
                "bit_value": 1,
                "starttime": prev_state.get("starttime", now_time),
                "start_monotonic": prev_state.get("start_monotonic", now_monotonic),
            }
        else:
            alarms_state[alarm_code] = {"bit_value": 0}
    return alarms_state


def _testdata_active_alarm_codes(raw_data: bytes) -> set[int]:
    active: set[int] = set()
    if len(raw_data) < 40:
        return active

    power_byte = raw_data[2]
    for index in range(8):
        if ((power_byte >> index) & 0x01) == 1:
            active.add(8000 + index)

    external_byte = raw_data[3]
    for index in range(2):
        if ((external_byte >> index) & 0x01) == 1:
            active.add(8010 + index)

    for cpu_index in range(4):
        base = cpu_index * 8
        fault_bytes = raw_data[base + 7 : base + 11]
        for byte_index, value in enumerate(fault_bytes):
            for bit in range(8):
                if ((value >> bit) & 0x01) == 1:
                    active.add(8200 + cpu_index * 100 + _normalize_testdata_cpu_fault(byte_index * 8 + bit))

        txb_a = raw_data[base + 12]
        txb_b = raw_data[base + 13]
        txb_bits = (
            (txb_a >> 0) & 0x01,
            (txb_a >> 7) & 0x01,
            (txb_b >> 0) & 0x01,
            (txb_b >> 7) & 0x01,
        )
        for txb_index, bit_value in enumerate(txb_bits):
            if bit_value == 1:
                active.add(8400 + cpu_index * 10 + txb_index)

        board_status = raw_data[base + 11]
        board_low = board_status & 0x0F
        if board_low not in (0x0A, 0x05):
            active.add(8500 + cpu_index)
        if ((board_status >> 7) & 0x01) == 1:
            active.add(8510 + cpu_index)
    return active


def _normalize_testdata_cpu_fault(code: int) -> int:
    if code in (10, 11):
        return 40
    if code in (12, 13):
        return 41
    return code
