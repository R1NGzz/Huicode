# HuiCode Plan Mode 权限与交互修复 Spec

## Background

用户实测发现：进入 `/plan` 后，模型仍然可以请求 `Bash(echo 2 > hello.txt)` 并在用户确认后写入文件。这说明当前 Plan Mode 只限制了暴露给模型的工具列表，但没有在工具执行层强制拦截模型主动发出的非只读工具调用。用户还反馈 TUI 不显示当前模式，且 `/permissions` 切换和权限确认交互不够方便。

## Goals

- 修复 Plan Mode 可执行写入或 Bash 的漏洞。
- 让用户在 TUI 中能持续看到当前任务模式和权限模式。
- 让权限模式切换和权限确认更短、更顺手。
- 保持现有 Agent Loop、权限系统和工具系统兼容。

## Functional Requirements

- F1: Plan Mode 必须在执行层强制只允许读类工具：`Read`、`Find`、`Search`、`Glob`。
- F2: 即使模型返回未暴露的 `Bash`、`Write`、`Edit` 或其他副作用工具，Plan Mode 也必须拒绝执行。
- F3: Plan Mode 的工具拒绝应作为结构化工具结果回灌给模型，不应终止 Agent Loop。
- F4: Plan Mode 的拒绝结果应清楚说明“Plan Mode 只允许读类工具”。
- F5: TUI 在每轮开始时应显示当前任务模式，例如 `chat`、`plan`、`do`。
- F6: TUI 或 CLI 状态显示应包含当前权限模式，例如 `strict`、`default`、`permissive`。
- F7: `/permissions` 应保留原行为，同时支持更短的别名或更轻量的切换方式。
- F8: 权限确认提示应支持短输入，并在提示文本中明确列出快捷键，例如 `d/o/s/a`。
- F9: 权限确认应提供默认选项，用户直接回车时按默认拒绝处理，避免误放行。
- F10: 上述改动不应改变黑名单、路径沙箱、规则优先级和权限模式的既有语义。

## Non-Functional Requirements

- N1: Plan Mode 的限制必须由代码执行，不能只依赖提示词或工具描述。
- N2: 交互文案应简短、中文可读，并避免增加用户输入负担。
- N3: 测试应覆盖模型绕过工具列表发出 Bash 的场景。
- N4: 不引入新的第三方依赖。

## Out of Scope

- 不重新设计权限系统配置格式。
- 不新增图形界面。
- 不实现完整审计日志。
- 不改变 `/plan`、`/do` 的基本语义。
- 不实现更复杂的多步确认策略。

## Acceptance Criteria

- AC1: 在 Plan Mode 中，模型返回 `Bash(echo 2 > hello.txt)` 时，文件不会被写入，工具结果为权限/模式拒绝。
- AC2: Agent Loop 收到 Plan Mode 工具拒绝后仍能继续下一轮并给出最终回复。
- AC3: TUI 每轮开始输出包含当前任务模式。
- AC4: 权限确认提示包含 `d/o/s/a` 快捷键和默认拒绝说明。
- AC5: `/permissions` 原命令仍可用，新增快捷方式测试通过。
- AC6: 权限系统既有测试、Agent Loop 测试、CLI/TUI 测试和全量测试通过。
