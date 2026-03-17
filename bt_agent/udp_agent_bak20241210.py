import asyncio
import tkinter as tk
from tkinter import ttk
import logging
from datetime import datetime
import socket
import queue
import redis

# 日志设置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 设置参数
HOST_IP = '0.0.0.0'  # 监听的 IP
HOST_PORT = 38315    # 监听的端口
REDIS_HOST = 'localhost'  # Redis 服务器地址（根据实际情况修改）
REDIS_PORT = 6380         # Redis 端口
HEARTBEAT_INTERVAL = 2    # 心跳包发送间隔（秒）
HEARTBEAT_IDENTIFIER = b'\xAA\xBB'  # 心跳包标识符

# 屏蔽的 IP 列表
blocked_ips = set()

# 数据包计数器，用于检测是否停止接收数据
udp_packet_count = 0

# 定义一个线程安全的队列，用于 GUI 更新
gui_queue = queue.Queue()

# 创建 Redis 连接池（全局）
redis_pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=False  # 保持数据为字节串
)

def calculate_checksum(data):
    """
    计算校验和。
    """
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder='little')

class UdpServerProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        super().__init__()
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info(f"UDP 接收器已启动，监听 {HOST_IP}:{HOST_PORT}")

    def datagram_received(self, data, addr):
        global udp_packet_count
        source_ip, source_port = addr

        # 获取数据长度
        data_length = len(data)

        # 接收器逻辑
        udp_packet_count += 1
        logger.info(f"收到来自 {source_ip}:{source_port} 的数据包，长度为 {data_length} 字节")
        
        if source_ip in blocked_ips:
            logger.info(f"已忽略被屏蔽的 IP: {source_ip}")
            return

        # 只处理长度为 54 的数据包
        if data_length != 54:
            logger.warning(f"丢弃了一个长度为 {data_length} 的无效数据包")
            return

        # 校验数据包格式
        frame_head = data[:2]
        frame_tail = data[-2:]
        if frame_head != b'\x7f\x7f' or frame_tail != b'\xf7\xf7':
            logger.error(f"丢弃了一个无效的帧头或帧尾，帧头: {frame_head}, 帧尾: {frame_tail}")
            return
        
        # 提取数据包内容（不包括帧头、帧尾和校验和）
        payload = data[2:-4]

        # 计算校验和并与包中的校验和进行对比
        received_checksum = data[-4:-2]
        calculated_checksum = calculate_checksum(payload)

        if received_checksum != calculated_checksum:
            logger.error(f"校验和错误！接收到的校验和: {received_checksum.hex()}, 计算的校验和: {calculated_checksum.hex()}")
            return

        # 如果校验和正确，处理数据
        logger.info(f"校验和正确，数据包内容: {payload.hex()}")

        # 将数据包通过 Redis 发布到 'udp_packets' 频道
        try:
            redis_client = redis.Redis(connection_pool=redis_pool)
            forward_packet = f"{source_ip}\n".encode() + data
            redis_client.publish('udp_packets', forward_packet)
            logger.info(f"成功将数据包发布到 Redis 频道 'udp_packets'，数据包大小: {data_length} 字节，来源 IP: {source_ip}")
        except Exception as e:
            logger.error(f"通过 Redis 发布数据包失败: {e}", exc_info=True)


