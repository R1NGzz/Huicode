# HuiCode 系统提示词完善 Tasks

## File List

| Action | File | Responsibility |
| --- | --- | --- |
| Modify | `huicode/prompts/modules.py` | 重写七个固定系统提示模块为 UTF-8 中文，并保持模块名与顺序不变。 |
| Modify | `tests/test_prompt_modules.py` | 增加关键规则断言，覆盖截图参考内容转写后的 HuiCode 规则。 |
| Modify | `tests/test_prompt_builder.py` | 增加稳定/动态拆分边界测试。 |
| Modify | `README.md` | 补充系统提示词完善说明和能力边界。 |
| Create | `specs/005-system-prompt-refinement/checklist.md` | 验收清单。 |
| Create | `specs/005-system-prompt-refinement/acceptance_report.md` | 实现后记录验收证据。 |

## T1: 重写固定系统提示模块

**Files:** `huicode/prompts/modules.py`

**Dependencies:** None

**Steps:**

1. 保留 `FIXED_MODULE_NAMES` 和 `OPTIONAL_MODULE_NAMES`。
2. 重写 `fixed_prompt_modules()` 的七个模块内容。
3. 确保 `identity` 包含终端 AI 编程助手、代码任务、安全代码优先。
4. 确保 `system_constraints` 包含用户可见输出、Markdown、URL、system-reminder、hook/事件上下文。
5. 确保 `task_mode` 和 `action_execution` 覆盖模糊任务、小步执行、测试验证、失败诊断和高风险操作确认。
6. 确保 `tool_usage` 只提到当前真实工具：`Read`、`Write`、`Edit`、`Bash`、`Find`、`Search`、`Glob`。
7. 确保 `tone_style` 和 `text_output` 覆盖无 emoji、简洁、`file_path:line_number`、短总结。

**Verification:** Run `python -m unittest tests.test_prompt_modules -v`; expect prompt module tests pass.

## T2: 增加 Prompt 模块关键规则测试

**Files:** `tests/test_prompt_modules.py`

**Dependencies:** T1

**Steps:**

1. 增加辅助函数按模块名读取内容。
2. 为七个固定模块添加关键短语断言。
3. 添加断言确认 `tool_usage` 不包含当前未实现的 `TaskCreate`、`Agent`、`MCP`、`ToolSearch`。
4. 保留原有顺序、分隔、可选模块槽位测试。

**Verification:** Run `python -m unittest tests.test_prompt_modules -v`; expect all pass.

## T3: 增加 Prompt Builder 边界测试

**Files:** `tests/test_prompt_builder.py`

**Dependencies:** T1

**Steps:**

1. 增加断言：稳定文本包含固定模块标题。
2. 增加断言：稳定文本不包含 `<huicode_context` 和 `<huicode_instruction`。
3. 增加断言：动态文本只包含环境标签，不混入固定模块标题。
4. 保留 Plan/Do 注入频率测试。

**Verification:** Run `python -m unittest tests.test_prompt_builder -v`; expect all pass.

## T4: 更新 README

**Files:** `README.md`

**Dependencies:** T1

**Steps:**

1. 在“结构化系统提示”附近补充本章完善后的行为约束说明。
2. 明确这些提示词不会让 HuiCode 拥有尚未实现的子 Agent、TaskCreate、真实 MCP 或 ToolSearch 能力。
3. 保持配置示例和启动说明不变。

**Verification:** Read `README.md`; ensure wording matches current implementation and does not claim nonexistent capability.

## T5: 运行回归测试和编译检查

**Files:** `huicode/prompts/modules.py`, `tests/test_prompt_modules.py`, `tests/test_prompt_builder.py`

**Dependencies:** T1-T4

**Steps:**

1. Run `python -m unittest tests.test_prompt_modules tests.test_prompt_builder -v`。
2. Run `python -m unittest discover -v`。
3. Run `python -m compileall -q huicode tests`。
4. 如果失败，修复后重新运行对应命令。

**Verification:** All commands pass.

## T6: 写验收报告并提交

**Files:** `specs/005-system-prompt-refinement/acceptance_report.md`

**Dependencies:** T5

**Steps:**

1. 记录已完成项。
2. 记录测试和编译检查证据。
3. 检查 tmux 可用性；若不可用，记录环境限制。
4. 根据 AGENT.md 要求提交 Git，避免提交 `huicode.yaml` 或临时文件。

**Verification:** `acceptance_report.md` exists and includes actual command results; `git status --short` shows no本章相关未提交改动。

## Execution Order

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6
```
