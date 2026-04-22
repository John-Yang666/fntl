# `sy_agent` 配置说明

本文档说明 `sy_agent` 外部 `config.json` 的各配置项含义、默认值作用、常见调整场景，以及 [`sy_agent_ui.py`](/Users/yangzijiang/BT_NMS/sy_agent/sy_agent_ui.py) 使用这些配置时的注意事项。字段结构与仓库中的遗留 [`config.py`](/Users/yangzijiang/BT_NMS/sy_agent/config.py) 保持兼容，但受保护部署默认只使用 JSON。

## 配置来源

`sy_agent` 运行时配置有两种主要来源：

1. 直接运行 [`sy_agent.py`](/Users/yangzijiang/BT_NMS/sy_agent/sy_agent.py) 时，默认读取 `%ProgramData%\BT_NMS\sy_agent\config.json`。
2. 通过 [`sy_agent_ui.py`](/Users/yangzijiang/BT_NMS/sy_agent/sy_agent_ui.py) 启动时，UI 会把当前配置导出到 `%ProgramData%\BT_NMS\sy_agent\runtime_config.json`，再通过环境变量 `SY_AGENT_CONFIG_JSON` 让 `sy_agent` 优先读取该 JSON。

也就是说：

- `config.json` 是默认配置源
- `sy_agent_ui.sqlite3` 是桌面 UI 的持久化配置源
- `runtime_config.json` 是 UI 启动子进程时使用的临时运行时配置

## 顶层结构

`CONFIG` 顶层包含这些分组：

- `redis`
- `stream`
- `cmd`
- `time_sync`
- `a2_burst`
- `serial`
- `probe`
- `ui`
- `debug_tuning`
- `lines`

---

## `redis`

Redis 连接参数。`sy_agent` 通过它读写 Redis Stream、去重键、DLQ 和命令状态键。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | `str` | `localhost` | Redis 主机地址 |
| `port` | `int` | `36380` | Redis 端口 |
| `db` | `int` | `0` | Redis 数据库编号 |

建议：

- 一般只在部署到其他主机或 Redis 端口变化时修改。
- 如果是同机部署，通常保持默认。

---

## `stream`

Redis Stream 名称和消费参数。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `raw_stream` | `str` | `sy.raw` | 原始采集数据写入的 Stream 名称 |
| `raw_stream_maxlen` | `int` | `200000` | 原始数据 Stream 近似最大长度 |
| `cmd_stream` | `str` | `sy-serial-commands` | 下发给 `sy_agent` 的命令 Stream |
| `cmd_group` | `str` | `sy_agent_cmd_group` | 命令消费组名 |
| `cmd_consumer` | `str` | `sy-agent-1` | 当前 agent 的 consumer 名 |
| `cmd_block_ms` | `int` | `1000` | `XREADGROUP` 阻塞读取时长，毫秒 |
| `cmd_count` | `int` | `10` | 每次读取的命令条数上限 |

建议：

- 多实例时，`cmd_consumer` 应保证唯一。
- `cmd_group` 通常整套系统固定，不建议频繁修改。
- `raw_stream_maxlen` 过小会导致历史原始数据保留不足，过大则 Redis 占用增加。

---

## `cmd`

命令处理、完成标记、DLQ、重试、无回帧命令确认等配置。

### 基础命令流 / DLQ

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `dlq_stream` | `str` | `sy-serial-commands.dlq` | 死信队列 Stream 名称 |
| `dlq_maxlen` | `int` | `50000` | DLQ 近似最大长度 |
| `done_key_prefix` | `str` | `sy:cmd_done:` | 命令完成标记键前缀 |
| `done_ttl_sec` | `int` | `3600` | Redis 中命令完成标记保留时间 |
| `done_local_ttl_sec` | `int` | `600` | 本地内存中的短期完成标记保留时间 |
| `dlq_dedupe_prefix` | `str` | `sy:cmd_dlq:` | DLQ 去重键前缀 |
| `dlq_dedupe_ttl_sec` | `int` | `600` | 同类坏消息短时间去重窗口 |

