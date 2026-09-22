# HuiCode Studio Web 化与任务平台 Plan

## Architecture Overview

第一期采用“模块化单体 API + 独立任务 Worker + React Web”的架构，不拆成多个微服务。这样可以复用现有 HuiCode Python Runtime，同时把长时间运行的 Agent 任务从 HTTP 请求生命周期中隔离出来。

```text
┌──────────────────────────────────────────────────────────────┐
│ React + TypeScript Web                                      │
│ Dashboard / Workspace / Chat / Approval / Timeline / Diff   │
└───────────────┬───────────────────────────┬──────────────────┘
                │ REST                       │ SSE
                ▼                            ▼
┌──────────────────────────────────────────────────────────────┐
│ FastAPI Application                                           │
│ Auth / Projects / Sessions / Runs / Approvals / Audit         │
│ API authorization + SSE event replay                          │
└───────────────┬───────────────────────────┬──────────────────┘
                │ SQLAlchemy                 │ Redis queue/events
                ▼                            ▼
         PostgreSQL                    Agent Worker
                                      │
                                      ▼
                               HuiCode Runtime
                         Agent Loop / Tools / MCP
                         Permissions / Skills / Teams
                                      │
                                      ▼
                              Project Workspace
```

核心原则：

1. Web 层只负责请求、鉴权、状态查询和事件传输，不复制 Agent Loop。
2. Agent Runtime 通过适配器被 Worker 调用，现有 CLI 继续使用原有入口。
3. 所有面向用户的状态变化都先转换为带序号的 Runtime Event，再持久化和推送。
4. 权限判断仍由现有权限引擎完成，Web 端只负责展示审批和提交决定。
5. 任务、事件和审计记录以 `workspace_id` 为主隔离键，所有查询默认带租户范围。

## Core Data Structures and Interfaces

### Identity and authorization

```python
class User:
    id: UUID
    email: str
    password_hash: str
    display_name: str
    is_active: bool
    created_at: datetime

class Workspace:
    id: UUID
    name: str
    created_by: UUID
    created_at: datetime

class WorkspaceMember:
    workspace_id: UUID
    user_id: UUID
    role: Literal["owner", "admin", "member", "viewer"]
```

`viewer` 只能查看；`member` 可以创建会话、发起低风险任务和响应自己有权限的审批；`admin` 可以管理项目、成员、审计和用量；`owner` 可以删除或转移工作区。

### Project and session

```python
class Project:
    id: UUID
    workspace_id: UUID
    name: str
    workspace_path: str
    status: Literal["active", "archived"]
    created_by: UUID
    created_at: datetime

class Session:
    id: UUID
    project_id: UUID
    workspace_id: UUID
    title: str
    status: Literal["idle", "running", "waiting_approval", "failed", "completed", "cancelled"]
    created_by: UUID
    created_at: datetime
    updated_at: datetime

class Run:
    id: UUID
    session_id: UUID
    workspace_id: UUID
    status: Literal["queued", "running", "waiting_approval", "completed", "failed", "cancelled"]
    prompt: str
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    attempt: int
    worker_id: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    idempotency_key: str | None
```

项目路径必须通过服务端的 `ProjectRootResolver` 校验，不能由请求直接访问任意本地路径。第一期项目来源限定为部署实例配置的项目根目录下的已有目录或由服务端创建的目录。

### Append-only session events

```python
class SessionEvent:
    id: UUID
    workspace_id: UUID
    session_id: UUID
    run_id: UUID | None
    sequence: int
    event_type: str
    payload: dict[str, Any]
    visibility: Literal["user", "admin", "internal"]
    created_at: datetime
```

`sequence` 在单个会话内单调递增，用于 SSE 的 `id` 和断线补偿。事件类型至少包括：

```text
run_queued
run_started
assistant_text_delta
thinking_delta
tool_call_started
tool_call_progress
tool_call_finished
tool_approval_requested
tool_approval_resolved
context_compacted
usage_updated
run_completed
run_failed
run_cancelled
```

内部事件可以写入数据库供审计，但不能直接推送给普通成员，例如完整的密钥解析结果和内部异常堆栈。

### Tool approval

```python
class ToolApproval:
    id: UUID
    workspace_id: UUID
    session_id: UUID
    run_id: UUID
    tool_call_id: str
    tool_name: str
    summary: str
    risk_level: Literal["low", "medium", "high"]
    status: Literal["pending", "allowed", "denied", "expired", "cancelled"]
    decided_by: UUID | None
    decided_at: datetime | None
    created_at: datetime
```

