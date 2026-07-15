# HuiCode Hook 系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| 新建 | `huicode/hooks/__init__.py` | 导出 Hook 公共接口 |
| 新建 | `huicode/hooks/types.py` | 事件、规则、动作、结果和运行状态类型 |
| 新建 | `huicode/hooks/config.py` | 三层 Hook YAML 加载、合并与集中校验 |
| 新建 | `huicode/hooks/matching.py` | 字段读取与 exact/glob/regex/not/all/any 匹配 |
| 新建 | `huicode/hooks/events.py` | 标准事件构造、脱敏与载荷截断 |
| 新建 | `huicode/hooks/actions.py` | command、prompt、HTTP、subagent 动作执行 |
| 新建 | `huicode/hooks/logger.py` | 线程安全 JSONL 追加日志 |
| 新建 | `huicode/hooks/manager.py` | 规则调度、once、异步任务和 Prompt 生命周期 |
| 修改 | `huicode/config.py` | 使用完整 YAML 解析并暴露 inline hooks |
| 修改 | `huicode/agent_events.py` | AgentState 增加 HookRuntimeState |
| 修改 | `huicode/agent.py` | 发布轮次、消息、工具、错误和上下文事件 |
| 修改 | `huicode/context/manager.py` | 增加重量压缩生命周期回调 |
| 修改 | `huicode/prompts/base.py` | PromptContext 增加 Hook 指令块 |
| 修改 | `huicode/prompts/builder.py` | 构建非缓存 Hook 动态模块 |
| 修改 | `huicode/permissions/rules.py` | 提取共享匹配和工具名规范化能力 |
| 修改 | `huicode/permissions/engine.py` | 保护 Hook 日志目录不被模型写入 |
| 修改 | `huicode/skills/runner.py` | isolated Skill 复用 HookManager 与 ContextManager |
| 修改 | `huicode/commands/runtime.py` | 手动压缩、clear、status 与 Hook 集成 |
| 修改 | `huicode/cli.py` | Hook 启动、session 事件、摘要和统一关闭 |
| 修改 | `README.md` | 增加 Hook 配置与行为说明 |
| 条件修改 | `docs/mew-spec-pitfalls.md` | 记录本章实现后出现的真实返工问题 |
| 新建 | `tests/test_hooks_config.py` | 配置来源、覆盖和校验测试 |
| 新建 | `tests/test_hooks_matching.py` | 条件匹配矩阵测试 |
| 新建 | `tests/test_hooks_events.py` | 事件载荷、脱敏和截断测试 |
| 新建 | `tests/test_hooks_actions.py` | 四类动作与安全边界测试 |
| 新建 | `tests/test_hooks_manager.py` | 调度、once、异步、日志、Prompt 状态测试 |
| 新建 | `tests/test_agent_hooks.py` | Agent 生命周期、拦截与回灌集成测试 |
| 新建 | `tests/test_cli_hooks.py` | 启动、退出、状态和真实 CLI 流程测试 |
| 修改 | `tests/test_config.py` | 完整 YAML 与现有配置兼容测试 |
| 修改 | `tests/test_permissions_rules.py` | 共享匹配保持权限行为的回归测试 |
| 修改 | `tests/test_prompt_builder.py` | Hook Prompt 模块顺序和缓存属性测试 |
| 修改 | `tests/test_agent_context.py` | 自动压缩 Hook 事件测试 |
| 修改 | `tests/test_cli.py` | Hook 配置错误和资源关闭回归测试 |
| 修改 | `tests/test_cli_skills.py` | isolated Skill Hook 继承与状态隔离测试 |
| 新建 | `specs/013-hook-system/acceptance_report.md` | 记录逐项验收证据 |

## T1：建立 Hook 类型与包导出

**文件：** `huicode/hooks/types.py`、`huicode/hooks/__init__.py`

**依赖：** 无

**步骤：**

