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

## 踩坑 13：主配置入口不支持 MCP 内联，用户会自然找错地方

现象：

MCP Client 章节实现后，HuiCode 只读取 `~/.huicode/mcp.yaml` 和项目根目录 `.huicode-mcp.yaml`。用户自然会问：既然模型、thinking、context 都写在 `huicode.yaml`，为什么 MCP 不能也写在主配置里？这说明配置入口虽然“分层合理”，但缺少一个直观的主入口。

根因：

008 MCP Client 的 spec 把“用户级、项目级两层合并”写得很清楚，却没有把 `huicode.yaml` 作为产品主配置入口纳入设计。与此同时，`huicode.yaml` 自己的解析器只支持一层嵌套，就算把 `mcp.context7.args` 写进去，也会在主配置解析阶段失败。

后来补救：

- `LLMConfig` 增加 `mcp` 原样映射，`huicode.yaml` 解析器支持深层 map/list。
- MCP loader 增加中间层 `inline_mcp`。
- 合并优先级固定为：用户级默认 < `huicode.yaml` < 项目级覆盖。
- README 增加 `huicode.yaml` 内联 Context7 示例。
- 测试覆盖主配置解析、三层覆盖顺序和 CLI 内联 MCP 工具注册。

以后写 spec 要补：

- 配置类能力要明确“主配置入口是否支持”，不要只设计旁路配置文件。
- 合并优先级要写成一条可测试规则，而不是只在文档里解释。
- 主配置解析器能力要跟示例同步，示例里出现深层 map/list 时必须有解析测试。

## 踩坑 14：TLS EOF 这类连接错误不能只丢给用户一串底层异常

现象：

DeepSeek Anthropic 兼容接口请求前，TUI 只显示：

```text
请求错误: 无法连接 API: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol
```

配置本身是 `protocol: anthropic` 与 `base_url: https://api.deepseek.com/anthropic`，属于 DeepSeek 官方兼容接口形态；这个错误发生在 TLS/连接层，还没到 HTTP 状态码和 JSON 错误阶段。

根因：

SSE 客户端只把 `urllib` 的连接异常原样包成“无法连接 API”，没有区分 TLS EOF、连接重置、HTTP 错误、流式中途断开，也没有对“请求尚未开始接收响应”的短暂断连做重试。

后来补救：

- `post_sse()` 在打开连接阶段遇到 TLS EOF/连接错误时默认重试一次。
- 一旦已经开始收到 SSE 数据，不自动重放请求，避免流式回答或工具调用重复。
- TLS EOF 的错误文案改成“TLS 连接被提前关闭，通常是网络、代理或上游网关临时断开”。
- `tests.test_sse` 覆盖连接前重试成功和重试耗尽后的友好错误文案。

以后写 spec 要补：

- Provider/SSE 章节要区分 HTTP 错误、连接前失败、流式中途失败三类错误。
- 只允许对“尚未收到响应”的连接失败自动重试；已开始流式输出后不能静默重放请求。
- 用户可见错误要给出排查方向，不要只暴露 Python/SSL 底层异常。

## 踩坑 15：查项目结构时模型退回 Bash，会把用户拖进确认地狱

现象：

用户让 HuiCode “看一下这个项目的代码结构”，模型先调了 `Find(*)`，随后又连续调用：

```text
Bash(dir /b /s ... | head -100)
Bash(Get-ChildItem -Recurse -Depth 2 -Name | Select-Object -First 100)
Bash(dir /s /b ...\huicode)
```

默认权限模式把所有 `Bash` 都当中风险副作用操作，于是每一次只读目录查看都要求用户确认。部分命令还混用了 Unix `head`、cmd `dir` 和 PowerShell `Get-ChildItem`，在 Windows 上失败。与此同时，`Find(*)` 结果被压缩后没有保留足够的 `matches`，模型又倾向继续找。

根因：

- 工具提示写了“优先用 Find”，但执行层没有降低只读 Bash 的摩擦。
- 权限系统只有工具级 `side_effect=True/False`，没有参数级风险判定。
- Windows shell 兼容只覆盖了少数 `ls` 别名，没有处理 `| head -N` 和 PowerShell cmdlet。
- 上下文压缩把 `matches` 视为可省略字段，对“项目结构”这类任务反而丢掉了核心证据。
- TUI 同时在工具结果和上下文事件里显示 spill，视觉上像重复整理。

后来补救：

- 默认模式下，白名单内只读 Bash 命令如 `dir`、`tree`、`Get-ChildItem`、`Get-Content`、`Select-String`、`git status/diff/log` 等按低风险放行；包含重定向、链式控制符或 workspace 外绝对路径时仍需确认。
- Windows 下将尾部 `| head -N` 转成 HuiCode 内部行数限制，避免依赖不存在的 `head`。
- Windows 下识别 PowerShell cmdlet，并包装成 `powershell -NoProfile -Command ...` 执行。
- `Find`/`Search` 跳过 `.git`、`__pycache__` 和 `.huicode/tool-results` 噪音目录。
- 轻量压缩保留 `matches` 前 80 条，避免模型只看到“ok, 50 files”。
- TUI spill 提示只保留“上下文整理”事件，不在工具结果下重复显示。

以后写 spec 要补：

