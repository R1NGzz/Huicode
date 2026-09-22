# HuiCode Studio Web 化与任务平台 Tasks

## 学习与工程记录交付约定

本项目实施的首要目标是提升用户全栈能力和面试竞争力。T1–T26 均须同步遵循 [全栈实践与面试证据库](../../docs/web-studio-learning/README.md)，每个任务或紧密关联任务组交付学习记录，内容包含原理、方案取舍、实际工程问题、代码/测试证据、复现实验和面试追问。各里程碑结束补充阶段复盘。

记录区分设计风险、故障注入和实际故障；未经验证不得写成已完成成果，不替用户认定已掌握知识。学习材料与代码同步交付，用户是否完成练习不阻断实施。

## File List

| Action | File | Responsibility |
| --- | --- | --- |
| Modify | `pyproject.toml` | 增加 Web API、数据库、认证、Redis 和测试依赖及启动入口 |
| Create | `huicode/server/app.py` | 创建 FastAPI 应用和生命周期管理 |
| Create | `huicode/server/config.py` | 服务端环境配置与运行限制 |
| Create | `huicode/server/auth/*` | 认证、Token、工作区角色和 API 鉴权 |
| Create | `huicode/server/db/*` | ORM 模型、数据库会话、Repository 和迁移支持 |
| Create | `huicode/server/domain/*` | 项目、会话、Run、审批、审计和用量业务规则 |
| Create | `huicode/server/events/*` | Runtime Event、持久化、发布、订阅和 SSE |
| Create | `huicode/server/runtime/*` | Agent 适配、取消、预算、权限桥接、执行边界和脱敏 |
| Create | `huicode/server/workers/*` | 队列、Worker、租约、心跳、恢复和幂等控制 |
| Create | `huicode/server/api/*` | REST API 的请求模型、路由和响应模型 |
| Create | `migrations/*` | 数据库初始迁移及后续迁移目录 |
| Create | `web/*` | React + TypeScript 前端工作台 |
| Create | `deploy/*` | API、Web、Worker 和基础设施的容器编排 |
| Create | `tests/server/*` | 服务端单元和集成测试 |
| Create | `tests/integration/*` | 数据库、事件、Worker 和 Agent Runtime 集成测试 |
| Create | `tests/e2e/*` | 浏览器端到端测试 |
| Create | `docs/web-studio-local-development.md` | 本地开发和启动文档 |
| Create | `docs/production-hardening.md` | 可靠性、安全边界和限制说明 |
| Create | `docs/incident-runbook.md` | 常见故障排查、恢复和回滚步骤 |

## T1: 建立服务端依赖和配置边界

**最新进度（2026-09-22）：已完成本任务验证。** 项目 .venv 依赖安装成功，pip check 通过，新旧配置测试通过，正确索引为 https://pypi.org/simple。下段为历史状态。

**进度（2026-09-19）：** 已增加可选依赖声明、配置加载器、环境变量模板和 9 项通过的专用测试。依赖安装与服务启动未验证；旧配置回归被当前解释器缺少 PyYAML 阻挡，T1 尚未整体标记完成。[学习记录](../../docs/web-studio-learning/T01-server-configuration.md)。

**Files:** `pyproject.toml`, `huicode/server/config.py`, `.env.example`

**Dependencies:** None

**Steps:**
1. 增加 FastAPI、Uvicorn、SQLAlchemy、Alembic、数据库驱动、Redis、认证和密码哈希依赖。
2. 为数据库 URL、Redis URL、JWT secret、项目根目录、CORS、运行预算和日志级别定义配置项。
3. 区分开发、测试和生产配置，禁止在代码中写入默认密钥。
4. 增加配置校验，缺少生产必需 secret 时启动失败。

**Verification:** 运行配置单元测试；使用合法和缺失配置分别启动，确认错误信息可读且不打印密钥。

## T2: 创建 FastAPI 应用骨架

**最新进度（2026-09-22）：应用骨架验证完成。** 配置/API 31 项测试及 CLI 13 项回归通过；真实 Uvicorn live=200、离线 ready=503、未知路由=404，request_id 匹配。真实数据库在线探测留待后续集成，Worker 生命周期/心跳随 T15 接入，不视为已经完成。下段为历史状态。

