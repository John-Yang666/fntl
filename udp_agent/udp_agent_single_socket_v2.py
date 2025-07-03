#宝鸡网管第二台服务器用的版本

import asyncio
import threading
import tkinter as tk
from tkinter import ttk
import logging
from datetime import datetime
import socket
import queue
import redis

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
REDIS_HOST = 'localhost'  # Redis服务器地址
REDIS_PORT = 6380         # Redis端口
HEARTBEAT_INTERVAL = 2    # 心跳包发送间隔（秒）
HEARTBEAT_IDENTIFIER = b'\xAA\xBB'  # 心跳包标识符

# =======================
# 全局变量
# =======================
blocked_ips = set()         # 被屏蔽的IP集合
udp_packet_count = 0        # UDP数据包计数器
gui_queue = queue.Queue()   # 用于GUI更新的线程安全队列

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
    def __init__(self, send_queue, gui_queue):
        super().__init__(daemon=True)
        self.send_queue = send_queue
        self.gui_queue = gui_queue
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

                data_length = len(data)
                if data_length != 54:
                    logger.warning(f"丢弃了一个长度为 {data_length} 的无效数据包")
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

                # 更新GUI显示
                self.gui_queue.put(source_ip)

                # 将接收到的数据包发布到Redis的 'udp_packets' 频道
                try:
                    redis_client = redis.Redis(connection_pool=redis_pool)
                    forward_packet = f"{source_ip}\n".encode() + data
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
        self.loop = asyncio.get_event_loop()

    async def listen(self):
        logger.info("开始监听Redis频道 'udp_commands'...")
        while True:
            message = await self.loop.run_in_executor(None, self.pubsub.get_message, True, 1)
            if message and message['type'] == 'message':
                data = message['data']
                self.handle_message(data)
            await asyncio.sleep(0.01)

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
# 心跳协程
# =======================
async def send_heartbeat():
    """
    定期发送心跳包到Redis的 'heartbeat' 频道。
    """
    try:
        redis_client_heartbeat = redis.Redis(connection_pool=redis_pool)
        logger.info("心跳协程已启动。")
        while True:
            try:
                redis_client_heartbeat.publish('heartbeat', HEARTBEAT_IDENTIFIER)
                logger.info("已发送心跳包到Redis频道 'heartbeat'")
            except Exception as e:
                logger.error(f"发送心跳包失败: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)
    except Exception as e:
        logger.error(f"心跳协程遇到错误: {e}", exc_info=True)

# =======================
# GUI应用类
# =======================
class UDPMonitorApp:
    """
    Tkinter GUI应用，用于监控和管理UDP通信。
    """
    def __init__(self, root):
        self.root = root
        self.root.title("UDP 管理器")

        # 处理窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        # 源IP表格的框架
        source_frame = tk.Frame(root)
        source_frame.pack(fill=tk.BOTH, expand=True)

        # 表格的滚动条
        self.tree_scrollbar = ttk.Scrollbar(source_frame, orient=tk.VERTICAL)
        self.tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 显示来源IP和最近接收时间的表格
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

        # "屏蔽选定 IP"按钮
        self.block_button = tk.Button(root, text="屏蔽选定 IP", command=self.block_selected_ip)
        self.block_button.pack(fill=tk.X, padx=5, pady=5)

        # 被屏蔽IP列表的滚动条
        blocked_frame = tk.Frame(root)
        blocked_frame.pack(fill=tk.BOTH, expand=True)

        self.blocked_scrollbar = ttk.Scrollbar(blocked_frame, orient=tk.VERTICAL)
        self.blocked_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 显示被屏蔽的IP列表
        self.blocked_list = tk.Listbox(
            blocked_frame,
            selectmode=tk.SINGLE,
            height=5,
            yscrollcommand=self.blocked_scrollbar.set
        )
        self.blocked_list.pack(fill=tk.BOTH, padx=5, pady=5, expand=True)
        self.blocked_scrollbar.config(command=self.blocked_list.yview)

        # "解除屏蔽 IP"按钮
        self.unblock_button = tk.Button(root, text="解除屏蔽 IP", command=self.unblock_selected_ip)
        self.unblock_button.pack(fill=tk.X, padx=5, pady=5)

        # 用于记录IP和最后接收时间的字典
        self.ip_data = {}

    def close_app(self):
        """关闭应用程序。"""
        self.root.quit()

    def update_table(self, ip):
        """
        更新表格，显示新的IP或更新已有IP的接收时间。
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if ip in self.ip_data:
            # 更新已有条目的时间
            for item in self.tree.get_children():
                if self.tree.item(item, "values")[0] == ip:
                    self.tree.item(item, values=(ip, current_time))
                    break
        else:
            # 插入新条目
            self.ip_data[ip] = current_time
            self.tree.insert("", "end", values=(ip, current_time))

    def block_selected_ip(self):
        """
        屏蔽在源IP表格中选中的IP。
        """
        selected_item = self.tree.selection()
        if selected_item:
            item = self.tree.item(selected_item)
            ip = item["values"][0]
            blocked_ips.add(ip)
            self.update_blocked_list()
            logger.info(f"已屏蔽IP: {ip}")

    def unblock_selected_ip(self):
        """
        解除屏蔽在被屏蔽IP列表中选中的IP。
        """
        selected_item = self.blocked_list.curselection()
        if selected_item:
            ip = self.blocked_list.get(selected_item)
            blocked_ips.remove(ip)
            self.update_blocked_list()
            logger.info(f"已解除屏蔽IP: {ip}")

    def update_blocked_list(self):
        """
        更新被屏蔽IP列表的显示。
        """
        self.blocked_list.delete(0, tk.END)
        for ip in blocked_ips:
            self.blocked_list.insert(tk.END, ip)

# =======================
# GUI更新协程
# =======================
async def update_gui(app):
    """
    协程，用于根据gui_queue中的数据更新GUI。
    """
    while True:
        try:
            while not gui_queue.empty():
                ip = gui_queue.get()
                app.update_table(ip)
            app.root.update()
            await asyncio.sleep(0.01)
        except tk.TclError:
            # GUI已关闭
            break

# =======================
# 主异步函数
# =======================
async def main():
    """
    主异步函数，用于设置和运行应用程序。
    """
    root = tk.Tk()
    app = UDPMonitorApp(root)

    # 创建发送队列，用于将数据发送到UDP线程
    send_queue = queue.Queue()

    # 初始化并启动UDP通信线程
    udp_thread = UdpCommunicationThread(send_queue, gui_queue)
    udp_thread.start()

    # 初始化Redis订阅者
    redis_subscriber = RedisSubscriber(send_queue)

    # 获取当前事件循环
    loop = asyncio.get_running_loop()

    # 启动Redis订阅者监听和心跳协程
    loop.create_task(redis_subscriber.listen())
    loop.create_task(send_heartbeat())
    loop.create_task(update_gui(app))

    try:
        # 保持事件循环运行
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        # 退出时清理资源
        udp_thread.stop()
        udp_thread.join()
        logger.info("应用程序已终止。")

# =======================
# 程序入口
# =======================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("退出UDP监控工具。")
