# HuiCode MCP Client Plan

## Architecture Overview

本章在现有工具系统外新增一层 MCP 集成：启动时读取 MCP 配置，按 Server 建立会话，完成初始化和工具发现，然后把每个远端工具包装成现有 `Tool` 接口注册进 `ToolRegistry`。Agent Loop、TUI、权限系统和 Provider 不需要知道工具来自本地还是 MCP。

整体分层：

```text
YAML config
  -> MCP config loader / merge / env expansion
  -> MCP manager
     -> MCP client session per server
        -> transport: stdio or streamable HTTP
        -> JSON-RPC request/response correlation
        -> initialize / tools/list / tools/call
  -> MCP tool adapter
  -> ToolRegistry
  -> existing Agent Loop
```

核心原则：

- MCP 是工具来源，不是新的 Agent Loop。
- MCP 工具必须走现有 `execute_tool_call()`，从而继承权限、错误兜底、Plan Mode guard、工具结果回灌和 TUI 渲染。
- Server 失败局部隔离：一个 Server 挂掉只影响它自己的工具。
- 远端工具默认视为有副作用，除非后续章节引入只读声明或权限分类。

## Core Data Structures And Interfaces

### MCP Server Config

```python
MCPServerConfig(
    name: str,
    transport: Literal["stdio", "http"],
    command: str | None,
    args: tuple[str, ...],
    env: dict[str, str],
    url: str | None,
    headers: dict[str, str],
    source: str,
)
```

说明：

- `name` 来自配置 map 的 key。
- `source` 用于诊断和合并说明，取 `user` 或 `project`。
- stdio server 必须有 `command`。
- http server 必须有 `url`。
- `${VAR}` 展开在配置加载阶段完成。

### MCP Config

```python
MCPConfig(
    servers: dict[str, MCPServerConfig],
)
```

合并策略：

- 用户级先加载。
- 项目级后加载。
- 同名 Server 后者整体覆盖前者。
- 不同名 Server 保留。

### JSON-RPC Message

内部使用普通 dict 表示 JSON-RPC 消息：

```python
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {...},
}
```

响应关联：

- 每个 session 维护递增 request id。
- `request()` 发送带 id 消息，并等待同 id 响应。
- 响应包含 `error` 时抛出或返回协议错误对象，由调用层转换成 `ToolResult.failure`。

### MCP Transport

```python
class MCPTransport(Protocol):
    def start(self) -> None: ...
    def request(self, message: dict[str, object], timeout_seconds: float) -> dict[str, object]: ...
    def notify(self, message: dict[str, object]) -> None: ...
    def close(self) -> None: ...
```

两个实现：

- `StdioMCPTransport`: 启动子进程，stdin 写入一行 JSON，stdout 读取一行 JSON，stderr 不参与协议。
- `HTTPMCPTransport`: 使用 HTTP POST 发送 JSON-RPC 消息，保存初始化响应里的 `MCP-Session-Id`，后续请求带 header。

### MCP Client Session

```python
MCPClientSession(
    config: MCPServerConfig,
    transport: MCPTransport,
    initialized: bool,
    server_info: dict[str, object],
)
```

职责：

- `initialize()`: 发送 `initialize`，成功后发 `notifications/initialized`。
- `list_tools()`: 调用 `tools/list`。
- `call_tool(name, arguments)`: 调用 `tools/call`。
- `close()`: 释放 transport。

### MCP Tool Adapter

```python
MCPToolAdapter(
    server_name: str,
    remote_name: str,
    public_name: str,
    description: str,
    parameters: dict[str, object],
    session: MCPClientSession,
)
```

映射规则：

- `public_name` 使用带来源前缀的稳定名称，推荐 `mcp__{server}__{tool}`。
- `remote_name` 保留 MCP 原始工具名，`tools/call` 使用它。
- `parameters` 来自 MCP `inputSchema`。
- `side_effect=True`，确保默认按副作用工具处理。
- `run()` 将 HuiCode 工具参数原样传给 MCP `tools/call`，并把返回 content 转成 `ToolResult`。

