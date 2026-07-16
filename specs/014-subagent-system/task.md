# HuiCode 子 Agent 系统 Tasks

## 文件列表

| 操作 | 文件 | 职责 |
| --- | --- | --- |
| 新建 | `huicode/subagents/__init__.py` | 导出子 Agent 公共接口 |
| 新建 | `huicode/subagents/types.py` | 角色、快照、任务、结果、通知与租约类型 |
| 新建 | `huicode/subagents/parser.py` | Markdown frontmatter 解析和字段校验 |
| 新建 | `huicode/subagents/discovery.py` | 插件、内置、用户、项目角色文件发现 |
| 新建 | `huicode/subagents/catalog.py` | 角色覆盖、全局校验和启动统计 |
| 新建 | `huicode/subagents/history.py` | Fork 协议安全历史边界选择 |
| 新建 | `huicode/subagents/filtering.py` | 子 Agent 工具逐层收窄 |
| 新建 | `huicode/subagents/workers.py` | 有界守护线程任务池 |
| 新建 | `huicode/subagents/runner.py` | 定义式/Fork 式隔离 Agent Loop 执行 |
| 新建 | `huicode/subagents/manager.py` | 任务状态机、通知、结果租约和生命周期 |
| 新建 | `huicode/subagents/tool.py` | 固定 Schema 的系统级 `Agent` 工具 |
| 新建 | `huicode/subagents/terminal.py` | TTY/非 TTY 前台等待及 `Ctrl+B` 适配 |
| 新建 | `huicode/subagents/builtin/general.md` | Hook 默认通用角色 |
| 新建 | `huicode/subagents/builtin/explorer.md` | 只读项目调查角色 |
| 新建 | `huicode/subagents/builtin/reviewer.md` | 代码审查角色 |
| 新建 | `huicode/permissions/snapshot.py` | 权限快照复制和严格度合并 |
| 修改 | `huicode/config.py` | 解析并校验 `subagents` 配置 |
| 修改 | `huicode/tools/base.py` | 为 ToolContext 增加独立读缓存 |
| 修改 | `huicode/tools/files.py` | Read 工具接入当前 Agent 读缓存 |
| 修改 | `huicode/tools/registry.py` | 支持按最终可见集合克隆注册表 |
| 修改 | `huicode/agent.py` | 父快照、Prompt override、结果租约与子运行时接入 |
| 修改 | `huicode/agent_events.py` | 补充子 Agent Loop 所需可选状态/事件数据 |
| 修改 | `huicode/prompts/base.py` | 角色目录、角色正文、后台结果和稳定模块覆盖字段 |
| 修改 | `huicode/prompts/builder.py` | 构建角色与 `subagent_results` 动态模块 |
| 修改 | `huicode/hooks/types.py` | 为 SubagentAction 增加角色字段 |
| 修改 | `huicode/hooks/config.py` | 解析 Hook 子 Agent 角色 |
| 修改 | `huicode/hooks/actions.py` | 真实提交后台子 Agent并阻止递归 |
| 修改 | `huicode/hooks/manager.py` | 支持后绑定 Subagent submitter |
| 修改 | `huicode/commands/ui.py` | 扩展角色与任务命令服务协议 |
| 修改 | `huicode/commands/builtin.py` | 注册 `/agents`、`/tasks` |
| 修改 | `huicode/commands/runtime.py` | 命令实现、状态栏、清理与任务状态摘要 |
| 修改 | `huicode/cli.py` | 初始化、通知泵、Agent 工具注册和有界关闭 |
| 修改 | `huicode/tui.py` | 子 Agent 状态与完成通知渲染 |
| 修改 | `huicode/provider_factory.py` | 通用模型覆盖错误文本与子 Agent 调用复用 |
| 修改 | `README.md` | 角色、配置、命令和后台行为使用说明 |
| 修改 | `docs/mew-spec-pitfalls.md` | 仅在本章出现真实返工时追加记录 |
| 新建 | `tests/test_subagent_config.py` | 配置解析与错误测试 |
| 新建 | `tests/test_subagent_catalog.py` | 四层发现、覆盖和角色校验测试 |
| 新建 | `tests/test_subagent_history.py` | Fork 历史协议边界测试 |
| 新建 | `tests/test_subagent_filtering.py` | 工具与权限收窄测试 |
| 新建 | `tests/test_subagent_manager.py` | 并发、状态、通知、租约和关闭测试 |
| 新建 | `tests/test_subagent_runner.py` | 定义式/Fork 隔离执行测试 |
| 新建 | `tests/test_subagent_tool.py` | Agent 工具参数与前后台行为测试 |
| 新建 | `tests/test_subagent_result_delivery.py` | 后台结果回流与重试测试 |
| 新建 | `tests/test_subagent_commands.py` | `/agents`、`/tasks`、状态与清理测试 |
| 新建 | `tests/test_subagent_hooks.py` | Hook 提交与递归保护测试 |
| 新建 | `tests/test_subagent_terminal.py` | 超时、手动切换及非 TTY 降级测试 |
| 新建 | `tests/test_subagent_cli_e2e.py` | fake Provider 端到端 CLI 场景 |
| 新建 | `specs/014-subagent-system/acceptance_report.md` | 本章逐项验收证据 |

