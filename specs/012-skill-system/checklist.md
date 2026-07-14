# HuiCode Skill System 验收清单

> 每项必须用自动测试、命令输出或真实交互证据验证。实现完成后将实际结果记录到本章 `acceptance_report.md`，不能只填写预期行为。

## 文件格式与安全解析

- [ ] 单文件 `<name>.md` 能解析为完整 Skill 定义。
  - 验证：运行 `python -m unittest tests.test_skills_parser -v`，检查全部 frontmatter 字段和正文。

- [ ] 目录型 `<package>/SKILL.md` 能解析，root 指向能力包目录。
  - 验证：临时目录放置入口、模板和参考文件，确认只有 `SKILL.md` 被当作入口。

- [ ] `name`、`description`、`allowed_tools`、`mode`、`history_messages` 和 `model` 执行严格类型与取值校验。
  - 验证：逐字段构造缺失、错误类型、非法枚举、负数和非法名称，确认只跳过该 Skill 并给出路径与原因。

- [ ] 缺失 frontmatter 边界、YAML 语法错误和空正文不会阻断其他 Skill。
  - 验证：一个目录同时放置坏文件与有效文件，确认有效文件仍进入 catalog，skipped/warnings 正确增加。

- [ ] frontmatter 使用安全 YAML 解析，不能构造任意 Python 对象。
  - 验证：使用危险 YAML tag，确认解析失败且没有执行副作用。

- [ ] `{{args}}` 只做字面替换并保留原始大小写、换行和特殊字符。
  - 验证：传入 `Focus On API {{x}}`，确认只替换 `{{args}}`，不解释其他模板或脚本内容。

- [ ] 单文件和目录型入口不能通过符号链接或真实路径逃出对应 skills 根目录。
  - 验证：运行 `python -m unittest tests.test_skills_discovery -v`，覆盖入口链接、目录链接和辅助文件链接逃逸。

- [ ] PyYAML 被声明为运行时依赖，缺失时错误信息明确。
  - 验证：检查 `pyproject.toml` 包含 `PyYAML>=6`，并测试导入失败路径不会退化为不完整解析。

## 三级发现与覆盖

- [ ] Skill 来源优先级为项目级高于用户级高于内置。
  - 验证：三层创建同名 Skill，确认项目版本生效；移除项目版本后用户版本生效，再移除后回退内置。

- [ ] 同一层多个文件声明相同 name 时，该层冲突候选全部跳过并报告 warning。
  - 验证：项目层放置两个同名 Skill，确认可回退用户或内置版本。

- [ ] 单文件解析失败不阻止其他有效 Skill 和低层 fallback。
  - 验证：运行 discovery/catalog 专项测试，检查 effective、overridden、skipped 和 warnings 计数。

- [ ] 目录型 Skill 的模板、示例、辅助脚本或参考文档变化能改变热更新指纹。
  - 验证：只修改辅助文件，不修改 `SKILL.md`，确认下一次顶层输入触发 reload。

- [ ] 启动 catalog 不读取或注入辅助文件正文。
  - 验证：辅助文件放置唯一哨兵文本，检查启动 Prompt 和状态输出中不存在该文本。

## 两阶段加载与 Prompt

- [ ] 未激活时 Prompt 只包含每个 Skill 的 name、description、mode。
  - 验证：运行 Prompt 专项测试，确认 SOP、allowed_tools、model、root 和辅助文件正文均不出现。

- [ ] 轻量 catalog 使用动态、不可缓存的系统级补充模块，不伪装成用户输入。
  - 验证：检查 PromptBundle 模块属性和 Provider 生成的消息结构。

- [ ] 模型可调用系统工具 `Skill(name, arguments)` 加载完整指令。
  - 验证：fake Provider 首轮返回 Skill tool call，下一轮 Prompt 包含渲染后的 SOP。

- [ ] active Skill 完整 SOP 位于动态补充上下文最前，早于环境、模式、记忆和普通 catalog。
  - 验证：断言 PromptBundle supplemental_modules 顺序及标签属性。

