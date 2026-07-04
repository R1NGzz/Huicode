# HuiCode 工具系统技术方案

## 架构概览
本阶段在现有聊天架构上增加三层能力：工具层、工具调度层、Provider 工具调用适配层。CLI 仍负责交互循环和流式展示；Provider 仍负责供应商协议差异；新增工具层提供统一工具接口和六个核心工具；新增调度层负责执行一次工具调用、展示 Claude Code 风格工具行、把工具调用和结果写回会话历史，再触发最终回复。

工具调用采用“一次工具回合”策略：每次用户输入后，HuiCode 向模型发送工具列表；如果模型请求工具，HuiCode 执行第一个工具调用，回灌结果，然后再请求模型生成最终回复；如果最终回复阶段模型再次请求工具，本阶段只记录并提示不继续执行。OpenAI 官方函数调用流程也是“发送工具、收到调用、应用侧执行、把结果发回模型、再拿最终回复”的多步对话；OpenAI 流式工具调用会在 `delta.tool_calls` 中分片返回 `arguments`，需要聚合为完整 JSON。Anthropic 工具使用中，客户端工具由应用执行，Claude 返回 `tool_use`，应用再发送 `tool_result`；其流式工具参数通过 `input_json_delta.partial_json` 分片返回。

文件类工具默认限制在当前项目工作目录内。命令执行默认在当前工作目录运行，带超时、输出截断和结构化错误，避免交互会话被异常或长时间命令拖死。

## 核心数据结构和接口

### `Tool`
```python
class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ...
```

字段说明：
- `name`：模型调用时使用的工具名。
- `description`：给模型看的能力说明。
- `parameters`：JSON Schema 风格参数说明。
- `run`：执行工具，永远返回 `ToolResult`，不把异常抛到 CLI。

### `ToolContext`
字段：
- `workspace: Path`，当前项目根目录。
- `timeout_seconds: int`，命令类工具默认超时。
- `max_output_chars: int`，命令输出和搜索结果摘要最大长度。

### `ToolResult`
字段：
- `ok: bool`，工具是否成功。
- `data: dict[str, Any] | None`，成功结果。
- `error: ToolError | None`，失败结果。
- `summary: str`，TUI 中展示的简洁摘要。

### `ToolError`
字段：
- `code: str`，机器可读错误码，如 `not_found`、`multiple_matches`、`timeout`。
- `message: str`，给模型和用户看的错误说明。
- `details: dict[str, Any]`，补充上下文。

### `ToolCall`
字段：
- `id: str`，供应商返回的调用 ID；缺失时由 HuiCode 生成。
- `name: str`，工具名。
- `arguments: dict[str, Any]`，完整 JSON 参数。
- `raw_arguments: str`，拼接后的原始 JSON 字符串。

### `ConversationMessage`
字段：
- `role: Literal["user", "assistant", "tool"]`
- `content: str`
- `tool_calls: list[ToolCall]`
- `tool_call_id: str | None`
- `tool_name: str | None`
- `tool_result: ToolResult | None`

说明：这是 HuiCode 内部统一会话历史。Provider 负责把它序列化为各自 API 所需格式：OpenAI 的 assistant `tool_calls` + tool 消息，Anthropic 的 assistant `tool_use` 内容块 + user `tool_result` 内容块。

### `StreamEvent`
扩展为：
- `kind="text"`：普通文本增量。
- `kind="thinking"`：Claude thinking 增量。
- `kind="tool_call"`：完整工具调用请求。

### `Provider`
```python
class Provider(Protocol):
    name: str
    model: str

    def stream_chat(
        self,
        messages: list[ConversationMessage],
        tools: list[ToolSpec] | None = None,
        allow_tool_calls: bool = True,
    ) -> Iterator[StreamEvent]:
        ...
```

`allow_tool_calls=False` 用于工具结果回灌后的最终回复阶段，避免本阶段自动执行第二次工具调用。

### `ToolRegistry`
职责：
- `register(tool)`：登记工具。
- `get(name)`：按名查找工具。
- `list()`：返回全部工具。
- `to_specs()`：返回统一 `ToolSpec` 列表，交给 Provider 转成供应商格式。

## 模块设计

### `huicode.tools.base`
**职责：** 定义 `Tool`、`ToolContext`、`ToolResult`、`ToolError`、`ToolSpec`、路径安全辅助函数。  
**外部接口：** `safe_join_workspace(workspace, path)`、各核心数据结构。  
**依赖：** Python 标准库。