## T1：增加并校验子 Agent 主配置

**文件：** `huicode/config.py`、`tests/test_subagent_config.py`

**依赖：** 无

**步骤：**

1. 增加冻结的 `SubagentConfig` 并挂到 `LLMConfig.subagents`。
2. 解析前台时限、后台并发、关闭等待、后台工具白名单和模型别名。
3. 校验数值为正、白名单为非空字符串列表、别名键只允许 haiku/sonnet/opus 且值非空。
4. 保持未配置时的默认值与现有配置兼容。
5. 为合法、缺省和逐字段非法配置补单元测试。

**验证：** 运行 `python -m unittest tests.test_subagent_config -v`；预期所有配置测试通过，错误信息包含完整字段路径。

## T2：定义子 Agent 领域类型

**文件：** `huicode/subagents/types.py`、`huicode/subagents/__init__.py`

**依赖：** T1

**步骤：**

1. 定义角色来源、角色定义和目录快照类型。
2. 定义父快照、启动请求、任务状态、任务详情、结果和通知类型。
3. 定义结果租约及前台等待结果类型。
4. 为状态枚举和公开类型补稳定序列化方法，确保不序列化 thinking。
5. 从包入口导出后续模块需要的类型。

**验证：** 运行 `python -m compileall -q huicode/subagents`；预期无导入和语法错误。

## T3：实现角色 Markdown 解析器

**文件：** `huicode/subagents/parser.py`、`tests/test_subagent_catalog.py`

**依赖：** T2

**步骤：**

1. 复用 PyYAML 解析 frontmatter，不执行模板或脚本。
2. 校验必填字段、名称格式、模型枚举、权限模式、最大轮次和非空正文。
3. 将格式语法错误标记为可跳过诊断，将安全字段错误标记为致命配置错误。
4. 保留来源路径和字段名用于用户可见错误。
5. 覆盖 UTF-8、BOM、空正文、错误 YAML 和非法字段测试。

**验证：** 运行 `python -m unittest tests.test_subagent_catalog.RoleParserTests -v`；预期合法角色可解析，错误分类符合 Spec。

## T4：实现四层角色发现与覆盖

**文件：** `huicode/subagents/discovery.py`、`huicode/subagents/catalog.py`、`tests/test_subagent_catalog.py`

**依赖：** T3

**步骤：**

