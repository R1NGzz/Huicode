# HuiCode 子 Agent 系统 Spec

## 背景

HuiCode 已经具备主 Agent Loop、工具、权限、上下文管理、记忆、Skill 和 Hook，但复杂任务仍全部堆积在主对话中。调查、审查、测试等子任务会持续增长主历史，工具结果也会污染后续判断；耗时任务还会占住 TUI，使用户无法继续输入。

本章引入统一的子 Agent 系统。主 Agent 通过一个始终存在且 Schema 稳定的 `Agent` 工具委派任务。定义式子 Agent 从干净对话和固定角色开始；Fork 式子 Agent 从父历史的完整协议边界分叉，并尽量复用父请求前缀的缓存。每个子 Agent 独立维护运行状态和权限追踪，共享 Provider、Hook、工具基础设施与工作区文件系统。

子 Agent 可以在前台短暂运行，也可以进入后台。后台结果只进入线程安全的系统结果队列：TUI 立即通知用户，下一次主 Agent 请求自动注入结果，但系统不会因为后台任务完成而自行调用模型。

## 目标

- 让主 Agent 使用一个稳定工具完成定义式和 Fork 式委派。
- 用可覆盖的 Markdown 角色定义复用调查、审查、测试等工作方式。
- 隔离父子上下文、权限状态、文件读取缓存和 Token 统计。
- 让 Fork 式任务继承协议安全历史，并保持缓存复用资格。
- 支持显式后台、超时自动后台和 `Ctrl+B` 手动切后台。
- 让后台任务状态、结果和用量对用户与主 Agent 都可观察。
- 通过多层工具过滤和 Hook 递归保护阻止无限嵌套与后台越权。

## 术语与既定决策

- **主 Agent**：直接处理用户普通输入的 Agent。
- **定义式子 Agent**：使用预定义角色，从空白消息历史开始执行任务。
- **Fork 式子 Agent**：复制父历史到最近完整协议边界后执行任务。
- **前台任务**：主 Agent 当前等待其结果的子 Agent 任务。
- **后台任务**：主 Agent 不等待，任务完成后通过结果队列通知。
- 后台结果不自动触发模型请求，只在下一次主 Agent 请求时注入。
- 前台定义式任务运行满 10 秒后自动转后台；该阈值可配置。
- 用户可在前台子 Agent 运行时按 `Ctrl+B` 手动转后台。
- Fork 式任务从创建起强制后台。
- 角色模型只写 `inherit`、`haiku`、`sonnet` 或 `opus`；后三者必须由主配置映射为真实模型名。

## 统一 Agent 工具

主 Agent 始终看到一个名为 `Agent` 的系统工具。角色数量、后台任务数量和当前模式变化不得改变该工具的名称、描述或参数 Schema，以免破坏工具列表稳定性和 Prompt Cache 前缀。

工具参数包含：

- `type`：必填，值为 `defined` 或 `fork`。
- `task`：必填，描述子任务目标和预期产出。
- `role`：定义式必填，Fork 式不得使用。
- `background`：定义式可选；为 true 时显式进入后台。Fork 式无论该值为何都强制后台。

定义式前台任务若在阈值内完成，`Agent` 工具直接返回最终摘要、停止原因和用量；显式后台、自动转后台、手动转后台和 Fork 式调用立即返回任务 id 与当前状态。未知类型、未知角色、缺失任务或不兼容参数返回结构化工具错误，不得让主 Agent Loop 崩溃。

`Agent` 工具在主 Agent 的 DEFAULT 和 PLAN 模式下都保持可见。PLAN 模式启动的子 Agent 只能使用父 Agent 当时可见的只读工具，角色或权限模式不得把能力重新放宽。

## 角色定义与加载

一个角色由带 YAML frontmatter 的 Markdown 文件定义。正文是伴随该子 Agent 整个生命周期的系统级角色指令。

加载优先级从高到低为：

1. 项目级角色
2. 用户级角色
3. 内置角色
4. 插件角色