1. 定义全部事件名、动作类型、状态枚举和公开事件字段 schema。
2. 定义 HookEvent、HookRule、HookCatalog、HookCondition、四种 Action、ActionResult 和 DispatchResult。
3. 定义 HookPromptBlock、HookRuntimeState 与 HookStatusSummary。
4. 在包入口只导出外部调用所需类型，避免循环依赖。

**验证：** 运行 `python -m compileall huicode/hooks`；从 Python 导入所有公开类型并实例化最小 HookEvent，预期无导入错误。

## T2：升级主配置 YAML 解析并暴露 inline hooks

**文件：** `huicode/config.py`、`tests/test_config.py`

**依赖：** T1

**步骤：**

1. 用 PyYAML safe_load 替换主配置手写结构解析入口，保留 ConfigError 包装和现有业务字段转换。
2. 为 YAML 语法错误保留行列信息，为非映射根节点返回明确错误。
3. 给 LLMConfig 增加 hooks 原始规则列表，校验 hooks 为列表且每项为映射。
4. 增加列表内嵌映射、嵌套条件和现有 context/memory/mcp 配置回归用例。

**验证：** 运行 `python -m unittest tests.test_config -v`；预期新旧配置测试全部通过。

## T3：实现三层 Hook 配置发现与确定性合并

**文件：** `huicode/hooks/config.py`、`tests/test_hooks_config.py`

**依赖：** T1、T2

**步骤：**

1. 定义用户级与项目级 Hook 路径，并读取根节点 `hooks` 列表。
2. 接收主配置 inline hooks，按用户、inline、项目顺序加载。
3. 检查单一来源重复 id；跨层相同 id 删除旧项并按高层位置追加。
4. 统计有效、禁用与来源数量，并保存来源标签和文件路径。
5. 覆盖文件不存在、空文件、BOM、同 id 覆盖和不同 id 合并测试。

**验证：** 运行 `python -m unittest tests.test_hooks_config.HookConfigMergeTests -v`；预期顺序、来源和统计断言通过。

## T4：实现 Hook 定义集中校验

**文件：** `huicode/hooks/config.py`、`tests/test_hooks_config.py`

**依赖：** T3

**步骤：**

1. 解析 event、enabled、once、async、timeout 和四种 action 的必需字段。
2. 校验 id 格式、event 合法性、timeout 1-300 秒和动作事件兼容矩阵。
3. 展开 command env、HTTP URL/headers 中的 `${VAR}`，未定义变量报字段路径。
4. 校验 Prompt 与 subagent 模板字段属于对应事件公开 schema。
5. 确保 enabled=false 的规则仍做完整校验。
6. 为每类错误断言消息包含规则 id、来源和字段。

**验证：** 运行 `python -m unittest tests.test_hooks_config.HookConfigValidationTests -v`；预期非法配置全部被启动期拒绝。

## T5：提取共享匹配语义并实现 Hook 条件

**文件：** `huicode/hooks/matching.py`、`huicode/permissions/rules.py`、`tests/test_hooks_matching.py`、`tests/test_permissions_rules.py`

**依赖：** T1、T4

**步骤：**

1. 提取大小写敏感 exact/glob 匹配和 canonical tool name helper。
2. 让现有权限 match_rule 复用共享函数，保持“精确或 glob”兼容行为。
3. 实现点号字段读取、regex 搜索、not 取反和缺失字段语义。
4. 实现 all/any 单层组合，无 `if` 时直接匹配。
5. 在配置加载时预编译 regex，并拒绝 all/any 混用和空条件组。

**验证：** 运行 `python -m unittest tests.test_hooks_matching tests.test_permissions_rules -v`；预期 Hook 匹配矩阵与权限旧行为全部通过。

## T6：实现标准事件工厂和递归脱敏

**文件：** `huicode/hooks/events.py`、`tests/test_hooks_events.py`

**依赖：** T1、T5

**步骤：**

