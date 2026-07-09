# HuiCode Mew Spec 踩坑经历

这份文档记录当前 HuiCode 项目里一些没有在最初一次 Mew Spec 流程中完整想清楚、后来又靠实测、报错和补丁修回来的点。它不是追责清单，而是下一章写 spec 时可以直接复用的“别再漏了”清单。

## 背景

项目早期从“纯对话 CLI”逐步演进到工具系统、Agent Loop、系统提示、权限系统。中间有几类问题不是功能缺失那么简单，而是“看起来实现了，但真实模型、真实终端、真实用户操作一跑就露馅”。

典型特征：

- spec 只覆盖了理想路径，没有覆盖模型绕过、Provider 兼容、终端平台差异。
- 实现依赖提示词或工具暴露列表，没有在执行层做硬约束。
- 单元测试覆盖了内部结构，没有覆盖用户真实输入后的端到端交互。
- 文档和 spec 文件一开始散落在根目录，后续章节容易覆盖旧文档。

## 踩坑 1：工具调用解析只按“标准 API”想，没有覆盖兼容模型的怪输出

现象：

用户问项目入口文件时，模型返回了类似 `<｜｜DSML｜｜tool_calls>` 的文本块，而不是被 HuiCode 识别成标准工具调用。TUI 最终把它当普通文本吐出来。

根因：

最初只按 OpenAI/Anthropic 的标准工具调用事件设计，没有把“兼容接口可能输出非标准工具调用文本”当作验收场景。Provider 层虽然有抽象，但 spec 没有明确要求：如果模型用非目标协议格式输出工具调用，系统应该如何处理、如何提示、是否重试。

后来补救：

- 强化工具调用解析和对话回灌。
- 通过系统提示告诉模型只能使用真实暴露的工具。
- 在后续 Agent Loop 中加入空响应重试、未知工具限制等兜底。

以后写 spec 要补：

- 明确 Provider 的“协议内工具调用”和“协议外文本伪工具调用”边界。
- 验收标准要包括：模型吐出无法解析的工具调用文本时，不应静默当作成功。
- 对兼容模型要单独列一组人工场景，而不是只跑 mock 单测。

## 踩坑 2：DeepSeek Anthropic 兼容接口要求 thinking 回传，最初没有作为多轮工具场景验收

现象：

使用 DeepSeek Anthropic 兼容接口开启 thinking 后，工具调用完成再请求下一轮时出现 400：

```text
The `content[].thinking` in the thinking mode must be passed back to the API.
```

根因：

早期只验证了单轮 thinking 流式输出，没有把“assistant thinking + tool_use + tool_result + 下一轮请求”作为一个完整链路验收。兼容 Anthropic 协议时，thinking 不是只展示给用户的临时文本，它还是下一轮 API 请求必须保留的历史内容。

后来补救：

- `ConversationMessage` 保留 `thinking` 和 `thinking_signature`。
- Anthropic Provider 序列化历史时带回 thinking block。
- 测试覆盖 `test_thinking_is_preserved_for_tool_history`、`test_serializes_text_assistant_thinking`、`test_parses_thinking_signature_delta` 等场景。

以后写 spec 要补：

- 只要支持 extended thinking，就必须把“thinking 是否需要回传”写成协议级要求。
- 多轮工具调用验收必须覆盖 thinking 模式。
- 兼容接口不要只按官方 Claude 行为猜，要用真实错误消息反推协议约束。

## 踩坑 3：Anthropic 工具结果必须紧跟 tool_use，最初没有把多工具回灌顺序写死

现象：

模型一次返回多个工具调用后，HuiCode 执行了工具，但下一轮请求触发 400：

```text
tool_use ids were found without tool_result blocks immediately after
```

根因：

最初只写了“工具执行完把结果回灌进对话历史”，没有写清 Anthropic 的强约束：assistant 的 `tool_use` 后面必须立刻跟一个 user message，里面包含对应所有 `tool_result`。如果把多个工具结果拆散、插入别的消息、或顺序不对，就会被 API 拒绝。

后来补救：

- Provider 序列化层把多个 tool result 合并成紧跟 tool_use 的消息。
- 测试覆盖 `test_serializes_multiple_tool_results_in_one_immediate_user_message`。
- Agent Loop 统一通过工具消息回灌，避免 TUI 和 Provider 各自拼历史。

以后写 spec 要补：

- “回灌进历史”不够，要写具体协议顺序。
- 多工具调用要有验收：一次返回 3 个工具调用时，下一轮请求 payload 的消息顺序必须合法。
- Provider 层测试不能只测解析，还要测序列化后的请求体。