**进度（2026-09-22）：** 应用工厂、lifespan、数据库/Redis 有界探测、请求 ID、安全错误响应和接口测试已编写。依赖安装无法获取 setuptools，HTTP 测试及 Uvicorn 启动尚未验证。Worker 心跳需等 T15 接入；API 不负责启动独立 Worker。见 [学习记录](../../docs/web-studio-learning/T02-api-lifecycle.md)。

**Files:** `huicode/server/app.py`, `huicode/server/api/health.py`, `huicode/server/api/__init__.py`

**Dependencies:** T1

**Steps:**
1. 创建应用工厂和 `/health/live`、`/health/ready` 接口。
2. 添加 request ID 中间件、统一异常响应和访问日志字段。
3. 添加数据库、Redis 和 Worker 生命周期钩子。
4. 暴露开发启动命令，并保持 `huicode` CLI 入口不变。

**Verification:** 启动 Uvicorn，访问两个健康接口；确认 API 错误包含 `request_id`，CLI 现有启动测试继续通过。

## T3: 建立数据库基础设施

**进度（2026-09-22）：** 已实现 Database/Session 事务封装、UUID/时间字段约定、工作区 Repository 与 Alembic 异步迁移入口；现有健康检查复用 Database。SQLite 提交、异常/取消回滚、工作区范围等 5 项测试通过，连同配置/API 共 36 项通过。Alembic 离线入口通过，尚无业务迁移（T4）。Docker 引擎不可用，PostgreSQL 在线验证待补；不声称已完成真实 PostgreSQL 验收。[学习记录](../../docs/web-studio-learning/T03-database-transactions.md)。

**Files:** `huicode/server/db/base.py`, `huicode/server/db/session.py`, `huicode/server/db/models.py`, `huicode/server/db/repositories/__init__.py`, `migrations/env.py`

**Dependencies:** T1

**Steps:**
1. 配置 SQLAlchemy async engine、session factory 和事务上下文。
2. 建立统一 Base、时间字段和 UUID 字段约定。
3. 配置 Alembic 异步迁移入口。
4. 定义 Repository 的 workspace scope 约束，禁止 API 层执行无范围全表查询。

**Verification:** 使用测试数据库创建连接、提交事务、回滚事务；执行 Alembic 检查，确认迁移环境可加载。

## T4: 实现核心数据模型和初始迁移

**Files:** `huicode/server/db/models.py`, `migrations/versions/0001_initial.py`

**Dependencies:** T3

**Steps:**
1. 创建 User、Workspace、WorkspaceMember、Project、Session、Run、SessionEvent、ToolApproval、AuditLog、Artifact 和 UsageRecord 模型。
2. 为 workspace、session、run、sequence、status 和时间字段建立索引。
3. 为 SessionEvent 增加 `(session_id, sequence)` 唯一约束。
4. 为 Run、Approval 和 Tool Call 预留幂等键或执行记录字段。
5. 生成初始迁移。

**Verification:** 在空数据库执行升级和降级；插入一组关联数据，确认外键、唯一约束和 workspace 查询索引生效。

## T5: 实现认证、Token 和工作区角色

**Files:** `huicode/server/auth/passwords.py`, `huicode/server/auth/tokens.py`, `huicode/server/auth/dependencies.py`, `huicode/server/auth/permissions.py`, `huicode/server/api/auth.py`

**Dependencies:** T4

**Steps:**
1. 实现密码哈希和校验，禁止保存明文密码。
2. 实现 access token、refresh token 和当前用户依赖。
3. 实现注册、登录、退出、刷新和当前用户接口。
4. 创建首个用户时创建默认工作区和 owner 成员关系。
5. 实现 member、admin、owner、viewer 的角色判断。

**Verification:** API 测试覆盖注册、错误密码、过期 Token、刷新 Token 和角色拒绝；确认响应和日志不包含密码或 Token 原文。

## T6: 实现工作区、项目和路径解析

