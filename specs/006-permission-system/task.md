# HuiCode 五层权限系统 Tasks

## File List

| Action | File | Responsibility |
| --- | --- | --- |
| Create | `huicode/permissions/__init__.py` | 暴露权限系统公共类型和函数。 |
| Create | `huicode/permissions/base.py` | 定义权限模式、规则、决策、确认请求、确认结果、确认器协议和配置错误。 |
| Create | `huicode/permissions/blacklist.py` | 实现不可配置绕过的危险 Bash 命令黑名单。 |
| Create | `huicode/permissions/sandbox.py` | 实现 workspace 路径解析、符号链接解析和逃逸检查。 |
| Create | `huicode/permissions/rules.py` | 解析 `工具名(模式)`，匹配工具调用目标。 |
| Create | `huicode/permissions/config.py` | 加载用户级、项目级、本地级 YAML 权限规则并合并。 |
| Create | `huicode/permissions/engine.py` | 按黑名单、沙箱、规则、模式、确认流程做权限决策。 |
| Modify | `huicode/tools/base.py` | 给 `ToolContext` 增加权限上下文，并让路径检查走新沙箱逻辑。 |
| Modify | `huicode/tools/executor.py` | 在工具执行前调用权限引擎，拒绝时返回结构化工具结果。 |
| Modify | `huicode/cli.py` | 加载权限配置，创建确认器，支持 `/permissions` 查看和切换模式。 |
| Modify | `huicode/tui.py` | 增加权限确认提示和权限拒绝摘要格式化。 |
| Modify | `README.md` | 记录权限模式、规则文件格式和阶段边界。 |
| Create | `tests/test_permissions_blacklist.py` | 覆盖危险命令硬拦截。 |
| Create | `tests/test_permissions_sandbox.py` | 覆盖路径、绝对路径、`..`、符号链接逃逸。 |
| Create | `tests/test_permissions_rules.py` | 覆盖规则解析、精确匹配和 glob 匹配。 |
| Create | `tests/test_permissions_config.py` | 覆盖三层 YAML 加载、优先级和解析错误。 |
| Create | `tests/test_permissions_engine.py` | 覆盖决策顺序、模式、确认、本次/会话/永久放行。 |
| Modify | `tests/test_tools_files.py` | 适配新路径沙箱并覆盖兼容性。 |
| Modify | `tests/test_tools_shell.py` | 覆盖 Bash 黑名单进入执行前被拒绝。 |
| Modify | `tests/test_agent_loop.py` | 覆盖权限拒绝回灌后 Agent Loop 继续。 |
| Modify | `tests/test_cli.py` | 覆盖 `/permissions` 命令和确认输入。 |
| Modify | `tests/test_tui.py` | 覆盖权限确认/拒绝显示。 |
| Create | `specs/006-permission-system/checklist.md` | 验收清单。 |
| Create | `specs/006-permission-system/acceptance_report.md` | 实现后记录验收证据。 |

## T1: 定义权限基础类型

**Files:** `huicode/permissions/__init__.py`, `huicode/permissions/base.py`, `tests/test_permissions_engine.py`

**Dependencies:** None

**Steps:**

1. 创建 `huicode/permissions` 包。
2. 定义 `PermissionMode`，包含 `strict`、`default`、`permissive`。
3. 定义 `PermissionRule`、`PermissionConfig`、`PermissionDecision`、`PermissionRequest`、`PermissionConfirmation`。
4. 定义 `PermissionConfirmer` 协议和 `PermissionConfigError`。
5. 在 `__init__.py` 暴露公共类型。
6. 添加基础默认值测试。

**Verification:** Run `python -m unittest tests.test_permissions_engine -v`; expect基础类型测试通过。

## T2: 实现危险命令黑名单

**Files:** `huicode/permissions/blacklist.py`, `tests/test_permissions_blacklist.py`

**Dependencies:** T1

**Steps:**

1. 定义危险命令正则列表。
2. 实现 `check_dangerous_command(command)`。
3. 覆盖 `rm -rf /`、`rm -rf *`、`git reset --hard`、`git clean -fdx`、`format`、`diskpart`、`mkfs`、`chmod -R 777` 等场景。
4. 确认普通命令如 `git status`、`dir`、`python -m unittest` 不命中。

**Verification:** Run `python -m unittest tests.test_permissions_blacklist -v`; expect all pass.

## T3: 实现路径沙箱

**Files:** `huicode/permissions/sandbox.py`, `huicode/tools/base.py`, `tests/test_permissions_sandbox.py`, `tests/test_tools_files.py`

**Dependencies:** T1

**Steps:**

1. 实现 `resolve_workspace_path(workspace, path)`，统一处理相对路径、绝对路径、`..` 和符号链接。
2. 实现 `is_within_workspace(workspace, target)`。
3. 实现 `extract_tool_paths(tool_name, args)`，从 `Read`、`Write`、`Edit`、`Find`、`Search`、`Bash` 中提取可判断路径。
4. 修改 `safe_join_workspace()` 复用新沙箱逻辑，保持旧接口。
5. 添加符号链接逃逸测试；Windows 上符号链接不可创建时用 skip 或可用替代断言。

**Verification:** Run `python -m unittest tests.test_permissions_sandbox tests.test_tools_files -v`; expect all pass.

