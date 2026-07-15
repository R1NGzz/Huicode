# HuiCode Hook 系统 Plan

## 架构概览

Hook 系统采用“配置目录 + 标准事件 + 调度器 + 动作执行器 + 动态提示状态 + JSONL 日志”六部分结构。

启动时，配置加载器分别读取用户级文件、当前 `huicode.yaml` 内联规则和项目级文件，使用 PyYAML 完整解析列表与嵌套映射，按规则 id 合并后一次性完成字段、条件、动作和事件兼容性校验。合法规则构成不可变 HookCatalog，交给会话级 HookManager 管理。

运行时，CLI 和 Agent Loop 在既有生命周期边界构造 HookEvent。HookManager 按目录顺序匹配规则：同步规则立即执行；后台规则提交给受控 daemon worker 池；`tool_before` 的明确拒绝转换为 ToolResult 并走原有工具结果回灌路径。Hook 的 command、HTTP、prompt 和 subagent 行为由统一 ActionExecutor 分发，所有结果进入追加式 HookLogger。

提示词动作不直接修改对话消息。会话级指令保存在 HookManager，轮次级和 next-request 指令保存在对应 AgentState 的 HookRuntimeState；构建 PromptBundle 时把有效 Hook 块插到 active Skill 与环境信息之间。主 Agent 和 isolated Skill 共用 HookManager，但各自拥有轮次提示状态，防止子会话的临时指令污染主历史。

上下文管理不直接依赖 Hook 模块。ContextManager 接收轻量生命周期回调，在真正尝试重量摘要前后通知调用方；Agent 和 Slash Command Runtime 再把通知转换为 HookEvent。

## 核心数据结构与接口

### HookEventName

```python
HookEventName = Literal[
    "session_start", "session_end",
    "turn_start", "turn_end",
    "message_received", "message_completed",
    "tool_before", "tool_after",
    "context_before_compact", "context_after_compact",
    "agent_error",
]
```

事件名只在一个常量集合中维护，配置校验、事件工厂和测试共享该集合。

### HookEvent

```python
@dataclass(frozen=True)
class HookEvent:
    name: HookEventName
    occurred_at: str
    session_id: str
    workspace: Path
    mode: str
    turn_id: str | None
    iteration: int
    agent_scope: str
    data: dict[str, Any]

    def to_payload(self) -> dict[str, Any]: ...
```

`agent_scope` 区分 `main` 与 `skill:<name>`。`to_payload()` 只输出 JSON 可序列化、递归脱敏且长度受控的数据，不输出 Python 对象、thinking 原文或认证配置。

### HookRule 与 HookCatalog

```python
@dataclass(frozen=True)
class HookRule:
    id: str
    event: HookEventName
    condition: HookCondition | None
    action: HookAction
    enabled: bool = True
    once: bool = False
    async_run: bool = False
    timeout_seconds: int = 30
    source: str = "unknown"
    source_path: str = ""

@dataclass(frozen=True)
class HookCatalog:
    rules: tuple[HookRule, ...]
    disabled_count: int
    source_counts: dict[str, int]
```

HookAction 是 CommandAction、PromptAction、HttpAction、SubagentAction 的联合类型。目录构建完成后不再修改；本章不支持热更新。

### HookCondition

```python
MatchOperator = Literal["exact", "glob", "regex"]
ConditionMode = Literal["all", "any"]

@dataclass(frozen=True)
class HookPredicate:
    field: str
    operator: MatchOperator
    value: str
    negate: bool = False

@dataclass(frozen=True)
class HookCondition:
    mode: ConditionMode
    predicates: tuple[HookPredicate, ...]
```

YAML 中普通叶子使用 `field + exact/glob/regex`；反向叶子使用以下形状，`not` 内仍只能有一个匹配器：

```yaml
- field: tool.arguments.path
  not:
    glob: "**/generated/**"
```

字段路径使用点号访问事件 payload。列表索引、通配字段名和任意表达式不支持。配置阶段检查字段是否属于该事件的公开 schema。