### MCP Manager

```python
MCPManager(
    sessions: dict[str, MCPClientSession],
    tools: list[MCPToolAdapter],
    errors: list[MCPServerError],
)
```

职责：

- 按配置建立多个 session。
- 初始化并发现工具。
- 注册工具到 `ToolRegistry`。
- 缓存 session，供工具调用复用。
- HuiCode 退出时关闭所有 session。
- 收集启动失败原因，用于启动提示和测试。

## Module Responsibilities

### `huicode/config.py`

职责：

- 保持现有 LLM 配置加载不破坏。
- 扩展顶层配置结构，允许读取可选 `mcp` map。
- 如果现有轻量 YAML 解析器不足以支持 MCP 嵌套和 list，改为内部增强解析器或使用轻量依赖，并保证旧配置测试通过。

本章建议：

- 新增独立 MCP 配置加载模块，不把所有 MCP 逻辑塞进 `LLMConfig`。
- `load_config()` 继续返回 LLM 配置。
- MCP 配置由 `load_mcp_config(user_path, project_path)` 单独读取，降低对现有配置的影响。

### `huicode/mcp/config.py`

职责：

- 定位用户级和项目级 MCP 配置文件。
- 解析 `mcp:` map。
- 校验 stdio/http 必填字段。
- 展开 `${VAR}`。
- 合并两层配置。
- 屏蔽敏感值输出。

推荐路径：

- 用户级：`~/.huicode/mcp.yaml` 或 `~/.huicode.yaml` 中的 `mcp`。
- 项目级：`<workspace>/.huicode-mcp.yaml` 或当前 `--config` 指定项目配置中的 `mcp`。

为避免破坏当前 `huicode.yaml` 的核心 LLM 字段，本章优先支持：

- 用户级独立文件：`~/.huicode/mcp.yaml`
- 项目级独立文件：`<workspace>/.huicode-mcp.yaml`

同时保留从主配置读取 `mcp` 的扩展点，是否在本章启用由实现阶段根据解析器复杂度决定。

### `huicode/mcp/jsonrpc.py`

职责：

- 生成 JSON-RPC request/notification。
- 校验 response 的 `jsonrpc`、`id`、`result`、`error`。
- 把 JSON-RPC error 转成内部异常或错误对象。
- 为 stdio 的异步/乱序响应提供 id 关联基础。

本章范围：

- 自动测试需覆盖 id 匹配。
- stdio 实现可以先串行 request，但仍必须按 id 校验响应，避免错包被当成成功。

### `huicode/mcp/transport.py`

职责：

- 定义 transport protocol。
- 实现 stdio transport。
- 实现 Streamable HTTP transport。

stdio：

- `subprocess.Popen` 启动。
- stdin 写入 JSON + `\n`。
- stdout 读取一行 JSON。
- stderr 可由后台线程或惰性读取收集最近日志，错误时放入 details。
- close 时终止进程。

HTTP：

- 使用标准库 `urllib.request`，避免新增重量依赖。
- POST body 为单个 JSON-RPC message。
- `Accept` 包含 `application/json, text/event-stream`。
- 初始化响应 header 读取 `MCP-Session-Id`。
- 后续请求带 `MCP-Session-Id`。
- 本章不实现 GET SSE 监听，因工具主流程可通过 POST response 完成。

### `huicode/mcp/session.py`

职责：

- 封装初始化握手。
- 封装 `tools/list`。
- 封装 `tools/call`。
- 统一超时和协议错误。

初始化 payload：

- 使用当前支持的 MCP protocol version 常量。
- clientInfo 使用 HuiCode 名称和版本。
- capabilities 本章只声明工具客户端所需的最小能力。

### `huicode/mcp/tools.py`

职责：

- 把 MCP tool metadata 转成 HuiCode `Tool`。
- 把 MCP call result 转成 `ToolResult`。

结果转换：