## 踩坑 4：Plan Mode 只限制暴露工具列表，没有在执行层硬拦截

现象：

用户进入 `/plan` 后要求写文件，模型仍然返回 `Bash(echo 2 > hello.txt)`。旧实现虽然只给模型暴露读类工具，但执行层仍然执行了模型吐出来的 `Bash`，甚至进入权限确认，用户选 `once` 后文件被写入。

根因：

最初把 Plan Mode 当成“提示词 + 工具列表过滤”问题，没有把它当成安全边界。模型不是可信调用方，不能假设它只会调用暴露列表里的工具。

后来补救：

- 在 `execute_tool_batches()` 执行前加入 Plan Mode guard。
- 非读类工具直接返回结构化 `permission_denied`，不触发权限确认。
- Agent Loop 继续下一轮，让模型有机会调整策略。
- 新增回归测试 `test_plan_mode_denies_side_effect_tool_before_confirmation_and_continues`。

以后写 spec 要补：

- 所有模式约束都要区分“模型侧可见限制”和“执行层强制限制”。
- Plan Mode 的验收必须模拟模型绕过工具列表，直接返回 `Bash`/`Write`/`Edit`。
- 权限系统不能覆盖任务模式：Plan Mode 比 once/session/always 更高优先级。

## 踩坑 5：权限系统实现了，但交互成本没有在 spec 里量化

现象：

权限系统上线后，功能能用，但用户反馈 `/permissions` 切换和确认交互不方便，TUI 也看不到当前模式。实际使用时，用户需要记住自己处于 Plan Mode 还是普通模式、权限模式是 strict/default/permissive。

根因：

006 权限系统 spec 更关注五层防御、规则优先级和拦截结果，对“操作频率高的命令应该短”“确认 prompt 要能一键输入”“当前模式必须可见”写得不够具体。

后来补救：

- 新增 `/perm` 作为 `/permissions` 短别名。
- 权限确认 prompt 改为 `Permission [d/o/s/a, enter=deny]>`。
- TUI 每轮开始显示 `mode=... permission=...`。
- README 记录快捷输入。

以后写 spec 要补：

- 交互类功能要写“用户输入步数”和“默认动作”。
- 高风险确认 prompt 必须明确默认值，回车默认应偏安全。
- 状态模式要显示在用户正在操作的地方，而不是只在命令查询里可见。

## 踩坑 6：Windows 终端命令兼容没有在 Bash 工具早期验收

现象：

用户让 HuiCode 查看项目入口时，模型调用 `Bash(ls -la)`，在 Windows PowerShell 环境里失败，然后又退回 `dir`。

根因：

项目运行环境是 Windows，但模型更常输出 Unix 命令。早期工具 spec 只写“执行命令”，没有要求对常见跨平台命令做兼容或给模型明确 shell 环境约束。

后来补救：

- Bash 工具加入常见 Unix `ls` 到 Windows 可执行形式的归一化。
- 系统提示环境信息中注入 shell/platform。
- 测试覆盖 `test_normalizes_common_unix_ls_on_windows`。

以后写 spec 要补：

- CLI Agent 的 shell 工具必须把平台差异当一等需求。
- 验收要覆盖 Windows 下模型常吐的 `ls -la`、`cat` 等命令。
- 系统提示不能代替工具兼容层，至少要对高频命令有兜底。

## 踩坑 7：Markdown/TUI 可读性不是“后面再说”的小事

现象：

当前 HuiCode 早期 TUI 输出能流式打印，但 Markdown 不渲染，工具行、状态行和回答混在一起时可读性一般。随着 Agent Loop 增加，输出事件越来越多，纯文本拼接很快变得难扫。

根因：

早期 spec 把 TUI 当成输出通道，没有把它当成 Agent 的核心可观测界面。工具调用、thinking、usage、权限确认、最终回答都需要不同视觉层级，否则用户很难判断 Agent 正在做什么。

后来补救：

- 引入 Rich Markdown 渲染。
- 工具调用使用 Claude Code 风格工具行。
- 权限确认和模式状态单独格式化。
- 测试覆盖 Markdown、工具组、elapsed、usage 等输出。

以后写 spec 要补：

- TUI 的验收不只看“有没有输出”，还要看输出结构是否可扫。
- 每类 AgentEvent 都要定义用户可见呈现。
- 流式 Markdown 要考虑代码块未闭合、段落缓冲和最终 flush。

## 踩坑 8：系统提示词不能只写三行，工具规则需要在多个层次重复

现象：

模型会用 Bash 替代专用工具、会在没读文件前编辑、会提到尚未实现的能力。只靠简单全局指令无法稳定约束行为。

根因：

