# HuiCode Context Management Plan

## Architecture Overview

本章新增 `huicode.context` 包，集中管理上下文预算、工具结果落盘、历史摘要和压缩状态。Agent Loop 在每次请求模型前调用 ContextManager 做预处理；工具执行后仍可以立即对单个超大结果落盘，避免大结果先进入历史再等待下一轮。

上下文管理分四层：

1. **配置层**：在 LLM 配置中加入 `context` 配置块，提供上下文窗口、阈值和安全余量默认值。
2. **估算层**：用 `TokenEstimator` 做近似 token 估算，并在收到 API usage 后更新锚点。
3. **轻量压缩层**：用 `ToolResultStore` 和 `LightweightCompactor` 压缩工具结果，完整结果写入 workspace 内，历史中保留摘要、预览和路径。
4. **重量兜底层**：用 `HistorySummarizer` 和 `HistoryCompactor` 在整体历史逼近上限时生成结构化摘要，替换较早的协议安全消息组，保留近期原文和边界提示。

CLI 提供 `/compact` 手动触发整体压缩，`/config` 显示上下文管理摘要。TUI 新增上下文事件渲染，展示轻量落盘、整体摘要、跳过、失败和熔断状态。

## Core Data Structures

### `ContextConfig`

位置：`huicode/config.py`

字段：

- `enabled: bool = True`
- `window_tokens: int = 128000`
- `auto_margin_tokens: int = 13000`
- `manual_margin_tokens: int = 3000`
- `recent_keep_tokens: int = 10000`
- `min_recent_messages: int = 5`
- `single_tool_result_tokens: int = 2000`
- `tool_result_group_tokens: int = 6000`
- `preview_chars: int = 1200`
- `max_summary_failures: int = 3`

配置示例：

```yaml
context:
  enabled: true
  window_tokens: 128000
  single_tool_result_tokens: 2000
  tool_result_group_tokens: 6000
```

### `ContextState`

位置：`huicode/context/state.py`

字段：

- `last_input_tokens: int | None`
- `last_estimated_request_tokens: int | None`
- `last_estimated_chars: int | None`
- `summary_failure_count: int`
- `summary_fuse_open: bool`
- `summary_count: int`
- `last_summary_tokens_freed: int`
- `last_compaction_reason: str`

职责：保存会话级上下文状态，挂到 `AgentState.context`。`/clear` 时重置。

### `TokenEstimate`

位置：`huicode/context/estimator.py`

字段：

- `tokens: int`
- `chars: int`
- `source: Literal["usage_anchor", "chars"]`

### `TokenEstimator`

接口：

```python
class TokenEstimator:
    def estimate_text(self, text: str) -> int: ...
    def estimate_message(self, message: ConversationMessage) -> TokenEstimate: ...
    def estimate_messages(self, messages: list[ConversationMessage]) -> TokenEstimate: ...
    def estimate_request(self, messages, prompt, tools) -> TokenEstimate: ...
    def record_usage(self, state: ContextState, usage: dict[str, object], request_estimate: TokenEstimate) -> None: ...
```

规则：

- 默认 `tokens = ceil(chars / 4)`。
- 如果最近一次请求有 `input_tokens` 或 `prompt_tokens`，记录 usage 锚点。
- 后续估算优先用上次输入 token 与字符差修正增量。
- usage 缺失时退回字符估算。

### `ToolResultStore`

位置：`huicode/context/store.py`

接口：

```python
class ToolResultStore:
    def spill(self, call: ToolCall, result: ToolResult, iteration: int, reason: str) -> SpillRecord: ...
```

落盘路径：

```text
<workspace>/.huicode/tool-results/turn-XXX-<tool-call-id>.json
```

文件内容为完整 `ToolResult.to_model_dict()` JSON。路径必须用 workspace 内相对路径写回历史。

### `SpillRecord`

字段：

- `path: str`
- `original_chars: int`
- `compact_chars: int`
- `tokens_freed: int`
- `preview: str`
- `reason: str`

### `ContextCompressionReport`

位置：`huicode/context/types.py`

字段：

- `kind: Literal["lightweight", "summary", "skip", "failure", "fuse"]`
- `spilled_count: int = 0`
- `summary_created: bool = False`
- `tokens_before: int = 0`
- `tokens_after: int = 0`
- `tokens_freed: int = 0`
- `message: str = ""`
- `paths: tuple[str, ...] = ()`

用于 AgentEvent 和 TUI 渲染。

### `HistorySegment`

位置：`huicode/context/segments.py`

字段：

- `messages: list[ConversationMessage]`
- `estimated_tokens: int`
- `contains_tool_pair: bool`

切分规则：

- 普通 user/assistant 文本消息可单独成段。
- assistant 带 tool_calls 时，必须和紧随其后的所有 tool messages 组成同一段。
- orphan tool message 作为不可拆安全段保留，不单独丢弃。

这个结构保证压缩 cutoff 只发生在协议安全边界上，不破坏 Anthropic 的 `tool_use` / `tool_result` 关系，也不破坏 OpenAI 的 `tool_call_id` 对应关系。

