# 使用 Node.js 官方镜像
FROM node:22

# 设置工作目录
WORKDIR /app

# 复制依赖清单和锁文件
COPY package.json package-lock.json ./

# 安装依赖
RUN npm ci --no-audit --no-fund

# 复制项目文件
COPY . .

# 暴露开发服务器的默认端口（5173）
EXPOSE 5173

# 设置启动命令为开发服务器
CMD ["npm", "run", "dev"]
