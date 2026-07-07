# HuiCode Plan Mode 权限与交互修复 Task

## File List

| File | Action | Purpose |
| --- | --- | --- |
| `huicode/agent.py` | Modify | 增加 Plan Mode 执行层拦截，扩展进度事件模式信息 |
| `huicode/tui.py` | Modify | 显示当前任务模式/权限模式，优化权限确认文案 |
| `huicode/cli.py` | Modify | 增加 `/perm` 别名，缩短权限确认输入提示 |
| `tests/test_agent_loop.py` | Modify | 覆盖 Plan Mode 越权工具调用被拒绝且 Loop 继续 |
| `tests/test_tui.py` | Modify | 覆盖模式显示与权限确认文案 |
| `tests/test_cli.py` | Modify | 覆盖 `/perm` 别名与短输入/空输入确认 |
| `README.md` | Modify if needed | 简要记录 `/perm` 和确认快捷键 |
| `specs/007-plan-mode-permission-ux-fix/acceptance_report.md` | Create | 记录验收结果 |

## Ordered Tasks

### T1. Inspect Current Control Flow

Dependencies: none

Steps:

1. 阅读 `huicode/agent.py` 中 `run_agent_loop()`、`execute_tool_batches()`、`execute_tool_call()`。
2. 阅读 `huicode/cli.py` 中命令解析和权限确认输入逻辑。
3. 阅读 `huicode/tui.py` 中 progress 和 permission request 的渲染逻辑。
4. 阅读相关测试，确认现有断言风格。

Verification:

- 能明确定位 Plan Mode 拦截应放在工具执行前、权限确认前。
- 能明确现有 `/permissions`、确认输入和 TUI progress 的测试入口。

### T2. Add Agent Execution Guard

Dependencies: T1

Steps:

1. 扩展 `execute_tool_batches()` 入参，使其能读取当前 `AgentOptions`。
2. 在每个工具执行前判断：如果 `options.mode == "plan"` 且工具名不在 `options.read_only_tool_names`，直接生成 `ToolResult.failure("permission_denied", ...)`。
3. 拒绝结果继续走现有工具结果事件和对话历史回灌流程。
4. 确保被拒绝工具不会调用 `execute_tool_call()`，因此不会触发权限确认。

Verification:

- 新增或更新单测证明 Plan Mode 下 `Bash(echo 2 > hello.txt)` 不会写入文件。
- 单测证明拒绝结果进入会话历史，并且下一轮 LLM 调用继续发生。

### T3. Add Mode Metadata To Progress Events

Dependencies: T1

Steps:

1. 在 `assistant_turn_start` progress event 的 `data` 中加入 `mode`。
2. 同一事件中加入当前 `permission_mode`，无权限上下文时使用 `disabled`。
3. 保持已有 progress event 消费方兼容。

Verification:

- 单测断言 progress event 包含 `mode=plan` 或当前模式。
- 单测断言 progress event 包含当前权限模式。

### T4. Improve TUI Mode And Permission Rendering

Dependencies: T3

Steps:

1. 调整 `tui.py` 的 progress 渲染，让每轮开始时显示任务模式和权限模式。
2. 重写权限确认展示文案，包含工具、目标、风险、原因。
3. 在确认文案中加入 `[d]eny / [o]nce / [s]ession / [a]lways` 和“回车默认 deny”。
4. 避免改动无关的 Markdown 或工具行渲染。

Verification:

- `tests/test_tui.py` 覆盖模式显示。
- `tests/test_tui.py` 覆盖确认文案包含 `d/o/s/a` 和默认拒绝说明。

### T5. Improve CLI Permission Commands And Prompt

Dependencies: T1

Steps:

1. 在命令列表中加入 `/perm`。
2. 让 `/perm` 等价于 `/permissions`。
3. 让 `/perm strict|default|permissive` 等价于 `/permissions strict|default|permissive`。
4. 将权限确认输入提示改为 `Permission [d/o/s/a, enter=deny]> `。
5. 确认空输入仍映射为 `deny`，短输入 `d/o/s/a` 映射到完整动作。

Verification:

- `tests/test_cli.py` 覆盖 `/perm` 查询和切换。
- `tests/test_cli.py` 覆盖短输入与空输入。

### T6. Documentation Touch-Up

Dependencies: T4, T5

Steps:

1. 检查 README 中权限命令说明是否已有 `/permissions`。
2. 如有相关章节，补充 `/perm` 别名和确认快捷键。
3. 保持文档改动最小，不重写无关内容。

Verification:

- README 中可以找到 `/perm` 或权限确认快捷键说明。

### T7. Run Verification

Dependencies: T2, T3, T4, T5, T6

Steps:

1. 运行目标测试：`python -m unittest tests.test_agent_loop tests.test_cli tests.test_tui -v`。
2. 运行全量测试：`python -m unittest discover -v`。
3. 运行编译检查：`python -m compileall -q huicode tests`。
4. 检查 `tmux` 是否可用；若 Windows 环境不可用，在验收报告中记录原因。

Verification:

- 目标测试通过。
- 全量测试通过。
- 编译检查通过。
- tmux E2E 可运行则记录结果，不可运行则记录不可用证据。

### T8. Acceptance Report And Commit

Dependencies: T7

Steps:

1. 创建 `acceptance_report.md`，按 checklist 记录实际证据。
2. 检查 `git status`，只暂存本章相关文件。
3. 提交 Git，提交信息描述本章修复。

Verification:

- `acceptance_report.md` 包含通过/失败项和命令证据。
- Git commit 成功，未包含 `huicode.yaml` 或旧根目录临时文件。

## Execution Order

1. T1 Inspect Current Control Flow
2. T2 Add Agent Execution Guard
3. T3 Add Mode Metadata To Progress Events
4. T4 Improve TUI Mode And Permission Rendering
5. T5 Improve CLI Permission Commands And Prompt
6. T6 Documentation Touch-Up
7. T7 Run Verification
8. T8 Acceptance Report And Commit

## Self Check

- Plan Mode 执行层拦截、模式显示、`/perm` 交互、确认快捷键都有对应任务。
- 每个任务都有验证方法。
- 任务顺序先读代码，再改核心安全逻辑，再改界面和测试，最后验收提交。
