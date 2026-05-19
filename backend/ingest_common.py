from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
import json
import time

import redis

from myapp.models import Device
from consts import BT_ALARM_CODES


RELAY_MAPPING = (
    ("一方向本站QHJ", 7, 0),
    ("一方向邻站QHJ", 9, 0),
    ("二方向本站QHJ", 11, 0),
    ("二方向邻站QHJ", 13, 0),
    ("一方向本站ZDJ(A系)", 14, 0),
    ("一方向本站FDJ(A系)", 14, 2),
    ("一方向本站ZXJ(A系)", 14, 4),
    ("一方向本站FXJ(A系)", 14, 6),
    ("一方向邻站ZDJ(A系)", 22, 0),
    ("一方向邻站FDJ(A系)", 22, 2),
    ("一方向邻站ZXJ(A系)", 22, 4),
    ("一方向邻站FXJ(A系)", 22, 6),
    ("二方向本站ZDJ(A系)", 32, 0),
    ("二方向本站FDJ(A系)", 32, 2),
    ("二方向本站ZXJ(A系)", 32, 4),
    ("二方向本站FXJ(A系)", 32, 6),
    ("二方向邻站ZDJ(A系)", 40, 0),
    ("二方向邻站FDJ(A系)", 40, 2),
    ("二方向邻站ZXJ(A系)", 40, 4),
    ("二方向邻站FXJ(A系)", 40, 6),
    ("一方向本站ZDJ(B系)", 23, 0),
    ("一方向本站FDJ(B系)", 23, 2),
    ("一方向本站ZXJ(B系)", 23, 4),
    ("一方向本站FXJ(B系)", 23, 6),
    ("一方向邻站ZDJ(B系)", 31, 0),
    ("一方向邻站FDJ(B系)", 31, 2),
    ("一方向邻站ZXJ(B系)", 31, 4),
    ("一方向邻站FXJ(B系)", 31, 6),
    ("二方向本站ZDJ(B系)", 41, 0),
    ("二方向本站FDJ(B系)", 41, 2),
    ("二方向本站ZXJ(B系)", 41, 4),
    ("二方向本站FXJ(B系)", 41, 6),
    ("二方向邻站ZDJ(B系)", 49, 0),
    ("二方向邻站FDJ(B系)", 49, 2),
    ("二方向邻站ZXJ(B系)", 49, 4),
    ("二方向邻站FXJ(B系)", 49, 6),
)

TESTDATA_SOURCE = "bt_agent_serial"
TESTDATA_ALARM_CODES = (
    tuple(range(8000, 8008))
    + tuple(range(8010, 8012))
    + tuple(8200 + cpu * 100 + code for cpu in range(4) for code in range(42))
    + tuple(8400 + cpu * 10 + idx for cpu in range(4) for idx in range(4))
    + tuple(8500 + cpu for cpu in range(4))
    + tuple(8510 + cpu for cpu in range(4))
)

TESTDATA_RELAY_NAMES = ("ZDJ", "FDJ", "ZXJ", "FXJ")
TESTDATA_CPU_NAMES = ("I-A", "I-B", "II-A", "II-B")


@dataclass(frozen=True)
class DeviceCacheSnapshot:
    ip_map: dict[str, int]
    id_set: set[int]
    alarm_filter_map: dict[int, set[int]]


@dataclass
class PacketMessage:
    entry_id: bytes | None
    ip_address: str
    data: bytes
    length: int
    device_id: int
    received_at: datetime
    received_monotonic: float
    source: str = ""
    source_ts_ms: int = 0


def load_device_cache(logger) -> DeviceCacheSnapshot | None:
    try:
        ip_map: dict[str, int] = {}
        id_set: set[int] = set()
        alarm_filter_map: dict[int, set[int]] = {}
        for device in Device.objects.all().only("ip_address", "device_id", "alarm_filters"):
            if device.ip_address:
                ip_map[device.ip_address] = device.device_id
            id_set.add(device.device_id)
            alarm_filter_map[device.device_id] = set(device.alarm_filters or [])
        return DeviceCacheSnapshot(ip_map=ip_map, id_set=id_set, alarm_filter_map=alarm_filter_map)
    except Exception as exc:
        logger.error("Failed to load device info from DB: %s", exc)
        return None


def ensure_stream_group(logger, r: redis.Redis, stream_key: str, group_name: str):
    try:
        r.xgroup_create(name=stream_key, groupname=group_name, id="$", mkstream=True)
        logger.info("[redis] created group=%s on stream=%s", group_name, stream_key)
    except Exception as exc:
        msg = str(exc)
        if "BUSYGROUP" in msg or "Consumer Group name already exists" in msg:
            return
        logger.warning("[redis] ensure group error: %s", exc)


def get_pending_count(r: redis.Redis, stream_key: str, group_name: str) -> int:
    try:
        pending = r.xpending(stream_key, group_name)
        if isinstance(pending, dict):
            return int(pending.get("pending", 0))
        if isinstance(pending, (list, tuple)) and pending:
            return int(pending[0])
    except Exception:
        return -1
    return -1


