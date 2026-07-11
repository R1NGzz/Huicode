# HuiCode Slash Command Tasks

## T1：建立命令核心类型和接口

涉及文件：

- 新增 `huicode/commands/__init__.py`
- 新增 `huicode/commands/types.py`
- 新增 `huicode/commands/ui.py`
- 新增 `tests/test_commands_types.py`

任务：

- 定义 `CommandType`、`CommandAlias`、`CommandSpec`、`ParsedCommand`、`CommandResult`。
- 定义 `CommandUI`、`CommandServices` 和 `CommandContext` 协议/数据结构。
- 定义 handler 类型签名，避免核心类型导入 `cli.py`。
- 约束命令名不带 `/`，并提供统一规范化函数。

完成条件：

- 类型可独立导入，不产生 CLI、Rich 或 prompt_toolkit 依赖。
- 单元测试覆盖默认字段、枚举值和名称规范化。

## T2：实现命令注册中心和启动冲突检查

涉及文件：

- 新增 `huicode/commands/registry.py`
- 新增 `tests/test_commands_registry.py`

任务：

- 实现命令注册、名称/alias 查找和稳定注册顺序。
- 实现 visible command、help entry、completion entry 查询。
- 检查名称-名称、名称-alias、alias-alias、命令内部重复和大小写冲突。
- 定义 `CommandRegistrationError`，错误包含冲突 key 和双方命令。
- 拒绝空名称、带 `/` 名称和非法字符。

完成条件：

- 所有冲突场景在注册阶段失败。
- 隐藏命令与隐藏 alias 不进入 visible/completion 查询。
- 注册中心不依赖运行时服务。

## T3：实现解析器、分发器和输入路由器

涉及文件：

- 新增 `huicode/commands/parser.py`
- 新增 `huicode/commands/dispatcher.py`
- 新增 `tests/test_commands_parser.py`
- 新增 `tests/test_commands_dispatcher.py`

任务：

- 实现空输入、普通文本和斜杠命令识别。
- 命令名大小写不敏感，参数保留原始大小写和内部空格。
- 实现未知命令 `/help` 引导。
- 实现 handler 返回消息、退出请求和异常兜底。
- 实现 `InputRouter`，保证本地命令不会落入 `send_user_message()`。

完成条件：

- `/StAtUs` 正确解析为 `status`。
- `/review  Focus On API` 保留参数内容。
- 未知命令、参数错误和 handler 异常均不调用 Provider/Agent。
- 普通文本只调用一次 `send_user_message()`。

## T4：实现注册中心驱动的 Tab 补全

涉及文件：

- 新增 `huicode/commands/completion.py`
- 新增 `tests/test_commands_completion.py`

任务：

- 实现 prompt_toolkit `Completer` 适配器。
- 候选只来自 registry，不保留静态词表。
- 支持主命令和可见 alias 的大小写不敏感前缀匹配。
- completion metadata 显示描述和参数提示。
- 参数区不执行动态参数补全。

完成条件：

- 单候选、多候选和无候选行为可预测。
- 隐藏命令/alias 不产生候选。
- 补全测试不需要真实终端。

## T5：登记十个可见内置命令

涉及文件：

- 新增 `huicode/commands/builtin.py`
- 新增 `tests/test_commands_builtin.py`

任务：

- 注册 `/help`、`/compact`、`/clear`、`/plan`、`/do`、`/session`、`/memory`、`/permission`、`/status`、`/review`。
- 为每条命令填写描述、用法、类型和参数提示。
- `/help` 按三类输出，仅展示十个可见命令；支持单命令详情。
- 不接受参数的命令收到参数时返回明确用法。
- `/review` 展开固定审查提示，可选 focus 原文追加。

完成条件：

- 可见命令数量严格等于 10，顺序稳定。
- 三种 `CommandType` 都有真实命令。
- `/review` 是唯一会调用 `send_user_message()` 的可见命令。

## T6：实现模式、上下文和会话命令

涉及文件：