## Module Design

### `huicode.context.manager`

**Responsibility:** Agent Loop 的上下文管理入口。

接口：

```python
class ContextManager:
    def compact_tool_result(self, call, result, context, iteration) -> tuple[ToolResult, ContextCompressionReport | None]: ...
    def prepare_before_request(self, provider, state, context, config, prompt, tools, mode) -> ContextPreparation: ...
    def manual_compact(self, provider, state, context, config, prompt, tools) -> ContextCompressionReport: ...
    def record_usage(self, state, usage, request_estimate) -> None: ...
    def reset(self, state) -> None: ...
```

`prepare_before_request()` 顺序：

1. 运行轻量聚合压缩，处理历史中尚未压缩的大工具结果。
2. 估算完整请求 token。
3. 如果未接近阈值，返回 skip 报告。
4. 如果接近阈值且未熔断，调用整体摘要压缩。
5. 如果摘要失败，增加失败计数；达到 3 次后打开熔断。

### `huicode.context.lightweight`

**Responsibility:** 压缩工具结果。

接口：

```python
def compact_single_tool_result(call, result, store, config, estimator, iteration) -> tuple[ToolResult, SpillRecord | None]: ...
def compact_tool_groups(messages, store, config, estimator) -> ContextCompressionReport: ...
```

行为：

- 单个工具结果估算超过 `single_tool_result_tokens` 时落盘。
- 同一 assistant tool_calls 后的一组 tool results 合计超过 `tool_result_group_tokens` 时，按估算 token 从大到小依次落盘。
- 已包含 `__spilled__` 的结果跳过，避免重复落盘。
- 压缩后的 `ToolResult.data` 保留常用元信息、`preview`、`__spilled__` 和原 summary。

### `huicode.context.summarizer`

**Responsibility:** 调 LLM 生成正式摘要。

接口：

```python
class HistorySummarizer:
    def summarize(self, provider, messages_to_summarize, config) -> SummaryResult: ...
```

摘要请求：

- 使用同一个 provider。
- `tools=[]`，`allow_tool_calls=False`。
- 不传普通 Agent 工具描述。
- Prompt 要求输出：

```xml
<draft>...</draft>
<summary>
## 当前任务
...
</summary>
```

处理规则：

- 如果流式事件里出现 tool_call，视为失败。
- 如果没有 `<summary>`，视为失败。
- 只提取 `<summary>` 内容进入历史，丢弃 `<draft>`。
- 摘要失败不修改原历史。

### `huicode.context.history`

**Responsibility:** 按预算选择摘要区和保留区，重写历史。

接口：

```python
def split_recent_messages(messages, config, estimator) -> tuple[list[ConversationMessage], list[ConversationMessage]]: ...
def apply_summary(messages_to_replace, recent_messages, summary_text) -> list[ConversationMessage]: ...
```

保留规则：

- 从尾部按段累计，保留至少 `min_recent_messages` 条消息。
- 在满足最小条数后继续保留，直到近期原文约 `recent_keep_tokens`。
- cutoff 只落在 `HistorySegment` 边界。

重写后的历史：

1. 一条 summary context message，包含结构化摘要。
2. 一条 compression boundary message，说明摘要只是导航信息，需要细节必须重新读取。
3. 原文保留区消息。

summary 和 boundary 使用 `role="user"`，内容带特殊标签：

```xml
<huicode_context type="conversation_summary" scope="compressed_history">...</huicode_context>
<huicode_context type="compression_boundary" scope="compressed_history">...</huicode_context>
```

### `huicode.context.events`

**Responsibility:** 生成上下文管理事件数据。

`AgentEventKind` 增加：

```python
"context"
```

事件 `data` 使用 `ContextCompressionReport` 的 dict 表示。

### `huicode.tui`

**Responsibility:** 渲染上下文管理事件。

显示示例：

```text
HuiCode> 上下文整理...
  ◦ spilled 2 tool result(s) to disk (~5300 tokens freed)
  ◦ summary created (~42000 -> ~18000 tokens)
```

失败或熔断：

```text
HuiCode> 上下文压缩失败: 摘要没有返回正式 summary
HuiCode> 上下文摘要已熔断，本轮仅执行轻量压缩
```

### `huicode.cli`

**Responsibility:** 新增命令和状态展示。

新增命令：

- `/compact`：手动触发整体压缩。
- `/context`：查看上下文状态摘要。

`/clear` 增加：

- 清空 messages 和 last_plan。
- 重置 context state。

`/config` 增加：

```text
context_window=128000 context_summary_count=1 context_fuse=false
```

不显示任何 secret 或落盘文件内容。

### `huicode.config`

**Responsibility:** 解析 `context` 配置块。

当前配置解析器支持一层嵌套，`context` 与 `thinking`、`headers` 同级。所有数值字段必须为正整数，布尔字段必须是 true/false。

### Provider 序列化测试