def read_stream_entries(
    r: redis.Redis,
    *,
    group_name: str,
    consumer_name: str,
    stream_key: str,
    stream_id: bytes,
    count: int,
    block_ms: int,
):
    response = r.xreadgroup(
        groupname=group_name,
        consumername=consumer_name,
        streams={stream_key: stream_id},
        count=count,
        block=block_ms,
    )
    if not response:
        return []
    entries = []
    for _stream, rows in response:
        entries.extend(rows)
    return entries


def decode_packet_fields(fields: dict[bytes, bytes]):
    msg_type = fields.get(b"type")
    if msg_type is not None and msg_type != b"packet":
        return None, "skip"

    ip_b = fields.get(b"ip", b"")
    data_hex_b = fields.get(b"data_hex", b"")
    if not ip_b or not data_hex_b:
        return None, "invalid_missing"

    ip_address = ip_b.decode(errors="ignore").strip()
    raw_hex = data_hex_b.decode(errors="ignore").strip()
    if not ip_address or not raw_hex:
        return None, "invalid_missing"

    try:
        data = bytes.fromhex(raw_hex)
    except Exception:
        return None, "invalid_hex"

    if len(data) < 4:
        return None, "invalid_short"

    if not (data[0:2] == b"\x7F\x7F" and data[-2:] == b"\xF7\xF7"):
        return None, "invalid_frame"

    src = fields.get(b"src", b"")
    ts_b = fields.get(b"ts", b"0")
    try:
        source_ts_ms = int(ts_b.decode(errors="ignore").strip() or "0")
    except Exception:
        source_ts_ms = 0

    explicit_device_id = _parse_explicit_device_id(fields)

    return {
        "ip_address": ip_address,
        "raw_hex": raw_hex,
        "data": data,
        "source": src.decode(errors="ignore").strip(),
        "source_ts_ms": source_ts_ms,
        "explicit_device_id": explicit_device_id,
    }, None


def _parse_explicit_device_id(fields: dict[bytes, bytes]) -> int | None:
    for key in (b"device_id", b"nms_id"):
        raw = fields.get(key, b"")
        if not raw:
            continue
        try:
            parsed = int(raw.decode(errors="ignore").strip())
        except Exception:
            continue
        if parsed > 0:
            return parsed
    return None


def resolve_device_id(ip_address: str, data: bytes, device_ip_map: dict[str, int], device_id_set: set[int]) -> int | None:
    try:
        device_id = int.from_bytes(data[2:3], byteorder="big")
    except Exception:
        return None

    if device_id in (0, 1):
        return device_ip_map.get(ip_address)

    return device_id if device_id in device_id_set else None


def parse_router_entry(
    entry_id: bytes,
    fields: dict[bytes, bytes],
    *,
    device_ip_map: dict[str, int],
    device_id_set: set[int],
):
    decoded, marker = decode_packet_fields(fields)
    if marker is not None:
        return None, marker

    device_id = decoded.get("explicit_device_id")
    if not device_id:
        device_id = resolve_device_id(decoded["ip_address"], decoded["data"], device_ip_map, device_id_set)
    if not device_id:
        return None, "invalid_device"
    if device_id not in device_id_set:
        return None, "invalid_device"

    return {
        "entry_id": entry_id,
        "ip_address": decoded["ip_address"],
        "raw_hex": decoded["raw_hex"],
        "data": decoded["data"],
        "device_id": device_id,
        "source": decoded["source"],
        "source_ts_ms": decoded["source_ts_ms"],
    }, None


def parse_worker_entry(entry_id: bytes, fields: dict[bytes, bytes]):
    decoded, marker = decode_packet_fields(fields)
    if marker is not None:
        return None, marker

    device_id = decoded.get("explicit_device_id")
    if not device_id:
        return None, "invalid_device"

    now_time = datetime.now(dt_timezone.utc)
    now_monotonic = time.monotonic()
    return (
        PacketMessage(
            entry_id=entry_id,
            ip_address=decoded["ip_address"],
            data=decoded["data"],
            length=len(decoded["data"]),
            device_id=device_id,
            received_at=now_time,
            received_monotonic=now_monotonic,
            source=decoded["source"],
            source_ts_ms=decoded["source_ts_ms"],
        ),
        None,
    )


def get_shard_index(device_id: int, shard_count: int) -> int:
    return device_id % shard_count


def _get_switch_bit_value(switch_status: bytes, byte_index: int, bit_index: int) -> int:
    idx = byte_index - 4
    if idx < 0 or idx >= len(switch_status):
        return 0
    byte_value = switch_status[idx]
    return (byte_value >> bit_index) & 1