**Files:** `huicode/server/domain/projects.py`, `huicode/server/runtime/workspace_resolver.py`, `huicode/server/api/workspaces.py`, `huicode/server/api/projects.py`

**Dependencies:** T4, T5

**Steps:**
1. 实现工作区列表、创建和成员查询。
2. 实现项目创建、列表、重命名和归档。
3. 限制项目路径必须位于服务端配置的项目根目录。
4. 解析并检查 `..`、符号链接、Windows junction 和绝对路径。
5. 为所有项目和文件相关 service 强制注入 workspace scope。

**Verification:** API 测试覆盖跨工作区访问、路径穿越、符号链接和归档项目写入；所有非法路径均被拒绝并记录审计事件。

## T7: 建立统一 Runtime Event 类型

**Files:** `huicode/server/events/types.py`, `huicode/server/events/mapper.py`, `tests/server/test_event_types.py`

**Dependencies:** T4

**Steps:**
1. 定义带 event_id、run_id、session_id、sequence、timestamp、type 和 payload 的事件模型。
2. 定义文本增量、工具生命周期、审批、使用量、错误、取消和完成事件。
3. 实现现有 `AgentEvent` 到 RuntimeEvent 的映射。
4. 对用户可见 payload 和内部 payload 设置 visibility。

**Verification:** 单元测试覆盖所有事件类型的序列化、反序列化和未知事件兼容行为。

## T8: 实现事件持久化、发布和补偿

**Files:** `huicode/server/events/store.py`, `huicode/server/events/publisher.py`, `huicode/server/events/subscriber.py`, `tests/integration/test_event_store.py`

**Dependencies:** T4, T7

**Steps:**
1. 实现事务内追加事件和 session 内 sequence 分配。
2. 实现按 sequence 查询缺失事件。
3. 实现数据库提交后发布 Redis 通知。
4. 实现 Redis 不可用时的数据库补偿路径。
5. 实现重复事件 ID 的幂等写入。

**Verification:** 集成测试覆盖并发追加、sequence 连续性、重复写入、发布失败和断点补偿。

## T9: 增加 Runtime 取消和资源预算

**Files:** `huicode/server/runtime/cancellation.py`, `huicode/server/runtime/limits.py`, `huicode/server/runtime/executor.py`, `tests/server/test_runtime_limits.py`

**Dependencies:** T7

**Steps:**
1. 实现 CancellationToken 及其状态传播。
2. 实现 Run、Tool、Shell、迭代、工具调用和输出大小预算。
3. 在模型请求前、工具调用前后和每轮 Agent Loop 检查取消与预算。
4. 统一产生超时、预算耗尽和取消错误码。

**Verification:** 测试取消运行中的任务、超时模型请求、超时工具、超大输出和最大迭代；确认任务进入正确终态。

## T10: 实现工具能力和权限桥接

**Files:** `huicode/server/runtime/permission_bridge.py`, `huicode/server/runtime/capabilities.py`, `huicode/tools/base.py`, `tests/integration/test_permission_bridge.py`

**Dependencies:** T6, T9

**Steps:**
1. 为工具增加只读、文件写入、Shell、网络和外部副作用能力声明。
2. 将现有 PermissionContext、Plan Mode 和工具权限规则接入服务端运行时。
3. 确保 Web 请求无法通过参数跳过权限判断。
4. 将权限决定映射为统一审批事件或拒绝事件。

**Verification:** 使用不同权限模式和工具能力运行同一任务；确认拒绝、需要审批和允许三种路径符合现有 CLI 语义。

## T11: 实现 SecretScrubber

**Files:** `huicode/server/runtime/scrubber.py`, `huicode/memory/scrub.py`, `tests/server/test_scrubber.py`

**Dependencies:** T7

**Steps:**
1. 统一识别 API key、Authorization、Cookie、Password、Token、私钥和常见环境变量。
2. 提供文本、字典、异常和事件 payload 的脱敏接口。
3. 在事件持久化、日志、审计、Artifact 和 API 响应前接入脱敏。
4. 保留内部错误分类，但不保存原始敏感值。

**Verification:** 使用测试密钥注入模型消息、工具输出、异常和环境变量；确认所有用户可见存储和响应均为脱敏值。

