# HuiCode MCP Client Task

## File List

| File | Action | Purpose |
| --- | --- | --- |
| `huicode/mcp/__init__.py` | Create | 导出 MCP 客户端相关类型和入口 |
| `huicode/mcp/config.py` | Create | 读取、校验、合并 MCP Server 配置，展开环境变量 |
| `huicode/mcp/jsonrpc.py` | Create | JSON-RPC 2.0 request/notification/response 校验与 id 配对 |
| `huicode/mcp/transport.py` | Create | stdio 和 Streamable HTTP transport |
| `huicode/mcp/session.py` | Create | MCP initialize、tools/list、tools/call 会话封装 |
| `huicode/mcp/tools.py` | Create | MCP tool 到 HuiCode Tool 的适配 |
| `huicode/mcp/manager.py` | Create | 多 Server 生命周期、工具发现和注册 |
| `huicode/cli.py` | Modify | 启动时加载 MCP、注册工具、退出时关闭、配置摘要不泄密 |
| `huicode/tools/registry.py` | Modify if needed | 支持批量注册或冲突检查辅助 |
| `README.md` | Modify | 增加 MCP 配置示例、合并规则和限制 |
| `tests/test_mcp_config.py` | Create | MCP 配置解析、合并、环境变量展开测试 |
| `tests/test_mcp_jsonrpc.py` | Create | JSON-RPC id、错误、非法响应测试 |
| `tests/test_mcp_stdio.py` | Create | stdio fake server 传输测试 |
| `tests/test_mcp_http.py` | Create | HTTP fake server 传输和 session header 测试 |
| `tests/test_mcp_tools.py` | Create | MCP ToolAdapter 结果转换测试 |
| `tests/test_mcp_manager.py` | Create | 多 server 注册、失败隔离、同名工具测试 |
| `tests/test_cli.py` | Modify | CLI 启动 MCP、`/config` 摘要不泄密测试 |
| `tests/test_agent_loop.py` | Modify if needed | MCP 工具回灌和 Plan Mode 默认拒绝集成测试 |
| `specs/008-mcp-client/acceptance_report.md` | Create | 记录验收证据 |

## Ordered Tasks

### T1. Inspect Existing Extension Points

Dependencies: none

Steps:

1. 阅读 `huicode/cli.py` 启动流程，确认 registry 创建、权限上下文和退出路径。
2. 阅读 `huicode/tools/base.py`、`registry.py`、`executor.py`，确认 MCP 工具如何复用 Tool 接口。
3. 阅读 `huicode/agent.py`，确认 Plan Mode guard 和工具结果回灌路径。
4. 阅读现有测试风格，确认 fake provider、临时目录和本地 HTTP server 的写法。

Verification:

- 明确 MCP manager 应插入在 registry 创建后、进入聊天循环前。
- 明确 MCP tool 只要实现 `Tool.run()` 就能走现有 Agent Loop。

### T2. Implement MCP Config Loader

Dependencies: T1

Steps:

1. 创建 `huicode/mcp/config.py`。
2. 定义 MCP config/server dataclass。
3. 实现用户级和项目级路径定位。
4. 实现 MCP YAML 子集解析，支持 map、list、字符串标量。
5. 实现 stdio/http 必填字段校验。
6. 实现 `${VAR}` 展开，缺失变量报配置错误。
7. 实现用户级 + 项目级合并，同名项目级覆盖用户级。

Verification:

- 新增 `tests/test_mcp_config.py` 覆盖 stdio/http、合并、环境变量展开、错误配置。

### T3. Implement JSON-RPC Helpers

Dependencies: T1

Steps:

1. 创建 `huicode/mcp/jsonrpc.py`。
2. 定义 JSON-RPC error/transport/protocol 异常类型。
3. 实现 request id 生成。
4. 实现 request 和 notification 消息构造。
5. 实现 response 校验，成功返回 `result`，错误响应抛出协议错误。
6. 校验 response id 必须匹配当前 request id。

Verification:

- 新增 `tests/test_mcp_jsonrpc.py` 覆盖 id 自增、id mismatch、error response、invalid envelope。

### T4. Implement Stdio Transport

Dependencies: T3

Steps:

1. 在 `huicode/mcp/transport.py` 中定义 transport protocol。
2. 实现 `StdioMCPTransport.start()` 启动子进程。
3. 实现 `request()` 写一行 JSON 到 stdin，并从 stdout 读一行 JSON。
4. 实现 `notify()` 写 notification，不等待响应。
5. 实现超时、进程退出、无效 JSON 的错误处理。
6. 实现 `close()` 终止子进程。

Verification:

- 新增 `tests/test_mcp_stdio.py`，使用测试 fake server 完成 initialize/tools/list/tools/call。
- 测试 stderr 日志不会污染 stdout 协议。

### T5. Implement HTTP Transport

Dependencies: T3

Steps:

1. 在 `huicode/mcp/transport.py` 中实现 `HTTPMCPTransport`。
2. 使用标准库发送 POST JSON-RPC。
3. 设置 `Content-Type` 和 `Accept` header。
4. 合并配置 headers，但测试确保摘要不泄密。
5. 初始化响应中读取 `MCP-Session-Id`。
6. 后续 request/notify 携带 session header。
7. 将 HTTP 错误、无效 JSON、JSON-RPC error 转成统一异常。

Verification:

- 新增 `tests/test_mcp_http.py`，本地 fake HTTP server 验证 POST body、Accept header 和 session header。

### T6. Implement MCP Session

Dependencies: T4, T5

Steps:

1. 创建 `huicode/mcp/session.py`。
2. 实现 `initialize()`：发送 `initialize`，保存 server info，再发 `notifications/initialized`。
3. 实现 `list_tools()` 调用 `tools/list`。
4. 实现 `call_tool()` 调用 `tools/call`。
5. 给所有操作加超时参数。
6. 确保 `close()` 调用 transport close。

Verification:

- stdio/http 测试通过 session 完成握手、工具发现和调用。

### T7. Implement MCP Tool Adapter

Dependencies: T6

Steps:

1. 创建 `huicode/mcp/tools.py`。
2. 实现 public tool name 规则 `mcp__{server}__{tool}`，对非法字符做稳定归一化。
3. 将 MCP `description` 和 `inputSchema` 映射为 HuiCode Tool 字段。
4. 设置 `side_effect=True`。
5. `run()` 调用 session 的 `tools/call`。
6. 将 MCP text content 转成 `ToolResult.success`。
7. 将 `isError=true` 转成 `ToolResult.failure("mcp_tool_error", ...)`。
8. 将协议/传输异常转成结构化失败结果。

Verification:

- 新增 `tests/test_mcp_tools.py` 覆盖名称映射、content 转换、isError、异常转换。

### T8. Implement MCP Manager And Registry Integration

Dependencies: T2, T6, T7

Steps:

1. 创建 `huicode/mcp/manager.py`。
2. 按 server config 创建 transport 和 session。
3. 对每个 server 单独初始化和 `tools/list`。
4. 将发现的工具包装成 adapter。
5. 注册到 `ToolRegistry`。
6. 单 server 失败记录错误并继续其他 server。
7. 实现 `close()` 关闭所有 session。

Verification:

- 新增 `tests/test_mcp_manager.py` 覆盖多 server、失败隔离、同名远端工具注册名不冲突、close 生命周期。

### T9. Integrate MCP Into CLI Startup

Dependencies: T8

Steps:

1. 在 `cli.py` 创建 registry 后加载 MCP config。
2. 启动 `MCPManager` 并注册 MCP 工具。
3. 启动提示显示 MCP server/tool 统计和失败数量。
4. `/config` 摘要显示 MCP 统计，但不显示 headers/env。
5. 在退出路径确保 `manager.close()` 被调用。
6. MCP 配置错误应给出清晰提示；如果是单 server 失败，应继续启动。

Verification:

- 修改 `tests/test_cli.py` 覆盖无 MCP 配置不变、有 MCP 配置注册工具、`/config` 不泄露 secret。

### T10. Add Agent Integration Tests

Dependencies: T9

Steps:

1. 用 fake MCP tool 或 manager 创建一个 MCP adapter。
2. 让 fake provider 调用 MCP 工具。
3. 验证工具结果进入历史，下一轮 provider 可见。
4. 在 Plan Mode 下调用 MCP 工具，验证默认被拒绝且不触发远端调用。

Verification:

- 新增或修改 `tests/test_agent_loop.py` 覆盖 MCP tool 回灌和 Plan Mode 拒绝。

### T11. Update Documentation

Dependencies: T9, T10

Steps:

1. 更新 README MCP 章节。
2. 写 stdio 配置示例。
3. 写 HTTP 配置示例。
4. 说明用户级/项目级合并规则。
5. 说明 `${VAR}` 展开策略。
6. 说明本章不支持 resources/prompts/sampling/健康检查/自动重连。

Verification:

- README 可搜索 `mcp`、`stdio`、`http`、`tools/list` 或等价说明。

### T12. Run Verification

Dependencies: T11

Steps:

1. 运行 MCP 目标测试。
2. 运行相关 CLI/Agent 测试。
3. 运行全量测试。
4. 运行编译检查。
5. 检查 tmux 是否可用；可用则做终端 E2E，不可用则记录原因。

Commands:

```powershell
python -m unittest tests.test_mcp_config tests.test_mcp_jsonrpc tests.test_mcp_stdio tests.test_mcp_http tests.test_mcp_tools tests.test_mcp_manager -v
python -m unittest tests.test_agent_loop tests.test_cli tests.test_tui -v
python -m unittest discover -v
python -m compileall -q huicode tests
Get-Command tmux -ErrorAction SilentlyContinue
```

Verification:

- 所有可运行命令通过。
- 不可运行 E2E 有明确原因。

### T13. Acceptance Report And Commit

Dependencies: T12

Steps:

1. 创建 `specs/008-mcp-client/acceptance_report.md`。
2. 对照 checklist 记录实际证据。
3. 检查 `git status`，只暂存本章相关文件。
4. 提交 Git。

Verification:

- acceptance report 包含测试命令、结果和 tmux 状态。
- Git commit 成功，不包含 `huicode.yaml` 或根目录旧临时文件。

## Execution Order

1. T1 Inspect Existing Extension Points
2. T2 Implement MCP Config Loader
3. T3 Implement JSON-RPC Helpers
4. T4 Implement Stdio Transport
5. T5 Implement HTTP Transport
6. T6 Implement MCP Session
7. T7 Implement MCP Tool Adapter
8. T8 Implement MCP Manager And Registry Integration
9. T9 Integrate MCP Into CLI Startup
10. T10 Add Agent Integration Tests
11. T11 Update Documentation
12. T12 Run Verification
13. T13 Acceptance Report And Commit

## Self Check

- 每个 plan 模块都有至少一个任务。
- 任务顺序先配置和协议，再传输、会话、工具适配、启动集成，最后验证提交。
- 每个任务都有明确验证方式。
- 没有越过 Mew Spec 闸门进入实现代码。