审批决定通过 `ApprovalBroker` 传给 Worker；Worker 在收到决定之前不能继续执行该副作用工具。审批必须具备幂等性，同一审批 ID 的重复提交不能重复执行工具。

### Resource budget and execution boundary

```python
class ResourceBudget:
    max_run_seconds: int
    max_tool_seconds: int
    max_shell_seconds: int
    max_iterations: int
    max_tool_calls: int
    max_output_bytes: int
    max_child_processes: int

class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...
    async def wait(self) -> None: ...

class ExecutionBackend(Protocol):
    async def execute(self, request: ExecutionRequest, budget: ResourceBudget) -> ExecutionResult: ...
    async def cancel(self, execution_id: str) -> None: ...
```

第一期提供受控的本地执行后端，所有路径、工作目录、超时、输出和子进程限制在后端内部再次校验。Docker 或其他操作系统级沙箱作为后续实现，不允许由 Web 请求直接选择任意宿主机路径或执行后端参数。

### Audit and artifact records

```python
class AuditLog:
    id: UUID
    workspace_id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    request_id: str
    metadata: dict[str, Any]
    created_at: datetime

class Artifact:
    id: UUID
    workspace_id: UUID
    run_id: UUID
    kind: Literal["diff", "file_snapshot", "tool_output"]
    relative_path: str | None
    content_ref: str
    redacted: bool
    created_at: datetime
```

大工具输出和 Diff 不直接塞进普通事件 payload；事件保存摘要，完整内容写入受控 Artifact 存储或项目内部受保护目录。

### API contracts

#### Authentication

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

登录返回短期 access token 和可轮换的 refresh token。服务端使用密码哈希存储密码，不保存明文密码。

#### Workspace and project

```text
GET  /api/workspaces
POST /api/workspaces
GET  /api/workspaces/{workspace_id}/members
GET  /api/workspaces/{workspace_id}/projects
POST /api/workspaces/{workspace_id}/projects
PATCH /api/projects/{project_id}
POST /api/projects/{project_id}/archive
```

#### Sessions and runs

```text
GET  /api/projects/{project_id}/sessions
POST /api/projects/{project_id}/sessions
GET  /api/sessions/{session_id}
PATCH /api/sessions/{session_id}
POST /api/sessions/{session_id}/messages
GET  /api/sessions/{session_id}/events?after={sequence}
GET  /api/sessions/{session_id}/events/stream
POST /api/runs/{run_id}/cancel
POST /api/runs/{run_id}/retry
```

`POST /messages` 创建 Run 并立即返回 `run_id`；模型输出通过 SSE 推送。SSE 支持 `Last-Event-ID`，服务端先补齐数据库中缺失的事件，再推送实时事件。

#### Approvals, timeline and artifacts

```text
GET  /api/runs/{run_id}/approvals
POST /api/approvals/{approval_id}/decision
GET  /api/runs/{run_id}/timeline
GET  /api/runs/{run_id}/diff
GET  /api/runs/{run_id}/artifacts/{artifact_id}
GET  /api/workspaces/{workspace_id}/audit-logs
GET  /api/workspaces/{workspace_id}/usage
```

所有 API 响应携带 `request_id`；写操作支持 `Idempotency-Key`，尤其是创建 Run、审批、取消和重试。

### Runtime adapters

```python
class AgentRunRequest(Protocol):
    run_id: UUID
    session_id: UUID
    project_path: Path
    prompt: str
    permission_snapshot: PermissionSnapshot

class AgentRunExecutor(Protocol):
    async def execute(
        self,
        request: AgentRunRequest,
        emit: Callable[[RuntimeEvent], Awaitable[None]],
        approval_broker: ApprovalBroker,
        cancel_token: CancellationToken,
    ) -> RunResult: ...

class EventStore(Protocol):
    async def append(self, event: RuntimeEvent) -> SessionEvent: ...
    async def list_after(self, session_id: UUID, sequence: int) -> list[SessionEvent]: ...
    async def subscribe(self, session_id: UUID) -> AsyncIterator[SessionEvent]: ...
```

`AgentRunExecutor` 是现有 CLI Agent Loop 与 Web Worker 之间的唯一适配边界。第一版可以在 Worker 中使用线程或进程隔离同步 Agent Loop；后续再逐步引入贯穿 Provider、Tool 和 Hook 的统一取消令牌。