- 权限系统不只要按工具分类，也要按参数/命令内容识别低风险只读操作。
- 查询项目结构是 Agent 的核心 E2E 场景，必须验收“不需要用户反复确认也能完成”。
- Windows shell 兼容要覆盖模型常见混写：`dir | head`、`Get-ChildItem | Select-Object`。
- 上下文压缩不能一刀切省略工具核心字段；对 `Find/Search`，`matches` 就是关键证据。

## 踩坑 16：Windows 路径写进权限规则后，`C:` 会把 YAML 解析器拆坏

现象：

用户在权限确认里对 `Bash(dir /s /b C:\Users\Administrator\Documents\Huicode\huicode)` 选择 `always` 后，HuiCode 把规则写入 `.huicode-permissions.local.yaml`：

```yaml
rules:
  Bash(dir /s /b C:\Users\Administrator\Documents\Huicode\huicode): allow
```

下次启动直接失败：

```text
权限配置错误: 权限规则 Bash(dir /s /b C 的结果必须是 allow 或 deny
```

根因：

权限配置解析器用第一个冒号拆分 `key: value`，Windows 绝对路径里的 `C:` 被误判成 YAML 分隔符。写入器也没有给复杂规则 key 加引号，导致本地持久规则很容易把自己写成启动阻塞文件。

后来补救：

- 权限规则解析改为从右侧拆分 `key: value`，兼容已经写入的旧未加引号 Windows 路径规则。
- `append_persistent_rule()` 写入规则时给 key 加单引号，并处理单引号转义。
- 测试覆盖旧格式 `C:\...` 规则加载，以及新规则写入后可再次加载。

以后写 spec 要补：

- 任何会写 YAML 的功能都要覆盖 Windows 路径、冒号、井号、括号和引号。
- 持久化规则写入后必须立刻用同一个 loader 回读，防止“写成功但下次启动炸”。
- 用户级/项目级/本地级配置文件错误应该尽可能定位到具体文件和行。

## 踩坑 17：上下文窗口小于安全余量时，自动压缩会每轮误触发

现象：

用户配置：

```yaml
context:
  window_tokens: 5000
  auto_margin_tokens: 13000
  recent_keep_tokens: 10000
```

随后每次对话都会显示：

```text
HuiCode> 上下文压缩跳过: 没有可压缩的早期历史
```

根因：

自动压缩触发线是 `window_tokens - auto_margin_tokens`。当窗口是 5000、自动安全余量是 13000 时，触发线变成 `-8000`，任何请求 token 估算都会大于这个负数，于是每轮都进入摘要路径。历史太短时不会真正调用摘要模型，但 TUI 会持续显示跳过，用户会以为上下文管理坏了。

后来补救：

- `load_config()` 增加跨字段校验：`auto_margin_tokens`、`manual_margin_tokens`、`recent_keep_tokens` 必须小于 `window_tokens`。
- README 明确记录这些字段的关系。
- 测试覆盖 `window_tokens=5000` 且 `auto_margin_tokens=13000` 的非法配置。

以后写 spec 要补：

- 配置校验不能只看单字段正整数，还要校验字段之间的数学关系。
- 自动触发阈值类配置要在 README 里写出公式和非法组合。
- TUI 的自动 skip 事件要考虑是否应该静默，避免正常小历史场景造成噪音。

## 踩坑 18：Mew Spec 模板是英文，但项目文档输出必须跟随 AGENT.md

现象：

记忆系统章节的 `spec.md`、`plan.md`、`task.md` 都按中文写了，但 `checklist.md` 受技能模板影响写成了英文小标题和英文条目。用户批准时指出“为什么 checklist 是英语输出”。

根因：

- `mew-spec` 技能参考模板是英文，生成最后一份文档时过度贴近模板，忘了项目 `AGENT.md` 明确要求中文回答、中文注释。
- checklist 被当成内部工程文档，而不是用户会审的交付物。
- 生成四份文档时没有做“语言一致性”自检，只检查了结构完整性。

后来补救：

- 立即把 `specs/010-memory-system/checklist.md` 全量改成中文。
- 后续实现、验收报告和最终说明继续使用中文。

以后写 spec 要补：

- 四份 Mew Spec 文档都必须遵循项目语言约定；模板语言不能覆盖 `AGENT.md`。
- 每份文档生成后自检一次：标题、章节、验收项、提示语是否和项目主要语言一致。
- 如果用户指出文档语言、格式或位置问题，要同步更新本踩坑文档。

## 踩坑 19：自动记忆和主 Agent 工具的职责边界不够硬

现象：

用户看到疑似“记忆更新”的文件工具权限确认，自动能力反而打断正常对话。

根因：

- 后台 `MemoryUpdater` 本身已经禁用工具并直接写笔记，但系统提示没有明确告诉主 Agent：会话和长期记忆是内部状态，不需要它调用工具维护。
- 自动更新排队成功仍产生一条可见事件，容易让后台维护显得像需要用户参与的任务。
- 权限层没有保护 `.huicode/sessions` 和 `.huicode/memory`，模型误调用副作用工具时会进入确认流程。

后来补救：

- 自动更新继续使用 `tools=[]`、`allow_tool_calls=False`，并改为后台静默执行；失败通过 `/memory` 查看。
- 系统提示和工具描述双重声明内部记忆由 HuiCode 自动维护。
- 对内部会话和记忆目录的 `Write`、`Edit` 和有副作用 Bash 直接拒绝，不弹确认框；明确读取仍可进行。

以后写 spec 要补：

