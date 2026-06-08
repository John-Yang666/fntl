# BT_NMS 运维手册

版本日期：2026-06-08
适用工程目录：`/Users/yangzijiang/BT_NMS`
适用对象：BT/SY 云网管系统的部署、巡检、备份、恢复和故障处理。

## 1. 系统概览

BT_NMS 当前由前端、BT 后端、SY 后端、数据采集 agent、PostgreSQL、Redis、Redis Streams、Celery、Nginx 等组件组成。

核心链路：

1. Windows 宿主机上的 `bt_agent` / `bt_agent_serial` / `sy_agent` 采集现场设备数据。
2. agent 将数据写入宿主机暴露的 Redis Streams 端口。
3. Docker 内的 `udp_receiver` 或 `sy_receiver` 消费 Stream，解析数据并写入数据库和 Redis 状态。
4. `summarize_alarms_container` 汇总告警和设备状态。
5. Django 后端提供 admin 和 API，Celery 执行异步任务，Vue 前端提供统一访问入口。

主要代码与配置：

- BT 后端：`backend/`
- SY 后端：`sy_backend/`
- 前端：`frontend/`
- BT agent：`bt_agent/`、`bt_agent_serial/`
- SY agent：`sy_agent/`
- Windows 启动脚本：`deploy/windows_host/`
- Docker 生产编排：`docker-compose-prod.yml`、`docker-compose-sy-prod.yml`
- 常用命令参考：`常用部署指令.md`

## 2. 端口与访问地址

| 用途 | 地址/端口 | 说明 |
| --- | --- | --- |
| 生产前端 | `http://<主机IP>:38173/` | BT/SY 共用前端入口 |
| BT 后端 admin/API | `http://<主机IP>:8000/admin/`、`/api/` | 由 `bt_nms_nginx0` 暴露 |
| SY 后端 admin/API | `http://<主机IP>:8001/admin/`、`/api/` | 由 `bt_nms_sy_nginx0` 暴露 |
| BT Redis Stream | `<主机IP>:36379` | BT agent 写 `stream:udp:packets`，接收下行 `stream:udp:cmd` |
| SY Redis Stream | `<主机IP>:36380` | SY agent 写 `sy.raw`，接收 `sy-serial-commands` |
| BT Flower | `http://<主机IP>:5555/` | Celery 监控 |
| SY Flower | `http://<主机IP>:5556/` | Celery 监控 |
| BT Portainer | `http://<主机IP>:9000/` | Docker 管理界面 |
| SY Portainer | `http://<主机IP>:9001/` | Docker 管理界面 |

现场访问异常时，先确认防火墙放行 `38173`、`8000`、`8001`、`36379`、`36380`。

## 3. 生产服务清单

### BT 生产环境

Compose 文件：`docker-compose-prod.yml`
项目名：`bt_nms_prod`

| 容器 | 作用 |
| --- | --- |
| `bt_nms_vue_prod0` | Vue 生产前端，默认端口 `38173` |
| `bt_nms_nginx0` | 反向代理 Django，暴露 `8000` |
| `bt_nms_django_app0` | BT Django/ASGI 后端 |
| `bt_nms_postgres_db0` | BT PostgreSQL |
| `bt_nms_redis0` | Django/Celery 业务 Redis |
| `bt_nms_redis_stream0` | BT 数据包和命令 Redis Streams |
| `bt_nms_udp_receiver0` | 消费 BT 上行数据流 |
| `bt_nms_summarize_alarms_container0` | 汇总 BT 告警和设备状态 |
| `bt_nms_celery_worker0` | Celery worker |
| `bt_nms_celery_beat0` | Celery 定时调度 |
| `bt_nms_flower0` | Celery 监控 |
| `bt_nms_portainer0` | Docker 管理 |

### SY 生产环境

Compose 文件：`docker-compose-sy-prod.yml`
项目名：`bt_nms_sy_prod`

