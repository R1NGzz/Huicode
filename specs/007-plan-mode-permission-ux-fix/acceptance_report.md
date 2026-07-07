# HuiCode Plan Mode 权限与交互修复 Acceptance Report

## Summary

本章修复已完成并通过验收。Plan Mode 现在不再只依赖“暴露给模型的工具列表”，而是在工具执行层再次强制校验。模型即使直接返回 `Bash`、`Write`、`Edit` 等非读类工具调用，也会得到结构化 `permission_denied` 工具结果，结果会回灌进对话历史，Agent Loop 继续下一轮。

TUI 现在会在每轮开始显示当前任务模式和权限模式；权限确认展示与输入 prompt 都支持 `d/o/s/a`，直接回车默认 `deny`。CLI 新增 `/perm` 作为 `/permissions` 的短别名。

## Checklist Results

- C1: Passed. `tests.test_agent_loop.AgentLoopTests.test_plan_mode_denies_side_effect_tool_before_confirmation_and_continues` 验证 `Bash(echo 2 > hello.txt)` 在 Plan Mode 下不会修改文件。
- C2: Passed. 同一测试验证工具结果为 `permission_denied`，summary 包含 `Plan Mode`。
- C3: Passed. 同一测试验证 provider 被调用两轮，拒绝后仍产生最终回答。
- C4: Passed. 同一测试使用会抛错的 confirmer，证明 Plan Mode 拦截发生在权限确认前。
- C5: Passed. Agent progress event 包含 `mode` 与 `permission_mode`。
- C6: Passed. `tests.test_tui.TUITests.test_progress_renders_task_and_permission_mode` 验证 TUI 渲染 `mode=plan` 与 `permission=strict`。
- C7: Passed. `tests.test_tui.TUITests.test_permission_request_format` 验证确认文案包含 `[d]eny/[o]nce/[s]ession/[a]lways` 与 `enter=deny`。
- C8: Passed. `tests.test_cli.CLITests.test_permission_confirmation_shortcuts_and_empty_default_deny` 验证 prompt 为 `Permission [d/o/s/a, enter=deny]> `，`o` 映射 `once`，空输入映射 `deny`。
- C9: Passed. `tests.test_cli.CLITests.test_perm_alias_shows_and_switches_mode` 验证 `/perm` 查询和 `/perm strict` 切换。
- C10: Passed. README 已记录 `/perm` 与 `d/o/s/a` 快捷输入。

## Integration Results

- I1: Passed. 既有权限系统测试随全量测试通过。
- I2: Passed. 既有 Plan Mode 读类工具过滤和工具执行测试通过。
- I3: Passed. 既有 Agent Loop、工具批处理和 TUI 工具行测试通过。

## Commands Run

```powershell
python -m unittest tests.test_agent_loop tests.test_cli tests.test_tui -v
```

Result: Passed, 30 tests.

```powershell
python -m unittest tests.test_agent_loop tests.test_tool_batching tests.test_cli tests.test_tui -v
```

Result: Passed, 31 tests.

```powershell
python -m unittest discover -v
```

Result: Passed, 126 tests.

```powershell
python -m compileall -q huicode tests
```

Result: Passed.

```powershell
Get-Command tmux -ErrorAction SilentlyContinue
```

Result: No command found in this Windows environment, so tmux E2E was not run. The core E2E behavior is covered by automated Agent Loop, CLI, and TUI regression tests.

## End-To-End Scenario Evidence

- E1 Passed by automated regression: Plan Mode 下模型返回 `Bash(echo 2 > hello.txt)`，HuiCode 不进入权限确认，返回 `permission_denied` 工具结果，文件内容保持 `old`，随后继续下一轮并最终回答。
- E2 Passed by CLI/TUI tests: 权限确认展示快捷键，CLI prompt 显示 `d/o/s/a` 和 `enter=deny`，输入 `o` 本次放行，直接回车拒绝。

## Git

本报告随本章实现、测试、文档和 spec 文件一起提交。提交范围不包含 `huicode.yaml` 或旧的根目录临时文档。
