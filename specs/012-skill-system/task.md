# HuiCode Skill System Tasks

## T1：建立 Skill 核心类型与运行时状态

涉及文件：

- 新增 `huicode/skills/__init__.py`
- 新增 `huicode/skills/types.py`
- 修改 `huicode/agent_events.py`
- 新增 `tests/test_skills_types.py`

任务：

- 定义 `SkillMode`、`SkillSource`、`SkillDefinition`、`ActiveSkill`、文件指纹、warning、目录快照和执行结果。
- 定义 `SkillRuntimeState`，维护有序 active 映射、轮次模型覆盖、快照 generation 和 reload error。
- 把 SkillRuntimeState 接入 `AgentState`，默认状态不影响现有 Agent。
- 保持定义层不导入 CLI、Rich、Provider 实现或具体工具。

验证：

- 运行 `python -m unittest tests.test_skills_types -v`。
- 验证默认 AgentState 的 Skill 状态为空，快照和结果类型不可变字段符合设计。

依赖：无。

## T2：引入安全 YAML 依赖并实现 Skill 解析器

涉及文件：

- 修改 `pyproject.toml`
- 新增 `huicode/skills/parser.py`
- 新增 `tests/test_skills_parser.py`

任务：

- 添加 `PyYAML>=6` 运行时依赖，使用 `yaml.safe_load()` 解析 frontmatter。
- 解析文件头 `---`、YAML 元数据和非空 Markdown 正文。
- 严格校验 name、description、allowed_tools、mode、history_messages 和 model。
- 实现 `{{args}}` 字面替换，不执行模板表达式、脚本或环境变量。
- 依赖不可用时抛出清楚的 Skill 配置错误。

验证：

- 运行 `python -m unittest tests.test_skills_parser -v`。
- 覆盖合法文件、缺失边界、非法字段类型、非法名称、空正文、shared/isolated 默认值和参数原样替换。

依赖：T1。

## T3：实现三级发现、目录型 Skill 与路径边界

涉及文件：

- 新增 `huicode/skills/discovery.py`
- 新增 `tests/test_skills_discovery.py`

任务：

- 扫描内置、用户、项目三级目录中的根级 `*.md` 和一级 `<package>/SKILL.md`。
- 对入口和 Skill 根目录执行 `resolve()` 与 `relative_to()` 边界检查，拒绝符号链接逃逸。
- 记录单文件解析失败、同层同名、跳过数量和来源路径 warning。
- 实现项目高于用户、用户高于内置的覆盖与同层冲突回退。
- 生成包含目录辅助文件的轻量文件指纹。

验证：

- 运行 `python -m unittest tests.test_skills_discovery -v`。
- 使用临时目录验证两种布局、三级覆盖、同层重名、坏文件隔离、路径逃逸和辅助文件变化。

依赖：T2。

## T4：扩展 ToolRegistry 的系统工具与白名单接口

涉及文件：

- 修改 `huicode/tools/base.py`
- 修改 `huicode/tools/registry.py`
- 修改 `tests/test_tools_registry.py`

任务：

- 给工具定义增加系统级标记或等价能力分类，默认现有工具均为普通工具。
- 提供按主名/alias 规范化白名单、筛选普通工具、追加系统工具的稳定接口。
- 保持现有 `to_specs()`、MCP 注册、alias 和 side-effect 查询兼容。
- 确保未知工具返回可定位名称，不发生静默忽略。

验证：

- 运行 `python -m unittest tests.test_tools_registry -v`。
- 验证普通工具筛选、alias 规范化、MCP 名称和系统工具始终保留。

依赖：T1。

## T5：实现 Catalog 构建与启动全局校验

涉及文件：

- 新增 `huicode/skills/catalog.py`
- 新增 `tests/test_skills_catalog.py`

任务：

- 把发现结果合并成不可变 `SkillCatalogSnapshot`。
- 在默认工具和 MCP 工具均注册后规范化 allowed_tools。
- 未知本地/MCP 工具抛出包含 Skill、来源文件和缺失工具的 `SkillConfigError`。
- 校验 Skill 名不与核心公开命令、隐藏命令或 alias 冲突。
- 统计 effective、overridden、skipped 和 warnings。

验证：

- 运行 `python -m unittest tests.test_skills_catalog -v`。
- 验证有效构建、alias、MCP 工具、未知工具、命令冲突和无 secret 错误输出。

依赖：T3、T4。

## T6：实现 SkillManager、激活和原子热更新

涉及文件：

- 新增 `huicode/skills/manager.py`
- 新增 `tests/test_skills_manager.py`

任务：

