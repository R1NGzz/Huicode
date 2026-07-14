# HuiCode Skill System Spec

## 背景

HuiCode 已具备 Agent Loop、工具系统、结构化系统提示、记忆、上下文管理和统一 Slash Command，但可复用任务仍主要依赖用户重复输入提示词。当前 `/review` 只是代码内硬编码的一段预设提示，无法由项目覆盖、无法携带辅助文件，也不能按任务限制工具或选择独立上下文。

本章要引入文件化 Skill 系统：用户用带 YAML frontmatter 的 Markdown 描述可复用 AI 操作，HuiCode 启动时只发现并注入名称与一句说明；模型判断需要时，通过系统级 `Skill` 工具按需加载完整 SOP。Skill 可以共享主对话执行，也可以在隔离对话中完成任务后把摘要回流；激活后的完整指令必须在每轮 Prompt 重建时保持高优先级，并收窄可见工具范围。

## 目标

- 把重复 AI 操作封装为可读、可编辑、可随项目分发的 Markdown Skill。
- 支持内置、用户级、项目级三级来源和确定性覆盖。
- 用“轻量目录先注入、完整 SOP 后加载”的两阶段机制控制 Token。
- 支持共享主历史和隔离子会话两种执行方式。
- 用 Skill 工具白名单提高工具选择准确率，并保证 Skill 只能收窄权限。
- 让有效 Skill 自动成为 Slash Command，并支持运行中热更新。
- 提供 commit、review、test 三个可直接使用和参考的内置样板。

## 存放位置与优先级

Skill 按以下优先级加载，高优先级同名 Skill 覆盖低优先级版本：

1. 项目级：`<workspace>/.huicode/skills/`
2. 用户级：`~/.huicode/skills/`
3. 内置：HuiCode 包内 `huicode/skills/builtin/`

支持两种布局：

- 单文件 Skill：`<root>/<name>.md`
- 目录型 Skill：`<root>/<package>/SKILL.md`

目录型 Skill 的 `SKILL.md` 是唯一入口；同目录下可以包含模板、示例、脚本和参考文档。加载完整 Skill 时要向模型提供 Skill 根目录，正文可以用相对路径引用这些资源。

同一层内如果多个文件声明相同 name，该层该 name 的候选全部视为冲突并跳过，同时给出 warning；随后允许回退到更低优先级的有效同名 Skill。单个文件的读取、frontmatter、字段或正文解析失败只跳过该文件，不阻断其他 Skill。

发现文件和目录型包时必须解析真实路径并确认入口仍在对应 skills 根目录内，符号链接不得借此逃出来源边界。

## Skill 文件格式

标准格式：

```markdown
---
name: review
description: 审查当前代码或改动，优先发现缺陷和回归风险
allowed_tools:
  - Read
  - Find
  - Search
  - Bash
mode: isolated
history_messages: 12
model: optional-model-name
---

你正在执行代码审查。

本次用户参数：{{args}}

先检查改动和相关代码，再按严重程度报告发现。
```

frontmatter 字段：

- `name`：必填，Skill 唯一名字，同时作为默认 Slash Command 名；必须满足现有命令名规范，只允许小写字母、数字、`-` 和 `_`。
- `description`：必填，非空单行说明；用于启动目录、`/help` 和 Tab 补全。
- `allowed_tools`：必填，字符串列表，可以为空；只声明该 Skill 可见的普通工具。
- `mode`：必填，只允许 `shared` 或 `isolated`。
- `history_messages`：可选，非负整数，默认 0；只控制 isolated 模式带入多少条最近历史，按协议安全消息组向前扩展。
- `model`：可选，非空模型名。shared 模式仅覆盖该 Skill 当前执行轮；isolated 模式覆盖整个子会话。protocol、base_url、api_key、headers 和 thinking 配置沿用主 LLM 配置。

正文必须非空，是激活后注入模型的 SOP。正文支持字面占位符 `{{args}}`，替换为本次工具调用或 Slash Command 传入的完整参数；不执行表达式、脚本或递归模板。未传参数时替换为空字符串。参数只作为数据替换，不能改变 Skill 元数据、工具白名单或执行模式。