### `huicode.tools.registry`
**职责：** 集中登记和查询工具，提供默认六工具注册函数。  
**外部接口：** `ToolRegistry`、`create_default_registry(workspace) -> ToolRegistry`。  
**依赖：** 六个工具实现。

### `huicode.tools.files`
**职责：** 实现 `ReadFileTool`、`WriteFileTool`、`EditFileTool`。  
**外部接口：** 三个 Tool 类。  
**行为：**
- `read_file(path)`：读取 UTF-8 文本文件。
- `write_file(path, content)`：创建父目录并写入 UTF-8 文本。
- `edit_file(path, old_text, new_text)`：要求 `old_text` 在文件中恰好出现一次，否则失败且不改文件。

### `huicode.tools.shell`
**职责：** 实现 `RunCommandTool`。  
**外部接口：** `RunCommandTool`。  
**行为：** 在 workspace 中执行命令，捕获退出码、stdout、stderr、超时状态；不使用 shell 字符串拼接删除文件，首版通过 PowerShell 执行用户给出的命令文本并限制超时。

### `huicode.tools.search`
**职责：** 实现 `FindFilesTool` 和 `SearchCodeTool`。  
**外部接口：** 两个 Tool 类。  
**行为：**
- `find_files(pattern)`：使用标准库 `Path.rglob` 匹配相对路径或文件名模式。
- `search_code(pattern, glob=None)`：逐行读取文本文件，返回文件、行号、片段。

### `huicode.tools.executor`
**职责：** 校验工具名、参数类型，执行工具并捕获异常。  
**外部接口：** `execute_tool_call(registry, call, context) -> ToolResult`。  
**依赖：** `ToolRegistry`、`ToolContext`。

### `huicode.tui`
**职责：** Claude Code 风格工具行和结果摘要格式化。  
**外部接口：** `format_tool_call_line(call) -> str`、`format_tool_result_line(result) -> str`。  
**示例输出：**
```text
● Read(huicode/cli.py)
  ⎿  ok, 83 lines, 2870 chars
```

### `huicode.providers.base`
**职责：** 扩展统一会话消息、工具调用和流式事件类型。  
**外部接口：** `ConversationMessage`、`ToolCall`、`StreamEvent`、`Provider`。

### `huicode.providers.openai`
**职责：** 转换工具定义为 OpenAI Chat Completions function tools；解析 `delta.tool_calls` 的分片 JSON 参数；序列化工具调用与工具结果历史。  
**关键点：**
- 请求中加入 `tools`。
- 设置 `parallel_tool_calls=False`，让本阶段尽量只收到一个工具调用。
- 累积 `tool_calls[index].function.arguments`。
- 流结束后解析完整 JSON 并产出 `StreamEvent(kind="tool_call")`。

### `huicode.providers.anthropic`
**职责：** 转换工具定义为 Anthropic `tools`；解析 `tool_use` content block 和 `input_json_delta.partial_json`；序列化 `tool_result` 历史。  
**关键点：**
- 请求中加入 `tools` 的 `name`、`description`、`input_schema`。
- 在 `content_block_start` 记录 `tool_use` 的 `id` 和 `name`。
- 在 `input_json_delta.partial_json` 中累积参数片段。
- 在 content block 结束或 message stop 时解析 JSON 并产出工具调用事件。

### `huicode.agent`
**职责：** 单次工具回合编排。  
**外部接口：** `run_agent_turn(provider, registry, context, messages, user_text, config) -> Iterator[StreamEvent]` 或 CLI 直接调用的等价函数。  
**流程：**
1. 追加用户消息。
2. 请求模型，允许工具调用。
3. 若只收到文本，流式输出并保存 assistant 回复。
4. 若收到工具调用，保存 assistant 工具调用消息。
5. TUI 打印 `● ToolName(arg_summary)`。
6. 执行工具，打印结果摘要。
7. 保存 tool 结果消息。
8. 第二次请求模型，`allow_tool_calls=False`。
9. 流式输出最终文本并保存 assistant 回复。
10. 若第二次仍收到工具调用，只记录提示，不执行。

### `huicode.cli`
**职责：** 创建默认工具注册中心和工具上下文，调用 agent turn，保留现有 `/exit`、`/clear`、`/config`。  
**变化：** CLI 不直接执行工具，只负责展示和会话生命周期。

