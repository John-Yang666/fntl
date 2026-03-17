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
# Logging Configuration
# =======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =======================
# Configuration Parameters
# =======================
HOST_IP = '0.0.0.0'  # Listening IP
HOST_PORT = 38315    # Listening port
REDIS_HOST = 'localhost'  # Redis server address
REDIS_PORT = 6380         # Redis port
HEARTBEAT_INTERVAL = 2    # Heartbeat interval in seconds
HEARTBEAT_IDENTIFIER = b'\xAA\xBB'  # Heartbeat packet identifier

# =======================
# Global Variables
# =======================
blocked_ips = set()      # Set of blocked IPs
udp_packet_count = 0     # UDP packet counter
gui_queue = queue.Queue()  # Queue for GUI updates

# =======================
# Redis Connection Pool
# =======================
redis_pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=False  # Keep data as bytes
)

# =======================
# Utility Functions
# =======================
def calculate_checksum(data):
    """
    Calculate checksum for the given data.
    """
    checksum = sum(data) & 0xFFFF
    return checksum.to_bytes(2, byteorder='little')

# =======================
# UDP Communication Thread
# =======================
class UdpCommunicationThread(threading.Thread):
    """
    A dedicated thread for handling UDP send and receive operations.
    """
    def __init__(self, send_queue, gui_queue):
        super().__init__(daemon=True)
        self.send_queue = send_queue
        self.gui_queue = gui_queue
        self.running = True

        # Initialize UDP socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((HOST_IP, HOST_PORT))
        self.socket.settimeout(1.0)  # 1 second timeout for non-blocking receive

    def run(self):
        logger.info(f"UDP Communication Thread started, listening on {HOST_IP}:{HOST_PORT}")
        while self.running:
            # Handle sending data
            try:
                target_ip, send_data = self.send_queue.get_nowait()
                self.socket.sendto(send_data, (target_ip, HOST_PORT))
                logger.info(f"Sent data to {target_ip}:{HOST_PORT}")
            except queue.Empty:
                pass  # No data to send
            except Exception as e:
                logger.error(f"Failed to send data: {e}", exc_info=True)

            # Handle receiving data
            try:
                data, addr = self.socket.recvfrom(4096)
                source_ip, source_port = addr

                global udp_packet_count
                udp_packet_count += 1
                logger.info(f"Received packet from {source_ip}:{source_port}")

                if source_ip in blocked_ips:
                    logger.info(f"Ignored blocked IP: {source_ip}")
                    continue

                data_length = len(data)
                if data_length != 54:
                    logger.warning(f"Discarded invalid packet of length {data_length}")
                    continue

                frame_head = data[:2]
                frame_tail = data[-2:]
                if frame_head != b'\x7f\x7f' or frame_tail != b'\xf7\xf7':
                    logger.error("Discarded packet with invalid frame head or tail")
                    continue

                payload = data[2:-4]
                checksum = data[-4:-2]
                calculated_checksum = calculate_checksum(payload)
                if checksum != calculated_checksum:
                    logger.error(
                        f"Checksum mismatch: received {checksum.hex()}, calculated {calculated_checksum.hex()}"
                    )
                    continue

                # Update GUI with source IP
                self.gui_queue.put(source_ip)

                # Publish received packet to Redis 'udp_packets' channel
                try:
                    redis_client = redis.Redis(connection_pool=redis_pool)
                    forward_packet = f"{source_ip}\n".encode() + data
                    redis_client.publish('udp_packets', forward_packet)
                    logger.info(
                        f"Published packet to Redis 'udp_packets' channel, size: {len(data)} bytes, from IP: {source_ip}"
                    )
                except Exception as e:
                    logger.error(f"Failed to publish packet to Redis: {e}", exc_info=True)

            except socket.timeout:
                continue  # No data received within timeout
            except Exception as e:
                logger.error(f"Error receiving data: {e}", exc_info=True)

    def stop(self):
        """
        Stop the communication thread.
        """
        self.running = False
        self.socket.close()
        logger.info("UDP Communication Thread stopped.")

# =======================
# Redis Subscriber Class
# =======================
class RedisSubscriber:
    """
    Subscribes to Redis channels and handles incoming messages.
    """
    def __init__(self, send_queue):
        self.redis_client = redis.Redis(connection_pool=redis_pool)
        self.pubsub = self.redis_client.pubsub()
        self.pubsub.subscribe('udp_commands')  # Subscribe to 'udp_commands' channel
        self.send_queue = send_queue
        self.loop = asyncio.get_event_loop()

    async def listen(self):
        logger.info("Listening to Redis 'udp_commands' channel...")
        while True:
            message = await self.loop.run_in_executor(None, self.pubsub.get_message, True, 1)
            if message and message['type'] == 'message':
                data = message['data']
                self.handle_message(data)
            await asyncio.sleep(0.01)

    def handle_message(self, data):
        """
        Handle messages from 'udp_commands' channel.
        Expected format: b"target_ip\npayload"
        """
        try:
            if b'\n' not in data:
                logger.error("Invalid message format: missing newline separator.")
                return
            encoded_ip, payload = data.split(b'\n', 1)
            target_ip = encoded_ip.decode().strip()

            if target_ip in blocked_ips:
                logger.info(f"Ignored command for blocked IP: {target_ip}")
                return

            # Enqueue data for sending
            self.send_queue.put((target_ip, payload))
            logger.info(f"Enqueued packet for sending to {target_ip}, size: {len(payload)} bytes")

        except Exception as e:
            logger.error(f"Error handling message from Redis: {e}", exc_info=True)

