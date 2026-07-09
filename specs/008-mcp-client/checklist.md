# HuiCode MCP Client Checklist

## Implementation Completeness

- [ ] C1: MCP 配置加载器支持用户级和项目级两层配置。
  - Verification: `tests/test_mcp_config.py` 覆盖用户级、项目级、同名覆盖、不同名保留。
  - Maps to: AC2

- [ ] C2: MCP 配置支持 stdio server。
  - Verification: 配置测试覆盖 `type: stdio`、`command`、`args`、`env`。
  - Maps to: AC4

- [ ] C3: MCP 配置支持 HTTP server。
  - Verification: 配置测试覆盖 `type: http`、`url`、`headers`。
  - Maps to: AC5

- [ ] C4: `${VAR}` 展开策略正确。
  - Verification: 配置测试覆盖 args、env、url、headers 中的变量展开和缺失变量错误。
  - Maps to: AC3

- [ ] C5: 无 MCP 配置时现有行为不变。
  - Verification: CLI/registry 相关既有测试通过，并新增无 MCP 配置测试。
  - Maps to: AC1

- [ ] C6: JSON-RPC request id 能生成并匹配响应。
  - Verification: `tests/test_mcp_jsonrpc.py` 覆盖 id 自增、id mismatch。
  - Maps to: AC10

- [ ] C7: JSON-RPC error 和非法响应能转成协议错误。
  - Verification: `tests/test_mcp_jsonrpc.py` 覆盖 error response、invalid JSON-RPC envelope。
  - Maps to: AC10

- [ ] C8: stdio transport 能通过换行 JSON-RPC 完成通信。
  - Verification: `tests/test_mcp_stdio.py` 使用 fake stdio server 完成 request/notify。
  - Maps to: AC4

- [ ] C9: stdio stderr 不污染协议。
  - Verification: fake stdio server 写 stderr 后，stdout JSON-RPC 仍正常解析。
  - Maps to: AC4, AC10

- [ ] C10: HTTP transport 能发送 MCP JSON-RPC POST。
  - Verification: `tests/test_mcp_http.py` fake HTTP server 验证 method、body、Content-Type、Accept。
  - Maps to: AC5

- [ ] C11: HTTP transport 能保存并复用 `MCP-Session-Id`。
  - Verification: fake HTTP server 初始化返回 session，后续请求断言 header 存在。
  - Maps to: AC5

- [ ] C12: MCP session 完成初始化握手。
  - Verification: session 测试验证 `initialize` 成功后发送 `notifications/initialized`。
  - Maps to: AC4, AC5

- [ ] C13: MCP session 能执行 `tools/list`。
  - Verification: stdio/http session 测试返回工具列表并解析。
  - Maps to: AC4, AC5

- [ ] C14: MCP session 能执行 `tools/call`。
  - Verification: stdio/http 测试验证调用原始工具名和参数。
  - Maps to: AC6

- [ ] C15: MCP tool adapter 使用稳定公开工具名。
  - Verification: `tests/test_mcp_tools.py` 验证 `mcp__server__tool` 命名和非法字符归一化。
  - Maps to: AC11

- [ ] C16: MCP tool adapter 保留远端原始工具名。
  - Verification: 调用 adapter 时 `tools/call.params.name` 使用原始 MCP 工具名。
  - Maps to: AC6

- [ ] C17: MCP `inputSchema` 转成 HuiCode 工具参数 Schema。
  - Verification: tool adapter 或 manager 测试检查 registry 中的 ToolSpec parameters。
  - Maps to: AC6

- [ ] C18: MCP text content 转成成功 ToolResult。
  - Verification: `tests/test_mcp_tools.py` 检查 summary 和 data 中包含 text content。
  - Maps to: AC6, AC7

- [ ] C19: MCP `isError=true` 转成失败 ToolResult。
  - Verification: `tests/test_mcp_tools.py` 检查 `mcp_tool_error`。
  - Maps to: AC10

- [ ] C20: MCP 传输、超时、协议错误转成失败 ToolResult。
  - Verification: `tests/test_mcp_tools.py` 或 transport 测试覆盖 `mcp_transport_error` / `mcp_protocol_error`。
  - Maps to: AC10

- [ ] C21: MCP manager 能初始化多个 server 并注册工具。
  - Verification: `tests/test_mcp_manager.py` 覆盖两个 server 都注册成功。
  - Maps to: AC9, AC11

- [ ] C22: 单个 MCP server 失败不影响其他 server。
  - Verification: manager 测试一个 server 初始化失败、另一个正常注册。
  - Maps to: AC9

- [ ] C23: MCP manager close 会释放 server 资源。
  - Verification: manager/transport 测试确认 close 调用到每个 session/transport。
  - Maps to: AC9

- [ ] C24: CLI 启动时注册 MCP 工具。
  - Verification: CLI 测试或集成测试确认 provider 看到 MCP tool spec。
  - Maps to: AC4, AC5, AC6

- [ ] C25: `/config` 或配置摘要不泄露 MCP secret。
  - Verification: CLI 测试使用 secret header/env，断言输出不包含 secret 值。
  - Maps to: AC13

- [ ] C26: MCP 工具调用结果回灌进 Agent 历史。
  - Verification: Agent Loop 测试中模型调用 MCP 工具，下一轮 provider messages 包含 tool result。
  - Maps to: AC7

