from alarm_delay_switch_bt import ALARM_DELAY_SWITCH

TESTDATA_CPU_NAMES = ("I-A", "I-B", "II-A", "II-B")
TESTDATA_POWER_MEANINGS = {
    8000: "TestData I系电源板A故障",
    8001: "TestData I系电源板B故障",
    8002: "TestData II系电源板A故障",
    8003: "TestData II系电源板B故障",
    8004: "TestData 网管板到I-CPU板A系485通信中断",
    8005: "TestData 网管板到I-CPU板B系485通信中断",
    8006: "TestData 网管板到II-CPU板A系485通信中断",
    8007: "TestData 网管板到II-CPU板B系485通信中断",
    8010: "TestData I路电源断电",
    8011: "TestData II路电源断电",
}
TESTDATA_CPU_FAULT_MEANINGS = {
    0: "系统自检故障",
    1: "地址码错误",
    2: "1CPU/2CPU之间TTL通信故障(同步)",
    3: "1CPU/2CPU同步数据1错误",
    4: "1CPU/2CPU同步数据2错误",
    5: "1CPU/2CPU状态不一致错误",
    6: "1CPU/2CPU之间开关量输入表决错误",
    7: "1CPU/2CPU之间开关量输出表决错误",
    8: "通信板A单元故障",
    9: "通信板B单元故障",
    10: "通信A数据故障",
    11: "通信A链路故障",
    12: "通信B数据故障",
    13: "通信B链路故障",
    14: "I/O单元动态继电器故障",
    15: "I/O单元故障采集错误",
    16: "A/B系通信故障",
    17: "A/B系通信通道1错误",
    18: "A/B系通信通道2错误",
    19: "A/B系之间心跳信号故障",
    20: "主备机同步错误",
    21: "主备切换错误",
    23: "配置数据信息错误",
    24: "数据风暴",
    25: "通信A闪断",
    26: "通信B闪断",
    27: "通信A预处理发送端口故障",
    28: "通信B预处理发送端口故障",
    29: "通信A预处理发送端口错误",
    30: "通信B预处理发送端口错误",
    40: "网管通信A中断故障",
    41: "网管通信B中断故障",
}
TESTDATA_TXB_MEANINGS = {
    0: "TXBA 系统自检故障",
    1: "TXBA Los故障",
    2: "TXBB 系统自检故障",
    3: "TXBB Los故障",
}
TESTDATA_ALARM_CODES = (
    tuple(range(8000, 8008))
    + tuple(range(8010, 8012))
    + tuple(8200 + cpu * 100 + code for cpu in range(4) for code in range(42))
    + tuple(8400 + cpu * 10 + idx for cpu in range(4) for idx in range(4))
    + tuple(8500 + cpu for cpu in range(4))
    + tuple(8510 + cpu for cpu in range(4))
)

# 普通 BT 开关量包使用的告警代码。TestData 告警码不要放进这里，
# 否则每个普通包都会额外遍历大量越界码。
BT_ALARM_CODES = {
    40, 41, 42, 43, 44, 45, 46, 47, 70, 71, 72, 74, 110, 111, 112, 114, 150, 162, 164, 176,
    190, 240, 252, 254, 266, 280, 330, 342, 344, 356, 370, 420, 432, 434, 446, 460,
}

# 系统全量告警代码，用于配置、回显和兼容老引用。
ALARM_CODES = {
    *BT_ALARM_CODES,
    *TESTDATA_ALARM_CODES,
}

#告警含义
ALARM_MEANINGS = {
    0: "设备网管连接中断",
    40: "1方向电源板A状态",
    41: "1方向电源板B状态",
    42: "2方向电源板A状态",
    43: "2方向电源板B状态",
    44: "1方向CPU板A通信状态",
    45: "1方向CPU板B通信状态",
    46: "2方向CPU板A通信状态",
    47: "2方向CPU板B通信状态",
    70: "提醒：1方向QHJ状态与邻站不同",
    71: "1方向电缆状态",
    72: "提醒：1方向切换模式与邻站不同",
    74: "接口箱1方向切换板故障",
    110: "提醒：2方向QHJ状态与邻站不同",
    111: "2方向电缆状态",
    112: "提醒：2方向切换模式与邻站不同",
    114: "接口箱2方向切换板故障",
    150: "邻站未正确输出（一方向CPU1）",
    162: "站间A通道或通信板故障（一方向A系）",
    164: "站间B通道或通信板故障（一方向A系）",
    176: "驱动模块故障（一方向CPU1）",
    190: "CPU板离线（一方向A系）",
    240: "邻站未正确输出（一方向CPU2）",
    252: "站间A通道或通信板故障（一方向B系）",
    254: "站间B通道或通信板故障（一方向B系）",
    266: "驱动模块故障（一方向CPU2）",
    280: "CPU板离线（一方向B系）",
    330: "邻站未正确输出（二方向CPU1）",
    342: "站间A通道或通信板故障（二方向A系）",
    344: "站间B通道或通信板故障（二方向A系）",
    356: "驱动模块故障（二方向CPU1）",
    370: "CPU板离线（二方向A系）",
    420: "邻站未正确输出（二方向CPU2）",
    432: "站间A通道或通信板故障（二方向B系）",
    434: "站间B通道或通信板故障（二方向B系）",
    446: "驱动模块故障（二方向CPU2）",
    460: "CPU板离线（二方向B系）",
}

