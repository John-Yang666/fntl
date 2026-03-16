# sy_receiver.py
# 功能：从 Redis Streams 订阅 sy.raw，解析 sy 串口帧：
#   1）可配置是否将原始帧落库到 RawFrameLog（含 7F7F...F7F7）
#   2）A1：保存到 SwitchData（状态字快照，sy_receiver 内部先做“变化/心跳”判断，再决定是否调用 _save_a1_frame_sync）
#   3）A2：保存 ChangeBitEvent，并同步更新 SwitchData
#
# 关键修复：
#   - 从 sy_agent 写入的 JSON 中读取 nms_id（网管唯一设备ID）
#   - 数据库匹配、入库、去重心跳、last_communication_time 的 Redis key 一律使用 nms_id
#   - 帧内 frame[2] 仅作为 serial_id（串口地址）用于日志/核对（不同线路可重复）

import os
import json
import time
import signal
import binascii
import traceback
from datetime import datetime, timedelta
from typing import Optional, Any, Dict

import redis

# ========= Redis Streams 基本配置 =========
# 业务 Redis（存通信时间、A1去重心跳缓存等）
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Streams Redis（可独立容器）
STREAM_REDIS_HOST = os.getenv("STREAM_REDIS_HOST", REDIS_HOST)
STREAM_REDIS_PORT = int(os.getenv("STREAM_REDIS_PORT", REDIS_PORT))

SY_STREAM_DB = int(os.getenv("SY_STREAM_DB", "0"))
SY_RAW_STREAM = os.getenv("SY_RAW_STREAM", "sy.raw")
SY_RAW_GROUP = os.getenv("SY_RAW_GROUP", "sy_ingestor")
SY_RAW_CONSUMER = os.getenv("SY_RAW_CONSUMER", f"sy-receiver-{os.getpid()}")

# 读取/阻塞参数
SY_RAW_READ_COUNT = int(os.getenv("SY_RAW_READ_COUNT", "50"))
SY_RAW_BLOCK_MS = int(os.getenv("SY_RAW_BLOCK_MS", "200"))


def str2bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


# 是否记录原始协议帧到 RawFrameLog（1开启，0关闭。生产环境建议关闭。）
SY_LOG_RAW_FRAMES = str2bool(os.getenv("SY_LOG_RAW_FRAMES", "0"))

# A1 心跳间隔（秒），用于“状态未变时，隔一段时间仍然落一条心跳快照”
A1_HEARTBEAT_SECONDS = int(os.getenv("A1_HEARTBEAT_SECONDS", "60"))

# ========= Django 初始化 =========
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
import django  # noqa: E402

django.setup()

# ========= Django / Redis / 常量 =========
from django.utils import timezone  # noqa: E402
from myapp.models import Device, RawFrameLog  # noqa: E402
from myapp.tasks import (  # noqa: E402
    _save_a1_frame_sync,
    _save_a2_change_sync,
)
from consts import LAST_COMMUNICATION_TIME_TIMEOUT  # 用作 last_communication_time 的 TTL

RUNNING = True

# Redis：db=2 专门存放通信时间等字符串（和 summarize_alarms 对齐，同时也用于 A1 去重）
redis_client2 = redis.StrictRedis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=2,
    decode_responses=True,
)

# Redis Streams 客户端（可指向独立 redis_stream 容器）
redis_stream = redis.StrictRedis(
    host=STREAM_REDIS_HOST,
    port=STREAM_REDIS_PORT,
    db=SY_STREAM_DB,
    decode_responses=True,
)

# ========= 信号处理 =========
def handle_sigterm(sig, frame):
    global RUNNING
    RUNNING = False
    print("\n[sy_receiver] shutting down...")


def ensure_group(r: redis.Redis, stream: str, group: str):
    """确保 consumer group 存在（不存在就创建；已存在忽略）"""
    try:
        r.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
        print(f"[Redis] xgroup_create OK: stream={stream}, group={group}")
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            return
        raise


# ========= 工具函数 =========
def hex_to_bytes(hex_str: str) -> bytes:
    hex_str = (hex_str or "").strip()
    if hex_str.startswith("0x") or hex_str.startswith("0X"):
        hex_str = hex_str[2:]
    # 去掉中间的空格
    hex_str = hex_str.replace(" ", "")
    if len(hex_str) == 0:
        return b""
    if len(hex_str) % 2 != 0:
        # 长度为奇数，说明上报有问题，丢弃最后 1 个半字节
        hex_str = hex_str[:-1]
    return binascii.unhexlify(hex_str)


