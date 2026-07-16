# Agent Team 技术计划

## 架构概览

本章在现有主 Agent、子 Agent 与 Worktree 体系之外新增独立的 Team 领域层。Team 层负责长期团队、共享任务、邮箱、成员后端、审批和成果集成；现有 Agent Loop、Provider、权限、Hook 与 Worktree 继续作为执行基础设施复用。

```text
普通主会话
  -> Team 入口创建/恢复团队
  -> 当前运行身份切换为 Team Lead
  -> TeamManager
       -> TeamStore（团队与成员元数据）
       -> SharedTaskStore（依赖任务）
       -> MailboxStore（点对点消息）
       -> MemberBackendRegistry
            -> TmuxBackend
            -> WindowsTerminalBackend
            -> CoroutineBackend
       -> TeamMemberRunner（独立 AgentState + Worktree）
       -> ApprovalGate（结构化计划审批）
       -> IntegrationManager（专用集成 Worktree）
  -> TeamEvent 流回 TUI
```

团队域数据放在用户级 `~/.huicode/teams/<team-name>/`，避免污染项目版本库；成员代码继续使用项目内已有 `.huicode/worktrees/` 隔离。每个成员拥有稳定成员 ID、独立 Worktree 和分支，完成一次任务后只停止 Agent Loop 并进入 idle，不立即销毁工作区或上下文。

## 核心数据结构与接口

### 1. Team 配置

在 `LLMConfig` 中增加：

```python
@dataclass(frozen=True)
class TeamConfig:
    enabled: bool = False
    default_backend: Literal["auto", "terminal", "coroutine"] = "auto"
    max_members: int = 4
    mailbox_lock_retries: int = 8
    mailbox_lock_retry_ms: int = 50
    mailbox_stale_lock_seconds: int = 30
    member_idle_poll_ms: int = 250
    shutdown_wait_seconds: float = 3.0
    coordinator_enabled: bool = False
    integration_checks: tuple[str, ...] = ()
```

YAML 示例：

```yaml
teams:
  enabled: true
  default_backend: auto
  max_members: 4
  mailbox_lock_retries: 8
  mailbox_lock_retry_ms: 50
  mailbox_stale_lock_seconds: 30
  member_idle_poll_ms: 250
  shutdown_wait_seconds: 3
  coordinator_enabled: false
  integration_checks:
    - python -m unittest discover -s tests -v
```

Coordinator 的第二把锁固定为环境变量 `HUICODE_COORDINATOR=1`。配置解析阶段集中校验枚举、正整数、正超时、并发上限和检查命令类型。

### 2. 团队与成员模型

```python
TeamStatus = Literal["active", "closing", "closed", "failed"]
MemberStatus = Literal[
    "starting", "working", "waiting_approval", "idle", "failed", "stopped"
]
BackendKind = Literal["tmux", "windows_terminal", "coroutine"]

@dataclass(frozen=True)
class TeamRecord:
    id: str
    name: str
    lead_session_id: str
    repository_id: str
    workspace: str
    target_branch: str
    target_base_commit: str
    status: TeamStatus
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class TeamMemberRecord:
    id: str
    name: str
    role: str
    requested_backend: Literal["auto", "terminal", "coroutine"]
    actual_backend: BackendKind
    approval_required: bool
    status: MemberStatus
    worktree_task_id: str
    worktree_path: str
    branch: str
    session_path: str
    backend_handle: dict[str, str]
    usage: dict[str, object]
    updated_at: str
```

- 团队 ID 与成员 ID 由系统生成，显示名称只作为安全校验后的逻辑标识。
- `repository_id` 复用 Worktree 章节的仓库身份，恢复时必须匹配当前仓库。
- `target_base_commit` 记录团队创建时目标分支位置，供最终集成并发检查。
- 元数据对象采用不可变快照，更新通过 Store 的锁和原子替换完成。

### 3. 共享任务模型