def _compute_alarm_bit(alarm_code: int, switch_status: bytes) -> int:
    if alarm_code == 70:
        bit_value_0_self = _get_switch_bit_value(switch_status, 7, 0)
        bit_value_0_neighbor = _get_switch_bit_value(switch_status, 9, 0)
        return 0 if bit_value_0_self == bit_value_0_neighbor else 1

    if alarm_code == 72:
        bit_value_2_self = _get_switch_bit_value(switch_status, 7, 2)
        bit_value_3_self = _get_switch_bit_value(switch_status, 7, 3)
        bit_value_2_neighbor = _get_switch_bit_value(switch_status, 9, 2)
        bit_value_3_neighbor = _get_switch_bit_value(switch_status, 9, 3)
        if bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0:
            return 0
        if (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):
            return 0
        return 0 if (bit_value_2_self == bit_value_2_neighbor and bit_value_3_self == bit_value_3_neighbor) else 1

    if alarm_code == 110:
        bit_value_0_self = _get_switch_bit_value(switch_status, 11, 0)
        bit_value_0_neighbor = _get_switch_bit_value(switch_status, 13, 0)
        return 0 if bit_value_0_self == bit_value_0_neighbor else 1

    if alarm_code == 112:
        bit_value_2_self = _get_switch_bit_value(switch_status, 11, 2)
        bit_value_3_self = _get_switch_bit_value(switch_status, 11, 3)
        bit_value_2_neighbor = _get_switch_bit_value(switch_status, 13, 2)
        bit_value_3_neighbor = _get_switch_bit_value(switch_status, 13, 3)
        if bit_value_2_neighbor == 0 and bit_value_3_neighbor == 0:
            return 0
        if (bit_value_2_self == 0 and bit_value_3_self == 1) or (bit_value_2_neighbor == 0 and bit_value_3_neighbor == 1):
            return 0
        return 0 if (bit_value_2_self == bit_value_2_neighbor and bit_value_3_self == bit_value_3_neighbor) else 1

    if alarm_code in {190, 280, 370, 460}:
        bit_value_0 = _get_switch_bit_value(switch_status, alarm_code // 10, 0)
        bit_value_3 = _get_switch_bit_value(switch_status, alarm_code // 10, 3)
        return bit_value_0 & bit_value_3

    return _get_switch_bit_value(switch_status, alarm_code // 10, alarm_code % 10)


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


def extract_relay_actions(previous_status: dict, switch_status: bytes, current_time: datetime):
    current_status = {}
    actions = []

    for relay_name, byte_index, bit_index in RELAY_MAPPING:
        bit_value = _get_switch_bit_value(switch_status, byte_index, bit_index)
        current_status[relay_name] = bit_value
        if previous_status and previous_status.get(relay_name) != bit_value:
            actions.append((relay_name, "吸起" if bit_value == 1 else "落下", current_time))

    return current_status, actions


def is_testdata_packet(msg) -> bool:
    return msg.length == 44 and msg.source == TESTDATA_SOURCE


def parse_testdata_switch_status(frame: bytes) -> bytes | None:
    if len(frame) != 44:
        return None
    if frame[:2] != b"\x7F\x7F" or frame[-2:] != b"\xF7\xF7":
        return None
    raw_data = frame[2:-2]
    if len(raw_data) != 40:
        return None
    expected = raw_data[38] + (raw_data[39] << 8)
    actual = sum(raw_data[:38]) & 0xFFFF
    if expected != actual:
        return None
    return raw_data


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


def extract_testdata_relay_actions(previous_status: dict, switch_status: bytes, current_time: datetime):
    current_status = {}
    actions = []
    for cpu_index, cpu_name in enumerate(TESTDATA_CPU_NAMES):
        base = cpu_index * 8
        if base + 6 >= len(switch_status):
            continue
        relay_byte = switch_status[base + 6]
        for relay_index, relay_name in enumerate(TESTDATA_RELAY_NAMES):
            bit_value = (relay_byte >> (relay_index * 2)) & 0x01
            key = f"{cpu_name}-{relay_name}"
            current_status[key] = bit_value
            if previous_status and previous_status.get(key) != bit_value:
                actions.append((key, "吸起" if bit_value == 1 else "落下", current_time))
    return current_status, actions


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


def parse_analog_payload(payload: bytes):
    if len(payload) < 12:
        return None

    voltage_1 = int.from_bytes(payload[4:6], byteorder="big", signed=True) / 100.0
    current_1 = int.from_bytes(payload[6:8], byteorder="big", signed=True) / 100.0
    voltage_2 = int.from_bytes(payload[8:10], byteorder="big", signed=True) / 100.0
    current_2 = int.from_bytes(payload[10:12], byteorder="big", signed=True) / 100.0

    voltage_threshold = 500
    if abs(voltage_1) > voltage_threshold and abs(voltage_2) > voltage_threshold:
        return None

    if abs(voltage_1) > voltage_threshold:
        voltage_1 = 0
    if abs(voltage_2) > voltage_threshold:
        voltage_2 = 0

    if abs(voltage_1) <= 1 and abs(voltage_2) <= 1:
        return None

    analog_json = json.dumps(
        {
            "voltage_1": voltage_1,
            "current_1": current_1,
            "voltage_2": voltage_2,
            "current_2": current_2,
        }
    )

    return voltage_1, current_1, voltage_2, current_2, analog_json