### Reliability and security interfaces

```python
class RunLeaseStore(Protocol):
    async def claim(self, run_id: UUID, worker_id: str, ttl_seconds: int) -> bool: ...
    async def heartbeat(self, run_id: UUID, worker_id: str) -> None: ...
    async def release(self, run_id: UUID, worker_id: str, status: str) -> None: ...
    async def recover_expired(self) -> list[UUID]: ...

class SecretScrubber(Protocol):
    def scrub_text(self, value: str) -> str: ...
    def scrub_payload(self, value: dict[str, Any]) -> dict[str, Any]: ...

class WorkspacePathResolver(Protocol):
    def resolve(self, workspace_id: UUID, relative_path: str) -> Path: ...
    def assert_inside(self, workspace_id: UUID, path: Path) -> None: ...
```

所有事件、日志和 Artifact 写入前经过 `SecretScrubber`；所有工具执行前经过 `WorkspacePathResolver` 和能力/权限检查。Run 租约用于避免多个 Worker 同时处理同一个任务。

## Module Design

### `huicode/server/app.py`

**Responsibility:** 创建 FastAPI 应用、注册路由、中间件、异常处理和生命周期钩子。

**Dependencies:** server settings, database, Redis, auth, API routers。

### `huicode/server/config.py`

**Responsibility:** 读取服务端配置，包括数据库、Redis、JWT、项目根目录、CORS 和运行模式。

**Dependencies:** environment variables and existing HuiCode config loader。

### `huicode/server/auth/`

**Responsibility:** 密码哈希、token 创建与验证、当前用户解析、工作区角色校验。

**Key modules:** `passwords.py`, `tokens.py`, `dependencies.py`, `permissions.py`。

### `huicode/server/db/`

**Responsibility:** SQLAlchemy engine/session、模型、迁移和事务边界。

**Key modules:** `base.py`, `models.py`, `session.py`, `repositories/`。

Repository 方法必须显式接收 `workspace_id` 或由 service 层完成范围约束，禁止提供默认的全表查询给 API 路由。

### `huicode/server/domain/`

**Responsibility:** 项目、会话、Run、审批、审计和用量的业务规则；不依赖 FastAPI 请求对象。

**Key modules:** `projects.py`, `sessions.py`, `runs.py`, `approvals.py`, `audit.py`, `artifacts.py`。

### `huicode/server/runtime/`

**Responsibility:** 将现有 Agent Runtime 封装成可观察、可取消、可审批的执行单元。

**Key modules:** `executor.py`, `event_mapper.py`, `approval_broker.py`, `cancellation.py`, `limits.py`, `execution_backend.py`, `permission_bridge.py`, `workspace_resolver.py`, `scrubber.py`。

Runtime 在模型请求、工具调用和 Shell 执行边界检查取消状态与资源预算；安全策略不能只依赖前端传入的参数。

### `huicode/server/events/`

**Responsibility:** 统一 Runtime Event、数据库追加、Redis 实时通知和 SSE 订阅。

**Key modules:** `types.py`, `store.py`, `publisher.py`, `subscriber.py`, `sse.py`。

事件写入采用“数据库成功后再发布”的顺序；发布失败时，SSE 客户端可通过 sequence 补偿，不依赖 Redis 消息永不丢失。

### `huicode/server/workers/`

**Responsibility:** 从任务队列领取 Run，加载会话上下文，调用 `AgentRunExecutor`，处理重试、超时和最终状态。

**Key modules:** `queue.py`, `agent_worker.py`, `recovery.py`, `heartbeat.py`, `idempotency.py`, `dead_letter.py`。

Worker 必须使用租约或 heartbeat 标记运行中的任务，服务重启后将超时任务恢复为可重试或失败，不重复执行已经完成的不可逆工具调用。

Worker 的状态更新和最终事件必须使用幂等写入；重复领取或重复消息只允许推进一次状态。无法安全恢复的任务进入可人工查看的 dead-letter 状态。

### `huicode/server/api/`

**Responsibility:** Pydantic 请求/响应模型、路由、状态码和权限依赖。

**Key modules:** `auth.py`, `workspaces.py`, `projects.py`, `sessions.py`, `runs.py`, `approvals.py`, `audit.py`, `usage.py`。