```python
TeamTaskStatus = Literal["pending", "blocked", "in_progress", "completed", "failed"]

@dataclass(frozen=True)
class TeamTaskRecord:
    id: str
    title: str
    description: str
    status: TeamTaskStatus
    assignee: str | None
    dependencies: tuple[str, ...]
    result_summary: str
    version: int
    created_at: str
    updated_at: str
```

`SharedTaskStore` 提供：

```python
class SharedTaskStore:
    def create(...) -> TeamTaskRecord: ...
    def list() -> tuple[TeamTaskRecord, ...]: ...
    def get(task_id: str) -> TeamTaskRecord: ...
    def claim(task_id: str, member: str, expected_version: int) -> TeamTaskRecord: ...
    def update(task_id: str, patch: TaskPatch, expected_version: int) -> TeamTaskRecord: ...
    def delete(task_id: str, expected_version: int) -> None: ...
```

- 任务清单保存为一个版本化 JSON 快照，锁内读取、校验、更新，再写临时文件并原子替换。
- `version` 实现乐观并发控制，陈旧写入返回结构化冲突，不静默覆盖。
- 每次变更后重新计算 `blocked`，并验证依赖存在、自依赖和环路。
- 仅 `completed` 的全部依赖满足后，任务才能认领或进入 `in_progress`。
- 被其他任务依赖或处于执行中的任务不得删除；删除同样要求版本匹配。

### 4. 消息与协议

```python
MessageType = Literal[
    "text", "assignment", "plan_request", "plan_decision", "progress",
    "completion", "idle", "wake", "stop"
]

@dataclass(frozen=True)
class TeamMessage:
    id: str
    sender: str
    recipients: tuple[str, ...]
    body: str
    summary: str
    type: MessageType
    correlation_id: str
    task_id: str | None
    timestamp: str
    read: bool = False
    payload: dict[str, object] = field(default_factory=dict)
```

`NameRegistry` 只接受 Lead 和当前花名册中的成员名。`MailboxStore.send()` 先解析全部收件人，再分别追加 UTF-8 JSONL；广播在锁定收件人集合后逐邮箱写入，并返回成功与失败清单。

每个邮箱使用 `locks/mailbox-<member>.lock`：

- 以排他创建获取锁。
- 获取失败按配置重试。
- 锁文件包含拥有者、进程和创建时间。
- 超过过期阈值且拥有进程不可确认存活时，允许清理后重试。
- 单条坏行读取时跳过并报告，其他消息继续恢复。
- 已读标记通过锁内重写快照文件完成，原 JSONL 保留追加优势。

### 5. 计划审批模型

```python
ApprovalStatus = Literal["pending", "allowed", "denied", "superseded"]

@dataclass(frozen=True)
class PlanApproval:
    request_id: str
    member: str
    task_id: str
    plan: str
    status: ApprovalStatus
    feedback: str
    created_at: str
    decided_at: str | None
```

`ApprovalGate` 持久化成员当前审批请求，并提供：

```python
def submit_plan(member, task_id, plan) -> PlanApproval: ...
def decide(request_id, decision, feedback) -> PlanApproval: ...
def allows_side_effect(member, task_id) -> bool: ...
```

- `TeamPlanDecision(request_id, decision, feedback)` 只在 Lead 作用域注册。
- 决定写入审批状态，同时发送 `plan_decision` 协议消息并唤醒成员。
- 成员 Registry 在工具枚举和执行两处检查 Gate；未批准时副作用工具不可见，陈旧调用仍返回结构化拒绝结果。
- `deny` 使旧请求终止，成员必须提交新请求 ID；普通文本永不进入 `decide()`。

### 6. 运行身份与工具作用域

新增运行身份：

```python
AgentRuntimeScope = Literal["main", "team_lead", "team_member", "subagent"]

@dataclass(frozen=True)
class TeamRuntimeIdentity:
    scope: AgentRuntimeScope
    team_id: str | None = None
    member_id: str | None = None
    coordinator: bool = False
```

