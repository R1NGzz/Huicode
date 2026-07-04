# HuiCode Agent Loop 与 Plan Mode 技术方案

## 架构概览
本阶段把现有“一次工具回合”的 `run_agent_turn` 改造为多轮 ReAct Agent Loop。Provider 仍然负责模型协议和流式工具调用解析；工具层仍然负责执行工具和返回结构化结果；新增 Agent 事件流作为 Agent 与 TUI 的边界。CLI 不再直接依赖 Agent 内部细节，而是消费事件并渲染文本、工具行、进度、错误和停止原因。

Agent Loop 每次迭代调用一次 LLM。若模型只输出文本且没有工具调用，循环结束；若模型请求工具，Agent 先把 assistant 的文本、thinking、tool_calls 写入历史，再按安全策略执行工具，把结果写入历史，然后进入下一轮。循环由停止条件兜底：最终回答、迭代上限、用户取消、连续未知工具、Provider/流式错误。

Plan Mode 通过 CLI 状态控制工具可见性。`/plan` 后，Agent 只向模型暴露读类工具，并把用户请求作为计划任务执行；`/do` 后，Agent 切回全工具，并把最近计划作为上下文继续执行。Plan Mode 不实现权限确认，只是工具集合收窄。

## 核心数据结构和接口

### `AgentMode`
```python
AgentMode = Literal["chat", "plan", "do"]
```
- `chat`：默认模式，允许全工具。
- `plan`：只允许读类工具。
- `do`：执行最近计划，允许全工具。

### `AgentOptions`
字段：
- `max_iterations: int`，默认 8。
- `max_unknown_tools: int`，默认 2。
- `mode: AgentMode`，当前模式。
- `read_only_tool_names: set[str]`，默认 `{"Read", "Find", "Search", "Glob"}`。

### `AgentState`
字段：
- `messages: list[ConversationMessage]`，会话历史。
- `last_plan: str`，最近一次 Plan Mode 产出的计划文本。
- `cancel_requested: bool`，取消标记。
- `unknown_tool_count: int`，连续未知工具计数。
- `iterations: int`，本轮请求已执行迭代数。

### `AgentEvent`
```python
@dataclass(frozen=True)
class AgentEvent:
    kind: Literal[
        "text",
        "thinking",
        "tool_call",
        "tool_result",
        "progress",
        "usage",
        "error",
        "done",
    ]
    text: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    iteration: int | None = None
    stop_reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)
```

### `CollectedResponse`
字段：
- `text: str`
- `thinking: str`
- `thinking_signature: str`
- `tool_calls: list[ToolCall]`
- `usage: dict[str, Any]`

作用：流式收集器一边把增量转成 `AgentEvent` 给 TUI，一边保存完整响应供历史写入和循环判断。

### `ToolBatch`
字段：
- `parallel_read_calls: list[ToolCall]`
- `serial_calls: list[ToolCall]`

作用：把同一轮模型返回的多个工具调用按安全性分批。

## 模块设计

### `huicode.agent_events`
**职责：** 定义 `AgentEvent`、`CollectedResponse`、`AgentOptions`、`AgentState`。  
**外部接口：** 事件和状态数据结构。

### `huicode.agent`
**职责：** 实现 ReAct Agent Loop、流式收集、停止条件、工具分批执行、Plan Mode 工具过滤。  
**外部接口：**
```python
def run_agent_loop(
    provider: Provider,
    registry: ToolRegistry,
    context: ToolContext,
    state: AgentState,
    user_text: str,
    config: LLMConfig,
    options: AgentOptions,
) -> Iterator[AgentEvent]:
    ...
```

核心内部函数：
- `collect_model_response(...) -> Iterator[AgentEvent]`：把 Provider `StreamEvent` 转成 AgentEvent，同时收集完整响应。
- `select_tools(registry, options) -> list[ToolSpec]`：根据模式返回全工具或只读工具。
- `batch_tool_calls(calls, registry) -> ToolBatch`：读类工具可并发，副作用工具串行。
- `execute_tool_batches(...) -> Iterator[AgentEvent]`：执行工具、产出工具事件、写回历史。

### `huicode.tools.base`
**职责变化：** 给工具增加安全分类。  
新增属性：
- `side_effect: bool`，读类工具为 `False`，写文件、改文件、执行命令为 `True`。

### `huicode.tools.registry`
**职责变化：** 支持按工具名集合导出 specs，并保留别名。  
新增接口：
- `to_specs(allowed_names: set[str] | None = None) -> list[ToolSpec]`
- `is_side_effect(name: str) -> bool`

### `huicode.tui`
**职责变化：** 从 AgentEvent 渲染输出。  
新增接口：
- `render_agent_event(event, output)`：渲染文本、工具调用、工具结果、进度、错误、done。