## 两阶段加载

### 第一阶段：Skill 目录

启动和热更新后，只向模型注入有效 Skill 的：

- name
- description
- mode

目录使用非缓存的系统级补充上下文，例如：

```xml
<huicode_context type="skill_catalog" scope="session">
- commit [shared]: 生成并提交符合项目规范的 Git commit
- review [isolated]: 审查当前代码或改动，优先发现缺陷和回归风险
- test [isolated]: 识别并运行最相关的测试，汇总失败原因

需要使用某个 Skill 时，调用系统工具 Skill(name, arguments) 加载完整指令。
</huicode_context>
```

目录不得包含 Markdown 正文、辅助文件内容、完整工具白名单或隐私路径，避免启动时把所有 SOP 塞进上下文。

### 第二阶段：按需激活

新增系统级工具 `Skill`：

```json
{
  "name": "review",
  "arguments": "重点检查 Provider 工具历史"
}
```

模型调用后，HuiCode：

1. 按有效 Skill 目录查找 name。
2. 用 arguments 替换正文中的 `{{args}}`。
3. 把完整指令、来源和 Skill 根目录写入会话级激活状态。
4. 应用工具白名单和可选模型覆盖。
5. shared 模式继续当前 Agent Loop；isolated 模式启动独立 Skill Runner。

未知 Skill、解析后失效或热更新中被删除时，`Skill` 工具返回结构化失败，Agent Loop 不崩溃。

## 激活状态与 Prompt 注入

- 会话状态维护有序的 active skills 映射，按首次激活顺序渲染。
- 同一个 Skill 重复激活时不重复堆叠，而是用最新 arguments、正文和来源替换原激活项。
- 多个 Skill 可以同时激活；每个 Skill 的完整 SOP 使用独立标签块，不能拼成无边界文本。
- 激活块必须位于动态补充系统上下文最前面，早于环境信息、模式提醒、记忆索引和普通 Skill 目录。
- 每次 Agent 请求、上下文压缩后请求和工具结果回灌后的下一轮都重新从 active state 构建完整激活块。
- active skill 正文不写入用户消息，不进入稳定缓存模块，不由摘要改写。
- `/clear` 清空消息、计划和上下文时，同时清空 active skills、模型覆盖和 Skill 工具限制，但不删除 Skill 文件。

激活块示例：

```xml
<huicode_instruction type="active_skill" name="review" mode="isolated" priority="highest">
skill_root: C:/project/.huicode/skills/review
allowed_tools: Read, Find, Search, Bash
...替换参数后的完整 SOP...
</huicode_instruction>
```

## 工具白名单

- `allowed_tools` 在 Skill 发现和优先级覆盖完成后验证。
- 白名单名称通过 ToolRegistry 的主名称和 alias 解析；例如 `Glob` 可以解析为 `Find`。
- 有效 Skill 白名单中出现当前 ToolRegistry 不存在的工具时，启动立即以 Skill 配置错误退出，错误包含 Skill name、来源文件和缺失工具。
- 工具验证必须在默认工具和 MCP 工具全部注册后执行；因此 Skill 可以白名单指定已成功加载的 MCP 工具。
- MCP Server 失败且导致白名单工具不存在时同样视为启动错误，不允许悄悄扩大或忽略白名单。
- shared 模式当前可见普通工具为：基础模式工具集合与所有 active shared skills 白名单的交集。
- isolated 模式子会话普通工具为：父级模式限制与该 Skill 白名单的交集。
- Plan Mode 的只读集合始终参与交集，Skill 不得借白名单绕过 Plan Mode。
- 多个 active shared skills 同时存在时取白名单交集，不取并集；任何 Skill 都不能扩大其他已激活 Skill 的范围。
- 系统级 `Skill` 加载工具始终可见，不受 Skill 白名单、Plan Mode 或普通工具过滤影响。
- Skill Runner 内部执行普通工具时继续经过现有路径沙箱、危险命令黑名单、权限规则和人在回路，不新增权限旁路。