- [ ] C27: MCP 工具在 TUI 中显示为普通工具行。
  - Verification: TUI/CLI 测试输出包含 MCP 工具名和结果摘要。
  - Maps to: AC8

- [ ] C28: Plan Mode 下 MCP 工具默认被拒绝。
  - Verification: Agent Loop 测试在 `mode="plan"` 调 MCP 工具，远端调用未发生，结果为 `permission_denied`。
  - Maps to: AC12

## Integration Checks

- [ ] I1: 本地工具注册和调用不回归。
  - Verification: 既有 tools、agent、cli 测试通过。
  - Maps to: AC1, AC15

- [ ] I2: 权限系统仍应用于 MCP 工具。
  - Verification: MCP 工具 `side_effect=True`，默认模式下会进入确认或被 Plan Mode guard 拒绝。
  - Maps to: AC12

- [ ] I3: MCP server 失败不会中断 HuiCode 启动。
  - Verification: CLI/manager 测试中一个 server 失败，进程仍进入聊天循环或返回可用 registry。
  - Maps to: AC9

- [ ] I4: MCP 工具名不会与本地工具冲突。
  - Verification: manager 测试中远端工具名为 `Read` 或多个 server 都叫 `search`，注册名仍唯一。
  - Maps to: AC11

- [ ] I5: README 与实现一致。
  - Verification: README 包含实际配置路径、示例字段和不支持能力说明。
  - Maps to: AC14

## Build And Test Checks

- [ ] T1: MCP 目标测试通过。
  - Command: `python -m unittest tests.test_mcp_config tests.test_mcp_jsonrpc tests.test_mcp_stdio tests.test_mcp_http tests.test_mcp_tools tests.test_mcp_manager -v`
  - Maps to: AC15

- [ ] T2: Agent/CLI/TUI 相关测试通过。
  - Command: `python -m unittest tests.test_agent_loop tests.test_cli tests.test_tui -v`
  - Maps to: AC15

- [ ] T3: 全量测试通过。
  - Command: `python -m unittest discover -v`
  - Maps to: AC15

- [ ] T4: 编译检查通过。
  - Command: `python -m compileall -q huicode tests`
  - Maps to: AC15

- [ ] T5: tmux E2E 检查完成或记录不可用原因。
  - Command: `Get-Command tmux -ErrorAction SilentlyContinue`
  - Maps to: AGENT.md

## End-To-End Scenarios

- [ ] E1: 无 MCP 配置启动。
  - Scenario:
    1. 不提供 `.huicode-mcp.yaml`。
    2. 启动 HuiCode。
    3. 本地工具仍可用。
    4. `/config` 不报错。
  - Verification: CLI 自动测试覆盖。
  - Maps to: AC1

- [ ] E2: stdio MCP 工具发现和调用。
  - Scenario:
    1. 项目级配置声明 fake stdio MCP server。
    2. HuiCode 启动时 initialize 并 tools/list。
    3. 模型调用 `mcp__fake__echo`。
    4. HuiCode 发送 tools/call。
    5. TUI 显示工具行，结果回灌进下一轮。
  - Verification: stdio + Agent Loop 集成测试覆盖。
  - Maps to: AC4, AC6, AC7, AC8

- [ ] E3: HTTP MCP session header。
  - Scenario:
    1. fake HTTP server 在 initialize 响应返回 `MCP-Session-Id`。
    2. HuiCode 后续 `tools/list` 和 `tools/call` 带该 header。
  - Verification: HTTP transport 测试覆盖。
  - Maps to: AC5

- [ ] E4: Server 失败隔离。
  - Scenario:
    1. 配置两个 MCP server。
    2. 第一个初始化失败。
    3. 第二个正常发现工具。
    4. 本地工具和第二个 server 工具仍可用。
  - Verification: manager 测试覆盖。
  - Maps to: AC9

- [ ] E5: Plan Mode 安全默认。
  - Scenario:
    1. 进入 Plan Mode。
    2. 模型请求 MCP 工具。
    3. HuiCode 不发远端 tools/call。
    4. 工具结果为 `permission_denied`，Agent Loop 继续。
  - Verification: Agent Loop 测试覆盖。
  - Maps to: AC12

## Documentation Checks

- [ ] D1: README 包含 stdio MCP 配置示例。
- [ ] D2: README 包含 HTTP MCP 配置示例。
- [ ] D3: README 说明用户级/项目级合并规则。
- [ ] D4: README 说明 `${VAR}` 展开。
- [ ] D5: README 说明本章不支持 resources/prompts/sampling/健康检查/自动重连。

## Acceptance Report Requirements

- [ ] R1: `acceptance_report.md` 逐项记录 checklist 结果。
- [ ] R2: 报告包含实际测试命令和结果摘要。
- [ ] R3: 报告包含 tmux E2E 是否运行及原因。
- [ ] R4: 报告包含 MCP fake stdio/HTTP 场景证据。
- [ ] R5: 报告说明是否已提交 Git commit。

## Self Check

- 每个 AC 至少映射到一个 checklist 项。
- 覆盖了配置、协议、传输、会话、工具适配、注册、CLI、Agent Loop、权限、文档和测试。
- E2E 场景对应真实用户使用路径，而不只是内部单元函数。
