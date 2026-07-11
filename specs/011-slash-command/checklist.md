# HuiCode Slash Command 验收清单

> 每一项必须通过单元测试、集成测试、命令输出或真实交互证据验证。实现完成后把证据记录到本章 `acceptance_report.md`。

## 注册中心与元数据

- [ ] 命令定义包含名称、别名、描述、用法、类型、参数提示、隐藏标记和处理函数。
  - 验证：运行 `python -m unittest tests.test_commands_types tests.test_commands_builtin -v`，检查十个可见命令字段完整。

- [ ] 命令类型支持 LOCAL、STATE、PROMPT 三类。
  - 验证：运行 `python -m unittest tests.test_commands_types tests.test_commands_builtin -v`，确认三类均有命令实例。

- [ ] 注册中心按名称和 alias 大小写不敏感查找命令。
  - 验证：运行 `python -m unittest tests.test_commands_registry -v`，确认 `/STATUS`、alias 和主名称解析到同一命令。

- [ ] 名称与名称冲突会在注册阶段失败。
  - 验证：注册 `status` 和 `STATUS`，确认抛出 `CommandRegistrationError`。

- [ ] 名称与 alias、alias 与 alias 冲突会在注册阶段失败。
  - 验证：运行 `python -m unittest tests.test_commands_registry -v`，确认错误包含冲突 key 和双方命令。

- [ ] 同一命令内部重复 alias 或 alias 等于主名称会被拒绝。
  - 验证：运行 registry 专项测试，确认不会把无效命令带入交互循环。

- [ ] 非法空名称、带 `/` 名称和非法字符名称会被拒绝。
  - 验证：运行 registry 专项测试，确认错误信息可定位字段。

- [ ] CLI 在外部资源启动前完成命令注册冲突检查。
  - 验证：注入冲突 registry 启动 `_run_chat()`，确认返回退出码 2，MCP 和 MemoryManager 未启动。

## 解析与分流

- [ ] 空字符串和全空白输入被忽略。
  - 验证：运行 `python -m unittest tests.test_commands_parser tests.test_commands_dispatcher -v`，确认不显示错误且不发送消息。

- [ ] 普通文本不被解析为命令。
  - 验证：输入 `review this code`，确认 router 只调用一次 `send_user_message()`。

- [ ] 只有第一个非空字符为 `/` 的输入进入命令解析。
  - 验证：覆盖前导空格、普通文本中间斜杠和裸 `/`。

- [ ] 命令名大小写不敏感。
  - 验证：输入 `/StAtUs`，确认命中 `status`。

- [ ] 参数保留原始大小写和内部空格。
  - 验证：输入 `/review  Focus On API`，确认 focus 中 `Focus On API` 未被转小写。

- [ ] 未知命令不进入 Agent Loop。
  - 验证：输入 `/unknown`，确认输出未知命令和 `/help` 引导，fake Provider 调用次数为 0。

- [ ] 本地命令参数错误不进入 Agent Loop。
  - 验证：输入 `/plan extra`、`/session bad`、`/permission wild`，确认只显示用法，Provider 调用次数为 0。

- [ ] handler 未预期异常不会终止 CLI。
  - 验证：fake handler 抛异常后继续输入第二条命令，确认仍能执行。

- [ ] `cli.py` 不再维护静态命令词表和按命令名称展开的长条件分支。
  - 验证：代码检查确认帮助、补全和分发都读取 registry。

## 界面控制接口

- [ ] 命令处理器只依赖 CommandUI、CommandServices 和 CommandContext。
  - 验证：builtin、dispatcher 测试使用 fake UI/services，不创建 Rich 或 PromptSession。

- [ ] CommandUI 支持显示消息、发送用户消息、切换模式、查询 Token 和刷新状态。
  - 验证：运行 `python -m unittest tests.test_commands_types tests.test_commands_builtin -v`。

- [ ] builtin 和 dispatcher 不导入 `huicode.cli`。
  - 验证：静态检查模块依赖，并运行独立导入测试。

- [ ] 命令异常统一转换为中文错误。
  - 验证：fake handler 抛 `RuntimeError`，输出包含命令名和错误信息。

## 帮助与补全

- [ ] `/help` 只展示十个可见高频命令。
  - 验证：输出包含 help/compact/clear/plan/do/session/memory/permission/status/review，数量为 10。

- [ ] `/help` 按本地、状态、提示词三类分组。
  - 验证：运行 `python -m unittest tests.test_commands_builtin -v`。

- [ ] `/help <command>` 展示名称、说明、用法、类型和参数提示。
  - 验证：输入 `/help review` 和 `/help permission` 检查字段。

- [ ] 隐藏兼容命令不出现在 `/help`。
  - 验证：确认 resume/sessions/perm/config/context/verbose/last/exit/quit 不在默认帮助中。

