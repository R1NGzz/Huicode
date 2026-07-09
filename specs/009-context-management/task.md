# HuiCode Context Management Tasks

## File List

| Action | File | Responsibility |
| --- | --- | --- |
| Create | `huicode/context/__init__.py` | 导出上下文管理公共类型和入口。 |
| Create | `huicode/context/types.py` | 定义压缩报告、准备结果、摘要结果等共享类型。 |
| Create | `huicode/context/state.py` | 定义会话级上下文状态和重置逻辑。 |
| Create | `huicode/context/estimator.py` | 实现近似 token 估算与 usage 锚点更新。 |
| Create | `huicode/context/store.py` | 实现工具结果落盘和相对路径记录。 |
| Create | `huicode/context/lightweight.py` | 实现单个和分组工具结果轻量压缩。 |
| Create | `huicode/context/segments.py` | 按协议安全边界切分历史消息。 |
| Create | `huicode/context/history.py` | 选择摘要区/近期保留区并应用摘要边界消息。 |
| Create | `huicode/context/summarizer.py` | 调用 provider 生成结构化摘要并丢弃草稿。 |
| Create | `huicode/context/manager.py` | 串联轻量压缩、整体摘要、失败熔断和手动压缩。 |
| Modify | `huicode/config.py` | 增加 `ContextConfig` 和 `context` YAML 配置解析。 |
| Modify | `huicode/agent_events.py` | 增加 `context` 事件和 `AgentState.context`。 |
| Modify | `huicode/agent.py` | 在请求前接入上下文预处理，在工具结果后接入压缩，记录 usage 锚点。 |
| Modify | `huicode/cli.py` | 增加 `/compact`、`/context`，更新 `/clear`、`/config`。 |
| Modify | `huicode/tui.py` | 渲染上下文压缩事件。 |
| Modify | `README.md` | 说明上下文管理策略、命令、配置和限制。 |
| Create | `tests/test_context_estimator.py` | 覆盖估算与 usage 锚点。 |
| Create | `tests/test_context_lightweight.py` | 覆盖工具结果落盘、预览、分组压缩。 |
| Create | `tests/test_context_history.py` | 覆盖协议安全切分、近期保留和摘要边界。 |
| Create | `tests/test_context_summarizer.py` | 覆盖摘要 prompt、禁用工具、草稿丢弃和失败场景。 |
| Create | `tests/test_context_manager.py` | 覆盖自动压缩、手动压缩、失败熔断和状态重置。 |
| Create | `tests/test_agent_context.py` | 覆盖 Agent Loop 请求前压缩、usage 锚点和 MCP 工具结果压缩。 |
| Create | `tests/test_cli_context.py` | 覆盖 `/compact`、`/context`、`/clear` 和 `/config`。 |
| Modify | `tests/test_tui.py` | 覆盖上下文事件渲染。 |
| Modify | `tests/test_openai_provider_tools.py` | 覆盖压缩后 OpenAI 消息序列合法。 |
| Modify | `tests/test_anthropic_provider_tools.py` | 覆盖压缩后 Anthropic tool_use/tool_result 顺序合法。 |
| Create | `specs/009-context-management/checklist.md` | 验收清单。 |
| Create | `specs/009-context-management/acceptance_report.md` | 实现完成后的验收报告。 |

## T1: Add Context Config

**Files:** `huicode/config.py`, `tests/test_config.py`

**Dependencies:** None

**Steps:**

1. 新增 `ContextConfig` dataclass，字段与 `plan.md` 保持一致。
2. 在 `LLMConfig` 中加入 `context: ContextConfig`。
3. 在 `load_config()` 中解析可选 `context` 映射。
4. 对所有 token/字符阈值字段使用正整数校验。
5. 对 `context.enabled` 使用布尔校验。
6. 扩展配置测试，覆盖默认值、显式配置、非法数字、非法布尔值。

**Verification:** Run `python -m unittest tests.test_config -v`; expect all config tests pass.

## T2: Add Context Types And State

**Files:** `huicode/context/__init__.py`, `huicode/context/types.py`, `huicode/context/state.py`, `huicode/agent_events.py`, `tests/test_context_manager.py`

**Dependencies:** T1

**Steps:**