- 后台自动能力必须明确是否经过权限系统、是否显示进度、失败从哪里查看。
- 内部状态目录要区分“框架内部写入”和“模型工具写入”，不能让模型通过普通工具维护。
- 验收要覆盖默认、严格和放行模式，确认内部状态保护不会被模式覆盖。

## 踩坑 20：实现新章节时误把用户调整过的迭代上限恢复成旧默认值

现象：

用户原本把 Agent Loop 最大迭代次数设为 50，记忆系统完成后又在第 8 轮停止。

根因：

- 实现记忆系统时把 `AgentOptions.max_iterations` 当成无关旧默认值恢复为 8。
- 验收只确认“达到上限会停止”，没有确认项目当前约定的具体上限。
- 验收报告甚至把恢复 8 写成回归修复，说明对既有行为基线判断错误。

后来补救：

- 默认迭代上限恢复为 50。
- 更新单元测试、README 和记忆系统验收报告。

以后写 spec 要补：

- 开始新章节前记录关键运行参数基线，不能凭旧提交或个人判断回退用户调整。
- 涉及默认值时同时检查当前代码、README、配置示例和用户已确认行为。

## 踩坑 21：Windows 子进程按系统编码解码 UTF-8 文件会连锁崩溃

现象：

恢复会话后，模型执行 `type .huicode\\sessions\\*.jsonl`，`subprocess` 的读取线程用 GBK 解码 UTF-8 JSONL，抛出 `UnicodeDecodeError`；随后 stdout 变成 `None`，摘要代码又触发 `object of type 'NoneType' has no len()`。

根因：

- `subprocess.run(text=True)` 隐式使用 Windows 本地编码，但项目会话文件固定为 UTF-8。
- 输出截断和摘要函数默认 stdout/stderr 一定是字符串，没有防御读取线程失败后的空值。
- shell 测试只覆盖 ASCII 输出，没有真实读取 UTF-8 文件。

后来补救：

- Bash 工具改为二进制收集 stdout/stderr，再按 BOM、UTF-8、本地编码、GB18030 顺序解码。
- `None` 输出统一归一化为空字符串，避免二次异常掩盖原始问题。
- 新增 Windows `type` 读取 UTF-8 JSONL 的真实回归测试，同时覆盖 UTF-8、GB18030 和空输出。

以后写 spec 要补：

- Windows shell 测试必须包含中文、非 GBK 字符、UTF-8 文件和空输出。
- 所有 subprocess 输出边界都要明确字节到文本的编码策略，不能依赖 `text=True` 默认编码。
- 错误处理还要验证错误后的摘要和 TUI 渲染不会再抛第二个异常。

## 踩坑 22：命令出现在补全列表，但裸命令没有处理分支

现象：

用户输入裸 `/resume` 后，HuiCode 没有展示会话列表，而是进入 Agent Loop。模型把它理解成恢复工作任务，连续读取记忆、项目文档、代码并执行测试；只有 `/resume <session-id>` 能正常恢复。

根因：

- `COMMANDS` 已登记 `/resume`，但 CLI 只实现了 `command.startswith("/resume ")`。
- 裸 `/resume` 未命中任何命令分支，最终作为普通用户消息发送给 Provider。
- 原验收只覆盖带 ID 的成功恢复，没有覆盖无参数入口，也没有断言管理命令不会调用 Provider。

后来补救：

- 裸 `/resume` 直接复用会话列表输出，并提示 `/resume <session-id>` 用法。
- 新增 CLI 回归测试，确认会话 ID 可见且 Provider 调用次数为 0。
- README 和记忆系统验收报告同步更新。

以后写 spec 要补：

- 每个斜杠命令都要覆盖裸命令、合法参数、缺失参数和非法参数。
- 本地管理命令必须断言不会落入 Agent Loop、不会消耗模型 token、不会触发工具或权限确认。
- 自动补全列表与命令分发器要做一致性检查，不能只验证命令“能补全”。

## 踩坑 23：系统工具通过可见列表过滤后，仍被执行前二次防线拒绝

现象：

Skill 系统要求加载工具在 Plan Mode 和工具白名单收窄后始终可见。最初实现只改了 Provider 的工具列表，模型确实能看到 `Skill`，但真正调用时仍会被 `_plan_mode_denial()` 拒绝；strict 权限模式也会把它当成未匹配工具拒绝。

根因：

- 工具能力有“暴露给模型”和“执行前授权”两道独立关口，只验收第一道不足以证明工具可用。
- 系统工具与普通业务工具没有明确分类，Plan Mode 和权限引擎无法判断该调用只加载指令，不直接操作文件。
- 原任务写了“系统 Skill 工具不受白名单约束”，但没有逐层列出 Plan Mode 执行检查和 strict 权限检查。

后来补救：

- ToolRegistry 增加系统工具分类，筛选普通工具时始终保留系统工具。
- Plan Mode 执行前检查只允许系统加载工具通过；普通 Read/Bash 等仍按只读规则校验。
- 权限执行器只跳过系统加载工具本身，Skill 子循环中的所有普通工具继续经过黑名单、沙箱、规则和人在回路。
- 新增 Plan Mode 加 strict 权限的组合测试，确认 Skill 能激活但不能借此扩大普通工具权限。

以后写 spec 要补：

- 声明“始终可用”时必须同时检查工具列表、批处理分类、执行前模式校验、权限引擎和实际 ToolResult。
- 系统控制工具要明确它能修改哪些内部状态，以及为什么可以绕过某一层；不能给它通用权限旁路。
- 验收至少覆盖默认、strict、Plan Mode 及其组合，确认控制工具可达、业务工具不扩权。

