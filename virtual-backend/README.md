# 贝通网管虚拟后端

独立桌面演示程序，内置 BT/SY 仿真服务和控制 UI，可代替真实后端连接现有贝通网管前端客户端。

## 默认信息

- BT 后端地址：`http://127.0.0.1:8000`
- SY 后端地址：`http://127.0.0.1:8001`
- 演示账号：`admin`
- 演示密码：`admin`
- 固定设备：`BT-01/02/03`、`SY-01/02/03`
- 演示线路：`演示线路`

## 功能范围

- 兼容前端客户端常用接口：登录、用户信息、设备列表、拓扑状态、当前告警、历史记录、设备状态、远程控制命令。
- 支持 WebSocket：BT/SY `/ws/topology/`，BT `/ws/device-monitor/<device_id>/`。
- 控制 UI 可切换正常、通信中断、一方向故障、二方向故障、当前告警。
- BT 设备可模拟电压电流异常；SY 设备可模拟启动、主机停用、备机停用。
- `/admin/` 提供只读仿真 Admin，用于查看设备、当前告警和操作记录。
- 状态保存到本机用户数据目录的 `simulator-state.json`，控制 UI 可一键重置。

## 开发命令

```bash
npm install
npm run test:unit
npm run build
npm run desktop:compile
npm run desktop:dev
```

`desktop:dev` 会先构建控制 UI 和 Electron 主进程，再启动桌面程序。程序启动后会占用 `127.0.0.1:8000` 和 `127.0.0.1:8001`；如果真实后端正在运行，需要先停止真实后端，或在前端客户端里改服务地址。

## 打包

```bash
npm run desktop:build:mac
npm run desktop:build:win
```

macOS 产物输出到 `desktop-release/`，包含 dmg 和 zip。Windows 产物包含 NSIS 安装包和 zip。默认不做代码签名、公证、自动更新或开机自启。

## 前端客户端连接

打开“贝通网管客户端”的服务地址设置：

- BT：`http://127.0.0.1:8000`
- SY：`http://127.0.0.1:8001`

保存后用 `admin/admin` 登录。控制 UI 切换故障状态后，拓扑、当前告警、记录页和设备状态页会通过轮询或 WebSocket 看到变化。