def parse_sy_frame(frame: bytes) -> dict:
    """
    解析 sy 串口协议帧格式，返回基本信息：
    {
        "serial_id": int,
        "cmd": "A1"/"A2"/"NO_CHANGE"/"0x??",
        "payload": b"...",  # 去掉头(7F7F)、地址、命令字、尾(F7F7) 后的内容
    }

    帧格式：
      [0] = 0x7F
      [1] = 0x7F
      [2] = 地址（serial_id，串口设备地址；不同线路可能重复）
      [3] = 命令字（0xA1 / 0xA2 / 0x05 / 其它）
      [4..-3] = payload
      [-2],[-1] = 0xF7,0xF7
    """
    if len(frame) < 6:
        raise ValueError("frame too short")

    if not (frame[0] == 0x7F and frame[1] == 0x7F):
        raise ValueError("bad header")

    if not (frame[-1] == 0xF7 and frame[-2] == 0xF7):
        raise ValueError("bad tail")

    serial_id = frame[2]
    cmd_code = frame[3]  # 命令字在下标 3
    payload = frame[4:-2]  # payload 从下标 4 开始，到倒数第 3 个字节结束

    if cmd_code == 0xA1:
        cmd_name = "A1"
    elif cmd_code == 0xA2:
        cmd_name = "A2"
    elif cmd_code == 0x05:
        # 0x05：设备回复“暂无变化量”（ACK，无业务数据）
        cmd_name = "NO_CHANGE"
    else:
        cmd_name = f"0x{cmd_code:02X}"

    return {
        "serial_id": int(serial_id),
        "cmd": cmd_name,
        "payload": payload,
    }


