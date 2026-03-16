import socket
import threading
import logging
from django.utils import timezone # type: ignore
from django.core.cache import cache # type: ignore
from myapp.models import Device
from myapp.tasks import process_switch_data
#from myapp.tasks import process_analog_data

logger = logging.getLogger(__name__)

# 包处理计数器
udp_packet_count = 0
udp_packet_count_lock = threading.Lock()

def get_device_by_ip(ip_address):
    cache_key = f"device_{ip_address}"
    device = cache.get(cache_key)
    if not device:
        try:
            device = Device.objects.get(ip_address=ip_address)
            cache.set(cache_key, device, timeout=60)  # 缓存1minute
        except Device.DoesNotExist:
            logger.error(f"No device found for IP address {ip_address}")
            return None
    return device

def handle_packet(data, addr):
    #t0 = 300 #设备离线告警持续时间(秒)#取消时间限制，不然时间到了会产生告警开始记录
    global udp_packet_count
    
    #Check if the device IP is in the database
    ip_address = addr[0]
    device = get_device_by_ip(ip_address)
    if not device:
        return

    device_id = device.device_id

    frame_head = data[0:2]
    frame_tail = data[-2:]

    if frame_head == b'\x7F\x7F' and frame_tail == b'\xF7\xF7':
        current_time = timezone.now()
        # cache.set(f"device_{device_id}_last_communication_time", current_time, timeout=None)
        if len(data) == 54:
            cache.set(f"device_{device_id}_last_communication_time", current_time, timeout=None)
            # Check if switch_status is in the cache
            if cache.get(f"device_{device_id}_switch_status"):
                # Check if data has changed for this IP address
                last_udp_switch_data_from_this_id = cache.get(f"device_{device_id}_last_udp_switch_data")
                if last_udp_switch_data_from_this_id == data:
                    # Data has not changed, skip processing
                    print('skipping unchanged udp_switch_data from device:', device_id)
                    with udp_packet_count_lock:
                        udp_packet_count += 1
                    return

            process_switch_data.delay(device_id, data, str(current_time))
            # Update the last data from this IP address
            cache.set(f"device_{device_id}_last_udp_switch_data", data, timeout=None)
        elif len(data) == 20:
            #process_analog_data.delay(device_id, data, str(current_time))
            pass
        else:
            logger.error(f"Unknown data length ({len(data)}) from IP address {ip_address}")
    else:
        logger.error(f"Unknown packet type from IP address {ip_address}")

    with udp_packet_count_lock:
        udp_packet_count += 1

def forward_cached_packet(sock):
    target_port = cache.get('udp_target_port')
    if target_port:
        packet = cache.get('udp_packet')
        target_ip = cache.get('udp_target_ip')
        if packet and target_ip:
            try:
                sock.sendto(packet, (target_ip, int(target_port)))
                cache.delete('udp_packet')
                cache.delete('udp_target_ip')
                cache.delete('udp_target_port')
            except socket.error as e:
                logger.error(f"Socket error while forwarding packet: {e}")

def print_packet_count():
    global udp_packet_count
    while True:
        threading.Event().wait(1)  # 等待一秒钟
        with udp_packet_count_lock:
            print(f"Processed {udp_packet_count} udp_switch_packets in the last second")
            udp_packet_count = 0

def udp_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 38316))
    logger.info("UDP Receiver started on port 38316")

    # 启动计数线程
    threading.Thread(target=print_packet_count, daemon=True).start()

    while True:
        forward_cached_packet(sock)

        try:
            data, addr = sock.recvfrom(1024)
            print("From IP:", addr[0])  # 打印真实来源IP地址
            handle_packet(data, addr)
        except socket.error as e:
            logger.error(f"Socket error: {e}")

if __name__ == "__main__":
    udp_receiver()