## 踩坑 24：权限确认的临时补全设置永久污染 PromptSession

现象：

HuiCode 刚启动时输入 `/` 会显示命令候选；经过几轮对话和一次权限确认后，再输入 `/` 不再自动弹出任何提示。

根因：

- 权限输入复用了主 `PromptSession`，调用时传入 `complete_while_typing=False`。
- prompt_toolkit 的 `PromptSession.prompt()` 参数会写回 Session 并对后续 prompt 持续生效，不是仅本次调用的临时选项。
- 传入 `completer=None` 也不会清空 completer；prompt_toolkit 规定 `None` 表示保留当前值，应使用 `DummyCompleter`。
- 原测试只检查权限 prompt 收到了 false，没有检查下一次用户输入是否恢复自动补全。

后来补救：

- 权限确认前保存 completer 和 `complete_while_typing`，使用 `DummyCompleter` 关闭本次候选。
- 在 `finally` 中恢复原 Session 状态，拒绝、异常和正常返回路径都不会污染下一轮。
- 回归测试模拟 prompt_toolkit 的持久写回行为，并断言权限确认后原 completer 对象和自动补全开关均恢复。

以后写 spec 要补：

- 复用交互 Session 做子提示时，要核对框架参数是调用级还是会话级。
- 权限、搜索、选择菜单等临时输入不仅要验收自身行为，还要验收返回主输入后的状态恢复。

## 踩坑 25：永久允许多行命令把权限 YAML 写坏，导致下次启动失败

现象：

用户用多行 PowerShell here-string 安装 Skill，并在权限确认选择 `always`。当次命令成功，但下次启动报“权限配置第 29 行应为 key: value 格式”，HuiCode 未进入 TUI；随后在 PowerShell 输入 `/help` 只会得到系统命令不存在错误。

根因：

- `always` 会把完整命令作为权限规则 key 追加到 YAML。
- 权限配置是单行解析器，序列化器却把命令中的真实换行原样写入单引号 key，破坏后续行结构。
- 原测试只覆盖引号、冒号和 Windows 路径，没有覆盖多行 shell 命令的持久化与重启回读。

后来补救：

- 多行规则 key 先用 UTF-8 URL-safe Base64 编码成单行并加内部前缀，加载时再严格解码为原始规则。
- 新增“追加后文件只有三行、重启加载后 raw 完全一致”的 round-trip 测试。
- 删除当前项目权限文件中已执行完且无复用价值的损坏安装规则，真实 loader 成功读回 26 条规则。

以后写 spec 要补：

- 任何持久化 shell 命令的配置格式都要覆盖换行、引号、冒号、反斜杠和非 ASCII 字符。
- “本次成功”不代表 `always` 成功，必须用写入后的真实 loader 回读模拟下次启动。
- CLI 启动失败时要明确用户仍在系统 shell，斜杠命令只有进入 HuiCode TUI 后才有效。

## 踩坑 26：Windows UTF-8 BOM 让合法 Skill 被误判为缺少 frontmatter

现象：

安装生成的 `SKILL.md` 肉眼第一行是 `---`，但 Skill 解析器报告“缺少开头 YAML frontmatter 边界”。

根因：

- Windows/.NET 写出的 UTF-8 文件带 BOM，真实首字符是 `\ufeff`，随后才是 `---`。
- 解析器使用 `utf-8` 读取并要求第一行严格等于 `---`，没有吸收 BOM。
- 原 Skill 测试只用无 BOM 的 Python UTF-8 文件。

后来补救：

- Skill 入口改用 `utf-8-sig` 读取，同时兼容有 BOM 和无 BOM UTF-8。
- 新增 Windows BOM 入口测试。
- 用真实用户级 `frontend-design/SKILL.md` 构建 Catalog，成功发现 4 个有效 Skill。

以后写 spec 要补：

- Windows 用户可编辑的 Markdown/YAML/JSONL 入口必须覆盖 UTF-8 BOM。
- 文件格式错误要检查原始首字节，不能只根据终端肉眼内容判断。

## 踩坑 27：验收解释器与用户解释器不同，依赖缺失被误判为 Skill 文件错误

现象：

验收报告称 4 个 Skill 已加载，但用户实际启动后 `/help`、Slash 补全都没有安装的 Skill。用户使用 Windows Python 3.11，验收使用 Codex 自带 Python 3.12。

根因：

- PyYAML 只安装在验收解释器，用户的 `python` 没有该依赖。
- `pyproject.toml` 声明依赖不等于直接从源码运行时已经安装依赖。
- 解析器把“全局 PyYAML 不存在”包装成每个文件的解析失败，Discovery 又按设计跳过单个坏文件，最终 4 个 Skill 全被跳过但程序继续启动。
- 验收没有执行用户原命令中的 `python`，也没有核对 `/help` 的真实输出。

后来补救：

- 为用户实际 Python 3.11 安装项目声明的 PyYAML。
- Catalog 构建前先检查全局依赖；缺失时直接抛启动级 SkillConfigError，不再产生看似正常的空 Catalog。
- 新增 `/skill [name]` 本地可观测入口。
- 使用用户实际 `python -m huicode --config .\huicode.yaml` 执行 `/skill`、`/help`、`/exit`：MCP 1/1、Skill 4 个，`frontend-design [shared/user]` 和 `/frontend-design` 均可见。

以后写 spec 要补：

