# HuiCode

HuiCode 是一个终端 AI 编程助手。当前阶段已经具备交互式对话、流式输出、工具调用、Agent Loop、Plan Mode、上下文管理、记忆、MCP、Skill、Rich Markdown 渲染、结构化系统提示，以及五层权限系统。

## 能力概览

- 交互式命令行对话
- SSE 流式输出
- 多轮上下文记忆
- OpenAI 兼容协议
- Anthropic Claude 兼容协议
- Claude extended thinking 配置与 thinking 回传
- 统一 Provider 抽象
- 统一工具系统
- 多轮 ReAct Agent Loop
- `/plan` 只读规划模式
- `/do` 返回默认执行模式
- Rich Markdown 输出渲染
- prompt_toolkit 交互输入增强
- 结构化系统提示与缓存 usage 可观测
- 五层权限系统
- MCP 客户端工具接入
- 两层上下文压缩
- 统一 Slash Command 注册、分发和 Tab 补全
- 两阶段加载的 Skill 系统与 isolated 子会话

## 工具系统

模型可以请求 HuiCode 执行六个核心工具：

- `Read`：读取 workspace 内文本文件
- `Write`：写入 workspace 内文本文件
- `Edit`：按原文唯一匹配替换文本
- `Bash`：在 workspace 内执行命令并返回退出码、标准输出和标准错误
- `Find`：按模式查找文件
- `Search`：搜索代码内容

工具调用会在 TUI 中显示为 Claude Code 风格工具行：

```text
● Read(huicode/cli.py)
  ⎿  ok, 83 lines, 2870 chars
```

当模型一次返回多个工具调用时，读类工具会优先并发执行，副作用工具会串行执行。工具结果会回灌到对话历史里，模型可据此继续下一轮。

## MCP 客户端

HuiCode 启动时会读取 MCP 配置，初始化外部 MCP Server，并把远端工具包装成普通 HuiCode 工具注册到工具中心。模型使用时不需要区分本地工具和 MCP 工具。

MCP 可以直接写在主配置 `huicode.yaml` 的 `mcp` 字段里，也可以继续使用独立配置文件。独立文件分两层：

```text
用户级：~/.huicode/mcp.yaml
项目级：<workspace>/.huicode-mcp.yaml
```

三处配置都使用顶层 `mcp` 映射。每个 key 是 server 名称；同名 server 按“用户级默认 < `huicode.yaml` < 项目级覆盖”的顺序合并，不同名 server 会合并。`env` 和 `headers` 的值支持 `${VAR}` 环境变量展开，变量未定义会作为配置错误处理。`/config` 只显示 server 和工具数量，不会打印 env 或 header 的具体值。

stdio server 示例：

```yaml
mcp:
  local_echo:
    type: stdio
    command: python
    args:
      - ./scripts/mcp_echo_server.py
    env:
      ECHO_PREFIX: ${ECHO_PREFIX}
```

HTTP server 示例：

```yaml
mcp:
  remote_search:
    type: http
    url: ${MCP_URL}
    headers:
      Authorization: Bearer ${MCP_TOKEN}
```

写在 `huicode.yaml` 里的 Context7 示例：

```yaml
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com/v1
api_key: sk-ant-...
mcp:
  context7:
    type: stdio
    command: npx.cmd
    args:
      - "-y"
      - "@upstash/context7-mcp"
```

远端工具会以稳定公开名称注册：

```text
mcp__<server>__<tool>
```

例如 `local_echo` server 暴露的 `echo` 工具会注册为 `mcp__local_echo__echo`。调用时 HuiCode 仍会把 MCP 原始工具名回传给远端 server。

当前 MCP 客户端支持：

- stdio 子进程传输
- Streamable HTTP 的 JSON-RPC POST
- 初始化握手、`tools/list`、`tools/call`
- `MCP-Session-Id` 保存和复用
- 单个 server 失败隔离，不影响其他 server 和本地工具

