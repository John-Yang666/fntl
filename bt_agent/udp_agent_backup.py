import asyncio
import tkinter as tk
from tkinter import ttk
import logging
from datetime import datetime
import socket
import queue

# 日志设置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 设置参数
HOST_IP = '0.0.0.0'  # host 监听的 IP
HOST_PORT = 38315    # host 监听的端口
PORT_FOR_UDP_SENDER = 38317  # host 监听转发数据包的端口
CONTAINER_IP = '127.0.0.1'  # Docker 容器内 UDP 接收器的 IP
CONTAINER_PORT = 38316      # Docker 容器内 UDP 接收器的端口
HEARTBEAT_INTERVAL = 5      # 心跳包发送间隔（秒）
HEARTBEAT_IDENTIFIER = b'\xAA\xBB'  # 心跳包标识符

# 屏蔽的 IP 列表
blocked_ips = set()

# 数据包计数器，用于检测是否停止接收数据
udp_packet_count = 0

# 定义一个线程安全的队列，用于 GUI 更新
gui_queue = queue.Queue()


class UdpServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, is_forwarder=False):
        super().__init__()
        self.transport = None
        self.is_forwarder = is_forwarder  # 是否为转发数据的协议

    def connection_made(self, transport):
        self.transport = transport
        port = PORT_FOR_UDP_SENDER if self.is_forwarder else HOST_PORT
        logger.info(f"UDP 接收器已启动，监听 {HOST_IP}:{port}")

    def datagram_received(self, data, addr):
        global udp_packet_count
        source_ip, source_port = addr

        if self.is_forwarder:
            # 转发器逻辑
            logger.info(f"收到来自 {source_ip}:{source_port} 的转发数据")
            self.forward_data(data)
        else:
            # 接收器逻辑
            udp_packet_count += 1
            logger.info(f"收到来自 {source_ip}:{source_port} 的数据包")
            if source_ip in blocked_ips:
                logger.info(f"已忽略被屏蔽的 IP: {source_ip}")
                return

            # 将 IP 地址放入 GUI 队列
            gui_queue.put(source_ip)

            # 转发数据到容器
            try:
                modified_data = (
                    f"PROXY TCP4 {source_ip} 127.0.0.1 {source_port} {CONTAINER_PORT}\r\n".encode() + data
                )
                self.transport.sendto(modified_data, (CONTAINER_IP, CONTAINER_PORT))
                logger.info(f"转发数据到容器: {source_ip}:{source_port} -> {CONTAINER_IP}:{CONTAINER_PORT}")
            except Exception as e:
                logger.error(f"转发数据失败: {e}", exc_info=True)

    def forward_data(self, data):
        """
        解析 forward_packet 并转发到指定目标 IP:38315
        """
        try:
            if b'\n' not in data:
                logger.error("数据格式错误，无法分割为 header 和 payload")
                return
            header, payload = data.split(b'\n', 1)  # 按换行符分割
            target_ip = header.decode().strip()  # 提取目标 IP

            # 创建套接字并发送数据到目标 IP:38315
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
                udp_sock.sendto(payload, (target_ip, HOST_PORT))
            logger.info(f"已将数据转发到 {target_ip}:{HOST_PORT}")
        except Exception as e:
            logger.error(f"转发数据失败: {e}", exc_info=True)


async def start_server():
    loop = asyncio.get_running_loop()

    # 启动 38315 接收器
    try:
        await loop.create_datagram_endpoint(
            lambda: UdpServerProtocol(is_forwarder=False),
            local_addr=(HOST_IP, HOST_PORT)
        )
    except Exception as e:
        logger.error(f"启动 UDP 接收器失败: {e}", exc_info=True)

    # 启动 38317 转发器
    try:
        await loop.create_datagram_endpoint(
            lambda: UdpServerProtocol(is_forwarder=True),
            local_addr=(HOST_IP, PORT_FOR_UDP_SENDER)
        )
    except Exception as e:
        logger.error(f"启动 UDP 转发器失败: {e}", exc_info=True)


async def send_heartbeat():
    """
    定期发送心跳包到容器的 UDP 接收器。
    """
    try:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=(CONTAINER_IP, CONTAINER_PORT)
        )
        logger.info("开始发送心跳包")
        while True:
            try:
                # 发送心跳包
                transport.sendto(HEARTBEAT_IDENTIFIER)
                logger.info(f"发送心跳包到 {CONTAINER_IP}:{CONTAINER_PORT}")
            except Exception as e:
                logger.error(f"发送心跳包失败: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)  # 间隔发送心跳包
    except Exception as e:
        logger.error(f"心跳任务遇到错误: {e}", exc_info=True)


class UDPMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UDP 管理器")

        # 捕获窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        # 添加 Source IP 表格滚动条
        source_frame = tk.Frame(root)
        source_frame.pack(fill=tk.BOTH, expand=True)

        self.tree_scrollbar = ttk.Scrollbar(source_frame, orient=tk.VERTICAL)
        self.tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 数据表格（显示 Source IP 和时间）
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

        # "屏蔽选定 IP" 按钮
        self.block_button = tk.Button(root, text="屏蔽选定 IP", command=self.block_selected_ip)
        self.block_button.pack(fill=tk.X, padx=5, pady=5)

        # 添加 Blocked IP 列表滚动条
        blocked_frame = tk.Frame(root)
        blocked_frame.pack(fill=tk.BOTH, expand=True)

        self.blocked_scrollbar = ttk.Scrollbar(blocked_frame, orient=tk.VERTICAL)
        self.blocked_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 显示被屏蔽的 IP 列表
        self.blocked_list = tk.Listbox(
            blocked_frame,
            selectmode=tk.SINGLE,
            height=5,
            yscrollcommand=self.blocked_scrollbar.set
        )
        self.blocked_list.pack(fill=tk.BOTH, padx=5, pady=5, expand=True)
        self.blocked_scrollbar.config(command=self.blocked_list.yview)

        # "解除屏蔽 IP" 按钮
        self.unblock_button = tk.Button(root, text="解除屏蔽 IP", command=self.unblock_selected_ip)
        self.unblock_button.pack(fill=tk.X, padx=5, pady=5)

        # 用于记录 IP 和最后接收时间的字典
        self.ip_data = {}

    def close_app(self):
        """关闭应用"""
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
            # 从队列中获取 IP 并更新表格
            while not gui_queue.empty():
                ip = gui_queue.get()
                app.update_table(ip)
            app.root.update()
            await asyncio.sleep(0.01)
        except tk.TclError:
            # GUI 已关闭
            break


async def main():
    root = tk.Tk()
    app = UDPMonitorApp(root)

    loop = asyncio.get_running_loop()
    # 启动服务器和心跳任务
    loop.create_task(start_server())
    loop.create_task(send_heartbeat())
    loop.create_task(update_gui(app))

    # 保持事件循环运行
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("退出 UDP 监控工具")