## 执行模式

### shared 模式

- 激活后继续使用当前 `AgentState.messages` 和当前 Agent Loop。
- `Skill` 工具结果回灌主历史，下一轮请求带完整激活 SOP 和收窄后的工具列表。
- Skill 最终回答、工具调用和结果都保留在主历史和当前 JSONL session。
- 如果 Skill 指定 model，从激活后的下一次 Provider 请求开始覆盖当前顶层用户轮，直到该轮自然 final、错误、取消或达到迭代上限；下一次普通用户轮恢复主配置模型。
- 通过 Slash Command 调用 shared Skill 时，HuiCode 直接激活 Skill，并把用户 arguments 作为该 Skill 的任务消息送入现有 Agent Loop。

### isolated 模式

- 创建独立 `AgentState`、独立消息列表和独立上下文计数，不修改主对话的工具调用序列。
- 子会话系统提示包含该 Skill 完整 SOP、Skill 根目录和父级环境摘要。
- `history_messages` 从主历史尾部选取目标数量，并扩展/截断到合法 tool_call/tool_result 边界；0 表示不带历史。
- 子会话工具只包含父级模式限制与 Skill 白名单的交集，加上系统级 `Skill` 工具。
- 可选 model 通过复制主 LLMConfig 并替换 model 创建 Provider；其他连接和 thinking 配置保持不变。
- 子会话沿用现有 Agent 最大迭代、取消、未知工具、空响应、权限和上下文安全网。
- 子会话自然结束时，把最终文本作为摘要回流；错误、取消或达到上限时回流结构化状态和已完成事实，不伪装成功。
- 模型通过 `Skill` 工具调用 isolated Skill 时，摘要作为该 tool_call 的 ToolResult 回灌主历史。
- 用户通过 Slash Command 调用 isolated Skill 时，在主历史和 session 中记录一条 Skill 请求和一条 assistant 摘要，使后续主模型知道执行结果，但不复制子会话完整过程。
- isolated Skill 可以调用其他 Skill，但嵌套深度最多 3 层；超限返回结构化错误，防止递归失控。

## 可选模型

- model 字段只替换模型名，不允许 Skill 文件覆盖协议、URL、密钥、headers、temperature、thinking 或上下文窗口。
- 创建覆盖 Provider 失败或模型请求失败时，只让当前 Skill 执行失败，不泄露认证信息，也不破坏主 Provider。
- shared 模式多个 Skill 同时激活且各自指定 model 时，以本轮最近一次显式调用/Slash Command 触发的 Skill model 为当前轮覆盖；其他 active Skill 只贡献 SOP 和白名单。
- Skill 执行结束后必须清除轮次模型覆盖，避免后续普通对话继续误用 Skill model。

## Slash Command 集成

- 每个优先级解析后的有效 Skill 自动注册为可见短命令 `/<name> [arguments]`。
- 命令说明来自 Skill description，参数提示统一为 `[arguments]`，命令类型为 PROMPT/SKILL 执行入口。
- shared Skill 命令激活 Skill 后进入主 Agent；isolated Skill 命令直接运行 Skill Runner 并显示/记录摘要。
- Skill 命令参与 `/help` 和 Tab 补全，热更新后帮助和补全同步变化。
- 核心 Slash Command 名称和隐藏兼容名称属于保留名称。项目或用户 Skill 与保留名称冲突时，启动立即报 Skill 命令冲突；热更新时拒绝整个新快照并继续使用上一份有效目录。
- 现有代码内 `/review` 提示词命令移除，改由内置 `review` Skill 注册。项目级或用户级 review Skill 可以按三级 Skill 优先级覆盖内置 review，而不会与核心命令冲突。
- 引入 Skill 后，上一章“十个公开命令固定不变”的约束被本章覆盖：核心公开命令不再包含硬编码 review，公开帮助由核心命令加当前有效 Skill 动态组成。