`ScopedToolRegistry` 在现有 `ToolRegistry` 外按身份动态筛选：

- `main`：普通工具和 Team 创建/恢复入口，不暴露任务、消息、审批和集成工具。
- `team_lead`：增加团队管理、共享任务、消息、计划决定、停止和集成工具。
- `team_member`：增加共享任务、消息和计划申请工具，不暴露 Lead 专属工具。
- `subagent`：保持现有过滤，所有 Team 工具列入全局禁用集合。

Team 工具不标记为无条件可见的 system tool。Skill 等既有系统工具继续沿用原规则，Team 作用域在最终工具规格生成和 `get()` 执行入口同时生效。

建议使用一组职责明确、Schema 稳定的工具：

- `Team`：创建、恢复、查看、关闭团队以及增删停成员。
- `TeamTask`：任务增删查改、认领、完成和失败。
- `TeamMessage`：单发、广播、收件和已读。
- `TeamPlanRequest`：审批成员提交计划。
- `TeamPlanDecision`：Lead 批准或驳回。
- `TeamIntegrate`：检查、开始、继续或中止集成。

### 7. Coordinator 工具限制

`CoordinatorToolPolicy` 在 `team_lead` Registry 上叠加：

- 去除 `Write`、`Edit` 和其他直接文件修改工具。
- 保留 `Read`、`Find`、`Search`、Team 管理工具和集成工具。
- 将普通 `Bash` 替换为 `CoordinatorGitTool`，参数 Schema 保持命令字符串，但只接受无重定向、无管道、无 shell 控制符的 Git 检查与集成子命令。
- 允许的 Git 操作限定为状态、日志、差异、分支检查、worktree 检查以及由集成流程需要的 merge/merge-abort；路径仍受工作区边界和权限系统约束。
- 模式判断为 `config.teams.coordinator_enabled and env["HUICODE_COORDINATOR"] == "1"`，每轮重新构建 Registry 时执行，不依赖提示词。

真正的合并优先通过 `TeamIntegrate` 调用固定参数 Git Backend；保留受限命令主要用于 Lead 诊断。

### 8. 成员后端接口

```python
class TeamMemberBackend(Protocol):
    kind: BackendKind
    def available(self) -> BackendAvailability: ...
    def launch(self, launch: MemberLaunchSpec) -> BackendHandle: ...
    def wake(self, handle: BackendHandle) -> None: ...
    def stop(self, handle: BackendHandle, timeout: float) -> None: ...
    def alive(self, handle: BackendHandle) -> bool: ...
```

`MemberBackendSelector`：

1. `auto` 依次探测 tmux、Windows Terminal、协程。
2. `terminal` 只在 tmux 或 Windows Terminal 中选择，均不可用则抛出启动错误。
3. `coroutine` 直接选择同进程执行。
4. 选择结果先持久化再产生启动事件。

后端实现：

- `CoroutineBackend` 使用独立 Worker Pool 运行长期成员循环，不复用普通子 Agent 的一次性任务对象。
- `TmuxBackend` 在独立 pane 启动 `python -m huicode --team-worker ...`，保存 session/window/pane 标识，以 `send-keys` 唤醒。
- `WindowsTerminalBackend` 通过 `wt split-pane` 启动同一内部 worker 命令，保存 worker ID 和进程信息；邮箱写入后通过本地唤醒事件通知 worker，终端进程持续显示状态。
- 内部 worker 参数只携带团队目录和成员 ID，不在命令行传递 API Key；worker 从原配置文件和持久化成员记录恢复。
- 后端启动命令使用参数数组；终端适配层不解析任务内容或执行模型工具。

### 9. TeamMemberRunner

`TeamMemberRunner` 复用 `run_agent_loop()`，但生命周期从“一次提交后销毁”调整为：

