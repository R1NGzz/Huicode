# HuiCode 子 Agent 系统 Plan

## 架构概览

本章在现有 Agent Loop 外增加一层“角色目录 + 启动快照 + 任务管理器”。主 Agent 仍只运行现有 `run_agent_loop()`，但工具中心固定注册一个系统级 `Agent` 工具。每次主模型请求前，Agent Loop 向子 Agent 管理器提交一份不可变父快照；模型随后调用 `Agent` 时，工具只消费这份快照，不读取正在追加的 assistant/tool 消息，因此 Fork 天然停在协议完整边界。

子 Agent 管理器是当前进程内唯一的任务状态所有者。它使用有界守护 worker 执行任务，维护状态机、取消信号、完整结果、通知队列和待回流结果队列。前台定义式任务也在 worker 中运行，`Agent` 工具最多等待配置的前台时限；显式后台、超时或 `Ctrl+B` 后只改变任务状态和后续工具过滤，worker 本身继续执行。Fork 创建后直接进入后台。

定义式与 Fork 式共用一个执行器，但上下文构造不同：定义式创建空白 `AgentState` 并持续注入角色正文；Fork 复制父快照中的协议安全历史、稳定提示前缀和工具快照。两者都创建独立权限上下文、上下文管理器、文件读缓存和 usage 统计，并从物理工具注册表中移除 `Agent`、`Skill` 及其他不允许的工具。

后台线程只向线程安全队列写通知和结果，不直接写主历史或 TUI。CLI 主线程/通知适配器负责渲染通知；主 Agent 请求通过“结果租约”读取待交付结果，完整收集一次模型响应后确认消费，请求异常则释放租约留待重试。

## 核心数据结构与接口

### `SubagentConfig`

位于 `huicode/config.py`，作为 `LLMConfig.subagents` 的冻结配置：

```python
@dataclass(frozen=True)
class SubagentConfig:
    foreground_timeout_seconds: float = 10.0
    max_background_tasks: int = 4
    shutdown_wait_seconds: float = 2.0
    background_allowed_tools: tuple[str, ...] = ("Read", "Find", "Search")
    model_aliases: dict[str, str] = field(default_factory=dict)
```

配置加载阶段校验正数、已存在工具名、模型别名键集合及非空值。工具名校验在 MCP 和系统工具注册完成后由角色目录初始化阶段执行，因为配置解析阶段尚不知道最终工具集合。

### `AgentDefinition`

位于 `huicode/subagents/types.py`：

```python
@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    model: Literal["inherit", "haiku", "sonnet", "opus"]
    max_iterations: int
    permission_mode: PermissionMode
    instructions: str
    source: AgentSource
    source_path: Path
```

`AgentCatalogSnapshot` 保存最终定义、覆盖数、跳过数、警告和各来源数量。单文件语法错误进入警告；同层重名和安全字段错误抛出 `SubagentConfigError`。

### `ParentAgentSnapshot`

由主 Agent Loop 在每次 Provider 请求前构造：

```python
@dataclass(frozen=True)
class ParentAgentSnapshot:
    messages: tuple[ConversationMessage, ...]
    prompt: PromptBundle
    visible_tools: tuple[str, ...]
    mode: AgentMode
    permission: PermissionSnapshot
    project_instructions: str
    captured_at: float
```

快照中的消息是当前请求发送前的深拷贝，尚不包含该请求返回的 `Agent` tool call。Fork 再通过协议边界选择器剔除孤立工具结果或末尾不完整工具组。稳定提示模块保留原对象顺序和文本，供 Fork 首次请求原样复用。

### `SubagentLaunchRequest`

```python
@dataclass(frozen=True)
class SubagentLaunchRequest:
    type: Literal["defined", "fork"]
    task: str
    role: str | None
    background: bool
    origin: Literal["tool", "hook"]
    parent: ParentAgentSnapshot
```

`AgentTool.run()` 只负责参数校验、取得最新父快照并调用管理器；非法组合统一返回 `ToolResult.failure()`。

### `SubagentTask`

```python
@dataclass
class SubagentTask:
    id: str
    type: Literal["defined", "fork"]
    role: str | None
    task: str
    status: TaskStatus
    created_at: float
    started_at: float | None
    completed_at: float | None
    iterations: int
    stop_reason: str
    usage: dict[str, object]
    summary: str
    error: str
    cancel_event: threading.Event
    background_event: threading.Event
```

