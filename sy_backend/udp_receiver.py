"""
历史兼容入口。

SY ingestion 已统一切换到 sy_receiver.py + Redis Streams 批处理架构。
保留本文件仅为了兼容旧的手工启动命令：`python udp_receiver.py`。
"""

from sy_receiver import main


if __name__ == "__main__":
    main()