1. 实现 session、turn、message、tool、context、agent_error 事件工厂。
2. 工具事件使用 canonical name 和 `target_value_for_call()` 生成稳定目标摘要。
3. 递归转换 Path、dataclass 和基础集合为 JSON 可序列化值。
4. 对密钥、认证、Cookie、密码、secret、token 字段二次脱敏。
5. 限制字符串、列表、映射和错误预览大小，不输出 thinking 内容。

**验证：** 运行 `python -m unittest tests.test_hooks_events -v`；把事件 payload 交给 `json.dumps(..., ensure_ascii=False)`，预期可序列化且敏感值不存在。

## T7：实现线程安全 Hook JSONL 日志

**文件：** `huicode/hooks/logger.py`、`tests/test_hooks_manager.py`

**依赖：** T1、T6

**步骤：**

1. 向 `.huicode/logs/hooks.jsonl` 追加单行 UTF-8 JSON。
2. 使用锁保护并发写，记录 status、耗时、rule/event/action/scope 和有界摘要。
3. 写入前再次脱敏并限制单行大小。
4. 捕获目录创建和写入错误，累计 write_failures 而不向调用方抛出。
5. 增加并发追加、坏目录和敏感字段测试。

**验证：** 运行 `python -m unittest tests.test_hooks_manager.HookLoggerTests -v`；逐行解析日志均成功，故障用例不抛异常。

## T8：实现 command 动作与安全边界

**文件：** `huicode/hooks/actions.py`、`tests/test_hooks_actions.py`

**依赖：** T1、T6

**步骤：**

1. 将事件 payload 编码为 UTF-8 JSON stdin，固定 command/args 不接受事件字段命令行拼接。
2. 默认 cwd 为 workspace；自定义 cwd 解析符号链接并限制在 workspace。
3. 执行前复用危险命令黑名单检查完整命令。
4. 捕获 stdout/stderr bytes，按 UTF-8、系统编码、GB18030 回退解码并截断。
5. 区分退出码 0、tool_before 退出码 2、其他非零和 TimeoutExpired。
6. 测试中文 stdin、危险命令、越界 cwd、拒绝原因和超时。

**验证：** 运行 `python -m unittest tests.test_hooks_actions.CommandActionTests -v`；预期所有状态和安全边界断言通过。

## T9：实现 HTTP、Prompt 与 SubAgent 动作

**文件：** `huicode/hooks/actions.py`、`tests/test_hooks_actions.py`

**依赖：** T4、T6、T8

**步骤：**

1. 使用标准库 HTTP 客户端发送统一 JSON payload，支持 method、headers、期望状态和 timeout。
2. 解析 tool_before 的 2xx deny JSON；连接、状态和响应格式错误转换为 Hook 失败。
3. 实现 Prompt 安全字段替换与注入回调，不写 ConversationMessage。
4. 实现 SubAgent 固定 skipped 占位，确保不接触 Provider。
5. 使用本地测试 HTTP Server 覆盖成功、deny、断连、无效 JSON 和超时。

**验证：** 运行 `python -m unittest tests.test_hooks_actions.HttpPromptSubagentActionTests -v`；预期四类结果可区分且无外网依赖。

## T10：实现同步 Hook 调度与明确拒绝

**文件：** `huicode/hooks/manager.py`、`tests/test_hooks_manager.py`

**依赖：** T5、T7、T8、T9

**步骤：**

1. 按目录顺序筛选 event、enabled 和 condition。
2. 在动作边界捕获所有异常并转换为 failed 日志。
3. 实现 once 原子标记，第一次匹配后无论结果如何都不重跑。
4. 只允许 tool_before 的合法 ActionResult 转成 DispatchResult.denied。
5. 遇到明确拒绝后停止剩余 tool_before 规则，保留 rule id 与有界原因。
6. 增加顺序、无条件、once、运行失败继续和首个拒绝停止测试。

**验证：** 运行 `python -m unittest tests.test_hooks_manager.HookManagerSyncTests -v`；预期调度顺序和拒绝语义通过。

## T11：实现异步调度、Prompt 生命周期和有界关闭