- `huicode/commands/builtin.py`
- 后续 `huicode/commands/runtime.py`
- `tests/test_commands_builtin.py`
- `tests/test_cli_plan_mode.py`
- `tests/test_cli_context.py`
- `tests/test_cli_memory.py`

任务：

- `/plan` 只切换 `[PLAN]` 并刷新状态，不调用 Provider。
- `/do` 只切换 `[DEFAULT]` 并刷新状态，不自动执行最近计划。
- `/compact` 复用 `ContextManager.manual_compact()`。
- `/clear` 重置 AgentState、ContextState、计划和当前 session，模式回 DEFAULT。
- `/session` 默认列表，支持 `resume <id>`、`clean` 和非法参数提示。

完成条件：

- plan/do 零 Provider 调用。
- `/do` 不产生旧的“请根据最近计划继续执行”消息。
- session 恢复继续满足坏行跳过、工具配对截断和超预算压缩规则。

## T7：实现记忆、权限和统一状态命令

涉及文件：

- `huicode/commands/builtin.py`
- 新增 `huicode/commands/runtime.py`
- `tests/test_commands_builtin.py`
- `tests/test_cli_commands.py`

任务：

- `/memory` 默认状态，支持 update/rebuild。
- `/permission` 默认状态，支持 strict/default/permissive。
- 权限切换后刷新状态栏。
- `/status` 聚合模式、Provider/model、Token/上下文、权限、MCP 和记忆状态。
- 状态输出采用白名单字段，不输出任何 secret 值。

完成条件：

- memory/permission/status 所有正常和参数错误路径 Provider 零调用。
- 记忆或 MCP 未启用时仍给出稳定状态。
- secret 构造测试确认 API key、header 和 token 值不出现在输出。

## T8：实现隐藏兼容命令

涉及文件：

- `huicode/commands/builtin.py`
- `tests/test_commands_builtin.py`
- `tests/test_cli_commands.py`

任务：

- 注册隐藏 `/sessions`、`/resume`、`/permissions`、`/perm`、`/config`、`/context`。
- 注册隐藏 `/verbose`、`/last`、`/exit`、`/quit`。
- 兼容命令委托新 handler/services，不复制领域逻辑。
- `/resume` 无参数显示列表，有参数恢复指定会话。
- exit/quit 只设置退出请求，由主循环统一关闭资源。

完成条件：

- 旧命令行为有回归测试。
- 隐藏命令不出现在 `/help` 和补全。
- 兼容入口同样不会落入 Agent Loop。

## T9：实现 CLI 运行时适配器

涉及文件：

- 新增 `huicode/commands/runtime.py`
- 修改 `huicode/cli.py`
- 新增 `tests/test_cli_commands.py`

任务：

- `CLICommandRuntime` 实现 CommandUI 和 CommandServices。
- 接入 Provider、工具 registry、ToolContext、AgentState、ContextManager、MemoryManager、MCPManager、PermissionContext。
- 将现有格式化和状态逻辑迁移或委托到 runtime。
- `send_user_message()` 复用 `_run_request()`，按 default/plan 映射 AgentMode。
- 管理 show_usage、退出请求和状态刷新回调。

完成条件：

- builtin/dispatcher 不导入 `huicode.cli`。
- runtime 可用 fake manager 测试。
- MCP/Memory 资源关闭路径保持幂等。

## T10：重构主输入循环

涉及文件：

- 修改 `huicode/cli.py`
- 修改 `tests/test_cli.py`
- 修改 `tests/test_cli_context.py`
- 修改 `tests/test_cli_memory.py`
- 修改 `tests/test_cli_plan_mode.py`

任务：

- 在初始化外部资源前创建命令 registry 并处理冲突错误。
- 创建 dispatcher、router 和 runtime。
- 每轮原始输入统一交给 router，不再提前把整行转小写。
- 删除静态 `COMMANDS` 和全部命令条件分支。
- 普通输入与 `/review` 共用 `_run_request()` 和 Agent 事件流。
- exit request 后统一关闭 MCP 和 MemoryManager。

