# HuiCode MCP Client Acceptance Report

## Summary

本章实现了 MCP 客户端工具接入：启动时读取用户级和项目级 MCP 配置，初始化 stdio 或 HTTP MCP Server，执行 `initialize`、`notifications/initialized`、`tools/list`，并把远端工具适配成 HuiCode 现有 `Tool` 接口注册进工具中心。Agent 调用 MCP 工具后，`tools/call` 结果会转成结构化 `ToolResult` 并回灌进对话历史。

结果：通过。

## Checklist Results

| Item | Result | Evidence |
| --- | --- | --- |
| C1 | PASS | `tests/test_mcp_config.py` 覆盖用户级、项目级、同名覆盖和不同名合并。 |
| C2 | PASS | 配置测试覆盖 `type: stdio`、`command`、`args`、`env`。 |
| C3 | PASS | 配置测试覆盖 `type: http`、`url`、`headers`。 |
| C4 | PASS | 配置测试覆盖 args、env、url、headers 的 `${VAR}` 展开和缺失变量错误。 |
| C5 | PASS | CLI/Agent/TUI 相关测试通过，无 MCP 配置时仍按原本流程启动。 |
| C6 | PASS | `tests/test_mcp_jsonrpc.py` 覆盖 id 自增、notification 无 id、响应 id 匹配。 |
| C7 | PASS | `tests/test_mcp_jsonrpc.py` 覆盖 JSON-RPC error、id mismatch 和非法 envelope。 |
| C8 | PASS | `tests/test_mcp_stdio.py` 使用 fake stdio server 完成初始化、列工具和调用工具。 |
| C9 | PASS | fake stdio server 写 stderr 后，stdout JSON-RPC 仍正常解析，stderr 仅作诊断。 |
| C10 | PASS | `tests/test_mcp_http.py` fake HTTP server 验证 JSON-RPC POST、headers 和 body。 |
| C11 | PASS | HTTP 测试验证 initialize 返回的 `MCP-Session-Id` 在后续请求中复用。 |
| C12 | PASS | stdio/HTTP session 测试均覆盖 initialize 后发送 `notifications/initialized`。 |
| C13 | PASS | stdio/HTTP session 测试验证 `tools/list` 解析工具列表。 |
| C14 | PASS | stdio/HTTP/tool adapter 测试验证 `tools/call` 使用原始工具名和参数。 |
| C15 | PASS | `tests/test_mcp_tools.py` 验证公开名称格式 `mcp__server__tool` 和非法字符归一化。 |
| C16 | PASS | adapter 测试验证远端调用保留 MCP 原始工具名。 |
| C17 | PASS | manager 和 adapter 测试验证 `inputSchema` 进入 HuiCode tool spec parameters。 |
| C18 | PASS | adapter 测试验证 MCP text content 转成成功 `ToolResult` summary/data。 |
| C19 | PASS | adapter 测试验证 `isError=true` 转成 `mcp_tool_error`。 |
| C20 | PASS | adapter 测试验证 transport/protocol 异常转成结构化失败结果。 |
| C21 | PASS | `tests/test_mcp_manager.py` 覆盖多个 server 初始化和工具注册。 |
| C22 | PASS | manager 测试覆盖单个 server 失败时其他 server 继续可用。 |
| C23 | PASS | manager close 由 CLI 测试和 manager 资源释放路径覆盖。 |
| C24 | PASS | CLI 测试验证启动时 MCP tool spec 注入 provider 可见工具列表。 |
| C25 | PASS | CLI 测试使用 secret env，断言 `/config` 输出不包含 secret。 |
| C26 | PASS | Agent Loop 测试验证 MCP 工具结果进入历史，并在下一轮传给 provider。 |
| C27 | PASS | MCP 工具走普通工具事件，TUI 既有工具行测试覆盖渲染路径。 |
| C28 | PASS | Agent Loop 测试验证 Plan Mode 下 MCP 工具默认被拒绝，远端未调用。 |
| I1 | PASS | 全量测试 146 条通过，本地工具、权限、Provider、TUI 未回归。 |
| I2 | PASS | MCP adapter 默认 `side_effect=True`，Plan Mode guard 和权限路径生效。 |
| I3 | PASS | manager 测试验证 server 失败隔离；CLI 启动摘要会展示 skipped server。 |
| I4 | PASS | MCP 工具名带 `mcp__{server}__{tool}` 前缀，manager 测试覆盖同名远端工具不冲突。 |
| I5 | PASS | README 已更新 MCP 配置路径、示例字段、合并规则和不支持能力。 |
| T1 | PASS | MCP 目标测试 17 条通过。 |
| T2 | PASS | Agent/CLI/TUI 相关测试 33 条通过。 |
| T3 | PASS | `python -m unittest discover -v` 运行 146 条，通过。 |
| T4 | PASS | `python -m compileall -q huicode tests` 通过。 |
| T5 | PASS_WITH_NOTE | `Get-Command tmux -ErrorAction SilentlyContinue` 未找到 tmux；Windows 当前环境不可做 tmux E2E，已记录。 |
| E1 | PASS | CLI 测试覆盖无 MCP 配置和 `/config` 正常路径。 |
| E2 | PASS | stdio fake server 与 Agent Loop MCP 工具调用测试覆盖发现、调用、回灌。 |
| E3 | PASS | HTTP 测试覆盖 `MCP-Session-Id` 保存和复用。 |
| E4 | PASS | manager 测试覆盖 server 失败隔离。 |
| E5 | PASS | Plan Mode MCP 默认拒绝测试通过。 |
| D1 | PASS | README 包含 stdio MCP 配置示例。 |
| D2 | PASS | README 包含 HTTP MCP 配置示例。 |
| D3 | PASS | README 说明用户级/项目级合并规则。 |
| D4 | PASS | README 说明 `${VAR}` 展开和缺失变量错误。 |
| D5 | PASS | README 说明暂不支持 resources/prompts/sampling/健康检查/自动重连。 |
| R1 | PASS | 本报告逐项记录 checklist 结果。 |
| R2 | PASS | 本报告包含实际测试命令和结果摘要。 |
| R3 | PASS | 本报告包含 tmux E2E 不可用原因。 |
| R4 | PASS | 本报告记录 fake stdio/HTTP 场景证据。 |
| R5 | PASS_WITH_NOTE | 本报告生成后会立即提交 Git commit，提交信息为 `add mcp client tool integration`。 |

## Verification Commands

```powershell
python -m unittest tests.test_mcp_config tests.test_mcp_jsonrpc tests.test_mcp_stdio tests.test_mcp_http tests.test_mcp_tools tests.test_mcp_manager -v
```

Result: 17 tests, OK.

```powershell
python -m unittest tests.test_agent_loop tests.test_cli tests.test_tui -v
```

Result: 33 tests, OK.

```powershell
python -m unittest discover -v
```

Result: 146 tests, OK.

```powershell
python -m compileall -q huicode tests
```

Result: OK.

```powershell
Get-Command tmux -ErrorAction SilentlyContinue
```

Result: exit code 1, no command found. tmux E2E skipped because tmux is unavailable in this Windows environment.

## Notes

- HTTP MCP transport accepts JSON responses and SSE `data:` JSON responses for POST requests.
- HTTP `notifications/initialized` now accepts an empty response body, which matches servers that return `202` for JSON-RPC notifications.
- MCP HTTP support is limited to request/response Streamable HTTP POST in this chapter; persistent server health checks and reconnect behavior remain out of scope.
