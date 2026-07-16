# HuiCode

HuiCode 是一个终端 AI 编程助手。当前阶段已经具备交互式对话、流式输出、工具调用、Agent Loop、Plan Mode、上下文管理、记忆、MCP、Skill、子 Agent、Agent Team、生命周期 Hook、Rich Markdown 渲染、结构化系统提示，以及五层权限系统。

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
- 声明式生命周期 Hook、工具拦截与自动化动作
- 定义式/Fork 式子 Agent、进程内后台任务与 Git Worktree 隔离
- 长期 Agent Team、共享任务、成员邮箱、计划审批与安全分支集成

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

十二个核心公开命令：

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
/skill [name]
/agents [name]
/tasks [task-id]
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

## 子 Agent 系统

主 Agent 始终可以调用固定 Schema 的系统工具 `Agent`，把独立任务交给定义式或 Fork 式子 Agent：

- `defined`：从干净消息历史和固定角色开始，需要提供 `role`。
- `fork`：从父对话最近的完整工具协议边界分叉，继承稳定 Prompt 和工具快照，始终后台运行。

角色按以下优先级覆盖：

```text
项目级：<workspace>/.huicode/agents/*.md
用户级：~/.huicode/agents/*.md
内置：huicode/subagents/builtin/*.md
插件：`HUICODE_PLUGIN_AGENT_PATHS` 指向的角色目录（多个目录按系统路径分隔符分隔）
```

角色示例：

```markdown
---
name: explorer
description: 只读调查项目结构和调用链
allowed_tools: [Read, Find, Search]
denied_tools: []
model: inherit
max_iterations: 20
permission_mode: strict
isolation: shared
---
先定位事实和调用关系，再给出带文件路径的结论。不要修改文件。
```

`model` 只允许 `inherit`、`haiku`、`sonnet`、`opus`。后三者需要在主配置中映射为真实模型名：

```yaml
subagents:
  foreground_timeout_seconds: 10
  max_background_tasks: 4
  shutdown_wait_seconds: 2
  background_allowed_tools: [Read, Find, Search]
  model_aliases:
    haiku: deepseek-chat
    sonnet: deepseek-reasoner
    opus: deepseek-reasoner

worktrees:
  root: .huicode/worktrees
  stale_after_days: 7
  cleanup_interval_seconds: 3600
  copy_files: [huicode.yaml, .huicode-permissions.local.yaml]
  symlink_directories: [node_modules]
  restore_ignored: [.env.local, fixtures/**/*.bin]
  hooks_path: .githooks
```

定义式任务默认在前台等待：短任务直接把摘要和独立 usage 返回给主 Agent；显式 `background: true`、运行超过前台时限，或交互终端中按 `Ctrl+B`，都会让任务继续在后台。非 TTY 环境没有按键监听，但显式后台和超时后台仍生效。Fork 从创建起强制后台。

后台完成只通知 TUI，不会自动调用模型。结果会在下一次主请求中通过一次性 `subagent_results` 系统上下文交付；Provider 请求失败时结果保留，完整响应后才消费。使用以下命令观察状态：

```text
/agents
/agents explorer
/tasks
/tasks task-ab12cd34
/status
```

子 Agent 的消息、上下文、权限临时规则、Read 缓存和 Token 统计互相隔离。`Agent` 与 `Skill` 在子 Agent 中被硬禁用，避免无限嵌套。后台默认只允许 `Read`、`Find`、`Search`。

定义式角色可把 `isolation` 改为 `worktree`。HuiCode 会从任务启动时的主仓库 `HEAD` 创建独立目录和分支，主工作区未提交修改不会带入；Fork 子 Agent 始终共享主工作区。所有工具都通过显式工作目录运行，进程不会调用 `chdir`。成功且干净的隔离任务会自动清理；存在未提交修改、未推送提交、失败或取消时会保留目录，并在任务结果中显示路径、分支和原因。HuiCode 不自动合并分支，检查完成后由用户或上层流程决定 `git merge`。

Worktree 根目录必须位于仓库内并被 Git 忽略。`copy_files` 复制本地配置，`restore_ignored` 按文件或 glob 补回运行文件，`symlink_directories` 为大型依赖建立目录链接，`hooks_path` 配置目标 Worktree 的 Git Hooks。Windows 无法创建目录链接时会明确报错，不会静默复制。已有目录只有在 `.huicode/worktree.json` 的仓库、任务和路径标识完全匹配时才会恢复；恢复检查不调用 Git。

## Agent Team

开启 Team 后，主 Agent 可以创建长期团队，给成员分配独立 Worktree，并通过共享任务和邮箱并行协作。团队状态保存在 `~/.huicode/teams/<team-name>/`，HuiCode 重启后可恢复；代码变更仍保存在当前仓库的成员分支中。

配置示例：

```yaml
teams:
  enabled: true
  default_backend: auto
  max_members: 4
  mailbox_lock_retries: 8
  mailbox_lock_retry_ms: 50
  mailbox_stale_lock_seconds: 30
  member_idle_poll_ms: 250
  shutdown_wait_seconds: 3
  coordinator_enabled: false
  integration_checks:
    - python -m unittest discover -s tests -v
```

模型通过以下工具组织团队：

- `Team`：创建、恢复、查看、关闭或删除团队，启动和停止成员。
- `TeamTask`：管理带依赖关系的共享任务并分配给成员。
- `TeamMessage`：成员点对点消息、Lead 广播和邮箱读取。
- `TeamPlanRequest`：需要审批的成员提交结构化计划。
- `TeamPlanDecision`：Lead 按 request ID 批准或驳回，不解析普通聊天文本。
- `TeamIntegrate`：在专用集成 Worktree 合并、继续冲突恢复、验证和发布。