- 验收必须记录并核对 `sys.executable`，用户命令中的解释器与测试解释器不一致时不能声称真实启动通过。
- 全局依赖缺失必须是全局错误，不能复用“单文件坏了可跳过”的容错路径。
- 插件/Skill 的发现结果必须通过用户可见命令或状态输出验证，不能只调用内部 Builder。

## 踩坑 28：上下文 Hook 已执行，但当前 Provider 请求看不到新指令

现象：

`context_after_compact` 的 prompt Hook 日志显示 success，状态里也已经有动态指令，但紧接着发出的主模型请求没有这段内容，要到下一次请求才出现。

根因：

- Agent 在调用 ContextManager 前就构建了 PromptBundle 快照。
- 重量压缩结束后 Hook 才把指令写入 HookRuntimeState，但当前请求仍复用旧 PromptBundle。
- 原测试只检查状态最终存在，没有检查压缩完成后的第一条真实 Provider 请求。

后来补救：

- ContextManager 返回后、Provider 请求前重新构建动态 PromptBundle。
- 新增“压缩后立即注入”的 Provider spy 测试，直接断言当前请求包含 Hook 指令。
- 保持稳定提示模块不变，只重建动态模块，不把 Hook 文本写进用户历史。

以后写 spec 要补：

- 任何运行时上下文注入都要验证“第几次请求生效”，不能只检查最终状态。
- 在请求准备阶段修改 Prompt 状态时，要明确快照创建点和重建边界。

## 踩坑 29：`shutdown(wait=False)` 不等于 Python 进程会按时退出

现象：

HookManager 的 `close()` 在 2 秒后返回，但存在慢后台 Hook 时，Python 解释器仍等待普通线程结束，终端实际退出时间超过约定上限。

根因：

- `ThreadPoolExecutor.shutdown(wait=False)` 只是不在该调用点等待。
- ThreadPoolExecutor 的普通 worker 会在解释器退出阶段被统一 join。
- 原测试只测量 `manager.close()` 耗时，没有测量进程生命周期语义。

后来补救：

- Hook 后台执行改为固定数量的 daemon worker，并继续使用 Future 关联 pending 状态。
- 关闭时最多等待 2 秒；未完成项记录 skipped，回调不再重复写最终状态。
- 文档同步改为“受控 daemon worker 池”，避免计划与实现不一致。

以后写 spec 要补：

- 后台任务的有界退出必须同时考虑管理器返回时间和解释器退出行为。
- 对不允许拖住 CLI 的后台能力，要明确线程 daemon 属性、未完成任务日志和迟到回调处理。

## 踩坑 30：给 Prompt Builder 插入模块后，主函数静默返回 `None`

现象：

子 Agent 角色和后台结果模块接入后，Prompt 专项、Agent Loop 和 isolated Skill 同时失败，Provider 收到的 `prompt` 变成 `None`。

根因：

- 插入新辅助函数时，原 `return PromptBundle(...)` 被移动到了辅助函数的不可达分支。
- Python 编译不会发现“函数合法但少 return”这类结构错误。
- 如果只跑新增子 Agent 测试，可能把问题误判为 Provider 或缓存逻辑异常。

后来补救：

- 恢复 `build_prompt_bundle()` 的显式返回位置。
- 在接入主 Loop 后立即运行原 Prompt、Agent Loop、CLI Skill 回归，再继续开发。
- 保留“未启用子 Agent时 Prompt 快照不变”的回归覆盖。

以后写 spec 要补：

- 修改核心构建器时，专项验证之外必须立刻跑所有直接调用方回归。
- 对返回复合对象的核心函数，要有非空断言，不能只检查某个字段。

## 踩坑 31：前台超时已返回，但 Ctrl+B 监听线程仍在读终端

现象：

前台子 Agent 超时转后台后，主界面虽然恢复输入，原按键监听线程仍会持续到子任务完成，可能抢走用户后续输入中的控制字符。

根因：

- 最初只用子任务 `done_event` 作为监听线程退出条件。
- “前台等待结束”和“子任务执行结束”是两个不同生命周期；超时/手动转后台时前者先结束。
- 自动化测试只验证 wait 返回 timeout，没有验证监听器是否同步停止。

后来补救：

- 为每次前台等待增加独立 `listener_stop`，wait 通过完成、超时或手动任一路径返回时都在 finally 停止监听。
- `Ctrl+C` 继续交给主循环，并同步取消仍在前台的子任务。
- 增加完成、超时、手动三路等待和有界关闭测试。

以后写 spec 要补：

- 终端监听器必须明确启动、停止和终端状态恢复边界。
- 后台转换测试不仅要看任务状态，还要验证前台临时资源已经释放。

## 踩坑 32：快速恢复入口仍然先初始化 Git

现象：
已有 Worktree 的管理清单完全匹配，本应只读文件系统快速恢复，但 Manager 在判断目录存在之前先取得 Git Backend，仍执行了仓库探测命令。

根因：
- 创建和恢复共用同一个 `prepare()` 入口，最初把 Git Backend 初始化放在路径分支之前。
- 仓库标识依赖 Git 公共目录，导致恢复校验看似必须调用 Git。
- 测试只验证恢复结果正确，没有一开始就注入“任何 Git 调用都失败”的 Backend。

后来补救：
- 仓库标识改为由规范工作区绝对路径稳定计算。
- 先计算安全目标路径并检查目录是否存在；存在时只读清单并匹配，之后立即返回。
- 新增爆炸式 Fake Git，恢复路径只要访问任何 Git 属性或方法就让测试失败。

