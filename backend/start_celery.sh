#!/bin/bash

# 激活虚拟环境
source venv/bin/activate

# 启动 Celery worker
celery -A myproject worker --loglevel=info
