# HuiCode 五层权限系统 Plan

## Architecture Overview

本章在现有工具执行链路前插入权限网关：模型仍通过 Agent Loop 产出 `ToolCall`，但 `execute_tool_call()` 在真正调用工具前先交给权限系统决策。权限系统按固定顺序评估五层防御：危险黑名单、路径沙箱、会话级规则、持久规则、权限模式/人在回路。决策结果为放行、拒绝或需要用户确认。拒绝和确认失败都返回普通 `ToolResult.failure(...)`，因此 Agent Loop 会把它当作工具结果回灌给模型，而不是终止流程。

## Core Data Structures

### PermissionMode

```python
PermissionMode = Literal["strict", "default", "permissive"]
```

- `strict`：规则未命中时拒绝。
- `default`：规则未命中且存在风险或副作用时询问用户；明显只读低风险调用可放行。
- `permissive`：规则未命中时默认放行，但黑名单和路径沙箱仍然硬拦截。

### PermissionDecision

```python
PermissionDecision(
    allowed: bool,
    reason: str,
    source: str,
    requires_confirmation: bool = False,
    matched_rule: str | None = None,
    risk: str = "low",
)
```

用于表达权限引擎的判断。`source` 标记命中来源，例如 `blacklist`、`sandbox`、`session_rule`、`local_rule`、`project_rule`、`user_rule`、`mode`、`confirmation`。

### PermissionRule

```python
PermissionRule(
    tool: str,
    pattern: str,
    action: Literal["allow", "deny"],
    source: str,
)
```

规则文本采用 `工具名(模式)`，例如 `Bash(git *)`、`Read(src/**/*.py)`、`Edit(README.md)`。`pattern` 使用精确匹配和 glob 匹配；对 `Bash` 匹配命令文本，对文件工具匹配路径，对搜索工具匹配模式或查询。

### PermissionConfig

```python
PermissionConfig(
    mode: PermissionMode = "default",
    rules: list[PermissionRule] = [],
)
```

每层 YAML 可声明 `mode` 和 `rules`。最终模式按近项目优先原则覆盖：本地级 > 项目级 > 用户级 > 默认值。

### PermissionContext

```python
PermissionContext(
    workspace: Path,
    mode: PermissionMode,
    rules: list[PermissionRule],
    session_rules: list[PermissionRule],
    confirmer: PermissionConfirmer | None,
)
```

`ToolContext` 增加可选 `permissions: PermissionContext | None` 字段。没有权限上下文时保留旧行为，便于测试和兼容。

### PermissionConfirmer

```python
class PermissionConfirmer(Protocol):
    def confirm(self, request: PermissionRequest) -> PermissionConfirmation: ...
```

TUI 实现该接口，负责展示工具名、参数摘要、风险说明，并返回用户选择：拒绝、仅本次放行、本会话放行、永久放行。

## Rule File Format

用户级、项目级、本地级均使用相同 YAML 子集：

```yaml
mode: default
rules:
  Bash(git *): allow
  Bash(rm -rf *): deny
  Read(src/**/*.py): allow
  Edit(README.md): allow
```

建议路径：

```text
用户级：~/.huicode/permissions.yaml
项目级：<workspace>/.huicode-permissions.yaml
本地级：<workspace>/.huicode-permissions.local.yaml
```

本地级文件用于机器私有偏好，默认不建议提交；项目级文件用于团队共享策略。永久放行默认写入本地级文件，避免误改团队规则。

## Module Design

### `huicode/permissions/base.py`

**Responsibility:** 定义权限相关枚举、数据类、协议和错误类型。

**External Interface:**

- `PermissionMode`
- `PermissionRule`
- `PermissionConfig`
- `PermissionContext`
- `PermissionDecision`
- `PermissionRequest`
- `PermissionConfirmation`
- `PermissionConfirmer`
- `PermissionConfigError`

### `huicode/permissions/blacklist.py`

**Responsibility:** 提供不可配置绕过的危险命令正则检查。

**External Interface:**

- `check_dangerous_command(command: str) -> PermissionDecision | None`

初始黑名单覆盖：

- `rm -rf /`、`rm -rf *` 等递归强删。
- `git reset --hard`、`git clean -fdx` 等破坏未提交改动的命令。
- `format`、`diskpart`、`mkfs` 等磁盘破坏命令。
- `chmod -R 777`、`takeown /f` 等大范围权限破坏命令。
- 指向系统目录的大范围删除或覆盖。

### `huicode/permissions/sandbox.py`

**Responsibility:** 做路径沙箱判定，统一替换/增强现有 `safe_join_workspace()`。

**External Interface:**

- `resolve_workspace_path(workspace: Path, path: str | Path) -> Path`
- `is_within_workspace(workspace: Path, target: Path) -> bool`
- `extract_tool_paths(tool_name: str, args: dict[str, object]) -> list[str]`

路径先解析绝对路径、`..` 和符号链接，再做 workspace 前缀判断。

### `huicode/permissions/rules.py`

**Responsibility:** 解析 `工具名(模式)`，匹配工具调用。

**External Interface:**

- `parse_rule_key(text: str) -> tuple[str, str]`
- `match_rule(rule: PermissionRule, call: ToolCall) -> bool`
- `target_value_for_call(call: ToolCall) -> str`

匹配策略：先精确相等，再 `fnmatch` glob。`Glob` 作为 `Find` 的别名参与匹配。

### `huicode/permissions/config.py`