以后写 spec 要补：
- 声称“零外部调用”的快速路径必须用会在任何外部调用时失败的替身测试。
- 共享入口要把只读恢复分支放在惰性基础设施初始化之前。

## 踩坑 33：失败终态只存在内存，过期清理会忘记保留原因

现象：
子 Agent 失败或取消后当场会保留 Worktree，但进程重启后清理器只能看到目录和 Git 状态；如果目录本身干净，未来可能把本应永久保留供排查的失败现场删掉。

根因：
- 初版管理清单只记录创建身份，没有记录任务终态和保留原因。
- `finalize()` 与后台清理共用变更保护，却没有共享“失败或取消必须保留”的持久状态。
- 验收只覆盖任务结束瞬间，没有覆盖跨时间、跨清理周期的二次判断。

后来补救：
- 在被忽略的管理清单中持久化 `terminal_status` 和 `retained_reason`。
- 失败、取消和成功后的变更保护检查都会原子更新清单。
- 清理器在 Git 状态检查前先读取终态，遇到失败或取消直接保留，不能绕过。

以后写 spec 要补：
- 自动清理依赖的保护状态必须跨进程持久化，不能只存在任务对象内存中。
- “结束时保留”必须同时验收“下一次启动或下一次清理仍保留”。

## 踩坑 34：`git check-ignore` 检查不存在的目录本身会漏掉尾斜杠规则

现象：
配置根目录为 `.wt`，仓库明确写了 `.wt/`，但创建前检查仍报告“Worktree 根目录未被 Git 忽略”。

根因：
- `git check-ignore --no-index .wt` 检查的是一个尚不存在的路径。
- `.wt/` 是目录规则；目标目录不存在时，Git 不会按目录项匹配这个裸路径。
- 初版测试只使用已经被父级 `.huicode/` 覆盖的默认根目录，没有覆盖自定义尾斜杠规则。

后来补救：
- 忽略检查改为验证根目录下的固定虚拟探针路径，`.wt/` 和其他目录规则都能按真实语义命中。
- 新增“只忽略自定义根目录、不全局忽略 `.huicode/`”的临时仓库测试。
- 同时为每个 Worktree 配置专属 exclude 文件，确保管理清单不会制造 dirty 状态。

以后写 spec 要补：
- Git ignore 测试要覆盖不存在路径、目录尾斜杠规则和嵌套文件三种输入。
- 检查“目录是否被忽略”时应验证目录内探针，而不是只验证尚不存在的目录名。

## 踩坑 35：同进程并发快照不能只用 PID 命名临时文件

现象：
Agent Team 压力测试中，审批决定偶发停在 pending，Windows 还会在 `os.replace` 时返回 WinError 5。单次测试大多通过，连续执行才容易复现。

根因：
- 原子写临时文件名只包含 PID；同一进程的成员线程会命中同一个临时文件。
- Windows 对刚写完或被安全软件短暂检查的文件更容易出现瞬时占用。
- 初版 checklist 写了“原子替换”，但没有要求同进程并发写和 Windows replace 短暂失败测试。

后来补救：
- 每次快照写入使用独立 UUID 临时名。
- `os.replace` 遇到短暂 PermissionError 时做有限退避重试，最终失败仍明确上报。
- TeamManager 审批场景连续压力运行 10 次验证竞态消失。

以后写 spec 要补：
- 原子快照验收必须覆盖同 PID 多线程写入，不能只覆盖多进程或单线程中断。
- Windows 文件替换需要覆盖短暂占用，但重试必须有上限，不能无限等待。

## 踩坑 36：等待审批时保留未读任务会造成忙轮询

现象：
成员提交计划后 assignment 必须保持未读，方便批准后继续执行；初版循环因此每轮都能看到任务，持续高速读取审批文件，批准后的执行表现不稳定。

根因：
- “未读消息触发工作”与“等待外部决定”共用了同一个循环条件。
- pending 分支直接 `continue`，没有等待 wake event 或轮询间隔。
- 初版测试只验证一次 allow，没有对审批等待阶段做重复压力和 CPU/文件访问行为检查。

后来补救：
- pending、首次申请和 deny 后重提都进入 wake event 或有界轮询等待。
- `TeamPlanDecision` 落盘后显式唤醒目标成员。
- 连续执行 10 次 deny/allow 邻近时序测试，确认任务稳定完成并回到 idle。

以后写 spec 要补：
- 任何“保留未消费事件等待外部状态”的循环，都要验收不会忙轮询。
- 唤醒机制必须同时有可靠落盘和超时兜底；wake 只优化延迟，不能承担消息可靠性。

## 踩坑 37：能力实现完成但用户配置未启用，真实模型看不到入口工具

现象：
Agent Team 模块、工具注册和作用域测试都已通过，但用户按原有 `huicode.yaml` 启动后，模型的可见工具中没有 `Team`，只能退回使用普通 `Agent`，因此实际没有创建持久团队。

根因：
- `teams.enabled` 为兼容旧配置默认关闭，而用户正在使用的主配置没有补上 `teams:` 段。
- 验收验证了“注册后作用域正确”，却没有验证“用户实际启动配置会进入注册分支”。
- 启动信息没有展示 Team 是启用还是禁用，用户和模型都只能从工具缺失反推状态。

