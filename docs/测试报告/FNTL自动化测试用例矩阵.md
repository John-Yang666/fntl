# FNTL 自动化测试用例矩阵

## 运行入口

| 范围 | 命令 | 验收标准 |
| --- | --- | --- |
| BT 后端 | `cd /Users/yangzijiang/BT_NMS && docker compose -f docker-compose.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py test myapp -v 2` | Django 测试全部通过，使用 Docker PostgreSQL/Redis 测试路径 |
| SY 后端 | `cd /Users/yangzijiang/BT_NMS && docker compose -f docker-compose-sy.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py test myapp -v 2` | Django 测试全部通过，使用 Docker PostgreSQL/Redis 测试路径 |
| Agent/客户端 | `cd /Users/yangzijiang/BT_NMS && python -m unittest discover -s alarm_client/tests && python -m unittest discover -s bt_agent_serial/tests` | unittest 全部通过，不依赖硬件和真实 Redis |
| 前端 | `cd /Users/yangzijiang/BT_NMS/frontend && npm run test:unit && npm run build` | Vitest 单测通过，生产构建成功 |
| 虚拟后端/E2E | `cd /Users/yangzijiang/BT_NMS/virtual-backend && npm run test:unit && npm run test:e2e` | simulator 单测和 Playwright 浏览器流程全部通过 |
| 全量分层回归 | `bash /Users/yangzijiang/BT_NMS/scripts/run-fntl-regression.sh` | 串联以上所有步骤并返回 0 |

## 用例矩阵

| ID | 层级 | 覆盖模块 | 自动化位置 | 验收点 |
| --- | --- | --- | --- | --- |
| FNTL-BT-API-001 | BT 后端 | 认证、设备范围隔离、命令审计 | `backend/myapp/test_security_api.py`、`backend/myapp/test_ops_api.py` | 未认证拒绝、越权设备 404、审计使用当前登录用户 |
| FNTL-BT-API-002 | BT 后端 | 记录查询/count/export | `backend/myapp/test_records_api.py` | 历史告警、继电器、用户操作、开关量、电压电流按权限过滤，导出 CSV 正确 |
| FNTL-BT-API-003 | BT 后端 | 运行参数、清理导出 | `backend/myapp/test_runtime_config.py`、`backend/myapp/test_cleanup_tasks.py` | 超级用户权限、配置保存审计、清理计划和导出失败保护 |
| FNTL-BT-AGENT-001 | BT 协议 | UDP/串口帧、校验、Redis Stream 字段 | `backend/myapp/test_bt_agent_serial_ingest.py`、`bt_agent_serial/tests/test_protocol.py` | 帧重同步、校验失败、Stream 字段、开关量/继电器解析 |
| FNTL-SY-API-001 | SY 后端 | 认证、设备范围隔离、命令审计 | `sy_backend/myapp/test_security_api.py` | A1/BB 命令鉴权、越权拒绝、BB 参数校验和审计 |
| FNTL-SY-API-002 | SY 后端 | 记录查询/count/export | `sy_backend/myapp/test_records_api.py` | 历史告警、继电器、用户操作、开关量按权限过滤，导出 CSV 正确 |
| FNTL-SY-API-003 | SY 后端 | 运行参数、清理导出 | `sy_backend/myapp/test_runtime_config.py`、`sy_backend/myapp/test_cleanup_tasks.py` | 超级用户权限、SY 告警延时、清理计划和导出失败保护 |
| FNTL-SY-PROTO-001 | SY 协议 | A1/A2/AA/BB/CC 打帧、Redis Stream | `sy_backend/myapp/test_sy_command_sender.py`、`sy_backend/myapp/tests.py` | 命令帧、变化位事件、去重、拓扑推送和通信超时告警 |
| FNTL-FE-UNIT-001 | 前端单测 | 系统 URL、WebSocket 协议、设备选择、状态解析 | `frontend/src/utils/__tests__/*.test.ts` | BT/SY API/WS 基址、token protocol、IndexedDB 迁移、开关量解析 |
| FNTL-FE-UNIT-002 | 前端单测 | 用户状态和 token 刷新 | `frontend/src/stores/__tests__/userStore.test.ts` | 登录态保存、401 刷新重试、请求头携带 Bearer token |
| FNTL-VBE-001 | 虚拟后端 | BT/SY simulator HTTP/WS | `virtual-backend/electron/simulator/*.test.ts` | 设备列表、拓扑状态、当前告警、命令记录、WebSocket 推送 |
| FNTL-VBE-002 | 虚拟后端 | 运维、系统设置、帮助、文件管理模拟接口 | `virtual-backend/electron/simulator/backendServer.test.ts` | `/api/ops/*`、`/api/runtime-config/`、`/api/help-faq/`、`/api/uploaded-files/` 兼容前端 |
| FNTL-E2E-001 | 浏览器 E2E | 登录、主界面、拓扑、当前告警、记录、运维 | `virtual-backend/e2e/fntl-regression.spec.ts` | 登录成功、拓扑工具可用、告警确认、记录页签、运维筛选和页签切换 |
| FNTL-E2E-002 | 浏览器 E2E | 帮助/文件管理、系统设置 BT/SY 切换 | `virtual-backend/e2e/fntl-regression.spec.ts` | FAQ 加载、BT/SY 文件页签、SY 参数页、清理导出测试 |

## 说明

默认回归的后端阶段使用 Docker Compose 中的 PostgreSQL/Redis，并在 Django 测试前设置 `FNTL_TEST_REAL_SERVICES=1`，避免后端清理、索引、事务等行为只在 sqlite/locmem 路径验证。脚本会记录测试前已运行的 compose 服务，测试后只停止本次新启动的 `db`、`redis`、`redis_stream`。

如需离线快速验证，可使用 `FNTL_BACKEND_TEST_MODE=local bash /Users/yangzijiang/BT_NMS/scripts/run-fntl-regression.sh`，此模式使用本机 Python、sqlite 和 locmem，仅作为开发备用路径，不作为 CI/正式回归的后端验收标准。