## 模块交互和数据流
1. 用户启动 HuiCode。
2. CLI 加载配置、创建 Provider、创建默认 ToolRegistry 和 ToolContext。
3. 用户输入问题。
4. Agent 将用户消息加入 `messages`。
5. Agent 调用 `provider.stream_chat(messages, tools=registry.to_specs(), allow_tool_calls=True)`。
6. Provider 把工具 schema 转为供应商格式并发送请求。
7. Provider 解析 SSE：文本直接产出；工具参数分片先累积，完整后产出 `ToolCall`。
8. Agent 若收到 `ToolCall`，显示工具行，调用 executor 执行工具。
9. executor 返回 `ToolResult`，失败也结构化返回。
10. Agent 显示结果摘要，把 assistant tool call 和 tool result 写入统一会话历史。
11. Agent 调用 `provider.stream_chat(..., allow_tool_calls=False)` 生成最终回复。
12. CLI 流式打印最终回复，保存 assistant 文本。

## 文件组织
```text
Huicode/
├── spec.md
├── plan.md
├── task.md
├── checklist.md
├── huicode/
│   ├── agent.py
│   ├── cli.py
│   ├── tui.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── openai.py
│   │   └── anthropic.py
│   └── tools/
│       ├── __init__.py
│       ├── base.py
│       ├── executor.py
│       ├── files.py
│       ├── registry.py
│       ├── search.py
│       └── shell.py
└── tests/
    ├── test_agent.py
    ├── test_anthropic_provider_tools.py
    ├── test_openai_provider_tools.py
    ├── test_tools_files.py
    ├── test_tools_registry.py
    ├── test_tools_search.py
    ├── test_tools_shell.py
    └── test_tui.py
```

## 技术决策
| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 工具接口 | Protocol + JSON Schema 字典 | 简洁，符合当前无外部依赖风格，也容易映射到不同 Provider。 |
| 工具结果 | `ToolResult` 永远返回结构化结果 | 让模型能基于错误重试，不让 CLI 崩溃。 |
| 路径限制 | 所有文件路径 resolve 后必须位于 workspace 内 | 满足规格中的工作目录边界。 |
| 文件修改 | `old_text` 恰好出现一次才替换 | 避免模糊改动和误改。 |
| 命令执行 | `subprocess.run(..., timeout=...)` | 标准库实现超时、退出码、stdout/stderr 捕获。 |
| 搜索实现 | 标准库递归遍历 | 首版无需依赖 `rg`，测试稳定；后续可优化为优先 `rg`。 |
| Provider 工具格式 | Provider 内部转换 | CLI 和工具层不感知 OpenAI/Anthropic 差异。 |
| OpenAI 多工具控制 | `parallel_tool_calls=False` 且只执行第一个工具调用 | 满足本阶段一次工具回合。 |
| Anthropic 多工具控制 | 首版只执行第一个 `tool_use` | 与本阶段范围一致，后续 Agent Loop 再扩展。 |
| TUI 工具行 | `● ToolName(args)` + 缩进摘要 | 贴近 Claude Code 风格，信息密度高。 |
| 最终回复阶段 | `allow_tool_calls=False` | 防止本阶段进入自动循环。 |

## 需求覆盖自检
- F1、F13、F14 由 ToolRegistry、ToolSpec 和 Provider 转换覆盖。
- F2-F10 由六个核心工具覆盖。
- F11-F12、F23 由 ToolResult、ToolError 和 executor 覆盖。
- F15 由 OpenAI/Anthropic Provider 的流式工具调用累积器覆盖。
- F16-F17 由 `huicode.tui` 和 Agent 编排覆盖。
- F18-F19 由统一 `ConversationMessage` 和 Provider 序列化覆盖。
- F20 由 Agent 单次工具回合和最终回复阶段 `allow_tool_calls=False` 覆盖。
- F21 由无工具调用时的文本流路径覆盖。
- F22 由路径安全辅助函数和文件类工具覆盖。

## 参考
- OpenAI Function Calling 文档：工具调用流程、Chat Completions `tools`、流式 `delta.tool_calls` 和参数聚合。
- Anthropic Tool Use 文档：客户端工具由应用执行、返回 `tool_use` 后应用发送 `tool_result`。
- Anthropic Streaming 文档：工具参数以 `input_json_delta.partial_json` 流式分片返回。