- [ ] active SOP 不写入用户消息、不进入稳定缓存、不被上下文摘要改写。
  - 验证：检查 messages、stable_modules 和压缩前后 Prompt；正文哨兵只存在于 active block。

- [ ] 同名 Skill 重复激活只替换参数和正文，不重复堆叠。
  - 验证：连续激活两次，active 数量保持 1，顺序不变，正文使用第二次参数。

- [ ] 多个不同 shared Skill 能按首次激活顺序同时保持。
  - 验证：激活两个 Skill 后经过普通轮次、工具结果回灌和一次上下文压缩，两个 block 均仍存在。

## Catalog 校验与工具白名单

- [ ] allowed_tools 支持工具主名和 alias，并统一规范为主名。
  - 验证：使用 `Glob` 等 alias，确认最终限制落到对应注册工具。

- [ ] allowed_tools 可以引用已成功注册的 MCP 工具。
  - 验证：fake MCP 注册工具后构建 catalog 成功，并能在 Skill 中调用。

- [ ] 未知本地或 MCP 工具导致启动失败，错误包含 Skill name、入口文件和缺失工具。
  - 验证：CLI 启动集成测试确认退出码 2，且不泄露正文或 secret。

- [ ] MCP Server 失败导致白名单工具缺失时同样启动失败，不静默扩大工具集。
  - 验证：模拟 MCP 连接失败，确认 Skill 配置错误而非忽略 allowed_tools。

- [ ] chat/do 下普通工具为基础集合与所有 active shared Skill 白名单的交集。
  - 验证：两个白名单部分重叠的 Skill 同时激活，模型只看到交集工具。

- [ ] Plan Mode 再与只读工具集合取交集。
  - 验证：Skill 白名单含 Write/Bash 时进入 Plan Mode，暴露列表和执行前检查均拒绝副作用工具。

- [ ] Skill 白名单不能绕过路径沙箱、危险命令黑名单、权限规则和人在回路。
  - 验证：通过 Skill 尝试越界 Read、危险 Bash 和需要确认的写操作，结果与普通 Agent 一致。

- [ ] allowed_tools 为空时不暴露任何普通工具。
  - 验证：模型仍能返回文本或加载其他 Skill，但不能调用 Read/Bash 等普通工具。

- [ ] 系统级 `Skill` 工具在空白名单、Plan Mode 和多 Skill 交集下始终可见。
  - 验证：运行 `tests.test_skills_tool` 与 Agent 工具选择矩阵。

## Shared 执行模式

- [ ] shared Skill 使用当前 AgentState 和主消息历史继续执行。
  - 验证：Skill 激活前后的用户消息、tool call、tool result 和 final 均保留在同一 state/session。

- [ ] 模型通过 Skill 工具激活 shared Skill 后，下一轮请求才应用完整 SOP 和白名单。
  - 验证：第一轮工具结果与第二轮请求紧邻，第二轮工具列表已收窄。

- [ ] Slash Command 调用 shared Skill 时，arguments 同时用于 SOP 渲染和当前任务消息。
  - 验证：输入大小写混合参数，fake Provider 收到原文任务且 Prompt 中占位符替换一致。

- [ ] shared Skill 指定 model 时，只从激活后的下一次请求覆盖当前顶层轮。
  - 验证：fake provider factory 记录模型序列，激活请求使用主模型，后续请求使用覆盖模型。

- [ ] shared 顶层轮 final、错误、取消或迭代上限后恢复主模型。
  - 验证：四条停止路径后发送普通消息，均确认使用主配置 model。

- [ ] model 覆盖只替换模型名，其他连接、thinking 和上下文配置沿用主配置。
  - 验证：逐字段比较复制配置，并确认错误输出不包含 api_key/header。

## Isolated 执行模式

- [ ] isolated Skill 创建独立 AgentState、消息历史和上下文计数。
  - 验证：子循环结束后主 state 的 iterations/context 不包含子循环内部值。