本阶段暂不支持 MCP resources、prompts、sampling、server 健康检查、自动重连，也不把 MCP 工具标记为只读能力。因此 Plan Mode 下 MCP 工具默认会被拒绝，后续章节再补细粒度安全声明。

## 上下文管理

HuiCode 会在每次请求模型前管理上下文预算，尽量在不改写用户原话的前提下，让长对话继续可用。

策略分两层：

- 轻量预防：优先压缩工具结果。单个工具结果过大时，完整结果写入 `.huicode/tool-results/`，对话里只保留摘要、预览和相对路径。
- 重量兜底：整体历史逼近窗口上限时，把较早消息压成结构化摘要，近期消息原文保留。

整体摘要不是文件事实来源。摘要只用于导航和继续任务；如果模型需要文件细节、命令输出或完整工具结果，必须重新读取文件或重新调用工具，不能凭摘要脑补内容。

当前实现使用近似 token 估算：

- 优先锚定上一次 API usage 的 `input_tokens` 或 `prompt_tokens`
- 对后续增量按字符数近似估算
- `auto_margin_tokens`、`manual_margin_tokens` 和 `recent_keep_tokens` 必须小于 `window_tokens`；否则自动压缩触发线会失效。

手动命令：

```text
/compact
/context
```

- `/compact`：手动触发上下文压缩。
- `/context`：查看当前上下文窗口、估算锚点、摘要次数、失败次数和熔断状态。

默认会话内工具结果落盘目录：

```text
<workspace>/.huicode/tool-results/
```

`/config` 会显示简要上下文状态，例如 `context_window`、`context_summary_count` 和 `context_fuse`，但不会显示 secret 或落盘文件内容。

## 权限系统

HuiCode 在工具执行前会经过五层防御：

1. 危险命令黑名单：例如递归强删、`git reset --hard`、`git clean -fdx`、磁盘格式化、大范围权限破坏等会被硬拦截。
2. 路径沙箱：文件路径会先解析绝对路径、`..` 和符号链接，再判断是否仍在 workspace 内。
3. 会话级规则：用户在当前会话中选择 `session` 后生成的临时规则，优先级最高。
4. 持久规则：本地级高于项目级，项目级高于用户级。
5. 权限模式和人在回路：规则未命中时，根据模式决定拒绝、确认或放行。

权限模式：

- `strict`：规则未命中时拒绝。
- `default`：低风险只读调用默认放行，副作用或风险操作需要确认。
- `permissive`：规则未命中时默认放行，但黑名单和路径沙箱仍然硬拦截。

查看或切换当前会话模式：

```text
/permissions
/perm
/permissions strict
/perm strict
/permissions default
/permissions permissive
```

确认提示支持四种输入：

- `deny`：拒绝本次工具调用
- `once`：仅本次放行
- `session`：本会话同类调用放行
- `always`：永久写入本地级规则

快捷输入同样可用：`d/o/s/a` 分别对应 `deny/once/session/always`，直接回车默认 `deny`。

规则文件路径：

```text
用户级：~/.huicode/permissions.yaml
项目级：<workspace>/.huicode-permissions.yaml
本地级：<workspace>/.huicode-permissions.local.yaml
```

规则格式：

```yaml
mode: default
rules:
  Bash(git *): allow
  Bash(rm -rf *): deny
  Read(src/**/*.py): allow
  Edit(README.md): allow
```

每条规则只能是 `allow` 或 `deny`。规则按精确匹配和 glob 匹配工具参数；`Bash` 匹配命令文本，文件工具匹配路径。

## Slash Command

斜杠命令在用户回车后先于 Agent 解析。本地命令和状态命令不会进入 Agent Loop，也不会消耗模型 Token。Skill 会自动注册为斜杠命令，并按 shared 或 isolated 模式执行。

命令由统一注册中心提供元数据、帮助、别名、分发和 Tab 补全。命令名大小写不敏感，未知命令会提示 `/help`，不会被当成普通问题发给模型。启动时如果名称或别名冲突，HuiCode 会直接报告命令注册错误并退出。