ALARM_MEANINGS.update(TESTDATA_POWER_MEANINGS)
for _cpu_index, _cpu_name in enumerate(TESTDATA_CPU_NAMES):
    for _code in range(42):
        ALARM_MEANINGS[8200 + _cpu_index * 100 + _code] = (
            f"TestData {_cpu_name}系{TESTDATA_CPU_FAULT_MEANINGS.get(_code, f'故障码{_code:02d}')}"
        )
    for _txb_index, _text in TESTDATA_TXB_MEANINGS.items():
        ALARM_MEANINGS[8400 + _cpu_index * 10 + _txb_index] = f"TestData {_cpu_name}系{_text}"
    ALARM_MEANINGS[8500 + _cpu_index] = f"TestData {_cpu_name}系监测单元异常"
    ALARM_MEANINGS[8510 + _cpu_index] = f"TestData {_cpu_name}系监测单元复位"

# 通信超时参数（秒）(0号告警延时参数)
COMMUNICATION_TIMEOUT = 60 #60

# 告警延时参数（秒）
ALARM_DELAY = {
    40: 5, 41: 5, 42: 5, 43: 5, 44: 5, 45: 5, 46: 5, 47: 5,
    70: 60, 110: 60,
    71: 600, 111: 600,
    72: 15, 112: 15, 
    74: 5,  114: 5,
    162: 5, 164: 5, 252: 5, 254: 5, 342: 5, 344: 5, 432: 5, 434: 5,
    176: 5, 266: 5, 356: 5, 446: 5,
    150: 5, 240: 5, 330: 5, 420: 5, 
    190: 5, 280: 5, 370: 5, 460: 5,   
}
ALARM_DELAY.update({code: 5 for code in TESTDATA_ALARM_CODES})

ALARM_DELAY2 = {
    40: 5, 41: 5, 42: 5, 43: 5, 44: 5, 45: 5, 46: 5, 47: 5,
    70: 60, 110: 60,
    71: 600, 111: 600,
    72: 15, 112: 15,
    74: 5, 114: 5,
    162: 5, 164: 5, 252: 5, 254: 5, 342: 5, 344: 5, 432: 5, 434: 5,
    176: 5, 266: 5, 356: 5, 446: 5,
    150: 5, 240: 5, 330: 5, 420: 5,
    190: 5, 280: 5, 370: 5, 460: 5,
}
ALARM_DELAY2.update({code: 5 for code in TESTDATA_ALARM_CODES})

if ALARM_DELAY_SWITCH == 2:
    ALARM_DELAY = ALARM_DELAY2.copy()
else:
    ALARM_DELAY = ALARM_DELAY.copy()

#拓扑图相关参数
TOPOLOGY_TIMEOUT = 10 # 拓扑状态缓存时长（秒）

#udp_receiver.py中使用的参数
LAST_COMMUNICATION_TIME_TIMEOUT = None # 最后通信时间缓存保存时长， summarize_alarms_container中通信超时时清除
SWITCH_DATA_TIMEOUT = 60  # 开关量数据缓存时长，单位秒，即使数据包内容不变也在这个时间间隔发一次数据包给 Celery 避免意外故障。（redis_client.set(f"device_{device_id}_last_switch_packet_hash", packet_hash.encode(), ex=SWITCH_DATA_TIMEOUT)）
HEARTBEAT_TIMEOUT = 300 # 收到的数据包作为心跳包，如果超过就重启udp_receiver程序
PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL= 60 #周期性设备刷新时间间隔（秒）生产环境可以设置为60秒