1. 定义插件、内置、用户、项目四类可注入 root，并按低到高顺序发现 `*.md`。
2. 同名跨层整体覆盖；同层重名抛出致命错误。
3. 汇总有效数、覆盖数、跳过数、来源数量和可见警告。
4. 对照最终工具注册表验证 allowed/denied 工具，并硬拒绝 Agent、Skill。
5. 验证角色引用的模型别名已在主配置映射。
6. 提供 `get/list/summary` 只读接口。

**验证：** 运行 `python -m unittest tests.test_subagent_catalog -v`；预期四层覆盖顺序、跳过与致命错误全部通过。

## T5：增加保守内置角色

**文件：** `huicode/subagents/builtin/general.md`、`explorer.md`、`reviewer.md`、`tests/test_subagent_catalog.py`

**依赖：** T4

**步骤：**

1. 编写通用、只读调查和审查三个 UTF-8 角色。
2. 全部使用 `inherit`，避免默认依赖模型别名。
3. 为每个角色设置最小工具白名单、合理轮次和保守权限模式。
4. 验证内置目录可被 catalog 加载，用户/项目同名角色可以覆盖。

**验证：** 运行 `python -m unittest tests.test_subagent_catalog.BuiltinRoleTests -v`；预期三个角色有效且覆盖顺序正确。

## T6：实现 Fork 协议安全历史选择

**文件：** `huicode/subagents/history.py`、`tests/test_subagent_history.py`

**依赖：** T2

**步骤：**

1. 按 assistant tool_calls 与紧随其后的 tool_result 分组。
2. 删除孤立工具结果和末尾未配对工具调用组。
3. 保留普通 user/assistant 消息和完整多工具调用组的原顺序。
4. 返回不可变深拷贝，防止父历史后续追加影响 Fork。
5. 覆盖 DeepSeek/Anthropic thinking 字段和多工具并发组测试。

**验证：** 运行 `python -m unittest tests.test_subagent_history -v`；预期每个保留的 tool call 都有对应结果，父消息修改不影响快照。

## T7：实现权限快照与严格度合并

**文件：** `huicode/permissions/snapshot.py`、`tests/test_subagent_filtering.py`

**依赖：** T2

**步骤：**

1. 复制父权限模式、项目规则与当前会话规则，避免共享可变列表。
2. 定义 strict、default、permissive 的严格度顺序。
3. 定义式取父模式和角色模式中更严格者；Fork 原样复制父模式。
4. 子权限上下文禁用 confirmer 和 persistent path。
5. 验证子 Agent 新增 session/once 决策不会写回父上下文。

**验证：** 运行 `python -m unittest tests.test_subagent_filtering.PermissionSnapshotTests -v`；预期模式只收紧且父子状态隔离。

## T8：实现工具逐层收窄

**文件：** `huicode/subagents/filtering.py`、`huicode/tools/registry.py`、`tests/test_subagent_filtering.py`

**依赖：** T4、T7

**步骤：**

1. 从父快照实际可见工具名开始计算最终集合。
2. 固定删除 Agent、Skill，再应用角色 allow、角色 deny、后台 allow 和 PLAN 只读限制。
3. 生成只包含最终工具的 registry clone，保留合法别名和 MCP 工具对象。
4. 验证过滤结果既影响 Provider specs，也影响实际 `execute_tool_call()`。
5. 覆盖 permissive 角色无法放宽父 PLAN/default/strict 的测试。

**验证：** 运行 `python -m unittest tests.test_subagent_filtering -v`；预期所有组合只减不增，Agent/Skill 永远不可见不可执行。

## T9：增加每 Agent 独立文件读缓存

**文件：** `huicode/tools/base.py`、`huicode/tools/files.py`、`tests/test_subagent_runner.py`

**依赖：** T2

**步骤：**

1. 定义线程安全 `FileReadCache` 并作为 ToolContext 可选字段。
2. Read 在完成权限和沙箱校验后按 resolved path、mtime、size 读写缓存。
3. 不改变 Read 的 ToolResult 结构和错误语义。
4. 验证同上下文重复读取命中、文件变化失效、不同上下文不共享。