1. 创建 `ContextState`，包含 usage 锚点、摘要失败计数、熔断标记、摘要次数和最近释放量。
2. 创建 `ContextCompressionReport`、`ContextPreparation`、`SummaryResult` 等共享类型。
3. 给 `AgentState` 增加 `context: ContextState`。
4. 给 `AgentEventKind` 增加 `"context"`。
5. 在 `huicode/context/__init__.py` 导出公共类型。
6. 写状态重置测试，确认新 `AgentState` 默认上下文状态正确。

**Verification:** Run `python -m unittest tests.test_context_manager tests.test_agent_events -v`; expect context state defaults pass.

## T3: Implement Token Estimator

**Files:** `huicode/context/estimator.py`, `tests/test_context_estimator.py`

**Dependencies:** T2

**Steps:**

1. 实现 `TokenEstimate`。
2. 实现 `estimate_text()`，默认 `ceil(chars / 4)`。
3. 实现 `estimate_message()`，把 content、thinking、tool calls、tool result JSON 都计入估算。
4. 实现 `estimate_messages()`。
5. 实现 `estimate_request()`，把 prompt system texts 和 tool specs 也计入估算。
6. 实现 `record_usage()`，优先读取 `input_tokens`，其次读取 `prompt_tokens`。
7. 测试 usage 锚点存在时，后续估算使用锚点加字符增量修正。

**Verification:** Run `python -m unittest tests.test_context_estimator -v`; expect estimator tests pass.

## T4: Implement Tool Result Store

**Files:** `huicode/context/store.py`, `tests/test_context_lightweight.py`

**Dependencies:** T3

**Steps:**

1. 实现 `ToolResultStore`，构造时接收 workspace。
2. 复用安全文件名规则，生成 `.huicode/tool-results/turn-XXX-<call-id>.json`。
3. 落盘完整 `ToolResult.to_model_dict()` JSON。
4. 返回 `SpillRecord`，包含相对路径、字符数、预览和估算释放 token。
5. 测试落盘路径必须在 workspace 内。
6. 测试文件内容包含完整工具结果而不是预览。

**Verification:** Run `python -m unittest tests.test_context_lightweight -v`; expect store tests pass.

## T5: Implement Lightweight Compaction

**Files:** `huicode/context/lightweight.py`, `tests/test_context_lightweight.py`

**Dependencies:** T4

**Steps:**

1. 实现 `compact_single_tool_result()`。
2. 当单个工具结果超过 `single_tool_result_tokens` 时调用 `ToolResultStore.spill()`。
3. 生成压缩后的 `ToolResult`，保留 summary、常用元信息、`preview` 和 `__spilled__`。
4. 已有 `__spilled__` 的工具结果跳过，避免重复落盘。
5. 实现 `compact_tool_groups()`，识别 assistant tool_calls 后紧随的 tool messages。
6. 当分组工具结果合计超过 `tool_result_group_tokens` 时，按估算大小从大到小压缩。
7. 测试单个超大结果、多个结果合计超阈值、较小结果保留内联、用户消息不变。

**Verification:** Run `python -m unittest tests.test_context_lightweight -v`; expect lightweight compaction tests pass.

## T6: Implement Protocol-Safe Segmentation

**Files:** `huicode/context/segments.py`, `tests/test_context_history.py`

**Dependencies:** T3

**Steps:**

1. 实现 `HistorySegment`。
2. 普通 user/assistant 文本消息单独成段。
3. assistant 带 tool_calls 时，把它和后续连续 tool messages 合成一个段。
4. orphan tool message 作为不可拆安全段保留。
5. 测试 Anthropic 多工具调用段不会被拆开。
6. 测试 OpenAI tool_call_id 对应关系在段内保留。

**Verification:** Run `python -m unittest tests.test_context_history -v`; expect segmentation tests pass.

## T7: Implement History Summary Rewrite

**Files:** `huicode/context/history.py`, `tests/test_context_history.py`

**Dependencies:** T6

**Steps:**

1. 实现 `split_recent_messages()`。
2. 从尾部按 segment 累计，至少保留 `min_recent_messages` 条消息。
3. 满足最小条数后继续保留到约 `recent_keep_tokens`。
4. cutoff 只允许落在 segment 边界。
5. 实现 `apply_summary()`，生成 summary special tag、compression boundary special tag 和近期原文。
6. 边界消息明确写入“需要文件细节时重新读取/重新调用工具，不能凭摘要脑补”。
7. 测试摘要只替换早期历史，近期消息原文保留。
8. 测试用户原始消息在保留区不被改写。