状态只允许以下迁移：

```text
queued -> running_foreground -> completed|failed|cancelled
queued -> running_background -> completed|failed|cancelled
running_foreground -> running_background -> completed|failed|cancelled
queued|running_* -> cancelled
```

所有状态迁移由 `SubagentManager` 在锁内完成。

### `SubagentResult`、`SubagentNotification` 与 `ResultLease`

`SubagentResult` 保存完整摘要、错误、停止原因、迭代、耗时及规范化 usage；序列化前统一脱敏敏感 header、API key、Cookie 和 thinking 内容。

`SubagentNotification` 是给 UI 的短消息，只包含任务 id、类型、角色、状态、耗时和截断摘要。

`ResultLease` 表示某次主请求暂借的一批完成结果：

```python
lease = manager.acquire_result_lease()
manager.ack_result_lease(lease.id)      # 完整模型响应后
manager.release_result_lease(lease.id)  # Provider/流失败后
```

同一结果同一时刻最多属于一个 lease，按完成时间排序。`/clear` 会使现有 lease 失效。

### `FileReadCache`

`ToolContext` 增加可选 `read_cache`，缓存键由解析后的路径、mtime 和文件大小组成。主 Agent 与每个子 Agent 分别创建实例；`Read` 工具仅在当前上下文内读写缓存。文件变化后旧键自然失效。

### `ForegroundSwitchController`

```python
class ForegroundSwitchController(Protocol):
    def wait(
        self,
        task_id: str,
        done: threading.Event,
        timeout_seconds: float,
    ) -> Literal["completed", "timeout", "manual"]: ...
```

TTY 实现用平台适配器监听 `Ctrl+B`：Windows 使用 `msvcrt.kbhit/getwch`，POSIX 使用 `select` 和临时 cbreak 模式；仅在等待前台子 Agent 时启用并在 `finally` 恢复终端。非 TTY 使用无键盘实现，仅等待完成或超时。`Ctrl+C` 不被消费，仍沿用主循环取消语义。

## 模块设计

### 角色解析与目录

**文件：** `huicode/subagents/parser.py`、`discovery.py`、`catalog.py`

**职责：**

- 解析 Markdown frontmatter 与正文，验证字段类型和名称格式。
- 从插件、内置、用户、项目四层发现 `*.md`，以低到高顺序覆盖。
- 区分可跳过的单文件语法错误与必须阻止启动的全局安全错误。
- 校验角色工具名、全局禁止工具、后台白名单及模型别名。
- 提供 `get()`、`list()`、启动统计和命令展示所需的安全元数据。

角色目录启动后保持只读，本章不实现热更新，以免运行中角色定义与任务审计信息不一致。

### 内置角色

**文件：** `huicode/subagents/builtin/general.md`、`explorer.md`、`reviewer.md`

`general` 是 Hook 默认角色；`explorer` 提供只读调查；`reviewer` 提供代码审查。内置角色使用真实工具名、保守权限和 `inherit` 模型，避免用户未配置模型别名时默认启动失败。

### 稳定 `Agent` 工具

**文件：** `huicode/subagents/tool.py`

`AgentTool` 作为 system tool 注册，Schema 固定枚举 `defined|fork`，不包含动态角色枚举。描述中列出调用约束，并把可用角色轻量目录放入动态 Prompt，而不是写入工具 Schema。工具调用流程：

1. 校验参数组合和任务文本。
2. 从管理器取得当前父快照。
3. 定义式解析角色；Fork 忽略并拒绝 `role`。
4. 向任务管理器提交。
5. 后台/Fork 立即返回任务 id。
6. 前台通过切换控制器等待完成、超时或手动后台。
7. 返回结构化完成结果或后台状态，不抛出到主 Agent Loop。

### 工具过滤与权限克隆

**文件：** `huicode/subagents/filtering.py`、`huicode/permissions/snapshot.py`

`resolve_subagent_tools()` 从父快照的实际可见普通工具开始，按固定顺序取交集/差集：全局禁止、角色 allow、角色 deny、后台 allow、PLAN 只读。它返回新的 `ToolRegistry` clone，因此模型不可见与执行器不可调用保持一致。

