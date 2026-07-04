# HuiCode Agent Loop 与 Plan Mode 实施任务

## 文件清单

| 动作 | 文件 | 职责 |
| --- | --- | --- |
| 创建 | `huicode/agent_events.py` | 定义 Agent 事件、状态、选项、收集结果和停止原因。 |
| 修改 | `huicode/agent.py` | 将一次工具回合改造为 ReAct Agent Loop、事件流、工具分批和停止条件。 |
| 修改 | `huicode/tools/base.py` | 给工具增加副作用分类默认值。 |
| 修改 | `huicode/tools/files.py` | 标记写文件、改文件为副作用工具。 |
| 修改 | `huicode/tools/search.py` | 标记查找和搜索为读类工具。 |
| 修改 | `huicode/tools/shell.py` | 标记命令执行为副作用工具。 |
| 修改 | `huicode/tools/registry.py` | 支持工具过滤、别名解析和副作用查询。 |
| 修改 | `huicode/tui.py` | 增加 AgentEvent 渲染函数。 |
| 修改 | `huicode/cli.py` | 接入 Agent Loop、`/plan`、`/do`、状态管理和事件渲染。 |
| 修改 | `huicode/providers/base.py` | 如需要，补 usage 事件字段或多工具调用兼容字段。 |
| 修改 | `huicode/providers/openai.py` | 如供应商返回 usage，透传 usage；保持多 tool_call 事件。 |
| 修改 | `huicode/providers/anthropic.py` | 如供应商返回 usage，透传 usage；保持 thinking/signature 回传。 |
| 创建 | `tests/test_agent_events.py` | 覆盖事件和状态默认值。 |
| 创建 | `tests/test_tool_batching.py` | 覆盖读类并发批、副作用串行批和混合分批。 |
| 创建 | `tests/test_agent_loop.py` | 覆盖多轮循环、停止条件、历史回灌、文本双路。 |
| 创建 | `tests/test_cli_plan_mode.py` | 覆盖 `/plan`、`/do`、`/clear` 行为。 |
| 修改 | `tests/test_agent.py` | 迁移或保留一次回合测试到新 Agent Loop 行为。 |
| 修改 | `tests/test_cli.py` | 适配事件渲染和新状态。 |
| 修改 | `README.md` | 增加 Agent Loop 和 Plan Mode 使用说明。 |
| 创建 | `specs/003-agent-loop-plan-mode/acceptance_report.md` | 记录本阶段验收结果。 |

## T1: 定义 Agent 事件与状态

**文件：** `huicode/agent_events.py`、`tests/test_agent_events.py`

**依赖：** 已批准的 `spec.md`、`plan.md`

**步骤：**
1. 定义 `AgentEvent`、`CollectedResponse`、`AgentOptions`、`AgentState`、`ToolBatch`。
2. 设置默认 `max_iterations=8`、`max_unknown_tools=2`。
3. 设置默认只读工具名集合 `Read/Find/Search/Glob`。
4. 添加事件和状态默认值测试。

**验证：** 运行 `python -m unittest tests.test_agent_events -v`；预期全部通过。

## T2: 给工具增加安全分类

**文件：** `huicode/tools/base.py`、`huicode/tools/files.py`、`huicode/tools/search.py`、`huicode/tools/shell.py`、`huicode/tools/registry.py`、`tests/test_tool_batching.py`

**依赖：** T1

**步骤：**
1. 在 Tool 协议中增加 `side_effect: bool` 默认约定。
2. 标记 `Read/Find/Search` 为读类工具。
3. 标记 `Write/Edit/Bash` 为副作用工具。
4. 在 registry 中增加 `resolve_name`、`is_side_effect`、`to_specs(allowed_names)`。
5. 确认 `Glob` 别名仍解析到 `Find`。
6. 添加测试覆盖工具分类、别名和过滤 specs。

**验证：** 运行 `python -m unittest tests.test_tool_batching tests.test_tools_registry -v`；预期全部通过。

## T3: 实现流式收集器

**文件：** `huicode/agent.py`、`tests/test_agent_loop.py`

**依赖：** T1

**步骤：**
1. 实现 `collect_model_response`，消费 Provider `StreamEvent`。
2. 对 text/thinking 立即产出 `AgentEvent`。
3. 同时累积完整文本、thinking、thinking_signature、tool_calls、usage。
4. 保持 DeepSeek Anthropic thinking/signature 保存行为。
5. 添加测试覆盖文本实时事件和完整响应收集。

**验证：** 运行 `python -m unittest tests.test_agent_loop -v`；预期收集器相关测试通过。

## T4: 实现工具分批与执行

**文件：** `huicode/agent.py`、`tests/test_tool_batching.py`

**依赖：** T2

**步骤：**
1. 实现 `batch_tool_calls`。
2. 读类工具进入并发批。
3. 副作用工具进入串行批。
4. 混合调用时先处理读类并发批，再按原顺序处理副作用批。
5. 实现 `execute_tool_batches`，产出 tool_call 和 tool_result 事件，并写入历史。
6. 添加测试覆盖批处理顺序和事件输出。

**验证：** 运行 `python -m unittest tests.test_tool_batching -v`；预期全部通过。

## T5: 实现 ReAct Agent Loop 主流程

**文件：** `huicode/agent.py`、`tests/test_agent_loop.py`

**依赖：** T3、T4

