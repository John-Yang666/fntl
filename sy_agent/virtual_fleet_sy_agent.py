#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sy_virtual_fleet_bus.py

串口总线“轮询风格”的 SY 虚拟响应帧发生器（写入 Redis Streams: sy.raw）

特点：
- 每条线 = 一条串口总线：同一时刻只会有 1 个设备“被轮询并响应”
- 用 BUS_TICK_SEC 控制每条线总吞吐：rate_line ≈ 1 / BUS_TICK_SEC
- A1/A2 选择逻辑模拟 sy_agent：
    - 若设备距上次 A1 >= A1_INTERVAL_SEC -> 产生 A1
    - 否则产生 A2（只变化继电器 bit）
- 输出 data(JSON bytes) 兼容你现有 sy_receiver(Streams) 解析
"""

import os
import time
import json
import random
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import redis


# =========================
# Redis Streams 配置
# =========================
REDIS_HOST = os.getenv("REDIS_STREAM_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_STREAM_PORT", "36380"))
REDIS_DB = int(os.getenv("REDIS_STREAM_DB", "0"))

RAW_STREAM_KEY = os.getenv("SY_RAW_STREAM_KEY", "sy.raw")
RAW_STREAM_MAXLEN = int(os.getenv("SY_RAW_STREAM_MAXLEN", "200000"))

# =========================
# A1/A2 节奏（按“设备维度”判断该发 A1 还是 A2）
# =========================
A1_INTERVAL_SEC = float(os.getenv("A1_INTERVAL", "5"))   # 5s
A2_INTERVAL_SEC = float(os.getenv("A2_INTERVAL", "1"))   # 1s（仅用于“像真一点”的 bit 翻转频率参考，可不严格）

# =========================
# 串口总线轮询节拍（按“线路维度”限制总吞吐）
# =========================
BUS_TICK_SEC = float(os.getenv("BUS_TICK_SEC", "0.05"))  # 0.05s -> 每线约 20 pkt/s
BUS_JITTER_SEC = float(os.getenv("BUS_JITTER", "0.005")) # 每 tick 加一点抖动

# 可选：模拟超时/丢包（更贴近现场“等不到回帧就耗时更久”）
DROP_RATE = float(os.getenv("BUS_DROP_RATE", "0.0"))      # 0.0~1.0
TIMEOUT_EXTRA_SEC = float(os.getenv("BUS_TIMEOUT_EXTRA", "0.0"))  # 丢包时额外等待（比如 0.2）

# 日志
LOG_EVERY_SEC = float(os.getenv("LOG_EVERY_SEC", "5"))

# =========================
# 手动分线路：你只需要改这里
# =========================
LINES_CONFIG = [
    {
        "line_id": 1,
        "name": "Line-1",
        "devices": [
            {"serial_id": 1, "nms_id": 1},
            {"serial_id": 2, "nms_id": 2},
            {"serial_id": 3, "nms_id": 3},
            {"serial_id": 4, "nms_id": 4},
            {"serial_id": 5, "nms_id": 5},
            {"serial_id": 6, "nms_id": 6},
            {"serial_id": 7, "nms_id": 7},
            {"serial_id": 8, "nms_id": 8},
            {"serial_id": 9, "nms_id": 9},
            {"serial_id": 10, "nms_id": 10},
            {"serial_id": 129, "nms_id": 129},
            {"serial_id": 130, "nms_id": 130},
            {"serial_id": 131, "nms_id": 131},
            {"serial_id": 132, "nms_id": 132},
            {"serial_id": 133, "nms_id": 133},
            {"serial_id": 134, "nms_id": 134},
            {"serial_id": 135, "nms_id": 135},
            {"serial_id": 136, "nms_id": 136},
            {"serial_id": 137, "nms_id": 137},
            {"serial_id": 138, "nms_id": 138},
        ],
    },
    {
        "line_id": 2,
        "name": "Line-2",
        "devices": [
            {"serial_id": 1, "nms_id": 11},
            {"serial_id": 2, "nms_id": 12},
            {"serial_id": 3, "nms_id": 13},
            {"serial_id": 4, "nms_id": 14},
            {"serial_id": 5, "nms_id": 15},
            {"serial_id": 6, "nms_id": 16},
            {"serial_id": 7, "nms_id": 17},
            {"serial_id": 8, "nms_id": 18},
            {"serial_id": 9, "nms_id": 19},
            {"serial_id": 10, "nms_id": 20},
            {"serial_id": 11, "nms_id": 21},
            {"serial_id": 129, "nms_id": 139},
            {"serial_id": 130, "nms_id": 140},
            {"serial_id": 131, "nms_id": 141},
            {"serial_id": 132, "nms_id": 142},
            {"serial_id": 133, "nms_id": 143},
            {"serial_id": 134, "nms_id": 144},
            {"serial_id": 135, "nms_id": 145},
            {"serial_id": 136, "nms_id": 146},
            {"serial_id": 137, "nms_id": 147},
            {"serial_id": 138, "nms_id": 148},
            {"serial_id": 139, "nms_id": 149},
        ],
    },
]


# =========================
# 帧构造（响应帧格式：7F7F ... F7F7）
# =========================
def build_a1_resp(serial_id: int, d_bytes: List[int]) -> bytes:
    frame = bytearray()
    frame += b"\x7F\x7F"
    frame.append(serial_id & 0xFF)
    frame.append(0xA1)
    frame.extend([x & 0xFF for x in d_bytes[:4]])
    h = sum(frame[2:]) & 0xFF
    frame.append(h)
    frame += b"\xF7\xF7"
    return bytes(frame)


def build_a2_resp(serial_id: int, d_bytes: List[int], bit_index_all: int, new_val: int) -> bytes:
    frame = bytearray()
    frame += b"\x7F\x7F"
    frame.append(serial_id & 0xFF)
    frame.append(0xA2)
    frame.extend([x & 0xFF for x in d_bytes[:4]])
    s = ((new_val & 0x01) << 7) | (bit_index_all & 0x7F)
    frame.append(s)
    h = sum(frame[2:]) & 0xFF
    frame.append(h)
    frame += b"\xF7\xF7"
    return bytes(frame)


# 继电器相关 bit（d1/d2/d3 的 D4~D7）
RELAY_BIT_INDEXES = [4, 5, 6, 7, 12, 13, 14, 15, 20, 21, 22, 23]


def now_mono() -> float:
    return time.monotonic()


def jitter(base: float, j: float) -> float:
    return base + (random.uniform(0, j) if j > 0 else 0.0)


def get_redis_client() -> redis.Redis:
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    r.ping()
    return r


def xadd_raw(
    r: redis.Redis,
    *,
    line_id: int,
    serial_id: int,
    nms_id: int,
    req_cmd: str,
    frame: bytes,
    extra: Optional[dict] = None,
):
    payload = {
        "payload_hex": frame.hex(),
        "ts": int(time.time()),
        "line_id": int(line_id),
        "port": "virtual-bus",
        "serial_id": int(serial_id),
        "nms_id": int(nms_id),
        "req_cmd": str(req_cmd),
    }
    if extra:
        payload.update(extra)

    r.xadd(
        RAW_STREAM_KEY,
        {"data": json.dumps(payload, ensure_ascii=False).encode("utf-8")},
        maxlen=RAW_STREAM_MAXLEN,
        approximate=True,
    )


@dataclass
class DevState:
    serial_id: int
    nms_id: int
    d_bytes: List[int] = field(default_factory=lambda: [random.getrandbits(8) for _ in range(4)])
    bits_state: Dict[int, int] = field(default_factory=lambda: {idx: 0 for idx in RELAY_BIT_INDEXES})
    last_a1_mono: float = 0.0
    last_a2_mono: float = 0.0


class LineBusSimulator(threading.Thread):
    """
    每条线：严格“轮询节拍”，每 tick 只产生 1 帧（A1 或 A2）
    """
    def __init__(self, *, line_id: int, name: str, devices: List[Dict]):
        super().__init__(daemon=True)
        self.line_id = int(line_id)
        self.name = str(name)

        self.devices: List[DevState] = []
        t0 = now_mono()
        for d in devices:
            sid = int(d["serial_id"]) & 0xFF
            nid = int(d.get("nms_id", sid))
            st = DevState(serial_id=sid, nms_id=nid)
            # 初始让 last_a1 分散一点，避免启动瞬间全 A1
            st.last_a1_mono = t0 - random.random() * A1_INTERVAL_SEC
            st.last_a2_mono = t0 - random.random() * A2_INTERVAL_SEC
            self.devices.append(st)

        self._stop = threading.Event()
        self._tx_count = 0
        self._a1_count = 0
        self._a2_count = 0
        self._last_log = now_mono()
        self._cursor = 0

    def stop(self):
        self._stop.set()

    def run(self):
        r = get_redis_client()
        devs = len(self.devices)

        print(
            f"[LineBus] start line={self.line_id} name={self.name} devs={devs} "
            f"redis={REDIS_HOST}:{REDIS_PORT}/{REDIS_DB} stream={RAW_STREAM_KEY} "
            f"BUS_TICK={BUS_TICK_SEC}s (~{(1.0/BUS_TICK_SEC) if BUS_TICK_SEC>0 else 0:.1f} pkt/s/line) "
            f"A1_INTERVAL={A1_INTERVAL_SEC}s DROP={DROP_RATE} TIMEOUT_EXTRA={TIMEOUT_EXTRA_SEC}s"
        )

        if devs == 0:
            print(f"[LineBus][{self.line_id}] no devices, exit.")
            return

        next_tick = now_mono()

        while not self._stop.is_set():
            t = now_mono()

            # 到点才“轮询一次”
            if t < next_tick:
                time.sleep(min(0.05, next_tick - t))
                continue

            # 轮到哪个设备
            dev = self.devices[self._cursor]
            self._cursor = (self._cursor + 1) % devs

            # 模拟丢包/超时：丢包就不写入流，并额外等待一段（模拟 wait_response_timeout）
            if DROP_RATE > 0 and random.random() < DROP_RATE:
                # 相当于“发了请求但没收到回帧”
                if TIMEOUT_EXTRA_SEC > 0:
                    next_tick = now_mono() + jitter(BUS_TICK_SEC + TIMEOUT_EXTRA_SEC, BUS_JITTER_SEC)
                else:
                    next_tick = now_mono() + jitter(BUS_TICK_SEC, BUS_JITTER_SEC)
            else:
                # 选择发 A1 还是 A2
                if (t - dev.last_a1_mono) >= A1_INTERVAL_SEC:
                    dev.d_bytes = [random.getrandbits(8) for _ in range(4)]
                    frame = build_a1_resp(dev.serial_id, dev.d_bytes)
                    xadd_raw(
                        r,
                        line_id=self.line_id,
                        serial_id=dev.serial_id,
                        nms_id=dev.nms_id,
                        req_cmd="A1",
                        frame=frame,
                    )
                    dev.last_a1_mono = t
                    self._a1_count += 1
                    self._tx_count += 1
                else:
                    # A2：为了“像现场”，可以不每次都翻 bit；
                    # 这里用 A2_INTERVAL_SEC 做个限速：距离上次A2太近就也允许发，但不翻bit也行。
                    bit_idx = random.choice(RELAY_BIT_INDEXES)
                    old = dev.bits_state.get(bit_idx, 0)
                    new = 1 - old
                    dev.bits_state[bit_idx] = new

                    frame = build_a2_resp(dev.serial_id, dev.d_bytes, bit_idx, new)
                    xadd_raw(
                        r,
                        line_id=self.line_id,
                        serial_id=dev.serial_id,
                        nms_id=dev.nms_id,
                        req_cmd="A2",
                        frame=frame,
                        extra={"bit_index_all": int(bit_idx), "new_value": int(new)},
                    )
                    dev.last_a2_mono = t
                    self._a2_count += 1
                    self._tx_count += 1

                next_tick = now_mono() + jitter(BUS_TICK_SEC, BUS_JITTER_SEC)

            # 日志：每条线打印吞吐 + A1/A2 比例
            nowt = now_mono()
            if (nowt - self._last_log) >= LOG_EVERY_SEC:
                dt = nowt - self._last_log
                rate = self._tx_count / dt if dt > 0 else 0.0
                a1r = self._a1_count / dt if dt > 0 else 0.0
                a2r = self._a2_count / dt if dt > 0 else 0.0
                print(
                    f"[LineBus][{self.line_id}] tx={self._tx_count} ({rate:.1f} pkt/s) "
                    f"A1={self._a1_count}({a1r:.1f}/s) A2={self._a2_count}({a2r:.1f}/s)"
                )
                self._tx_count = 0
                self._a1_count = 0
                self._a2_count = 0
                self._last_log = nowt


def main():
    sims: List[LineBusSimulator] = []
    total_devices = 0

    for line in LINES_CONFIG:
        devs = list(line.get("devices") or [])
        total_devices += len(devs)
        sim = LineBusSimulator(
            line_id=int(line["line_id"]),
            name=str(line.get("name", f"Line-{line['line_id']}")),
            devices=devs,
        )
        sim.start()
        sims.append(sim)

    est_line = (1.0 / BUS_TICK_SEC) if BUS_TICK_SEC > 0 else 0.0
    est_total = est_line * len(sims)
    print(f"[FleetBus] started lines={len(sims)} devices={total_devices} "
          f"estimated_rate≈{est_total:.1f} pkt/s (≈{est_line:.1f} per line)")

    # 每台设备被轮到的平均周期（估算）
    # T_visit ≈ N / rate_line
    for line in LINES_CONFIG:
        n = len(line.get("devices") or [])
        if n > 0 and est_line > 0:
            tvisit = n / est_line
            print(f"[FleetBus] line={line['line_id']} devs={n} avg_visit_period≈{tvisit:.2f}s/device")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[FleetBus] stopping...")
        for s in sims:
            s.stop()
        for s in sims:
            s.join(timeout=1.0)
        print("[FleetBus] bye.")


if __name__ == "__main__":
    main()