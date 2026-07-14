# HuiCode Skill System Plan

## 架构概览

本章新增 `huicode.skills` 包，把 Skill 的解析、三级发现、覆盖、校验、激活、热更新和隔离执行集中在一个领域模块中。CLI 在默认工具与 MCP 工具注册完成后创建 `SkillManager`；Manager 生成不可变的有效目录快照，并把同一份快照提供给 Prompt、系统级 `Skill` 工具、Slash Command 和状态输出。

整体分为七层：

1. **定义层**：声明 Skill 元数据、来源、激活项、目录快照、加载结果和隔离执行结果。
2. **解析与发现层**：解析 YAML frontmatter 与 Markdown 正文，扫描单文件和目录型 Skill，执行真实路径边界检查。
3. **覆盖与校验层**：按项目、用户、内置优先级生成有效目录；在所有本地与 MCP 工具注册后校验白名单和命令冲突。
4. **会话状态层**：维护 active shared skills、当前轮模型覆盖、热更新指纹和最近错误。
5. **执行层**：系统级 `Skill` 工具负责按需激活；shared 复用主 Agent Loop，isolated 使用独立状态运行并只回流摘要。
6. **集成层**：Prompt 注入目录和完整 SOP；Agent 计算工具交集；Slash Command 动态映射到 Skill 执行。
7. **生命周期层**：启动构建首个快照，每次顶层输入前检查热更新，`/clear` 清理会话级 Skill 状态。

数据流：

```text
启动
  -> 注册默认工具 -> 加载 MCP 工具
  -> SkillManager.discover()
  -> 解析/覆盖/白名单校验/命令冲突校验
  -> 原子发布 SkillCatalogSnapshot
  -> 注册系统级 Skill 工具和动态 Slash Command

普通 Agent 请求
  -> Prompt 注入轻量 Skill 目录
  -> 模型调用 Skill(name, arguments)
  -> shared: 激活 SOP -> 收窄工具 -> 继续主 Agent Loop
  -> isolated: 建立独立 AgentState -> 运行子循环 -> 摘要作为 ToolResult 回流

顶层 Slash Command
  -> 输入前热更新检查
  -> /<skill> [arguments]
  -> shared: 激活并发送任务到主 Agent
  -> isolated: 独立执行并把请求和摘要写入主历史
```

## 核心数据结构

### Skill 定义

在 `huicode/skills/types.py` 定义：

```python
SkillMode = Literal["shared", "isolated"]
SkillSource = Literal["project", "user", "builtin"]

@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    mode: SkillMode
    history_messages: int
    model: str | None
    body: str
    entry_path: Path
    root_path: Path
    source: SkillSource

@dataclass(frozen=True)
class ActiveSkill:
    definition: SkillDefinition
    arguments: str
    rendered_body: str
    activated_order: int

@dataclass(frozen=True)
class SkillCatalogSnapshot:
    definitions: Mapping[str, SkillDefinition]
    fingerprint: tuple[SkillFileFingerprint, ...]
    overridden_count: int
    skipped_count: int
    warnings: tuple[SkillWarning, ...]
    generation: int
```

`SkillDefinition` 不保存执行对象，保证解析结果可测试、可比较。`ActiveSkill` 保存替换参数后的正文，避免每轮 Prompt 重复读取文件。Catalog 对外只暴露不可变映射，热更新成功时整体替换。

### 会话状态

在 `AgentState` 增加 `SkillRuntimeState`：

```python
@dataclass
class SkillRuntimeState:
    active: dict[str, ActiveSkill] = field(default_factory=dict)
    next_activation_order: int = 0
    turn_model_override: str | None = None
    reload_error: str = ""
    catalog_generation: int = 0
```

`dict` 使用 Python 插入顺序保存首次激活顺序。同名 Skill 再次激活时原位置不变，只替换参数、定义和渲染正文。`turn_model_override` 在一个顶层用户轮结束、报错、取消或达到迭代上限后清空。