## T12: 实现受控本地 ExecutionBackend

**Files:** `huicode/server/runtime/execution_backend.py`, `huicode/tools/shell.py`, `tests/integration/test_execution_backend.py`

**Dependencies:** T6, T9, T10

**Steps:**
1. 抽象 ExecutionBackend 接口。
2. 将现有 Shell 工具封装为受控本地后端。
3. 强制工作目录和文件路径经过 WorkspacePathResolver。
4. 实现命令超时、输出截断、子进程树终止和环境变量过滤。
5. 预留 Docker 或远程后端的实现边界，但暂不实现容器调度。

**Verification:** 测试危险命令、路径逃逸、超时进程、子进程树、超大输出和非法环境变量；确认所有失败都有明确错误码。

## T13: 实现会话和 Run 领域服务

**Files:** `huicode/server/domain/sessions.py`, `huicode/server/domain/runs.py`, `huicode/server/api/sessions.py`, `huicode/server/api/runs.py`

**Dependencies:** T4, T7, T9, T10

**Steps:**
1. 实现项目内会话创建、列表、读取和重命名。
2. 实现消息提交时创建 Run 和 `run_queued` 事件。
3. 实现 Run 状态机和合法状态转移检查。
4. 实现取消、重试和当前状态查询。
5. 为写操作增加 Idempotency-Key。

**Verification:** API 测试覆盖合法和非法状态转移、重复提交、跨工作区访问、取消和重试。

## T14: 实现审批 Broker 和幂等审批

**Files:** `huicode/server/runtime/approval_broker.py`, `huicode/server/domain/approvals.py`, `huicode/server/api/approvals.py`, `tests/integration/test_approvals.py`

**Dependencies:** T8, T10, T13

**Steps:**
1. 创建审批记录并发布 `tool_approval_requested` 事件。
2. 实现允许、拒绝、取消和过期状态。
3. 校验用户角色、workspace、run、tool_call 和审批有效期。
4. 使用 approval_id 和幂等键防止重复释放工具。
5. 将决定传给等待中的 Worker。

**Verification:** 集成测试覆盖审批等待、允许、拒绝、过期、重复点击和无权限操作。

## T15: 实现 RunLease、Worker 心跳和恢复

**Files:** `huicode/server/workers/queue.py`, `huicode/server/workers/agent_worker.py`, `huicode/server/workers/heartbeat.py`, `huicode/server/workers/recovery.py`, `huicode/server/workers/idempotency.py`, `tests/integration/test_worker_recovery.py`

**Dependencies:** T8, T9, T13, T14

**Steps:**
1. 实现任务入队、领取和租约记录。
2. Worker 执行期间更新 heartbeat 和 lease expiry。
3. 实现任务完成、失败、取消和人工处理状态的幂等写入。
4. 启动恢复扫描，识别过期任务。
5. 根据已完成工具记录和 retry policy 决定重试或标记不可安全恢复。
6. 记录 recovery 和 dead-letter 事件。

**Verification:** 集成测试中强制终止 Worker，重启后确认可恢复任务重试、不可恢复任务不重复执行，并且审计完整。

## T16: 接入现有 Agent Loop

**Files:** `huicode/server/runtime/agent_executor.py`, `huicode/agent.py`, `huicode/agent_events.py`, `tests/integration/test_agent_executor_contract.py`

**Dependencies:** T7, T9, T10, T11, T12, T15

**Steps:**
1. 实现 AgentRunRequest、AgentRunExecutor 和 PermissionSnapshot 适配器。
2. 将现有 AgentEvent 转换为 RuntimeEvent。
3. 将工具审批、取消、预算和项目路径传入运行上下文。
4. 确保 CLI 仍使用原有 Agent Loop，不复制 Web 专用循环。
5. 在 Worker 中隔离同步 Agent Loop，避免阻塞 API 事件循环。

**Verification:** 使用真实 Provider mock 和测试工具完成多轮 Agent Loop；确认工具调用、审批、取消、错误和 usage 都能落到事件流。

## T17: 实现 SSE 事件接口

**Files:** `huicode/server/events/sse.py`, `huicode/server/api/events.py`, `tests/integration/test_sse_replay.py`