- `content` 中 text block 拼接进 summary 和 data。
- 非 text block 保留在 data 的 `content` 列表中。
- `isError=true` 时返回 `ToolResult.failure("mcp_tool_error", ...)`。
- JSON-RPC error 返回 `ToolResult.failure("mcp_protocol_error", ...)`。
- transport/timeout 返回 `ToolResult.failure("mcp_transport_error", ...)`。

### `huicode/mcp/manager.py`

职责：

- 根据配置创建 session。
- 初始化 server。
- 发现工具。
- 生成 adapter。
- 注册进 registry。
- 关闭生命周期。

失败隔离：

- 每个 Server 单独 try/except。
- 失败记录到 `errors`。
- 继续处理其他 Server。

### `huicode/cli.py`

职责：

- 启动时加载 MCP 配置。
- 创建默认本地 registry 后注册 MCP 工具。
- 启动提示显示 MCP server/tool 统计，错误用简短诊断，不输出 secret。
- 主循环退出时关闭 MCP manager。
- `/config` 摘要显示 MCP server 数量和工具数量，不显示 headers/env 值。

### `README.md`

职责：

- 添加 MCP 配置示例。
- 说明 stdio 和 http 两种 server。
- 说明用户级/项目级合并。
- 说明本章不支持 resources/prompts/sampling/健康检查/自动重连。

## Module Interactions And Data Flow

### Startup

```text
main()
  -> load LLM config
  -> create provider
  -> create default ToolRegistry
  -> load MCP config
  -> MCPManager.start()
      -> for each server:
          -> create transport
          -> initialize
          -> initialized notification
          -> tools/list
          -> create MCPToolAdapter(s)
  -> registry.register(adapter)
  -> enter chat loop
```

### Tool Call

```text
model emits tool call: mcp__server__tool(args)
  -> execute_tool_call()
      -> permission evaluation
      -> Plan Mode guard has already filtered side-effect calls
      -> MCPToolAdapter.run(args)
          -> session.call_tool(remote_name, args)
          -> transport.request(JSON-RPC tools/call)
          -> convert MCP result to ToolResult
  -> tool result event
  -> history backfill
  -> next model turn
```

### Shutdown

```text
CLI exits
  -> MCPManager.close()
      -> close each session transport
      -> terminate stdio processes
```

## File Organization

```text
huicode/
  mcp/
    __init__.py
    config.py
    jsonrpc.py
    transport.py
    session.py
    tools.py
    manager.py
  cli.py
  tools/
    registry.py
  config.py
tests/
  test_mcp_config.py
  test_mcp_jsonrpc.py
  test_mcp_stdio.py
  test_mcp_http.py
  test_mcp_tools.py
  test_mcp_manager.py
  test_cli.py
README.md
specs/008-mcp-client/
  spec.md
  plan.md
  task.md
  checklist.md
  acceptance_report.md
```

## Technical Decisions And Rationale

| Decision Point | Choice | Rationale |
| --- | --- | --- |
| MCP tool public name | `mcp__{server}__{tool}` | 避免同名冲突，来源清晰，适合模型和 TUI 展示 |
| MCP tool side effect | 默认 `side_effect=True` | 本章无可靠只读判定，按安全默认处理 |
| HTTP client | 标准库 `urllib.request` | 避免新增网络依赖，满足 POST JSON 主流程 |
| HTTP SSE GET | 本章不实现 | 工具调用主流程可用 POST response，SSE 监听属于更完整客户端能力 |
| Config files | 独立 MCP 配置优先 | 当前主配置解析器很轻量，独立文件降低破坏 LLM 配置风险 |
| Server failure | 跳过并记录 | 满足单 Server 不影响其他 Server |
| JSON-RPC concurrency | 先支持 id 配对，stdio 可串行等待 | 满足协议正确性，同时控制本章复杂度 |
| Permission integration | 复用 `Tool` 执行路径 | 不绕过现有权限、Plan Mode、回灌和 TUI |

## Configuration Plan

推荐配置：

用户级：

```text
~/.huicode/mcp.yaml
```

项目级：

```text
<workspace>/.huicode-mcp.yaml
```

内容：