# ========= 核心处理逻辑 =========
def handle_frame(
    frame_bytes: bytes,
    *,
    nms_id: Optional[int] = None,
    msg_serial_id: Optional[int] = None,
    line_id: Optional[Any] = None,
    port: Optional[Any] = None,
):
    """
    对单个协议帧做完整处理：
      0）解析出 serial_id / cmd / payload
      1）刷新通信时间（last_communication_time） —— 使用 nms_id
      2）按配置决定是否写 RawFrameLog —— 绑定 Device(nms_id)，note 记录 serial_id/line/port
      3）根据 cmd 分流到 A1/A2/NO_CHANGE/其它处理 —— 入库/去重使用 nms_id
    """
    # 统一打点时间（用于通信时间 + A1 心跳）
    now = timezone.now()  # aware datetime

    try:
        parsed = parse_sy_frame(frame_bytes)
    except Exception as e:
        # 结构都不对，但在开启原始日志时也要落 RawFrameLog，方便排查
        print(f"[WARN] invalid frame format: {e}")
        if SY_LOG_RAW_FRAMES:
            RawFrameLog.objects.create(
                device=None,
                raw_frame=frame_bytes,
                cmd=None,
                note=f"parse_error: {e}; nms_id={nms_id}; line_id={line_id}; port={port}",
            )
        return

    serial_id = parsed["serial_id"]
    cmd = parsed["cmd"]
    payload = parsed["payload"]

    # ✅ 真正用于数据库匹配的 device_id：优先用 nms_id（来自 stream JSON）
    if nms_id is None:
        # 兼容旧消息：没有 nms_id 时才退回 serial_id（但多线路会串，尽量不要依赖）
        device_db_id = int(serial_id)
        print(
            f"[WARN] stream msg missing nms_id, fallback to serial_id={serial_id} "
            f"(may conflict across lines). line_id={line_id}, port={port}"
        )
    else:
        device_db_id = int(nms_id)

    # 可选核对：消息里的 serial_id 与帧里的 serial_id 是否一致
    if msg_serial_id is not None:
        try:
            if int(msg_serial_id) != int(serial_id):
                print(
                    f"[WARN] serial_id mismatch: msg={msg_serial_id} frame={serial_id} "
                    f"nms_id={device_db_id} line_id={line_id} port={port}"
                )
        except Exception:
            pass

    # ====== 1) 刷新通信时间：给 summarize_alarms 用（用 nms_id） ======
    try:
        redis_client2.set(
            f"device_{device_db_id}_last_communication_time",
            now.isoformat(),
            ex=LAST_COMMUNICATION_TIME_TIMEOUT,  # TTL，避免长时间遗留
        )
    except Exception as e:
        print(f"[WARN] update last_communication_time failed for device={device_db_id}: {e}")
        # 失败不影响后面处理

    # ====== 2) 先找到设备（可能没有，允许为 None）—— 用 nms_id ======
    device_obj = Device.objects.filter(device_id=device_db_id).first()

    # 原始帧按配置决定是否落 RawFrameLog
    # 注意：NO_CHANGE (0x05) 不入库
    if SY_LOG_RAW_FRAMES and cmd != "NO_CHANGE":
        RawFrameLog.objects.create(
            device=device_obj,
            raw_frame=frame_bytes,
            cmd=cmd,
            note=f"nms_id={device_db_id}; serial_id={serial_id}; line_id={line_id}; port={port}",
        )

    # ====== 3) 根据命令字分流 ======
    if cmd == "A1":
        # A1：全部开关量快照
        # payload 里包含 d1~d4（4 个字节，分别是一/二/三方向和系统状态）
        # 为了兼容老版本 6 字节，这里先取前 4 字节
        status_bytes = bytes(payload[:4])
        if len(status_bytes) == 0:
            print(f"[WARN] A1 frame payload empty, nms_id={device_db_id} serial_id={serial_id}")
            return

        print(f"[A1] nms_id={device_db_id}, serial_id={serial_id}, status_bytes={status_bytes.hex()}")

        # ===== A1 在 sy_receiver 中做“变化 + 心跳” 判断 =====
        # ✅ 去重/心跳 key 必须用 nms_id（否则跨线路串）
        key_last_bytes = f"sy:a1:last_bytes:{device_db_id}"
        key_last_log_ts = f"sy:a1:last_log_ts:{device_db_id}"

        # 默认：需要落库（如果 Redis 出问题，就直接落，保证数据有）
        need_save = True

        try:
            hex_cur = status_bytes.hex()
            last_bytes = redis_client2.get(key_last_bytes)
            last_log_ts_str = redis_client2.get(key_last_log_ts)

            # 1) 判断是否变化
            changed = (last_bytes is None) or (hex_cur != last_bytes)

            # 2) 未变化 → 判断心跳间隔
            need_log_for_heartbeat = False
            if not changed:
                if last_log_ts_str is None:
                    # 从未落库过，也记一条
                    need_log_for_heartbeat = True
                else:
                    try:
                        last_log_ts = datetime.fromisoformat(last_log_ts_str)
                        if timezone.is_naive(last_log_ts):
                            last_log_ts = timezone.make_aware(
                                last_log_ts,
                                timezone.get_current_timezone(),
                            )
                        if now - last_log_ts >= timedelta(seconds=A1_HEARTBEAT_SECONDS):
                            need_log_for_heartbeat = True
                    except Exception as e:
                        print(f"[WARN] A1 parse last_log_ts failed nms_id={device_db_id}: {e}")
                        # 解析失败时，宁可多记一条
                        need_log_for_heartbeat = True

            # 3) 决定是否需要真正落库
            if (not changed) and (not need_log_for_heartbeat):
                # 不需要落库，但也更新一下 last_bytes，防止缓存丢失
                need_save = False
                try:
                    redis_client2.set(key_last_bytes, hex_cur)
                except Exception:
                    pass
            else:
                # 需要落库（变化 or 心跳），同时更新 Redis 中的 last_bytes / last_log_ts
                need_save = True
                try:
                    redis_client2.set(key_last_bytes, hex_cur)
                    redis_client2.set(key_last_log_ts, now.isoformat())
                except Exception as e:
                    print(f"[WARN] A1 redis set failed nms_id={device_db_id}: {e}")

        except Exception as e:
            # Redis 整体失败：回退为“每条都落库”，保证功能正确性
            print(f"[WARN] A1 dedup/heartbeat logic failed nms_id={device_db_id}: {e}")
            need_save = True

        # 4) 最终决定是否调用 _save_a1_frame_sync（真正入库）
        if not need_save:
            # 状态没变且心跳间隔未到 → 不插表
            return

        # 真的需要入库时，才调用 A1 保存函数
        _save_a1_frame_sync(
            device_id=device_db_id,  # ✅ 用 nms_id
            frame_bytes=status_bytes,
        )

    elif cmd == "A2":
        # A2：单个变化开关量
        # 协议：最后两个字节是 S 状态 + H 校验和
        #   S: D0~D6 表示位置(0~48)，D7 表示新值(0/1)
        if len(payload) < 2:
            print(f"[WARN] A2 frame payload too short, nms_id={device_db_id} serial_id={serial_id}")
            return

        s_byte = payload[-2]  # 倒数第二个字节
        bit_index_all = s_byte & 0x7F  # 0~127，实际 0~48
        new_value = (s_byte >> 7) & 0x01  # 0 or 1

        byte_index = bit_index_all // 8  # 第几个字节（从 0 开始）
        bit_pos = bit_index_all % 8  # 该字节内第几位（从 0 开始，LSB）

        print(
            f"[A2] nms_id={device_db_id}, serial_id={serial_id}, "
            f"byte_index={byte_index}, bit_pos={bit_pos}, value={new_value}"
        )

        _save_a2_change_sync(
            device_id=device_db_id,  # ✅ 用 nms_id
            byte_index=byte_index,
            bit_pos=bit_pos,
            new_value=new_value,
            persist=True,
        )

    elif cmd == "NO_CHANGE":
        # 0x05：设备回复当前“暂无变化量”
        # 不入库，只打印简洁日志
        print(f"[INFO] nms_id={device_db_id} serial_id={serial_id} 暂无变化量")
        return

    else:
        # 其它未知命令字：只做信息打印（如果开启 RawFrameLog 已经在上面入库）
        print(
            f"[INFO] unknown cmd {cmd}, nms_id={device_db_id}, serial_id={serial_id}, "
            f"len={len(payload)}"
        )