- [ ] history_messages 从主历史尾部选择，并扩展到完整协议消息组。
  - 验证：边界落在 tool call/result 中间时自动扩展或舍弃，不产生孤立块。

- [ ] `history_messages: 0` 不带主对话历史，仅注入任务、SOP 和环境摘要。
  - 验证：主历史放置唯一哨兵，子 Provider 请求中不存在该哨兵。

- [ ] isolated 工具集为父级模式与目标 Skill 白名单的交集，并保留系统 Skill 工具。
  - 验证：chat、plan 和嵌套场景分别检查 Provider tools。

- [ ] isolated model 覆盖整个子会话，主 Provider 不被修改。
  - 验证：子循环多次请求均使用指定模型，返回主对话后使用主模型。

- [ ] isolated 自然结束时只把最终摘要回流主历史。
  - 验证：主历史/session 不包含子会话内部 thinking、普通 tool calls 或 tool results。

- [ ] 模型触发 isolated Skill 时，摘要作为对应 tool call 的紧邻 ToolResult 回流。
  - 验证：检查 call id、tool name、消息顺序和 Provider 序列化结果。

- [ ] Slash Command 触发 isolated Skill 时，主历史只记录一条 Skill 请求和一条 assistant 摘要。
  - 验证：恢复 JSONL session 后仍能看到请求与摘要，子过程未被复制。

- [ ] 子会话错误、取消、未知工具、迭代上限均作为结构化失败回流，主 Agent 不崩溃。
  - 验证：逐一注入停止原因，下一轮主 Agent 仍可根据失败结果继续调整。

- [ ] Skill 嵌套最大深度为 3，超限返回 `nested_depth_exceeded`。
  - 验证：构造四层调用，确认第四层不启动 Provider 且主循环继续可用。

- [ ] isolated 默认只显示开始、结束和摘要，不把每条 thinking 灌入主 TUI。
  - 验证：fake 子 Provider 输出多段 thinking，主渲染事件中不存在这些正文。

## Slash Command 与内置 Skill

- [x] `/skill` 列出有效 Skill、mode、source 和 active 标记，`/skill <name>` 显示详情且 Provider 调用为 0。
  - 验证：用真实 Python 启动后执行 `/skill` 和 `/skill frontend-design`，并运行 CLI 集成测试。

- [ ] 每个有效 Skill 自动注册为可见 `/<name> [arguments]`。
  - 验证：运行 `python -m unittest tests.test_skills_commands -v`，检查命令类型、描述、usage 和参数提示。

- [ ] `/help` 动态列出当前有效 Skill，Tab 补全使用同一目录快照。
  - 验证：新增 Skill 后下一次输入中 help 与 completion 同时出现；删除后同时消失。

- [ ] Skill 参数保留用户原始大小写和内部空格。
  - 验证：输入 `/review Focus On API`，Runner 和渲染正文均收到 `Focus On API`。

- [ ] Skill 名与核心公开命令、隐藏兼容命令或 alias 冲突时启动失败。
  - 验证：分别使用 `help`、`resume`、`perm` 构造冲突并确认退出码 2。

- [ ] 硬编码 `REVIEW_PROMPT` 和旧 `/review` handler 已移除。
  - 验证：代码搜索与命令测试确认 `/review` 来源为有效 review Skill。

- [ ] 项目级或用户级 review 可覆盖内置 review。
  - 验证：依次添加上层 review，检查 `/help` 描述、SOP 和执行模式来自高优先级版本。

- [ ] 内置 commit 是 shared，白名单为 Read/Bash，并继续经过提交权限确认。
  - 验证：解析元数据并用 fake PermissionConfirmation 运行样板流程。

- [ ] 内置 review 是 isolated/history 12，白名单为 Read/Find/Search/Bash。
  - 验证：运行 catalog 和 isolated runner 测试，确认只读审查输出。