```text
恢复 TeamMemberRecord
  -> 可信恢复成员 Worktree
  -> 恢复成员 JSONL 会话
  -> 等待 assignment/wake 消息
  -> 构建成员作用域 Registry
  -> 若需审批：先规划并提交 plan_request
  -> 等待匹配 plan_decision
  -> 执行 Agent Loop 直到 final/error/cancel
  -> 更新任务和 Token 用量
  -> 发送 completion + idle
  -> 持久化并继续等待
```

- 每个成员拥有独立 `AgentState`、`ContextManager`、`FileReadCache`、权限上下文和 Token 汇总。
- 角色定义继续从现有 `AgentCatalog` 解析，角色白名单、黑名单、模型、迭代上限和权限模式仍然生效。
- Team 额外工具在角色工具过滤之后按成员身份加入，但成员不能通过角色配置获得 Lead 工具。
- 会话使用成员目录下 UTF-8 JSONL 追加；恢复复用现有协议安全历史截断和上下文压缩逻辑。
- 角色 Prompt 后注入最高优先级团队块，包含 Team、成员名、任务、Worktree、协作规则与审批状态。

### 10. Worktree 生命周期适配

新增 `TeamWorktreeService` 包装现有 `WorktreeManager`：

- 成员创建时以稳定的 `team-id/member-id` 生成 Worktree task ID 和逻辑名。
- 成员重启使用原 ID 走现有可信快速恢复，不重新初始化或创建分支。
- 一次任务结束时不调用自动删除，只记录状态并保留给后续指派。
- 团队关闭只停止后端；团队删除才进入 Worktree 删除保护检查。
- 只读成员同样调用此服务，不共享 Lead 工作区。
- 集成 Worktree 使用独立的 `team-id/integration-attempt-id` 标识，不与成员 Worktree 复用。

需要为现有 Worktree 层补充“状态检查”和“受保护删除预检”接口，但不削弱当前脏修改、未推送提交和清单匹配保护。

### 11. 成果集成

`IntegrationManager` 维护版本化 `IntegrationRecord`：

```python
@dataclass(frozen=True)
class IntegrationRecord:
    id: str
    team_id: str
    target_branch: str
    expected_target_commit: str
    integration_branch: str
    worktree_path: str
    member_branches: tuple[str, ...]
    merged_members: tuple[str, ...]
    status: Literal["preparing", "merging", "conflicted", "verifying", "ready", "published", "aborted"]
    pre_attempt_commit: str
    error: str
```

流程：

1. 根据任务依赖拓扑排序筛选已完成成员，并确认各成员工作树干净且成果已提交。
2. 从目标分支当前提交创建专用集成分支和 Worktree，并记录 `expected_target_commit`。
3. 使用参数数组依次合并成员分支；每步记录成功成员。
4. 冲突时持久化 `conflicted`，可启动 resolver 成员独占该集成 Worktree 和分支。
5. Resolver 成功提交后继续；失败时执行 merge abort，并把集成分支恢复到 `pre_attempt_commit`。这些破坏性动作只允许作用于清单匹配的专用集成 Worktree。
6. 执行配置的 `integration_checks`，全部通过后标记 `ready`。
7. 发布前再次读取目标分支；若已变化，则拒绝发布并要求基于新目标重新集成。
8. 目标分支未变化且对应工作树干净时执行 `--ff-only` 发布；若目标分支当前未检出，可在临时发布 Worktree 完成。
9. 发布失败保留 `ready` 集成分支供恢复，不修改或重置用户工作区。

集成命令全部由专用 Git Backend 执行，模型不能提供任意 merge 参数。Resolver 是特殊团队成员，运行时该集成 Worktree 是它唯一的独立工作区，其他成员不得同时进入。

### 12. 持久化布局