**验证：** 运行 `python -m unittest tests.test_subagent_runner.FileReadCacheTests -v tests.test_tools_files -v`；预期缓存测试和原 Read 回归通过。

## T10：实现 Prompt 扩展点

**文件：** `huicode/prompts/base.py`、`huicode/prompts/builder.py`、`tests/test_prompt_builder.py`、`tests/test_subagent_runner.py`

**依赖：** T2

**步骤：**

1. 增加角色轻量目录、持续角色正文、后台结果块和稳定模块覆盖输入。
2. 角色正文置于动态高优先级模块，每轮重建都存在。
3. 后台结果渲染为一次 `<huicode_context type="subagent_results">`，限制长度并转义边界。
4. Fork 稳定模块覆盖必须保持父模块文本和顺序不变。
5. 默认输入为空时保持现有 Prompt 快照不变。

**验证：** 运行 `python -m unittest tests.test_prompt_builder tests.test_anthropic_provider_prompts tests.test_openai_provider_prompts -v`；预期新增模块正确，现有 Provider Prompt 回归通过。

## T11：实现有界守护 Worker

**文件：** `huicode/subagents/workers.py`、`tests/test_subagent_manager.py`

**依赖：** T2

**步骤：**

1. 创建固定数量 daemon worker 和有界工作队列。
2. 支持提交、停止接收、广播取消和限时关闭。
3. 捕获任务异常并传给完成回调，不允许 worker 静默死亡。
4. 验证超过并发数的任务排队且线程数不增长。
5. 验证阻塞任务不会让 `close(timeout)` 无限等待。

**验证：** 运行 `python -m unittest tests.test_subagent_manager.DaemonWorkerTests -v`；预期并发上限、异常与有界退出测试通过。

## T12：实现任务状态机、通知和结果租约

**文件：** `huicode/subagents/manager.py`、`tests/test_subagent_manager.py`、`tests/test_subagent_result_delivery.py`

**依赖：** T11

**步骤：**

1. 实现合法状态迁移和锁内任务更新。
2. 保存完整脱敏结果并生成有界 UI 通知。
3. 实现按完成顺序 acquire/ack/release 的结果租约。
4. 实现 list/detail/summary、取消、clear 和 close。
5. 验证失败请求 release 后可再次获取，ack 后不再出现。
6. 验证 `/clear` 使旧 lease 和待交付结果失效。

**验证：** 运行 `python -m unittest tests.test_subagent_manager tests.test_subagent_result_delivery -v`；预期状态、并发、租约和脱敏测试通过。

## T13：实现终端前台切换控制器

**文件：** `huicode/subagents/terminal.py`、`tests/test_subagent_terminal.py`

**依赖：** T12

**步骤：**

1. 定义可注入的 `ForegroundSwitchController` 协议。
2. 实现完成事件、超时和手动信号三路竞争，确保只返回一次。
3. Windows 适配 `msvcrt`，POSIX 适配 `select/termios`，并在 finally 恢复终端。
4. 非 TTY 控制器只支持完成与超时。
5. 保证 Ctrl+C 不被识别为手动转后台。

**验证：** 运行 `python -m unittest tests.test_subagent_terminal -v`；预期完成、超时、Ctrl+B 模拟、Ctrl+C 与非 TTY 降级通过。

## T14：实现隔离子 Agent Runner

**文件：** `huicode/subagents/runner.py`、`huicode/provider_factory.py`、`tests/test_subagent_runner.py`

**依赖：** T6、T8、T9、T10、T12

**步骤：**