**步骤：**
1. 实现 `run_agent_loop`。
2. 每轮发起 Provider 请求，允许工具调用。
3. 没有工具调用时保存 assistant 文本并产出 done。
4. 有工具调用时保存 assistant tool_calls、执行工具、回灌结果并继续下一轮。
5. 保留现有 `run_agent_turn` 作为兼容包装或迁移到调用 `run_agent_loop`。
6. 添加测试覆盖多轮工具调用后最终回答。

**验证：** 运行 `python -m unittest tests.test_agent_loop tests.test_agent -v`；预期全部通过。

## T6: 实现停止条件

**文件：** `huicode/agent.py`、`tests/test_agent_loop.py`

**依赖：** T5

**步骤：**
1. 实现迭代上限停止。
2. 实现 `cancel_requested` 停止。
3. 实现连续未知工具上限停止。
4. 实现 Provider/API 错误停止。
5. 每种停止都产出可读 `done` 或 `error` 事件。
6. 添加测试覆盖四类停止条件。

**验证：** 运行 `python -m unittest tests.test_agent_loop -v`；预期全部通过。

## T7: 实现 TUI 事件渲染

**文件：** `huicode/tui.py`、`tests/test_tui.py`

**依赖：** T1

**步骤：**
1. 实现 `render_agent_event(event, output)`。
2. 渲染 text 为流式文本。
3. 渲染 tool_call 为 `● Tool(args)`。
4. 渲染 tool_result 为 `⎿` 摘要。
5. 渲染 progress、error、done。
6. 保持现有格式化函数兼容。
7. 添加测试覆盖各事件类型。

**验证：** 运行 `python -m unittest tests.test_tui -v`；预期全部通过。

## T8: 接入 CLI Agent Loop

**文件：** `huicode/cli.py`、`tests/test_cli.py`

**依赖：** T5、T7

**步骤：**
1. CLI 创建并持有 `AgentState`。
2. 普通输入调用 `run_agent_loop` 并渲染事件。
3. 保留 `/exit`、`/quit`、`/config`。
4. `/clear` 清空 messages、last_plan、cancel 状态。
5. 更新 CLI 测试覆盖普通多轮 Agent Loop 渲染。

**验证：** 运行 `python -m unittest tests.test_cli -v`；预期全部通过。

## T9: 实现 Plan Mode 命令

**文件：** `huicode/cli.py`、`tests/test_cli_plan_mode.py`

**依赖：** T8

**步骤：**
1. 实现 `/plan <任务>`：只读工具运行并保存计划。
2. 实现 `/plan`：切换到 Plan Mode，下一条输入作为计划任务。
3. 实现 `/do <任务>`：全工具运行，注入最近计划。
4. 实现 `/do`：用最近计划继续执行。
5. Plan Mode 禁止副作用工具出现在可见工具 specs 中。
6. 添加测试覆盖 `/plan`、`/do`、`/clear`。

**验证：** 运行 `python -m unittest tests.test_cli_plan_mode -v`；预期全部通过。

## T10: Provider usage 事件兼容

**文件：** `huicode/providers/base.py`、`huicode/providers/openai.py`、`huicode/providers/anthropic.py`、相关 provider 测试

**依赖：** T1、T3

**步骤：**
1. 如需要扩展 `StreamEvent` 支持 usage 数据。
2. OpenAI/Anthropic 流中若出现 usage，转换为 usage 事件。
3. 无 usage 时保持现有行为。
4. 添加轻量测试覆盖 usage 可选解析。

**验证：** 运行 `python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v`；预期全部通过。

## T11: 更新 README

**文件：** `README.md`

**依赖：** T9

**步骤：**
1. 增加 Agent Loop 说明。
2. 增加 `/plan` 和 `/do` 使用示例。
3. 说明迭代上限和停止条件。
4. 说明本阶段仍不做权限系统、上下文压缩和交互式确认。

**验证：** 阅读 README，确认说明与实现一致。

## T12: 完整测试和编译检查

**文件：** 全部实现和测试文件

**依赖：** T1-T11

**步骤：**
1. 运行全部单元测试。
2. 运行 Python 编译检查。
3. 修复所有失败。

**验证：** 运行 `python -m unittest discover -v` 和 `python -m compileall -q huicode tests`；预期全部通过。

## T13: tmux 端到端验收

**文件：** `specs/003-agent-loop-plan-mode/checklist.md`、运行中的 HuiCode

**依赖：** T12、已批准的 checklist

**步骤：**
1. 在 tmux 中启动 `python -m huicode --config huicode.yaml`。
2. 输入需要多步读取/搜索的问题。
3. 观察多轮工具调用和最终回答。
4. 使用 `/plan` 让模型只读分析并产出计划。
5. 使用 `/do` 基于计划执行。
6. 触发迭代上限或未知工具停止场景。
7. 对照 checklist 记录证据。

**验证：** tmux 中可观察多轮工具、计划模式、执行模式和停止条件；生成验收报告。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13
```

## 任务自检
- Agent 事件流由 T1、T3、T7 覆盖。
- ReAct Agent Loop 由 T5、T6 覆盖。
- 文本双路由 T3 覆盖。
- 多工具分批和并发/串行执行由 T2、T4 覆盖。
- Plan Mode 和 `/do` 由 T8、T9 覆盖。
- Provider usage 兼容由 T10 覆盖。
- 文档、完整测试和端到端验收由 T11-T13 覆盖。
