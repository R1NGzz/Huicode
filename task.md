# HuiCode 工具系统实施任务

## 文件清单

| 动作 | 文件 | 职责 |
| --- | --- | --- |
| 修改 | `huicode/providers/base.py` | 扩展统一会话消息、工具调用、工具规格和流式事件类型。 |
| 创建 | `huicode/tools/__init__.py` | 导出工具包公共接口。 |
| 创建 | `huicode/tools/base.py` | 定义 Tool、ToolContext、ToolResult、ToolError、ToolSpec 和路径安全函数。 |
| 创建 | `huicode/tools/files.py` | 实现读文件、写文件、改文件工具。 |
| 创建 | `huicode/tools/search.py` | 实现按模式找文件和搜代码内容工具。 |
| 创建 | `huicode/tools/shell.py` | 实现执行命令工具。 |
| 创建 | `huicode/tools/registry.py` | 实现工具注册中心和默认六工具注册。 |
| 创建 | `huicode/tools/executor.py` | 实现工具查找、参数校验、异常捕获和执行包装。 |
| 创建 | `huicode/tui.py` | 实现 Claude Code 风格工具行和结果摘要格式化。 |
| 修改 | `huicode/providers/openai.py` | 支持工具 schema 转换、工具历史序列化、流式工具调用参数拼接。 |
| 修改 | `huicode/providers/anthropic.py` | 支持工具 schema 转换、工具历史序列化、流式 tool_use 参数拼接。 |
| 创建 | `huicode/agent.py` | 实现一次工具调用回合编排和历史回灌。 |
| 修改 | `huicode/cli.py` | 接入 ToolRegistry、ToolContext、Agent 编排和工具 TUI 展示。 |
| 修改 | `tests/test_cli.py` | 适配新消息结构并补 CLI 工具路径测试。 |
| 创建 | `tests/test_tools_files.py` | 覆盖文件工具行为和路径越界。 |
| 创建 | `tests/test_tools_search.py` | 覆盖找文件和搜代码工具。 |
| 创建 | `tests/test_tools_shell.py` | 覆盖命令执行成功、失败和超时。 |
| 创建 | `tests/test_tools_registry.py` | 覆盖注册中心和未知工具。 |
| 创建 | `tests/test_tui.py` | 覆盖 Claude Code 风格工具行和摘要。 |
| 创建 | `tests/test_openai_provider_tools.py` | 覆盖 OpenAI 工具 schema、历史序列化、流式工具调用拼接。 |
| 创建 | `tests/test_anthropic_provider_tools.py` | 覆盖 Anthropic 工具 schema、历史序列化、流式 input_json_delta 拼接。 |
| 创建 | `tests/test_agent.py` | 覆盖一次工具回合、回灌历史、禁止第二次自动工具调用。 |

## T1: 扩展统一 Provider 类型

**文件：** `huicode/providers/base.py`

**依赖：** 无

**步骤：**
1. 新增 `ToolSpec`、`ToolCall`、`ConversationMessage` 数据结构。
2. 将 `StreamEvent.kind` 扩展为 `text`、`thinking`、`tool_call`。
3. 调整 `Provider.stream_chat` 签名，支持 `tools` 和 `allow_tool_calls`。
4. 保留与文本流兼容的构造方式，减少旧测试改动面。

**验证：** 运行 `python -m compileall -q huicode/providers`；预期无语法错误。

## T2: 实现工具基础类型和路径安全

**文件：** `huicode/tools/__init__.py`、`huicode/tools/base.py`

**依赖：** T1

**步骤：**
1. 定义 `Tool` 协议、`ToolContext`、`ToolResult`、`ToolError`。
2. 定义成功和失败结果的辅助构造函数。
3. 实现 `safe_join_workspace(workspace, path)`，拒绝 workspace 外路径。
4. 导出工具包基础类型。

**验证：** 运行 `python -m compileall -q huicode/tools`；预期无语法错误。

## T3: 实现文件工具

**文件：** `huicode/tools/files.py`、`tests/test_tools_files.py`

**依赖：** T2