九个核心公开命令：

```text
/help [command]
/compact
/clear
/plan
/do
/session [resume <session-id>|clean]
/memory [update|rebuild]
/permission [strict|default|permissive]
/status
```

有效 Skill 会动态追加到公开命令，例如内置的 `/commit [arguments]`、`/review [arguments]` 和 `/test [arguments]`。项目级或用户级同名 Skill 可以覆盖内置版本。

命令分四类：

- 本地命令：查询状态或执行已有管理流程，不进入 Agent。
- 状态命令：改变模式、权限或当前会话状态，并立即刷新状态栏。
- 提示词命令：把预设提示送入正常 Agent Loop，供后续扩展使用。
- Skill 命令：加载 Skill SOP，shared 模式进入主 Agent，isolated 模式只把摘要回流主历史。

交互终端底部状态栏会显示 `[DEFAULT]` 或 `[PLAN]`，以及最近 Token、权限模式和记忆状态。非交互回退输入会在 `You>` 前显示相同模式标记。Tab 单匹配直接补全，多匹配显示候选菜单；隐藏兼容命令不参与补全。

## Skill 系统

Skill 把可复用的 AI 操作保存成带 YAML frontmatter 的 Markdown。HuiCode 启动时只把名称、说明和执行模式放进轻量目录；模型真正需要时再调用系统级 `Skill` 工具加载完整 SOP，避免把所有指令一次塞进上下文。

Skill 按以下优先级覆盖：

```text
项目级：<workspace>/.huicode/skills/
用户级：~/.huicode/skills/
内置：huicode/skills/builtin/
```

支持单文件 `<name>.md` 和目录型 `<package>/SKILL.md`。目录型 Skill 可以附带模板、示例、脚本和参考文档；入口必须留在对应 skills 根目录内，符号链接不能用于路径逃逸。

示例：

```markdown
---
name: explain-api
description: 调查并解释指定 API 的调用链
allowed_tools:
  - Read
  - Find
  - Search
mode: shared
history_messages: 0
model: optional-model-name
---
先定位 API 定义、调用方和测试，再解释数据流。

用户关注点：{{args}}
```

字段说明：

- `name`：唯一小写名称，同时作为 `/<name>` 命令。
- `description`：启动目录、`/help` 和 Tab 补全显示的一句话说明。
- `allowed_tools`：普通工具白名单，只能收窄能力，不能绕过 Plan Mode、权限、黑名单或路径沙箱。
- `mode`：`shared` 复用主历史；`isolated` 使用独立 AgentState，只回流摘要。
- `history_messages`：isolated 模式带入的最近消息数，工具调用与结果会按协议安全边界成组保留。
- `model`：可选，只覆盖模型名；URL、密钥、headers、thinking 和上下文配置继续沿用主配置。
- 正文：完整 SOP；`{{args}}` 会替换为工具调用或 Slash Command 的原始参数。

多个 active shared Skill 同时存在时，普通工具取所有白名单的交集；Plan Mode 再与只读工具取交集。系统 `Skill` 加载工具始终可用，但 Skill 内执行 Read、Bash 等普通工具仍走现有权限系统。

每次顶层输入前 HuiCode 会检查项目级和用户级 Skill 是否变化。合法更新会原子刷新目录、命令和 active SOP；未知工具或命令冲突会保留上一份有效快照，并在 `/status` 显示 reload error。`/clear` 会清除 active Skill、工具限制和当前轮模型覆盖，但不会删除 Skill 文件或目录。

## Agent Loop

普通输入会进入多轮 ReAct 流程：

1. 模型产出文本、thinking 或工具调用。
2. HuiCode 执行工具并显示结果摘要。
3. 工具结果回灌到历史。
4. 模型继续，直到给出最终回答或触发停止条件。

权限拒绝会作为结构化工具结果回灌给模型，Agent Loop 不会因为单次拒绝而崩溃。

