# 使用 Node.js 官方镜像作为基础镜像
#FROM node:22-alpine

# 设置工作目录
#WORKDIR /app

# 复制 package.json 和 package-lock.json (如果有) 并安装依赖
#COPY package.json package-lock.json* ./
#RUN npm install

# 复制项目文件到工作目录
#COPY . .

# 构建 Vue 项目
#RUN npm run build

# 安装 serve 工具，用于提供静态文件
#RUN npm install -g serve

# 暴露应用运行的端口（默认 5173 为 Vite 的开发端口，若使用不同端口，请修改）
#EXPOSE 5173

# 设置默认启动命令，运行 Vite 本地开发服务器或构建后的静态文件服务器
#CMD ["serve", "-s", "dist", "-l", "5173"]

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