**Verification:** Run `python -m unittest tests.test_context_history -v`; expect history rewrite tests pass.

## T8: Implement History Summarizer

**Files:** `huicode/context/summarizer.py`, `tests/test_context_summarizer.py`

**Dependencies:** T7

**Steps:**

1. 实现 summary prompt 构造，包含固定摘要部分要求。
2. Prompt 要求模型输出 `<draft>` 和 `<summary>`，并说明只保留正式摘要。
3. 调用 `provider.stream_chat()` 时传 `tools=[]`、`allow_tool_calls=False`。
4. 收集流式 text。
5. 如果出现 tool_call，返回失败结果。
6. 如果没有 `<summary>` 标签，返回失败结果。
7. 只提取 `<summary>` 内容，丢弃 `<draft>`。
8. 测试成功摘要、草稿丢弃、工具调用失败、缺失 summary 失败。

**Verification:** Run `python -m unittest tests.test_context_summarizer -v`; expect summarizer tests pass.

## T9: Implement Context Manager

**Files:** `huicode/context/manager.py`, `tests/test_context_manager.py`

**Dependencies:** T5, T7, T8

**Steps:**

1. 实现 `ContextManager.compact_tool_result()`。
2. 实现 `prepare_before_request()`，按轻量分组压缩、估算请求、判断阈值、整体摘要的顺序执行。
3. 自动模式使用 `auto_margin_tokens`。
4. 实现 `manual_compact()`，使用 `manual_margin_tokens`，历史可压缩时主动尝试摘要。
5. 摘要成功后更新 `summary_count`、`last_summary_tokens_freed`、失败计数归零。
6. 摘要失败后增加失败计数，达到 `max_summary_failures` 后打开熔断。
7. 熔断后自动模式跳过整体摘要，但轻量压缩仍运行。
8. 实现 `record_usage()` 和 `reset()`。
9. 测试自动摘要触发、手动摘要触发、历史太短跳过、失败三次熔断、熔断后轻量仍生效。

**Verification:** Run `python -m unittest tests.test_context_manager -v`; expect manager tests pass.

## T10: Integrate Context Manager Into Agent Loop

**Files:** `huicode/agent.py`, `tests/test_agent_context.py`, `tests/test_agent.py`, `tests/test_agent_loop.py`

**Dependencies:** T9

**Steps:**

1. 移除或替换 `agent.py` 中旧的 `_spill_large_tool_result()` 逻辑。
2. 在每次 `provider.stream_chat()` 前构建 prompt/tools 后调用 `ContextManager.prepare_before_request()`。
3. 如果历史被改写，重新构建 prompt/tools 或确保估算与请求使用同一份历史。
4. 将 `ContextCompressionReport` 转成 `AgentEvent(kind="context")`。
5. 在工具执行结果 append 前调用 `ContextManager.compact_tool_result()`。
6. 继续保留现有工具结果 TUI 事件顺序。
7. 在 collect usage 后调用 `ContextManager.record_usage()`。
8. 确保摘要失败不删除刚追加的用户消息。
9. 测试请求前整体摘要、工具结果单个落盘、usage 锚点记录、MCP 工具大结果落盘。

**Verification:** Run `python -m unittest tests.test_agent_context tests.test_agent tests.test_agent_loop -v`; expect agent tests pass.

## T11: Add CLI Commands And State Output

**Files:** `huicode/cli.py`, `tests/test_cli_context.py`, `tests/test_cli.py`

**Dependencies:** T10

**Steps:**

1. 在命令补全列表中加入 `/compact`、`/context`。
2. 实现 `/context`，输出 window、估算锚点、summary_count、failure_count、fuse 状态。
3. 实现 `/compact`，手动触发 ContextManager，并渲染报告。
4. `/clear` 调用 ContextManager reset 或重置 `AgentState.context`。
5. `/config` 增加 context summary，不显示 secret、不显示落盘完整内容。
6. 测试 `/compact` 成功、跳过和失败输出。
7. 测试 `/context` 和 `/config` 不泄露 api key、headers、MCP env。
8. 测试 `/clear` 重置上下文状态。

**Verification:** Run `python -m unittest tests.test_cli_context tests.test_cli -v`; expect CLI tests pass.

## T12: Render Context Events In TUI

**Files:** `huicode/tui.py`, `tests/test_tui.py`

**Dependencies:** T10

**Steps:**