**步骤：**
1. 实现 `ReadFileTool`，读取 UTF-8 文本并返回内容、行数、字符数。
2. 实现 `WriteFileTool`，在 workspace 内创建父目录并写入 UTF-8 文本。
3. 实现 `EditFileTool`，仅在 `old_text` 恰好出现一次时替换。
4. 对文件不存在、路径越界、匹配不到、匹配多次返回结构化错误。
5. 添加单元测试覆盖成功和失败路径。

**验证：** 运行 `python -m unittest tests.test_tools_files -v`；预期全部通过。

## T4: 实现搜索工具

**文件：** `huicode/tools/search.py`、`tests/test_tools_search.py`

**依赖：** T2

**步骤：**
1. 实现 `FindFilesTool`，按相对路径或文件名模式返回匹配文件。
2. 实现 `SearchCodeTool`，逐行搜索文本模式，返回文件、行号、片段。
3. 跳过明显二进制文件和解码失败文件。
4. 对路径越界和参数错误返回结构化错误。
5. 添加单元测试覆盖匹配、无匹配和结果限制。

**验证：** 运行 `python -m unittest tests.test_tools_search -v`；预期全部通过。

## T5: 实现命令工具

**文件：** `huicode/tools/shell.py`、`tests/test_tools_shell.py`

**依赖：** T2

**步骤：**
1. 实现 `RunCommandTool`，在 workspace 内执行命令。
2. 捕获 `returncode`、`stdout`、`stderr`、`timed_out`。
3. 支持工具参数覆盖超时，但不得超过上下文最大超时策略。
4. 超时或异常时返回结构化失败结果。
5. 添加单元测试覆盖成功命令、非零退出和超时。

**验证：** 运行 `python -m unittest tests.test_tools_shell -v`；预期全部通过。

## T6: 实现注册中心和执行器

**文件：** `huicode/tools/registry.py`、`huicode/tools/executor.py`、`tests/test_tools_registry.py`

**依赖：** T3、T4、T5

**步骤：**
1. 实现 `ToolRegistry.register/get/list/to_specs`。
2. 实现 `create_default_registry(workspace)`，注册六个核心工具。
3. 实现 `execute_tool_call`，处理未知工具、参数非对象、工具异常。
4. 保证所有失败都返回 `ToolResult(ok=False)`。
5. 添加单元测试覆盖注册、查找、六工具存在、未知工具、异常包装。

**验证：** 运行 `python -m unittest tests.test_tools_registry -v`；预期全部通过。

## T7: 实现 TUI 工具行格式化

**文件：** `huicode/tui.py`、`tests/test_tui.py`

**依赖：** T1、T2

**步骤：**
1. 实现 `format_tool_call_line(call)`。
2. 实现 `format_tool_result_line(result)`。
3. 为路径、命令、搜索模式等常见参数生成短摘要。
4. 控制输出长度，避免工具行过长。
5. 添加单元测试覆盖 `● Read(path)` 风格和成功/失败摘要。

**验证：** 运行 `python -m unittest tests.test_tui -v`；预期全部通过。

## T8: 改造 OpenAI Provider 工具能力

**文件：** `huicode/providers/openai.py`、`tests/test_openai_provider_tools.py`、既有 `tests/test_openai_provider.py`

**依赖：** T1、T6

**步骤：**
1. 将统一 `ToolSpec` 转换为 OpenAI `tools` function schema。
2. 当 `allow_tool_calls=False` 时禁用工具调用。
3. 序列化 assistant tool call 和 tool result 历史。
4. 解析流式 `delta.tool_calls`，按 index 拼接 function name、id、arguments。
5. 流结束后解析完整 JSON 参数并产出 `StreamEvent(kind="tool_call")`。
6. 保持普通文本流测试继续通过。
7. 添加工具 schema、工具历史和分片 JSON 参数测试。

**验证：** 运行 `python -m unittest tests.test_openai_provider tests.test_openai_provider_tools -v`；预期全部通过。

## T9: 改造 Anthropic Provider 工具能力

**文件：** `huicode/providers/anthropic.py`、`tests/test_anthropic_provider_tools.py`、既有 `tests/test_anthropic_provider.py`

**依赖：** T1、T6