**Dependencies:** T8, T13, T15, T16

**Steps:**
1. 实现 session event stream。
2. 支持 `Last-Event-ID` 和 `after` sequence 补偿。
3. 先发送数据库缺失事件，再订阅实时通知。
4. 处理客户端断开、Redis 断连和重复事件。
5. 只推送当前用户可见的事件 payload。

**Verification:** 测试任务运行中断开和重连；确认事件按序补齐、不重复、越权事件不泄露。

## T18: 实现时间线、Diff 和 Artifact API

**Files:** `huicode/server/domain/artifacts.py`, `huicode/server/api/artifacts.py`, `huicode/server/api/timeline.py`, `tests/server/test_artifacts.py`

**Dependencies:** T6, T8, T11, T16

**Steps:**
1. 保存工具输出摘要和完整 Artifact 引用。
2. 实现 Run 时间线查询。
3. 实现受控项目 Diff 计算。
4. 对 Diff、工具输出和文件快照应用权限和脱敏。
5. 限制 Artifact 大小和保留时间。

**Verification:** 完成一次写文件任务，查询时间线和 Diff；确认 workspace 外文件和敏感 Artifact 无法读取。

## T19: 创建 React 前端骨架

**Files:** `web/package.json`, `web/vite.config.ts`, `web/src/main.tsx`, `web/src/app/*`, `web/src/types/*`

**Dependencies:** T2, T17

**Steps:**
1. 创建 React + TypeScript + Vite 项目。
2. 配置路由、基础布局、环境变量和 API base URL。
3. 定义与服务端一致的 API 和 Runtime Event 类型。
4. 配置前端 lint、类型检查和测试入口。

**Verification:** `npm run build`、类型检查和前端测试通过；打开应用可以看到登录页和空状态工作区。

## T20: 实现前端认证和项目页面

**Files:** `web/src/auth/*`, `web/src/features/dashboard/*`, `web/src/features/projects/*`, `web/src/api/*`

**Dependencies:** T5, T6, T19

**Steps:**
1. 实现注册、登录、退出和 Token 刷新。
2. 实现工作区和项目列表、创建、重命名和归档。
3. 对 API 错误显示稳定的用户提示。
4. 对未登录和无权限状态实现路由保护。

**Verification:** 前端组件测试覆盖登录失败、Token 过期和项目权限；浏览器可以完成登录到项目打开。

## T21: 实现会话、聊天和实时事件 Store

**Files:** `web/src/features/sessions/*`, `web/src/features/agent-chat/*`, `web/src/stores/run-events.ts`, `web/src/api/sse.ts`

**Dependencies:** T13, T17, T19, T20

**Steps:**
1. 实现会话列表、创建和重命名。
2. 实现发送消息并显示 Run 状态。
3. 实现 SSE 连接、断线重连、sequence 去重和事件合并。
4. 显示文本增量、工具生命周期、usage、错误和完成状态。
5. 页面刷新后根据服务端状态恢复当前 Run。

**Verification:** 前端集成测试和浏览器测试覆盖实时输出、网络断开恢复和重复事件。

## T22: 实现审批、时间线和 Diff 页面

**Files:** `web/src/features/approvals/*`, `web/src/features/timeline/*`, `web/src/features/diff-viewer/*`

**Dependencies:** T14, T18, T21

**Steps:**
1. 显示待审批工具、风险级别、目标资源和摘要。
2. 实现允许、拒绝和取消按钮，并处理重复提交。
3. 实现 Run 时间线和错误详情。
4. 实现文件 Diff、工具输出摘要和脱敏提示。

**Verification:** 浏览器测试覆盖审批等待到继续执行、拒绝后的安全终止和完成后的 Diff 查看。

## T23: 增加部署编排和运维配置

**Files:** `deploy/Dockerfile.api`, `deploy/Dockerfile.web`, `deploy/docker-compose.yml`, `deploy/nginx.conf`, `docs/web-studio-local-development.md`

**Dependencies:** T2, T5, T15, T19