### 动作数据结构

```python
@dataclass(frozen=True)
class CommandAction:
    type: Literal["command"]
    command: str
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class PromptAction:
    type: Literal["prompt"]
    content: str
    scope: Literal["next_request", "turn", "session"] = "next_request"

@dataclass(frozen=True)
class HttpAction:
    type: Literal["http"]
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    expected_status: tuple[int, int] = (200, 299)

@dataclass(frozen=True)
class SubagentAction:
    type: Literal["subagent"]
    task: str
```

命令参数和环境、HTTP URL 与 headers 在配置加载时完成 `${VAR}` 展开。Prompt `content` 与 subagent `task` 保留事件字段模板，模板仅允许 `{{公开.字段.路径}}`，由受限替换器按纯文本渲染。

### HookActionResult 与 HookDispatchResult

```python
HookStatus = Literal[
    "success", "denied", "failed", "timeout", "skipped", "scheduled"
]

@dataclass(frozen=True)
class HookActionResult:
    status: HookStatus
    message: str = ""
    deny_reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class HookDispatchResult:
    denied: bool = False
    denied_by: str = ""
    deny_reason: str = ""
    records: tuple[HookActionResult, ...] = ()
```

只有同步 `tool_before` command 的退出码 2 或 HTTP 的合法 deny 响应能设置 `denied=True`。其他事件即使动作输出 deny，也只按普通成功结果记录。

### HookRuntimeState 与 HookPromptBlock

```python
@dataclass(frozen=True)
class HookPromptBlock:
    rule_id: str
    scope: Literal["next_request", "turn", "session"]
    content: str
    source_event: HookEventName

@dataclass
class HookRuntimeState:
    turn_id: str = ""
    next_request_blocks: list[HookPromptBlock] = field(default_factory=list)
    turn_blocks: list[HookPromptBlock] = field(default_factory=list)
```

`AgentState` 新增 `hooks: HookRuntimeState`。session 块由 HookManager 持有，确保主 Agent 与 Skill 子会话共享会话级注入；turn 和 next-request 块跟随各自 AgentState。

### HookManager

```python
class HookManager:
    def start_session(self, event: HookEvent, state: HookRuntimeState) -> HookDispatchResult: ...
    def dispatch(self, event: HookEvent, state: HookRuntimeState) -> HookDispatchResult: ...
    def prompt_blocks(self, state: HookRuntimeState) -> tuple[str, ...]: ...
    def consume_next_request(self, state: HookRuntimeState) -> None: ...
    def end_turn(self, state: HookRuntimeState) -> None: ...
    def close(self, event: HookEvent | None = None) -> None: ...
    def summary(self) -> HookStatusSummary: ...
```

内部包含 once 规则集合、后台 daemon worker 池、pending future 集合、session prompt 块和 HookLogger。`dispatch()` 兜住匹配、模板和动作异常；任何异常都转换为 failed 日志，不向 Agent 抛出。

### ContextLifecycleCallbacks

```python
@dataclass(frozen=True)
class ContextLifecycleCallbacks:
    before_compact: Callable[[dict[str, Any]], None] | None = None
    after_compact: Callable[[ContextCompressionReport], None] | None = None
```

ContextManager 的自动和手动压缩入口接受可选 callbacks；只在准备调用重量摘要时触发 before，并对 summary、skip、failure、fuse 结果触发 after。轻量工具结果落盘仍由既有 `context` AgentEvent 表示，不额外触发重量压缩 Hook。

## 模块设计

### `huicode/hooks/types.py`

**职责：** 定义事件、规则、条件、动作、运行结果、Prompt 状态和状态摘要等纯数据类型。

**对外接口：** 上述 dataclass、Literal 与事件 schema 常量。

**依赖：** 标准库；不依赖 CLI、Agent、Provider 或工具实现。

### `huicode/hooks/config.py`

**职责：** 计算用户/项目配置路径，读取三层 YAML，解析环境变量，按 id 合并，并把错误包装为 HookConfigError。