- [ ] Tab 候选来自 registry，代码中没有第二份静态列表。
  - 验证：动态注册测试命令后，completer 自动出现该候选。

- [ ] 补全大小写不敏感。
  - 验证：`/HE` 能补全 `/help`。

- [ ] 单匹配能直接完成，多匹配能返回完整菜单候选。
  - 验证：运行 `python -m unittest tests.test_commands_completion -v`，检查 `/rev` 和 `/s` 候选。

- [ ] 隐藏命令和隐藏 alias 不参与补全。
  - 验证：completion entries 不包含 `/resume`、`/quit` 等隐藏入口。

- [ ] 进入参数区后不做动态参数补全。
  - 验证：`/review api` 光标位于参数区时不返回命令候选。

## 模式与状态栏

- [ ] 启动默认模式显示 `[DEFAULT]`。
  - 验证：真实 PromptSession bottom toolbar 或非 TTY 输入提示包含 `[DEFAULT]`。

- [ ] `/plan` 立即切换到 `[PLAN]` 并刷新状态。
  - 验证：fake UI 记录 set_mode/refresh 调用；集成输出显示 `[PLAN]`。

- [ ] `/plan` 本身不调用 Provider。
  - 验证：输入 `/plan` 后立即 `/exit`，fake Provider 调用次数为 0。

- [ ] `[PLAN]` 下普通消息使用现有只读 Plan Mode。
  - 验证：下一条普通请求只暴露 Read、Find、Search、Glob，副作用工具被执行层拒绝。

- [ ] `/do` 只切换回 `[DEFAULT]`。
  - 验证：输入 `/do` 后状态栏恢复 `[DEFAULT]`。

- [ ] `/do` 不自动执行最近计划，也不调用 Provider。
  - 验证：预置 `state.last_plan` 后输入 `/do`，确认没有生成“请根据最近计划继续执行”消息。

- [ ] 非 TTY 回退输入也显示模式标记。
  - 验证：mock `input()` 检查 prompt 文本从 `[DEFAULT] You>` 切到 `[PLAN] You>`。

- [ ] 状态栏显示 Token、permission 和 memory 简要状态。
  - 验证：构造 usage、权限模式和 pending memory，检查 toolbar 文本。

## 十个可见命令

- [ ] `/compact` 直接调用现有手动压缩流程。
  - 验证：fake ContextManager 记录一次 compact，Provider 仅用于摘要而不进入 Agent Loop。

- [ ] `/clear` 清空消息、计划和 ContextState，并开启新 session。
  - 验证：旧 session 和长期记忆仍存在，模式恢复 DEFAULT。

- [ ] `/session` 默认列出可恢复会话。
  - 验证：输出包含 ID、标题、更新时间和消息数，Provider 调用次数为 0。

- [ ] `/session resume <id>` 恢复指定会话。
  - 验证：恢复后下一条普通请求包含历史消息，并继续追加同一 JSONL。

- [ ] `/session clean` 清理过期非活动会话。
  - 验证：活动 session 保留，输出清理数量。

- [ ] `/memory` 默认显示记忆状态。
  - 验证：输出包含 session、笔记、索引、pending 和最近错误，不泄露 secret。

- [ ] `/memory update` 和 `/memory rebuild` 正常工作。
  - 验证：update 使用 no-tool Provider 调用；rebuild 不进入 Agent Loop。

- [ ] `/permission` 默认显示模式和规则摘要。
  - 验证：输出包含 mode、规则总数和来源。

- [ ] `/permission strict|default|permissive` 切换模式并刷新状态。
  - 验证：三个模式逐一测试，非法模式显示用法。

- [ ] `/status` 聚合模式、Provider、上下文/Token、权限、MCP 和记忆。
  - 验证：运行 `python -m unittest tests.test_cli_commands -v`，检查所有栏目。

- [ ] `/status` 不泄露 API key、header、MCP secret 或记忆正文。
  - 验证：注入 `test-secret` 后确认输出不存在该值。

- [ ] `/review` 发送固定代码审查提示词。
  - 验证：fake UI 收到缺陷、回归、安全风险和缺失测试要求。

- [ ] `/review <focus>` 把 focus 原文追加到固定提示词。
  - 验证：输入 `/review Focus On API`，检查展开提示词包含原文。

- [ ] `/review` 复用当前 Agent Loop、模式、权限、记忆和会话记录。
  - 验证：在 DEFAULT 和 PLAN 下各运行一次，确认只产生一条展开后的用户消息并走对应工具集。

## 隐藏兼容命令

- [ ] `/sessions` 兼容 `/session` 列表，`/sessions clean` 兼容清理。
  - 验证：旧命令输出和主命令一致。