**Responsibility:** 加载三层 YAML 规则并合并。

**External Interface:**

- `permission_config_paths(workspace: Path) -> PermissionConfigPaths`
- `load_permission_config(paths: PermissionConfigPaths) -> PermissionConfig`
- `append_persistent_rule(path: Path, rule: PermissionRule) -> None`

优先级：用户级先加载，项目级覆盖用户级，本地级覆盖项目级；会话级不在这里持久化，运行时由 `PermissionContext.session_rules` 管理。

### `huicode/permissions/engine.py`

**Responsibility:** 权限决策核心。

**External Interface:**

- `evaluate_permission(call: ToolCall, tool: Tool | None, context: ToolContext) -> PermissionDecision`
- `apply_confirmation(decision, call, context) -> PermissionDecision`
- `permission_denied_result(call, decision) -> ToolResult`

评估顺序：

1. Bash 黑名单硬拦截。
2. 路径沙箱硬拦截。
3. 会话级规则。
4. 本地级规则。
5. 项目级规则。
6. 用户级规则。
7. 权限模式。
8. 人在回路确认。

### `huicode/tools/executor.py`

**Responsibility:** 在工具真正运行前调用权限引擎。

**Changes:**

- 未知工具和参数非法逻辑保持不变。
- 找到工具后先执行权限检查。
- 权限拒绝时返回 `ToolResult.failure("permission_denied", ...)`。
- 权限确认通过后继续执行原工具。

### `huicode/tools/base.py`

**Responsibility:** 承载权限上下文，并统一路径沙箱。

**Changes:**

- `ToolContext` 增加 `permissions: PermissionContext | None = None`。
- `safe_join_workspace()` 改用新路径解析函数，保持旧调用接口。

### `huicode/cli.py`

**Responsibility:** 加载权限配置、提供 TUI 确认器和权限模式命令。

**Changes:**

- 启动时加载三层权限配置，创建 `PermissionContext`。
- 增加 `/permissions` 查看当前模式和规则来源摘要。
- 增加 `/permissions strict|default|permissive` 切换当前会话模式。
- TUI 确认器在需要时读取用户输入：deny、once、session、always。

### `huicode/tui.py`

**Responsibility:** 渲染权限相关提示和拒绝摘要。

**Changes:**

- 增加权限确认文案格式化函数。
- 权限拒绝仍作为工具结果行展示，但摘要更清楚。

### Tests

新增测试模块：

- `tests/test_permissions_blacklist.py`
- `tests/test_permissions_sandbox.py`
- `tests/test_permissions_rules.py`
- `tests/test_permissions_config.py`
- `tests/test_permissions_engine.py`

修改测试模块：

- `tests/test_tools_files.py`
- `tests/test_tools_shell.py`
- `tests/test_agent_loop.py`
- `tests/test_cli.py`
- `tests/test_tui.py`

## Module Interactions

```text
CLI startup
  -> load permission config
  -> create PermissionContext
  -> ToolContext(permissions=...)

Agent Loop
  -> ToolCall
  -> execute_tool_call()
  -> evaluate_permission()
     -> blacklist
     -> sandbox
     -> session/local/project/user rules
     -> mode
     -> confirmer if needed
  -> tool.run() OR permission_denied ToolResult
  -> tool result backfills conversation history
```

## File Organization

```text
huicode/
├── permissions/
│   ├── __init__.py
│   ├── base.py
│   ├── blacklist.py
│   ├── sandbox.py
│   ├── rules.py
│   ├── config.py
│   └── engine.py
├── tools/
│   ├── base.py
│   └── executor.py
├── cli.py
└── tui.py

tests/
├── test_permissions_blacklist.py
├── test_permissions_sandbox.py
├── test_permissions_rules.py
├── test_permissions_config.py
├── test_permissions_engine.py
├── test_agent_loop.py
├── test_cli.py
└── test_tui.py
```

## Technical Decisions

| Decision Point | Choice | Rationale |
| --- | --- | --- |
| 权限入口 | 放在 `execute_tool_call()` | 覆盖所有工具调用，不改 Provider 和模型协议 |
| 黑名单优先级 | 永远第一且不可覆盖 | 满足硬安全边界 |
| 规则格式 | `rules:` 下的 `工具名(模式): allow|deny` | 符合用户示例，也适合当前轻量 YAML 风格 |
| 永久放行写入层 | 默认写入本地级 | 避免自动修改团队项目规则或用户全局规则 |
| 默认模式 | `default` | 平衡可用性和安全性，副作用/风险操作进入确认 |
| 拒绝表达 | 返回结构化 `ToolResult.failure` | Agent Loop 已能回灌工具结果，可让模型调整策略 |
| 路径沙箱 | 统一解析符号链接后判断 | 防止 `..`、绝对路径和 symlink 逃逸 |
| TUI 确认 | 同步阻塞当前工具调用 | 当前 Agent Loop 是同步生成器，先保持实现简单 |

## Coverage Mapping

- F1, F16, F17 -> `tools/executor.py` + `permissions/engine.py`
- F2, F3 -> `permissions/blacklist.py`
- F4, F5 -> `permissions/sandbox.py` + `tools/base.py`
- F6-F10 -> `permissions/rules.py` + `permissions/config.py`
- F11-F12 -> `permissions/engine.py`
- F13-F15, F18-F19 -> `cli.py` + `tui.py`
- F20 -> `permissions/config.py` + CLI startup error handling