| 容器 | 作用 |
| --- | --- |
| `bt_nms_sy_nginx0` | 反向代理 Django，暴露 `8001` |
| `bt_nms_sy_django_app0` | SY Django/ASGI 后端 |
| `bt_nms_sy_postgres_db0` | SY PostgreSQL |
| `bt_nms_sy_redis0` | Django/Celery 业务 Redis |
| `bt_nms_sy_redis_stream0` | SY 上行数据和下行命令 Redis Streams |
| `bt_nms_sy_receiver0` | 消费 SY 上行数据流 |
| `bt_nms_sy_summarize_alarms_container0` | 汇总 SY 告警和设备状态 |
| `bt_nms_sy_celery_worker0` | Celery worker |
| `bt_nms_sy_celery_beat0` | Celery 定时调度 |
| `bt_nms_sy_flower0` | Celery 监控 |
| `bt_nms_sy_portainer0` | Docker 管理 |

## 4. 目录与持久化数据

默认生产数据根目录：`/srv/bt_nms_data`

| 路径 | 内容 | 备份要求 |
| --- | --- | --- |
| `/srv/bt_nms_data/postgres` | BT PostgreSQL 数据目录 | 必备 |
| `/srv/bt_nms_data/sy/postgres` | SY PostgreSQL 数据目录 | 必备 |
| `/srv/bt_nms_data/cleanup_exports` | 清理/导出文件 | 按现场要求备份 |
| `/srv/bt_nms_data/portainer` | BT Portainer 数据 | 使用 Portainer 时备份 |
| `/srv/bt_nms_data/sy/portainer` | SY Portainer 数据 | 使用 Portainer 时备份 |
| `frontend/dist` | 本地 dist 挂载模式下的前端产物 | 小改动现场模式下建议备份 |

Redis 和 Redis Streams 当前配置为不持久化，并使用 `tmpfs` 或禁用 `save`/`appendonly`。Redis 只作为运行态缓存和消息总线，不应作为长期数据备份来源。

Windows 受保护部署的 agent 运行态数据：

```text
%ProgramData%\BT_NMS\bt_agent\
%ProgramData%\BT_NMS\bt_agent_serial\
%ProgramData%\BT_NMS\sy_agent\
```

这些目录包含 `config.json`、`runtime_config.json`、本地 UI sqlite 状态等，现场配置变更后应纳入备份。

### Windows Docker Desktop 用户与国内镜像源

Windows Docker Desktop 的 Linux engine、镜像、容器和 Desktop 设置跟 Windows 登录用户相关。`admin` 和 `贝通` 登录后看到的 Docker Desktop 可能是两套环境，切换运维用户前先确认：

```powershell
$env:USERNAME
docker context ls
docker ps
docker images
```

更新 Windows 现场源码时必须保留现场 `.env`，尤其是 `DATA_DIR=D:/bt_nms_data`、数据库密码和密钥；不要用 Mac 或源码包里的 `.env` 覆盖 Windows 现场配置。

国内网络环境建议给 `admin` 或实际运维用户配置以下镜像源。Docker Desktop 读取的 `daemon.json` 必须是 UTF-8 无 BOM；旧版 Windows PowerShell 的 `Set-Content` 可能写出 Docker 无法解析的 BOM，表现为 `invalid character 'ï' looking for beginning of value`。

```powershell
$daemon = [ordered]@{
  builder = [ordered]@{
    gc = [ordered]@{
      enabled = $true
      defaultKeepStorage = "20GB"
    }
  }
  experimental = $false
  "registry-mirrors" = @(
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run",
    "https://hub-mirror.c.163.com"
  )
}

$json = $daemon | ConvertTo-Json -Depth 10
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText("$env:USERPROFILE\.docker\daemon.json", $json + [Environment]::NewLine, $utf8NoBom)

docker desktop restart
docker info --format "{{json .RegistryConfig.Mirrors}}"
```

npm 和 Python 构建源：

```powershell
npm config set registry https://registry.npmmirror.com/

New-Item -ItemType Directory -Force "$env:APPDATA\pip" | Out-Null
@"
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
timeout = 120
retries = 5

[install]
trusted-host = pypi.tuna.tsinghua.edu.cn
"@ | Set-Content -Encoding ASCII "$env:APPDATA\pip\pip.ini"
```