- 实现初始化、按名查询、shared 激活、重复激活替换和清空状态。
- 生成只含 name/description/mode 的轻量目录数据。
- 计算 active shared Skill 白名单交集。
- 每次顶层输入前比较文件指纹，仅变化时重建候选快照。
- 全局校验失败时保留旧快照；成功后原子发布并刷新 active Skill。
- 处理已激活 Skill 修改、删除、低层 fallback 和无 fallback 停用。

验证：

- 运行 `python -m unittest tests.test_skills_manager -v`。
- 验证 generation、无变化快返、失败回滚、原参数重渲染、删除/fallback 和 `/clear` 所需 reset 行为。

依赖：T5。

## T7：把 Skill 目录和完整 SOP 接入 Prompt

涉及文件：

- 修改 `huicode/prompts/base.py`
- 修改 `huicode/prompts/builder.py`
- 修改 `huicode/prompts/modules.py`
- 修改 `huicode/agent.py`
- 修改 `tests/test_prompt_builder.py`
- 修改 `tests/test_prompt_modules.py`
- 新增 `tests/test_agent_skills.py`

任务：

- 扩展 PromptContext，接收轻量 catalog 和 active Skill 块。
- 将 active SOP 作为动态不可缓存系统补充模块最先注入。
- 将环境、模式、记忆和轻量 catalog 按批准顺序拼装。
- 普通启动 Prompt 不包含正文、辅助文件内容或白名单详情。
- 每轮 Agent、工具结果回灌后和上下文压缩后都从 state 重建 active block。

验证：

- 运行 Prompt 与 Agent Skill 专项测试。
- 使用正文哨兵断言未激活时不可见、激活后每轮可见，且不进入稳定缓存和用户消息。

依赖：T6。

## T8：实现工具交集与系统级 Skill 加载工具

涉及文件：

- 新增 `huicode/skills/tool.py`
- 修改 `huicode/agent.py`
- 修改 `huicode/tools/registry.py`
- 新增 `tests/test_skills_tool.py`
- 修改 `tests/test_agent_loop.py`
- 修改 `tests/test_tool_batching.py`

任务：

- 实现 `Skill(name, arguments)` Schema 和结构化成功/失败结果。
- shared Skill 激活后继续当前 Agent Loop，并从下一次请求开始注入 SOP。
- 按基础模式、所有 active shared Skill 白名单取普通工具交集。
- 无论白名单、Plan Mode 或空普通工具集如何，始终暴露系统 Skill 工具。
- 保留 `_plan_mode_denial()`、权限、黑名单和路径沙箱的执行前二次防线。
- 未知、失效或删除 Skill 返回错误结果，不让循环崩溃。

验证：

- 运行 `python -m unittest tests.test_skills_tool tests.test_agent_loop tests.test_tool_batching -v`。
- 覆盖 chat/plan、单 Skill、多 Skill、空白名单、未知 Skill 和工具结果回灌。

依赖：T7。

## T9：实现仅模型名覆盖的 Provider 创建

涉及文件：

- 修改 `huicode/provider_factory.py`
- 修改 `tests/test_provider_factory.py`
- 修改 `tests/test_agent_skills.py`

任务：

- 复制主 LLMConfig 并只替换 model，沿用 protocol、base_url、api_key、headers、thinking 和 context 配置。
- shared Skill 从激活后的下一次请求起覆盖当前顶层轮。
- 在 final、错误、取消和迭代上限路径统一清理轮次覆盖。
- Provider 创建或请求失败不修改主 Provider。

验证：

- 运行 provider factory 和 shared model override 测试。
- 用 secret 哨兵断言连接配置被沿用但不出现在错误或状态输出中。

依赖：T8。

## T10：实现协议安全历史选择与 isolated SkillRunner

涉及文件：

- 新增 `huicode/skills/runner.py`
- 视复用需要修改 `huicode/context/history.py`
- 修改 `huicode/agent.py`
- 新增 `tests/test_skills_runner.py`
- 修改 `tests/test_anthropic_provider_tools.py`
- 修改 `tests/test_openai_provider_tools.py`

任务：

- 从主历史尾部按 history_messages 选择消息，并扩展到合法 tool_call/tool_result 组合边界。
- 创建独立 AgentState、ContextState 和消息列表，复用现有 Agent Loop。
- 对父级模式与目标 Skill 白名单取交集，并保留系统 Skill 工具。
- 可选 model 对整个 isolated 子会话生效。
- 支持嵌套 Skill，显式传递 depth，最大深度为 3。
- 将 final 转为摘要；错误、取消、迭代上限和嵌套超限转为结构化失败。
- 默认不把子循环 thinking 和逐工具细节灌入主 TUI。

验证：

- 运行 `python -m unittest tests.test_skills_runner -v` 及两个 Provider 工具历史测试。
- 分别验证 Anthropic 与 OpenAI 在切片、嵌套和摘要回流后的消息序列合法。

