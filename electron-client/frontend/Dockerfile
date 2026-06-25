# 使用 Node.js 官方镜像
FROM node:22@sha256:e0d149b4727ac0c20d9774e801e423d7a946a0bffced886f42cfe9cd3c67820a

# 设置工作目录
WORKDIR /app

ARG NPM_VERSION=11.17.0
RUN npm install -g npm@${NPM_VERSION} && npm cache clean --force

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