Electron 客户端打包下载源建议写入用户环境变量，重开 PowerShell 后生效：

```powershell
[Environment]::SetEnvironmentVariable("ELECTRON_MIRROR", "https://npmmirror.com/mirrors/electron/", "User")
[Environment]::SetEnvironmentVariable("ELECTRON_BUILDER_BINARIES_MIRROR", "https://npmmirror.com/mirrors/electron-builder-binaries/", "User")
[Environment]::SetEnvironmentVariable("PLAYWRIGHT_DOWNLOAD_HOST", "https://npmmirror.com/mirrors/playwright/", "User")
```

## 5. 首次部署

进入工程目录：

```bash
cd /Users/yangzijiang/BT_NMS
```

配置部署 IP：

- BT：`backend/deploy_host_ip.txt`
- SY：`sy_backend/deploy_host_ip.txt`

示例：

```text
192.168.1.88
```

支持用换行、逗号或分号配置多个 IP。修改后重启对应 Django 和 Nginx：

```bash
docker restart bt_nms_django_app0 bt_nms_nginx0
docker restart bt_nms_sy_django_app0 bt_nms_sy_nginx0
```

启动 BT 生产环境：

```bash
docker compose -f docker-compose-prod.yml up -d --build --remove-orphans
```

启动 SY 生产环境：

```bash
docker compose -f docker-compose-sy-prod.yml up -d --build --remove-orphans
```

只部署 SY 后端但仍需前端入口时，单独启动前端：

```bash
docker compose -f docker-compose-prod.vue.yml up -d --force-recreate
```

注意：独立前端模式不要加 `--remove-orphans`，避免误删同项目名下其他生产容器。

## 6. 日常启停与更新

查看容器：

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

重启 BT 生产后端相关服务：

```bash
docker compose -f docker-compose-prod.yml up -d --no-deps --force-recreate web nginx udp_receiver summarize_alarms_container celery celery-beat
```

重启 SY 生产后端相关服务：

```bash
docker compose -f docker-compose-sy-prod.yml up -d --no-deps --force-recreate web nginx sy_receiver summarize_alarms_container celery celery-beat
```

只改 Python、Django 模板、admin 文案或业务代码时，通常不需要重新构建镜像，执行上述重建容器命令即可。

改 Dockerfile、Python 依赖或基础镜像时：

```bash
docker compose -f docker-compose-prod.yml up -d --build --remove-orphans
docker compose -f docker-compose-sy-prod.yml up -d --build --remove-orphans
```

数据库迁移：

```bash
docker exec -it bt_nms_django_app0 python manage.py migrate
docker exec -it bt_nms_sy_django_app0 python manage.py migrate
```

## 7. 前端发布

生产前端镜像构建：

```bash
docker build -t my_vue:prod -f frontend/Dockerfile.prod \
  --build-arg VITE_BT_BACKEND_PORT=8000 \
  --build-arg VITE_SY_BACKEND_PORT=8001 \
  frontend
```

重建前端容器：

```bash
docker compose -f docker-compose-prod.vue.yml up -d --no-deps --force-recreate vue
```

小范围前端修改建议使用本地 `dist` 挂载模式：

```bash
cd /Users/yangzijiang/BT_NMS/frontend
npm run build

cd /Users/yangzijiang/BT_NMS
docker compose -f docker-compose-prod.vue.yml -f docker-compose-prod.frontend-local.yml up -d --no-deps --force-recreate vue
```

后续只要重新执行 `npm run build`，容器会直接读取新的 `frontend/dist`。浏览器仍显示旧页面时，先强制刷新并清理缓存。

验证前端：

```bash
curl -I http://127.0.0.1:38173/
docker logs --tail 50 bt_nms_vue_prod0
docker inspect bt_nms_vue_prod0 --format '{{json .Mounts}}'
```

## 8. Windows Agent 运维

受保护部署推荐使用编译产物，不在现场机器保留源码。

构建 Windows agent 包：

```powershell
cd deploy/windows_host
.\build_protected_agents.ps1
```