依赖：T8、T9。

## T11：接通 SkillTool 的 isolated 回流和会话记录

涉及文件：

- 修改 `huicode/skills/tool.py`
- 修改 `huicode/skills/runner.py`
- 修改 `huicode/memory/manager.py` 或复用公开记录接口
- 修改 `tests/test_skills_tool.py`
- 修改 `tests/test_agent_memory.py`

任务：

- 模型调用 isolated Skill 时，把 Runner 摘要作为同一 tool_call 的 ToolResult 紧邻回灌。
- Slash Command 路径只向主历史/session 写入 Skill 请求和 assistant 摘要。
- 子会话内部消息不写入主 JSONL session，不触发主会话逐条自动记忆。
- 子执行失败时保留真实 stop_reason 和已完成事实，不伪装成功。

验证：

- 运行 SkillTool、Agent Memory 和 Provider 历史测试。
- 检查主 session 中不存在子循环内部 tool_call，但存在可恢复的请求与摘要。

依赖：T10。

## T12：支持动态 Skill Slash Command 和迁移 `/review`

涉及文件：

- 修改 `huicode/commands/types.py`
- 修改 `huicode/commands/registry.py`
- 修改 `huicode/commands/builtin.py`
- 修改 `huicode/commands/completion.py`
- 修改 `huicode/commands/runtime.py`
- 新增 `tests/test_skills_commands.py`
- 修改 `tests/test_commands_builtin.py`
- 修改 `tests/test_commands_completion.py`

任务：

- 新增 SKILL 命令类型或等价专用分发路径。
- 支持从基础 registry 构建候选副本，批量登记 Skill 命令后原子替换。
- shared 命令激活 Skill 并把 arguments 作为任务消息发送主 Agent。
- isolated 命令直接运行 Runner，只显示并记录摘要。
- `/help` 和补全动态读取当前有效 Skill；隐藏项规则保持不变。
- 删除硬编码 `REVIEW_PROMPT` 和旧 review handler，由有效 review Skill 注册 `/review`。

验证：

- 运行命令专项测试。
- 验证项目/用户 review 覆盖内置 review、参数大小写保留、核心冲突失败、帮助和补全同步。

依赖：T6、T11。

## T13：添加 commit、review、test 内置目录型 Skill

涉及文件：

- 新增 `huicode/skills/builtin/commit/SKILL.md`
- 新增 `huicode/skills/builtin/review/SKILL.md`
- 新增 `huicode/skills/builtin/test/SKILL.md`
- 修改 `tests/test_skills_catalog.py`
- 修改 `tests/test_skills_commands.py`

任务：

- 按 spec 写入三份 YAML frontmatter 与中文 SOP。
- commit 使用 shared、Read/Bash；review 使用 isolated/history 12；test 使用 isolated/history 6。
- review/test 的 Bash 指令强调只运行调查或测试命令，不修改项目。
- 不在内置 Skill 指定 model、认证信息或权限模式。

验证：

- 解析三份内置 Skill，校验 mode、history 和白名单。
- 验证三条 Slash Command 自动出现且可被上层同名 Skill 覆盖。

依赖：T12。

## T14：接入 CLI 初始化、热更新、状态和清理

涉及文件：

- 修改 `huicode/cli.py`
- 修改 `huicode/commands/runtime.py`
- 修改 `huicode/commands/completion.py`
- 新增 `tests/test_cli_skills.py`
- 修改 `tests/test_cli_commands.py`
- 修改 `tests/test_tui.py`

任务：

- 在默认/MCP 工具注册后初始化 SkillManager，启动错误返回退出码 2。
- 注册系统 Skill 工具并构建首个动态命令 registry。
- 每次顶层输入分流前检查热更新；成功时刷新目录、active state、命令和补全，失败时保留旧快照。
- 启动摘要和 `/status` 显示 discovered、active、reload errors 和工具限制摘要。
- `/clear` 同时清除 active skills、工具限制和轮次模型覆盖。
- CLI 退出时不需要删除 Skill 文件或额外持久化目录快照。

验证：

- 运行 `python -m unittest tests.test_cli_skills tests.test_cli_commands tests.test_tui -v`。
- fake Provider 集成覆盖启动、shared/isolated 命令、热更新成功/失败、状态和 clear。

依赖：T13。

## T15：更新 README 与使用示例

涉及文件：

- 修改 `README.md`
- 视真实返工修改 `docs/mew-spec-pitfalls.md`

任务：

