# HuiCode Memory System Plan

## Architecture Overview

本章新增 `huicode.memory` 包，把记忆系统拆成四条相对独立的路径：

1. **项目指令加载路径**：启动和每轮请求前读取用户级、项目根、项目 `.huicode` 指令文件，处理 `@include`，生成系统级指令模块。
2. **会话存档路径**：Agent Loop 每次追加 user/assistant/tool 消息时同步追加一行 JSONL，保证会话可以从文件扫描恢复。
3. **会话恢复路径**：TUI 命令列出和恢复 JSONL 会话；恢复时跳过坏行、修复协议边界、必要时调用上下文压缩。
4. **长期笔记路径**：Agent Loop 自然结束后提交后台记忆更新任务，由 LLM 判断是否新增、合并或忽略笔记，再重建精简索引。

`MemoryManager` 是 Agent/CLI 的统一入口。CLI 启动时创建它，清理过期会话，打开当前会话存档，并把加载到的指令和记忆索引写入 `AgentState.memory`。Agent Loop 只依赖一个可选的 `MemoryManager`：有记忆系统时记录消息、发送记忆事件、自然结束后排队更新；没有记忆系统时现有测试和嵌入调用仍可运行。

系统提示注入复用现有 Prompt 层：项目指令进入 `custom_instructions` 模块；长期记忆索引用独立的非缓存补充模块注入，带 `<huicode_context type="memory_index">` 标签，避免模型把它当成用户新请求，也避免频繁变化的索引污染稳定缓存。

## Core Data Structures

### `MemoryConfig`

位置：`huicode/config.py`

字段：

```python
@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = True
    auto_update: bool = True
    instruction_include_depth: int = 5
    session_retention_days: int = 30
    stale_session_notice_hours: int = 24
    index_max_lines: int = 200
    index_max_bytes: int = 25 * 1024
    update_timeout_seconds: int = 45
```

挂到 `LLMConfig.memory`，配置块示例：

```yaml
memory:
  enabled: true
  auto_update: true
  session_retention_days: 30
  stale_session_notice_hours: 24
  index_max_lines: 200
  index_max_bytes: 25600
```

### `MemoryRuntimeState`

位置：`huicode/memory/types.py`，并作为 `AgentState.memory` 字段。

字段：

```python
@dataclass
class MemoryRuntimeState:
    session_id: str = ""
    instructions_text: str = ""
    memory_index_text: str = ""
    warnings: list[str] = field(default_factory=list)
    last_error: str = ""
    pending_updates: int = 0
    last_update_at: str = ""
```

用途：

- `build_agent_prompt()` 从这里读取项目指令和记忆索引。
- `/memory` 展示状态时读取索引大小、警告和最后错误。
- `/clear` 清空当前消息后会创建新会话 ID，但不会删除笔记和旧存档。

### `InstructionSource`

位置：`huicode/memory/instructions.py`

字段：

```python
@dataclass(frozen=True)
class InstructionSource:
    path: Path
    scope: Literal["project", "user"]
    priority: int
    boundary: Path
```

加载优先级从高到低：

1. `<workspace>/.huicode/instructions.md`
2. `<workspace>/.mewcode/instructions.md`，兼容旧命名
3. `<workspace>/HUICODE.md`
4. `<workspace>/MEWCODE.md`，兼容旧命名
5. `<home>/.huicode/instructions.md`
6. `<home>/.mewcode/instructions.md`，兼容旧命名

高优先级内容排在最终文本前面。相同 realpath 只加载一次。

### `InstructionLoadResult`

字段：

```python
@dataclass(frozen=True)
class InstructionLoadResult:
    text: str
    loaded_paths: tuple[str, ...]
    warnings: tuple[str, ...] = ()
```

`text` 会包装成：

```xml
<huicode_context type="project_instructions" scope="memory">
...
</huicode_context>
```

### `SessionRecord`

位置：`huicode/memory/sessions.py`

JSONL 每行结构：