说明：

- `done_*` 用于防止同一命令被重复执行。
- `done_local_ttl_sec` 是 Redis 短暂抖动时的本地兜底，不替代 Redis。
- `dlq_dedupe_*` 用于避免某类持续性故障疯狂刷 DLQ。

### 重试 / inflight

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `try_key_prefix` | `str` | `sy:cmd_try:` | 命令重试次数键前缀 |
| `try_ttl_sec` | `int` | `3600` | 重试次数键保留时间 |
| `max_tries` | `int` | `20` | 单条命令最大尝试次数 |
| `inflight_ttl_sec` | `float` | `3.0` | 命令 inflight 保护窗口，防止过快重复处理 |

说明：

- `max_tries` 太小会导致偶发故障时过早入 DLQ。
- `max_tries` 太大则会让坏命令长时间占资源。
- `inflight_ttl_sec` 一般不需要大改，它主要防止重复 claim 或并发重复处理。

### 无回帧 / BB / CC 相关

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `no_resp_enable` | `bool` | `True` | 是否启用“无回帧命令”特殊处理 |
| `confirm_delay_sec` | `float` | `0.08` | 无回帧命令发送后，开始确认前的等待时间 |
| `confirm_timeout_sec` | `float` | `0.25` | 无回帧命令确认超时 |
| `confirm_a1` | `bool` | `True` | 无回帧命令确认时是否在 `A2` 后补一次 `A1` |
| `bb_cmd_retries` | `int` | `3` | `BB` 未收到 `0x05` 确认时的额外重发次数 |
| `no_resp_cmds` | `list[str]` | `["CC"]` | 按“无回帧命令”处理的请求命令列表 |

关键说明：

- 当前实现里，`BB` 已经按“等待 `0x05` 执行确认”处理，不应再放进 `no_resp_cmds`。
- 默认只有 `CC` 仍被视为无回帧命令。
- `bb_cmd_retries=3` 表示首发失败后再额外重发 3 次，总共最多发 4 次。

建议：

- 如果现场 `BB` 偶尔确认丢失，可以适当把 `bb_cmd_retries` 增到 `4` 或 `5`。
- `confirm_a1=True` 会让确认更稳，但也会多一次完整状态读取。

---

## `time_sync`

时间同步（`AA`）配置。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | `bool` | `False` | 是否启用周期性时间同步 |
| `interval_sec` | `float` | `3600` | 时间同步间隔，秒 |

说明：

- 开启后，agent 会按周期向线路发送 `AA`。
- 如果现场暂时不需要时间同步，保持关闭即可。

---

## `a2_burst`

`A2` 突发补读配置。用于收到 `A2` 正常返回后，再在短时间窗口内做额外 `A2` 读取。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | `bool` | `True` | 是否启用 `A2 burst` |
| `max` | `int` | `3` | 一次 burst 最多额外发几次 `A2` |
| `timeout_sec` | `float` | `0.06` | 单次 burst 等待超时 |
| `budget_sec` | `float` | `0.16` | 整个 burst 总预算时间 |

适用场景：

- 希望更及时接住变化量事件。
- 不想完全依赖单次 `A2` 返回。

风险：

- 设得过激会增加总线压力。
- 若现场链路已经很脆弱，过高的 burst 会加重抖动。

---

## `serial`

串口默认参数。每条线路未单独指定时使用这里的默认值。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `default_baudrate` | `int` | `19200` | 默认波特率 |
| `timeout` | `float` | `0.0` | `pyserial` 读超时 |

说明：

- 代码里的数据位 / 校验位 / 停止位是固定的：`8 data bits / odd parity / 2 stop bits`。
- 这里只控制默认波特率和 timeout。
- 每条 `line` 也可以单独写自己的 `baudrate` 和 `timeout`。

---

## `probe`

