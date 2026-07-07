# 006 五层权限系统验收报告

## 结论

已完成本章目标：HuiCode 现在在工具执行前具备五层权限防御，包括危险命令黑名单、路径沙箱、会话/本地/项目/用户规则、三档权限模式和人在回路确认。权限拒绝会作为结构化工具结果回灌到 Agent Loop，模型可以继续下一轮调整策略。

## 已完成项

- 新增 `huicode.permissions` 包，包含基础类型、黑名单、路径沙箱、规则解析、配置加载和权限引擎。
- `ToolContext` 增加可选权限上下文，旧调用在未启用权限上下文时保持兼容。
- `execute_tool_call()` 在工具运行前执行权限检查。
- Bash 黑名单会硬拦截 `git reset --hard`、`git clean -fdx`、递归强删、磁盘格式化和大范围权限破坏等危险命令。
- 路径沙箱会解析绝对路径、`..` 和符号链接后判断是否仍在 workspace 内。
- 规则支持 `工具名(模式): allow|deny`，支持精确匹配和 glob 匹配。
- 规则优先级为会话级 > 本地级 > 项目级 > 用户级。
- 权限模式支持 `strict`、`default`、`permissive`。
- CLI 支持 `/permissions` 查看模式和规则摘要，并支持 `/permissions strict|default|permissive` 切换当前会话模式。
- 默认模式下副作用工具会触发确认，支持 `deny`、`once`、`session`、`always`。
- README 已记录五层防御、规则文件路径、规则格式和阶段边界。
- `.gitignore` 已忽略 `.huicode-permissions.local.yaml`。

## 验证记录

```text
python -m unittest tests.test_permissions_blacklist tests.test_permissions_sandbox tests.test_permissions_rules tests.test_permissions_config tests.test_permissions_engine tests.test_tools_files tests.test_tools_shell tests.test_agent_loop tests.test_cli tests.test_tui -v
结果：54 tests OK
```

```text
python -m unittest discover -v
结果：122 tests OK
```

```text
python -m compileall -q huicode tests
结果：通过
```

```text
Get-Command tmux -ErrorAction SilentlyContinue
结果：tmux 不可用
```

## 端到端场景证据

- 危险命令硬拦截：`Bash(git reset --hard)` 在 `permissive` 模式且存在 allow 规则时仍被 `blacklist` 拒绝。
- 路径沙箱：`../outside.txt`、workspace 外绝对路径、symlink 指向外部目录均被拒绝。
- 人在回路：默认模式下 `Write(a.txt)` 触发确认；选择 `session` 后，同类调用不再询问。
- Agent Loop 回灌：权限拒绝被保存为 `tool` 消息，下一轮模型可继续输出最终回答。
- CLI 模式切换：`/permissions` 可查看当前模式，`/permissions strict` 可切换当前会话模式。

## 环境限制

当前 Windows PowerShell 环境未安装 tmux，因此未执行 AGENT.md 中要求的 tmux 端到端场景。已用单元测试覆盖权限系统关键路径、工具执行链路、Agent Loop 回灌、CLI 命令和 TUI 权限确认文本。

## 本章未做

- 网络请求限制。
- CPU、内存、磁盘、进程数等资源配额。
- 完整审计日志。
- 操作系统级容器沙箱。
- 多用户权限隔离。