OpenAI/Anthropic Provider 不需要知道压缩细节，但需要确保压缩后消息仍能序列化。测试重点：

- summary/boundary 普通 user message 可序列化。
- assistant tool_calls 与紧随 tool messages 仍保持成组。
- 压缩不会留下 orphan tool result。

## Module Interactions

### 普通 Agent Loop

```text
user input
  -> append user message
  -> build prompt and tool specs
  -> ContextManager.prepare_before_request()
       -> lightweight group compaction
       -> estimate request
       -> maybe summary compaction
       -> emit context events
  -> rebuild prompt and tool specs if history changed
  -> provider.stream_chat()
  -> collect text/thinking/tool_calls/usage
  -> ContextManager.record_usage()
  -> append assistant message
  -> execute tools
       -> ContextManager.compact_tool_result() for single oversized result
       -> append compacted tool message
       -> emit tool_result and context event if spilled
  -> next iteration
```

### 手动压缩

```text
/compact
  -> build prompt and tool specs for estimate
  -> ContextManager.manual_compact()
       -> lightweight group compaction
       -> force summary attempt if there is compressible history
       -> use manual_margin_tokens
       -> emit context report
  -> print status
```

如果历史太短或没有可摘要的早期消息，返回 skip，不调用 provider。

### Usage 锚点

```text
provider usage event
  -> collect_model_response stores usage
  -> Agent Loop records request estimate + usage
  -> TokenEstimator updates ContextState anchor
```

优先读取：

- `input_tokens`
- `prompt_tokens`

缓存字段不改变估算，只用于 TUI usage 原样展示。

## File Organization

```text
huicode/
├── context/
│   ├── __init__.py
│   ├── estimator.py
│   ├── events.py
│   ├── history.py
│   ├── lightweight.py
│   ├── manager.py
│   ├── segments.py
│   ├── state.py
│   ├── store.py
│   └── summarizer.py
├── agent.py
├── agent_events.py
├── cli.py
├── config.py
└── tui.py

tests/
├── test_context_estimator.py
├── test_context_lightweight.py
├── test_context_history.py
├── test_context_summarizer.py
├── test_context_manager.py
├── test_agent_context.py
├── test_cli_context.py
├── test_tui.py
├── test_openai_provider_tools.py
└── test_anthropic_provider_tools.py

specs/
└── 009-context-management/
    ├── spec.md
    ├── plan.md
    ├── task.md
    ├── checklist.md
    └── acceptance_report.md
```

## Technical Decisions

| Decision Point | Choice | Rationale |
| --- | --- | --- |
| Token 估算 | 字符数近似 + usage 锚点 | 符合本章“不做精确 tokenizer”，同时能利用真实 API usage 修正漂移。 |
| 工具结果落盘路径 | 继续使用 `.huicode/tool-results` | 兼容现有行为和测试，避免迁移已生成文件。 |
| 整体摘要调用 | 复用当前 provider，`allow_tool_calls=False` | 不引入第二套 LLM 配置，满足禁止工具调用要求。 |
| 摘要解析 | `<draft>` + `<summary>` 标签，保留 summary | 明确丢弃草稿，测试可观察。 |
| 历史切分 | 按协议安全段切分 | 避免破坏 Anthropic/OpenAI 工具调用序列。 |
| Summary/boundary 角色 | 使用带特殊标签的 user message | 现有 `ConversationMessage` 只有 user/assistant/tool；特殊标签说明它是系统注入上下文，不是用户新请求。 |
| 自动压缩失败 | 失败 3 次熔断，仅停止重量摘要 | 防止每轮死循环，同时保留轻量压缩收益。 |
| 手动命令 | `/compact` 和 `/context` | `/compact` 动词明确，`/context` 可查看状态，符合现有短命令风格。 |
| 配置默认窗口 | `window_tokens=128000` | 给现代长上下文模型一个保守默认值，用户可按模型调小。 |
| TUI 事件 | 新增 `context` event | 比复用 `progress` 更清晰，便于测试和后续扩展。 |

## Requirement Coverage

| Requirement | Plan Coverage |
| --- | --- |
| F1-F4 | `LightweightCompactor`、`ToolResultStore`、Agent preflight 和工具执行后单结果压缩。 |
| F5-F7 | `ContextConfig`、`ContextState`、`TokenEstimator` 和 auto/manual margin。 |
| F8-F10 | `HistorySegment`、`split_recent_messages()`、结构化 summary prompt。 |
| F11-F12 | `HistorySummarizer` 使用 `allow_tool_calls=False`，解析 `<summary>` 丢弃 `<draft>`。 |
| F13 | `apply_summary()` 插入 compression boundary special tag。 |
| F14-F17 | `/compact`、`/context`、`context` AgentEvent 和 TUI 渲染。 |
| F18 | 协议安全段切分 + Provider 序列化回归测试。 |
| F19 | 对所有 `ToolResult` 统一处理，不区分本地/MCP 工具。 |
| F20 | `ContextManager.reset()` 接入 `/clear`。 |