早期系统提示过短，没有区分稳定指令、动态环境、任务模式、工具使用规则，也没有把关键规则同时放进系统提示和工具描述。

后来补救：

- 建立七个固定模块：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。
- 增加环境信息和模式指令的动态注入。
- 工具描述里强化“优先用专用工具”“编辑前先读”等规则。
- 缓存 usage 归一化，用于观察缓存策略是否生效。

以后写 spec 要补：

- 系统提示要按职责模块化，不要把所有规则堆成一段。
- 稳定内容和动态内容要分开设计。
- 对模型经常违反的规则，要同时进入系统模块、工具描述、测试场景。

## 踩坑 9：Mew Spec 文档一开始没有分章保存，导致历史容易被覆盖

现象：

早期根目录有 `spec.md`、`plan.md`、`task.md`、`checklist.md`、`acceptance_report.md`。后续继续走 Mew Spec 时容易覆盖上一章文档。用户明确提出“每次 mewspec 的四份文档分开可行吗，别老把之前的覆盖”。

根因：

最初把 Mew Spec 当作一次性工作流文件，而不是项目长期演进档案。章节之间没有固定目录编号，也没有把 acceptance report 放回同一目录。

后来补救：

- 后续章节改为 `specs/NNN-feature-name/` 目录。
- 每章包含 `spec.md`、`plan.md`、`task.md`、`checklist.md`、`acceptance_report.md`。
- 007 还专门记录了 Plan Mode 权限 UX 修复的完整闭环。

以后写 spec 要补：

- 每章创建独立目录，不在根目录覆盖旧文档。
- 目录名要带序号和短主题。
- 提交时只暂存本章目录，避免把旧根目录临时文件混进去。

## 踩坑 10：验收不能只靠 mock，真实 Provider/真实平台仍然会教做人

现象：

不少问题是在真实 DeepSeek Anthropic 兼容接口、真实 Windows 终端、真实 TUI 对话里暴露的，而不是最初单测里暴露的。

根因：

mock Provider 很适合保证内部逻辑，但它默认“协议干净、工具调用规范、平台稳定”。Agent 项目的风险正好藏在这些不稳定处。

后来补救：

- 增加 Provider payload 序列化测试。
- 增加 Windows shell 行为测试。
- 增加用户实测触发的回归测试。
- 在 acceptance report 中明确记录 tmux 或网络受限时哪些 E2E 没跑。

以后写 spec 要补：

- 每章至少有一个“真实用户句子”的 E2E 场景。
- Provider 兼容章节要有真实 API 或录制 payload 的验收。
- 如果 E2E 因环境不可用没跑，要写进 acceptance report，而不是假装通过。

## 踩坑 11：MCP 配置“能解析”不等于“能启动并注册工具”

现象：

Context7 MCP 配置文件放到项目里后，HuiCode 启动没有加载到工具。第一次排查发现文件路径曾放在 `.huicode/mcp.yaml`，但实现只读项目根目录 `.huicode-mcp.yaml`。移动后仍然没有注册工具，又发现顶层 key、`args` 类型和 Windows 命令名都有坑。

具体表现：

- 项目内 `.huicode/mcp.yaml` 不会被当前实现读取；项目级路径是 `.huicode-mcp.yaml`。
- 顶层写成 `mcp_servers` 时，解析器不会报错，但 `loaded_server_count=0`，因为实现只认 `mcp`。
- `args: ["-y", "@upstash/context7-mcp"]` 或 `args: -y @upstash/context7-mcp` 在当前简化 YAML 解析器里会变成字符串；实现要求 `args` 是多行列表。
- Windows 下 Python `subprocess.Popen(["npx", ...])` 可能报 `[WinError 2] 系统找不到指定的文件`；改成 `command: npx.cmd` 后才能稳定启动。
- 只检查“配置能加载到 1 个 server”还不够，必须实际启动 MCP manager 并确认 `mcp_tools` 数量。

根因：

008 MCP Client 的 spec 写清了“用户级、项目级两层合并”和“stdio 填 command/args/env”，但验收更偏 fake server 和内部接口，没有把“用户照着第三方 MCP 文档粘配置”的真实路径作为独立验收。Context7 官方示例多是 JSON，常见 key 有 `mcpServers`、`servers`，而 HuiCode 当前 YAML 格式是自定义的 `mcp`。此外 Windows 命令解析差异也没有写进 MCP 章节验收。

后来补救：

- 用脱敏结构检查确认配置路径、顶层 key、字段类型和 server 数量，不打印 token/header/env 的值。
- 把 Context7 配置改成 HuiCode 当前可识别格式：

```yaml
mcp:
  context7:
    type: stdio
    command: npx.cmd
    args:
      - "-y"
      - "@upstash/context7-mcp"
```