`snapshot_permission_context()` 复制父权限模式、项目/本地规则和会话规则；定义式再取父与角色中更严格的模式。子上下文的 confirmer 固定为 `None`，persistent path 固定为 `None`，防止子 Agent 弹确认或写回父会话/永久规则。黑名单和路径沙箱继续由现有权限执行器处理。

任务从前台转后台时设置 `background_event`。每轮子模型请求前重新计算可见工具；已提交执行器的单次工具调用不强杀，下一轮开始应用后台白名单。

### 子 Agent 执行器

**文件：** `huicode/subagents/runner.py`、`history.py`

执行器创建独立 `AgentState`、`ContextManager`、`ToolContext`、权限对象和 usage 汇总器，然后复用 `run_agent_loop()`：

- 定义式：空消息历史；用户消息为 `task`；Prompt 持续含角色正文、项目指令及本 scope Hook 注入；不接入父 memory/Skill/待交付结果。
- Fork：从 `ParentAgentSnapshot.messages` 选择协议安全前缀并追加 `task`；首次请求复用父 `PromptBundle.stable_modules`，动态模块重建；不加载角色或 active Skill。
- 每个子 Agent 使用 `agent_scope` 区分 Hook 状态。
- 监听 `cancel_event`，在安全迭代边界令 `AgentState.cancel_requested=True`。
- 聚合 `usage` 事件中的 input/output/cache 字段，不保存 thinking 原文。
- 将 final 文本作为摘要；错误、最大轮次或取消映射为结构化 `SubagentResult`。

为支持定义式角色和 Fork 稳定前缀，`build_agent_prompt()` 增加可选 `PromptOverrides`：角色正文作为每轮动态高优先级模块；Fork 可指定稳定模块覆盖。默认值为空，因此主 Agent 与 Skill 行为不变。

### 任务管理器与守护 Worker

**文件：** `huicode/subagents/manager.py`、`workers.py`

管理器维护有界任务队列和固定数量守护 worker。守护线程避免异常任务阻止 Python 进程退出；`close(timeout)` 停止接收任务、广播取消并只等待配置时限。

主要接口：

```python
capture_parent(snapshot: ParentAgentSnapshot) -> None
submit(request: SubagentLaunchRequest) -> SubagentTaskView
wait_foreground(task_id: str) -> ForegroundWaitResult
list_tasks() -> tuple[SubagentTaskView, ...]
task_detail(task_id: str) -> SubagentTaskView | None
drain_notifications() -> tuple[SubagentNotification, ...]
acquire_result_lease() -> ResultLease | None
ack_result_lease(lease_id: str) -> None
release_result_lease(lease_id: str) -> None
clear() -> None
close(timeout_seconds: float) -> None
```

显式后台和 Fork 直接标记 `running_background`；前台 worker 标记 `running_foreground`。若 worker 尚未取到任务，状态保持 `queued`，但后台属性已经记录，任务详情仍可区分预期运行方式。

### Agent Loop 集成与结果回流

**文件：** `huicode/agent.py`、`huicode/agent_events.py`、`huicode/prompts/base.py`、`builder.py`

`run_agent_loop()` 增加可选 `subagent_runtime` 与 `prompt_overrides`，默认均为空。仅 `agent_scope == "main"` 时执行：

1. 计算 selected tools 和最终 Prompt 后捕获父快照。
2. 获取待交付结果 lease，把有界、脱敏内容渲染为 `<huicode_context type="subagent_results">` 动态模块。
3. 调用 Provider。
4. 完整结束流收集后 ack；异常或中断 release。

快照必须在 Provider 调用前产生，且包含本次实际 selected tools 与 Prompt。子 Agent scope 不捕获父快照、不租用主结果，避免递归和结果串线。

Provider cache usage 沿用现有 `normalize_cache_usage()` 和 usage 事件；Fork 测试直接比较父快照与首次子请求的稳定模块文本和历史对象序列。

### Hook 对接

**文件：** `huicode/hooks/types.py`、`config.py`、`actions.py`、`manager.py`

`SubagentAction` 增加可选 `role`，配置解析允许：

```yaml
action:
  type: subagent
  role: general
  task: "..."
```