- [ ] 裸 `/resume` 显示列表，`/resume <id>` 兼容恢复。
  - 验证：两种路径 Provider 零误调用，恢复后的普通消息使用历史。

- [ ] `/permissions` 和 `/perm` 兼容 `/permission`。
  - 验证：查看和三种模式切换结果一致。

- [ ] `/config` 兼容统一状态入口且不泄露 secret。
  - 验证：旧命令由 registry 分发，不保留 CLI 特判。

- [ ] `/context` 保留上下文详细摘要。
  - 验证：输出 window、margin、usage anchor、summary 和 fuse。

- [ ] `/verbose` 保留用量显示开关。
  - 验证：切换前后 usage 事件显示行为一致。

- [ ] `/last [count]` 保留最近工具结果展开。
  - 验证：无结果、默认 1 条、指定数量和非法数量均有测试。

- [ ] `/exit` 和 `/quit` 安全关闭资源。
  - 验证：MCP、MemoryManager、session recorder 被关闭，重复关闭不异常。

## Provider 零调用边界

- [ ] `/help`、`/clear`、`/plan`、`/do`、`/session`、`/permission`、`/status` 不调用 Provider。
  - 验证：每条命令独立运行，fake Provider 调用次数为 0。

- [ ] `/memory` 状态和 rebuild 不调用 Provider。
  - 验证：只有明确 `/memory update` 可以发起 no-tool 记忆整理请求。

- [ ] `/compact` 不进入 Agent Loop。
  - 验证：即使摘要会使用 Provider，也没有 user turn、工具调用或 Agent 迭代事件。

- [ ] `/review` 是十个可见命令中唯一进入 Agent 的命令。
  - 验证：按命令矩阵统计 send_user_message 调用。

- [ ] 未知命令和所有参数错误路径不调用 Provider。
  - 验证：运行 dispatcher/CLI 集成参数矩阵。

## 构建与回归

- [ ] 命令专项测试全部通过。
  - 验证：运行 `python -m unittest tests.test_commands_types tests.test_commands_registry tests.test_commands_parser tests.test_commands_dispatcher tests.test_commands_completion tests.test_commands_builtin tests.test_cli_commands -v`。

- [ ] 现有 CLI、Plan、Context、Memory、Permission、MCP 测试通过。
  - 验证：运行相关 `tests.test_cli*`、`tests.test_agent_loop`、`tests.test_mcp_*` 和权限测试。

- [ ] OpenAI 和 Anthropic 工具历史序列没有回退。
  - 验证：运行 `python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v`。

- [ ] 全量单元测试通过。
  - 验证：运行 `python -m unittest discover -v`。

- [ ] Python 文件编译通过。
  - 验证：运行 `python -m compileall -q huicode tests`。

- [ ] Git diff 检查通过。
  - 验证：运行 `git diff --check`，仅允许已有换行提示，不允许空白错误。

- [ ] README 与实际 `/help` 输出一致。
  - 验证：逐项对照十个可见命令、子命令、模式标签和隐藏兼容说明。

## 端到端场景

- [ ] 场景 1：启动后状态栏显示 `[DEFAULT]`，输入 `/help` 不调用模型。
- [ ] 场景 2：输入 `/plan` 后显示 `[PLAN]`，普通任务只使用读类工具。
- [ ] 场景 3：输入 `/do` 后恢复 `[DEFAULT]`，不自动执行任何计划。
- [ ] 场景 4：输入 `/session` 展示会话，`/session resume <id>` 后继续对话。
- [ ] 场景 5：输入 `/permission permissive` 后状态栏立即更新。
- [ ] 场景 6：输入 `/status` 能看到完整摘要且没有 secret。
- [ ] 场景 7：输入 `/review Provider 序列` 后 Agent 收到展开提示并开展只读审查。
- [ ] 场景 8：输入未知 `/wat` 只出现帮助引导，不思考、不调用工具、不消耗 Token。
- [ ] 场景 9：Tab 输入 `/rev` 单匹配补全；输入 `/s` 显示多个可见候选菜单。
- [ ] 场景 10：旧 `/resume <id>`、`/perm`、`/context` 仍可使用，但不出现在帮助和补全中。

## 验收项映射

| Spec AC | 清单范围 |
| --- | --- |
| AC1 | 注册中心与元数据 |
| AC2-AC4 | 解析与分流 |
| AC5 | 界面控制接口 |
| AC6-AC7 | 帮助与补全 |
| AC8 | 模式与状态栏 |
| AC9 | 十个可见命令、Provider 零调用 |
| AC10-AC12 | session、memory、permission、隐藏兼容 |
| AC13 | `/status` 和 secret 检查 |
| AC14 | `/review` |
| AC15 | `/do` 新语义 |
| AC16 | exit/quit 资源关闭 |
| AC17 | 构建与回归、端到端 |
| AC18 | README、checklist、acceptance report |