- [ ] 内置 test 是 isolated/history 6，白名单为 Read/Find/Search/Bash。
  - 验证：fake 项目运行测试，摘要包含命令、结果和剩余风险。

## 热更新与生命周期

- [ ] 无文件变化时热更新检查快速返回，不解析文件、不调用 Provider。
  - 验证：spy parser/provider 调用次数均为 0。

- [ ] 新增、修改、删除 Skill 后在下一次顶层输入分流前刷新 catalog、命令和 active state。
  - 验证：分别执行三类文件操作，确认本次输入使用新快照而不是下一次才生效。

- [ ] 已激活 Skill 更新后保留原 arguments 并重新渲染正文。
  - 验证：修改 SOP 后触发 reload，active 顺序不变且新正文含旧参数。

- [ ] 已激活 Skill 删除后优先切换低层 fallback；无 fallback 时停用并 warning。
  - 验证：覆盖存在和不存在两种删除路径。

- [ ] 热更新遇到未知工具或命令冲突时，catalog、命令和 active state 全部保留旧快照。
  - 验证：检查 generation 不变，旧 Skill 仍能执行，`/status` 显示 reload error。

- [ ] 单个新文件解析失败只跳过该文件，其他合法变化仍能发布。
  - 验证：同一次 reload 同时新增一个合法 Skill 和一个坏文件，合法 Skill 生效并产生 warning。

- [ ] `/clear` 清除 active Skills、工具限制和轮次模型覆盖。
  - 验证：clear 后 Agent 工具恢复当前基础模式集合，active 计数为 0。

- [ ] `/clear` 不删除 Skill 文件或 catalog，之后仍可再次运行 Skill 命令。
  - 验证：clear 后 `/help` 仍显示 Skill，重新调用能正常激活。

## 状态与信息安全

- [ ] 启动摘要显示 effective、overridden、skipped 和 warnings 数量。
  - 验证：构造覆盖与坏文件后检查启动输出，不显示完整 SOP。

- [ ] `/status` 显示 discovered、active、reload errors 和当前工具限制摘要。
  - 验证：未激活、已激活和 reload 失败三种状态输出稳定。

- [ ] Skill 工具行显示 name、mode 和来源层级，不打印完整 SOP。
  - 验证：TUI 快照或渲染测试使用 SOP 哨兵确认不可见。

- [ ] warning、ToolResult、isolated 摘要和状态不泄露 API key、headers、完整隐藏 SOP 或敏感辅助文件正文。
  - 验证：注入统一 `test-secret` 哨兵后检查所有可见输出。

## Provider 协议与回归

- [ ] Anthropic shared Skill 调用保持 `tool_use` 后紧邻对应 `tool_result`。
  - 验证：运行 `python -m unittest tests.test_anthropic_provider_tools tests.test_skills_tool -v`。

- [ ] Anthropic isolated Skill 摘要回流保持 call id 和工具配对合法。
  - 验证：序列化消息后不存在无结果 `tool_use`，兼容 DeepSeek Anthropic 接口要求。

- [ ] Anthropic extended thinking 在 shared 和 isolated 后续请求中按原协议回传。
  - 验证：有 thinking/signature 的 assistant tool call 经 Skill 流程后仍完整保留。

- [ ] OpenAI shared/isolated Skill 保持 assistant tool_calls 与 tool 消息配对合法。
  - 验证：运行 `python -m unittest tests.test_openai_provider_tools tests.test_skills_runner -v`。

- [ ] Skill 回流后上下文轻量外置和重量摘要不会切断工具消息组。
  - 验证：构造大 ToolResult 触发两层压缩，下一次 Provider 请求序列合法。

- [ ] 记忆自动更新不记录 isolated 子循环内部消息，也不请求额外权限。
  - 验证：自然 final 后检查 memory 输入仅含主请求与摘要，权限确认次数无新增。

- [ ] MCP、权限、Plan Mode、上下文、记忆和 Slash Command 现有测试没有回归。
  - 验证：运行对应测试模块与全量测试。

