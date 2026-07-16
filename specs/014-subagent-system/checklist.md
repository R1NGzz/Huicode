# HuiCode 子 Agent 系统 Checklist

> 每一项必须通过运行测试、执行 CLI 或观察输出验证；不得仅凭代码阅读勾选。

## 实现完整性

- [ ] C1：主 Agent 在 DEFAULT、PLAN、零角色、多角色、无任务和有后台任务时都暴露同一个 `Agent` 工具名称与参数 Schema。（验证：运行 `python -m unittest -v tests.test_subagent_tool.AgentToolSchemaTests`，比较六种状态下的 ToolSpec 完全相等）【AC1】
- [ ] C2：`Agent` 工具能分流 defined/fork，非法 type、空 task、defined 缺 role、fork 携带 role 均返回结构化错误且主 Loop 不崩溃。（验证：运行 `python -m unittest -v tests.test_subagent_tool.AgentToolValidationTests`）【AC1】
- [ ] C3：角色按项目 > 用户 > 内置 > 插件覆盖，同层重复名会阻止启动。（验证：运行 `python -m unittest -v tests.test_subagent_catalog.RolePrecedenceTests`，观察最终来源和重复名错误路径）【AC2】
- [ ] C4：损坏的 frontmatter 文件被警告跳过；非法工具、空正文、非法轮次/权限和未映射模型别名会阻止启动并指出文件与字段。（验证：运行 `python -m unittest -v tests.test_subagent_catalog.RoleValidationTests tests.test_subagent_config`）【AC2】
- [ ] C5：定义式子 Agent 首次请求不含父消息、active Skill、父记忆索引和后台结果，但含项目指令、角色正文和 task；第二轮仍含角色正文。（验证：运行 `python -m unittest -v tests.test_subagent_runner.DefinedContextTests`，检查 fake Provider 捕获的两次请求）【AC3】
- [ ] C6：Fork 截止到当前未配对 Agent tool call 前的完整协议边界，每个保留 tool call 都有对应 tool result。（验证：运行 `python -m unittest -v tests.test_subagent_history`）【AC4】
- [ ] C7：Fork 首次请求与父请求的稳定 system/history 前缀一致，cache read/create usage 能进入任务详情。（验证：运行 `python -m unittest -v tests.test_subagent_runner.ForkCacheTests tests.test_anthropic_provider_prompts tests.test_openai_provider_prompts`）【AC4】
- [ ] C8：两个并行子 Agent 的消息、上下文状态、权限临时规则、读缓存、迭代和 usage 不互相串写。（验证：运行 `python -m unittest -v tests.test_subagent_runner.StateIsolationTests`）【AC5】
- [ ] C9：父子共享工作区变更、MCP 工具对象和 Hook 基础设施，但各自拥有独立 Hook turn 状态。（验证：运行 `python -m unittest -v tests.test_subagent_runner.SharedInfrastructureTests tests.test_subagent_hooks.ScopeIsolationTests`）【AC5】
- [ ] C10：父工具快照、全局禁止、角色 allow/deny、后台白名单和 PLAN 限制按顺序只减不增。（验证：运行 `python -m unittest -v tests.test_subagent_filtering.ToolFilteringTests`）【AC6】
- [ ] C11：`Agent`、`Skill` 在任何子 Agent 的 Provider tool list 和执行 registry 中都不可见；角色 permissive 不能放宽父 default/strict。（验证：运行 `python -m unittest -v tests.test_subagent_filtering.GlobalGuardTests tests.test_subagent_filtering.PermissionSnapshotTests`）【AC6】
- [ ] C12：子 Agent 遇到待确认权限时不弹 TUI，收到结构化拒绝后可以继续下一轮调整。（验证：运行 `python -m unittest -v tests.test_subagent_runner.NonInteractivePermissionTests`，断言 confirmer 未调用且 Provider 收到拒绝结果）【AC7】
- [ ] C13：无工具 final、工具失败、最大轮次、取消及 Provider/流错误都形成独立任务结果，不改变主 Agent 的 final/stop reason。（验证：运行 `python -m unittest -v tests.test_subagent_runner.StopConditionTests`）【AC7】
- [ ] C14：后台 manager 记录 queued/running/completed/failed/cancelled、耗时、迭代、停止原因和 usage；超过并发上限时保持 queued。（验证：运行 `python -m unittest -v tests.test_subagent_manager.TaskStateTests tests.test_subagent_manager.DaemonWorkerTests`）【AC8】
- [ ] C15：短定义式任务前台直接返回结果；`background:true`、前台超时和 Ctrl+B 返回 task id 并继续后台；Fork 从创建起强制后台。（验证：运行 `python -m unittest -v tests.test_subagent_tool.ForegroundBackgroundTests tests.test_subagent_terminal`）【AC9】
- [ ] C16：任务转后台后只对后续工具调用应用后台白名单，已开始的单个工具不会被强杀。（验证：运行 `python -m unittest -v tests.test_subagent_runner.BackgroundTransitionTests`）【AC9】
- [ ] C17：后台完成通知不会增加 Provider 调用数，且通知包含 task id、类型/角色、状态、耗时和摘要。（验证：运行 `python -m unittest -v tests.test_subagent_cli_e2e.BackgroundNotificationTests`）【AC10】
- [ ] C18：下一次主请求注入一次 `subagent_results` 系统上下文，主消息历史没有伪造 user；请求失败时结果保留，完整成功响应后才消费。（验证：运行 `python -m unittest -v tests.test_subagent_result_delivery`）【AC10】
- [ ] C19：`/agents`、`/agents <name>` 与启动摘要显示角色数量、来源、覆盖/跳过和安全元数据，不输出完整角色正文。（验证：运行 `python -m unittest -v tests.test_subagent_commands.AgentCommandTests tests.test_subagent_cli_e2e.StartupSummaryTests`）【AC11】
- [ ] C20：`/tasks`、`/tasks <id>`、`/status` 和底部状态栏能观察任务数量、状态、摘要、停止原因、迭代和 usage，且不泄露敏感字段。（验证：运行 `python -m unittest -v tests.test_subagent_commands.TaskCommandTests`）【AC8】【AC11】
- [ ] C21：main scope 的 Hook subagent 动作使用指定角色或默认 general 创建真实 defined/background 任务。（验证：运行 `python -m unittest -v tests.test_subagent_hooks.HookSubmissionTests`）【AC12】
- [ ] C22：来自任意 `subagent:*` scope 的 Hook subagent 动作只记录 `recursion_guard`，任务数不增加，提交失败也不改变主 Loop。（验证：运行 `python -m unittest -v tests.test_subagent_hooks.RecursionGuardTests`）【AC12】
- [ ] C23：`/clear` 取消未完成任务并清空任务表、通知和待交付结果；旧结果不会进入新对话。（验证：运行 `python -m unittest -v tests.test_subagent_commands.ClearTaskTests tests.test_subagent_result_delivery.ClearLeaseTests`）【AC13】
- [ ] C24：`/exit` 和 EOF 在 `shutdown_wait_seconds` 内结束，阻塞任务被标记 cancelled/abandoned，重启后没有旧后台任务。（验证：运行 `python -m unittest -v tests.test_subagent_cli_e2e.BoundedShutdownTests` 并断言实测耗时上限）【AC13】