路由只做参数解析、鉴权和 service 调用，不直接操作 Agent Loop 或 ORM 查询细节。

### `web/`

**Responsibility:** 浏览器端产品界面。

**Recommended modules:**

```text
web/src/
├── app/                 # router, providers, global layout
├── api/                 # typed REST client and SSE client
├── auth/                # login/register/session state
├── components/          # reusable UI components
├── features/
│   ├── dashboard/
│   ├── projects/
│   ├── sessions/
│   ├── agent-chat/
│   ├── approvals/
│   ├── timeline/
│   └── diff-viewer/
├── stores/              # UI and live run state
└── types/               # API and runtime event types
```

前端通过 React Query 管理服务端数据，通过单独的 Run Event Store 合并 SSE 事件；组件不能自行拼接事件顺序或修改服务端状态。

### `tests/server/` and `web/src/**/*.test.*`

**Responsibility:** API、权限隔离、事件补偿、Worker 状态机、超时取消、租约恢复、幂等性、敏感信息脱敏和关键 UI 行为测试。

## Module Interactions and Data Flow

### Starting a run

```text
Browser submits prompt
  → API validates session membership and project path
  → transaction creates Run + run_queued event
  → queue publishes run_id
  → API returns run_id
  → Worker claims Run and emits run_started
  → Worker loads HuiCode session/runtime snapshot
  → Agent Loop emits normalized RuntimeEvent
  → EventStore appends sequence-numbered event
  → Publisher notifies Redis subscribers
  → SSE sends event to Browser
```

### Tool approval

```text
Agent requests side-effect tool
  → permission bridge asks existing permission engine
  → waiting_approval event is persisted
  → ApprovalBroker creates pending approval
  → browser receives approval request
  → user allows/denies/cancels
  → API verifies approval ownership and idempotency
  → broker wakes Worker
  → existing permission result controls tool execution
  → approval result and tool result become events
```

### Reconnection and replay

```text
Browser reconnects with Last-Event-ID = N
  → API verifies session access
  → EventStore returns events where sequence > N
  → API sends missing events in order
  → API subscribes to new events
  → client deduplicates by event id/sequence
```

### Completion and Diff

```text
Agent Loop ends
  → Worker records usage and final Run status
  → workspace diff service compares approved project state
  → redacts secrets from tool output and diff metadata
  → Artifact record is created
  → run_completed event is emitted
  → browser refreshes timeline and diff view
```

### Failure recovery

```text
Worker claims Run with lease
  → periodically writes heartbeat
  → process exits or heartbeat expires
  → recovery job marks Run as recovering
  → checks last completed tool call and retry policy
  → safely requeues or marks failed_requires_review
  → writes audit and recovery events
```

## File Organization

```text
Huicode/
├── huicode/
│   ├── server/
│   │   ├── app.py
│   │   ├── config.py
│   │   ├── auth/
│   │   ├── db/
│   │   ├── domain/
│   │   ├── runtime/
│   │   ├── events/
│   │   ├── workers/
│   │   └── api/
│   └── ...existing CLI/runtime modules...
├── web/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   └── tests/
├── migrations/
├── tests/
│   ├── server/
│   ├── integration/
│   └── e2e/
├── deploy/
│   ├── Dockerfile.api
│   ├── Dockerfile.web
│   ├── docker-compose.yml
│   └── nginx.conf
├── .env.example
└── docs/
    ├── web-studio-local-development.md
    ├── production-hardening.md
    └── incident-runbook.md
```

## Technical Decisions

