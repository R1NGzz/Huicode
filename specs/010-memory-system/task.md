# HuiCode Memory System Tasks

## File List

| Action | File | Responsibility |
| --- | --- | --- |
| Modify | `huicode/config.py` | 增加 `MemoryConfig` 和 `memory` 配置解析/校验。 |
| Modify | `huicode/agent_events.py` | 增加 `memory` 事件和 `AgentState.memory`。 |
| Modify | `huicode/agent.py` | 接入记忆注入、会话追加、自然结束后的记忆更新。 |
| Modify | `huicode/cli.py` | 初始化 `MemoryManager`，新增 `/memory`、`/sessions`、`/resume` 等命令。 |
| Modify | `huicode/tui.py` | 渲染记忆状态和记忆事件。 |
| Modify | `huicode/prompts/base.py` | 扩展 `PromptContext` 的记忆字段。 |
| Modify | `huicode/prompts/builder.py` | 注入项目指令和记忆索引。 |
| Modify | `huicode/prompts/modules.py` | 调整可选模块和长期记忆输出格式。 |
| Create | `huicode/memory/__init__.py` | 导出记忆系统公共入口。 |
| Create | `huicode/memory/types.py` | 定义记忆运行状态、报告和数据类型。 |
| Create | `huicode/memory/paths.py` | 管理用户级/项目级记忆目录。 |
| Create | `huicode/memory/scrub.py` | 统一脱敏。 |
| Create | `huicode/memory/instructions.py` | 加载指令文件和 `@include`。 |
| Create | `huicode/memory/codec.py` | 消息、工具调用、工具结果 JSON 编解码。 |
| Create | `huicode/memory/recovery.py` | 会话恢复协议安全裁剪。 |
| Create | `huicode/memory/sessions.py` | JSONL 会话追加、扫描、恢复、清理。 |
| Create | `huicode/memory/notes.py` | Markdown 笔记读写。 |
| Create | `huicode/memory/index.py` | 记忆索引重建和大小控制。 |
| Create | `huicode/memory/updater.py` | LLM 自动笔记更新。 |
| Create | `huicode/memory/manager.py` | 记忆系统统一编排。 |
| Modify | `README.md` | 说明记忆系统文件位置、命令和限制。 |
| Create | `tests/test_memory_instructions.py` | 指令加载与 include 安全测试。 |
| Create | `tests/test_memory_sessions.py` | JSONL 存档、扫描、恢复和清理测试。 |
| Create | `tests/test_memory_recovery.py` | 工具调用协议安全裁剪测试。 |
| Create | `tests/test_memory_notes.py` | 笔记 frontmatter 读写测试。 |
| Create | `tests/test_memory_index.py` | 索引重建和大小限制测试。 |
| Create | `tests/test_memory_updater.py` | 自动笔记更新测试。 |
| Create | `tests/test_agent_memory.py` | Agent Loop 记忆集成测试。 |
| Create | `tests/test_cli_memory.py` | TUI 命令测试。 |
| Modify | `tests/test_config.py` | memory 配置解析测试。 |
| Modify | `tests/test_prompt_builder.py` | 记忆注入 prompt 测试。 |
| Modify | `tests/test_openai_provider_tools.py` | 恢复/注入后的 OpenAI 序列兼容测试。 |
| Modify | `tests/test_anthropic_provider_tools.py` | 恢复/注入后的 Anthropic 序列兼容测试。 |
| Create | `specs/010-memory-system/acceptance_report.md` | 验收证据记录。 |

## T1: 配置和运行状态骨架

**Files:** `huicode/config.py`, `huicode/agent_events.py`, `huicode/memory/types.py`, `huicode/memory/__init__.py`, `tests/test_config.py`

**Dependencies:** None

**Steps:**
1. 创建 `huicode/memory` 包和 `MemoryRuntimeState`、`MemoryStatus`、`MemoryUpdateReport`、`ResumeReport` 等基础类型。
2. 在 `LLMConfig` 中增加 `memory: MemoryConfig`。
3. 在 `load_config()` 中解析 `memory` 配置块。
4. 校验 `index_max_lines`、`index_max_bytes`、`session_retention_days`、`instruction_include_depth` 等正整数。
5. 给 `AgentEventKind` 增加 `memory`。
6. 给 `AgentState` 增加 `memory: MemoryRuntimeState`。