```json
{
  "type": "message",
  "session_id": "20260709-213000-a1b2",
  "ts": "2026-07-09T21:30:00+08:00",
  "message": {
    "role": "assistant",
    "content": "...",
    "thinking": "",
    "thinking_signature": "",
    "tool_calls": [],
    "tool_call_id": null,
    "tool_name": null,
    "tool_result": null
  }
}
```

控制记录只用于会话状态，不参与 provider 历史：

```json
{"type": "event", "event": "clear", "session_id": "...", "ts": "..."}
```

会话 ID 使用：

```text
YYYYMMDD-HHMMSS-xxxx
```

存放位置：

```text
<workspace>/.huicode/sessions/<session-id>.jsonl
```

### `SessionSummary`

字段：

```python
@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    path: Path
    title: str
    message_count: int
    updated_at: datetime | None
    warnings: tuple[str, ...] = ()
```

标题来自第一条用户消息的前 40 个字符；消息数量、更新时间和警告全部通过扫描 JSONL 得出，不维护 meta 文件。

### `RecoveredSession`

字段：

```python
@dataclass(frozen=True)
class RecoveredSession:
    session_id: str
    messages: list[ConversationMessage]
    warnings: tuple[str, ...]
    truncated: bool = False
    skipped_bad_lines: int = 0
    time_gap_message: ConversationMessage | None = None
```

恢复后如果最后更新时间距离当前超过 `stale_session_notice_hours`，追加一条特殊上下文消息：

```xml
<huicode_context type="session_time_gap" scope="restored_session">
...
</huicode_context>
```

### `MemoryNote`

位置：`huicode/memory/notes.py`

字段：

```python
MemoryScope = Literal["user", "project"]
MemoryCategory = Literal["preference", "correction", "project_knowledge", "reference"]

@dataclass(frozen=True)
class MemoryNote:
    note_id: str
    scope: MemoryScope
    category: MemoryCategory
    title: str
    summary: str
    body: str
    source_session: str
    created_at: str
    updated_at: str
```

每条笔记是一个带 frontmatter 的 Markdown 文件：

```markdown
---
id: mem-20260709-213000-a1b2
scope: project
category: project_knowledge
title: HuiCode 使用 prompt_toolkit
source_session: 20260709-213000-a1b2
created_at: 2026-07-09T21:30:00+08:00
updated_at: 2026-07-09T21:30:00+08:00
---

正文...
```

路径：

```text
<workspace>/.huicode/memory/notes/*.md
<workspace>/.huicode/memory/index.md
<home>/.huicode/memory/notes/*.md
<home>/.huicode/memory/index.md
```

测试可通过 `HUICODE_HOME` 覆盖用户级目录。

### `MemoryUpdateOperation`

位置：`huicode/memory/updater.py`

模型输出 JSON：

```json
{
  "operations": [
    {
      "action": "create",
      "scope": "project",
      "category": "project_knowledge",
      "title": "...",
      "summary": "...",
      "body": "..."
    },
    {
      "action": "update",
      "id": "mem-...",
      "summary": "...",
      "body": "..."
    },
    {
      "action": "noop",
      "reason": "没有稳定的新记忆"
    }
  ]
}
```

允许动作：`create`、`update`、`delete`、`noop`。所有写入前经过 schema 校验和 secret scrub。

## Module Design

### `huicode.memory.paths`

**Responsibility:** 统一计算用户级和项目级记忆路径。

接口：

```python
def huicode_home() -> Path: ...
def project_memory_dir(workspace: Path) -> Path: ...
def user_memory_dir() -> Path: ...
def session_dir(workspace: Path) -> Path: ...
```

`huicode_home()` 优先读取 `HUICODE_HOME`，否则使用 `Path.home() / ".huicode"`。

### `huicode.memory.instructions`

**Responsibility:** 加载项目指令和 `@include`。

接口：

```python
class InstructionLoader:
    def __init__(self, workspace: Path, settings: MemoryConfig) -> None: ...
    def load(self) -> InstructionLoadResult: ...
```

