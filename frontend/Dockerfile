# 使用 Node.js 官方镜像
FROM node:22-alpine

# 设置工作目录
WORKDIR /app

# 复制 package.json 和 package-lock.json
COPY package.json package-lock.json* ./

# 注入 docker-compose 中的环境变量给 Vite
ARG VITE_BACKEND_PORT
ENV VITE_BACKEND_PORT=$VITE_BACKEND_PORT

# 安装依赖
RUN npm install

# 复制项目文件
COPY . .

# 暴露开发服务器的默认端口（5173）
EXPOSE 5173

# 设置启动命令为开发服务器
CMD ["npm", "run", "dev"]