# =======================
# Heartbeat Coroutine
# =======================
async def send_heartbeat():
    """
    Periodically send heartbeat packets to Redis.
    """
    try:
        redis_client_heartbeat = redis.Redis(connection_pool=redis_pool)
        logger.info("Heartbeat coroutine started.")
        while True:
            try:
                redis_client_heartbeat.publish('heartbeat', HEARTBEAT_IDENTIFIER)
                logger.info("Sent heartbeat to Redis 'heartbeat' channel.")
            except Exception as e:
                logger.error(f"Failed to send heartbeat: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)
    except Exception as e:
        logger.error(f"Heartbeat coroutine encountered an error: {e}", exc_info=True)

# =======================
# GUI Application Class
# =======================
class UDPMonitorApp:
    """
    Tkinter GUI application for monitoring and managing UDP communications.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("UDP Manager")

        # Handle window close event
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        # Frame for Source IP Table
        source_frame = tk.Frame(root)
        source_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbar for the table
        self.tree_scrollbar = ttk.Scrollbar(source_frame, orient=tk.VERTICAL)
        self.tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Treeview for displaying Source IP and Last Received Time
        self.tree = ttk.Treeview(
            source_frame,
            columns=("IP", "Last Received Time"),
            show="headings",
            yscrollcommand=self.tree_scrollbar.set
        )
        self.tree.heading("IP", text="Source IP")
        self.tree.heading("Last Received Time", text="Last Received Time")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree_scrollbar.config(command=self.tree.yview)

        # Button to Block Selected IP
        self.block_button = tk.Button(root, text="Block Selected IP", command=self.block_selected_ip)
        self.block_button.pack(fill=tk.X, padx=5, pady=5)

        # Frame for Blocked IP List
        blocked_frame = tk.Frame(root)
        blocked_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbar for Blocked IP List
        self.blocked_scrollbar = ttk.Scrollbar(blocked_frame, orient=tk.VERTICAL)
        self.blocked_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Listbox for displaying Blocked IPs
        self.blocked_list = tk.Listbox(
            blocked_frame,
            selectmode=tk.SINGLE,
            height=5,
            yscrollcommand=self.blocked_scrollbar.set
        )
        self.blocked_list.pack(fill=tk.BOTH, padx=5, pady=5, expand=True)
        self.blocked_scrollbar.config(command=self.blocked_list.yview)

        # Button to Unblock Selected IP
        self.unblock_button = tk.Button(root, text="Unblock Selected IP", command=self.unblock_selected_ip)
        self.unblock_button.pack(fill=tk.X, padx=5, pady=5)

        # Dictionary to track IPs and their last received time
        self.ip_data = {}

    def close_app(self):
        """
        Handle application closure.
        """
        self.root.quit()

    def update_table(self, ip):
        """
        Update the table with the given IP and current timestamp.
        """
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if ip in self.ip_data:
            # Update existing entry
            for item in self.tree.get_children():
                if self.tree.item(item, "values")[0] == ip:
                    self.tree.item(item, values=(ip, current_time))
                    break
        else:
            # Insert new entry
            self.ip_data[ip] = current_time
            self.tree.insert("", "end", values=(ip, current_time))

    def block_selected_ip(self):
        """
        Block the IP selected in the Source IP table.
        """
        selected_item = self.tree.selection()
        if selected_item:
            item = self.tree.item(selected_item)
            ip = item["values"][0]
            blocked_ips.add(ip)
            self.update_blocked_list()
            logger.info(f"Blocked IP: {ip}")

    def unblock_selected_ip(self):
        """
        Unblock the IP selected in the Blocked IP list.
        """
        selected_item = self.blocked_list.curselection()
        if selected_item:
            ip = self.blocked_list.get(selected_item)
            blocked_ips.remove(ip)
            self.update_blocked_list()
            logger.info(f"Unblocked IP: {ip}")

    def update_blocked_list(self):
        """
        Refresh the Blocked IP list in the GUI.
        """
        self.blocked_list.delete(0, tk.END)
        for ip in blocked_ips:
            self.blocked_list.insert(tk.END, ip)

# =======================
# GUI Update Coroutine
# =======================
async def update_gui(app):
    """
    Coroutine to update the GUI based on incoming data from gui_queue.
    """
    while True:
        try:
            while not gui_queue.empty():
                ip = gui_queue.get()
                app.update_table(ip)
            app.root.update()
            await asyncio.sleep(0.01)
        except tk.TclError:
            # GUI has been closed
            break

# =======================
# Main Async Function
# =======================
async def main():
    """
    Main asynchronous function to set up and run the application.
    """
    root = tk.Tk()
    app = UDPMonitorApp(root)

    # Create a queue for sending data to the UDP thread
    send_queue = queue.Queue()

    # Initialize and start the UDP communication thread
    udp_thread = UdpCommunicationThread(send_queue, gui_queue)
    udp_thread.start()

    # Initialize Redis subscriber with the send queue
    redis_subscriber = RedisSubscriber(send_queue)

    # Get the current event loop
    loop = asyncio.get_running_loop()

    # Start Redis subscriber listening and heartbeat coroutines
    loop.create_task(redis_subscriber.listen())
    loop.create_task(send_heartbeat())
    loop.create_task(update_gui(app))

    try:
        # Run the event loop indefinitely
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        # Clean up on exit
        udp_thread.stop()
        udp_thread.join()
        logger.info("Application has been terminated.")

# =======================
# Entry Point
# =======================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting UDP Monitor Tool.")