规则：

- 支持一行一个 `@include relative/path.md`。
- include 路径相对当前文件目录解析。
- project scope 的 include 必须 resolve 后仍在 workspace 内。
- user scope 的 include 必须 resolve 后仍在对应用户配置目录内。
- 使用 `visited: set[Path]` 防环路。
- 超过 `instruction_include_depth` 时跳过并记录 warning。
- 不存在的 include 跳过并记录 warning。

### `huicode.memory.codec`

**Responsibility:** `ConversationMessage`、`ToolCall`、`ToolResult` 和 JSON 之间互转。

接口：

```python
def message_to_json(message: ConversationMessage) -> dict[str, object]: ...
def message_from_json(data: dict[str, object]) -> ConversationMessage: ...
```

恢复 `tool_result` 时重建 `ToolResult(ok, data, error, summary)`，保证 OpenAI/Anthropic provider 序列化时仍能调用 `to_model_dict()`。

### `huicode.memory.sessions`

**Responsibility:** JSONL 追加、扫描、恢复和清理。

接口：

```python
class SessionStore:
    def new_session_id(self) -> str: ...
    def open(self, session_id: str | None = None) -> SessionRecorder: ...
    def list_sessions(self) -> list[SessionSummary]: ...
    def recover(self, session_id: str, now: datetime) -> RecoveredSession: ...
    def cleanup_expired(self, active_session_id: str, now: datetime) -> int: ...
```

`SessionRecorder`：

```python
class SessionRecorder:
    session_id: str
    path: Path
    def append_message(self, message: ConversationMessage) -> None: ...
    def append_event(self, event: str, payload: dict[str, object] | None = None) -> None: ...
```

追加策略：

- 每行 `json.dumps(..., ensure_ascii=False)` 后立即写入换行。
- 每次追加后 `flush()`；不强制 `fsync()`，避免普通对话明显变慢。
- 写入失败记录到 `MemoryRuntimeState.last_error`，不终止 Agent Loop。

### `huicode.memory.recovery`

**Responsibility:** 会话恢复后的协议安全裁剪。

接口：

```python
def recover_safe_messages(messages: list[ConversationMessage]) -> tuple[list[ConversationMessage], bool, str]: ...
```

规则：

- 普通 user/assistant 文本可直接保留。
- assistant 带 `tool_calls` 时，后面必须紧跟对应数量且 ID 匹配的 tool 消息。
- 遇到未配对、错配或 orphan tool 消息，截断到问题段之前。
- Anthropic thinking 和 thinking signature 跟随 assistant 消息保留。
- 裁剪只发生在协议边界，避免产生 DeepSeek/Anthropic 的 tool_result 配对错误。

### `huicode.memory.notes`

**Responsibility:** 读写 Markdown 笔记和 frontmatter。

接口：

```python
class NoteStore:
    def list_notes(self, scope: MemoryScope | None = None) -> list[MemoryNote]: ...
    def create_note(self, note: MemoryNote) -> Path: ...
    def update_note(self, note_id: str, changes: dict[str, str]) -> Path | None: ...
    def delete_note(self, note_id: str) -> bool: ...
```

文件名使用 `note_id + ".md"`，不使用 title 直接作为路径，避免特殊字符和路径穿越。

### `huicode.memory.index`

**Responsibility:** 从笔记重建精简索引。

接口：

```python
class MemoryIndex:
    def rebuild(self) -> MemoryIndexResult: ...
    def load_text(self) -> str: ...
```

索引格式：

```markdown
# HuiCode Memory Index

## Project Knowledge
- [mem-...] 标题：摘要（source: .huicode/memory/notes/mem-....md）

## User Preferences
- [mem-...] 标题：摘要（source: ~/.huicode/memory/notes/mem-....md）
```

控制策略：