如果构建机没有 `py -3.12`，但安装了兼容 Python，可以显式指定解释器。这台 Windows 维护机使用的是 Python 3.13：

```powershell
cd D:\BT_NMS
& .\deploy\windows_host\build_protected_agents.ps1 `
  -PythonLauncher "C:\Python313\python.exe" `
  -PythonLauncherArgs @()
```

产物目录：

```text
deploy/windows_host/artifacts/windows_agents/
```

Nuitka standalone 产物依赖同目录 DLL 和资源文件，现场转移时压缩整个 `windows_agents` 目录，不要只拷单个 exe：

```powershell
Compress-Archive `
  -Path D:\BT_NMS\deploy\windows_host\artifacts\windows_agents\* `
  -DestinationPath D:\BT_NMS\deploy\windows_host\artifacts\windows_agents_YYYYMMDD.zip `
  -Force
```

现场启动入口：

```text
scripts\run_bt_agent_ui.bat
scripts\run_sy_agent_ui.bat
scripts\run_sy_agent_sub_ui.bat
scripts\run_agents.bat
```

常改配置：

- `bt_agent`：Redis 主机、端口、UDP 监听端口、屏蔽 IP 列表。
- `bt_agent_serial`：Redis 主机、端口、串口号、数据流名称。
- `sy_agent`：Redis 主机、端口、线路、头尾端串口、设备 `serial_id`/`nms_id`、A1 轮询间隔。

端口约定：

- BT agent 默认连接 `127.0.0.1:36379`。
- SY agent 默认连接 `127.0.0.1:36380`。
- 如果 agent 与 Docker 后端不在同一台机器，Redis host 应改为后端部署机器 IP，并确认防火墙放行。

配置调整后，重启对应 agent 或 UI 启动的子进程即可生效。

## 9. 日常巡检

建议每天至少巡检一次，故障处理后补做一次。

### 容器状态

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker compose -f docker-compose-prod.yml ps
docker compose -f docker-compose-sy-prod.yml ps
```

重点确认：

- `web` / `nginx` 为 healthy 或 Up。
- `postgres`、`redis`、`redis_stream` 没有频繁重启。
- `udp_receiver`、`sy_receiver`、`summarize_alarms_container` 正常运行。

### 访问检查

```bash
curl -I http://127.0.0.1:38173/
curl -I http://127.0.0.1:8000/admin/
curl -I http://127.0.0.1:8001/admin/
```

返回 `200`、`302` 或登录跳转均可视为服务可达。

### Redis 检查

```bash
docker exec bt_nms_redis0 redis-cli ping
docker exec bt_nms_redis_stream0 redis-cli ping
docker exec bt_nms_sy_redis0 redis-cli ping
docker exec bt_nms_sy_redis_stream0 redis-cli ping
```

查看 Stream 堆积：

```bash
docker exec bt_nms_redis_stream0 redis-cli XLEN stream:udp:packets
docker exec bt_nms_redis_stream0 redis-cli XINFO GROUPS stream:udp:packets
docker exec bt_nms_sy_redis_stream0 redis-cli XLEN sy.raw
docker exec bt_nms_sy_redis_stream0 redis-cli XINFO GROUPS sy.raw
```

`pending` 长时间增加通常说明 receiver 消费异常或数据库写入异常。

### 数据库检查

```bash
docker exec bt_nms_postgres_db0 pg_isready -U myuser -d mydatabase
docker exec bt_nms_sy_postgres_db0 pg_isready -U myuser -d mydatabase
```

查看数据库大小：

```bash
docker exec bt_nms_postgres_db0 psql -U myuser -d mydatabase -c "select pg_size_pretty(pg_database_size('mydatabase'));"
docker exec bt_nms_sy_postgres_db0 psql -U myuser -d mydatabase -c "select pg_size_pretty(pg_database_size('mydatabase'));"
```

### 日志检查

BT：

```bash
docker logs --tail 100 bt_nms_django_app0
docker logs --tail 100 bt_nms_udp_receiver0
docker logs --tail 100 bt_nms_summarize_alarms_container0
docker logs --tail 100 bt_nms_celery_worker0
```

