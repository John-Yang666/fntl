# 贝通网管客户端说明

本目录是贝通网管桌面客户端的独立源码目录，客户端代码放在：

```text
/Users/yangzijiang/BT_NMS/electron-client/frontend
```

主前端目录仍保留在：

```text
/Users/yangzijiang/BT_NMS/frontend
```

当前目录不会自动跟随主前端更新。以后如果主前端新增页面或修复功能，需要把对应改动同步到 `electron-client/frontend` 后再重新打包客户端。

## 目录结构

```text
electron-client/
  README.md                       本说明
  docs/桌面客户端构建说明.md        详细构建和发布说明
  frontend/
    electron/                     Electron 主进程、preload、本机代理
    src/                          Vue 前端源码
    package.json                  前端和桌面客户端脚本
    tsconfig.electron.json        Electron TypeScript 配置
    vitest.config.ts              客户端相关单元测试配置
```

## 客户端行为

- 应用名：贝通网管客户端。
- 客户端只内置前端，不捆绑 Django、PostgreSQL、Redis、agent 或 Nginx。
- Electron 自带 Chromium 内核，不依赖用户电脑上的 Chrome/Safari/Edge 渲染主界面。
- 启动后本地开启 `127.0.0.1:<随机端口>`，加载 `frontend/dist`。
- HTTP API 通过本机代理访问：
  - `/__client/proxy/bt/api/*` -> 前端入口 `/bt-api/*` -> BT 后端 `/api/*`
  - `/__client/proxy/sy/api/*` -> 前端入口 `/sy-api/*` -> SY 后端 `/api/*`
- WebSocket 通过本机代理访问：
  - `/__client/proxy/bt/ws/*` -> 前端入口 `/bt-ws/*` -> BT 后端 `/ws/*`
  - `/__client/proxy/sy/ws/*` -> 前端入口 `/sy-ws/*` -> SY 后端 `/ws/*`
- 默认前端入口：
  - BT: `http://127.0.0.1:38173`
  - SY: `http://127.0.0.1:38173`

## 保活与自动恢复

从 `0.2.0` 起，桌面客户端包含以下保活机制：

- 关闭最后一个客户端窗口时隐藏到托盘，HTTP/WebSocket 连接和告警监听继续运行；需要完全退出时使用托盘菜单的“退出”。
- 渲染进程崩溃、持续无响应或主页面加载失败时自动重载窗口；短时间连续失败时自动重启整个客户端。
- 每 30 秒检查一次客户端本机静态资源/代理服务，连续 3 次失败时自动重启客户端。
- 主进程发生未捕获异常时自动重启，5 分钟内最多连续重启 3 次，避免故障循环。
- Windows 安装版会设置当前用户登录后后台启动，并创建每分钟运行一次的计划任务 `BeiTongNmsClientWatchdog`。客户端已运行时任务不会打开新窗口；客户端意外退出时，最迟约 1 分钟自动恢复到托盘。
- Windows 卸载程序会删除登录启动项和计划任务。
- Windows 免安装 ZIP 不注册系统级启动项或计划任务，但保留窗口、渲染进程、主进程和本机代理的内部自动恢复。

客户端运行日志位于 Electron 用户数据目录的 `logs/client.log`。Windows 默认位置通常为：

```text
%APPDATA%\贝通网管客户端\logs\client.log
```

日志达到 5 MB 后保留一份上一轮日志 `client.log.1`。

## macOS 本机验证

```bash
cd /Users/yangzijiang/BT_NMS/electron-client/frontend
npm ci
npm run test:unit
npm run build
npm run desktop:compile
npm run desktop:build:mac
```

macOS 产物输出到：

```text
frontend/desktop-release
```

## Windows 打包

在 Windows 上安装 Node.js 20 或 22 LTS，然后把 `electron-client/frontend` 拷过去，进入该目录执行：

```powershell
npm ci
npm run desktop:build:win
```

Windows 产物输出到：

```text
frontend\desktop-release
```

包括：

- NSIS 安装包 `.exe`
- 免安装压缩包 `.zip`

如果 Windows 下载慢，可以临时使用国内源：

```powershell
npm config set registry https://registry.npmmirror.com
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"
npm ci
npm run desktop:build:win
```

如果 Windows 通过 VPN 下载 GitHub/npm 更快，就不要设置上面的 mirror 环境变量。

## 从 Mac 打源码包给 Windows

```bash
cd /Users/yangzijiang/BT_NMS/electron-client
zip -r /tmp/beitong-electron-client-src.zip frontend \
  -x "frontend/node_modules/*" \
     "frontend/dist/*" \
     "frontend/electron-dist/*" \
     "frontend/desktop-release/*" \
     "frontend/.vite/*" \
     "frontend/.DS_Store"
```

Windows 解压后进入 `frontend` 运行 `npm ci` 和 `npm run desktop:build:win`。

## 与主前端同步

因为客户端现在是独立副本，所以主前端 `/Users/yangzijiang/BT_NMS/frontend` 的后续修改不会自动进入客户端。

同步时重点关注这些位置：

```text
src/
public/
index.html
package.json
package-lock.json
vite.config.ts
components.d.ts
env.d.ts
```

不要用主前端直接覆盖客户端的这些桌面专用文件，除非确认要重做 Electron 适配：

```text
electron/
tsconfig.electron.json
vitest.config.ts
src/utils/clientRuntime.ts
src/components/ClientSettingsDialog.vue
```

同步后至少运行：

```bash
npm run test:unit
npm run build
npm run desktop:compile
```

## 不要提交或拷贝的生成物

这些目录是本机安装依赖或构建产物，不应该作为源码同步：

```text
node_modules/
dist/
electron-dist/
desktop-release/
npm-cache/
*.tsbuildinfo
```