- 先按 scope/category 分组，再按 `updated_at` 倒序。
- 单条摘要限制长度。
- 超过 `index_max_lines` 或 `index_max_bytes` 时，从较旧笔记开始裁剪。
- 索引只保存摘要和定位路径，不保存完整正文。

### `huicode.memory.updater`

**Responsibility:** 使用 LLM 判断长期笔记更新。

接口：

```python
class MemoryUpdater:
    def update_from_turn(
        self,
        provider: Provider,
        session_id: str,
        mode: AgentMode,
        turn_messages: list[ConversationMessage],
        current_index: str,
    ) -> MemoryUpdateReport: ...
```

行为：

- 使用同一个 provider，`allow_tool_calls=False`，`tools=[]`。
- 只传当前 turn 的用户请求、最终回复、工具结果摘要和当前记忆索引。
- Prompt 明确四类记忆定义、scope 选择规则、不要保存临时状态、不要保存 secret。
- 模型返回 JSON 操作列表；解析失败或出现 tool_call 视为更新失败。
- 所有操作经 `SecretScrubber` 处理后写入 NoteStore。
- 写入完成后调用 `MemoryIndex.rebuild()`。

异步策略：

- `MemoryManager` 持有单线程 `ThreadPoolExecutor`。
- Agent Loop 自然结束后调用 `schedule_update()`，立即返回。
- 后台任务完成后更新 `MemoryRuntimeState.last_update_at` 或 `last_error`。
- 测试可使用同步 executor 或直接调用 `update_from_turn()`。

### `huicode.memory.scrub`

**Responsibility:** 注入和写入前脱敏。

规则：

- 屏蔽 `api_key`、`Authorization`、`Bearer ...`、`x-api-key`、`ANTHROPIC_API_KEY`、`OPENAI_API_KEY` 等常见 secret。
- 对 `headers`、`env`、`token`、`secret`、`password` 字样附近的值做保守替换。
- `/memory`、`/sessions`、warning 和 index 注入都只能使用 scrub 后文本。

### `huicode.memory.manager`

**Responsibility:** CLI/Agent 统一入口。

接口：

```python
class MemoryManager:
    def __init__(self, workspace: Path, settings: MemoryConfig, provider: Provider) -> None: ...
    def start(self, state: AgentState) -> list[str]: ...
    def refresh_prompt_memory(self, state: AgentState) -> None: ...
    def record_message(self, state: AgentState, message: ConversationMessage) -> None: ...
    def schedule_update_after_final(self, state: AgentState, mode: AgentMode, turn_start: int) -> MemoryUpdateReport: ...
    def list_sessions(self) -> list[SessionSummary]: ...
    def resume_session(self, session_id: str, state: AgentState, context_manager: ContextManager, config: LLMConfig) -> ResumeReport: ...
    def clear_current_session(self, state: AgentState) -> None: ...
    def status(self, state: AgentState) -> MemoryStatus: ...
    def close(self) -> None: ...
```

`start()` 顺序：

1. 创建目录。
2. 打开新 session。
3. 清理超过 30 天的非活动 session。
4. 加载指令文件。
5. 加载或重建记忆索引。
6. 写入 `state.memory`。

`resume_session()` 顺序：

1. 扫描 JSONL，跳过坏行。
2. 运行 `recover_safe_messages()`。
3. 必要时插入 time gap context。
4. 用恢复消息替换 `state.messages`。
5. 把 recorder 切到该 session，后续继续追加到同一 JSONL。
6. 估算 token；如果接近窗口，调用 `ContextManager.manual_compact()`。
7. 返回中文 warning 和压缩结果。

## Prompt Integration

### `PromptContext`

新增字段：

```python
memory_index: str = ""
memory_warnings: tuple[str, ...] = ()
```

保留 `custom_instructions` 用于项目指令。

### `build_agent_prompt()`

从 `state.memory` 填充：

```python
PromptContext(
    custom_instructions=state.memory.instructions_text,
    memory_index=state.memory.memory_index_text,
    memory_warnings=tuple(state.memory.warnings),
)
```

### `build_prompt_bundle()`