### 结构化结果

定义 `SkillLoadResult`、`SkillRunResult` 和 `SkillWarning`：

- 加载结果包含 `ok`、name、mode、source、generation 和错误码，不返回完整 SOP。
- 隔离结果包含 `status`、summary、iterations、stop_reason 和可公开错误信息。
- Warning 包含入口路径、错误类别和原因，不保存或打印 API key、正文片段等敏感内容。

## 模块职责

### `huicode/skills/parser.py`

- 使用 PyYAML 的安全解析读取 frontmatter，禁止自定义对象构造。
- 仅接受文件开头的 `---` frontmatter；第二个 `---` 后是 Markdown 正文。
- 严格验证 `name`、`description`、`allowed_tools`、`mode`、`history_messages` 和可选 `model`。
- `name` 只允许小写字母、数字、`-`、`_`；description 必须是非空单行；正文必须非空。
- 只执行字面 `{{args}}` 替换，不解释表达式、环境变量或脚本。
- 入口路径和 Skill 根路径都先 `resolve()`，再用 `Path.relative_to()` 验证仍位于对应来源目录中。

不复用 `config.py` 的最小 YAML 解析器。Skill frontmatter 包含列表和严格类型，需要标准安全 YAML 解析；在 `pyproject.toml` 新增 `PyYAML>=6` 运行时依赖并使用 `yaml.safe_load()`。若依赖缺失，启动时给出明确安装错误，不静默退化到能力不足的最小解析器。

### `huicode/skills/discovery.py`

- 依次扫描内置、用户、项目三层，并在合并时让后者覆盖前者。
- 每层只识别根目录下的 `*.md` 和一级目录中的 `SKILL.md`，辅助文件不参与入口发现。
- 同层相同 name 的全部候选在该层失效，记录 warning，再允许低优先级版本继续生效。
- 单文件解析失败仅增加 skipped/warning，不阻断其他文件。
- 指纹包含来源、入口真实路径、mtime_ns 和 size；目录型 Skill 还纳入包内文件的相对路径、mtime_ns 和 size，使模板或参考文件变化也能触发刷新。

### `huicode/skills/catalog.py`

`SkillCatalogBuilder` 接收三层目录、`ToolRegistry` 和核心命令保留名，负责：

- 合并发现结果并生成有效定义映射。
- 通过 `ToolRegistry.resolve_name()` 把 alias 规范为工具主名。
- 对每个有效 Skill 校验白名单；任何未知工具都是全局错误。
- 校验 Skill 名不与核心公开命令、隐藏兼容命令或其 alias 冲突。
- 返回完整候选快照；不直接修改运行时对象。

启动时全局错误抛出 `SkillConfigError` 并让 CLI 返回退出码 2。热更新时错误由 Manager 记录，旧快照继续工作。

### `huicode/skills/manager.py`

`SkillManager` 是目录和激活状态的协调器：

- `initialize()` 构建首个有效快照。
- `reload_if_changed()` 快速比较指纹；有变化时完整重建并原子发布。
- `activate_shared(state, name, arguments)` 渲染并更新 active state。
- `refresh_active(state)` 在快照更新后用原参数重新渲染；无 fallback 的已删除 Skill 自动停用。
- `catalog_prompt()` 只生成 name、description、mode。
- `active_prompt_blocks(state)` 生成完整高优先级 SOP 块。
- `effective_tool_names(state, mode)` 计算基础模式工具集与 active shared 白名单的交集。
- `clear_state(state)` 清除 active、工具限制、模型覆盖和 reload 状态。

Manager 不直接调用 Provider，isolated 执行委托给 Runner，避免目录管理与 Agent Loop 相互耦合。

### `huicode/skills/tool.py`

新增系统级 `SkillTool`，实现现有 `Tool` 接口：