**文件：** `huicode/hooks/manager.py`、`tests/test_hooks_manager.py`

**依赖：** T10

**步骤：**

1. 建立小型 daemon worker 池、pending futures 集合和完成回调。
2. 异步提交时记录 scheduled，完成时补记最终状态；后台回调不持有 AgentState。
3. 实现 session、turn、next_request Prompt 块存储、渲染和清理。
4. 实现 close 停止接收任务、最多等待 2 秒、取消或标记未完成项。
5. 暴露有效数、pending、失败、拒绝和日志写入失败统计。
6. 测试后台不阻塞、once 异步只提交一次、Prompt 三种 scope 和有界退出。

**验证：** 运行 `python -m unittest tests.test_hooks_manager -v`；预期完整 Manager 测试通过且慢任务关闭耗时不超过测试上限。

## T12：把 Hook Prompt 状态接入 AgentState 和 PromptBuilder

**文件：** `huicode/agent_events.py`、`huicode/prompts/base.py`、`huicode/prompts/builder.py`、`tests/test_prompt_builder.py`

**依赖：** T1、T11

**步骤：**

1. 给 AgentState 增加默认 HookRuntimeState。
2. 给 PromptContext 增加 hook_instruction_blocks。
3. 将每个 Hook block 构造成独立、dynamic、non-cacheable PromptModule。
4. 固定模块顺序为 active Skill、Hook、environment、既有 supplemental。
5. 测试 Hook 文本不进入 stable/cacheable 模块，也不伪装成用户消息。

**验证：** 运行 `python -m unittest tests.test_prompt_builder tests.test_prompt_cache -v`；预期模块顺序和缓存断言通过。

## T13：为上下文重量压缩增加生命周期回调

**文件：** `huicode/context/manager.py`、`tests/test_agent_context.py`、`tests/test_context_manager.py`

**依赖：** T6

**步骤：**

1. 定义无 Hook 依赖的 ContextLifecycleCallbacks。
2. 自动与手动压缩入口把 callbacks 传到重量摘要路径。
3. 摘要尝试前调用 before；summary、skip、failure 后调用 after。
4. 轻量工具结果落盘不误触重量压缩事件。
5. 回调异常不得改变 ContextCompressionReport。

**验证：** 运行 `python -m unittest tests.test_context_manager tests.test_agent_context -v`；预期自动、手动、跳过、失败和回调异常用例通过。

## T14：接入轮次、消息、错误和 Prompt 生命周期事件

**文件：** `huicode/agent.py`、`tests/test_agent_hooks.py`

**依赖：** T6、T11、T12、T13

**步骤：**

1. run_agent_loop 接收可选 HookManager、ContextManager 和 agent_scope，未提供时保持原行为。
2. 在用户消息前后按规范发布 turn_start、message_received。
3. 完整模型响应写历史后发布 message_completed。
4. Provider/API/Agent 错误发布 agent_error，Hook 失败不进入该事件。
5. 所有 done 原因恰好发布一次 turn_end，并清理 turn/未消费 next-request 块。
6. Provider 请求 finally 消费 next_request 块，失败请求同样消费。

**验证：** 运行 `python -m unittest tests.test_agent_hooks.AgentLifecycleHookTests -v`；预期事件顺序、停止原因和 Prompt 清理断言通过。

## T15：接入 tool_before/tool_after 与批处理协议配对

**文件：** `huicode/agent.py`、`tests/test_agent_hooks.py`、`tests/test_tool_batching.py`

**依赖：** T10、T14

**步骤：**

1. 在读工具线程池提交前，按调用顺序同步执行所有 tool_before。
2. Hook 明确拒绝时构造 `hook_denied` ToolResult，包含 rule id、原因和 source。
3. 未拒绝调用继续按 Hook、Plan Mode、权限、真实工具顺序执行。
4. 所有成功、工具失败、Plan/权限拒绝和 Hook 拒绝都发布一次 tool_after。
5. 保持多 ToolCall 的 tool_result 数量、顺序和 id 一一配对。
6. 验证 Hook 拒绝不触发权限确认，Agent 收到结果后继续下一次模型请求。