1. 为每个任务创建独立 AgentState、ContextManager、ToolContext、权限和读缓存。
2. 定义式从空历史构造角色 Prompt 与 task，不连接父 memory、Skill 或结果队列。
3. Fork 复制安全历史并复用父稳定 Prompt 模块。
4. 按 inherit/模型别名创建 Provider 覆盖，其他 LLM 配置保持不变。
5. 每轮按前台/后台状态重新计算工具集并传入 `run_agent_loop()`。
6. 聚合 usage、迭代、stop reason 和 final/error 摘要，过滤 thinking 与敏感字段。
7. 将 cancel_event 安全映射到子 Agent 取消状态。

**验证：** 运行 `python -m unittest tests.test_subagent_runner -v`；预期定义式/Fork 上下文、隔离、模型覆盖、停止条件和 usage 测试通过。

## T15：实现固定 Schema 的 Agent 工具

**文件：** `huicode/subagents/tool.py`、`tests/test_subagent_tool.py`

**依赖：** T12、T13、T14

**步骤：**

1. 定义固定 name、description、parameters 和 system tool 属性。
2. 校验 type、task、role、background 及 defined/fork 参数组合。
3. defined 前台等待完成、配置超时或 Ctrl+B；后两者将任务转后台。
4. defined 显式后台与 Fork 立即返回 task id；Fork 强制后台。
5. 所有参数、角色、提交和执行错误都转为结构化 ToolResult。
6. 比较零/多角色、DEFAULT/PLAN 和有无任务时的工具 Schema 完全一致。

**验证：** 运行 `python -m unittest tests.test_subagent_tool -v`；预期 Schema 稳定、参数错误和四种前后台路径通过。

## T16：把父快照和结果租约接入 Agent Loop

**文件：** `huicode/agent.py`、`huicode/agent_events.py`、`tests/test_subagent_result_delivery.py`、`tests/test_subagent_runner.py`

**依赖：** T10、T12、T15

**步骤：**

1. 为 `run_agent_loop()` 增加默认关闭的子运行时和 Prompt override 参数。
2. 仅主 scope 在 Provider 请求前捕获消息、Prompt、实际 tools、模式和权限快照。
3. 仅主 scope acquire 待交付结果并加入动态 Prompt。
4. 完整流响应后 ack；API/流错误、KeyboardInterrupt 和异常时 release。
5. 子 scope 不捕获父快照、不交付主结果。
6. 验证未传子运行时时现有 Agent 行为和函数调用兼容。

**验证：** 运行 `python -m unittest -v tests.test_subagent_result_delivery tests.test_agent_loop tests.test_agent`；预期一次性交付、失败重试和现有 Loop 回归通过。

## T17：验证 Fork 缓存资格

**文件：** `tests/test_subagent_history.py`、`tests/test_subagent_runner.py`、`tests/test_anthropic_provider_prompts.py`、`tests/test_openai_provider_prompts.py`

**依赖：** T14、T16

**步骤：**

1. 捕获父请求与 Fork 首次请求的序列化输入。
2. 比较稳定 system 模块字节文本与继承历史前缀。
3. 验证当前未配对 Agent tool call 不进入 Fork。
4. 让 fake Provider 返回 cache read/create usage，验证任务详情可观察。
5. 覆盖 Anthropic 与 OpenAI 两种序列化路径。

**验证：** 运行 `python -m unittest tests.test_subagent_history tests.test_subagent_runner.ForkCacheTests tests.test_anthropic_provider_prompts tests.test_openai_provider_prompts -v`；预期前缀一致且 cache usage 保留。

## T18：对接 Hook Subagent 动作

**文件：** `huicode/hooks/types.py`、`huicode/hooks/config.py`、`huicode/hooks/actions.py`、`huicode/hooks/manager.py`、`tests/test_subagent_hooks.py`、`tests/test_hooks_actions.py`

**依赖：** T12、T14

**步骤：**

1. 为 SubagentAction 增加可选 role，默认 general。
2. 解析和模板校验 role/task，禁止 Fork 参数。
3. 为 HookActionExecutor 增加后绑定 submitter。
4. main scope 提交真实 defined/background 任务并记录 task id。
5. 任意 `subagent:*` scope 返回 skipped/recursion_guard，不创建任务。
6. 提交失败只形成 Hook 日志结果，不改变主 Agent stop reason。