- Schema 接受必填 `name` 和可选 `arguments`。
- 工具持有当前 `SkillExecutionContext`，将激活请求交给 Manager/Runner。
- shared 返回“已激活，下一轮按 SOP 继续”的结构化结果。
- isolated 同步消费子 Agent 事件，最终返回结构化摘要。
- 未知、已删除、嵌套超限和子执行失败均返回 `ToolResult.failure()`，不抛出到 Agent Loop。

`SkillTool` 使用显式系统工具标记。Agent 的工具选择逻辑始终追加它，不参与 Plan Mode 或 Skill 白名单交集；但 Skill 内调用的普通工具继续走现有权限和沙箱执行器。

### `huicode/skills/runner.py`

`SkillRunner` 复用 `run_agent_loop()`，不复制 Provider SSE 或工具执行逻辑：

- 创建独立 `AgentState` 和独立 ContextState。
- 从主历史尾部调用协议安全选择函数，按 `history_messages` 扩展到完整 tool-call/tool-result 组合。
- 注入该 Skill 的完整 SOP、根目录和父级环境摘要。
- 传入该 Skill 白名单与父级 Plan Mode 的交集。
- 可选 model 通过复制主 `LLMConfig`、只替换 `model`，再调用 `create_provider()`。
- 隔离执行事件默认只转换为开始、结束和摘要事件；内部 thinking 不灌入主 TUI。
- 嵌套上下文携带 depth，超过 3 时返回 `nested_depth_exceeded`。
- 最终文本作为成功摘要；错误、取消、未知工具上限和迭代上限转换为明确的非成功结果。

协议安全历史选择逻辑从现有上下文历史处理模块提取或复用，不能按固定条数硬切断 Anthropic/OpenAI 的工具配对。

## Agent 与 Provider 集成

### 工具选择

扩展 `select_tools()` 接受 Skill 状态：

1. chat/do 基础集合为 registry 全部普通工具；plan 基础集合为只读工具。
2. 对每个 active shared Skill，把基础集合与其已规范化白名单取交集。
3. isolated Runner 再与目标 Skill 白名单取交集。
4. 最后无条件加入系统级 `Skill` 工具。

批处理和执行前仍保留 `_plan_mode_denial()` 作为第二层防线，避免仅靠暴露列表控制安全。

### shared 模型覆盖

`run_agent_loop()` 增加可选 Skill runtime/Provider resolver：当 shared Skill 激活并指定 model 后，从下一次模型请求起使用覆盖 Provider；顶层轮自然结束或异常退出时在 `finally` 清理覆盖。主 Provider 实例不被修改。

### isolated 回流

- 模型通过 `Skill` 工具触发时，Runner 摘要直接成为该 tool call 的 ToolResult，保持下一条消息紧邻并满足 Provider 协议。
- Slash Command 触发时，运行时先向 session 记录一条用户 Skill 请求，结束后只记录一条 assistant 摘要。
- 子会话内部消息不写入主 JSONL session，也不参与主会话自动记忆更新。

## Prompt 集成

扩展 `PromptContext`：

```python
skill_catalog: tuple[SkillCatalogItem, ...]
active_skill_blocks: tuple[ActiveSkillPrompt, ...]
```

动态补充模块顺序调整为：

1. active Skill 完整 SOP，每个 Skill 一个 `<huicode_instruction type="active_skill">`。
2. 环境信息和轮次模式指令。
3. 记忆索引与警告。
4. 轻量 Skill catalog。

active block 与 catalog 均为动态、不可缓存系统补充消息，不写成用户消息。Catalog 只含 name、description、mode；active block 含来源层级、根目录、规范化白名单和渲染后的 SOP。完整 SOP 不进入稳定缓存、摘要或普通 TUI 输出。

## Slash Command 集成

### 注册中心调整

