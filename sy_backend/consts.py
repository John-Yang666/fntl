from alarm_delay_switch_sy import SY_ALARM_DELAY_SWITCH

#extract_sy_alarms_task.py中使用的告警代码
SY_ALARM_CODES = {42, 43, 52, 53, 62, 63, 66, 67, 70, 71, 73, 75}

#告警含义
SY_ALARM_MEANINGS = {
    0: "设备网管连接中断",
    #40: "一方向故障",
    42: "一方向通道B故障",
    43: "一方向通道A故障",
    #50: "二方向故障",
    52: "二方向通道A故障",
    53: "二方向通道B故障",
    #60: "三方向故障",
    62: "一方向电缆故障(三方向启用时为通道A故障)",
    63: "二方向电缆故障(三方向启用时为通道B故障)",
    66: "一方向为电缆状态",
    67: "二方向为电缆状态",
    70: "主机故障",
    71: "备机故障",
    #72: "同步故障",
    73: "备机未同步",
    #74: "通道故障",
    75: "励磁故障",
    #76: "系统故障",
}

# 通信超时参数（秒）(0号告警延时参数)
COMMUNICATION_TIMEOUT = 10 #生产环境建议设为60

# 告警延时参数（秒）
SY_ALARM_DELAY = {
    42: 5, 
    43: 5, 
    52: 5, 
    53: 5, 
    62: 5, 
    63: 5, 
    66: 5,
    67: 5,
    70: 5, 
    71: 5, 
    73: 5,
    75: 5,
}

SY_ALARM_DELAY2 = {
    42: 5,
    43: 5,
    52: 5,
    53: 5,
    62: 5,
    63: 5,
    66: 5,
    67: 5,
    70: 5,
    71: 5,
    73: 5,
    75: 5,
}

if SY_ALARM_DELAY_SWITCH == 2:
    SY_ALARM_DELAY = SY_ALARM_DELAY2.copy()
else:
    SY_ALARM_DELAY = SY_ALARM_DELAY.copy()

#拓扑图相关参数
TOPOLOGY_TIMEOUT = 10 # 拓扑状态缓存时长（秒）

# sy_receiver / 兼容入口 udp_receiver.py 中使用的参数
LAST_COMMUNICATION_TIME_TIMEOUT = None # 最后通信时间缓存保存时长， summarize_alarms_container中通信超时时清除
SWITCH_DATA_TIMEOUT = 60  # 开关量数据缓存时长，单位秒，即使数据包内容不变也在这个时间间隔发一次数据包给 Celery 避免意外故障。（redis_client.set(f"device_{device_id}_last_switch_packet_hash", packet_hash.encode(), ex=SWITCH_DATA_TIMEOUT)）
HEARTBEAT_TIMEOUT = 3600 # 收到的数据包作为心跳包，如果超过就重启udp_receiver程序
PERIODIC_DEVICE_CACHE_REFRESH_INTERVAL= 60 #周期性设备刷新时间间隔（秒）生产环境可以设置为60秒
