import asyncio
import threading
import logging
import socket
import queue
import redis
from watchdog.observers  import Observer 
from watchdog.events  import FileSystemEventHandler 

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
HOST_IP = '0.0.0.0'  # 监听的IP地址
HOST_PORT = 38315    # 监听的端口
REDIS_HOST = "localhost"  # Redis服务器地址
REDIS_PORT = 6379         # Redis端口

# =======================
# 全局变量
# =======================
udp_packet_count = 0        # UDP数据包计数器

# blocked_ips初始化：
def load_blocked_ips():
    blocked_ips = set()
    try:
        with open('blocked_ips.txt',  'r') as f:
            for line in f:
                ip = line.strip() 
                if ip and not ip.startswith('#'):   # 支持注释行（以#开头）
                    blocked_ips.add(ip) 
    except FileNotFoundError:
        logger.warning("blocked_ips.txt 未找到，已创建空文件")
        open('blocked_ips.txt',  'w').close()
    except Exception as e:
        logger.error(f" 加载屏蔽IP文件失败: {e}")
    return blocked_ips 
 
blocked_ips = load_blocked_ips()  # 替换原blocked_ips = set()

#动态更新机制
class BlockedIPsHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('blocked_ips.txt'): 
            global blocked_ips 
            blocked_ips = load_blocked_ips()
            logger.info(" 检测到blocked_ips.txt 更新，已重新加载IP列表")

# =======================
# Redis连接池
# =======================
redis_pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=False  # 保持数据为字节串
)

# =======================
# 工具函数
# =======================
def calculate_checksum(data):
    """
    计算校验和。
    """
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder='little')

# =======================
# UDP通信线程
# =======================
class UdpCommunicationThread(threading.Thread):
    """
    一个专用线程，用于处理UDP的发送和接收操作。
    """
    def __init__(self, send_queue):
        super().__init__(daemon=True)
        self.send_queue = send_queue
        self.running = True

        # 初始化UDP套接字
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((HOST_IP, HOST_PORT))
        self.socket.settimeout(1.0)  # 设置1秒超时以实现非阻塞接收

    def run(self):
        logger.info(f"UDP通信线程已启动，监听 {HOST_IP}:{HOST_PORT}")
        while self.running:
            # 处理发送数据
            try:
                target_ip, send_data = self.send_queue.get_nowait()
                self.socket.sendto(send_data, (target_ip, HOST_PORT))
                logger.info(f"已发送数据到 {target_ip}:{HOST_PORT}")
            except queue.Empty:
                pass  # 没有数据需要发送
            except Exception as e:
                logger.error(f"发送数据失败: {e}", exc_info=True)

            # 处理接收数据
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

                # 如果是模拟量数据
                function_code = data[3]
                if function_code == 0x01:
                    self.handle_analog_data(data, addr)

                # 将接收到的数据包发布到Redis的 'udp_packets' 频道
                try:
                    redis_client = redis.Redis(connection_pool=redis_pool)
                    forward_packet = data
                    redis_client.publish('udp_packets', forward_packet)
                    logger.info(
                        f"已将数据包发布到Redis频道 'udp_packets'，数据包大小: {len(data)} 字节，来源IP: {source_ip}"
                    )
                except Exception as e:
                    logger.error(f"通过Redis发布数据包失败: {e}", exc_info=True)

            except socket.timeout:
                continue  # 在超时时间内未接收到数据
            except Exception as e:
                logger.error(f"接收数据时出错: {e}", exc_info=True)

    def stop(self):
        """
        停止通信线程。
        """
        self.running = False
        self.socket.close()
        logger.info("UDP通信线程已停止。")

    def handle_analog_data(self, data, addr):
        """ 处理接收到的模拟量数据包 """
        try:
            # 模拟量数据提取
            # 假设模拟量数据从第4字节开始，按需修改
            analog_data = data[4:16]  # 这个范围可以根据协议调整
            logger.info(f"Received analog data from {addr}: {analog_data.hex()}")
            
            # 将模拟量数据发布到Redis的 'analog_data' 频道
            redis_client = redis.Redis(connection_pool=redis_pool)
            redis_client.publish('analog_data', analog_data)
            logger.info(f"Published analog data to Redis channel 'analog_data': {analog_data.hex()}")

        except Exception as e:
            logger.error(f"Error handling analog data: {e}", exc_info=True)

# =======================
# Redis订阅者类
# =======================
class RedisSubscriber:
    """
    订阅Redis频道并处理接收到的消息。
    """
    def __init__(self, send_queue):
        self.redis_client = redis.Redis(connection_pool=redis_pool)
        self.pubsub = self.redis_client.pubsub()
        self.pubsub.subscribe('udp_commands')  # 订阅 'udp_commands' 频道
        self.send_queue = send_queue

    def listen(self):
        logger.info("开始监听Redis频道 'udp_commands'...")
        while True:
            message = self.pubsub.get_message()
            if message and message['type'] == 'message':
                data = message['data']
                self.handle_message(data)

    def handle_message(self, data):
        """
        处理从 'udp_commands' 频道接收到的消息。
        期望格式: b"target_ip\npayload"
        """
        try:
            if b'\n' not in data:
                logger.error("数据格式错误：缺少换行符分隔符。")
                return
            encoded_ip, payload = data.split(b'\n', 1)
            target_ip = encoded_ip.decode().strip()

            if target_ip in blocked_ips:
                logger.info(f"忽略被屏蔽的IP: {target_ip}")
                return

            # 将数据加入发送队列
            self.send_queue.put((target_ip, payload))
            logger.info(f"已将数据包加入发送队列，目标IP: {target_ip}，数据大小: {len(payload)} 字节")

        except Exception as e:
            logger.error(f"处理Redis消息时出错: {e}", exc_info=True)

# =======================
# 主异步函数
# =======================
async def main():
    """
    主异步函数，用于设置和运行应用程序。
    """
    logger.info("启动主程序...")  # 确保程序从主函数开始

    # 创建发送队列，用于将数据发送到UDP线程
    send_queue = queue.Queue()

    # 动态更新屏蔽IP列表
    observer = Observer()
    observer.schedule(BlockedIPsHandler(),  path='.', recursive=False)
    observer.start() 

    # 初始化并启动UDP通信线程
    udp_thread = UdpCommunicationThread(send_queue)
    udp_thread.start()

    # 初始化Redis订阅者
    redis_subscriber = RedisSubscriber(send_queue)

    # 启动Redis订阅者监听和心跳协程
    logger.info("启动Redis订阅监听...")
    await asyncio.gather(redis_subscriber.listen()) 

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("退出UDP监控工具。")