`CommandRegistry` 增加构建新快照或 clone-and-register 能力。核心命令先构建为基础 registry，Skill 命令在副本上批量注册；全部成功后 CLI runtime 原子替换当前 registry，并让 completer 引用可更新的 registry provider。

动态 Skill 命令元数据：

- name：Skill name。
- description：Skill description。
- usage：`/<name> [arguments]`。
- argument hint：`[arguments]`。
- 类型：新增 `SKILL`，或在现有 PROMPT 类型中通过专用 handler 标识 Skill；计划采用新增 `SKILL`，便于 shared/isolated 分流与帮助展示。

移除 `builtin.py` 的硬编码 `REVIEW_PROMPT` 和 `/review` handler。内置 review 由 Catalog 注册，与项目/用户同名覆盖遵循相同路径。

### 输入入口与热更新

每次顶层输入交给 `InputRouter` 前：

1. 调用 `reload_if_changed()`。
2. 成功时刷新动态命令和 active state。
3. 失败时显示一次简短 reload warning，继续使用旧快照。
4. 再按最新 registry 解析本次输入。

`/clear` 调用 `SkillManager.clear_state()`，但不清除 catalog。`/help` 和 Tab 补全从当前动态 registry 读取，因此下一次输入即可反映文件变化。

## CLI 生命周期与状态

CLI 初始化顺序调整为：

1. 加载 LLM、权限、上下文和记忆配置。
2. 创建默认 `ToolRegistry`。
3. 连接 MCP 并注册远端工具。
4. 构建基础 Command Registry 和保留名集合。
5. 创建 SkillManager 并校验首个 Catalog。
6. 注册 `SkillTool`，发布动态 Command Registry。
7. 创建 Runtime、InputRouter 和补全器，进入输入循环。

启动摘要增加：`skills: effective=N overridden=N skipped=N warnings=N`。

`/status` 增加：

```text
skills: discovered=3 active=review reload_errors=0 tools=Read,Find,Search,Bash
```

只显示名称、计数和工具限制摘要。状态栏可增加紧凑 `skills: 1`，不显示 SOP。

## 内置 Skill 文件

创建目录：

```text
huicode/skills/builtin/
  commit/SKILL.md
  review/SKILL.md
  test/SKILL.md
```

- `commit`：shared，`Read`、`Bash`；先检查状态和 diff，再拟定提交说明并执行提交，权限确认保持有效。
- `review`：isolated，history 12，`Read`、`Find`、`Search`、`Bash`；只读审查并按严重程度输出发现。
- `test`：isolated，history 6，`Read`、`Find`、`Search`、`Bash`；识别相关测试、运行并归纳失败。

三个入口保持简洁，可作为单文件格式和目录型辅助资源引用的 README 示例。

## 文件组织

### 新增

- `huicode/skills/__init__.py`：公共导出。
- `huicode/skills/types.py`：定义、状态、快照、警告和结果类型。
- `huicode/skills/parser.py`：frontmatter 与正文解析、参数渲染。
- `huicode/skills/discovery.py`：三级扫描、真实路径检查、指纹生成。
- `huicode/skills/catalog.py`：覆盖、工具校验、命令冲突校验。
- `huicode/skills/manager.py`：快照生命周期、激活和热更新。
- `huicode/skills/tool.py`：系统级 `Skill` 工具。
- `huicode/skills/runner.py`：isolated Agent 执行和摘要回流。
- `huicode/skills/builtin/{commit,review,test}/SKILL.md`：内置样板。
- `tests/test_skills_parser.py`
- `tests/test_skills_discovery.py`
- `tests/test_skills_catalog.py`
- `tests/test_skills_manager.py`
- `tests/test_skills_tool.py`
- `tests/test_skills_runner.py`
- `tests/test_skills_commands.py`
- `tests/test_cli_skills.py`

### 修改