```text
~/.huicode/teams/<team-name>/
  team.json
  roster.json
  tasks.json
  approvals.json
  events.jsonl
  integration.json
  members/
    <member-name>/
      session.jsonl
      runtime.json
  mailboxes/
    lead.jsonl
    <member-name>.jsonl
  locks/
    team.lock
    tasks.lock
    approvals.lock
    mailbox-<name>.lock
```

- Snapshot 文件使用同目录临时文件、flush、可用时 fsync、原子替换。
- JSONL 记录一行一个对象，写入前完成序列化，锁内一次追加并 flush。
- Store 读取时校验格式版本、团队 ID、仓库 ID 和路径边界。
- 敏感配置、API Key、完整环境变量不进入团队目录。

### 13. TeamManager 与事件流

```python
class TeamManager:
    def create(...) -> TeamSnapshot: ...
    def resume(name: str) -> TeamSnapshot: ...
    def spawn_member(...) -> TeamMemberRecord: ...
    def stop_member(name: str) -> TeamMemberRecord: ...
    def send_message(...) -> DeliveryReport: ...
    def close_team() -> TeamSnapshot: ...
    def delete_team() -> DeleteReport: ...
    def drain_events() -> tuple[TeamEvent, ...]: ...
```

`TeamEvent` 至少包含 kind、team、member、task、correlation_id、message、timestamp 和展示数据。CLI 增加独立事件泵，与子 Agent 通知泵并列，通过 `prompt_toolkit.run_in_terminal` 安全刷新，不直接从后台线程渲染。

主 Agent 每轮开始前从 `TeamManager` 获取最新快照：

- 更新运行身份和工具作用域。
- 注入精简团队状态（成员、阻塞任务、待审批、未读消息、集成状态）。
- 后台完成和消息事件采用租约式回灌，只有成功加入历史后才确认，避免 API 失败导致通知丢失。

## 模块职责

### 新增模块

- `huicode/teams/types.py`：团队、成员、任务、消息、审批、集成和事件领域类型。
- `huicode/teams/naming.py`：团队名、成员名、任务 ID、分支与持久化路径校验。
- `huicode/teams/locking.py`：可重试、可判定过期的文件锁。
- `huicode/teams/storage.py`：目录布局、版本化快照和 JSONL 原子持久化。
- `huicode/teams/tasks.py`：共享任务 CRUD、依赖图和乐观并发。
- `huicode/teams/mailbox.py`：名称解析、单发、广播、收件和已读处理。
- `huicode/teams/approval.py`：计划申请、结构化决定和副作用闸门。
- `huicode/teams/backends.py`：后端协议、能力探测、选择与协程实现。
- `huicode/teams/terminal_backends.py`：tmux 与 Windows Terminal 启动、唤醒和停止。
- `huicode/teams/member_runner.py`：长期成员循环、会话恢复和 idle 转换。
- `huicode/teams/worktrees.py`：稳定成员 Worktree 与集成 Worktree 适配。
- `huicode/teams/integration.py`：拓扑合并、冲突恢复、验证和发布。
- `huicode/teams/scoping.py`：身份工具过滤、审批过滤和 Coordinator 策略。
- `huicode/teams/tools.py`：Team、Task、Message、Plan 与 Integrate 工具。
- `huicode/teams/manager.py`：团队生命周期总编排和事件队列。
- `huicode/teams/worker.py`：独立终端成员的内部进程入口。
- `huicode/teams/__init__.py`：公开类型与构造入口。

### 修改模块

- `huicode/config.py`：增加并校验 `teams` 配置。
- `huicode/cli.py`：初始化 TeamManager、注册入口工具、切换 Lead 作用域、启动事件泵和关闭资源。
- `huicode/__main__.py`：支持内部 team worker 启动参数，同时保持普通 CLI 用法。
- `huicode/agent.py`：每轮接收 Team 运行身份、动态 Registry 和团队事件租约。
- `huicode/subagents/filtering.py`：把所有 Team 工具加入普通子 Agent 禁用集合。
- `huicode/prompts/modules.py`：注入 Lead/成员身份、团队状态和 coordinator 约束。
- `huicode/tui.py`：渲染成员、消息、审批、空闲和集成事件。
- `huicode/worktrees/manager.py`：补充 Team 所需的状态检查与保护性删除预检。
- `README.md`：说明 Team 配置、后端选择、协作工具、审批和集成流程。
- `docs/mew-spec-pitfalls.md`：仅在实现或验收发生真实返工时追加本章经历。