**Steps:**
1. 编写 API、Worker 和 Web 镜像。
2. 编排 PostgreSQL、Redis、API、Worker、Web 和 Nginx。
3. 添加 healthcheck、迁移命令和本地 seed 数据。
4. 提供 `.env.example` 和启动、停止、查看日志文档。
5. 确保敏感配置只从环境变量读取。

**Verification:** 在干净环境执行 Compose 启动；完成数据库迁移、登录和一次 Agent 任务；停止并重新启动后数据仍存在。

## T24: 增加可靠性、安全和故障注入测试

**Files:** `tests/server/test_authorization.py`, `tests/server/test_security_boundaries.py`, `tests/integration/test_failure_injection.py`, `tests/integration/test_idempotency.py`

**Dependencies:** T6, T9, T10, T11, T12, T15, T17

**Steps:**
1. 测试 workspace 越权、路径穿越、符号链接和危险命令。
2. 测试取消、超时、输出预算和最大迭代。
3. 测试重复 Run、审批、Tool Call 和 Worker 消息。
4. 测试 Worker 崩溃、Redis 断连、事件发布失败和数据库回滚。
5. 测试敏感信息在终端、事件、日志和 API 中的脱敏。

**Verification:** 运行服务端和集成测试；每个失败注入场景都能得到确定的终态和审计记录。

## T25: 增加端到端场景和 CLI 回归

**Files:** `tests/e2e/test_web_studio.py`, `tests/e2e/fixtures/*`, existing `tests/*`, `docs/production-hardening.md`, `docs/incident-runbook.md`

**Dependencies:** T20, T21, T22, T23, T24

**Steps:**
1. 编写“注册/登录 → 创建项目 → 创建会话 → 发起任务”的 E2E 场景。
2. 编写工具审批、拒绝、取消、断线恢复和查看 Diff 的 E2E 场景。
3. 保留并运行现有 CLI、Agent、权限、工具和 Team 测试。
4. 编写生产加固说明，包括限制、日志定位、任务恢复、备份和回滚。
5. 编写故障 Runbook，覆盖 API、Worker、数据库、Redis 和事件流故障。

**Verification:** 使用 Docker Compose 环境运行完整 E2E；现有回归测试无新增失败；按照 Runbook 实际完成一次任务恢复演练。

## T26: CI、类型检查和发布门禁

**Files:** `.github/workflows/ci.yml`, `pyproject.toml`, `web/package.json`, `README.md`

**Dependencies:** T23, T24, T25

**Steps:**
1. 配置 Python 单元测试、集成测试和类型检查。
2. 配置前端 lint、类型检查、单元测试和构建。
3. 在 CI 中启动依赖服务或使用测试容器运行数据库集成测试。
4. 添加迁移检查、镜像构建和 E2E 发布门禁。
5. 更新 README 的开发、测试和 Web 启动说明。

**Verification:** 提交一次无关紧要的 CI 变更验证流水线全绿；故意引入测试或类型错误确认门禁能够失败。

## Execution Order

```text
T1 → T2 → T3 → T4
              ├→ T5 → T6
              ├→ T7 → T8
              └→ T11

T6 + T7 → T9 → T10 → T12
T8 + T9 + T13 → T14 → T15 → T16 → T17
T11 + T16 → T18
T2 + T5 + T6 + T17 → T19 → T20 → T21 → T22
T15 + T19 → T23
T6 + T9 + T10 + T11 + T12 + T15 + T17 → T24
T20 + T21 + T22 + T23 + T24 → T25 → T26
```

## Milestones

### M1: 服务端和 Runtime 基础

完成 T1-T12。目标是 API 骨架、数据模型、事件模型、取消、资源预算、路径安全、Shell 限制和脱敏能力可独立测试。

### M2: 可恢复的 Agent Run

完成 T13-T18。目标是一次 Run 能够被创建、执行、审批、取消、恢复、回放并生成 Diff。

### M3: Web 工作台

完成 T19-T22。目标是浏览器可以登录、创建项目、实时运行任务、审批工具、断线恢复并查看结果。

### M4: 部署和验收

完成 T23-T26。目标是 Docker Compose 一键运行、故障可定位、E2E 可重复、CLI 不回归。
