FROM python:3.12

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends netcat-openbsd gcc && \
    rm -rf /var/lib/apt/lists/*

# 复制 requirements.txt 并安装依赖
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# 复制项目文件和脚本到容器中
COPY . /app
COPY wait-for-it.sh /app/wait-for-it.sh
COPY ./entrypoint.sh /app/entrypoint.sh

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=myproject.settings

# 给脚本执行权限
RUN chmod +x /app/wait-for-it.sh
RUN chmod +x /app/entrypoint.sh

# 设置通用的 ENTRYPOINT 以支持不同命令
# 还有其他容器使用这个Dockerfile所以不能在此执行entrypoint脚本，而是在docker-compose中执行
# ENTRYPOINT ["/app/entrypoint.sh"]

# 默认启动命令，运行Django服务
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