后台健康探测配置。用于低频探测非优先侧链路状态，不直接改业务选路。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | `bool` | `True` | 是否启用后台探测 |
| `interval_sec` | `float` | `45.0` | 探测周期 |
| `timeout_sec` | `float` | `0.12` | 单次探测超时 |
| `queue_threshold` | `int` | `32` | 接收队列积压超过该值时跳过探测 |
| `cooldown_after_fault_sec` | `float` | `15.0` | 刚发生故障后，暂停探测的冷却时间 |

说明：

- 探测主要为了判断备用链路最近是否还能通。
- 它不会直接把 `last_good_side` 改掉。
- 如果总线很忙、队列积压，探测会主动跳过。

建议：

- `interval_sec` 一般保持 `30` 到 `60` 秒比较稳。
- 如果现场链路非常敏感，不建议把探测频率调得太高。

---

## `ui`

终端版 `sy_agent` 的控制台显示配置，不是桌面版 `sy_agent_ui` 的窗口参数。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `mode` | `str` | `dashboard` | 终端显示模式，可选 `dashboard` 或 `plain` |
| `refresh_sec` | `float` | `1.0` | dashboard 刷新周期 |
| `event_buffer_size` | `int` | `20` | recent events 缓冲条数 |
| `ansi` | `str` | `auto` | ANSI 控制模式，可选 `auto` / `always` / `never` |

说明：

- `dashboard` 是单屏刷新模式。
- `plain` 是普通文本日志模式，适合被桌面 UI 接管或做日志采集。
- `sy_agent_ui` 启动 `sy_agent` 时会强制把运行时 `ui.mode` 改成 `plain`，避免 ANSI dashboard 干扰日志解析。

---

## `debug_tuning`

这一组是运行时调优参数。大多数项目上线后只会改其中少数几项，其他保持默认。

### 收发节奏 / 响应等待

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `AFTER_WRITE_SLEEP_SEC` | `float` | `0.035` | 发完串口请求后附加等待时间 |
| `ENABLE_AFTER_WRITE_SLEEP` | `bool` | `True` | 是否启用发后等待 |
| `WAIT_RESPONSE_TIMEOUT_SEC` | `float` | `0.20` | 等待响应帧超时 |

说明：

- 这是最常调的现场参数之一。
- 如果普遍超时，可先适度增大 `WAIT_RESPONSE_TIMEOUT_SEC`。
- 如果现场对时序特别敏感，也可能需要调 `AFTER_WRITE_SLEEP_SEC`。

### 自动睡眠自适应

这些参数控制 `ADAPT` 自适应发后等待逻辑。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `AUTO_SLEEP_ENABLE` | `bool` | `True` | 是否启用自动睡眠调节 |
| `AUTO_SLEEP_WINDOW` | `int` | `80` | 统计窗口大小 |
| `AUTO_SLEEP_PCTL` | `int` | `95` | 响应延迟分位数 |
| `AUTO_SLEEP_MARGIN_SEC` | `float` | `0.005` | 安全边际 |
| `AUTO_SLEEP_MIN_SEC` | `float` | `0.010` | 最小睡眠 |
| `AUTO_SLEEP_MAX_SEC` | `float` | `0.080` | 最大睡眠 |
| `AUTO_SLEEP_UPDATE_EVERY` | `int` | `8` | 每多少次响应更新一次估计 |
| `AUTO_SLEEP_PRINT_EVERY_SEC` | `float` | `5.0` | 调试打印周期 |
| `AUTO_SLEEP_NO_RESP_BUMP_SEC` | `float` | `0.005` | 超时时增加的等待量 |
| `AUTO_SLEEP_NO_RESP_STREAK` | `int` | `2` | 连续超时多少次后触发 bump |
| `AUTO_SLEEP_NO_RESP_COOLDOWN_SEC` | `float` | `0.8` | 超时 bump 冷却时间 |
| `AUTO_SLEEP_DECAY_OK_STREAK` | `int` | `40` | 连续成功多少次后开始回落 |
| `AUTO_SLEEP_DECAY_STEP_SEC` | `float` | `0.002` | 每次回落步长 |

说明：

- 如果你不想让 agent 自己调节发后等待，可以直接把 `AUTO_SLEEP_ENABLE` 关掉。
- 正常情况下，不建议频繁微调这组参数。

