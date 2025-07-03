import asyncio
import threading
import logging
import socket
import queue
import os
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from confluent_kafka import Producer, Consumer

# =======================
# 日志配置
# =======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =======================
# 配置参数
# =======================
HOST_IP = '0.0.0.0' # 监听的IP，如果是多网卡，设置为网管网络中本机的IP
HOST_PORT = 38315
KAFKA_BOOTSTRAP_SERVERS = "localhost:19092"
KAFKA_TOPIC_PUB = 'udp-packets'
KAFKA_TOPIC_SUB = 'udp-commands'

# =======================
# 全局变量
# =======================
udp_packet_count = 0

def load_blocked_ips():
    blocked_ips = set()
    try:
        with open('blocked_ips.txt', 'r') as f:
            for line in f:
                ip = line.strip()
                if ip and not ip.startswith('#'):
                    blocked_ips.add(ip)
    except FileNotFoundError:
        logger.warning("blocked_ips.txt 未找到，已创建空文件")
        open('blocked_ips.txt', 'w').close()
    except Exception as e:
        logger.error(f" 加载屏蔽IP文件失败: {e}")
    return blocked_ips

blocked_ips = load_blocked_ips()

class BlockedIPsHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('blocked_ips.txt'):
            global blocked_ips
            blocked_ips = load_blocked_ips()
            logger.info(" 检测到blocked_ips.txt 更新，已重新加载IP列表")

# =======================
# Kafka Producer
# =======================
producer = Producer({'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS})

def delivery_report(err, msg):
    if err:
        logger.error(f"❌ Kafka 发送失败: {err}")
    else:
        logger.info(f"✅ Kafka 成功发送到 topic={msg.topic()} partition={msg.partition()} offset={msg.offset()}")

# =======================
# 工具函数
# =======================
def calculate_checksum(data):
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder='little')

# =======================
# UDP通信线程
# =======================
class UdpCommunicationThread(threading.Thread):
    def __init__(self, send_queue):
        super().__init__(daemon=True)
        self.send_queue = send_queue
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((HOST_IP, HOST_PORT))
        self.socket.settimeout(1.0)

    def run(self):
        logger.info(f"UDP通信线程已启动，监听 {HOST_IP}:{HOST_PORT}")
        while self.running:
            try:
                target_ip, send_data = self.send_queue.get_nowait()
                self.socket.sendto(send_data, (target_ip, HOST_PORT))
                logger.info(f"已发送数据到 {target_ip}:{HOST_PORT}")
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"发送数据失败: {e}", exc_info=True)

            try:
                data, addr = self.socket.recvfrom(4096)
                source_ip, source_port = addr

                global udp_packet_count
                udp_packet_count += 1
                logger.info(f"收到来自 {source_ip}:{source_port} 的数据包")

                if source_ip in blocked_ips:
                    logger.info(f"忽略被屏蔽的IP: {source_ip}")
                    continue

                frame_head = data[:2]
                frame_tail = data[-2:]
                if frame_head != b'\x7f\x7f' or frame_tail != b'\xf7\xf7':
                    logger.error("丢弃了一个格式错误的数据包：帧头或帧尾无效")
                    continue

                payload = data[2:-4]
                checksum = data[-4:-2]
                calculated_checksum = calculate_checksum(payload)
                if checksum != calculated_checksum:
                    logger.error(
                        f"校验和错误：接收的校验和 {checksum.hex()}，计算的校验和 {calculated_checksum.hex()}"
                    )
                    continue

                function_code = data[3]
                if function_code == 0x01:
                    self.handle_analog_data(data, addr)

                try:
                    message = json.dumps({
                        "ip": source_ip,
                        "data": data.hex()
                    }).encode()
                    producer.produce(KAFKA_TOPIC_PUB, value=message, callback=delivery_report)
                    producer.poll(0)
                except Exception as e:
                    logger.error(f"通过 Kafka 发布数据包失败: {e}", exc_info=True)

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"接收数据时出错: {e}", exc_info=True)

    def stop(self):
        self.running = False
        self.socket.close()
        logger.info("UDP通信线程已停止。")

    def handle_analog_data(self, data, addr):
        try:
            analog_data = data[4:16]
            logger.info(f"Received analog data from {addr}: {analog_data.hex()}")
        except Exception as e:
            logger.error(f"Error handling analog data: {e}", exc_info=True)

# =======================
# Kafka 订阅线程
# =======================
class KafkaSubscriber(threading.Thread):
    def __init__(self, send_queue):
        super().__init__(daemon=True)
        self.send_queue = send_queue
        self.consumer = Consumer({
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'group.id': 'udp-agent-command-consumer',
            'auto.offset.reset': 'latest'
        })
        self.consumer.subscribe([KAFKA_TOPIC_SUB])

    def run(self):
        logger.info("开始监听 Kafka topic 'udp-commands'...")
        while True:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error(f"Kafka consumer error: {msg.error()}")
                continue
            self.handle_message(msg.value())

    def handle_message(self, data):
        try:
            if b'\n' not in data:
                logger.error("Kafka 指令格式错误，缺少换行符。")
                return
            encoded_ip, payload = data.split(b'\n', 1)
            target_ip = encoded_ip.decode().strip()
            if target_ip in blocked_ips:
                logger.info(f"忽略被屏蔽的IP: {target_ip}")
                return
            self.send_queue.put((target_ip, payload))
            logger.info(f"收到 Kafka 指令，目标IP: {target_ip}，数据大小: {len(payload)} 字节")
        except Exception as e:
            logger.error(f"处理 Kafka 指令失败: {e}", exc_info=True)

# =======================
# 主异步函数
# =======================
async def main():
    logger.info("启动主程序...")
    send_queue = queue.Queue()

    observer = Observer()
    observer.schedule(BlockedIPsHandler(), path='.', recursive=False)
    observer.start()

    udp_thread = UdpCommunicationThread(send_queue)
    udp_thread.start()

    kafka_subscriber = KafkaSubscriber(send_queue)
    kafka_subscriber.start()

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        # 停止UDP通信线程
        udp_thread.stop()

        # 关闭 Kafka 消费者
        kafka_subscriber.consumer.close()
        kafka_subscriber.join()

        # 清理 Kafka 生产者
        producer.flush()

        # 停止文件系统观察者
        observer.unschedule_all()  # 取消所有观察
        observer.stop()  # 停止观察者
        observer.join()  # 等待观察者线程结束

        # 记录日志，表明资源已被清理
        logger.info("Kafka 订阅线程已停止。")
        logger.info("UDP通信线程已停止。")
        logger.info("Kafka生产者已停止。")
        logger.info("Kafka消费者已停止。")
        logger.info("文件系统观察者已停止。")
        logger.info("程序退出，已清理资源。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("退出UDP监控工具。")
        producer.flush()
