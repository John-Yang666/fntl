# syntax=docker/dockerfile:1.7

FROM python:3.12

# 设置工作目录
WORKDIR /app

ARG APT_MIRROR_HOST=mirrors.ustc.edu.cn
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_DEFAULT_TIMEOUT=180
ARG PIP_RETRIES=10

# 安装系统依赖（使用 BuildKit 缓存提升重复构建速度）
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    sed -i "s|deb.debian.org|${APT_MIRROR_HOST}|g; s|security.debian.org|${APT_MIRROR_HOST}|g" /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends netcat-openbsd gcc

# 复制依赖清单和锁文件并安装依赖（使用 BuildKit 缓存提升重复构建速度）
COPY requirements.txt /app/
COPY requirements.lock.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then \
      python -m pip install \
      --default-timeout=${PIP_DEFAULT_TIMEOUT} \
      --retries=${PIP_RETRIES} \
      -i ${PIP_INDEX_URL} \
      --extra-index-url ${PIP_EXTRA_INDEX_URL} \
      --trusted-host ${PIP_TRUSTED_HOST} \
      -r requirements.txt \
      -c requirements.lock.txt; \
    else \
      python -m pip install \
      --default-timeout=${PIP_DEFAULT_TIMEOUT} \
      --retries=${PIP_RETRIES} \
      -i ${PIP_INDEX_URL} \
      --trusted-host ${PIP_TRUSTED_HOST} \
      -r requirements.txt \
      -c requirements.lock.txt; \
    fi

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
