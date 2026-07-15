# HuiCode Hook 系统验收报告

## 验收结论

2026-07-15 完成本章验收。`spec.md` 的 AC1-AC11、`checklist.md` 的 C01-C55 与 E01-E04 均通过，无未解释失败项。

## 实现范围

- 三层 Hook 配置按“用户级 `<` `huicode.yaml` `<` 项目级”合并，同 id 整体覆盖并集中校验。
- 发布会话、轮次、消息、工具、上下文压缩和 Agent 错误事件。
- 支持 exact、glob、regex、not 与互斥 all/any；`Glob`/`Find` 使用统一规范名。
- 支持 command、prompt、HTTP 和 subagent 占位动作。
- `tool_before` 明确拒绝回灌 `hook_denied`，跳过权限确认并保持 Agent Loop 继续。
- 支持 once、async、timeout、Prompt 三种作用域、JSONL 日志和 2 秒有界退出。
- 主 Agent、isolated Skill、`/compact`、`/clear`、`/status` 与统一资源关闭均已接线。

## 自动化证据

### Hook 专项与相关回归

使用 Codex 工作区 Python 3.12 运行 Hook、配置、权限、Prompt、上下文和 Skill 相关测试：87 项全部通过。

Hook 专项测试文件共 36 个测试方法，覆盖配置合并与负例、条件矩阵、载荷脱敏、四类动作、后台调度、Prompt 生命周期、工具拒绝、CLI 启停和 README 示例解析。

### 完整测试

```text
python -m unittest discover -s tests -v
Ran 327 tests in 11.837s
OK (skipped=2)
```

两个跳过项均为当前 Windows 权限不允许创建符号链接：

- `tests/test_permissions_sandbox.py` 的符号链接逃逸用例。
- `tests/test_skills_discovery.py` 的 Skill 符号链接逃逸用例。

其余 Agent Loop、Anthropic/OpenAI 协议、权限、MCP、上下文、记忆、Slash Command、Skill 和 TUI 测试全部通过。

### 用户实际解释器

实际解释器：

```text
C:\Users\Administrator\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe
PyYAML 6.0.3
```

该解释器重复运行 36 项 Hook/CLI 专项测试，结果全部通过。随后执行真实启动命令并输入 `/status`、`/exit`，观察到：

```text
MCP servers=1/1 tools=2 errors=0
Skills effective=4 overridden=0 skipped=0 warnings=0
Hooks effective=0 disabled=0 sources=none
hooks: effective=0 disabled=0 pending=0 failed=0 denied=0 log=.../.huicode/logs/hooks.jsonl
```

本次真实 CLI 验收没有发送普通用户问题，因此没有调用模型 API；MCP、Skill、Hook 状态和退出路径均正常。

### 静态检查

- `python -m compileall -q huicode tests`：退出码 0。
- `git diff --check`：通过，仅有 Git 的 LF/CRLF 工作区提示。
- README Hook YAML 由 `tests/test_hooks_readme.py` 提取并交给真实加载器，4 条规则全部通过校验。
- 独立进程提交一个睡眠 10 秒的后台 Hook 后关闭，输出 `close_elapsed=2.015s`，整个进程约 2.7 秒退出，没有等待到 10 秒。

## 端到端场景

### E01 工具安全拦截

fake Provider 请求 `Write`，`tool_before` command 以退出码 2 拒绝。目标文件未创建，权限 confirmer 未调用；模型下一轮收到带 rule id 和原因的 `hook_denied`，随后正常给出最终回答。通过。

### E02 后台格式化与通知

fake Provider 请求 `Edit`。工具成功后，异步 command 从 stdin 事件 JSON 读取目标路径并格式化文件，异步 HTTP 收到同一 `tool_after` JSON。慢 HTTP 完成前 Agent 已返回 final，关闭时日志和文件状态完整。通过。

### E03 上下文注入

验证 next_request 只消费一次、turn 跨同轮多次 Provider 请求、session 跨 transient clear 保留；Hook 块位于动态系统模块，不进入 ConversationMessage。重量压缩结束后注入的指令在紧接着的主请求立即可见。通过。

### E04 跨子系统流程

三层配置覆盖测试确认项目级同 id 胜出；isolated Skill 使用 `skill:<name>` scope 并继承共享工具 Hook，父子 AgentState 保持隔离；`/compact` 仅触发 context 事件，本地 `/status` 不触发 turn/message，`/exit` 与 EOF 均只触发一次 session_end。通过。

## 环境限制

系统未安装 tmux，因此无法按 `AGENT.md` 使用 tmux。已采用真实 CLI 输入流、fake Provider、本地 HTTP Server、真实文件副作用和用户实际 Python 解释器完成等价验收。

## 返工记录

实现验收中发现并修复两项设计落地问题：上下文 Hook 注入时 PromptBundle 快照过早，以及 `ThreadPoolExecutor.shutdown(wait=False)` 不能保证解释器有界退出。经验已记录到 `docs/mew-spec-pitfalls.md` 的踩坑 28、29。