### RTS 控制

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `RTS_TOGGLE` | `bool` | `False` | 是否启用 RTS 收发切换 |
| `RTS_TX_LEVEL` | `int` | `1` | 发送时 RTS 电平 |
| `RTS_RX_LEVEL` | `int` | `0` | 接收时 RTS 电平 |
| `RTS_PRE_DELAY_SEC` | `float` | `0.001` | 拉 RTS 到发送态后的预延时 |
| `RTS_POST_DELAY_SEC` | `float` | `0.002` | 发送完成后的后延时 |

适用场景：

- 某些 RS-485 或外部收发控制场景才需要。
- 普通串口部署通常保持关闭。

### Redis / 串口重连

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `REDIS_RETRY_MIN_SEC` | `float` | `1.0` | Redis 最小重试退避 |
| `REDIS_RETRY_MAX_SEC` | `float` | `10.0` | Redis 最大重试退避 |
| `REDIS_DOWN_PAUSE_SEC` | `float` | `0.5` | Redis DOWN 时轮询线程暂停时间 |
| `SERIAL_RETRY_MIN_SEC` | `float` | `1.0` | 串口最小重试退避 |
| `SERIAL_RETRY_MAX_SEC` | `float` | `30.0` | 串口最大重试退避 |

说明：

- 这些值越小，恢复更积极；但过小会导致异常时疯狂重试。

### RX 故障 / 看门狗

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `SERIAL_RX_ERROR_LIMIT` | `int` | `5` | 接收线程连续错误容忍数 |
| `RX_THREAD_DEAD_REOPEN` | `bool` | `True` | 接收线程异常后是否触发重开 |
| `STALL_WATCHDOG_ENABLE` | `bool` | `True` | 是否启用无帧看门狗 |
| `STALL_NOFRAME_SEC` | `float` | `15.0` | 多久没收到有效帧视为卡死 |
| `STALL_GRACE_AFTER_OPEN_SEC` | `float` | `2.0` | 刚开口后的宽限时间 |
| `STALL_COOLDOWN_SEC` | `float` | `15.0` | 看门狗动作冷却时间 |

说明：

- 拔线但 COM 口仍存在时，`Port` 可能还是 `open`，这组参数负责把“长时间没帧”的情况识别为坏链路并尝试重开。

### 日志 / 状态打印

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `LOG_SEND` | `bool` | `False` | 是否打印发送日志 |
| `LOG_RECV_OK` | `bool` | `False` | 是否打印每条成功回帧日志 |
| `LOG_NO_RESP` | `bool` | `True` | 是否打印无响应日志 |
| `LOG_RX_STATS` | `bool` | `True` | 是否打印 RX 统计日志 |
| `LOG_MATCH_DETAIL` | `bool` | `False` | 是否打印匹配细节 |
| `LOG_REDIS_STATE` | `bool` | `True` | 是否打印 Redis 状态 |
| `LOG_PORT_STATE` | `bool` | `True` | 是否打印端口状态 |
| `STATUS_PRINT_EVERY_SEC` | `float` | `10.0` | 周期状态打印间隔 |

建议：

- 生产环境不要随便开 `LOG_RECV_OK`，否则日志量会非常大。
- 现场排障时可以临时开 `LOG_SEND` 或 `LOG_MATCH_DETAIL`，排完后再关。

### 接收缓冲 / pending reclaim

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `MAX_READ_ONCE` | `int` | `4096` | 单次串口读取上限 |
| `MAX_SOFTBUF` | `int` | `8192` | 软件缓冲区上限 |
| `PENDING_RETRY_ENABLE` | `bool` | `True` | 是否回收 Redis pending 命令 |
| `PENDING_MIN_IDLE_MS` | `int` | `5000` | claim 前最小空闲时间 |
| `PENDING_CLAIM_EVERY_SEC` | `float` | `2.0` | pending 回收周期 |
| `PENDING_CLAIM_COUNT` | `int` | `20` | 每次回收条数 |