完成条件：

- `cli.py` 不再按命令名称分支。
- 每个 LOCAL/STATE 命令及参数错误均有 Provider 零调用集成测试。
- 未知命令不进入 Agent。

## T11：接入状态栏和交互补全

涉及文件：

- 修改 `huicode/cli.py`
- 视实现需要修改 `huicode/tui.py`
- `huicode/commands/completion.py`
- `tests/test_cli_commands.py`
- `tests/test_tui.py`

任务：

- PromptSession 使用 `SlashCommandCompleter`。
- 增加 prompt_toolkit bottom toolbar，显示 `[DEFAULT]/[PLAN]`、Token、permission 和 memory。
- 模式、权限和记忆状态改变时 invalidate 状态栏。
- 无 TTY 时输入提示显示 `[DEFAULT] You>` 或 `[PLAN] You>`。
- 保持权限确认输入不被命令补全干扰。

完成条件：

- 状态栏模式标签实时联动。
- hidden command 不参与 Tab 菜单。
- 非交互测试可稳定断言模式标签。

## T12：更新系统提示和 Agent 模式衔接

涉及文件：

- 修改 `huicode/agent.py` 或模式映射位置
- 视需要修改 `huicode/prompts/builder.py`
- 修改 `tests/test_prompt_builder.py`
- 修改 `tests/test_cli_plan_mode.py`

任务：

- DEFAULT 映射现有 `chat` 执行模式。
- PLAN 映射现有 `plan` 只读模式。
- 移除命令触发的一次性 `do` 模式路径；保留底层类型仅在其他调用仍需要时使用。
- 确认 `/review` 在当前模式下进入相同 Agent Loop。

完成条件：

- `/do` 后下一条普通消息使用 chat/default。
- `/plan` 后普通消息只暴露读类工具。
- Provider 历史、thinking 和 tool_result 配对不回退。

## T13：更新文档和踩坑记录

涉及文件：

- 修改 `README.md`
- 视真实返工情况修改 `docs/mew-spec-pitfalls.md`
- 更新 `specs/011-slash-command/*`

任务：

- 说明十个可见命令、三种类型、状态栏和隐藏兼容入口。
- 明确 `/do` 新语义和 `/review` 会消耗 Token。
- 给出 `/session`、`/memory`、`/permission` 子命令示例。
- 实现中若发现 Mew Spec 漏项或真实交互返工，追加踩坑记录。

完成条件：

- README 与实际 help 输出一致。
- 文档不继续宣传旧 `/do` 自动执行行为。

## T14：完整验证与验收

涉及文件：

- 新增 `specs/011-slash-command/checklist.md`
- 新增 `specs/011-slash-command/acceptance_report.md`

任务：

- 运行命令专项测试和全量 unittest。
- 运行 compileall 和 diff check。
- 检查注册冲突、未知命令、Provider 零调用、模式切换、状态栏、补全、兼容命令和资源关闭。
- 当前环境存在 tmux 时执行真实 CLI 场景；不存在时记录限制和替代证据。

完成条件：

- checklist 全部有自动测试、命令输出或人工观察证据。
- acceptance report 记录测试数量、未执行项和风险。
- 按 `AGENT.md` 提交 Git，且不暂存用户无关文件。

## 任务依赖关系

```text
T1 -> T2 -> T3 -> T4
          -> T5 -> T6 -> T7 -> T8
T1 ---------------------> T9 -> T10 -> T11 -> T12
                                      -> T13 -> T14
```

## 实施检查点

- 检查点 A：T1-T4 完成后，核心注册/解析/分发/补全不依赖 CLI。
- 检查点 B：T5-T8 完成后，十个可见命令和隐藏兼容命令均可用 fake runtime 验证。
- 检查点 C：T9-T12 完成后，真实 CLI 只保留统一 router，模式和状态栏联动。
- 检查点 D：T13-T14 完成后，文档、验收和 Git 提交闭环。
