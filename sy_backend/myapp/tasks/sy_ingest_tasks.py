# myapp/tasks/sy_ingest_tasks.py

from django.db import transaction
from celery import shared_task

from myapp.models import Device, SwitchData, ChangeBitEvent, RelayAction

from django.core.cache import cache
from django.utils import timezone

from myapp.tasks.extract_sy_alarms_task import extract_sy_alarms  # 告警位图


# ========================
# A1/A2 后处理：告警 + latest_switch（异步）
# 说明：
# - 用 hex 传参，避免 bytes 在 Celery 序列化/兼容上的坑
# - 任务内执行 extract_sy_alarms + cache.set
# ========================
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def sy_postprocess_status_task(self, device_id: int, status_hex: str, ver: str, now_str: str = "") -> None:
    """
    异步后处理：
    1) 更新告警位图（extract_sy_alarms）
    2) 写 latest_switch 到 cache

    参数：
    - device_id: 设备ID
    - status_hex: 状态字节 hex 字符串
    - ver: "v4"/"v6"
    - now_str: 展示用时间字符串（可选）
    """
    status_bytes = bytes.fromhex(status_hex) if status_hex else b""
    if not status_bytes:
        return

    # 1) 告警位图（异步）
    extract_sy_alarms(device_id, status_bytes)

    # 2) latest_switch cache（异步）
    if not now_str:
        now_str = timezone.now().isoformat()

    cache.set(f"device_{device_id}_switch_status", status_bytes, timeout=None)
    cache.set(f"device_{device_id}_switch_status_updated_at", now_str, timeout=None)
    cache.set(f"device_{device_id}_switch_status_version", ver, timeout=None)


def _save_a1_frame_sync(*, device_id: int, frame_bytes: bytes) -> None:
    """
    同步保存 A1 全部量快照到 SwitchData：
    - device_id: 设备ID（sy_agent 已经解析出来）
    - frame_bytes: 状态字节原始内容，例如 b'\\x01\\x02\\x03\\x04'

    改造点（半异步）：
    - SwitchData 落库保持同步（保证 A2 的“基准快照”一致）
    - extract_sy_alarms + latest_cache 改为 Celery 异步（避免阻塞 Kafka 消费）
    """
    if not frame_bytes:
        print(f"[A1] device={device_id} frame_bytes is empty, skip")
        return

    try:
        dev = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        print(f"[A1] device_id={device_id} 不存在，丢弃该帧")
        return

    # 根据长度判断版本：4 字节 = 新协议，>4 视为老协议
    ver = "v4" if len(frame_bytes) <= 4 else "v6"

    # 1) 同步写状态快照（关键：保持同步）
    SwitchData.objects.create(
        device=dev,
        switch_status=frame_bytes,
        version=ver,
    )

    # 2) 告警 + cache：异步（建议 on_commit，确保当前事务提交后再发任务）
    now_str = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    status_hex = frame_bytes.hex()

    transaction.on_commit(
        lambda: sy_postprocess_status_task.delay(device_id, status_hex, ver, now_str)
    )


# ========================
# 继电器位映射（全局 bitIndex -> (方向, 继电器代号)）
# bitIndex = byte_index * 8 + bit_pos
# ========================
SY_RELAY_BITS = {
    # d1（第一字节）：D4..D7 -> bit 4..7
    4:  ("一方向", "FDJ"),  # D4
    5:  ("一方向", "ZDJ"),  # D5
    6:  ("一方向", "FXJ"),  # D6
    7:  ("一方向", "ZXJ"),  # D7

    # d2（第二字节）：D4..D7 -> bit 12..15
    12: ("二方向", "FDJ"),  # D4
    13: ("二方向", "ZDJ"),  # D5
    14: ("二方向", "FXJ"),  # D6
    15: ("二方向", "ZXJ"),  # D7

    # d3（第三字节）：D4..D7 -> bit 20..23
    20: ("三方向", "FDJ"),  # D4
    21: ("三方向", "ZDJ"),  # D5
    22: ("三方向", "FXJ"),  # D6
    23: ("三方向", "ZXJ"),  # D7
}