同名角色由高优先级来源整体覆盖。角色入口按以下位置发现：

```text
项目级：<workspace>/.huicode/agents/*.md
用户级：~/.huicode/agents/*.md
内置：HuiCode 随包角色目录
插件：已安装插件声明的角色目录
```

基础格式：

```markdown
---
name: explorer
description: 调查项目结构、调用链和现有约定
allowed_tools:
  - Read
  - Find
  - Search
denied_tools:
  - Write
  - Edit
  - Bash
model: haiku
max_iterations: 20
permission_mode: strict
---
你是一个只读代码调查 Agent。先定位事实，再给出带文件依据的结论。
不要修改文件，不要把猜测写成事实。
```

字段语义：

- `name`：必填，角色唯一名。
- `description`：必填，供主 Agent 选择角色的一句话说明。
- `allowed_tools`：必填白名单；空列表表示不允许普通工具。
- `denied_tools`：可选黑名单；与白名单冲突时 deny 优先。
- `model`：必填，只允许 `inherit`、`haiku`、`sonnet`、`opus`。
- `max_iterations`：必填，必须处于系统允许范围内且不得超过全局上限 50。
- `permission_mode`：必填，只允许 `strict`、`default`、`permissive`。
- Markdown 正文：必填，作为角色系统指令持续注入，不作为用户消息。

单个文件的 Markdown/frontmatter 语法损坏时跳过该文件并显示来源警告，不阻断其他来源。以下安全或全局一致性错误必须阻止启动：同一来源重复角色名、未知工具、角色名非法、模型别名未映射、非法轮次、非法权限模式、空正文。

启动时显示有效角色数、覆盖数、跳过数和来源摘要。`/agents` 列出角色，`/agents <name>` 显示来源、模型别名、工具限制、轮次和权限模式，但不输出完整正文。

## 定义式执行

定义式子 Agent 从空白消息历史启动，只接收：

- HuiCode 稳定的身份、安全和工具约束。
- 当前工作区环境与项目指令文件。
- 该角色的完整正文。
- 本次 `task` 用户消息。
- 由共享 Hook 引擎针对该子 Agent scope 动态注入的补充指令。

它不继承父对话消息、父 active Skill、父自动记忆索引、父轮次临时 Hook 指令或尚未消费的后台结果。角色正文在该任务的每次模型请求中持续存在。

定义式子 Agent 的 Provider 协议、base URL、API key、headers、thinking 与主配置一致；`inherit` 使用主模型，模型别名只替换实际模型名。

## Fork 式执行与缓存

Fork 式子 Agent 从父对话最近一个完整协议边界复制历史。创建 Fork 的当前 assistant 消息仍含尚未配对的 `Agent` tool call，因此不得复制该不完整工具组；历史必须截止到它之前最近一个 `tool_use/tool_result` 完整边界，再追加 Fork 的 `task` 用户消息。

Fork 继承父 Agent 创建时实际可见的工具集合、模式、项目指令和稳定系统提示前缀，然后再应用子 Agent 全局禁止项与后台白名单。Fork 不加载定义式角色正文，也不继承父 active Skill 的可变运行状态。

在 Provider 支持缓存时，Fork 首次请求应保持父请求的稳定系统前缀和历史前缀字节一致，使其具备 Prompt Cache 命中资格。系统继续解析并展示 Provider 返回的 cache read/create usage；无法保证第三方 Provider 一定命中，但必须能验证请求前缀一致且缓存字段可观察。

Fork 始终后台运行，不能请求前台等待，也不能通过 `Ctrl+B` 再次切换状态。

## 状态隔离与共享基础设施

每个子 Agent 独立拥有：

- 消息历史和上下文压缩状态。
- 权限模式、规则快照、会话临时规则与拒绝计数。
- 文件读取缓存；父子和不同子 Agent 之间不得复用缓存内容。
- Token usage、缓存 usage、迭代数、停止原因和错误状态。
- Skill、Hook 轮次状态与取消标记。