- `huicode/agent_events.py`：增加 Skill 会话状态与必要事件类型。
- `huicode/agent.py`：工具交集、Prompt 上下文、shared Provider 覆盖和 Runner 复用入口。
- `huicode/prompts/base.py`、`builder.py`、`modules.py`：目录和高优先级 active block。
- `huicode/tools/registry.py`：系统工具标记、规范化白名单和稳定筛选接口。
- `huicode/commands/types.py`、`registry.py`、`builtin.py`、`completion.py`、`runtime.py`：动态 Skill 命令和原子刷新，迁移 `/review`。
- `huicode/cli.py`：初始化顺序、热更新入口、状态和资源生命周期。
- `huicode/provider_factory.py`：仅模型名覆盖的 Provider 创建辅助函数。
- `pyproject.toml`：新增 `PyYAML>=6` 运行时依赖。
- `README.md`：格式、目录、优先级、加载、模式、白名单、命令和热更新说明。
- 相关 Agent、Prompt、Command、CLI、Provider 测试：补充回归断言。

## 技术决策与理由

### 目录快照是唯一真相源

Prompt、工具和命令都从同一个 `SkillCatalogSnapshot` 派生。热更新先完整校验候选快照，再一次替换，避免模型看见新 Skill、命令仍指向旧 Skill 或白名单尚未更新的中间状态。

### 白名单取交集

Skill 表达的是当前任务所需的最小工具范围，不是权限授权。与 Plan Mode、其他 active Skill 和权限系统取交集，才能保证任何 Skill 都不能扩大能力。

### Skill 工具独立于普通白名单

两阶段加载要求模型始终能加载目录中声明的 Skill，因此 `Skill` 是系统控制工具。它只加载指令或启动受限子循环，本身不直接读写用户文件；普通操作仍经过现有权限链。

### isolated 复用 Agent Loop

复用 Agent Loop 可保持 SSE、extended thinking、工具调用拼接、权限、上下文压缩和停止条件一致。Runner 只负责建立隔离状态和筛选回流事件，不实现第二套 Agent。

### 热更新使用轮询指纹

每次顶层输入前比较轻量文件指纹，跨 Windows/Linux 且不增加文件监听依赖。只有指纹变化才重新解析；构建失败保留旧快照。

### 完整 SOP 使用动态系统补充消息

SOP 可能频繁修改且带用户参数，不适合稳定缓存，也不能伪装成用户输入。放在动态系统补充消息首位，既保持高优先级，也不会被上下文摘要改写。

## 测试计划

### 解析与发现

- 正常单文件、目录型入口和 `{{args}}` 字面替换。
- 缺失 frontmatter、字段类型错误、非法 name、空正文和未知字段策略。
- 项目覆盖用户、用户覆盖内置；同层重名回退低层。
- 坏文件不阻断其他 Skill；符号链接和真实路径逃逸被拒绝。
- 辅助文件变化触发目录型 Skill 指纹变化。

### Catalog 与工具限制

- 本地工具 alias 和 MCP 工具名成功规范化。
- 未知白名单工具启动失败，热更新时保留旧快照。
- Plan Mode、单 Skill、多 Skill均按交集收窄。
- `Skill` 工具在空白名单、Plan Mode 和多 Skill 下始终可见。
- 普通工具仍经过权限、黑名单和路径沙箱。

### 执行模式

- shared 激活、重复替换、多 Skill 顺序和每轮 Prompt 持久化。
- shared 模型覆盖仅当前顶层轮有效，并保留主配置其他字段。
- isolated 使用独立状态、协议安全历史和独立上下文计数。
- isolated 成功只回流摘要；错误、取消、迭代上限和嵌套超限结构化返回。
- OpenAI 与 Anthropic 工具消息在 Skill 调用和摘要回流后保持合法配对。

### 命令与热更新

