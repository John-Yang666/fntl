# syntax=docker/dockerfile:1.7

FROM python:3.14-slim@sha256:44dd04494ee8f3b538294360e7c4b3acb87c8268e4d0a4828a6500b1eff50061

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ARG PIP_DEFAULT_TIMEOUT=180
ARG PIP_RETRIES=10

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV FLOWER_DATA_DIR=/data
ENV PYTHONPATH=/data

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install \
      --default-timeout=${PIP_DEFAULT_TIMEOUT} \
      --retries=${PIP_RETRIES} \
      -i ${PIP_INDEX_URL} \
      --trusted-host ${PIP_TRUSTED_HOST} \
      "celery[redis]==5.6.3" \
      "flower==2.0.1"

RUN mkdir -p /data && \
    useradd --uid 10001 --create-home --shell /usr/sbin/nologin flower && \
    chown -R 10001:10001 /data

USER 10001:10001
EXPOSE 5555
CMD ["celery", "flower"]