**验证：** 运行 `python -m unittest tests.test_agent_hooks.ToolHookIntegrationTests tests.test_tool_batching -v`；预期并发、拒绝与 Anthropic 安全配对断言通过。

## T16：接入 isolated Skill 并验证状态隔离

**文件：** `huicode/skills/runner.py`、`tests/test_cli_skills.py`、`tests/test_skills_runner.py`

**依赖：** T14、T15

**步骤：**

1. SkillRunner 接收可选共享 HookManager 与 ContextManager。
2. 子 Agent Loop 使用 `skill:<name>` agent_scope 并传入共享 Manager。
3. 确保 session Prompt 与 once 规则进程级共享。
4. 确保子 Agent turn/next-request blocks 留在子 AgentState，不进入主 AgentState。
5. 验证 isolated Skill 的工具调用同样能被 tool_before 拒绝。

**验证：** 运行 `python -m unittest tests.test_skills_runner tests.test_cli_skills -v`；预期 Skill 旧用例及 Hook 新用例通过。

## T17：接入 CLI 启动、会话事件和统一资源关闭

**文件：** `huicode/cli.py`、`tests/test_cli_hooks.py`、`tests/test_cli.py`

**依赖：** T3、T11、T14、T16

**步骤：**

1. MCP、权限、记忆、Skill 完成后加载 HookCatalog；错误时清理已启动资源并返回 2。
2. 创建 HookManager，完成运行时接线后发布一次 session_start。
3. 启动输出有效、禁用和来源摘要。
4. 将 HookManager/ContextManager 传入普通请求和 isolated Skill。
5. 统一 EOF、`/exit` 和正常返回路径：先 session_end、再有界关闭 Hook，最后关闭 Memory/MCP。
6. 用关闭标记保证 session_end 和 close 最多执行一次。

**验证：** 运行 `python -m unittest tests.test_cli_hooks.CLIHookLifecycleTests tests.test_cli -v`；预期各退出路径和配置错误清理通过。

## T18：接入手动压缩、clear、status 和日志目录保护

**文件：** `huicode/commands/runtime.py`、`huicode/permissions/engine.py`、`tests/test_cli_hooks.py`、`tests/test_permissions_engine.py`

**依赖：** T12、T13、T17

**步骤：**

1. CLICommandRuntime 保存 HookManager，并为 `/compact` 构造 context callbacks。
2. `/clear` 清除当前 AgentState 的 turn/next-request Hook 块，不清 session 块和 once 集合。
3. `/status` 输出 Hook effective、pending、failed 和日志位置摘要。
4. 把 `.huicode/logs` 纳入 Write/Edit 与有副作用 Bash 的内部状态保护。
5. 本地 Slash Command 不误触 turn/message Hook。

**验证：** 运行 `python -m unittest tests.test_cli_hooks.CLIHookCommandTests tests.test_permissions_engine -v`；预期 compact 事件、clear/status 和目录保护通过。

## T19：完成动作、管理器与 CLI 故障隔离场景

**文件：** `tests/test_hooks_actions.py`、`tests/test_hooks_manager.py`、`tests/test_agent_hooks.py`、`tests/test_cli_hooks.py`

**依赖：** T17、T18

**步骤：**

1. 添加命令不存在、非 2 退出、HTTP 断连、HTTP 非预期状态和无效 deny JSON 用例。
2. 添加 logger 不可写、模板运行保护和后台 callback 异常用例。
3. 断言所有运行故障只记日志，不改变 Agent 最终 stop_reason。
4. 断言 Hook 运行故障不发布 agent_error，避免递归。
5. 断言日志中不出现 API key、Authorization、Cookie、secret 或 thinking 原文。

**验证：** 运行 `python -m unittest tests.test_hooks_actions tests.test_hooks_manager tests.test_agent_hooks tests.test_cli_hooks -v`；预期故障矩阵全部通过。