工具按运行身份隔离：普通主会话只看到 `Team` 入口；激活团队后 Lead 获得管理、审批和集成工具；成员只能使用任务、消息和计划申请；普通子 Agent 看不到 Team 工具。需要审批的成员在匹配的 `allow` 到达前看不到副作用工具，历史或伪造调用也会被程序拒绝。

`default_backend: auto` 的顺序固定为 tmux、Windows Terminal、同进程协程，启动事件会显示实际后端。显式设置 `terminal` 时，如果两个终端后端都不可用会直接失败，不会静默降级。所有后端中的每个成员都强制使用独立 Worktree。

Coordinator 模式需要两把锁同时开启：

```yaml
teams:
  enabled: true
  coordinator_enabled: true
```

```powershell
$env:HUICODE_COORDINATOR = "1"
python -m huicode --config .\huicode.yaml
```

Linux/macOS 使用 `export HUICODE_COORDINATOR=1`。双锁开启后，Lead 不能直接使用 Write/Edit；Bash 也被收窄为只读 Git 诊断，实际合并通过 `TeamIntegrate` 的固定流程执行。

成员最终回复后进入 idle，保留会话、权限和 Worktree。后续消息会唤醒原成员并恢复 JSONL 历史，不创建同名新成员。集成先在专用分支和 Worktree 中完成；检查通过且目标分支没有漂移、用户工作区干净时才 fast-forward 发布。冲突、检查失败或目标变化都不会覆盖用户当前工作区。

## Hook 系统

Hook 用 YAML 声明“事件 + 可选条件 + 动作”，适合自动格式化、固定安全拦截、外部通知和系统级上下文注入。规则按以下优先级合并，相同 `id` 由高层整体覆盖：

```text
用户级：~/.huicode/hooks.yaml
启动配置：--config 指定的 huicode.yaml 中的 hooks
项目级：<workspace>/.huicode/hooks.yaml
```

独立文件和主配置都使用顶层 `hooks` 列表。下面的示例可以直接放进任一位置：

```yaml
hooks:
  - id: format-python-after-edit
    event: tool_after
    if:
      all:
        - field: tool.name
          exact: Edit
        - field: tool.arguments.path
          glob: "**/*.py"
    action:
      type: command
      command: python
      args:
        - -m
        - black
        - .
    async: true
    timeout_seconds: 30

  - id: protect-generated-files
    event: tool_before
    if:
      any:
        - field: tool.arguments.path
          glob: "**/generated/**"
    action:
      type: command
      command: python
      args:
        - -c
        - "import sys; print('generated files are read-only', file=sys.stderr); raise SystemExit(2)"

  - id: inject-project-policy
    event: session_start
    action:
      type: prompt
      scope: session
      content: "提交前必须运行与改动相关的测试。"

  - id: notify-turn-finished
    event: turn_end
    action:
      type: http
      url: http://127.0.0.1:9000/hooks/turn-end
      method: POST
      headers:
        X-HuiCode-Source: local
    async: true
    timeout_seconds: 5
```

事件覆盖 `session_start/session_end`、`turn_start/turn_end`、`message_received/message_completed`、`tool_before/tool_after`、`context_before_compact/context_after_compact` 和 `agent_error`。条件支持大小写敏感的 `exact`、`glob`、`regex`、`not`，多个叶子只能选择 `all` 或 `any`。工具别名会规范化，例如 `Glob` 在 `tool.name` 中按 `Find` 匹配，原名保存在 `tool.original_name`。

动作行为：

- `command`：从 UTF-8 stdin 接收事件 JSON；`tool_before` 下退出码 `2` 表示明确拒绝，stderr 是拒绝原因。
- `prompt`：以 `<huicode_instruction type="hook">` 动态系统指令注入，支持 `next_request`、`turn`、`session`，不会进入用户历史。
- `http`：请求体是同一事件 JSON；`tool_before` 的 2xx JSON `{"decision":"deny","reason":"..."}` 表示明确拒绝。
- `subagent`：提交真实的定义式后台子 Agent；可用 `role` 指定角色，默认 `general`。子 Agent scope 再次命中时会记录 `recursion_guard`，不会递归创建任务。

`once: true` 让规则在当前进程第一次匹配后不再运行；`async: true` 只适用于不需要即时结果的动作；`timeout_seconds` 范围为 1 到 300。`tool_before` 和 prompt 动作不能异步。工具被 Hook 拒绝后不会弹权限确认，拒绝会作为 `hook_denied` 工具结果回灌模型，Agent Loop 可以继续调整。

Hook 命令仍受危险命令黑名单和项目 cwd 沙箱保护。运行失败默认不刷屏、不终止 Agent，详情追加到 `<workspace>/.huicode/logs/hooks.jsonl`；`/status` 显示 effective、disabled、pending、failed、denied 和日志路径。退出时后台动作最多收拢 2 秒。配置错误会在启动阶段指出规则 id、来源和字段并返回状态码 2；本章不支持 Hook 热更新、显式优先级或 once 跨进程持久化。

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
- `/status`：聚合查看模式、Provider、Token、上下文、权限、MCP、记忆、Skill 和 Hook
- `/skill [name]`：列出已加载/已激活 Skill，或查看指定 Skill 的来源、模式和工具白名单
- `/agents [name]`：列出子 Agent 角色，或查看指定角色的安全元数据
- `/tasks [task-id]`：列出当前进程任务，或查看状态、摘要、停止原因和 usage
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
- `ToolSearch`
- Skill 市场、远程分发和版本管理
- Hook 热更新、显式优先级和 once 标记持久化
- 跨机器分布式团队、成员间逐 Token 实时通信和复杂任务依赖约束