```yaml
mcp:
  local_echo:
    type: stdio
    command: python
    args:
      - tests/fixtures/mcp_echo_server.py
    env:
      ECHO_PREFIX: ${ECHO_PREFIX}
  remote_search:
    type: http
    url: ${MCP_SEARCH_URL}
    headers:
      Authorization: Bearer ${MCP_TOKEN}
```

合并：

```text
user mcp map + project mcp map
same key: project replaces user
different key: both kept
```

环境变量展开策略：

- `${VAR}` 替换为 `os.environ["VAR"]`。
- 缺失变量报配置错误，并指明字段路径，但不输出 secret 值。

## Test Strategy

### Unit Tests

- MCP config:
  - 读取 stdio/http server。
  - 用户级/项目级合并。
  - `${VAR}` 展开。
  - 缺失变量、缺失必填字段报错。

- JSON-RPC:
  - request id 自增。
  - response id 匹配。
  - error response 转异常。
  - invalid JSON/invalid envelope 报协议错误。

- stdio transport:
  - 使用测试 fixture server 完成 initialize/tools/list/tools/call。
  - stderr 日志不污染协议。
  - 无效 stdout 转 transport/protocol failure。

- HTTP transport:
  - 使用本地 fake HTTP server。
  - 验证 POST body。
  - 验证 `Accept` header。
  - 验证 `MCP-Session-Id` 后续携带。

- Tool adapter:
  - MCP text content 转 ToolResult.success。
  - `isError` 转 ToolResult.failure。
  - JSON-RPC/transport error 转 ToolResult.failure。
  - public name 和 remote name 正确映射。

- Manager:
  - 多 server 注册多个工具。
  - 单 server 失败不影响其他 server。
  - 同名工具 public name 不冲突。

### Integration Tests

- CLI 启动时注册 MCP 工具。
- `/config` 只显示 MCP 数量，不泄露 header/env。
- Agent Loop 调用 MCP 工具后结果回灌，下一轮模型可见。
- Plan Mode 下 MCP 工具默认被拒绝执行。

### Verification Commands

```powershell
python -m unittest tests.test_mcp_config tests.test_mcp_jsonrpc tests.test_mcp_stdio tests.test_mcp_http tests.test_mcp_tools tests.test_mcp_manager -v
python -m unittest discover -v
python -m compileall -q huicode tests
Get-Command tmux -ErrorAction SilentlyContinue
```

## Coverage Mapping

- F1-F6 -> MCP config loader, merge tests, no-config CLI regression
- F7-F11 -> transport/jsonrpc modules and tests
- F12-F18 -> session/tool adapter tests
- F19-F21 -> manager lifecycle/failure isolation tests
- F22-F25 -> CLI/TUI/Agent integration tests
- N1-N8 -> dependency choice, docs, verification, acceptance report
- AC1-AC15 -> checklist and test strategy

## Risks And Mitigations

- Risk: 当前轻量 YAML 解析器不支持 list 和深层 map。
  - Mitigation: MCP 配置解析独立实现或引入轻量 YAML 解析能力；不破坏现有 `load_config()` 行为。

- Risk: MCP Server 工具是否只读无法从标准 schema 可靠判断。
  - Mitigation: 本章全部 MCP 工具默认副作用，Plan Mode 默认拒绝。

- Risk: Streamable HTTP SSE 完整实现复杂。
  - Mitigation: 本章只做 POST request/response 工具主线，明确 SSE GET 监听不做。

- Risk: 子进程生命周期处理不当留下进程。
  - Mitigation: manager close 尽力 terminate/kill，并用测试覆盖 close 调用。

- Risk: secret 泄露到日志或 `/config`。
  - Mitigation: 配置摘要只显示 server/tool 数量，不显示 env/header 值。

## Self Check

- 每个 spec 功能点都有模块和测试覆盖。
- 架构复用现有 Tool/Registry/Agent Loop，不引入第二套工具执行系统。
- 已把 MCP 协议顺序、JSON-RPC id、HTTP session、stdio framing、失败隔离和 Plan Mode 安全默认写入设计。