### 测试模块

- `tests/test_team_naming_storage.py`：名称边界、快照、JSONL 和损坏恢复。
- `tests/test_team_tasks.py`：CRUD、依赖、环路、阻塞和并发版本。
- `tests/test_team_mailbox.py`：单发、广播、锁重试、过期锁和坏行。
- `tests/test_team_approval.py`：申请配对、重复决定和副作用闸门。
- `tests/test_team_backends.py`：探测优先级、显式终端失败、启动和唤醒。
- `tests/test_team_scoping.py`：四类身份工具可见性和 coordinator Bash 限制。
- `tests/test_team_member_runner.py`：工作、idle、持久化与恢复。
- `tests/test_team_integration.py`：临时仓库中的排序合并、冲突、中止、验证和目标漂移。
- `tests/test_team_manager.py`：生命周期、故障隔离、停止和删除保护。
- `tests/test_team_cli.py`：配置、状态展示、事件泵和内部 worker 入口。

## 模块交互与数据流

### 创建团队并派生成员

```text
Team(create)
  -> 校验 TeamConfig / 名称 / Git 仓库
  -> 记录 target branch + base commit
  -> 原子创建团队目录和 TeamRecord
  -> 主 Agent scope = team_lead
  -> Team(spawn_member)
  -> 校验角色、成员名、并发上限
  -> 为成员创建独立 Worktree
  -> BackendSelector 探测并选择
  -> 持久化 actual_backend 和 handle
  -> 启动 MemberRunner
  -> TeamEvent(member_started)
```

### 成员协作与审批

```text
Lead 创建带依赖任务并发送 assignment
  -> MailboxStore 落盘
  -> Backend.wake(member)
  -> MemberRunner 收件并认领任务
  -> approval_required?
       yes -> 只开放读类 + TeamPlanRequest
            -> plan_request 落盘并通知 Lead
            -> TeamPlanDecision(request_id, allow|deny)
            -> ApprovalGate 更新 + 邮件 + wake
       no  -> 直接执行
  -> Agent Loop 最终回复
  -> task completed/failed
  -> completion + idle 消息
  -> 保存 session/usage/status
```

### 恢复空闲成员

```text
TeamMessage(to=idle_member)
  -> 名称注册表命中原 MemberRecord
  -> 若后端不存活，按 actual/requested backend 重新启动
  -> 可信恢复 Worktree
  -> 恢复协议安全 JSONL 历史并按预算压缩
  -> 收取新消息
  -> 原成员继续执行
```

### 集成与发布

```text
TeamIntegrate(start)
  -> 拓扑排序 completed tasks/members
  -> 校验成员分支已提交
  -> 新建 integration branch/worktree
  -> 按序 merge
       conflict -> resolver 独占 integration worktree
                 -> 成功提交后继续 / 失败则 abort + restore
  -> integration_checks
  -> 再校验 target commit 和目标工作树
  -> ff-only 发布
  -> published event
```

## 技术决策与理由

### D1 Team 是独立领域，不扩充 SubagentTask

普通子 Agent 是一次性任务，团队成员是可恢复的长期身份。直接把成员塞进现有 `SubagentManager` 会混淆 idle、邮箱、审批和持久化语义，因此只复用 Agent Runner 基础设施，不复用一次性任务状态机。

### D2 所有成员强制 Worktree

同进程协程只是运行时轻量，不代表文件系统可以共享。统一强制 Worktree 能消除后端和角色之间的隔离差异，也让恢复与集成只处理一种代码来源。