`HookActionExecutor` 通过可后绑定的 `SubagentSubmitter` 提交定义式后台任务。payload 的 `agent_scope` 以 `subagent:` 开头时直接返回 `skipped / recursion_guard`。提交、角色或队列错误只形成 Hook action result 并写现有日志。

CLI 初始化时先建立角色目录和子 Agent 管理器，再把 submitter 绑定到 Hook executor；随后把共享 HookManager 回注子 Agent runner，避免构造期循环依赖。

### CLI、命令与通知

**文件：** `huicode/commands/builtin.py`、`ui.py`、`runtime.py`、`huicode/cli.py`、`huicode/tui.py`

新增公开本地命令：

- `/agents [name]`：列角色或显示单角色安全元数据。
- `/tasks [task-id]`：列任务或显示完整任务详情。

`CLICommandRuntime` 持有角色目录和任务管理器，扩展 `/status`、`toolbar_text()` 与 `/clear`。`/clear` 先取消任务并清结果队列，再清主状态；退出路径先关闭子 Agent，再关闭 Hook、Memory、MCP。

CLI 使用通知泵读取 `SubagentNotification`。交互 TTY 通过 prompt_toolkit 的线程安全终端输出机制刷新当前输入行；非 TTY 在每次读取输入前后排空通知。通知泵是唯一触碰 TUI 的组件，worker 只写队列。

`Ctrl+B` 监听仅在 `AgentTool` 等待前台任务期间启用。TUI 显示“按 Ctrl+B 转后台”的状态提示；切换成功后工具结果行给出 task id，避免用户误以为任务被取消。

### 文件读缓存

**文件：** `huicode/tools/base.py`、`huicode/tools/files.py`

`ToolContext` 持有 `FileReadCache`。CLI 为主 Agent 创建一个实例；子 Agent runner 每次创建新的实例。读取缓存只优化同一 Agent 的重复读取，不改变返回结构和沙箱检查顺序；必须先完成路径解析与权限检查，再访问缓存。

## 模块交互与数据流

### 定义式前台流程

```text
主请求构建 Prompt/Tools
  -> SubagentManager.capture_parent(snapshot)
  -> Provider 返回 Agent(type=defined)
  -> AgentTool 校验角色并 submit
  -> worker 创建隔离状态并 run_agent_loop
  -> AgentTool 等待 completed / 10s / Ctrl+B
     -> completed: ToolResult 返回摘要与 usage
     -> timeout/manual: 状态转 background，ToolResult 返回 task id
```

### Fork 后台流程

```text
Agent(type=fork)
  -> 读取请求前 ParentAgentSnapshot
  -> 协议边界选择器校验历史
  -> 强制 background + 后台工具过滤
  -> worker 复用稳定 Prompt 前缀并运行
  -> 完成结果写任务表、通知队列、结果队列
```

### 后台结果交付流程

```text
worker 完成
  -> notification_queue
  -> CLI 通知泵安全渲染

worker 完成
  -> pending_results
  -> 下一次主 Provider 请求 acquire lease
  -> 动态 subagent_results 模块
  -> 完整响应: ack 并删除
  -> 请求失败: release 并保留
```

### Hook 子 Agent 流程

```text
Hook rule 命中
  -> 若 agent_scope=subagent:*: recursion_guard
  -> 否则渲染 task，role 默认 general
  -> submit defined/background
  -> Hook 立即记录 submitted task id
```

## 文件组织

```text
huicode/
├── subagents/
│   ├── __init__.py
│   ├── types.py
│   ├── parser.py
│   ├── discovery.py
│   ├── catalog.py
│   ├── history.py
│   ├── filtering.py
│   ├── runner.py
│   ├── workers.py
│   ├── manager.py
│   ├── tool.py
│   ├── terminal.py
│   └── builtin/
│       ├── general.md
│       ├── explorer.md
│       └── reviewer.md
├── agent.py                         # 父快照、结果 lease、Prompt override
├── agent_events.py                  # 子 Agent 可选运行时状态
├── cli.py                           # 初始化、通知、关闭顺序
├── config.py                        # SubagentConfig
├── prompts/
│   ├── base.py                      # 角色/结果/稳定模块覆盖字段
│   └── builder.py                   # 动态角色和结果模块
├── commands/
│   ├── builtin.py                   # /agents、/tasks
│   ├── runtime.py                   # 状态与清理
│   └── ui.py                        # 服务协议扩展
├── hooks/
│   ├── types.py                     # SubagentAction.role
│   ├── config.py                    # role 解析
│   └── actions.py                   # 真实提交与递归保护
├── permissions/
│   └── snapshot.py                  # 权限快照与严格度合并
└── tools/
    ├── base.py                      # ToolContext.read_cache
    └── ...                          # Read 工具接入缓存

tests/
├── test_subagent_config.py
├── test_subagent_catalog.py
├── test_subagent_history.py
├── test_subagent_filtering.py
├── test_subagent_manager.py
├── test_subagent_runner.py
├── test_subagent_tool.py
├── test_subagent_result_delivery.py
├── test_subagent_commands.py
├── test_subagent_hooks.py
├── test_subagent_terminal.py
└── test_subagent_cli_e2e.py
```