- 有效 Skill 自动进入 `/help` 和补全，参数大小写原样传递。
- shared/isolated Slash Command 走各自执行路径。
- 项目 review 覆盖内置 review，旧 `REVIEW_PROMPT` 不再存在。
- 核心命令冲突启动失败；热更新冲突保留旧命令。
- 新增、修改、删除和 fallback 后，目录、active state 与命令原子刷新。
- `/clear` 清除 active、工具限制和模型覆盖，但目录仍可用。

### 回归与端到端

- 更新 Agent、Prompt、Command、Provider 和 CLI 现有测试。
- `python -m unittest discover -v`
- `python -m compileall -q huicode tests`
- `git diff --check`
- 有 tmux 时执行真实 TUI：`/help`、`/review`、shared Skill、多 Skill 工具交集、热更新和 `/clear`。
- Windows 无 tmux 时用 fake Provider 的 CLI 集成测试覆盖完整输入、工具调用、子循环和摘要回流，并在验收报告说明替代证据。

## 实施顺序

1. 建立 Skill 类型、解析器和参数渲染，锁定文件格式。
2. 实现三级发现、覆盖、真实路径边界和指纹。
3. 实现 Catalog 全局校验与原子 SkillManager 快照。
4. 扩展 AgentState、Prompt 动态模块和工具交集。
5. 实现系统级 `SkillTool` 与 shared 激活链。
6. 实现 isolated Runner、协议安全历史和模型覆盖。
7. 改造 Command Registry 与 Runtime，动态注册 Skill 并迁移 `/review`。
8. 接入 CLI 初始化、输入前热更新、状态和 `/clear`。
9. 添加内置 commit/review/test，更新 README。
10. 完成专项测试、全量回归、端到端验收和验收报告。

## 需求覆盖检查

- F1-F3：parser、discovery、catalog。
- F4-F6：Prompt catalog、SkillTool、active state。
- F7-F8：Catalog 工具校验、Agent 工具交集、系统工具保留。
- F9-F11：shared/isolated Runner、协议安全历史、Provider 覆盖。
- F12-F14：动态命令、热更新、`/clear` 生命周期。
- F15-F16：三个内置目录型 Skill 与 `/review` 迁移。
- F17：复用现有工具执行、权限、上下文和停止条件。
- F18：README 和示例文档。

所有功能需求均有明确模块和测试路径；依赖顺序为工具与 MCP 注册完成后再校验 Skill，命令与 Prompt 只消费已发布的有效快照。

## 风险与控制

- **Agent 与 Runner 递归耦合**：用执行上下文和深度值显式传递，Runner 复用循环但不持有 CLI。
- **动态命令刷新出现半更新**：在副本 registry 上注册全部命令，成功后一次替换引用。
- **工具白名单误扩权**：统一使用主名集合取交集，执行前保留 Plan Mode 和权限二次校验。
- **历史硬切导致 Provider 400**：使用协议安全消息分组选择，专测 Anthropic/OpenAI tool call/result 边界。
- **热更新频繁阻塞输入**：无变化只比较指纹；解析和全局校验仅在变化时执行。
- **SOP 或密钥泄露到日志**：事件和状态只输出元数据与摘要，测试使用哨兵 secret 验证不外泄。
- **shared model 覆盖污染后续轮次**：顶层 loop 使用 `finally` 清理，错误和取消路径单独测试。

## 完成定义

- 三层 Skill、两种布局、覆盖和错误隔离符合 spec。
- Prompt 首阶段只含轻量目录，激活后完整 SOP 每轮保持最高动态优先级。
- shared 与 isolated 两种模式行为、历史边界和回流结果可观察且协议合法。
- 工具白名单只收窄能力，未知工具启动失败，系统 `Skill` 工具始终可用。
- Skill 命令、帮助、补全和热更新来自同一个有效快照。
- `/review` 已迁移，commit/review/test 三个内置样板可运行。
- `/clear`、状态输出、权限、上下文、记忆和 MCP 回归正常。
- 全量测试、编译、diff 检查及可用环境下的端到端验收通过，README 和验收报告与实现一致。