停止条件包括：模型不再请求工具、达到默认 50 轮迭代上限、用户中断、连续未知工具达到上限、Provider 或流式解析出错。

## Plan Mode

`/plan` 只负责进入 `[PLAN]`，之后的普通输入只暴露读类工具并用于调查、规划。`/do` 只负责返回 `[DEFAULT]`；它不会自动执行最近计划，也不会请求模型。返回默认模式后，再输入明确任务才会使用完整工具集执行。

```text
[DEFAULT] You> /plan
已进入 [PLAN]，后续普通输入只使用读类工具。

[PLAN] You> 帮我规划如何给 CLI 增加版本号参数
HuiCode> ● ...

[PLAN] You> /do
已返回 [DEFAULT]。

[DEFAULT] You> 按刚才的计划开始实现
```

## 结构化系统提示

HuiCode 会把系统提示按优先级拼装成固定模块：

1. 身份
2. 系统约束
3. 任务模式
4. 动作执行
5. 工具使用
6. 语气风格
7. 文本输出
8. 环境信息

固定模块用于约束模型的长期行为：HuiCode 应像终端里的编程助手一样协助代码任务；优先输出安全、正确、可维护的代码；不要编造工具结果；编辑前先读文件；有专用工具时不要用 `Bash` 代替；高风险或破坏性操作需要先获得用户确认；回复默认使用中文、简洁、无 emoji。

可选模块包括自定义指令和长期记忆。稳定模块固定排在请求前部，便于供应商侧缓存；active Skill 完整 SOP、动态环境、模式指令和轻量 Skill 目录按轮次作为系统级补充上下文注入，不污染用户消息或稳定缓存。

运行时补充信息使用特殊标签：

```xml
<huicode_context type="environment" scope="turn">...</huicode_context>
<huicode_instruction type="plan_mode" scope="turn">...</huicode_instruction>
<huicode_instruction type="execution_mode" scope="turn">...</huicode_instruction>
```

Plan/DEFAULT 指令注入频率为：首轮完整注入，每 4 轮重复关键约束，其余轮次注入精简提醒。

这些提示词只约束模型行为，不代表凭空增加工具。当前 HuiCode 支持 isolated Skill 子会话和真实 MCP 工具，但还没有通用 `TaskCreate` 或 `ToolSearch`；模型只能使用当前工具列表中真实暴露的能力。

## 缓存 Usage

开启 `/verbose` 后，TUI 会显示 token usage。HuiCode 会归一化常见缓存字段：

- Anthropic/DeepSeek Anthropic 兼容：`cache_creation_input_tokens`、`cache_read_input_tokens`
- OpenAI 兼容：`prompt_tokens_details.cached_tokens`

示例：

```text
tokens: input_tokens=1200, output_tokens=200, cache_creation_input_tokens=800, cache_read_input_tokens=400
```

当前实现会优先保持协议兼容，不强制向 DeepSeek Anthropic 兼容接口加入可能不支持的 `cache_control` 字段。

## 记忆系统

HuiCode 启动后可以自动恢复项目知识和用户偏好。记忆系统分三层：

- 项目指令：启动和每轮请求前加载，作为系统级上下文注入。
- 会话存档：当前对话以 JSONL 追加写入，坏行可跳过，恢复时会截断不完整工具调用。
- 自动笔记：最终回复自然结束后整理为长期记忆，并重建精简索引。

自动笔记由 HuiCode 在后台静默更新，不经过工具权限确认。主 Agent 不应使用 `Write`、`Edit` 或 `Bash` 直接维护 `.huicode/sessions` 和 `.huicode/memory`；这些内部目录的副作用操作会被直接拒绝，避免打断交互或破坏存档。

配置示例：

```yaml
memory:
  enabled: true
  auto_update: true
  session_retention_days: 30
  stale_session_notice_hours: 24
  index_max_lines: 200
  index_max_bytes: 25600
```

项目指令文件按优先级加载：

```text
<workspace>/.huicode/instructions.md
<workspace>/.mewcode/instructions.md
<workspace>/HUICODE.md
<workspace>/MEWCODE.md
~/.huicode/instructions.md
~/.mewcode/instructions.md
```