## T20：补充 README 配置与使用说明

**文件：** `README.md`

**依赖：** T18

**步骤：**

1. 说明用户级、inline、项目级路径和覆盖顺序。
2. 给出 command 格式化、tool_before 拦截、Prompt 注入和 HTTP 通知示例。
3. 说明 command stdin/HTTP body 的标准事件 JSON、exit 2 与 deny JSON 协议。
4. 说明 once/async/timeout、后台退出等待、日志路径和 SubAgent 占位限制。
5. 标注配置错误会阻止启动、运行错误只写日志。

**验证：** 对照 HookConfig parser 逐项检查示例字段；复制每个示例到临时配置并调用加载器，预期均能通过校验。

## T21：运行专项、全量与静态验证

**文件：** 全部本章修改文件

**依赖：** T19、T20

**步骤：**

1. 运行全部 Hook 专项和相关回归测试。
2. 运行完整 unittest，确认无 Hook 配置时旧功能不回归。
3. 运行 compileall 检查语法和导入。
4. 检查 `git diff --check`，修复空白错误。
5. 使用实际启动 HuiCode 的 Python 解释器重复完整测试或至少 Hook/CLI 专项，避免再次出现解释器依赖错位。

**验证：**

```powershell
python -m unittest discover -s tests -v
python -m compileall huicode tests
git diff --check
```

预期所有命令成功；Windows 符号链接权限相关既有 skip 可保留并记录。

## T22：执行端到端验收并记录证据

**文件：** `specs/013-hook-system/checklist.md`、`specs/013-hook-system/acceptance_report.md`

**依赖：** T21

**步骤：**

1. 检查 tmux 是否可用；可用时按 AGENT.md 在 tmux 启动 HuiCode。
2. Windows 无 tmux 时使用真实 CLI 输入流、真实配置加载器和 fake Provider 完成等价流程。
3. 配置 tool_before command Hook 拒绝 Write，确认文件不变、无权限确认、模型收到拒绝并继续。
4. 配置 turn_start Prompt、tool_after 后台 command 和 HTTP 本地测试服务，确认注入、日志和后台退出。
5. 验证 isolated Skill 工具 Hook、上下文压缩事件和三层配置覆盖。
6. 逐项勾选 checklist，并在 acceptance_report 记录命令、观察结果和限制。
7. 若验收暴露本章 Mew Spec 后真实返工，修复后更新 `docs/mew-spec-pitfalls.md` 再重跑相关项。

**验证：** checklist 无未解释失败项；acceptance_report 包含端到端结果、完整测试数量、解释器路径和 tmux 可用性说明。

## T23：审查变更范围并提交本章 Git

**文件：** 本章相关实现、测试、README、`specs/013-hook-system/`，以及有真实返工时的 `docs/mew-spec-pitfalls.md`

**依赖：** T22

**步骤：**

1. 查看 `git status --short` 与 `git diff --stat`，区分本章文件和用户已有未跟踪文件。
2. 只暂存本章相关文件，不删除、不暂存根目录旧临时文档和其他用户文件。
3. 查看 staged diff，确认无密钥、Hook 测试日志、临时配置或 `.huicode` 运行产物。
4. 创建中文 Git commit，说明 Hook 系统完成。

**验证：** `git show --stat --oneline HEAD` 只包含本章文件；`git status --short` 中用户原有未跟踪文件仍保持未跟踪。

## 执行顺序

```text
T1
  -> T2
  -> T3 -> T4
  -> T5 -> T6 -> T7
  -> T8 -> T9 -> T10 -> T11
  -> T12 -> T13 -> T14 -> T15
  -> T16 -> T17 -> T18
  -> T19 -> T20 -> T21 -> T22 -> T23
```

其中 T7 与 T8 可在 T6 后并行，T12 与 T13 可在 T11 后并行；实现阶段仍按上述主顺序逐项验证，降低跨模块失败定位成本。