## 集成检查

- [ ] C25：角色目录在 MCP 工具注册后校验，角色可引用已加载 MCP 工具；引用不存在工具时启动失败。（验证：运行 `python -m unittest -v tests.test_subagent_catalog.MCPToolValidationTests tests.test_mcp_manager`）【AC2】【AC5】
- [ ] C26：模型别名只替换 model，protocol、base_url、api_key、headers、thinking、context 保持主配置一致。（验证：运行 `python -m unittest -v tests.test_subagent_runner.ModelAliasTests tests.test_provider_factory`）【AC2】【AC3】
- [ ] C27：Read 缓存在同一 Agent 内可命中，文件变化后失效，父子与不同子 Agent 之间不共享。（验证：运行 `python -m unittest -v tests.test_subagent_runner.FileReadCacheTests tests.test_tools_files`）【AC5】
- [ ] C28：Hook 事件 scope 分别为 main、`subagent:defined:<role>:<id>`、`subagent:fork:<id>`，turn/next-request 注入不串线。（验证：运行 `python -m unittest -v tests.test_subagent_hooks.ScopeIsolationTests tests.test_agent_hooks`）【AC5】【AC12】
- [ ] C29：后台线程只写通知/结果队列，不直接改主消息历史；通知渲染不会破坏 prompt_toolkit 当前输入。（验证：运行 `python -m unittest -v tests.test_subagent_manager.ThreadOwnershipTests tests.test_subagent_cli_e2e.PromptSafetyTests`）【AC10】【AC14】
- [ ] C30：未调用 Agent 工具时，普通聊天、工具批处理、权限、上下文、记忆、MCP、Slash、Skill 和 Hook 的既有专项测试全部保持通过。（验证：运行完整 unittest discovery，并核对无新增失败/非预期 skip）【AC14】

## 构建与测试

- [ ] C31：全部子 Agent 专项测试通过。（验证：运行 `python -m unittest discover -s tests -p "test_subagent_*.py" -v`，预期 0 failure、0 error）【AC1-AC14】
- [ ] C32：完整测试套件通过。（验证：运行 `python -m unittest discover -s tests -v`，记录总数、通过数和合理 skip）【AC14】
- [ ] C33：源码和测试均可编译。（验证：运行 `python -m compileall -q huicode tests`，预期退出码 0）【AC14】
- [ ] C34：改动无空白错误或冲突标记。（验证：运行 `git diff --check` 和 `Get-ChildItem huicode,tests -Recurse -File | Select-String -Pattern '<<<<<<<|=======|>>>>>>>'`，预期无匹配）【AC14】
- [ ] C35：配置示例、角色格式、前后台规则、Ctrl+B、`/agents`、`/tasks` 和无 Worktree 风险已写入 README。（验证：运行 README 关键词检查并人工执行示例配置加载）【AC11】【AC13】【AC14】

