#注意事项：
#处理MQTT消息时的异常捕获：确保在所有可能出错的地方都进行异常捕获。
#在Django启动时启动MQTT客户端：确保MQTT客户端在Django启动时正确启动。
#=================================================================
import paho.mqtt.client as mqtt
from myapp.models import Device
from myapp.tasks import process_switch_data, process_analog_data
import logging
import json
from django.core.cache import cache
from django.utils import timezone
#import threading
#from django.apps import AppConfig

logger = logging.getLogger(__name__)

# MQTT broker地址
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_SWITCH = "devices/switch"
MQTT_TOPIC_ANALOG = "devices/analog"

def on_connect(client, userdata, flags, rc):#在客户端连接到MQTT broker时调用，订阅相关主题。
    if rc == 0:
        logger.info("Connected to MQTT Broker!")
        client.subscribe(MQTT_TOPIC_SWITCH)
        client.subscribe(MQTT_TOPIC_ANALOG)
    else:
        logger.error(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):#在接收到消息时调用，解析消息并处理。
    try:
        payload = json.loads(msg.payload)#解析消息负载
        ip_address = payload.get("ip_address")#从消息负载中提取IP地址
        data = bytes.fromhex(payload.get("data"))

        #使用 Device.objects.get(ip_address=ip_address) 根据提取到的IP地址在数据库中查找设备对象
        try:
            device = Device.objects.get(ip_address=ip_address)
            device_id = device.device_id
        except Device.DoesNotExist:
            logger.error(f"No device found for IP address {ip_address}")
            return

        frame_head = data[0:2]
        frame_tail = data[-2:]

        if frame_head == b'\x7F\x7F' and frame_tail == b'\xF7\xF7':
            # 记录最新一次接收数据时间
            cache.set(f"device_{device_id}_last_communication_time", timezone.now(), timeout=60*5)#此处决定设备网络连接中断告警最长持续时间
            if len(data) == 54:
                process_switch_data.delay(device_id, data)
            elif len(data) == 20:
                process_analog_data.delay(device_id, data)
            else:
                logger.error(f"Unknown data length ({len(data)}) from IP address {ip_address}")
        else:
            logger.error(f"Unknown packet type from IP address {ip_address}")
    except Exception as e:
        logger.error(f"Error processing message: {e}")

# 初始化 MQTT 客户端
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

def start_mqtt():#负责连接到MQTT broker并启动MQTT客户端的循环。
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)#客户端使用 TCP 连接到指定的 MQTT Broker 的地址和端口
        client.loop_start()
    except Exception as e:
        logger.error(f"Failed to start MQTT client: {e}")

# 启动配置在apps.py中，在Django启动时启动MQTT客户端