说明：

- 这一组主要影响 Redis command stream 的消费恢复能力。
- 一般不需要大改，除非命令堆积或切换 consumer 后恢复不及时。

---

## `lines`

线路配置列表。每一项对应一个 `LinePoller` 实例。

示例：

```python
{
    "line_id": 1,
    "name": "Line-1",
    "head_port": "COM3",
    "tail_port": "NONE",
    "baudrate": 19200,
    "timeout": 0.0,
    "devices": [
        {"serial_id": 1, "nms_id": 1, "a1_interval": 5.0},
        {"serial_id": 2, "nms_id": 2, "a1_interval": 5.0},
    ],
}
```

### 线路字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `line_id` | `int` | 线路编号，UI 和日志里会用到 |
| `name` | `str` | 线路名称 |
| `head_port` | `str` | 头端串口名，例如 `COM3` |
| `tail_port` | `str` | 尾端串口名；若不用可填 `NONE` |
| `ring_mode` | `bool` | 是否按“单侧发、双侧收”成环模式处理 |
| `baudrate` | `int` | 本线路波特率，覆盖 `serial.default_baudrate` |
| `timeout` | `float` | 本线路串口 timeout，覆盖 `serial.timeout` |
| `devices` | `list[dict]` | 该线路上的设备列表 |

`ring_mode` 说明：

- 设为 `True` 时，按成环模式处理：单侧发、双侧收、窗口化匹配、镜像帧去重。
- 如果未显式配置，当前代码会在 `head_port` 和 `tail_port` 都是有效串口时自动启用 ring 行为。
- 如果不是成环现场，建议明确写 `False`。

### 设备字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `serial_id` | `int` | 设备在线路协议里的地址，用于真正发帧 |
| `nms_id` | `int` | 网管侧设备 ID，用于命令路由和上层映射 |
| `a1_interval` | `float` | 完整 `A1` 轮询周期，秒 |

说明：

- `serial_id` 是串口协议地址，`nms_id` 是系统业务 ID，这两个不要混。
- 如果命令是按 `nms_id` 下发的，最终会被映射回 `serial_id` 去发串口帧。
- `a1_interval` 越小，完整状态轮询越频繁；越大则更依赖 `A2`。

---

## 常见调整建议

### 1. 普遍超时很多

优先看：

- `debug_tuning.WAIT_RESPONSE_TIMEOUT_SEC`
- `debug_tuning.AFTER_WRITE_SLEEP_SEC`
- `debug_tuning.AUTO_SLEEP_ENABLE`
- `lines[*].a1_interval`

建议顺序：

1. 先适当放宽 `WAIT_RESPONSE_TIMEOUT_SEC`
2. 仍不稳再微调 `AFTER_WRITE_SLEEP_SEC`
3. 如果自动调节不稳定，再考虑暂时关闭 `AUTO_SLEEP_ENABLE`

### 2. `BB` 控制偶尔执行了但确认弱

优先看：

- `cmd.bb_cmd_retries`
- `cmd.confirm_delay_sec`
- `cmd.confirm_timeout_sec`
- `cmd.confirm_a1`

### 3. 日志太多

优先看：

- `debug_tuning.LOG_RECV_OK`
- `debug_tuning.LOG_SEND`
- `debug_tuning.LOG_MATCH_DETAIL`
- `debug_tuning.STATUS_PRINT_EVERY_SEC`

### 4. 备用侧想保留健康探测但不想太频繁

优先看：

- `probe.interval_sec`
- `probe.timeout_sec`
- `probe.queue_threshold`
- `probe.cooldown_after_fault_sec`

---

## 修改配置时的建议

- 先改一组参数，不要一次改很多组。
- 涉及时序的参数尽量小步调整，例如 `0.02 -> 0.03 -> 0.04`。
- 现场稳定后，把临时排障打开的详细日志再关掉。
- 通过桌面版修改后，若要复制到其他设备，优先用 UI 的“导出 JSON 配置”统一分发；`.py` 仅保留给开发兼容场景。
