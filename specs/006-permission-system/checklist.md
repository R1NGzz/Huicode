# HuiCode 五层权限系统 Checklist

## Implementation Completeness

- [x] 权限基础类型存在并有默认值：`strict`、`default`、`permissive` 三档模式可用。验证：`tests.test_permissions_engine` 通过。
- [x] Bash 危险命令黑名单在规则和模式之前生效，且不可被 allow 规则绕过。验证：`tests.test_permissions_blacklist`、`tests.test_permissions_engine` 通过。
- [x] 黑名单覆盖递归强删、强制重置、磁盘格式化、大范围权限破坏等代表性命令。验证：`tests.test_permissions_blacklist` 通过。
- [x] 路径沙箱能拒绝 `..`、绝对路径和 workspace 外路径。验证：`tests.test_permissions_sandbox` 通过。
- [x] 路径沙箱在可创建符号链接的平台能拒绝 symlink 逃逸；不可创建时测试明确跳过该子场景。验证：`tests.test_permissions_sandbox` 通过。
- [x] `工具名(模式)` 规则能被解析，结果只允许 `allow` 或 `deny`。验证：`tests.test_permissions_rules`、`tests.test_permissions_config` 通过。
- [x] 规则匹配支持精确匹配和 glob 匹配。验证：`tests.test_permissions_rules` 通过。
- [x] `Glob` 与 `Find` 兼容匹配。验证：`tests.test_permissions_rules` 通过。
- [x] 用户级、项目级、本地级规则按优先级合并，本地级最高。验证：`tests.test_permissions_config` 通过。
- [x] 会话级临时规则覆盖本地级、项目级和用户级。验证：`tests.test_permissions_engine` 通过。

## Permission Modes and Confirmation

- [x] 严格模式下，未命中规则的工具调用被拒绝。验证：`tests.test_permissions_engine` 通过。
- [x] 默认模式下，未命中规则的低风险只读调用可放行，副作用或风险调用进入确认。验证：`tests.test_permissions_engine` 通过。
- [x] 放行模式下，未命中规则的调用默认放行，但黑名单和路径沙箱仍会拒绝。验证：`tests.test_permissions_engine` 通过。
- [x] 人在回路确认能处理拒绝、仅本次放行、本会话放行、永久放行。验证：`tests.test_permissions_engine`、`tests.test_cli` 通过。
- [x] 本会话放行会生成会话级规则并影响后续同类调用。验证：`tests.test_permissions_engine` 通过。
- [x] 永久放行会写入本地级规则文件。验证：`tests.test_permissions_config` 通过。

## Tool and Agent Integration

- [x] `execute_tool_call()` 在工具运行前调用权限引擎。验证：`tests.test_tools_shell` 通过。
- [x] 权限拒绝返回 `permission_denied` 结构化工具结果。验证：`tests.test_permissions_engine`、`tests.test_agent_loop` 通过。
- [x] Agent Loop 收到权限拒绝后继续下一轮，不崩溃、不直接终止。验证：`tests.test_agent_loop` 通过。
- [x] 现有文件工具 workspace 边界测试仍通过。验证：`tests.test_tools_files` 通过。
- [x] 现有 Bash 工具超时、非零退出、Windows 命令归一化测试仍通过。验证：`tests.test_tools_shell` 通过。

## CLI and TUI

- [x] CLI 启动时加载权限配置，并把权限上下文传入 `ToolContext`。验证：`tests.test_cli` 通过。
- [x] `/permissions` 能显示当前权限模式和规则摘要。验证：`tests.test_cli` 通过。
- [x] `/permissions strict|default|permissive` 能切换当前会话模式。验证：`tests.test_cli` 通过。
- [x] 权限确认提示显示工具名、参数摘要、风险摘要和可选决策。验证：`tests.test_tui`、`tests.test_cli` 通过。
- [x] 权限拒绝摘要能在 TUI 工具结果中清楚展示。验证：`tests.test_tui` 和 CLI 权限拒绝测试通过。
- [x] 权限配置解析失败时给出明确错误，并且不会默认放行。验证：`tests.test_permissions_config` 通过。

## Documentation

- [x] README 说明五层防御、三档权限模式、规则格式和规则文件路径。验证：已更新 `README.md`。
- [x] README 明确本章不做网络限制、资源配额、审计日志。验证：已更新 `README.md`。
- [x] 验收报告记录测试结果、tmux 环境状态和已知限制。验证：见 `acceptance_report.md`。

## Build and Tests

- [x] 权限相关单元测试通过。验证：权限测试组通过。
- [x] 工具、Agent、CLI、TUI 回归测试通过。验证：回归测试组通过。
- [x] 全量单元测试通过。验证：`python -m unittest discover -v`，122 tests OK。
- [x] Python 编译检查通过。验证：`python -m compileall -q huicode tests` 通过。

## End-to-End Scenarios

- [x] 场景 1：模型请求 `Bash(git reset --hard)`，即使存在 allow 规则也返回权限拒绝，Agent Loop 继续。验证：`tests.test_permissions_engine`、`tests.test_agent_loop` 通过。
- [x] 场景 2：模型请求读取 workspace 外路径或 symlink 指向外部文件，返回权限拒绝。验证：`tests.test_permissions_sandbox` 通过。
- [x] 场景 3：默认模式下未命中规则的 `Edit/Write` 类副作用调用触发确认，用户选择本会话放行后，下一次同类调用不再询问。验证：`tests.test_permissions_engine` 通过。
- [x] 场景 4：`/permissions strict` 后当前会话模式切换为严格；`/permissions permissive` 支持切换到放行模式。验证：`tests.test_cli` 通过。

## Environment Notes

- [x] tmux E2E 已检查但当前 Windows 环境不可用，已记录在验收报告。