README、配置示例、本章验收报告和 `docs/mew-spec-pitfalls.md` 在实现验收阶段同步更新；踩坑文档只记录本章实际发生的返工，不预写假设问题。

## 技术决策

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| Agent 工具定义 | 固定 system tool，角色不进入 Schema | 工具列表稳定，角色变化不破坏缓存前缀 |
| 父状态传递 | Provider 请求前不可变快照 | 避免复制当前未配对 `Agent` tool call，Fork 边界确定 |
| 子任务执行 | 前台和后台统一跑在有界 worker | 支持无损超时/手动转后台，不迁移执行栈 |
| Worker 类型 | 固定数量守护线程 | 限制并发，异常任务不阻塞进程退出 |
| 后台结果消费 | acquire/ack/release 租约 | 只有完整模型响应后才消费，请求失败可重试 |
| TUI 通知 | 队列 + CLI 通知适配器 | 后台线程不直接操作 Rich 或 prompt_toolkit |
| Ctrl+B | 等待期间临时平台键监听 | 不侵入普通输入，非 TTY 可明确降级 |
| 工具限制 | clone 注册表并物理移除 | 同时约束模型可见性与执行器，不能靠 Prompt 绕过 |
| 权限隔离 | 深复制规则快照、无 confirmer/persistent path | 子 Agent 可自调策略但不能弹窗或污染父授权 |
| 后台能力 | 默认 Read/Find/Search 白名单 | 在无 Worktree 时降低并发写冲突风险 |
| Fork Prompt | 原样复用父稳定模块，动态模块重建 | 保持缓存资格，同时隔离临时状态 |
| 角色加载错误 | 语法损坏跳过，安全一致性错误致命 | 单文件问题不拖垮全部角色，越权配置不能静默运行 |
| Hook 递归 | scope 前缀硬保护 | 不依赖角色配置，确保子 Agent 不能链式创建 |
| 文件读缓存 | 每个 ToolContext 独立实例 | 满足父子隔离，又不改变 Read 工具公共协议 |
| 生命周期 | `/clear` 取消并清队列，退出有界关闭 | 防止旧结果污染新会话和退出无限等待 |

## 需求覆盖自检

| 需求 | 架构落点 |
| --- | --- |
| F1 | 稳定 `AgentTool`、`SubagentLaunchRequest` |
| F2 | parser/discovery/catalog 与四层覆盖 |
| F3 | runner 定义式空状态与 PromptOverrides |
| F4 | ParentAgentSnapshot、history、稳定模块覆盖 |
| F5 | 独立 state/context/permission/cache，复用共享 registry/provider/hook |
| F6 | filtering 与权限快照模块 |
| F7 | runner 复用 ReAct Loop 和非交互 confirmer |
| F8 | manager、worker、任务状态机和 usage 聚合 |
| F9 | AgentTool 等待策略与 terminal controller |
| F10 | notification queue、result lease、动态 Prompt 模块 |
| F11 | `/agents`、`/tasks`、status/toolbar、启动摘要 |
| F12 | Hook submitter 与 recursion_guard |
| F13 | SubagentConfig、目录启动集中校验 |

依赖方向保持单向：`types/config -> catalog/filtering/history -> runner -> manager/tool -> agent/cli/commands`。Hook 通过回调接口依赖提交能力，子 Agent manager 通过后绑定引用共享 HookManager，不形成模块导入环。