## 热更新

- HuiCode 在每次顶层用户输入分流前检查项目级和用户级 Skill 快照指纹；指纹至少覆盖入口路径、修改时间和文件大小。
- 发现变化时重新扫描、解析、覆盖、验证工具并构建命令快照。
- 热更新必须原子化：全部全局校验通过后才替换 catalog、Skill 命令和补全；工具缺失、核心命令冲突等全局错误会拒绝新快照并保留旧快照。
- 单个文件解析失败只从新快照跳过该文件，并产生可见 warning，不阻断其他有效 Skill 更新。
- 已激活 Skill 文件更新时，保留原 arguments 并用新正文重新渲染激活指令。
- 已激活 Skill 被删除且没有低优先级 fallback 时，自动停用并警告；若出现低优先级 fallback，则切换来源并重新渲染。
- 热更新不自动执行 Skill，不发起 Provider 请求，也不修改主消息历史。

## 内置样板

内置三个目录型 Skill，每个目录含 `SKILL.md`，可以附带示例或参考文件：

- `commit`：shared；allowed_tools 为 Read、Bash；检查状态和 diff，生成符合项目习惯的 commit，并继续经过权限确认。
- `review`：isolated；history_messages 默认 12；allowed_tools 为 Read、Find、Search、Bash；只读审查缺陷、回归、安全风险和测试缺口。
- `test`：isolated；history_messages 默认 6；allowed_tools 为 Read、Find、Search、Bash；识别并运行最相关测试，汇总失败和剩余风险。

内置 Skill 不写死 model。它们的内容既要可直接使用，也要作为用户编写 Skill 的简洁示例。

## 状态与可观测性

- 启动时显示 Skill 统计：有效数量、覆盖数量、跳过数量和 warning 数量，不打印完整 SOP。
- `/status` 增加 discovered、active、reload errors 和当前工具限制摘要。
- `Skill` 工具行显示 Skill name、mode 和来源层级；不得把完整 SOP 打印到普通 TUI。
- isolated 执行显示开始、结束和摘要，不把内部每条 thinking 默认灌入主界面。
- 解析 warning 必须包含来源文件和原因，但不得打印密钥或正文中的敏感内容。

## 功能需求

- F1：解析 YAML frontmatter 和 Markdown 正文，严格校验所有元数据字段。
- F2：支持单文件和目录型 Skill，目录型入口固定为 `SKILL.md`。
- F3：按项目、用户、内置三级发现并覆盖，同层重复和单文件错误可诊断且不阻断其他 Skill。
- F4：启动 Prompt 只注入有效 Skill 的名称、说明和 mode，不注入完整正文。
- F5：提供系统级 `Skill` 工具按需加载、替换参数和激活完整 SOP。
- F6：完整 active Skill 指令在每轮 Prompt 最前部重建，支持多个同时激活和重复激活替换。
- F7：Skill 白名单在 MCP 工具注册后校验，未知工具导致启动失败。
- F8：普通工具集合按模式和所有 active Skill 白名单取交集，系统 `Skill` 工具永远保留。
- F9：shared 模式复用主历史，isolated 模式使用独立历史并只回流摘要。
- F10：isolated 历史选择保持 Provider 工具消息配对合法，并限制嵌套深度。
- F11：可选 model 只覆盖模型名，并按 shared 当前轮或 isolated 子会话生效。
- F12：有效 Skill 自动注册 Slash Command，帮助和补全随热更新同步。
- F13：每次顶层输入前检测热更新，失败时原子保留上一有效快照。
- F14：`/clear` 清除激活 Skill、工具限制和轮次模型覆盖。
- F15：提供 commit、review、test 三个内置目录型样板。
- F16：现有硬编码 review 命令迁移为内置 Skill，允许同名上层 Skill 覆盖。
- F17：Skill 执行继续遵守权限、路径沙箱、黑名单、上下文和 Agent 停止条件。
- F18：README 说明格式、目录、优先级、两阶段加载、执行模式、白名单、命令和热更新。