后来补救：
- 在用户实际使用的主配置中显式开启 `teams.enabled`。
- 启动信息增加 Team 启用状态和选定后端。
- 增加回归测试，验证注册 Team 工具后，主 Agent 的 Provider 工具列表包含唯一入口 `Team`，且不会提前暴露 Lead 专用工具。

以后写 spec 要补：
- 所有默认关闭的能力，都要使用交付给用户的真实配置跑一次完整启动路径。
- 验收必须同时覆盖“组件可以注册”和“配置确实触发注册”。
- 可选能力要在启动状态或 `/status` 中明确显示 enabled/disabled，不能只靠 README 说明。

## 踩坑 38：Team 把成员角色误做成启动期硬依赖，失败后看起来像 Worktree 没生效

现象：
模型创建团队后，又在项目角色目录写入 Alice/Bob 定义并立即 spawn。spawn 报未知角色，roster 保持为空，也没有成员 Worktree；模型却把原因概括为“重启后才能加载”，还误判角色文件定义正确。

根因：
- Agent Catalog 只在启动时扫描，Team spawn 又把角色命中 Catalog 当成硬门槛。
- 新文件的 frontmatter 使用大写角色名，实际违反只允许小写名称的校验规则。
- Team 只借 Catalog 校验名称，没有把角色指令、工具限制、模型、轮次和权限真正传给成员执行器。
- 角色校验发生在 Worktree 创建前，因此 spawn 失败时没有 Worktree 是预期的事务顺序，却缺少清楚说明。

后来补救：
- 每次顶层输入和 Team spawn 前刷新 Agent Catalog，失败时保留上一有效快照。
- Team 允许自由角色；同名定义存在时固化角色快照，不存在或新目录损坏时降级为通用角色。
- 协程和独立终端成员统一继承角色指令、工具白黑名单、模型、最大轮次和权限模式。
- Team 成员始终强制创建独立 Worktree，不受角色定义里的 `isolation` 字段影响。
- 工具 Schema、README 和测试明确 spawn 成功才会返回实际 Worktree 路径与分支。

以后写 spec 要补：
- 跨模块复用“定义”时，不能只验证名称存在，必须验收定义的每个行为字段都真正进入执行路径。
- 动态目录需要明确启动扫描、热更新还是按调用刷新，并测试“同一轮写入后立即使用”。
- 多阶段创建流程要测试每个失败点的持久化与资源状态，并在错误里说明哪些后续阶段尚未发生。

## 踩坑 39：Team 已激活但 Lead 仍能调用普通 Agent，状态栏造成“已组队”的错觉

现象：
状态栏显示 `team: demo`，模型却返回 `子 Agent task-... [defined/bob]`。任务在主工作区执行，Team roster 仍为空，用户因此误以为 Team Worktree 没有生效。

根因：
- Team Lead 作用域在加入 Team 协作工具后，仍保留了普通 `Agent` 工具。
- 系统提示只建议使用 Team 工具，没有执行层禁止模型走更熟悉的普通子 Agent 路径。
- 状态栏的 Team 名只代表已恢复团队，不代表当前任务由团队成员执行。

后来补救：
- Team 激活后从 Lead 的 Provider 工具列表中移除普通 `Agent`。
- Team Lead 动态指令明确要求 `Team spawn -> TeamTask assign`，禁止用普通 Agent 代替成员。
- README 和作用域测试明确：看到 `子 Agent` 通知就不是 Team；成功 spawn 必须写入 roster 并展示 Worktree。

以后写 spec 要补：
- 当两个工具能完成相似任务但语义不同，不能只靠提示词引导，模式激活后要在作用域层消除歧义。
- 状态栏模式标记必须与本轮实际执行通道分开验收，不能把“能力已激活”当成“任务已使用该能力”。

## 踩坑 40：同一轮恢复 Team 后工具作用域仍停在旧快照，后台通知还误用异步 API

现象：
模型在同一轮中先 `Team resume`，随后仍能调用普通 `Agent`；后台完成时出现 `coroutine ... was never awaited`。完成结果末尾自动出现 `[truncated]`，用户误以为任务被系统中断。

根因：
- `_team_scoped_registry` 在一轮开始时固化 `main` 身份，Team 状态改变后没有重新计算可见工具。
- 后台线程直接调用 prompt_toolkit 的异步 `run_in_terminal()`，既没有 await，也没有提交到 Application 的事件循环。
- 通知队列把完整结果二次裁成 160 字符，且没有告诉用户 `/tasks <id>` 可以读取完整结果。

后来补救：
- ScopedToolRegistry 接受动态身份提供器，每次解析和序列化工具时读取最新 Team 状态。
- 后台通知使用 `asyncio.run_coroutine_threadsafe` 投递到 prompt_toolkit 运行循环；非交互环境安全回退普通输出。
- 通知保留最多 4000 字符，仍超限时明确提示 `/tasks <task-id>`；任务状态 `completed` 与显示截断分开表达。

以后写 spec 要补：
- Agent Loop 内会改变模式或权限的工具，必须验收“同一轮下一次 LLM 请求”立即看到新状态，不能只测下一轮用户输入。
- 从工作线程调用 TUI 框架前，要区分普通函数、协程和线程安全调度入口，并把 RuntimeWarning 纳入失败条件。
- 后台结果的持久化长度、通知长度和完整结果查询入口要分别定义，截断必须提供恢复路径。

## 踩坑 41：Team 只有工具外壳，没有“分配、执行、提交、汇总”真实闭环