def process_stream_message(data: Dict[str, Any]):
    """
    从 Streams 拉到一条 JSON（字段里），抽出 hex 字符串，转成 bytes，交给 handle_frame。
    兼容几种可能的 key：payload_hex / frame_hex / raw_hex。

    同时读取 nms_id / serial_id / line_id / port 等上下文，供 handle_frame 做设备匹配与日志核对。
    """
    hex_str = data.get("payload_hex") or data.get("frame_hex") or data.get("raw_hex")
    if not hex_str:
        print(f"[WARN] message without hex field: {data}")
        return

    try:
        frame_bytes = hex_to_bytes(hex_str)
    except Exception as e:
        print(f"[ERR] hex_to_bytes failed: {e}, raw={hex_str!r}")
        return

    if not frame_bytes:
        print(f"[WARN] empty frame after hex_to_bytes, raw={hex_str!r}")
        return

    # ✅ 关键：从 sy_agent 写入的 JSON 中获取 nms_id（网管唯一ID）
    nms_id = data.get("nms_id")
    msg_serial_id = data.get("serial_id")  # 可选：核对用（可能没有）
    line_id = data.get("line_id")
    port = data.get("port")

    # 打印尽量简洁（避免刷屏）
    # 你要是想看全帧可以打开下一行
    # print(f"[MSG] raw frame ({len(frame_bytes)} bytes): {frame_bytes.hex()}")
    print(
        f"[MSG] nms_id={nms_id} msg_serial_id={msg_serial_id} "
        f"line_id={line_id} port={port} bytes={len(frame_bytes)}"
    )

    handle_frame(
        frame_bytes,
        nms_id=int(nms_id) if nms_id is not None else None,
        msg_serial_id=int(msg_serial_id) if msg_serial_id is not None else None,
        line_id=line_id,
        port=port,
    )


def main():
    print(
        f"[sy_receiver] start, "
        f"biz_redis={REDIS_HOST}:{REDIS_PORT}/2, "
        f"stream_redis={STREAM_REDIS_HOST}:{STREAM_REDIS_PORT}/{SY_STREAM_DB}, "
        f"stream={SY_RAW_STREAM}, group={SY_RAW_GROUP}, consumer={SY_RAW_CONSUMER}, "
        f"log_raw_frames={'ON' if SY_LOG_RAW_FRAMES else 'OFF'}, "
        f"A1_HEARTBEAT_SECONDS={A1_HEARTBEAT_SECONDS}"
    )

    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)

    ensure_group(redis_stream, SY_RAW_STREAM, SY_RAW_GROUP)

    while RUNNING:
        try:
            resp = redis_stream.xreadgroup(
                groupname=SY_RAW_GROUP,
                consumername=SY_RAW_CONSUMER,
                streams={SY_RAW_STREAM: ">"},
                count=SY_RAW_READ_COUNT,
                block=SY_RAW_BLOCK_MS,
            )
        except Exception as e:
            print(f"[Stream Error] XREADGROUP failed: {e}")
            time.sleep(0.2)
            continue

        if not resp:
            continue

        for _stream_name, entries in resp:
            for msg_id, fields in entries:
                try:
                    # 兼容两种字段：data / json（你的上一版就是这么做的）
                    raw = fields.get("data") or fields.get("json")
                    if not raw:
                        print(f"[WARN] stream message missing data/json: id={msg_id}, fields={fields}")
                        redis_stream.xack(SY_RAW_STREAM, SY_RAW_GROUP, msg_id)
                        continue

                    data = json.loads(raw)
                    process_stream_message(data)

                    # 处理成功后 ack（等价 Kafka commit）
                    redis_stream.xack(SY_RAW_STREAM, SY_RAW_GROUP, msg_id)

                except Exception as e:
                    print(f"[ERR] process stream message failed: {e}")
                    traceback.print_exc()
                    # 不 ack：留 pending，便于你后续做 pending reclaim
                    time.sleep(0.05)

    print("[sy_receiver] bye.")


if __name__ == "__main__":
    main()