1. 在 `render_agent_event()` 中处理 `event.kind == "context"`。
2. 渲染轻量压缩：落盘数量、估算释放量、路径摘要。
3. 渲染整体摘要：压缩前后 token 估算。
4. 渲染 skip、failure、fuse。
5. 保证 context 事件不会破坏正在流式输出的 Markdown 缓冲。
6. 测试各类 context 事件输出。

**Verification:** Run `python -m unittest tests.test_tui -v`; expect TUI tests pass.

## T13: Verify Provider Serialization Compatibility

**Files:** `tests/test_openai_provider_tools.py`, `tests/test_anthropic_provider_tools.py`

**Dependencies:** T7, T10

**Steps:**

1. 为 OpenAI provider 增加压缩后 summary/boundary user message 序列化测试。
2. 为 OpenAI provider 增加工具调用段未被拆坏的测试。
3. 为 Anthropic provider 增加 summary/boundary user message 序列化测试。
4. 为 Anthropic provider 增加 assistant tool_use 后紧跟 tool_result 的压缩后序列测试。
5. 确认压缩不会留下 orphan tool result。

**Verification:** Run `python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v`; expect provider serialization tests pass.

## T14: Update README

**Files:** `README.md`

**Dependencies:** T11, T12

**Steps:**

1. 增加“上下文管理”章节。
2. 说明两层策略：工具结果轻量落盘、整体历史摘要。
3. 说明 `/compact`、`/context` 命令。
4. 说明 `.huicode/tool-results` 落盘位置。
5. 说明配置字段和默认值。
6. 说明限制：近似估算、摘要不是文件事实来源、需要细节应重新读取。
7. 确认 README 不包含本地 secret 或 `.huicode-mcp.yaml` 内容。

**Verification:** Review README manually and run `python -m unittest tests.test_cli_context -v`; expect docs and command behavior align.

## T15: Run Targeted Test Groups

**Files:** tests only

**Dependencies:** T1-T14

**Steps:**

1. Run context module tests.
2. Run Agent/CLI/TUI context integration tests.
3. Run Provider serialization tests.
4. Fix any failures before moving to full verification.

**Verification:**

```powershell
python -m unittest tests.test_context_estimator tests.test_context_lightweight tests.test_context_history tests.test_context_summarizer tests.test_context_manager -v
python -m unittest tests.test_agent_context tests.test_cli_context tests.test_tui -v
python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v
```

Expect all targeted tests pass.

## T16: Run Full Verification

**Files:** whole project

**Dependencies:** T15

**Steps:**

1. Run full unittest discovery.
2. Run compileall.
3. Check tmux availability.
4. If tmux exists, run an E2E session with a realistic long-tool-result request and `/compact`.
5. If tmux is unavailable, record the exact unavailable evidence in acceptance report.

**Verification:**

```powershell
python -m unittest discover -v
python -m compileall -q huicode tests
Get-Command tmux -ErrorAction SilentlyContinue
```

Expect tests and compileall pass; tmux result recorded.

## T17: Write Acceptance Report

**Files:** `specs/009-context-management/acceptance_report.md`

**Dependencies:** T16

**Steps:**

1. Record every checklist item result with evidence.
2. Include targeted and full test command summaries.
3. Include tmux E2E result or unavailable reason.
4. Include notes for any skipped real-API behavior.
5. Record final commit hash after commit.

**Verification:** Acceptance report exists and maps checklist items to evidence.

## T18: Commit Chapter

**Files:** all tracked files for this chapter

**Dependencies:** T17

**Steps:**

1. Run `git status --short`.
2. Stage only this chapter's implementation, tests, README, and `specs/009-context-management`.
3. Do not stage `.huicode-mcp.yaml` or root legacy untracked files.
4. Commit with message `add context management`.

**Verification:**

```powershell
git status --short
git commit -m "add context management"
```

Expect commit succeeds and unrelated untracked files remain unstaged.

## Execution Order

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13 -> T14 -> T15 -> T16 -> T17 -> T18
```

## Self-Check

- Every component in `plan.md` has at least one task.
- Every task has a concrete verification method.
- The implementation order avoids circular dependencies: config/state first, then estimator/store, then compaction/history/summarizer, then manager, then integrations.
- Provider protocol compatibility is tested after history rewrite and Agent integration.
- Root legacy Mew Spec files and `.huicode-mcp.yaml` are explicitly excluded from staging.