所有 Agent 共享：

- Provider 连接配置与可复用客户端基础设施。
- 只读的工具注册信息和 MCP 连接。
- Hook 规则引擎与 Hook 日志。
- 当前工作区文件系统。
- 项目级权限规则、黑名单和路径沙箱定义。

共享文件系统意味着子 Agent 的文件修改对其他 Agent 立即可见。本章不提供 Worktree 隔离，因此后台工具白名单默认只包含 `Read`、`Find`、`Search`；用户显式放宽后需要自行承担并发写冲突风险。

Hook 事件的 `agent_scope` 必须区分 `main`、`subagent:defined:<role>:<task-id>` 和 `subagent:fork:<task-id>`。一个子 Agent 的 turn/next-request Hook 状态不得进入父 Agent 或其他任务。

## 工具与权限多层防线

子 Agent 最终工具集按以下顺序只减不增：

1. 父 Agent 创建任务时实际可见的工具集合。
2. 全局禁止工具：至少包括 `Agent` 和 `Skill`，所有子 Agent 都不可见，配置不能重新放开。
3. 定义式角色的 `allowed_tools` 白名单。
4. 定义式角色的 `denied_tools` 黑名单。
5. 进入后台后的全局后台白名单。
6. 当前 PLAN Mode、权限规则、危险命令黑名单和路径沙箱。

Fork 没有角色白黑名单，使用父可见工具集减去全局禁止项和后台白名单。后台转换只影响转换后的后续工具调用；已经开始执行的单个工具不会被强行中止。

定义式权限模式取“父当前模式”和“角色模式”中更严格者，角色不能借 `permissive` 绕过父 `strict/default`。Fork 复制父权限模式和当前规则快照。父子权限对象随后独立变化，子 Agent 不得向父会话写入 once/session/always 授权。

子 Agent 使用非交互确认器跑到底：需要人工确认的调用直接形成结构化权限拒绝并回灌子 Agent，让模型自行调整，不弹 TUI 权限询问。不可配置黑名单和路径沙箱始终优先。

## 跑到底与停止条件

子 Agent 使用现有 ReAct 语义非交互执行：模型请求工具时继续循环，模型不再请求工具时完成。停止条件包括最终回答、角色最大轮次、连续未知工具、取消、Provider/流错误和不可恢复的运行异常。

最大轮次到达、权限拒绝或单个工具失败不会击穿主 Agent。任务管理器记录清晰状态和最后错误；前台调用返回结构化失败，后台任务发送失败通知并保留详情。

## 前台与后台切换

定义式任务支持三种进入后台的方式：

1. **显式指定**：`background: true`，创建后立即返回 task id。
2. **超时自动**：前台运行达到 `foreground_timeout_seconds`，默认 10 秒，当前任务继续在后台运行，`Agent` 工具返回 task id。
3. **手动切换**：交互式 TUI 等待前台子 Agent 时按 `Ctrl+B`，立即恢复主界面输入，任务继续后台运行。

非交互 stdin 环境没有 `Ctrl+B` 监听，但显式和超时路径仍生效。`Ctrl+C` 保持现有取消语义，不得被误识别为转后台。

任务状态至少区分 queued、running_foreground、running_background、completed、failed、cancelled。后台管理器使用有界 worker 数；超过并发数的任务保持 queued，不创建无限线程。

## 后台结果回流

后台任务完成或失败时：

1. TUI 显示一条不会破坏当前输入行的通知，包含 task id、类型、角色、状态、耗时和摘要。
2. 完整结果、停止原因和 usage 保存在当前进程的任务管理器中。
3. 有界摘要进入主 Agent 的系统级结果队列。
4. 下一次主 Agent Provider 请求把所有待交付结果按完成顺序注入 `<huicode_context type="subagent_results">` 动态上下文。
5. 结果不得伪装成用户消息，不自动触发模型请求，也不直接修改主消息历史。
6. 只有主 Agent 成功收集完一次完整模型响应后才把已注入结果标记为已交付；请求失败时保留，供下次重试。