**对外接口：**

```python
def hook_config_paths(workspace: Path) -> HookConfigPaths: ...
def load_hook_catalog(
    paths: HookConfigPaths,
    inline_hooks: list[dict[str, Any]] | None = None,
    environ: Mapping[str, str] | None = None,
) -> HookCatalog: ...
```

**合并顺序：** 用户级规则先加入；内联和项目规则按层处理。高层相同 id 先删除旧项，再按高层声明位置追加，因此覆盖后的执行顺序由最高有效来源决定。

**校验：**

- id 在单一来源内唯一，且只允许字母、数字、`.`、`_`、`-`。
- event、if、action、布尔值、timeout 类型和范围合法。
- `all`/`any` 二选一且至少有一个叶子。
- 每个叶子只含一个匹配方式；regex 在加载时预编译。
- `tool_before` 禁止 async 与 subagent。
- prompt 禁止 async，`session_end` 禁止 prompt。
- timeout 默认 30 秒、允许 1-300 秒。
- 未定义环境变量、未知事件字段和未知模板字段直接报错。

### `huicode/hooks/matching.py`

**职责：** 安全读取事件字段并执行 exact/glob/regex/not 与 all/any 匹配。

**对外接口：**

```python
def match_condition(condition: HookCondition | None, payload: Mapping[str, Any]) -> bool: ...
def match_value(actual: str, operator: MatchOperator, expected: str) -> bool: ...
```

为了真正复用权限语义，新增通用字符串匹配函数；`huicode.permissions.rules.match_rule()` 改为调用它的 exact-or-glob 兼容入口，权限规则现有行为不变。工具事件工厂继续复用 `target_value_for_call()`，并通过公开的 canonical tool helper 统一 `Glob`/`Find`。

### `huicode/hooks/events.py`

**职责：** 为每类生命周期构造标准 HookEvent，递归脱敏并限制预览长度。

**对外接口：** session、turn、message、tool、context、error 事件工厂，以及 `sanitize_payload()`。

递归脱敏键名至少覆盖 api_key、authorization、cookie、password、secret、token；字符串预览默认最多 4KB，集合限制最大项数。工具参数保留结构，但敏感键的值替换为 `[REDACTED]`。

### `huicode/hooks/actions.py`

**职责：** 执行四种动作并把任何运行状态转成 HookActionResult。

**Command：**

- 先使用既有危险命令黑名单检查完整命令文本。
- cwd 通过 `resolve_workspace_path()` 解析真实路径并限制在 workspace。
- 以 UTF-8 JSON bytes 作为 stdin，捕获 bytes 后复用稳健解码策略。
- 命令与配置参数使用平台安全引用组合，不把事件字段拼进命令行。
- 退出码 0 为 success，2 在 `tool_before` 为 denied，其他退出码为 failed。
- stdout/stderr 各保留 4KB 预览；TimeoutExpired 转 timeout。

**HTTP：**

- 使用标准库 HTTP 客户端，发送 `application/json; charset=utf-8`。
- 非预期状态、连接异常、超时和非 JSON deny 响应转为 failed/timeout。
- `tool_before` 的 2xx JSON `{ "decision": "deny", "reason": "..." }` 转 denied。

**Prompt：** 渲染模板后调用 HookManager 提供的注入回调；内容包装为 `<huicode_instruction type="hook" ...>`，只进入动态 PromptModule。

**Subagent：** 返回 skipped，message 固定为“SubAgent 动作尚未实现”，不调用 Provider。

### `huicode/hooks/logger.py`

**职责：** 线程安全地向 `<workspace>/.huicode/logs/hooks.jsonl` 追加单行 JSON，负责最终脱敏与记录大小限制。

**对外接口：** `HookLogger.write(record)`。单行包含 timestamp、rule_id、event、action、status、duration_ms、agent_scope 和 summary。写日志异常在内部吞掉并累计 `write_failures`，不能递归记录自身错误。