调整模块：

- 固定系统模块仍在最前。
- `custom_instructions` 放入 stable/cacheable 模块。
- `memory_index` 放入 supplemental/non-cacheable 模块，格式：

```xml
<huicode_context type="memory_index" scope="long_term">
...
如果需要文件细节，请重新读取 source 指向的笔记或项目文件，不要只凭索引脑补。
</huicode_context>
```

这样 AC14 的“请求前注入记忆索引”不会破坏 tool_use/tool_result 消息序列。

## Agent Loop Integration

`run_agent_loop()` 新增可选参数：

```python
memory: MemoryManager | None = None
```

改动点：

1. 进入 turn 时记录 `turn_start = len(state.messages)`。
2. 追加 user message 后调用 `memory.record_message()`。
3. 追加 assistant message 后调用 `memory.record_message()`。
4. 追加 tool message 后调用 `memory.record_message()`。
5. 每次 build prompt 前调用 `memory.refresh_prompt_memory(state)`，确保 index 更新后下一轮可见。
6. 当 stop_reason 为 `final` 且该轮最终 assistant 没有 tool_calls 时，调用 `memory.schedule_update_after_final()`。
7. 记忆失败产生 `AgentEvent(kind="memory")` 或写入 state warning，不改变原有 done 结果。

`AgentEventKind` 增加：

```python
"memory"
```

TUI 渲染示例：

```text
HuiCode> 记忆更新已排队
HuiCode> 记忆更新失败: 模型返回的 JSON 无法解析
```

## CLI Commands

新增命令：

```text
/memory
/memory update
/memory rebuild
/sessions
/resume <session-id>
/sessions clean
```

行为：

- `/memory`：展示 enabled、session_id、项目/用户笔记数、index 行数/大小、pending 更新、last_update_at、last_error。
- `/memory update`：用当前会话最近一轮手动触发记忆整理；如果没有可整理内容，给出中文提示。
- `/memory rebuild`：扫描 notes 重建 index。
- `/sessions`：列出最近会话 ID、标题、更新时间、消息数和 warning 数。
- `/resume <session-id>`：恢复指定会话；显示坏行跳过、是否截断、是否插入时间跨度提醒、是否触发压缩。
- `/sessions clean`：手动清理过期会话，显示清理数量。
- `/clear`：清空当前 `state.messages`，重置上下文状态，关闭当前 recorder 并创建新 session；不删除旧 session、notes 或 index。
- `/config`：追加 memory 摘要，不显示 secret。

## Module Interactions

### 启动

```text
CLI start
  -> load_config()
  -> create_provider()
  -> create MemoryManager
  -> MemoryManager.start(state)
       -> cleanup old sessions
       -> open new session recorder
       -> load instructions
       -> load/rebuild memory index
       -> state.memory = ...
  -> interactive loop
```

### 普通请求

```text
user input
  -> _run_request(..., memory_manager)
  -> run_agent_loop()
       -> append user message
       -> memory.record_message(user)
       -> refresh_prompt_memory()
       -> build prompt with instructions + index
       -> provider.stream_chat()
       -> append assistant message
       -> memory.record_message(assistant)
       -> execute tools if any
           -> append tool messages
           -> memory.record_message(tool)
       -> if final without tool calls:
           -> memory.schedule_update_after_final()
  -> user sees final answer without waiting for memory update
```

### 恢复会话

```text
/resume <id>
  -> SessionStore.recover(id)
       -> scan JSONL
       -> skip bad lines
       -> decode messages
       -> recover_safe_messages()
       -> maybe time_gap message
  -> replace state.messages
  -> switch recorder to existing session
  -> ContextManager.manual_compact() if over budget
  -> refresh instructions + index
```

### 自动笔记更新

```text
final answer
  -> MemoryUpdater.update_from_turn()
       -> build no-tool memory prompt
       -> provider.stream_chat(allow_tool_calls=False)
       -> parse JSON operations
       -> apply NoteStore writes
       -> MemoryIndex.rebuild()
       -> update state.memory.last_update_at
```