| Decision point | Choice | Rationale |
| --- | --- | --- |
| Web frontend | React + TypeScript + Vite | 与 Python 后端边界清晰，构建快速，适合展示组件、状态管理和类型化 API 能力 |
| Backend API | FastAPI | 复用现有 Python Runtime，自动生成 OpenAPI，适合异步 SSE 接口 |
| Primary database | PostgreSQL | 支持事务、索引、JSON 字段和并发访问，足以承载会话与审计数据 |
| Test database | SQLite 或临时 PostgreSQL | 单元测试启动快；关键集成测试再覆盖真实 PostgreSQL 行为 |
| ORM/migrations | SQLAlchemy 2 + Alembic | 保持 Python 生态一致，迁移可审查、可回滚 |
| Live events | SSE + sequence replay | Agent 事件天然是服务端到客户端单向流；`Last-Event-ID` 适合断线补偿 |
| Job execution | Redis-backed queue + dedicated worker | 将长任务与 HTTP 解耦，支持取消、租约、重试和页面关闭后继续运行 |
| Session history | Append-only events plus projections | 支持回放、恢复、审计和后续分支，不破坏原始事件 |
| Auth | Short-lived access token + refresh token + workspace RBAC | 实现成本可控，同时展示认证、授权和租户隔离能力 |
| Project source | Server-managed local project root | 第一阶段控制安全边界，避免任意路径访问；未来可替换为 Git/remote source adapter |
| Agent integration | Adapter around existing Agent Loop | CLI 与 Web 共用核心行为，避免复制或重写一套循环 |
| Deployment | Docker Compose | 一条命令启动前端、API、Worker、PostgreSQL 和 Redis，适合作品演示 |
| Frontend/server state | React Query + dedicated event store | 查询缓存与实时事件分工明确，避免组件各自维护运行状态 |
| Microservices | 暂不拆分 | 当前规模下模块化单体更容易调试、部署和验证；Worker 已提供进程隔离边界 |
| Run recovery | Lease + heartbeat + explicit retry policy | 服务重启后能够发现失联任务，并避免无条件重复执行副作用 |
| Idempotency | Run/tool/approval idempotency keys | 重复请求和消息不会产生重复不可逆操作 |
| Resource limits | Per-run, per-tool and process budgets | 防止模型循环、Shell 卡死和超大输出拖垮服务 |
| Execution boundary | Local backend behind `ExecutionBackend` | 第一阶段控制范围，后续可替换为 Docker 或远程沙箱 |
| Secret handling | Centralized scrubber before persistence/output | 统一保护事件、日志、记忆、Artifact 和 API 响应 |
| Operational checks | Liveness/readiness/structured logs/run correlation | 让故障可以被发现、定位和恢复，而不是只看终端输出 |

## Risks and Mitigations

- **同步 Agent Loop 阻塞事件循环**：第一期在 Worker 中通过线程或进程执行，并将事件桥接到异步 EventStore；后续再逐步引入统一 async/cancel token。
- **事件发布与数据库写入不一致**：先提交数据库事件，再发布 Redis 通知；客户端始终可以按 sequence 从数据库补偿。
- **重复执行副作用工具**：Run、Approval 和工具调用都使用幂等标识；Worker 使用任务租约和完成标记。
- **项目路径越权**：创建和读取项目时统一通过 workspace root resolver，禁止从请求直接传入任意绝对路径。
- **敏感信息进入日志或事件**：复用现有 secret scrub 逻辑，事件 payload 只保存摘要；完整工具输出按权限受控存储。
- **Web 功能影响 CLI**：先以适配器接入，不改动 CLI 默认启动路径；保留原有测试并增加共享 Runtime contract tests。
- **恢复任务重复副作用**：用 Run lease、tool call idempotency、完成记录和显式 retry policy 共同约束；无法证明安全的任务进入人工处理状态。
- **本地执行权限过大**：把路径、进程、输出和网络策略集中到 ExecutionBackend；Docker 沙箱作为后续替换实现，不让 API 直接传递宿主机执行参数。
- **敏感信息泄露**：所有持久化和对外输出经过中央 SecretScrubber，并用包含测试密钥的自动化用例验证。

## Coverage of Spec Requirements

| Spec requirement | Main architectural home |
| --- | --- |
| F1-F3 | `auth/`, `db/`, `domain/`, project/session API and Web features |
| F4-F5 | `runtime/`, `workers/`, `events/`, run API and SSE client |
| F6-F7 | `permission_bridge.py`, `approval_broker.py`, approval API and run controls |
| F8-F9 | append-only `SessionEvent`, `EventStore`, artifacts, replay API and timeline UI |
| F10 | `AuditLog`, usage projection, admin API and dashboard |
| F11 | existing CLI plus shared Runtime adapter and contract tests |
| F12 | `deploy/`, migrations, `.env.example`, local development documentation and E2E test |
| F13-F14 | Run state machine, `RunLeaseStore`, cancellation, recovery worker and timeline events |
| F15-F16 | `ResourceBudget`, timeout enforcement, idempotency store and worker retry policy |
| F17-F18 | `ExecutionBackend`, path resolver, tool capability metadata and `SecretScrubber` |
| F19 | correlation IDs, structured logs, health endpoints, usage projection and operational runbook |