### `huicode/hooks/manager.py`

**职责：** 规则筛选、once 控制、同步/异步调度、Prompt 生命周期、拒绝聚合、后台任务收拢和统计。

**调度顺序：**

1. 从目录按顺序筛选 enabled 且 event 相同的规则。
2. 计算 condition；不匹配不产生日志。
3. once 规则在提交/执行前原子标记，失败也不重跑。
4. async 规则写 scheduled 后提交受控 worker 池，完成回调补写最终状态。
5. 同步规则立即执行并写最终状态。
6. `tool_before` 遇到 denied 后停止余下规则并返回拒绝信息。

后台执行器固定为小规模 daemon worker，避免 Hook 数量直接创建线程，也避免解释器退出阶段隐式等待普通线程。`close()` 先可选发送 session_end，再停止接收任务，最多等待 2 秒；剩余任务取消或记录 skipped，不无限阻塞。

### `huicode/config.py`

**职责变更：** `LLMConfig` 增加 `hooks` 原始列表字段；主配置改用 PyYAML safe_load，以支持 Hook 所需的“列表内嵌映射”结构。

现有字段转换与业务校验继续保留，确保 protocol、context、memory、mcp 等错误文本不因换解析器而丢失。YAML 语法错误统一带行列号包装为 ConfigError。Hook 细节不在主配置层重复解析，只确认 `hooks` 是列表且每项是映射。

### `huicode/agent_events.py`

**职责变更：** AgentState 增加 HookRuntimeState；不把 Hook 内部执行记录加入 AgentEventKind，保持 TUI 默认安静。

### `huicode/agent.py`

**职责变更：** 接受可选 HookManager 和 ContextManager，并在现有循环边界发布事件。

关键时序：

```text
turn_start Hook
  -> 追加 user message
  -> message_received Hook
  -> 构建含 Hook blocks 的 Prompt
  -> 自动 context_before/context_after Hook
  -> Provider 流式响应
  -> 消费 next_request Prompt blocks
  -> 追加 assistant message
  -> message_completed Hook
  -> 无工具: turn_end Hook -> done
  -> 有工具:
       每个调用 tool_before Hook
       -> 若拒绝，直接构造 hook_denied ToolResult
       -> 否则 Plan Mode 检查 -> 权限系统 -> 工具执行
       -> tool_after Hook
       -> 工具结果压缩、写历史、继续下一轮
```

并发读工具仍可并发执行，但所有 `tool_before` 先在主线程按模型调用顺序完成。被 Hook/Plan 拒绝的项不提交线程池；其余读工具再并发。`tool_after` 按原调用顺序触发，保持历史稳定。

Provider/API/Agent 错误先发布 agent_error，再输出既有 error/done 事件。外层在观察到 done 时发布一次 turn_end，并清理 turn blocks；next-request blocks 若本轮从未发生 Provider 请求，也随 turn 清理，避免泄漏到下一用户轮。

### `huicode/prompts/base.py` 与 `huicode/prompts/builder.py`

**职责变更：** PromptContext 增加 `hook_instruction_blocks`；Builder 生成非缓存动态模块，顺序为：

```text
active Skill blocks
-> Hook instruction blocks
-> environment
-> 既有 supplemental modules
```

每个 Hook 块独立成 PromptModule，不写用户消息、不进入稳定缓存、不被上下文摘要改写。

### `huicode/context/manager.py`

**职责变更：** 自动与手动重量压缩接受 ContextLifecycleCallbacks，在 `_run_summary` 调用前后通知。回调异常由调用方 HookManager 吞掉，不改变压缩结果。

### `huicode/skills/runner.py`

**职责变更：** SkillRunner 接收共享 HookManager 与 ContextManager，并传入子 Agent Loop。子 Agent 使用自己的 AgentState.hooks，因此 turn/next-request Prompt 隔离；session Prompt 与 once 规则仍为进程级共享。事件载荷标明 `skill:<name>` scope。

### `huicode/commands/runtime.py`