## T4: 实现规则解析与匹配

**Files:** `huicode/permissions/rules.py`, `tests/test_permissions_rules.py`

**Dependencies:** T1

**Steps:**

1. 实现 `parse_rule_key("Bash(git *)")`。
2. 实现 `target_value_for_call(call)`。
3. 实现 `match_rule(rule, call)`，先精确匹配，再 glob 匹配。
4. 支持 `Glob` 与 `Find` 的兼容匹配。
5. 测试 `Bash(git *)`、`Read(src/**/*.py)`、`Edit(README.md)`、`Search(query)` 等场景。

**Verification:** Run `python -m unittest tests.test_permissions_rules -v`; expect all pass.

## T5: 实现三层配置加载和持久规则写入

**Files:** `huicode/permissions/config.py`, `tests/test_permissions_config.py`

**Dependencies:** T1, T4

**Steps:**

1. 定义用户级、项目级、本地级默认路径。
2. 实现最小 YAML 加载，支持 `mode` 和 `rules` 映射。
3. 校验 mode 只能是三档之一。
4. 校验规则结果只能是 `allow` 或 `deny`。
5. 合并三层配置：用户级 < 项目级 < 本地级。
6. 实现 `append_persistent_rule()`，默认追加到本地级。
7. 测试配置解析失败时抛出 `PermissionConfigError`，不静默放行。

**Verification:** Run `python -m unittest tests.test_permissions_config -v`; expect all pass.

## T6: 实现权限引擎

**Files:** `huicode/permissions/engine.py`, `tests/test_permissions_engine.py`

**Dependencies:** T2, T3, T4, T5

**Steps:**

1. 实现 `evaluate_permission(call, tool, context)`。
2. 按黑名单、路径沙箱、会话级规则、本地级规则、项目级规则、用户级规则、权限模式顺序判断。
3. 实现 `permission_denied_result(call, decision)`。
4. 实现确认结果处理：本次放行、本会话放行、永久放行、拒绝。
5. 测试黑名单不可被 allow 规则和 permissive 模式绕过。
6. 测试严格模式默认拒绝、默认模式触发确认、放行模式默认放行。

**Verification:** Run `python -m unittest tests.test_permissions_engine -v`; expect all pass.

## T7: 接入工具执行链路

**Files:** `huicode/tools/base.py`, `huicode/tools/executor.py`, `tests/test_tools_shell.py`, `tests/test_agent_loop.py`

**Dependencies:** T6

**Steps:**

1. 给 `ToolContext` 增加 `permissions` 可选字段，默认 `None` 保持旧测试兼容。
2. 在 `execute_tool_call()` 找到工具并校验参数后调用权限引擎。
3. 权限拒绝时返回 `ToolResult.failure("permission_denied", ...)`。
4. 确认通过后才执行 `tool.run()`。
5. 添加 Agent Loop 测试：权限拒绝以 tool result 形式进入历史，下一轮模型仍能回答。

**Verification:** Run `python -m unittest tests.test_tools_shell tests.test_agent_loop -v`; expect all pass.

## T8: 接入 CLI 权限上下文和命令

**Files:** `huicode/cli.py`, `tests/test_cli.py`

**Dependencies:** T5, T7

**Steps:**

1. 启动聊天时加载权限配置。
2. 创建 `PermissionContext` 并传入 `ToolContext`。
3. 实现同步 TUI 确认器，支持输入 `deny`、`once`、`session`、`always`。
4. 增加 `/permissions` 查看当前模式和规则摘要。
5. 增加 `/permissions strict|default|permissive` 切换当前会话模式。
6. 配置解析失败时输出清晰错误并停止启动。

**Verification:** Run `python -m unittest tests.test_cli -v`; expect all pass.

## T9: 更新 TUI 展示

**Files:** `huicode/tui.py`, `tests/test_tui.py`

**Dependencies:** T7, T8

**Steps:**

1. 增加权限确认请求格式化函数。
2. 优化权限拒绝工具结果摘要，让用户能看到工具名、参数摘要和拒绝来源。
3. 保持现有工具行和 Markdown 渲染不回归。

**Verification:** Run `python -m unittest tests.test_tui -v`; expect all pass.

## T10: 更新文档

**Files:** `README.md`, `specs/006-permission-system/checklist.md`

**Dependencies:** T1-T9

**Steps:**

1. README 增加权限系统章节。
2. 说明五层防御、三档权限模式、规则文件路径、规则格式。
3. 说明本章不做网络限制、资源配额和审计日志。
4. 生成 checklist。

**Verification:** Read `README.md` and `checklist.md`; ensure content matches implementation.

## T11: 全量验证、验收报告和提交

**Files:** `specs/006-permission-system/acceptance_report.md`

**Dependencies:** T10

**Steps:**

1. Run `python -m unittest discover -v`。
2. Run `python -m compileall -q huicode tests`。
3. 检查 tmux 是否可用；可用则按 AGENT.md 做简单 E2E，不可用则记录限制。
4. 写 `acceptance_report.md`。
5. 暂存本章相关文件，避免提交 `huicode.yaml` 和临时文件。
6. 创建 Git commit。

**Verification:** Full tests and compile pass; `acceptance_report.md` records evidence; git commit succeeds.

## Execution Order

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11
```
