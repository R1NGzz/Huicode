# HuiCode Slash Command 验收报告

## 结果概览

通过。HuiCode 已建立统一 Slash Command 注册、解析、分发、补全和运行时适配机制。十个公开命令、隐藏兼容入口、`[DEFAULT]/[PLAN]` 模式展示和 `/review` 提示词命令均接入现有 Agent、Context、Memory、Permission 和 MCP 能力。

## 核心架构

- [x] 新增独立 `huicode.commands` 包。
  - 证据：包含 types、registry、parser、dispatcher、completion、builtin、runtime 七个模块。

- [x] registry 是命令元数据、帮助、补全和分发的唯一真相源。
  - 证据：`huicode/cli.py` 已删除静态 `COMMANDS` 和所有 `command ==` / `command.startswith` 命令分支。

- [x] 命令处理器通过 CommandUI 和 CommandServices 工作。
  - 证据：`tests.test_commands_builtin` 使用 fake runtime 完成全部 handler 测试，不依赖 Rich 或真实 PromptSession。

## 注册与解析

- [x] 命令名、alias 和大小写冲突在注册阶段失败。
  - 证据：`python -m unittest tests.test_commands_registry -v` 通过，覆盖名称-名称、名称-alias、alias-alias 和内部重复。

- [x] 非法命令名在启动前被拒绝。
  - 证据：空名称、斜杠、空格和非约定字符均有测试。

- [x] CLI 在启动外部服务前处理 registry 致命错误。
  - 证据：`test_registration_failure_happens_before_chat_loop` 返回退出码 2，Provider 调用为 0。

- [x] 命令名大小写不敏感，参数原始大小写保留。
  - 证据：`tests.test_commands_parser` 覆盖 `/ReView Focus On API`。

- [x] 未知命令不会进入 Agent。
  - 证据：`test_unknown_and_invalid_commands_do_not_call_provider` 确认 Provider 调用次数为 0，并输出 `/help` 引导。

## 十个公开命令

- [x] `/help`、`/compact`、`/clear`、`/plan`、`/do`、`/session`、`/memory`、`/permission`、`/status`、`/review` 已登记。
  - 证据：`test_registers_exactly_ten_visible_commands_with_all_types` 确认可见命令严格为 10。

- [x] `/help` 按本地、状态、提示词分组，并支持单命令详情。
  - 证据：`tests.test_commands_builtin` 通过；隐藏命令不出现在帮助中。

- [x] `/plan` 只进入 `[PLAN]`，`/do` 只返回 `[DEFAULT]`。
  - 证据：`tests.test_cli_plan_mode` 通过；`/do` 不再注入最近计划或自动调用 Provider。

- [x] `/session` 统一列表、恢复和清理。
  - 证据：`tests.test_cli_memory` 和 builtin 参数矩阵通过。

- [x] `/memory` 统一状态、更新和索引重建。
  - 证据：`test_memory_update_and_rebuild_commands` 通过。

- [x] `/permission` 查看和切换 strict/default/permissive。
  - 证据：主命令 handler 和隐藏旧入口回归测试通过。

- [x] `/status` 聚合模式、Provider、上下文/Token、权限、MCP 和记忆。
  - 证据：CLI 集成输出包含全部栏目，构造的 API key 和 header secret 未出现。

- [x] `/review [focus]` 展开固定审查提示并进入当前 Agent 模式。
  - 证据：`test_review_expands_prompt_and_uses_current_mode` 在 `[PLAN]` 下收到固定 prompt、保留 focus，且只暴露读类工具。

## Provider 零调用

- [x] LOCAL/STATE 命令不进入 Agent Loop。
  - 证据：`test_local_and_state_commands_do_not_call_provider` 连续运行 help/plan/do/session/memory/permission/status/clear 后 Provider 调用次数为 0。

- [x] 参数错误和未知命令不调用 Provider。
  - 证据：plan/session/permission 非法参数矩阵调用次数为 0。

- [x] `/review` 是十个公开命令中唯一通过 `send_user_message` 进入 Agent 的命令。
  - 证据：builtin fake runtime 记录 `/review` 一次 send，其他命令为 0。

- [x] `/compact` 复用摘要 Provider，但不创建普通用户轮次或工具 Agent Loop。
  - 证据：`tests.test_cli_context` 通过，手动压缩产生 ContextManager 摘要结果。

## 补全与状态栏

- [x] Tab 候选由 registry 动态生成。
  - 证据：`tests.test_commands_completion` 覆盖单匹配、多匹配、大小写匹配和参数区。

- [x] 隐藏命令和隐藏 alias 不参与补全。
  - 证据：completion 测试确认 `/resume` 不在候选；PromptSession 集成测试确认使用 `SlashCommandCompleter`。

- [x] PromptSession 接入 bottom toolbar。
  - 证据：`test_prompt_session_uses_registry_completer_and_toolbar` 通过。

- [x] 权限确认输入不继承 Slash Command 补全。
  - 证据：`test_permission_confirmation_disables_command_completion` 确认 confirmer 传入 `completer=None` 和 `complete_while_typing=False`。

- [x] 非 TTY 输入提示联动 `[DEFAULT]/[PLAN]`。
  - 证据：`test_non_tty_prompt_tracks_mode` 依次观察 DEFAULT、PLAN、DEFAULT。

- [x] 状态栏包含 Token、permission 和 memory 状态。
  - 证据：`CLICommandRuntime.toolbar_text()` 使用 ContextState、PermissionContext 和 MemoryRuntimeState 生成。

## 隐藏兼容入口

- [x] `/sessions`、`/resume`、`/permissions`、`/perm` 保持兼容。
- [x] `/config`、`/context`、`/verbose`、`/last` 保持兼容。
- [x] `/exit`、`/quit` 通过统一 dispatcher 请求退出并由主循环关闭资源。
  - 证据：原有 CLI、Context、Memory、Permission 和 MCP 测试全部通过；隐藏入口不出现在 help 或 completion。

## 构建与回归

- [x] 命令核心与 builtin 专项测试通过。
  - 证据：types、registry、parser、dispatcher、completion、builtin、CLI command 测试全部通过。

- [x] 全量单元测试通过。
  - 证据：`python -m unittest discover -v` 通过，253 个测试全部 OK。

- [x] README 已更新。
  - 证据：新增 Slash Command 章节，更新 Plan Mode、记忆命令和交互命令；明确隐藏兼容入口和 `/review` Token 行为。

## 未执行项

- tmux 真实端到端验收未执行。
  - 原因：当前 Windows PowerShell 环境检测结果为 `tmux-unavailable`。
  - 替代证据：真实 `_run_chat()` 集成测试覆盖输入分流、模式切换、Provider 零调用、review 展开、会话恢复、权限切换、MCP 工具和资源关闭；prompt_toolkit completer/toolbar 使用适配测试覆盖。

## 语义变更

- `/plan <task>` 不再接受内联任务；使用 `/plan` 后再输入普通任务。
- `/do <task>` 和自动执行最近计划已移除；`/do` 只返回 `[DEFAULT]`。
- `/session`、`/permission`、`/status` 成为公开主入口。
- 旧命令暂时作为隐藏兼容入口保留，未来破坏性版本可以移除。