**Verification:** Run `python -m unittest tests.test_config -v`; expect memory defaults and invalid values covered.

## T2: 路径和脱敏工具

**Files:** `huicode/memory/paths.py`, `huicode/memory/scrub.py`, `tests/test_memory_notes.py`

**Dependencies:** T1

**Steps:**
1. 实现 `huicode_home()`，支持 `HUICODE_HOME` 覆盖。
2. 实现项目级 memory、sessions、notes、index 路径函数。
3. 实现用户级 memory、notes、index 路径函数。
4. 实现 `scrub_secrets(text)`，覆盖 API key、Authorization、Bearer、token、secret、password 等常见模式。
5. 写测试确认路径在 workspace 或 `HUICODE_HOME` 内，脱敏不会输出原 secret。

**Verification:** Run `python -m unittest tests.test_memory_notes -v`; expect path and scrub tests pass.

## T3: 项目指令加载

**Files:** `huicode/memory/instructions.py`, `tests/test_memory_instructions.py`

**Dependencies:** T1, T2

**Steps:**
1. 实现指令文件候选路径和优先级排序。
2. 实现 `InstructionLoader.load()`。
3. 支持 `@include relative/path.md`。
4. 用 `visited` 防环路。
5. 用 `instruction_include_depth` 限制嵌套深度。
6. 对 project scope 和 user scope 分别做 resolve 后边界检查。
7. 输出 XML 标签包裹的指令文本、loaded paths 和 warnings。

**Verification:** Run `python -m unittest tests.test_memory_instructions -v`; expect priority, include, loop, depth, escape all covered.

## T4: Prompt 注入集成

**Files:** `huicode/prompts/base.py`, `huicode/prompts/builder.py`, `huicode/prompts/modules.py`, `huicode/agent.py`, `tests/test_prompt_builder.py`

**Dependencies:** T1, T3

**Steps:**
1. 在 `PromptContext` 增加 `memory_index` 和 `memory_warnings`。
2. 保持 `custom_instructions` 用于项目指令。
3. 在 `build_prompt_bundle()` 中新增非缓存 `memory_index` supplemental 模块。
4. 给 memory index 加 `<huicode_context type="memory_index" scope="long_term">` 标签。
5. 在 `build_agent_prompt()` 中从 `state.memory` 填入指令和索引。
6. 确认固定系统模块顺序不变。

**Verification:** Run `python -m unittest tests.test_prompt_builder -v`; expect project instructions and memory index both appear in expected prompt sections.

## T5: 消息 JSON 编解码

**Files:** `huicode/memory/codec.py`, `tests/test_memory_sessions.py`

**Dependencies:** T1

**Steps:**
1. 实现 `ToolCall` JSON 编解码。
2. 实现 `ToolResult` 和 `ToolError` JSON 编解码。
3. 实现 `ConversationMessage` JSON 编解码。
4. 保留 `thinking`、`thinking_signature`、`tool_call_id`、`tool_name` 和 `tool_result`。
5. 对非法 role、缺失字段和坏结构返回可捕获错误。

**Verification:** Run `python -m unittest tests.test_memory_sessions -v`; expect round-trip preserves assistant/tool messages.

## T6: JSONL 会话存档

**Files:** `huicode/memory/sessions.py`, `tests/test_memory_sessions.py`

**Dependencies:** T2, T5

**Steps:**
1. 实现 `SessionStore.new_session_id()`。
2. 实现 `SessionRecorder.append_message()` 和 `append_event()`。
3. 每行写入 JSON 后 flush。
4. 实现 `list_sessions()`，扫描 JSONL 计算 title、message_count、updated_at。
5. 实现坏行跳过和 warnings 统计。
6. 不创建或读取 meta 文件。

**Verification:** Run `python -m unittest tests.test_memory_sessions -v`; expect append, list, bad-line scan pass.

## T7: 会话恢复协议安全裁剪

**Files:** `huicode/memory/recovery.py`, `huicode/memory/sessions.py`, `tests/test_memory_recovery.py`, `tests/test_memory_sessions.py`

**Dependencies:** T5, T6