SY：

```bash
docker logs --tail 100 bt_nms_sy_django_app0
docker logs --tail 100 bt_nms_sy_receiver0
docker logs --tail 100 bt_nms_sy_summarize_alarms_container0
docker logs --tail 100 bt_nms_sy_celery_worker0
```

持续跟踪：

```bash
docker logs -f bt_nms_udp_receiver0
docker logs -f bt_nms_sy_receiver0
```

## 10. 备份

### 备份原则

- 数据库备份优先使用 `pg_dump`，不要只依赖复制 PostgreSQL 数据目录。
- 停机冷备可复制 `/srv/bt_nms_data`，但必须确保相关容器已停止。
- Redis 不持久化，不作为备份对象。
- Windows agent 的 `%ProgramData%\BT_NMS` 是现场配置来源，必须备份。
- 镜像和源码要分开管理，离线现场建议保留镜像 tar 包。

### 在线数据库备份

创建备份目录：

```bash
sudo mkdir -p /srv/bt_nms_data/backups
sudo chown "$(id -u):$(id -g)" /srv/bt_nms_data/backups
```

BT 数据库：

```bash
docker exec bt_nms_postgres_db0 pg_dump -U myuser -d mydatabase -Fc > /srv/bt_nms_data/backups/bt_$(date +%F_%H%M).dump
```

SY 数据库：

```bash
docker exec bt_nms_sy_postgres_db0 pg_dump -U myuser -d mydatabase -Fc > /srv/bt_nms_data/backups/sy_$(date +%F_%H%M).dump
```

校验备份文件：

```bash
ls -lh /srv/bt_nms_data/backups/*.dump
pg_restore -l /srv/bt_nms_data/backups/bt_2026-05-26_1530.dump >/dev/null
```

### 项目文件备份

在项目父目录执行：

```bash
rsync -av --delete --exclude-from=BT_NMS/.rsync-filter BT_NMS/ BT_NMS_backup/
```

当前 `.rsync-filter` 会排除 `.git/`、`udp_agent/.env`、`node_modules/`、`__pycache__/`、`*.log`、`.DS_Store`、`venv/`、`docs/`。如果需要备份文档，请调整排除规则或单独备份 `docs/`。

### 镜像备份

前端生产镜像：

```bash
docker save -o my_vue_prod.tar my_vue:prod
```

后端生产镜像：

```bash
docker save -o my_django_v5.0.6_prod.tar my_django:v5.0.6-prod
docker save -o my_django_v5.0.6_sy_prod.tar my_django:v5.0.6-sy-prod
```

受保护 Docker 镜像：

```bash
cd deploy/protected
./export_protected_images.sh
```

## 11. 恢复

### 数据库恢复前准备

恢复会覆盖数据库内容。执行前先确认：

- 已选择正确备份文件。
- 已停止会写数据库的业务容器。
- 当前数据库已另行备份，便于回滚。

停止 BT 写入服务：

```bash
docker stop bt_nms_django_app0 bt_nms_nginx0 bt_nms_udp_receiver0 bt_nms_summarize_alarms_container0 bt_nms_celery_worker0 bt_nms_celery_beat0
```

恢复 BT 数据库：

```bash
docker exec -i bt_nms_postgres_db0 pg_restore -U myuser -d mydatabase --clean --if-exists < /srv/bt_nms_data/backups/bt_2026-05-26_1530.dump
```

启动 BT 服务：

```bash
docker compose -f docker-compose-prod.yml up -d --no-deps --force-recreate web nginx udp_receiver summarize_alarms_container celery celery-beat
```

停止 SY 写入服务：

```bash
docker stop bt_nms_sy_django_app0 bt_nms_sy_nginx0 bt_nms_sy_receiver0 bt_nms_sy_summarize_alarms_container0 bt_nms_sy_celery_worker0 bt_nms_sy_celery_beat0
```

恢复 SY 数据库：