**验证：** 运行 `python -m unittest tests.test_subagent_hooks tests.test_hooks_actions tests.test_hooks_manager -v`；预期真实提交、默认角色、递归保护和 Hook 回归通过。

## T19：增加角色与任务 Slash Command

**文件：** `huicode/commands/ui.py`、`huicode/commands/builtin.py`、`huicode/commands/runtime.py`、`tests/test_subagent_commands.py`

**依赖：** T4、T12

**步骤：**

1. 注册公开 `/agents [name]` 和 `/tasks [task-id]`。
2. 列表展示来源、类型、状态和有界摘要；详情不输出角色正文或敏感数据。
3. `/status` 增加 queued/running/ready/failed 数量。
4. toolbar 增加紧凑任务计数。
5. `/clear` 取消任务、清任务表和待交付结果。
6. 补帮助列表、命令解析和错误用法测试。

**验证：** 运行 `python -m unittest tests.test_subagent_commands tests.test_commands_builtin tests.test_commands_runtime -v`；预期命令、帮助、状态与 clear 行为通过。

## T20：接入 CLI 初始化、通知和关闭流程

**文件：** `huicode/cli.py`、`huicode/tui.py`、`tests/test_subagent_cli_e2e.py`

**依赖：** T15、T16、T18、T19

**步骤：**

1. 在 MCP/工具完成后初始化角色 catalog，输出启动统计和警告。
2. 创建 manager/runner，注册 system Agent tool，并后绑定 Hook submitter。
3. 向主 `_run_request()` 传入子运行时。
4. 实现队列驱动通知适配器，TTY 安全刷新输入，非 TTY 在输入边界 drain。
5. 为前台等待渲染 Ctrl+B 提示和后台转换结果。
6. `/exit`/EOF 按配置停止接收、取消并限时关闭，再关闭 Hook、Memory、MCP。
7. 初始化失败时逆序释放已启动资源。

**验证：** 运行 `python -m unittest -v tests.test_subagent_cli_e2e tests.test_cli_commands tests.test_cli_skills tests.test_cli_hooks`；预期启动、通知、命令、资源清理及已有 CLI 回归通过。

## T21：覆盖端到端前后台与回流场景

**文件：** `tests/test_subagent_cli_e2e.py`

**依赖：** T20

**步骤：**

1. 用 fake Provider 驱动主 Agent 调用短时 defined 前台任务并收到直接结果。
2. 驱动显式后台、超时后台、模拟 Ctrl+B 和强制 Fork。
3. 验证完成通知不增加 Provider 调用数。
4. 下一次用户输入验证 `subagent_results` 注入且主消息历史无伪造 user。
5. 模拟第一次 Provider 失败、第二次成功，验证结果只在成功后消费。
6. 并发超过上限时验证 queued，再逐项完成。

**验证：** 运行 `python -m unittest tests.test_subagent_cli_e2e -v`；预期完整用户路径和失败重试场景通过。

## T22：更新使用文档和配置示例

**文件：** `README.md`、`docs/mew-spec-pitfalls.md`

**依赖：** T20

**步骤：**

1. 说明 `.huicode/agents`、用户级和内置角色优先级与 frontmatter 格式。
2. 增加 `subagents` 配置示例和模型别名解释。
3. 说明 Agent 工具、前后台语义、Ctrl+B、非 TTY 降级、`/agents`、`/tasks`。
4. 明确后台默认只读、无 Worktree 隔离及结果不自动调用模型。
5. 仅当实现过程发生真实返工时，把原因、症状、修复和预防追加到踩坑文档。

**验证：** 运行 `Select-String -Path README.md -Pattern 'subagents|/agents|/tasks|Ctrl\+B|\.huicode/agents'`；预期核心用法均可检索，且踩坑文档没有虚构记录。