**职责变更：** 保存 HookManager；手动 `/compact` 通过 ContextLifecycleCallbacks 发布压缩事件；`/clear` 清理当前 AgentState 的 turn/next-request Hook 注入但保留 session 注入和 once 标记；`/status` 增加 Hook 有效数、pending、失败数和日志路径摘要。

### `huicode/cli.py`

**职责变更：**

1. 在 MCP、权限、记忆、Skill 初始化完成后加载 HookCatalog 并创建 HookManager。
2. 完成 Runtime、ToolRegistry 与 PromptSession 接线后发布 session_start。
3. 启动信息输出 `Hooks effective=N disabled=N sources=...`。
4. 普通 AI 请求和 isolated Skill 都传入 HookManager/ContextManager。
5. 所有正常退出路径统一发布 session_end，并调用 HookManager.close() 后再关闭 Memory/MCP。
6. HookConfigError 显示为“Hook 配置错误”并以状态码 2 退出。

Slash Command 本地操作不触发 turn/message 事件；只有真正送入 Agent 的输入触发。`/compact` 只触发 context 系统事件。

### `huicode/permissions/rules.py`、`blacklist.py` 与 `engine.py`

**职责变更：** 提取并公开规范化工具名和共享字符串匹配；Hook command 直接复用危险命令检查。`.huicode/logs` 加入后台状态保护目录，防止模型通过 Write/Edit 修改 Hook 日志；读取仍可按原权限规则执行。

## 模块交互

### 启动与关闭

```text
CLI
  -> load_config() 得到 inline hooks
  -> 初始化 MCP / 权限 / 记忆 / Skill
  -> load_hook_catalog(user, inline, project)
  -> HookManager(catalog, workspace)
  -> session_start
  -> 交互循环
  -> session_end
  -> HookManager.close(2s)
  -> MemoryManager.close()
  -> MCPManager.close()
```

Hook 配置错误发生在进入交互循环前，已启动的 Memory/MCP 资源按现有清理路径关闭。

### 工具拦截与回灌

```text
LLM ToolCall
  -> HookEvent(tool_before)
  -> HookManager.dispatch()
     -> 条件匹配
     -> ActionExecutor
     -> denied?
        yes -> ToolResult.failure("hook_denied", reason, rule_id)
        no  -> Plan Mode -> Permission -> Tool.run()
  -> HookEvent(tool_after)
  -> 轻量结果压缩
  -> ConversationMessage(role="tool")
  -> 下一轮 LLM
```

Hook 拒绝发生在权限确认之前，因此不会出现“先让用户批准、再被 Hook 拦截”的重复交互。

### Prompt 注入

```text
Hook prompt action
  -> 模板字段安全替换
  -> 按 scope 放入 manager/session 或 AgentState/hooks
  -> build_agent_prompt()
  -> 动态 Hook PromptModule
  -> Provider request
  -> consume next_request blocks
  -> turn_end 清理 turn blocks
```

同一规则多次注入不做内容去重；是否只执行一次由 `once` 明确控制，避免隐式策略。

### 后台动作

```text
dispatch(async rule)
  -> once 原子标记
  -> log scheduled
  -> executor.submit(action)
  -> Agent 立即继续
  -> callback: log success/failed/timeout
  -> session close: bounded drain
```

后台回调不接触 AgentState、ConversationMessage 或 TUI，只写日志和原子统计。

## 文件组织