## 构建与文档

- [ ] Skill 专项测试全部通过。
  - 验证：运行所有 `tests.test_skills_*` 和 `tests.test_cli_skills`。

- [ ] 全量单元测试通过。
  - 验证：运行 `python -m unittest discover -v`，记录测试数量和耗时。

- [ ] Python 编译检查通过。
  - 验证：运行 `python -m compileall -q huicode tests`。

- [ ] Git diff 检查通过。
  - 验证：运行 `git diff --check`，不存在新增空白错误。

- [ ] README 与实现一致。
  - 验证：逐项对照格式、目录、优先级、两阶段加载、执行模式、白名单、命令、热更新和三个内置 Skill。

- [ ] Git 提交只包含本章相关文件。
  - 验证：提交前检查 `git status --short` 和 staged diff，不包含用户旧的未跟踪文件。

## 端到端场景

- [ ] 场景 1：启动后摘要显示三个内置 Skill，`/help` 和 Tab 均出现 commit/review/test，普通 Prompt 不包含其 SOP。
- [ ] 场景 2：创建项目级 shared Skill，输入对应 Slash Command 后 SOP 激活、工具收窄，最终消息留在主历史。
- [ ] 场景 3：输入 `/review Provider 序列`，isolated 子会话只读调查，主界面只显示开始、结束和审查摘要。
- [ ] 场景 4：同时激活两个 shared Skill，模型只能看到白名单交集；进入 `/plan` 后进一步只保留读类交集。
- [ ] 场景 5：修改已激活 Skill 正文，下一次输入前自动更新并保留原参数；制造非法白名单后旧版本继续可用。
- [ ] 场景 6：删除项目级 review 后自动回退用户级或内置 review，命令说明和 SOP 同步切换。
- [ ] 场景 7：输入 `/clear` 后 active 和工具限制清空，但 `/review` 仍在 help 中并可再次执行。
- [ ] 场景 8：Anthropic/DeepSeek 兼容 fake 服务连续执行 Skill tool call、子工具和摘要回流，不出现 thinking 缺失或 tool_result 配对 400。
- [ ] 场景 9：Skill 尝试越界读文件或执行危险 Bash 时被现有沙箱/黑名单拒绝，Agent 根据结构化错误继续。
- [ ] 场景 10：指定 model 的 shared 和 isolated Skill 执行结束后，下一条普通消息恢复主模型。

> 优先在 tmux 中完成真实 TUI 场景。当前 Windows 环境没有 tmux 时，使用 fake Provider、临时项目目录和 CLI 输入流完成同等端到端验证，并在验收报告明确记录环境限制。

## 验收项映射

| Spec AC | 清单范围 |
| --- | --- |
| AC1 | 文件格式与安全解析 |
| AC2 | 三级发现与覆盖 |
| AC3 | 两阶段加载与 Prompt：未激活目录 |
| AC4 | 两阶段加载与 Prompt：Skill 工具、参数替换、active block |
| AC5 | active 持久化、重复激活和多 Skill |
| AC6 | Catalog 校验、未知工具、系统 Skill 工具 |
| AC7 | 工具白名单交集、Plan Mode 和权限安全 |
| AC8 | Shared 执行模式与模型覆盖 |
| AC9 | Isolated 状态、历史选择和摘要回流 |
| AC10 | Isolated 结构化失败与嵌套限制 |
| AC11 | Slash Command、帮助、补全和参数保留 |
| AC12 | `/review` 迁移和三级覆盖 |
| AC13 | 热更新与原子旧快照保留 |
| AC14 | `/clear` 生命周期 |
| AC15 | 内置 commit、review、test |
| AC16 | 状态与信息安全 |
| AC17 | Provider 协议与回归 |
| AC18 | 构建、文档和端到端场景 |

## 审批门槛

- [x] `spec.md` 已批准。
- [x] `plan.md` 已批准。
- [x] `task.md` 已批准。
- [x] 本 `checklist.md` 已批准后才开始实现。