现象：
Lead 创建任务后只发 TeamMessage，成员始终 idle；手动 assign 后 Alice 报文件不存在且只有只读工具，Bob 的 assignment 一直未读。每个 TeamTask/TeamMessage 还弹权限确认，后台通知插入确认界面后输入被误判为 deny。即使成员以后能修改，主工作区大量无关未跟踪文件也会让集成发布永久失败。

根因：
- TeamMessage 与 assignment 语义没有在 Schema 和执行层区分，普通消息不会被 runner 当任务消费。
- assign 只写邮箱、不持久化 assignee，成员错过 worker 唤醒后无法从共享任务表恢复工作。
- `approval_required=false` 仍挂 ApprovalGate，非交互成员的 default 权限又没有 confirmer，Write/Edit 被双重剥夺。
- Git Worktree 只包含提交历史，主工作区未跟踪的任务文件没有共同基线。
- 成员结束后没有自动提交，Lead 也没有可阻塞等待全部结果的工具动作。
- Windows Terminal 启动只拿到 wt 客户端 PID，单个 pane 退出后 roster 仍伪装为 idle。
- 发布把所有无关 untracked 文件也当作 dirty，真实脏工作区几乎不可能通过。

后来补救：
- TeamTask 增加严格 assign 参数和 wait 动作；assign 持久化 assignee，runner 会从任务表自领 pending 工作。
- Team 内部编排工具保持串行但免人工确认，身份包装器透传免确认属性。
- 无需审批的成员使用非交互 permissive 模式，但黑名单、沙箱、显式 deny 和角色 strict 仍生效。
- 任务 `paths` 在首次派发前生成共享 Git 基线，支持安全的未跟踪文件；成员完成后自动提交。
- Integration 允许无关未跟踪文件存在，对基线文件做哈希校验后安全 fast-forward 发布。
- Windows 本地默认切到 coroutine；恢复旧 Team 时回收终端 worker、补 assignee 和基线，再启动可靠后端。
- 新增真实 Git 端到端测试：双成员并行修改同一未跟踪文件的不同 section，等待、自动提交、合并、发布全部成功。

以后写 spec 要补：
- 并发 Agent 功能的验收必须从自然语言请求一路跑到用户主工作区出现最终修改，不能把“任务已入队”当完成。
- 任务通知、任务分配和任务唤醒要分层；可靠性必须来自持久化状态，事件只用于降延迟。
- Worktree 输入基线、成员输出提交和主分支发布要作为一个事务链设计，并覆盖 dirty/untracked/ignored 文件。
- 非交互 worker 的权限模式必须单独验收真实 Write/Edit，不能只断言工具名可见。

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
14. 新增配置是否既支持主配置入口，又说明与用户级/项目级文件的覆盖优先级？
15. 网络/Provider 错误是否区分连接前失败、HTTP 错误和流式中途断开，并有清楚文案？
16. 真实用户查询项目结构时，是否会优先用读类工具，并避免只读 Bash 反复确认？
17. 写入配置文件后，是否用真实 loader 回读验证 Windows 路径和特殊字符不会破坏下次启动？
18. 配置项之间是否存在阈值、上限、余量关系，并有跨字段校验？
19. 四份 Mew Spec 文档是否都遵循 `AGENT.md` 的语言约定，而不是照搬技能模板语言？
20. 后台自动能力是否真正静默，且内部状态不会被模型工具误写或触发确认？
21. 新章节是否保留用户已经调整过的默认值和关键运行参数？
22. Windows subprocess 是否覆盖 UTF-8、中文、非本地编码字符和空输出？
23. 每个斜杠命令的裸命令、参数错误和 Provider 零调用是否都有测试？
24. 声明始终可用的系统工具是否同时通过工具暴露、模式检查和权限执行三层验证？
25. 临时复用 TUI Session 后，补全器、历史、模式和输入开关是否恢复？
26. 持久化 shell 命令是否覆盖多行内容并在写入后用真实 loader 回读？
27. Windows 用户生成的文本入口是否兼容 UTF-8 BOM？
28. 验收是否使用用户实际解释器，并把全局依赖错误与单文件解析错误分开？
29. 运行时注入的动态上下文是否在约定的第一条 Provider 请求中生效？
30. 后台任务的退出上限是否覆盖解释器退出阶段，而不只是管理器方法返回时间？
31. 修改核心 Builder 后是否立即验证返回值非空并跑完所有直接调用方？
32. 前台任务转后台后，按键监听、spinner 和临时终端模式是否立即释放？

## 维护约定

以后 HuiCode 开发中只要出现“已经按 Mew Spec 做完，但真实使用又返工”的问题，都要同步更新这份文档。记录时至少写清：

- 现象：用户看到的报错或不符合预期的行为。
- 根因：当初 spec、plan、task 或 checklist 漏掉了什么。
- 后来补救：代码、测试、文档或配置怎样修。
- 以后写 spec 要补：下一章可以直接复用的验收项。

如果问题涉及配置或密钥，文档只记录结构和规则，不记录真实 token、header、API key 或本地私有路径中敏感部分。

## 结论

HuiCode 这几轮最大的经验是：Coding Agent 的难点不在“能不能调 API”，而在协议历史、工具边界、安全执行、平台差异和用户可观测性。Mew Spec 对这类项目很有用，但前提是 spec 不能只写理想功能，要把真实模型会犯错、真实接口会挑剔、真实用户会怎么操作都写进去。