## 非功能需求

- N1：发现目录和 catalog 注入必须轻量，不读取或注入辅助文件正文。
- N2：单个 Skill 坏文件不影响整体可用；全局不变量错误必须清晰失败或原子回滚。
- N3：Skill 文件和热更新不得覆盖 API key、Provider URL、权限规则或其他安全配置。
- N4：所有来源路径必须经过真实路径边界检查，防止符号链接逃逸。
- N5：Skill 工具结果、isolated 摘要和 warning 必须结构化、可诊断且不泄露完整隐藏 SOP。
- N6：共享和隔离执行必须保持 OpenAI/Anthropic tool_call/tool_result 历史合法。
- N7：热更新检查不得发起网络请求或明显阻塞每次输入；无变化时快速返回。
- N8：新增代码和文档使用中文，沿用 Python 3.11、unittest、Rich 和 prompt_toolkit 技术栈。

## 非目标

- 不实现 Skill 市场、远程下载、发布、签名或版本解析。
- 不实现团队 Skill 同步或云端目录。
- 不允许 Skill 自定义新的 Tool 实现；辅助脚本仍通过现有工具执行。
- 不实现任意模板语言、条件表达式或代码执行式参数渲染。
- 不实现向量检索或基于语义自动加载 Skill 正文。
- 不实现 Skill 级独立 API key、base_url、headers 或权限模式。
- 不实现全屏 Skill 管理 UI。

## 验收标准

- AC1：单文件和目录型 Skill 都能解析；frontmatter 缺失、字段类型错误、正文为空或路径逃逸时只跳过坏 Skill并报告 warning。
- AC2：项目级同名 Skill 覆盖用户级和内置，用户级覆盖内置；同层重复时该层冲突候选跳过并可回退低层版本。
- AC3：普通启动 Prompt 只包含 name、description、mode，不包含 SOP 正文或辅助文件内容。
- AC4：模型调用 `Skill(name, arguments)` 后，`{{args}}` 被原样替换，完整 SOP 从下一轮起出现在最高优先级 active block。
- AC5：重复激活同名 Skill 不重复堆叠；多个不同 Skill 同时激活并在每轮、压缩后和工具回灌后持续存在。
- AC6：allowed_tools 中存在未知本地/MCP 工具时启动失败，并定位 Skill 和缺失工具；`Skill` 工具本身始终可见。
- AC7：Plan Mode、单个 Skill 和多个 Skill 的工具集合分别按交集收窄，任何 Skill 都不能扩大工具或绕过权限。
- AC8：shared Skill 的消息、工具调用、结果和 final 保留在主历史；当前轮 model 覆盖结束后恢复主模型。
- AC9：isolated Skill 使用独立 AgentState，按 history_messages 带入协议安全历史，主历史只收到请求与摘要或 ToolResult。
- AC10：isolated Skill 的错误、取消、迭代上限和嵌套深度超限作为结构化失败回流，不崩溃主 Agent。
- AC11：有效 Skill 自动出现在 `/help` 和 Tab 补全；Slash Command 可执行 shared/isolated Skill，参数保留大小写。
- AC12：项目或用户 review 覆盖内置 review；硬编码 REVIEW_PROMPT 和旧 review handler 被移除。
- AC13：新增、修改、删除 Skill 后，下一次顶层输入前目录、命令和 active state 原子更新；非法全局快照保留旧版本。
- AC14：`/clear` 后 active Skill 为空、工具列表恢复基础模式、模型覆盖清除，但 Skill 文件和 catalog 仍存在。
- AC15：内置 commit、review、test 可被发现、通过工具校验并完成各自样板流程。
- AC16：`/status` 和启动摘要展示 Skill 数量、激活项和 reload 状态，不泄露完整 SOP 或 secret。
- AC17：OpenAI 和 Anthropic 在 shared、isolated、工具加载和摘要回流后仍保持合法消息序列。
- AC18：全量单元测试、Python 编译、diff 检查和可用环境下的 tmux 端到端验收通过，README 与实现一致。