- 说明单文件和目录型格式、三级目录与覆盖优先级。
- 说明两阶段加载、shared/isolated、history_messages、model 和 `{{args}}`。
- 说明白名单只收窄工具、未知工具启动失败、Plan Mode 不可绕过。
- 说明自动 Slash Command、热更新、`/clear` 和内置 commit/review/test。
- 给出不包含真实密钥和绝对用户路径的示例。
- 若实现或真实验收出现已批准文档未覆盖的返工，追加踩坑记录。

验证：

- 对照 `/help`、`/status` 和实际目录逐项人工检查 README。
- 搜索确认 README 不再把 `/review` 描述为硬编码提示词。

依赖：T14。

## T16：完整回归、验收报告与 Git 提交

涉及文件：

- 新增 `specs/012-skill-system/acceptance_report.md`
- 更新 `specs/012-skill-system/checklist.md` 的执行证据
- 本章全部实现与测试文件

任务：

- 运行 Skill 专项测试和全量 unittest。
- 运行 compileall、diff check，并检查未跟踪文件范围。
- 验证 OpenAI/Anthropic、权限、上下文、记忆、MCP、Slash Command 和 Plan Mode 回归。
- 有 tmux 时运行真实 TUI；Windows 无 tmux 时使用 fake Provider CLI 集成场景并记录限制。
- 按 checklist 逐项记录实际证据，生成验收报告。
- 仅暂存本章相关文件，按 `AGENT.md` 创建 Git 提交。

验证：

- `python -m unittest discover -v`
- `python -m compileall -q huicode tests`
- `git diff --check`
- `git status --short` 确认未暂存用户无关文件。

依赖：T15 及此前全部任务。

## 文件变更总表

### 新增实现

- `huicode/skills/__init__.py`
- `huicode/skills/types.py`
- `huicode/skills/parser.py`
- `huicode/skills/discovery.py`
- `huicode/skills/catalog.py`
- `huicode/skills/manager.py`
- `huicode/skills/tool.py`
- `huicode/skills/runner.py`
- `huicode/skills/builtin/commit/SKILL.md`
- `huicode/skills/builtin/review/SKILL.md`
- `huicode/skills/builtin/test/SKILL.md`

### 修改实现

- `pyproject.toml`
- `huicode/agent_events.py`
- `huicode/agent.py`
- `huicode/provider_factory.py`
- `huicode/context/history.py`（仅在协议安全选择需要抽取公共函数时）
- `huicode/prompts/base.py`
- `huicode/prompts/builder.py`
- `huicode/prompts/modules.py`
- `huicode/tools/base.py`
- `huicode/tools/registry.py`
- `huicode/commands/types.py`
- `huicode/commands/registry.py`
- `huicode/commands/builtin.py`
- `huicode/commands/completion.py`
- `huicode/commands/runtime.py`
- `huicode/cli.py`
- `README.md`
- `docs/mew-spec-pitfalls.md`（只在出现真实返工时）

### 新增与修改测试

- 新增 `tests/test_skills_types.py`
- 新增 `tests/test_skills_parser.py`
- 新增 `tests/test_skills_discovery.py`
- 新增 `tests/test_skills_catalog.py`
- 新增 `tests/test_skills_manager.py`
- 新增 `tests/test_skills_tool.py`
- 新增 `tests/test_skills_runner.py`
- 新增 `tests/test_skills_commands.py`
- 新增 `tests/test_cli_skills.py`
- 修改 ToolRegistry、Agent、Prompt、Provider、Command、CLI、Memory 和 TUI 相关回归测试。

## 任务依赖关系

```text
T1 -> T2 -> T3 -----\
  \-> T4 ------------> T5 -> T6 -> T7 -> T8 -> T9 --\
                                           \----------> T10 -> T11 --\
T6 -----------------------------------------------------> T12 -> T13 -> T14 -> T15 -> T16
```

## 实施检查点

- **检查点 A（T1-T5）**：文件格式、三级目录、覆盖和全局校验可独立运行，尚不接入 Agent。
- **检查点 B（T6-T9）**：目录快照、Prompt、shared 激活、工具交集和模型覆盖可用 fake Provider 验证。
- **检查点 C（T10-T11）**：isolated 子循环与 OpenAI/Anthropic 历史回流协议合法。
- **检查点 D（T12-T14）**：动态命令、内置 Skill、热更新、状态和 `/clear` 完整接入 CLI。
- **检查点 E（T15-T16）**：文档、全量回归、端到端验收和 Git 提交闭环。

## 自检结论

- plan 中每个组件至少有一项实现任务和对应验证。
- 依赖顺序保证 MCP 工具先注册、Skill 白名单后校验，Runner 在 shared 基础链稳定后实现。
- 每个任务都列出具体文件、操作、验证命令和完成边界。
- 实现代码仍须等待 `checklist.md` 批准后开始。