```text
huicode/
├── hooks/
│   ├── __init__.py          # Hook 公共导出
│   ├── types.py             # 事件、规则、动作、状态数据类型
│   ├── config.py            # 三层 YAML 加载、覆盖、校验
│   ├── matching.py          # 条件字段访问和匹配
│   ├── events.py            # 标准事件构造、脱敏、截断
│   ├── actions.py           # command/prompt/http/subagent 动作
│   ├── logger.py            # JSONL 追加日志
│   └── manager.py           # 调度、once、后台任务、Prompt 生命周期
├── agent.py                 # 发布 Agent/消息/工具/错误事件
├── agent_events.py          # AgentState 挂载 HookRuntimeState
├── cli.py                   # Hook 初始化、session 事件和资源关闭
├── config.py                # inline hooks 与完整 YAML 解析
├── commands/runtime.py      # compact、clear、status 集成
├── context/manager.py       # 重量压缩回调
├── permissions/
│   ├── rules.py             # 共享 exact/glob 语义与工具规范化
│   └── engine.py            # 保护 Hook 日志目录
├── prompts/
│   ├── base.py              # PromptContext 增加 Hook blocks
│   └── builder.py           # 动态 Hook 指令模块
└── skills/runner.py         # isolated Skill 复用 HookManager

tests/
├── test_hooks_config.py     # 三层合并、YAML 和集中校验
├── test_hooks_matching.py   # exact/glob/regex/not/all/any
├── test_hooks_events.py     # 载荷、脱敏和预览限制
├── test_hooks_actions.py    # 四类动作、拒绝、超时和沙箱
├── test_hooks_manager.py    # once、异步、日志、Prompt 生命周期
├── test_agent_hooks.py      # Agent/工具/错误/回灌集成
└── test_cli_hooks.py        # 启动摘要、session、compact、退出 E2E

specs/013-hook-system/
├── spec.md
├── plan.md
├── task.md
├── checklist.md
└── acceptance_report.md
```

现有 `test_config.py`、`test_permissions_rules.py`、`test_prompt_builder.py`、`test_agent_context.py`、`test_cli.py` 和 `test_cli_skills.py` 补充兼容回归用例。

## 需求覆盖

| 需求 | 技术落点 |
| --- | --- |
| F1 | hooks/config.py、LLMConfig.hooks、PyYAML safe_load、HookCatalog |
| F2 | hooks/events.py、agent.py、cli.py、context callbacks |
| F3 | hooks/matching.py、共享 match_value、配置预编译 regex |
| F4 | HookManager.dispatch、execute_tool_batches 的前置同步拦截、hook_denied ToolResult |
| F5 | hooks/actions.py 四类 Action dataclass 与执行分发 |
| F6 | HookRuntimeState、HookManager session blocks、PromptBuilder 动态模块 |
| F7 | once 集合、受控 daemon worker、timeout、close bounded drain |
| F8 | HookLogger、ActionResult、manager 全边界异常兜底 |
| F9 | HookEvent.to_payload、stdin/HTTP JSON、blacklist 与 sandbox 复用 |
| F10 | CLI 启动摘要、Runtime status、HookManager.close |

## 技术决策

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| YAML 解析 | 主配置和 Hook 配置使用 PyYAML safe_load | Hook 需要列表内映射和多层嵌套，继续扩展手写解析器风险高；项目已声明 PyYAML 依赖 |
| 配置合并 | 相同 id 整体替换并移动到高层声明位置 | 保留高优先级来源对规则内容和执行顺序的完整控制 |
| 事件结构 | 统一 HookEvent + 分层 data | 动作、日志、HTTP 和条件共享同一 payload，减少绑定 |
| 条件组合 | 单层 all/any，叶子可 not | 满足当前表达能力，同时避免引入表达式解释器和复杂优先级 |
| 权限语义复用 | 提取共享 match_value，保留权限 exact-or-glob 行为 | 真正共享 glob/精确匹配且不改变已有权限配置 |
| 拒绝协议 | command exit 2、HTTP 2xx deny JSON | 将明确策略决定与运行故障分开，符合失败不打断主流程的要求 |
| 工具 Hook 顺序 | Hook before -> Plan -> Permission -> Tool -> Hook after | 拒绝尽早发生，不产生无意义权限确认；结果仍走统一回灌 |
| 并发工具 | tool_before 串行，允许项再并发；tool_after 按调用顺序 | 兼顾确定性、安全性和原有读工具并发效率 |
| Prompt 存储 | session 在 Manager，turn/next 在 AgentState | session 可共享，子 Agent 临时注入不污染主 Agent |
| Prompt 位置 | active Skill 后、environment 前的非缓存动态模块 | 保持 Skill 的既有最高位置，同时让 Hook 指令在环境和普通补充信息前可见 |
| next_request 清理 | Provider 请求结束的 finally 中消费 | 成功或失败都算已尝试下一次请求，避免错误后意外常驻 |
| Hook 可观测性 | 默认静默，JSONL 日志 + 启动/状态摘要 | 自动化不刷屏，同时保留完整诊断证据 |
| HTTP 实现 | Python 标准库 | 不增加网络客户端依赖，当前同步/worker 模型足够 |
| 后台执行 | 小型 daemon worker 池 + 2 秒有界收拢 | 兼容现有同步生成器架构，且解释器退出不会隐式等待超时后的任务 |
| Skill 集成 | 共享 Manager、独立 RuntimeState | isolated Skill 也受安全 Hook 约束，但临时 Prompt 生命周期隔离 |
| 子 Agent 动作 | 校验配置并返回 skipped | 现在固定未来 schema，不提前耦合尚不存在的 SubAgent 实现 |