### D3 Team 数据在用户目录，代码在项目 Worktree

团队需要跨 HuiCode 会话恢复，因此元数据不能依赖临时进程；代码又必须属于目标 Git 仓库。两类数据分离后，团队目录可安全保存邮箱和会话，而 Git 变更仍由仓库原生分支管理。

### D4 邮箱 JSONL，任务与元数据原子快照

邮箱以追加为主，JSONL 可把崩溃损失限制在最后一行；任务需要一致的依赖图和版本比较，使用锁内原子快照更容易保证整体一致性。

### D5 工具作用域在 Registry 和执行入口双重约束

只靠 Prompt 隐藏工具无法阻止历史工具调用或模型错误调用。动态规格过滤控制“看得到什么”，执行入口复核控制“真正能调用什么”。

### D6 审批决定必须走专用工具

自然语言解析容易把讨论、引用或否定句误判为批准。请求 ID 配对的结构化工具使审批可持久化、可幂等，也能在终端和协程后端间保持一致。

### D7 Auto 后端有固定顺序，显式 terminal 不降级

自动模式强调可用性，固定顺序保证行为可预测；显式 terminal 表达的是隔离要求，降级会违背用户信任边界，因此必须失败并报告。

### D8 Windows Terminal 用内部 Worker 与本地唤醒事件

Windows Terminal CLI 不提供与 tmux 完全对等的 pane 消息接口。让 pane 内 worker 持续运行，并通过邮箱加本地事件唤醒，可以保持消息可靠落盘，同时保留独立可见终端实例。

### D9 Coordinator 的 Bash 必须收窄

仅删除 Write/Edit 仍可通过 shell 重定向写文件。Coordinator 使用受限 Git 命令包装器，并把实际合并放入固定参数的集成服务，才能让“只协调不编码”成为程序保证。

### D10 专用集成 Worktree 后再发布

成员合并和验证期间不触碰用户当前工作区。目标分支漂移时拒绝发布，成功时优先 `ff-only`，既保留完整成果，也避免自动覆盖用户新提交。

### D11 成员 idle 而非销毁

成员的价值包括已经形成的任务上下文。自然停止后持久化并等待消息，可以在不占用 LLM 请求的情况下长期存在，后续指派只恢复运行后端。

### D12 独立终端与协程共享同一存储协议

后端只决定进程边界和唤醒方式，任务、邮箱、审批和状态语义全部落在相同 Store 中。这样后端故障或切换不会改变协作协议，也便于无真实终端的自动化测试。

## 需求覆盖自检

- F1-F2：TeamStore、TeamRecord、花名册和 TeamManager 生命周期。
- F3：BackendSelector、三种 Backend 与显式失败策略。
- F4：TeamWorktreeService 和每成员独立上下文。
- F5：TeamRuntimeIdentity、ScopedToolRegistry 与子 Agent 全局禁用。
- F6：SharedTaskStore、依赖图和乐观并发。
- F7-F8：NameRegistry、MailboxStore、锁文件和结构化消息。
- F9：ApprovalGate、TeamPlanRequest/Decision 与执行双重闸门。
- F10：TeamMemberRunner 的 JSONL 会话、idle 和恢复流程。
- F11：TeamManager、Lead 工具和 TeamEvent 流。
- F12：IntegrationManager、Resolver、目标漂移检查和安全发布。
- F13：Coordinator 双锁、Registry 过滤和受限 Git 命令。
- F14：TeamConfig、TUI 状态与诊断事件。
- F15：后端停止顺序、删除预检和 Worktree 保护。

所有功能需求均有对应模块、数据流和测试入口。核心依赖方向为 `CLI/Tools -> TeamManager -> Store/Backend/Runner/Integration`；存储和后端适配层不反向依赖 TUI，成员执行层不直接修改 Lead 状态文件。