```bash
docker exec -i bt_nms_sy_postgres_db0 pg_restore -U myuser -d mydatabase --clean --if-exists < /srv/bt_nms_data/backups/sy_2026-05-26_1530.dump
```

启动 SY 服务：

```bash
docker compose -f docker-compose-sy-prod.yml up -d --no-deps --force-recreate web nginx sy_receiver summarize_alarms_container celery celery-beat
```

恢复后执行巡检：

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
curl -I http://127.0.0.1:38173/
curl -I http://127.0.0.1:8000/admin/
curl -I http://127.0.0.1:8001/admin/
```

## 12. 常见故障处理

### 前端打不开

检查：

```bash
docker ps | grep bt_nms_vue_prod0
docker logs --tail 100 bt_nms_vue_prod0
curl -I http://127.0.0.1:38173/
```

处理：

1. 容器未运行：`docker compose -f docker-compose-prod.vue.yml up -d --force-recreate`
2. 页面仍旧：强制刷新浏览器；本地 dist 模式下重新执行 `npm run build`。
3. 端口冲突：临时使用 `VUE_PORT=38174 docker compose -f docker-compose-prod.vue.yml up -d --force-recreate`。

### 后端 admin/API 打不开

检查：

```bash
docker logs --tail 100 bt_nms_django_app0
docker logs --tail 100 bt_nms_nginx0
docker logs --tail 100 bt_nms_sy_django_app0
docker logs --tail 100 bt_nms_sy_nginx0
```

处理：

1. Django 未健康：检查 Postgres、Redis 是否 ready。
2. Nginx 等待 web：重启 `web`，健康后再重启 `nginx`。
3. 局域网 IP 访问报 CSRF/跨域：检查 `backend/deploy_host_ip.txt` 或 `sy_backend/deploy_host_ip.txt`，修改后重启 Django 和 Nginx。

### 页面没有实时数据

BT 检查：

```bash
docker exec bt_nms_redis_stream0 redis-cli XLEN stream:udp:packets
docker exec bt_nms_redis_stream0 redis-cli XINFO GROUPS stream:udp:packets
docker logs --tail 100 bt_nms_udp_receiver0
```

SY 检查：

```bash
docker exec bt_nms_sy_redis_stream0 redis-cli XLEN sy.raw
docker exec bt_nms_sy_redis_stream0 redis-cli XINFO GROUPS sy.raw
docker logs --tail 100 bt_nms_sy_receiver0
```

判断：

- Stream 长度一直为 0：agent 没写入、Redis host/port 不对、网络或防火墙不通。
- Stream 有数据但 pending 增长：receiver 或数据库写入异常。
- receiver 正常但页面无变化：检查 `summarize_alarms_container` 日志。

### Agent 连接不上 Redis

检查：

```bash
docker ps | grep redis_stream
docker exec bt_nms_redis_stream0 redis-cli ping
docker exec bt_nms_sy_redis_stream0 redis-cli ping
```

处理：

1. 同机部署：agent Redis host 使用 `127.0.0.1`，BT 端口 `36379`，SY 端口 `36380`。
2. 跨机器部署：agent Redis host 使用后端部署机 IP，确认防火墙放行对应端口。
3. Windows 受保护部署：检查 `%ProgramData%\BT_NMS\...\config.json`，不要只改源码目录里的旧配置。

### 告警延时开关修改后不生效

BT 文件：`backend/alarm_delay_switch_bt.py`
SY 文件：`sy_backend/alarm_delay_switch_sy.py`

修改后重启汇总容器：

```bash
docker restart bt_nms_summarize_alarms_container0
docker restart bt_nms_sy_summarize_alarms_container0
```

### 数据库迁移失败

检查：

```bash
docker logs --tail 100 bt_nms_django_app0
docker exec bt_nms_postgres_db0 pg_isready -U myuser -d mydatabase
docker exec bt_nms_django_app0 python manage.py showmigrations
```

处理：

1. 先备份数据库。
2. 确认 Django 容器和 PostgreSQL 使用同一套数据库配置。
3. 依赖或模型变更导致失败时，不要反复重启覆盖现场状态，先保存日志再处理迁移脚本。

### 磁盘空间不足

检查：

```bash
df -h
docker system df
du -sh /srv/bt_nms_data/*
```

处理建议：

1. 先备份数据库。
2. 清理旧镜像和未使用构建缓存：`docker system prune`。
3. 清理前确认不会删除现场仍需回滚的镜像 tar 或历史镜像。
4. 不要直接删除 PostgreSQL 数据目录。

## 13. 安全与账号

默认超级用户由生产 entrypoint 自动创建：

- 用户名：`admin`
- 邮箱：`admin@example.com`
- 密码：`admin`

现场正式交付后必须修改默认密码。

修改密码：

```bash
docker exec -it bt_nms_django_app0 python manage.py changepassword admin
docker exec -it bt_nms_sy_django_app0 python manage.py changepassword admin
```

建议：

- 后端管理端口只开放给运维网段。
- Redis Streams 端口只开放给 agent 所在机器。
- 生产环境保持 `DEBUG=false`。
- 备份文件、镜像 tar 和 Windows `%ProgramData%\BT_NMS` 配置不要外发。

## 14. 变更发布检查单

发布前：

- 已确认修改范围：前端、后端、数据库迁移、agent、配置文件。
- 已备份数据库和 Windows agent 配置。
- 已记录当前运行镜像和容器状态。
- 已确认部署机器磁盘空间足够。

发布中：

- 前端小改动优先使用 `frontend/dist` 挂载模式。
- 后端 Python 小改动优先重建容器，不必盲目重新 build。
- 涉及依赖、Dockerfile、基础镜像时才重新 build。
- 数据库迁移先在可控环境验证，再在生产执行。

发布后：

- `docker ps` 状态正常。
- 前端、BT admin、SY admin 可访问。
- agent 正常连接 Redis Streams。
- `udp_receiver` / `sy_receiver` 无持续报错。
- Stream pending 没有持续增长。
- 页面实时数据、告警确认、命令下发做一次抽检。

## 15. 紧急回滚

前端回滚：

1. 如果使用本地 `dist` 挂载，恢复上一份 `frontend/dist` 备份后刷新页面。
2. 如果使用镜像，导入旧镜像 tar 后重建前端容器：

```bash
docker load -i my_vue_prod_old.tar
docker compose -f docker-compose-prod.vue.yml up -d --no-deps --force-recreate vue
```

后端回滚：

1. 停止相关写入服务。
2. 切回上一版源码或导入上一版镜像。
3. 如已执行不可逆迁移，按数据库备份恢复流程恢复数据库。
4. 启动服务并执行巡检。

数据库回滚：

按第 11 节从发布前备份恢复。

## 16. 附录：常用命令速查

```bash
# BT 生产整体启动/更新
docker compose -f docker-compose-prod.yml up -d --build --remove-orphans

# SY 生产整体启动/更新
docker compose -f docker-compose-sy-prod.yml up -d --build --remove-orphans

# 独立生产前端
docker compose -f docker-compose-prod.vue.yml up -d --force-recreate

# BT 日志
docker logs --tail 100 bt_nms_django_app0
docker logs --tail 100 bt_nms_udp_receiver0
docker logs --tail 100 bt_nms_summarize_alarms_container0

# SY 日志
docker logs --tail 100 bt_nms_sy_django_app0
docker logs --tail 100 bt_nms_sy_receiver0
docker logs --tail 100 bt_nms_sy_summarize_alarms_container0

# BT 数据库备份
docker exec bt_nms_postgres_db0 pg_dump -U myuser -d mydatabase -Fc > /srv/bt_nms_data/backups/bt_$(date +%F_%H%M).dump

# SY 数据库备份
docker exec bt_nms_sy_postgres_db0 pg_dump -U myuser -d mydatabase -Fc > /srv/bt_nms_data/backups/sy_$(date +%F_%H%M).dump

# BT 迁移
docker exec -it bt_nms_django_app0 python manage.py migrate

# SY 迁移
docker exec -it bt_nms_sy_django_app0 python manage.py migrate
```