任务结果在当前 HuiCode 进程内可通过 `/tasks` 列表查看，通过 `/tasks <task-id>` 查看完整摘要、状态、停止原因、迭代和 usage。`/status` 与底部状态栏显示 queued/running/ready/failed 数量。

`/clear` 取消当前会话的未完成子 Agent、清空任务与待交付结果，防止旧任务污染新上下文。`/exit` 或 EOF 停止接收新任务，请求取消运行中任务并有界等待；未结束任务标记 cancelled/abandoned，不能无限拖住进程。本章不恢复 `/resume` 前的后台任务。

## Hook SubAgent 动作对接

上一章的 Hook `subagent` 占位在本章接入真实后台定义式子 Agent。Hook 动作可指定角色和任务；未指定角色时使用内置 `general` 角色。Hook 子 Agent 始终后台运行，不允许 Fork。

为防止递归，来自任何 `subagent:*` scope 的 Hook 事件即使匹配 subagent 动作，也只记录 `skipped: recursion_guard`，不得再次创建任务。Hook 提交失败只写 Hook 日志，不改变主 Agent stop reason。

## 主配置

主配置增加：

```yaml
subagents:
  foreground_timeout_seconds: 10
  max_background_tasks: 4
  shutdown_wait_seconds: 2
  background_allowed_tools:
    - Read
    - Find
    - Search
  model_aliases:
    haiku: deepseek-chat
    sonnet: deepseek-reasoner
    opus: deepseek-reasoner
```

模型别名只替换 `model`；protocol、base URL、API key、headers、thinking、context 与主配置保持一致。角色引用未映射别名时启动失败，不静默回退。配置中的未知工具、非法时间、非正整数并发数或重复模型别名必须给出明确字段错误。

## 功能需求

- F1：系统必须始终向主 Agent 暴露一个 Schema 稳定的 `Agent` 工具，用 `type` 分流定义式与 Fork 式调用。
- F2：系统必须从插件、内置、用户和项目来源加载 Markdown 角色，并按既定优先级覆盖和校验。
- F3：定义式子 Agent 必须从干净消息历史和固定角色启动，不继承父对话运行状态。
- F4：Fork 式子 Agent 必须从完整协议边界继承父历史和工具快照，并保持缓存复用资格。
- F5：父子 Agent 必须隔离消息、上下文、权限、读缓存、Token 和临时状态，同时共享 Provider、Hook、工具连接和工作区。
- F6：系统必须按父能力、全局禁止、角色白黑名单、后台白名单、模式和权限逐层收窄工具。
- F7：子 Agent 必须非交互跑到底，并把失败或拒绝留在自己的循环中处理。
- F8：后台任务管理器必须追踪状态、结果、停止原因、迭代、耗时和 usage，并限制并发。
- F9：定义式任务必须支持显式后台、10 秒自动后台和 `Ctrl+B` 手动后台；Fork 必须强制后台。
- F10：后台结果必须通知 TUI，并在下一次主请求中以一次性系统上下文回流，不自动调用模型。
- F11：系统必须提供角色和任务的本地可观测入口，并在状态栏和 `/status` 展示任务摘要。
- F12：Hook subagent 动作必须接入真实定义式后台任务，并阻止子 Agent scope 递归创建。
- F13：模型别名、前台阈值、后台并发、关闭等待和后台工具白名单必须可配置并集中校验。

## 非功能需求