**步骤：**
1. 将统一 `ToolSpec` 转换为 Anthropic `tools` schema。
2. 当 `allow_tool_calls=False` 时不发送工具列表。
3. 序列化 assistant `tool_use` 和 user `tool_result` 历史。
4. 解析 `content_block_start` 的 `tool_use` 元信息。
5. 拼接 `input_json_delta.partial_json` 参数片段。
6. 在 block 结束或 message stop 时产出 `StreamEvent(kind="tool_call")`。
7. 保持普通文本和 thinking 流测试继续通过。
8. 添加工具 schema、工具历史和分片 JSON 参数测试。

**验证：** 运行 `python -m unittest tests.test_anthropic_provider tests.test_anthropic_provider_tools -v`；预期全部通过。

## T10: 实现一次工具回合 Agent 编排

**文件：** `huicode/agent.py`、`tests/test_agent.py`

**依赖：** T6、T7、T8、T9

**步骤：**
1. 实现单次用户请求处理：追加用户消息、第一次请求模型。
2. 若只有文本事件，保存 assistant 文本并结束。
3. 若收到工具调用，保存 assistant 工具调用消息。
4. 打印工具调用行，执行工具，打印结果摘要。
5. 保存 tool result 消息。
6. 第二次请求模型，设置 `allow_tool_calls=False`。
7. 保存最终 assistant 文本。
8. 如果第二次仍出现工具调用，提示不执行并结束。
9. 添加测试覆盖无工具路径、一次工具路径、历史回灌、禁止第二次工具执行。

**验证：** 运行 `python -m unittest tests.test_agent -v`；预期全部通过。

## T11: 接入 CLI

**文件：** `huicode/cli.py`、`tests/test_cli.py`

**依赖：** T10

**步骤：**
1. CLI 启动时创建 `ToolContext` 和默认 `ToolRegistry`。
2. 将会话历史类型切换为 `ConversationMessage`。
3. 普通输入交给 Agent 编排。
4. 保留 `/exit`、`/quit`、`/clear`、`/config` 行为。
5. 确保 `/config` 不输出 API key。
6. 更新 CLI 单元测试，覆盖工具行输出和历史保留。

**验证：** 运行 `python -m unittest tests.test_cli -v`；预期全部通过。

## T12: 更新说明文档

**文件：** `README.md`

**依赖：** T11

**步骤：**
1. 增加工具系统说明。
2. 列出六个核心工具。
3. 说明本阶段只执行一次工具调用回合。
4. 说明文件工具的 workspace 边界。

**验证：** 阅读 README，确认命令、配置和范围说明与实现一致。

## T13: 完整测试和编译检查

**文件：** 全部实现和测试文件

**依赖：** T1-T12

**步骤：**
1. 运行全部单元测试。
2. 运行 Python 编译检查。
3. 修复所有失败。

**验证：** 运行 `python -m unittest discover -v` 和 `python -m compileall -q huicode tests`；预期全部通过。

## T14: tmux 端到端验收

**文件：** `checklist.md`、运行中的 HuiCode

**依赖：** T13、已批准的 `checklist.md`

**步骤：**
1. 使用有效 `huicode.yaml` 在 tmux 中启动 `python -m huicode --config huicode.yaml`。
2. 提问要求读取一个当前 workspace 内文件。
3. 观察 TUI 是否出现 `● Read(...)` 工具行和结果摘要。
4. 观察模型是否基于工具结果生成最终回复。
5. 提问要求一次改文件，验证唯一匹配替换成功。
6. 提问触发匹配不到或多次匹配错误，验证结构化错误和摘要。
7. 对照 `checklist.md` 逐项记录证据。

**验证：** tmux 中可观察工具调用行、工具结果摘要、最终回复和错误路径；验收报告记录结果。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13 -> T14
```

## 任务自检
- 工具基础接口由 T1、T2 覆盖。
- 六个核心工具由 T3、T4、T5 覆盖。
- 注册中心和错误包装由 T6 覆盖。
- Claude Code 风格工具行由 T7 覆盖。
- OpenAI/Anthropic 流式工具调用解析由 T8、T9 覆盖。
- 工具调用和结果回灌历史由 T10 覆盖。
- CLI 接入由 T11 覆盖。
- 文档、完整测试和端到端验收由 T12-T14 覆盖。
