# HuiCode Plan Mode 权限与交互修复 Plan

## Architecture Overview

本次修复在 Agent Loop 层增加 Plan Mode 工具执行守卫：模型响应中的工具调用即使没有出现在当前暴露的工具列表里，也必须在执行前再次检查当前模式是否允许。Plan Mode 下只有 `Read`、`Find`、`Search`、`Glob` 可执行，其他工具直接生成结构化 `ToolResult.failure("permission_denied", ...)` 并回灌历史。这样限制不依赖提示词、不依赖 Provider 工具列表，也不依赖权限确认。

同时，TUI 的每轮进度事件会展示当前任务模式和权限模式；权限确认提示保留长输入，同时明确短输入 `d/o/s/a` 和默认拒绝。CLI 增加更短的 `/perm` 别名，等价于 `/permissions`。

## Core Data Structures

### AgentOptions

保持现有字段不变：

```python
AgentOptions(
    mode: AgentMode,
    read_only_tool_names: frozenset[str],
)
```

Plan Mode 执行守卫直接使用 `options.read_only_tool_names` 判断允许工具。

### ToolResult

继续使用现有结构：

```python
ToolResult.failure(
    code="permission_denied",
    message="Plan Mode 只允许读类工具",
    details={...},
)
```

拒绝结果作为普通工具结果写入会话历史。

### AgentEvent.progress.data

扩展进度事件中的 `data`：

```python
{
    "stage": "assistant_turn_start",
    "mode": options.mode,
    "permission_mode": context.permissions.mode if exists else "disabled",
}
```

TUI 读取这两个字段用于显示状态。

## Module Design

### `huicode/agent.py`

**Responsibility:** Agent Loop 和工具批处理。

**Changes:**

- 在 progress 事件中加入 `permission_mode`。
- 在 `execute_tool_batches()` 中接收 `options` 或 read-only set。
- 对每个工具调用先执行 Plan Mode 允许性判断。
- 如果当前模式是 `plan` 且工具不在 read-only set 中，直接返回 `permission_denied` 工具结果。
- 拒绝结果仍走 `_tool_message()`、`AgentEvent(kind="tool_result")`，确保回灌历史。
- 对被拒绝的工具不调用 `execute_tool_call()`，也不触发权限确认。

### `huicode/tui.py`

**Responsibility:** 渲染进度、权限确认提示、工具结果。

**Changes:**

- `assistant_turn_start` 输出包含 `mode` 和 `permission_mode`。
- `format_permission_request()` 文案改为中文可读，并显示快捷键：
  `选择: [d]eny / [o]nce / [s]ession / [a]lways，回车默认 deny`。
- 保持原有 Markdown 和工具行渲染不回归。

### `huicode/cli.py`

**Responsibility:** 交互命令和权限确认输入。

**Changes:**

- `COMMANDS` 增加 `/perm`。
- `/perm` 等价于 `/permissions`。
- `/perm strict|default|permissive` 等价于 `/permissions strict|default|permissive`。
- 权限确认 prompt 缩短为 `Permission [d/o/s/a, enter=deny]> `。
- 空输入默认 `deny`。

### Tests

**Modify `tests/test_agent_loop.py`:**

- 新增测试：Plan Mode 中模型返回 `Bash(echo 2 > hello.txt)`，文件不存在或未改变，结果为 `permission_denied`，下一轮继续回答。
- 新增断言：progress 事件包含 `mode=plan` 和权限模式。

**Modify `tests/test_tui.py`:**

- 新增测试：progress 输出包含 mode 和 permission mode。
- 更新权限确认文案测试，覆盖 `d/o/s/a` 和默认 deny。

**Modify `tests/test_cli.py`:**

- 新增 `/perm` 查看和切换模式测试。
- 更新确认输入测试，覆盖短输入和空输入默认拒绝。

## Module Interactions

```text
model tool calls
  -> execute_tool_batches(..., options)
  -> plan mode guard
     -> denied ToolResult OR execute_tool_call()
  -> tool result event
  -> history backfill
  -> next model iteration

CLI command
  -> /perm or /permissions
  -> update PermissionContext.mode
  -> progress event shows current task mode + permission mode
```

## File Organization

```text
Huicode/
├── huicode/
│   ├── agent.py
│   ├── cli.py
│   └── tui.py
├── tests/
│   ├── test_agent_loop.py
│   ├── test_cli.py
│   └── test_tui.py
└── specs/
    └── 007-plan-mode-permission-ux-fix/
        ├── spec.md
        ├── plan.md
        ├── task.md
        ├── checklist.md
        └── acceptance_report.md
```

## Technical Decisions

| Decision Point | Choice | Rationale |
| --- | --- | --- |
| Plan Mode 拦截位置 | Agent 工具批处理层 | 能覆盖模型绕过工具列表直接吐出的工具调用 |
| 拒绝结果形式 | `permission_denied` ToolResult | 保持 Agent Loop 回灌机制一致 |
| 是否进入权限确认 | Plan Mode 非读类工具不进入确认 | Plan Mode 是更高层任务模式约束，不能被 once/session/always 放开 |
| 权限命令别名 | `/perm` | 短、清楚，不破坏 `/permissions` 原命令 |
| 确认默认值 | 回车默认 deny | 避免误放行 |

## Coverage Mapping

- F1-F4 -> `agent.py` Plan Mode guard + Agent Loop tests
- F5-F6 -> `agent.py` progress data + `tui.py` progress rendering tests
- F7 -> `cli.py` `/perm` alias tests
- F8-F9 -> `tui.py` confirmation text + `cli.py` confirmation parsing tests
- F10 -> existing permission regression tests