## 端到端场景

- [ ] E1：启动 HuiCode 后可见角色与 Hook/Skill/MCP 摘要；输入 `/agents` 和 `/agents explorer` 能看到正确角色来源与限制。（验证：实际用户 Python 启动 fake Provider CLI，保存可观察输出）【AC2】【AC11】
- [ ] E2：主 Agent 调用短时 defined/explorer，子 Agent 使用只读工具跑到 final，主 Agent 在同一次工具结果中拿到摘要和独立 usage。（验证：fake Provider 完整输入流，检查调用次数、工具行和最终结果）【AC3】【AC6】【AC7】【AC9】
- [ ] E3：主 Agent 调用 Fork 后立即获得 task id；Fork 历史不含未配对 Agent call，后台完成只通知，不自动请求模型。（验证：fake Provider 捕获请求和调用计数）【AC4】【AC9】【AC10】
- [ ] E4：后台结果完成后保持在 ready；下一次用户普通输入触发一次结果注入，Provider 首次失败后结果仍在，重试成功后 ready 归零。（验证：两次 fake Provider 响应序列和 `/status` 输出）【AC8】【AC10】
- [ ] E5：前台慢任务分别因超时和模拟 Ctrl+B 转后台；非 TTY 下 Ctrl+B 功能明确降级但超时仍生效。（验证：Windows TTY/可注入键盘适配测试加真实非交互输入流）【AC9】【AC14】
- [ ] E6：Hook 在 main scope 创建 general 后台任务；该子 Agent 再触发同一 Hook 时出现 recursion_guard 且任务总数不变。（验证：加载测试 hooks YAML，观察 `/tasks` 与 Hook 日志）【AC12】
- [ ] E7：并发提交超过 `max_background_tasks` 的任务，额外任务显示 queued；执行 `/clear` 后任务和 ready 结果清空，再输入新问题不收到旧结果。（验证：fake 阻塞 Provider + `/tasks`、`/clear`、下一请求）【AC8】【AC13】
- [ ] E8：后台任务阻塞时输入 `/exit` 或发送 EOF，进程在配置等待上限附近退出；再次启动无旧任务恢复。（验证：计时 CLI 子进程并重新启动 `/tasks`）【AC13】

## 平台与安全

- [ ] C36：UTF-8/BOM 中文角色文件可加载，Windows 路径和非 TTY 输入不会触发 GBK 解码异常。（验证：运行 `python -m unittest -v tests.test_subagent_catalog tests.test_subagent_cli_e2e.WindowsEncodingTests`）【AC14】
- [ ] C37：任务详情、通知、Hook 日志和结果上下文不包含 api_key、Authorization、Cookie 或 thinking 原文。（验证：使用带哨兵敏感值的测试并对所有输出断言不存在）【AC14】
- [ ] C38：后台默认工具仅为 Read/Find/Search，无法调用 Bash/Write/Edit；用户放宽配置后仍受黑名单、沙箱和权限规则约束。（验证：运行 `python -m unittest -v tests.test_subagent_filtering.BackgroundSafetyTests tests.test_permissions_blacklist tests.test_permissions_sandbox`）【AC6】【AC14】
- [ ] C39：当前环境若无 tmux，验收报告明确记录降级原因、替代 CLI 方法和覆盖差异；不得宣称执行了 tmux。（验证：检查 `tmux -V` 结果和 acceptance report 证据）【AC14】
- [ ] C40：Git 暂存区只包含本章代码、测试、README、本章四份 Mew Spec 文档、验收报告，以及确有真实返工时的踩坑记录。（验证：运行 `git diff --cached --name-only`，逐项核对；根目录临时文档和用户文件不得出现）【AC14】

## 验收映射自检

| 验收标准 | Checklist |
| --- | --- |
| AC1 | C1-C2、C31 |
| AC2 | C3-C4、C25、C26、E1 |
| AC3 | C5、C26、E2 |
| AC4 | C6-C7、E3 |
| AC5 | C8-C9、C25、C27-C28 |
| AC6 | C10-C11、C38、E2 |
| AC7 | C12-C13、E2 |
| AC8 | C14、C20、E4、E7 |
| AC9 | C15-C16、E2、E3、E5 |
| AC10 | C17-C18、C29、E3-E4 |
| AC11 | C19-C20、C35、E1 |
| AC12 | C21-C22、C28、E6 |
| AC13 | C23-C24、C35、E7-E8 |
| AC14 | C29-C40、E5、E8 |

共 40 项检查和 8 个端到端场景；AC1-AC14 均至少映射到一个可运行、可观察的验收项。