**Steps:**
1. 实现 `recover_safe_messages()`。
2. 校验 assistant tool_calls 后紧跟匹配 tool result。
3. 遇到未配对、错配或 orphan tool 时截断到问题段前。
4. 保留 thinking 和签名。
5. 在 `SessionStore.recover()` 中调用裁剪逻辑。
6. 生成 `RecoveredSession` 的 `truncated`、`skipped_bad_lines` 和 warnings。

**Verification:** Run `python -m unittest tests.test_memory_recovery tests.test_memory_sessions -v`; expect malformed tool history is truncated safely.

## T8: 时间跨度提醒和会话清理

**Files:** `huicode/memory/sessions.py`, `tests/test_memory_sessions.py`

**Dependencies:** T6, T7

**Steps:**
1. 恢复会话时比较 `updated_at` 和当前时间。
2. 超过 `stale_session_notice_hours` 时生成 time gap context message。
3. 实现 `cleanup_expired(active_session_id, now)`。
4. 清理超过 `session_retention_days` 的非活动 JSONL。
5. 当前活动 session 永不清理。

**Verification:** Run `python -m unittest tests.test_memory_sessions -v`; expect stale notice and expiration cleanup pass.

## T9: Markdown 笔记存储

**Files:** `huicode/memory/notes.py`, `tests/test_memory_notes.py`

**Dependencies:** T2

**Steps:**
1. 定义 frontmatter 解析和写入。
2. 实现 `NoteStore.list_notes()`。
3. 实现 `create_note()`，文件名只使用 note id。
4. 实现 `update_note()` 和 `delete_note()`。
5. scope 分别落到 user/project 目录。
6. 写入前调用脱敏。

**Verification:** Run `python -m unittest tests.test_memory_notes -v`; expect create/list/update/delete and scope separation pass.

## T10: 记忆索引

**Files:** `huicode/memory/index.py`, `tests/test_memory_index.py`

**Dependencies:** T9

**Steps:**
1. 实现 `MemoryIndex.rebuild()`。
2. 按 scope/category 分组输出。
3. 单条摘要控制长度。
4. source 使用相对定位提示，不暴露绝对用户目录 secret。
5. 超过 `index_max_lines` 或 `index_max_bytes` 时裁剪旧笔记。
6. 实现 `load_text()`。

**Verification:** Run `python -m unittest tests.test_memory_index -v`; expect index content, source hints, size limits pass.

## T11: 自动笔记更新器

**Files:** `huicode/memory/updater.py`, `tests/test_memory_updater.py`

**Dependencies:** T9, T10

**Steps:**
1. 构造 no-tool memory update prompt。
2. 调用 provider 时传 `tools=[]` 和 `allow_tool_calls=False`。
3. 收集流式 text，不允许 tool_call。
4. 解析 JSON operations。
5. 校验 action、scope、category 和必要字段。
6. 应用 create/update/delete/noop。
7. 写入后重建 index。
8. 失败时返回 `MemoryUpdateReport(ok=False)`，不抛出到 Agent 主流程。

**Verification:** Run `python -m unittest tests.test_memory_updater -v`; expect create/update/noop, invalid JSON, tool_call failure pass.

## T12: 记忆管理器

**Files:** `huicode/memory/manager.py`, `tests/test_agent_memory.py`, `tests/test_cli_memory.py`

**Dependencies:** T3, T6, T8, T10, T11

**Steps:**
1. 实现 `MemoryManager.start()`。
2. 启动时创建目录、打开 session、清理过期 session、加载指令、加载索引。
3. 实现 `refresh_prompt_memory()`。
4. 实现 `record_message()`，捕获写入失败并记录 warning。
5. 实现 `schedule_update_after_final()`，默认使用单线程后台 executor。
6. 实现 `list_sessions()`、`resume_session()`、`clear_current_session()`、`status()`、`close()`。
7. `resume_session()` 中接入 `ContextManager.manual_compact()`。

**Verification:** Run `python -m unittest tests.test_agent_memory tests.test_cli_memory -v`; expect manager startup, record, resume, clear status pass.

## T13: Agent Loop 接入

**Files:** `huicode/agent.py`, `tests/test_agent_memory.py`, `tests/test_agent_loop.py`

**Dependencies:** T4, T12