## File Organization

```text
huicode/
├── memory/
│   ├── __init__.py
│   ├── codec.py
│   ├── index.py
│   ├── instructions.py
│   ├── manager.py
│   ├── notes.py
│   ├── paths.py
│   ├── recovery.py
│   ├── scrub.py
│   ├── sessions.py
│   ├── types.py
│   └── updater.py
├── agent.py
├── agent_events.py
├── cli.py
├── config.py
├── prompts/
│   ├── base.py
│   ├── builder.py
│   └── modules.py
└── tui.py

tests/
├── test_memory_instructions.py
├── test_memory_sessions.py
├── test_memory_recovery.py
├── test_memory_notes.py
├── test_memory_index.py
├── test_memory_updater.py
├── test_agent_memory.py
├── test_cli_memory.py
└── test_prompt_builder.py

specs/
└── 010-memory-system/
    ├── spec.md
    ├── plan.md
    ├── task.md
    ├── checklist.md
    └── acceptance_report.md
```

## Technical Decisions

| Decision Point | Choice | Rationale |
| --- | --- | --- |
| 会话格式 | JSONL append-only | 满足崩溃最多丢最后一行，坏行可跳过，且无需 meta 文件。 |
| 会话 meta | 每次扫描 JSONL 计算 | 避免 ID、标题、消息数多处状态不同步。 |
| 当前 `/clear` 行为 | 新开 session，旧 session 保留 | 用户得到空上下文，同时历史仍可恢复。 |
| 指令文件名 | `.huicode/instructions.md` 为主，兼容 `.mewcode` 和根目录文件 | 贴合当前 HuiCode 项目，同时尊重需求里的 MewCode 命名。 |
| include 安全 | resolve 后做边界检查 + visited 防环 | 阻止路径逃逸和循环引用。 |
| 长期记忆注入 | 非缓存 supplemental 模块 | 索引可能变化，放入动态系统上下文更稳。 |
| 自动笔记更新 | 后台单线程，失败降级 | 不阻塞最终回复，失败不影响 Agent Loop。 |
| 去重策略 | LLM 判断操作，代码做 schema/路径/secret 校验 | 满足“去重交给 LLM”，同时保留工程防线。 |
| 索引大小控制 | 确定性重建和裁剪 | 不引入向量库或额外摘要策略，保证大小可预测。 |
| 恢复工具历史 | 截断到最后安全边界 | 优先保证 OpenAI/Anthropic 协议合法，不冒险保留破损尾部。 |
| 过期清理 | 启动时自动，命令可手动触发 | 实现 30 天清理，同时保留用户可观察入口。 |
| Secret 处理 | 注入和写笔记前脱敏 | 状态输出和模型上下文都不暴露敏感值。 |

## Requirement Coverage

| Requirement | Plan Coverage |
| --- | --- |
| F1-F4 | `InstructionLoader`、优先级顺序、`@include` 边界检查、Prompt system context 注入。 |
| F5-F7 | `SessionStore`、`SessionRecorder`、`codec`、`recovery` 坏行跳过和协议安全截断。 |
| F8-F10 | `/resume` 调用 `ContextManager.manual_compact()`、time gap message、`cleanup_expired()`。 |
| F11-F14 | `MemoryNote` 四类、scope 分离、`MemoryUpdater` 自然结束后更新。 |
| F15-F17 | `MemoryIndex` 大小限制、source 定位、`SecretScrubber`。 |
| F18-F19 | `/memory`、`/memory update`、`/sessions`、`/resume`、`/clear` 新语义。 |
| F20-F21 | Agent 可选 memory 参数、PromptBundle 注入不改消息序列、失败写 warning 不崩溃。 |
| F22 | README 更新任务。 |
| N1-N8 | 路径集中管理、协议安全裁剪、索引限制、后台更新、Markdown/JSONL、中文状态、失败降级和异常测试。 |
