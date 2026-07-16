# HuiCode 子 Agent 系统验收报告

## 验收结论

通过。Checklist 共 40 项行为检查和 8 个端到端场景，均获得自动化测试、真实 CLI 输入流或静态检查证据。

## 通过项（48/48）

### 配置与角色目录

- Agent 工具 Schema 在目录和任务状态变化时保持固定；非法参数返回结构化错误。
- 插件、内置、用户、项目四层角色按优先级覆盖，同层重名和安全字段错误致命。
- 损坏 YAML 文件警告跳过；未知工具、未映射模型别名、重复 YAML key 明确报错。
- 三个内置角色 `general`、`explorer`、`reviewer` 可通过真实 CLI 启动摘要发现。

证据：`tests.test_subagent_config`、`tests.test_subagent_catalog`、`tests.test_subagent_tool`、`tests.test_subagent_cli_e2e`。

### 隔离、Fork 与缓存

- 定义式任务从干净消息历史启动，角色正文每轮作为动态高优先级系统指令存在。
- Fork 丢弃未配对 tool call，保留完整协议组并原样复用父稳定 Prompt 模块。
- 父子权限规则、消息、上下文、Read 缓存和 usage 独立；角色权限只能收紧。
- Fork cache usage 字段被任务结果保存，thinking 原文不进入结果。

证据：`tests.test_subagent_history`、`tests.test_subagent_runner`、`tests.test_subagent_filtering`、原 Anthropic/OpenAI Prompt 与工具回归。

### 工具与权限防线

- 工具按父可见集合、Agent/Skill 全局禁止、角色 allow/deny、后台白名单和 PLAN 逐层收窄。
- 转后台后 Provider tool specs 与执行 registry 同时移除写工具。
- 子 Agent confirmer 与 persistent path 均为空，需要确认的调用形成结构化拒绝。
- 后台默认只有 Read、Find、Search，现有黑名单和路径沙箱回归全部通过。

证据：`tests.test_subagent_filtering`、`tests.test_permissions_*`、`tests.test_agent_loop`。

### 前台、后台与生命周期

- 短 defined 前台直接返回摘要；显式后台、超时后台和模拟 Ctrl+B 三路通过。
- Fork 始终后台；并发上限为 1 时额外任务保持 queued。
- 后台完成只生成通知和 ready 结果，不自动增加 Provider 调用。
- `clear()` 清除任务与迟到结果；阻塞 runner 下 `close()` 仍在配置时限内返回。
- 前台等待结束会停止临时键盘监听；Ctrl+C 路径同步取消前台任务。

证据：`tests.test_subagent_terminal`、`tests.test_subagent_tool`、`tests.test_subagent_manager`、`tests.test_subagent_cli_e2e`。

### 结果回流与可观测性

- 后台结果使用 acquire/ack/release lease；Provider 失败后保留，完整响应后消费。
- 结果以一次性 `subagent_results` 动态系统上下文注入，不伪造用户消息。
- `/agents`、`/tasks`、`/status`、帮助与状态栏接入本地命令系统，不调用 Provider。
- 摘要、错误、usage 和通知经过深度脱敏，XML 边界字符被转义。

证据：`tests.test_subagent_result_delivery`、`tests.test_subagent_commands`、`tests.test_subagent_manager`、CLI 全量回归。

### Hook 对接

- main scope Hook 可使用指定角色或默认 general 提交真实 defined/background 任务。
- 任意 `subagent:*` scope 返回 `recursion_guard`，不递归创建任务。
- submitter 未绑定或提交失败保持 Hook 失败开放语义，不击穿主 Loop。

证据：`tests.test_subagent_hooks`、`tests.test_hooks_actions`、`tests.test_hooks_manager`、`tests.test_agent_hooks`。

## 端到端

- [x] 定义式前台：主模型调用 `Agent(explorer)`，子 Agent 独立 final，摘要作为工具结果回灌，`/tasks` 显示 completed。
- [x] Fork 后台：主调用立即获得 task id，后台完成后 Provider 总调用数保持 3，没有自动追加模型请求。
- [x] 结果重试：首次主 Provider 请求失败后 ready 保留，第二次成功请求注入结果并归零。
- [x] 前台转换：短任务完成、慢任务超时、模拟 Ctrl+B 都走到对应状态。
- [x] 并发限制：单 worker 下第二项 queued，第一项结束后继续执行。
- [x] Hook 递归：main 提交成功，subagent scope 只记录 recursion_guard。
- [x] 清理与退出：clear 阻止迟到结果污染新会话，close 在 0.05 秒配置下有界返回。
- [x] Windows 非 TTY：真实 Python 输入流下显式/超时路径工作；按键监听使用可注入控制器验证。

## 测试与静态检查

```text
子 Agent 专项：30 tests，OK
完整回归：357 tests，OK
compileall：huicode + tests，退出码 0
git diff --check：退出码 0
冲突标记：none
```

当前 Windows 环境 `tmux: unavailable`，因此没有声称执行 tmux。替代验收使用用户实际 `python.exe`、fake Provider 和真实 `_run_chat()` 输入流，覆盖定义式、Fork、Slash Command、TUI 输出及资源关闭。

## 残余边界

- 第三方 Provider 是否真正命中 Prompt Cache 取决于其实现；本章只保证稳定 system/history 前缀一致并保留 cache usage。
- 本章没有 Worktree 隔离；后台白名单若由用户放宽到写工具，仍可能发生共享工作区写冲突。
- Ctrl+B 的平台适配通过注入式按键测试，未在自动化环境中模拟物理键盘设备。