## T23：运行专项与完整回归

**文件：** `tests/test_subagent_*.py`、所有受影响测试

**依赖：** T21、T22

**步骤：**

1. 运行全部子 Agent 专项测试。
2. 运行完整 unittest discovery。
3. 运行 compileall 和 `git diff --check`。
4. 修复失败后从专项和全量两层重新运行，不跳过失败项。
5. 确认没有引入新的非预期 skip。

**验证：** 运行：

```powershell
python -m unittest discover -s tests -p "test_subagent_*.py" -v
python -m unittest discover -s tests -v
python -m compileall -q huicode tests
git diff --check
```

预期所有测试通过、编译成功且 diff 无空白错误。

## T24：执行真实 CLI 验收并记录证据

**文件：** `specs/014-subagent-system/checklist.md`、`specs/014-subagent-system/acceptance_report.md`

**依赖：** T23

**步骤：**

1. 当前 Windows 环境检查 tmux；不可用时记录原因并使用实际用户 Python + fake Provider CLI 输入流等价验收。
2. 逐项执行 checklist，记录命令、观察结果和测试名称。
3. 覆盖定义式、Fork、后台三路径、结果回流、Hook 递归、清理和有界退出。
4. 验证 UTF-8 角色文件、Windows 非 TTY 降级和已有 Slash/Skill/Hook 路径。
5. 失败项修复后重新执行关联专项和全量测试。

**验证：** `acceptance_report.md` 中每个 checklist 项都有 Passed/Failed 与实际证据，端到端场景有真实输出摘要。

## T25：检查提交边界并提交本章

**文件：** 本章代码、测试、README、`specs/014-subagent-system/*`，以及确有新增记录时的 `docs/mew-spec-pitfalls.md`

**依赖：** T24

**步骤：**

1. 运行 `git status --short`，区分本章文件与用户原有未跟踪文件。
2. 只暂存子 Agent 相关代码、测试和本章文档，不暂存根目录临时 spec/plan/task/checklist 或其他用户文件。
3. 检查 staged diff、文件编码和敏感信息。
4. 创建中文 Git 提交，并再次确认工作区只剩用户原有文件。

**验证：** 运行 `git diff --cached --check`、`git diff --cached --stat` 和 `git show --stat --oneline -1`；预期提交只包含本章相关文件，提交成功且无 API key 或用户临时文件。

## 执行顺序

```text
T1 -> T2
T2 -> T3 -> T4 -> T5
T2 -> T6
T2 -> T7 -> T8
T2 -> T9
T2 -> T10
T2 -> T11 -> T12 -> T13
T6 + T8 + T9 + T10 + T12 -> T14 -> T15
T10 + T12 + T15 -> T16 -> T17
T12 + T14 -> T18
T4 + T12 -> T19
T15 + T16 + T18 + T19 -> T20 -> T21
T20 -> T22
T21 + T22 -> T23 -> T24 -> T25
```

## 任务覆盖自检

| Plan 组件 | 对应任务 |
| --- | --- |
| 配置与模型别名 | T1、T14 |
| 领域类型 | T2 |
| 角色解析、发现、覆盖和内置角色 | T3-T5 |
| Fork 历史与缓存资格 | T6、T17 |
| 权限与工具逐层过滤 | T7-T8 |
| 独立文件读缓存 | T9 |
| Prompt 扩展与后台结果模块 | T10、T16 |
| 有界 worker、状态、通知、结果租约 | T11-T12 |
| Ctrl+B 与超时切换 | T13、T15 |
| 定义式/Fork 执行 | T14-T16 |
| Hook 对接与递归保护 | T18 |
| 命令、状态栏和 TUI | T19-T20 |
| 端到端、文档、验收与提交 | T21-T25 |

共 25 项任务；每项均有明确依赖、文件、步骤和可运行验证方法，依赖图无环。