- N1：未使用 `Agent` 工具时，现有对话、工具、权限、上下文、记忆、MCP、Slash Command、Skill 和 Hook 行为保持不变。
- N2：后台线程不得直接修改主消息历史或 Rich/prompt_toolkit 输入缓冲区。
- N3：相同父状态、角色和任务应得到确定的工具集合、权限模式和 Fork 边界。
- N4：`Agent` 工具 Schema、稳定系统提示前缀和角色轻量目录应控制缓存波动。
- N5：后台任务异常不得让主 Agent Loop 或 TUI 崩溃，进程退出必须有界。
- N6：任务结果、错误和 usage 必须脱敏，不记录 API key、Authorization、Cookie 或 thinking 原文。
- N7：Windows 与常见 POSIX 终端都支持显式/超时后台；`Ctrl+B` 在支持交互键监听的终端生效并有清楚降级。

## 不在本章范围

- 为子 Agent 创建独立 Git Worktree、容器或文件系统快照。
- 多 Agent 团队、角色间通信、投票、计划协调或依赖图编排。
- 后台任务、结果队列和 usage 的跨会话持久化或 `/resume` 恢复。
- 子 Agent 之间直接通信或互相创建任务。
- 远程分布式 worker、资源配额、优先级调度和抢占式终止。
- 自动选择或训练角色、角色市场和远程角色版本管理。
- 保证第三方 Provider 一定产生 Prompt Cache 命中。

## 验收标准

- AC1（F1）：DEFAULT/PLAN、零角色/多角色和有无后台任务时，主请求中的 `Agent` 工具名称与 Schema 完全一致；两种 type 均能分流，非法参数返回结构化错误。
- AC2（F2、F13）：四个来源出现同名与不同名角色时，项目级高于用户级、高于内置、高于插件；格式损坏文件被警告跳过，重复名、未知工具和未映射模型别名阻止启动并指出来源字段。
- AC3（F3）：定义式任务的第一条请求不含父消息、active Skill、父记忆索引或待交付结果，但含项目指令、角色正文和任务；角色正文持续出现在后续请求。
- AC4（F4）：Fork 在当前未配对 Agent tool call 之前截断，复制的每个 tool_use 都有对应 tool_result；首次请求与父请求的稳定系统/历史前缀一致，并能展示 cache usage 字段。
- AC5（F5）：并行运行两个子 Agent 时，消息、权限临时规则、读缓存、迭代和 Token 互不串写；文件修改、MCP 与 Hook 基础设施保持共享。
- AC6（F6）：角色白名单、黑名单、父 PLAN 模式、后台白名单和全局禁止项逐层取交集；`Agent`、`Skill` 在任何子 Agent 中都不可见，角色 permissive 不能放宽父 default/strict。
- AC7（F7）：子 Agent 无工具调用时完成；权限待确认自动拒绝并允许模型调整；工具失败、最大轮次和 Provider 错误形成任务失败结果而不影响主 Agent final。
- AC8（F8、F11）：`/tasks`、`/tasks <id>`、`/status` 和状态栏能观察 queued/running/completed/failed、摘要和独立 usage；后台并发超过上限时任务排队。
- AC9（F9）：定义式任务分别通过 `background:true`、达到 10 秒和 `Ctrl+B` 进入后台并返回 task id；短任务前台直接回结果；Fork 从创建起始终后台。
- AC10（F10）：后台完成时 TUI 立即通知但 Provider 调用数不增加；下一次主请求包含一次性 `subagent_results` 系统上下文且用户历史无伪造消息；请求失败后结果仍在，成功响应后才消费。
- AC11（F11）：`/agents` 能列出有效角色和来源，`/agents <name>` 显示安全元数据；启动摘要显示有效、覆盖、跳过和来源数量。
- AC12（F12）：主 scope 的 Hook subagent 动作创建真实定义式后台任务；同一规则在子 Agent scope 只记录 recursion_guard，任务数不递增。
- AC13（F8、F10、F13）：`/clear` 清理任务和待交付结果；`/exit`/EOF 在配置等待上限内结束；未完成任务不跨重启恢复。
- AC14（N1-N7）：子 Agent 专项、完整回归、实际用户 Python、真实 CLI 输入流、UTF-8 角色文件和 Windows 非交互降级验收全部通过；无关用户文件不进入提交。