- 实际启动 MCP manager 验证：

```text
mcp_servers=1/1
mcp_tools=2
tool=mcp__context7__resolve_library_id
tool=mcp__context7__query_docs
```

以后写 spec 要补：

- 配置类功能要区分“文件存在”“解析成功”“server 加载”“server 启动”“工具注册”五层验收。
- README 示例必须使用当前解析器真实支持的 YAML 写法，不要放 inline list 这种看似标准但当前 parser 不支持的格式。
- MCP 章节要至少覆盖一个真实第三方 server，例如 Context7，而不仅是 fake stdio/http server。
- Windows 平台要验证 stdio command 是否能被 `subprocess` 直接启动；`npx` 这类命令优先写 `npx.cmd`。
- 排查配置时默认采用脱敏结构检查，只输出 key 名、字段类型、数量和工具名，不打印 secret 值。
- 如果用户实测暴露出 spec 未覆盖的返工问题，要立即更新本文件，形成后续章节的反例库。

## 踩坑 12：自动加载外部能力后，测试不能把“工具集合”写死

现象：

进入新的上下文管理章节后跑全量测试，`tests.test_cli_plan_mode` 失败。失败不是 `/plan` 或 `/do` 行为错了，而是断言写成了“`/do` 时工具集合必须刚好等于 6 个内置工具”。项目后来接入了自动加载的 MCP 工具，例如 Context7，于是实际工具集合里会额外出现：

```text
mcp__context7__resolve_library_id
mcp__context7__query_docs
```

根因：

早期 Plan Mode 测试建立在“系统只有内置工具”这个静态前提上。随着 008 MCP Client 落地，工具中心变成动态可扩展集合，但老测试仍把全量工具视为固定常量，没有区分“必须存在的核心工具”和“允许新增的扩展工具”。

后来补救：

- 把断言从“集合完全相等”改成“至少包含 `Read/Write/Edit/Bash/Find/Search` 六个核心工具”。
- 保留 `/plan` 场景对只读工具集合的精确约束，因为那是模式边界本身。
- 在 009 章验收阶段通过 `python -m unittest discover -v` 暴露并修正这个问题。

以后写 spec 要补：

- 只要系统支持插件、MCP 或动态注册，测试就要区分“核心下限”与“扩展上限”。
- 对全量工具断言，优先检查必需能力、别名和模式过滤结果，不要默认工具列表永远固定。
- checklist 里要补一句：新增外部能力后，回归测试需复核是否把动态集合写成了静态常量。

## 可复用 Spec Checklist

以后每次写 HuiCode 新章节 spec，可以先问这几件事：

1. 这个能力有没有执行层硬约束，还是只靠提示词？
2. 模型绕过工具列表或输出畸形工具调用时会怎样？
3. OpenAI 和 Anthropic 兼容协议的历史序列化是否都合法？
4. thinking、tool_use、tool_result、usage 是否能跨多轮保留？
5. Windows PowerShell 下是否有等价行为？
6. 用户在 TUI 里是否能看见当前模式、进度、风险和默认动作？
7. 权限拒绝、工具失败、未知工具、空响应是否都能继续或清晰停止？
8. 多工具并发/串行顺序是否写入验收？
9. README、测试、acceptance report 是否和实现同步？
10. 本章文档是否在独立 `specs/NNN-*` 目录，避免覆盖旧记录？
11. 配置类能力是否同时验证了路径、顶层 key、字段类型、环境变量展开和 secret 不泄露？
12. 外部集成是否至少跑过一个真实第三方服务或本地真实启动命令，而不只靠 fake server？
13. Windows 下 `subprocess` 能否直接找到配置里的 `command`？

## 维护约定

以后 HuiCode 开发中只要出现“已经按 Mew Spec 做完，但真实使用又返工”的问题，都要同步更新这份文档。记录时至少写清：

- 现象：用户看到的报错或不符合预期的行为。
- 根因：当初 spec、plan、task 或 checklist 漏掉了什么。
- 后来补救：代码、测试、文档或配置怎样修。
- 以后写 spec 要补：下一章可以直接复用的验收项。

如果问题涉及配置或密钥，文档只记录结构和规则，不记录真实 token、header、API key 或本地私有路径中敏感部分。

## 结论

HuiCode 这几轮最大的经验是：Coding Agent 的难点不在“能不能调 API”，而在协议历史、工具边界、安全执行、平台差异和用户可观测性。Mew Spec 对这类项目很有用，但前提是 spec 不能只写理想功能，要把真实模型会犯错、真实接口会挑剔、真实用户会怎么操作都写进去。