class RedisSubscriber:
    def __init__(self):
        self.redis_client = redis.Redis(connection_pool=redis_pool)
        self.pubsub = None

    def reconnect(self):
        while True:
            try:
                self.pubsub = self.redis_client.pubsub()
                self.pubsub.subscribe('udp_commands')
                logger.info("已成功重新订阅 Redis 频道 'udp_commands'")
                break
            except Exception as e:
                logger.error(f"Redis 重新连接失败: {e}，5秒后重试...")
                asyncio.sleep(5)

    async def listen(self):
        while True:
            try:
                if not self.pubsub:
                    self.reconnect()
                message = await asyncio.to_thread(self.pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
                if message and message['type'] == 'message':
                    self.handle_message(message['data'])
            except (redis.ConnectionError, redis.TimeoutError) as e:
                logger.error(f"Redis 连接错误: {e}。尝试重新连接...")
                self.reconnect()
            except Exception as e:
                logger.error(f"Redis 监听器遇到未知错误: {e}")

    def handle_message(self, data):
        try:
            if b'\n' not in data:
                logger.error("数据格式错误，无法分割为目标 IP 和数据包")
                return
            header, payload = data.split(b'\n', 1)
            target_ip = header.decode().strip()

            #if target_ip in blocked_ips:
            #    logger.info(f"已忽略被屏蔽的 IP: {target_ip}")
            #    return

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
                udp_sock.sendto(payload, (target_ip, HOST_PORT))
            logger.info(f"已将数据转发到 {target_ip}:{HOST_PORT}")
            gui_queue.put(target_ip)

        except Exception as e:
            logger.error(f"处理数据包时发生错误: {e}", exc_info=True)


async def start_server():
    loop = asyncio.get_running_loop()
    try:
        await loop.create_datagram_endpoint(
            lambda: UdpServerProtocol(),
            local_addr=(HOST_IP, HOST_PORT)
        )
    except Exception as e:
        logger.error(f"启动 UDP 接收器失败: {e}", exc_info=True)


async def send_heartbeat():
    try:
        redis_client_heartbeat = redis.Redis(connection_pool=redis_pool)
        logger.info("开始发送心跳包")
        while True:
            try:
                redis_client_heartbeat.publish('heartbeat', HEARTBEAT_IDENTIFIER)
                logger.info("发送心跳包到 Redis 频道 'heartbeat'")
            except Exception as e:
                logger.error(f"发送心跳包失败: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)
    except Exception as e:
        logger.error(f"心跳任务遇到错误: {e}", exc_info=True)


class UDPMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UDP 管理器")
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        source_frame = tk.Frame(root)
        source_frame.pack(fill=tk.BOTH, expand=True)

        self.tree_scrollbar = ttk.Scrollbar(source_frame, orient=tk.VERTICAL)
        self.tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(
            source_frame,
            columns=("IP", "最近接收时间"),
            show="headings",
            yscrollcommand=self.tree_scrollbar.set
        )
        self.tree.heading("IP", text="来源 IP")
        self.tree.heading("最近接收时间", text="最近接收时间")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree_scrollbar.config(command=self.tree.yview)

        self.block_button = tk.Button(root, text="屏蔽选定 IP", command=self.block_selected_ip)
        self.block_button.pack(fill=tk.X, padx=5, pady=5)

        blocked_frame = tk.Frame(root)
        blocked_frame.pack(fill=tk.BOTH, expand=True)

        self.blocked_scrollbar = ttk.Scrollbar(blocked_frame, orient=tk.VERTICAL)
        self.blocked_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.blocked_list = tk.Listbox(
            blocked_frame,
            selectmode=tk.SINGLE,
            height=5,
            yscrollcommand=self.blocked_scrollbar.set
        )
        self.blocked_list.pack(fill=tk.BOTH, padx=5, pady=5, expand=True)
        self.blocked_scrollbar.config(command=self.blocked_list.yview)

        self.unblock_button = tk.Button(root, text="解除屏蔽 IP", command=self.unblock_selected_ip)
        self.unblock_button.pack(fill=tk.X, padx=5, pady=5)

        self.ip_data = {}

    def close_app(self):
        self.root.quit()

    def update_table(self, ip):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if ip in self.ip_data:
            for item in self.tree.get_children():
                if self.tree.item(item, "values")[0] == ip:
                    self.tree.item(item, values=(ip, current_time))
                    break
        else:
            self.ip_data[ip] = current_time
            self.tree.insert("", "end", values=(ip, current_time))

    def block_selected_ip(self):
        selected_item = self.tree.selection()
        if selected_item:
            item = self.tree.item(selected_item)
            ip = item["values"][0]
            blocked_ips.add(ip)
            self.update_blocked_list()

    def unblock_selected_ip(self):
        selected_item = self.blocked_list.curselection()
        if selected_item:
            ip = self.blocked_list.get(selected_item)
            blocked_ips.remove(ip)
            self.update_blocked_list()

    def update_blocked_list(self):
        self.blocked_list.delete(0, tk.END)
        for ip in blocked_ips:
            self.blocked_list.insert(tk.END, ip)


async def update_gui(app):
    while True:
        try:
            while not gui_queue.empty():
                ip = gui_queue.get()
                app.update_table(ip)
            app.root.update()
            await asyncio.sleep(0.01)
        except tk.TclError:
            break


async def main():
    root = tk.Tk()
    app = UDPMonitorApp(root)
    redis_subscriber = RedisSubscriber()

    loop = asyncio.get_running_loop()
    loop.create_task(start_server())
    loop.create_task(redis_subscriber.listen())
    loop.create_task(send_heartbeat())
    loop.create_task(update_gui(app))

    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("退出 UDP 监控工具")