指令文件支持 `@include relative/path.md`。项目级 include 必须留在 workspace 内，用户级 include 必须留在用户配置目录内；循环、过深、缺失和越界引用会跳过并产生 warning。

会话存档位置：

```text
<workspace>/.huicode/sessions/<session-id>.jsonl
```

长期笔记和索引位置：

```text
<workspace>/.huicode/memory/notes/*.md
<workspace>/.huicode/memory/index.md
~/.huicode/memory/notes/*.md
~/.huicode/memory/index.md
```

笔记分为四类：`preference`、`correction`、`project_knowledge`、`reference`。索引默认限制在 200 行和 25KB 内，只保存摘要和 source 提示；需要细节时应重新读取笔记或项目文件，不要凭索引脑补。

记忆命令：

```text
/memory
/memory update
/memory rebuild
/session
/session resume <session-id>
/session clean
```

- `/memory`：查看当前 session、笔记数量、索引大小和最近错误。
- `/memory update`：手动根据最近对话整理记忆。
- `/memory rebuild`：从笔记重建索引。
- `/session`：列出可恢复会话。
- `/session resume <session-id>`：恢复指定会话，坏行跳过，破损工具历史截断。
- `/session clean`：清理超过保留期的非活动会话。

`/clear` 只清空当前工作上下文并开启新 session，不删除历史 session、长期笔记或索引。记忆状态、索引和笔记写入前会做基础 secret 脱敏，不会主动输出 API key、Authorization、token、password 等敏感值。

## 启动

```powershell
python -m huicode --config .\huicode.yaml
```

安装为包后也可以运行：

```powershell
huicode --config .\huicode.yaml
```

## OpenAI 兼容配置

```yaml
protocol: openai
model: gpt-4.1-mini
base_url: https://api.openai.com/v1
api_key: sk-...
show_usage: false
headers:
  HTTP-Referer: https://example.test
  X-Title: HuiCode
```

## Anthropic Claude 兼容配置

```yaml
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com/v1
api_key: sk-ant-...
max_tokens: 4096
thinking:
  enabled: true
  budget_tokens: 1024
  show: false
context:
  enabled: true
  window_tokens: 128000
  single_tool_result_tokens: 1000
  tool_result_group_tokens: 6000
```

## 交互命令

- `/help [command]`：查看公开命令列表或单条命令详情
- `/compact`：手动触发上下文压缩，不进入 Agent Loop
- `/clear`：清空当前工作上下文和计划，开启新 session
- `/plan`：进入 `[PLAN]`，后续普通输入只使用读类工具
- `/do`：返回 `[DEFAULT]`，不自动执行计划
- `/session [resume <session-id>|clean]`：列出、恢复或清理会话
- `/memory [update|rebuild]`：查看、更新长期记忆或重建索引
- `/permission [strict|default|permissive]`：查看或切换权限模式
- `/status`：聚合查看模式、Provider、Token、上下文、权限、MCP、记忆和 Skill
- `/commit [arguments]`：运行当前有效的 commit Skill
- `/review [arguments]`：运行当前有效的 review Skill，默认使用 isolated 子会话
- `/test [arguments]`：运行当前有效的 test Skill，默认使用 isolated 子会话

为兼容旧用法，`/sessions`、`/resume`、`/permissions`、`/perm`、`/config`、`/context`、`/verbose`、`/last`、`/exit`、`/quit` 仍可使用，但不会出现在 `/help` 或 Tab 补全中。后续破坏性版本可能移除这些隐藏入口。

## 本阶段暂不包含

- 自动化评估
- 网络请求限制
- CPU、内存、磁盘、进程数等资源配额
- 完整审计日志
- 操作系统级容器沙箱
- 用户交互式确认之外的权限 UI
- 通用子 Agent 或 `TaskCreate`
- `ToolSearch`
- Skill 市场、远程分发和版本管理