**Steps:**
1. 给 `run_agent_loop()` 增加可选 `memory` 参数。
2. 记录 `turn_start`。
3. 追加 user/assistant/tool 消息后调用 `memory.record_message()`。
4. 每次 build prompt 前调用 `memory.refresh_prompt_memory()`。
5. 自然 final 且最后 assistant 无 tool_calls 时调用 `schedule_update_after_final()`。
6. 错误、取消、max_iterations、unknown_tool_limit 不触发自动笔记。
7. 保持 `memory=None` 时现有测试行为不变。

**Verification:** Run `python -m unittest tests.test_agent_memory tests.test_agent_loop -v`; expect messages are recorded and only final turn schedules memory update.

## T14: CLI 和 TUI 命令

**Files:** `huicode/cli.py`, `huicode/tui.py`, `tests/test_cli_memory.py`, `tests/test_tui.py`

**Dependencies:** T12, T13

**Steps:**
1. CLI 启动时创建并 start `MemoryManager`。
2. 把 memory manager 传入 `_run_request()` 和 `run_agent_loop()`。
3. `/clear` 调用 `memory.clear_current_session()`。
4. 实现 `/memory`、`/memory update`、`/memory rebuild`。
5. 实现 `/sessions`、`/resume <session-id>`、`/sessions clean`。
6. `/config` 追加 memory 摘要。
7. TUI 渲染 `memory` event。
8. 所有输出脱敏。

**Verification:** Run `python -m unittest tests.test_cli_memory tests.test_tui -v`; expect command output and event rendering pass.

## T15: Provider 序列兼容回归

**Files:** `tests/test_openai_provider_tools.py`, `tests/test_anthropic_provider_tools.py`

**Dependencies:** T4, T7, T13

**Steps:**
1. 增加恢复历史后序列化测试。
2. 增加 memory index 和 project instruction 注入后序列化测试。
3. 覆盖 assistant tool_calls 紧跟 tool results 的合法序列。
4. 覆盖 time gap context 和 compression boundary 同时存在的序列。

**Verification:** Run `python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v`; expect both provider payloads valid.

## T16: README 和用户文档

**Files:** `README.md`

**Dependencies:** T14

**Steps:**
1. 增加记忆系统章节。
2. 说明项目指令文件位置、include 规则和安全边界。
3. 说明会话 JSONL 位置、恢复、清理和 `/clear` 语义。
4. 说明自动笔记位置、四类笔记、索引大小限制和脱敏边界。
5. 说明 `/memory`、`/sessions`、`/resume` 等命令。

**Verification:** Run `python -m compileall -q huicode tests`; expect no syntax error after docs-only change.

## T17: 全量测试和验收报告

**Files:** `specs/010-memory-system/acceptance_report.md`

**Dependencies:** T1-T16

**Steps:**
1. 运行 `python -m unittest discover -v`。
2. 运行 `python -m compileall -q huicode tests`。
3. 手动用非网络 fake provider 或测试命令验证会话列表、恢复、记忆状态。
4. 如当前 Windows 环境没有 tmux，记录无法执行 tmux E2E 的原因。
5. 按 `checklist.md` 填写验收证据。

**Verification:** Acceptance report records commands, results, skipped E2E reason if any.

## T18: Git 提交

**Files:** all changed tracked files for this chapter

**Dependencies:** T17

**Steps:**
1. 检查 `git status --short`。
2. 只 stage 本章相关文件，避开用户本地配置和未跟踪临时文件。
3. 提交 commit。

**Verification:** `git show --stat --oneline HEAD` shows only intended files.

## Execution Order

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13 -> T14 -> T15 -> T16 -> T17 -> T18
```

## Task Coverage

| Plan Component | Covered By |
| --- | --- |
| MemoryConfig / MemoryRuntimeState | T1 |
| paths / scrub | T2 |
| InstructionLoader | T3, T4 |
| Prompt integration | T4, T15 |
| codec / SessionStore | T5, T6 |
| safe recovery / stale notice / cleanup | T7, T8 |
| NoteStore / MemoryIndex | T9, T10 |
| MemoryUpdater | T11 |
| MemoryManager | T12 |
| Agent Loop integration | T13 |
| CLI/TUI integration | T14 |
| Provider compatibility | T15 |
| README / acceptance | T16, T17 |
| Git workflow | T18 |