## 风险与缓解

- **主配置解析器替换产生兼容差异：** 保留所有现有字段转换、错误包装和完整 `test_config.py`；增加已有样例配置回归测试。
- **并发读工具绕过前置 Hook：** 在提交 ThreadPoolExecutor 之前统一执行所有 tool_before；测试同时覆盖多个工具调用。
- **Hook 拒绝破坏 Anthropic 工具消息配对：** 每个被拒 ToolCall 仍生成一条紧随 assistant tool_use 的 tool_result，并复用现有批处理顺序测试。
- **提示词跨轮泄漏：** next-request 在 Provider finally 消费，turn 在 done 时清理，`/clear` 清理临时块；分别断言三种作用域。
- **Hook 错误触发递归：** Hook 内部错误只交给 HookLogger，不发布 agent_error。
- **后台线程修改会话状态：** 异步仅允许 command/HTTP 等无即时上下文动作，后台回调禁止持有 AgentState。
- **事件载荷泄密：** 事件工厂与日志器两次递归脱敏，HTTP headers 只记录键名和遮罩值。
- **命令动作越界：** 命令文本先过不可绕过黑名单，cwd 必须解析到 workspace 内，事件参数只走 stdin 不拼命令行。
- **正常退出遗漏 session_end：** CLI 所有退出分支收敛到统一资源关闭函数，并用单次标记保证只发布一次。
- **Windows UTF-8 与进程输出问题：** stdin 固定 UTF-8 bytes，stdout/stderr 使用既有 UTF-8/系统编码/GB18030 回退策略。

## 验证策略

1. **单元测试：** 配置覆盖、条件矩阵、模板字段、递归脱敏、动作结果、once、异步、超时和 Prompt 清理。
2. **集成测试：** fake Provider 发出单个和多个 ToolCall，验证 Hook 拒绝后协议配对、权限确认不触发及 Agent 继续。
3. **上下文测试：** 自动与 `/compact` 手动压缩分别验证 before/after 事件，skip/failure 也有 after。
4. **CLI 测试：** 临时 HOME/workspace 三层配置，验证启动摘要、session start/end、status 和配置错误清理。
5. **隔离 Skill 测试：** isolated Skill 内工具调用同样触发 Hook，子会话 turn Prompt 不进入主 AgentState。
6. **故障测试：** 不存在命令、HTTP 断连、无效 JSON、日志目录不可写和超时均不改变 Agent 最终 stop_reason。
7. **回归测试：** 运行完整 unittest 与 compileall，确认无 Hook 配置时现有 286 项基线行为不变。
8. **端到端验收：** Windows 无 tmux 时使用真实 CLI 输入流 + fake Provider；配置一个拒绝 Write 的 command Hook、一个 tool_after 后台日志 Hook和一个 turn_start Prompt Hook，观察目标文件、模型第二轮、日志和退出时长。
