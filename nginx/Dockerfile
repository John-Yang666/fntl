# 使用官方 Nginx 镜像
FROM nginx:latest

# 启用流模块（stream module）支持 UDP
RUN apt-get update && apt-get install -y vim && \
    echo "load_module /usr/lib/nginx/modules/ngx_stream_module.so;" >> /etc/nginx/nginx.conf

# 复制自定义配置文件
COPY nginx.conf /etc/nginx/nginx.conf