### `huicode.cli`
**职责变化：** 管理 Plan Mode 状态和命令。  
行为：
- `/plan <任务>`：进入 Plan Mode 并立刻以只读工具运行任务。
- `/plan`：只切换到 Plan Mode，下一条用户输入作为计划任务。
- `/do <任务>`：进入执行模式，结合最近计划和任务运行。
- `/do`：使用最近计划继续执行。
- `/clear`：清空消息、计划和状态。
- 普通输入：默认全工具 Agent Loop。

### `huicode.providers.base`
**职责变化：** 支持一次模型响应中多个工具调用。  
现有 `StreamEvent(kind="tool_call")` 可被多次产出；Agent 收集器保存全部 tool calls。

### `huicode.providers.openai` / `huicode.providers.anthropic`
**职责变化：** 保持现有多 tool_call 事件产出能力，补充 token usage 解析若供应商流式返回 usage。若没有 usage，不阻塞流程。

## 模块交互和数据流
1. 用户输入普通请求、`/plan` 或 `/do`。
2. CLI 更新 `AgentState` 和 `AgentOptions`，调用 `run_agent_loop`。
3. Agent 追加用户消息；若 `/do` 且有 `last_plan`，把计划作为上下文加入请求文本。
4. Agent 根据模式选择工具集合。
5. Agent 调用 Provider 流式请求模型。
6. 收集器实时产出 `text/thinking/tool_call/usage` 事件，同时收集完整响应。
7. 如果没有工具调用，Agent 写入 assistant 文本，若在 Plan Mode 则更新 `last_plan`，产出 `done`。
8. 如果有工具调用，Agent 写入 assistant tool_calls。
9. Agent 分批执行工具：读类并发，副作用串行。
10. 每个工具执行前产出 `tool_call` 事件，执行后产出 `tool_result` 事件，并把结果写入历史。
11. Agent 进入下一轮迭代。
12. 达到停止条件时产出 `done` 或 `error` 事件。
13. CLI 用 `render_agent_event` 渲染输出并回到输入提示。

## 文件组织
```text
Huicode/
├── specs/
│   └── 003-agent-loop-plan-mode/
│       ├── spec.md
│       ├── plan.md
│       ├── task.md
│       └── checklist.md
├── huicode/
│   ├── agent.py
│   ├── agent_events.py
│   ├── cli.py
│   ├── tui.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── openai.py
│   │   └── anthropic.py
│   └── tools/
│       ├── base.py
│       ├── registry.py
│       └── ...
└── tests/
    ├── test_agent_loop.py
    ├── test_agent_events.py
    ├── test_cli_plan_mode.py
    ├── test_tool_batching.py
    └── ...
```

## 技术决策
| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 循环模型 | ReAct：模型 -> 工具 -> 观察 -> 模型 | 符合用户目标，直接复用现有工具回灌能力。 |
| 事件边界 | Agent 产出 `AgentEvent`，TUI 渲染事件 | 让 Agent 和界面解耦，后续可替换 TUI。 |
| 文本双路 | 流式事件实时输出，同时 `CollectedResponse` 保存完整内容 | 满足实时显示和历史判断两种需求。 |
| 默认迭代上限 | 8 | 足够完成小任务，防止无限循环。 |
| 未知工具上限 | 连续 2 次 | 防止模型反复调用不存在工具。 |
| 并发模型 | 读类工具用线程池并发，副作用工具串行 | 标准库可实现，安全边界清楚。 |
| 读类工具集合 | `Read`、`Find`、`Search`、`Glob` | Plan Mode 能分析项目但不能修改。 |
| `/plan` 语义 | 只读工具 + 保存最近计划 | 避免计划阶段产生副作用。 |
| `/do` 语义 | 全工具 + 注入最近计划上下文 | 让执行阶段延续计划。 |
| usage 事件 | 有则透传，无则跳过 | 兼容不同 Provider。 |
| 用户取消 | 捕获 KeyboardInterrupt 作为 cancel stop | 不引入交互确认系统。 |

## 需求覆盖自检
- F1-F3 由 `run_agent_loop` 的迭代流程覆盖。
- F4-F7 由停止条件和错误事件覆盖。
- F8-F9 由 `AgentEvent` 和 TUI 渲染边界覆盖。
- F10-F12 由流式收集器和历史写入覆盖。
- F13-F16 由多工具收集、分批和并发/串行执行覆盖。
- F17-F21 由 CLI Plan Mode、`/plan`、`/do` 和最近计划状态覆盖。
- F22 由 `/clear` 状态清理覆盖。
- F23 由现有工具/TUI/边界保留和回归测试覆盖。
- F24 由 thinking/signature 历史保留覆盖。
- F25 通过范围控制和不新增权限/压缩/确认模块满足。