def _log_relay_action_if_needed(dev: Device, bit_index_flat: int, new_val: int) -> None:
    """
    根据 bit_index_flat 判断是否为继电器动作，如果是则写 RelayAction。
    new_val: 0 / 1
    """
    mapping = SY_RELAY_BITS.get(bit_index_flat)
    if not mapping:
        return

    direction_label, relay_type = mapping

    # 没启用三方向时，忽略三方向继电器动作
    if direction_label == "三方向" and not getattr(dev, "direction3_enabled", False):
        return

    relay_label = f"{direction_label}{relay_type}"
    action_label = "吸起" if new_val == 1 else "落下"

    RelayAction.objects.create(
        device=dev,
        relay=relay_label,
        action=action_label,
        source="A2",
        # timestamp 不要传，模型里 auto_now_add=True 会自动写
    )


@shared_task
def log_relay_action_task(device_id: int, bit_index_flat: int, new_val: int) -> None:
    """
    Celery 任务封装：
    - 通过 device_id 重新获取 Device
    - 调用本地工具函数 _log_relay_action_if_needed
    这样 Flower 中可以看到继电器动作任务。
    """
    try:
        dev = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        print(f"[RelayTask] device_id={device_id} 不存在，丢弃继电器动作记录")
        return

    _log_relay_action_if_needed(dev, bit_index_flat, new_val)


@transaction.atomic
def _save_a2_change_sync(
    *,
    device_id: int,
    byte_index: int,
    bit_pos: int,
    new_value: int,
    persist: bool = True,
) -> None:
    """
    同步处理 A2 单点变化：
    - 基于最新一条 SwitchData，修改对应 bit，生成一条新的快照
    - 可选地在 ChangeBitEvent 记录一条变化事件
    - 告警位图 + latest_cache 改为异步（sy_postprocess_status_task）
    - 继电器动作：异步（log_relay_action_task）
    """
    try:
        dev = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        print(f"[A2] device_id={device_id} 不存在，丢弃该变化")
        return

    # 取该设备最新的状态快照，如果没有，就从全 0 的 4 字节起步
    last = SwitchData.objects.filter(device=dev).order_by("-timestamp").first()
    if last and last.switch_status:
        buf = bytearray(last.switch_status)
    else:
        buf = bytearray(b"\x00\x00\x00\x00")  # 默认 4 字节，对应 d1~d4

    if byte_index < 0 or byte_index >= len(buf):
        print(f"[A2] device={device_id} byte_index={byte_index} 越界(len={len(buf)}), 丢弃")
        return
    if bit_pos < 0 or bit_pos > 7:
        print(f"[A2] device={device_id} bit_pos={bit_pos} 非法, 丢弃")
        return

    bit_mask = 1 << bit_pos
    new_val = 1 if new_value else 0

    if new_val == 1:
        buf[byte_index] |= bit_mask
    else:
        buf[byte_index] &= ~bit_mask & 0xFF

    # 新增一条更新后的快照
    ver = "v4" if len(buf) <= 4 else "v6"
    new_status = bytes(buf)

    SwitchData.objects.create(
        device=dev,
        switch_status=new_status,
        version=ver,
    )

    # 记录变化事件（方便后台分析/前端实时）
    bit_index_flat = byte_index * 8 + bit_pos  # 展开成 0-based 全局位序号
    if persist:
        ChangeBitEvent.objects.create(
            device=dev,
            bit_index=bit_index_flat,
            value=bool(new_val),
            source="A2",
        )

    print(
        f"[A2] saved change device={device_id}, "
        f"byte={byte_index}, bit={bit_pos}, value={new_val}"
    )

    # ★ 告警 + latest_switch：异步（建议 on_commit，避免任务跑在提交前）
    now_str = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    status_hex = new_status.hex()

    transaction.on_commit(
        lambda: sy_postprocess_status_task.delay(device_id, status_hex, ver, now_str)
    )

    # ★ 继电器动作记录（如果该 bit 属于继电器），交给 Celery
    log_relay_action_task.delay(device_id, bit_index_flat, new_val)
