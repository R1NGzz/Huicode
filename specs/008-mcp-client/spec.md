# HuiCode MCP Client Spec

## Background

HuiCode 目前已经有本地工具系统、工具注册中心、Agent Loop、权限系统和 TUI 工具行展示。下一步要接入 MCP，让用户可以在配置文件中声明外部 MCP Server，HuiCode 启动时自动连接、发现工具，并把这些远端工具包装成现有 Tool 接口注册进工具中心。Agent 使用这些工具时不需要知道工具来自本地还是 MCP。

本章聚焦 MCP 工具能力。根据 MCP 官方协议文档，本章涉及的主线能力是 JSON-RPC 2.0 消息、`initialize`/`notifications/initialized` 生命周期、`tools/list` 工具发现、`tools/call` 工具调用，以及 stdio 和 Streamable HTTP 两类传输。

## Goals

- 支持用户通过配置声明多个 MCP Server。
- HuiCode 启动时自动连接可用 MCP Server，并发现其工具。
- MCP 工具以统一 Tool 接口进入现有工具注册中心。
- Agent 调用 MCP 工具时和调用本地工具一样走工具调用、结果回灌、TUI 展示和权限系统。
- 单个 MCP Server 失败不影响其他 Server 和本地工具。
- 支持用户级和项目级 MCP 配置合并。

## Functional Requirements

- F1: HuiCode 必须支持从配置中读取 MCP Server 列表，配置结构为一个 map，每个 key 是 Server 名称。
- F2: MCP Server 配置必须支持 `stdio` 类型，字段包含 `command`、`args`、`env`。
- F3: MCP Server 配置必须支持 `http` 类型，字段包含 `url`、`headers`。
- F4: `env` 和 `headers` 的值必须支持 `${VAR}` 环境变量展开。
- F5: MCP 配置必须支持用户级和项目级两层合并，项目级同名 Server 覆盖用户级 Server。
- F6: 缺失、空文件或未声明 MCP Server 时，HuiCode 必须保持现有本地工具行为不变。
- F7: HuiCode 必须支持 stdio 传输：启动本地子进程，通过 stdin/stdout 收发换行分隔 JSON-RPC 消息，stderr 作为日志或诊断信息，不作为协议消息。
- F8: HuiCode 必须支持 Streamable HTTP 传输：向 MCP endpoint 发送 JSON-RPC POST 请求，支持服务端返回的 JSON 响应。
- F9: Streamable HTTP 初始化阶段如果服务端返回 `MCP-Session-Id`，后续请求必须带上该 session header。
- F10: JSON-RPC 客户端必须为每个请求生成 id，并能把响应按 id 关联回对应请求。
- F11: JSON-RPC 客户端必须能识别成功响应和错误响应；错误响应应转换成结构化失败结果。
- F12: 每个 MCP Server 会话必须执行初始化握手：发送 `initialize`，收到成功响应后发送 `notifications/initialized`。
- F13: 初始化成功后，HuiCode 必须调用 `tools/list` 获取远端工具列表。
- F14: `tools/list` 返回的每个工具必须被转换成 HuiCode 可暴露给模型的工具规格，使用 MCP `inputSchema` 作为参数 Schema。
- F15: 多个 MCP Server 提供同名工具时，HuiCode 必须避免注册名冲突，并能让用户从工具名看出工具来源。
- F16: MCP 工具被 Agent 调用时，HuiCode 必须通过 `tools/call` 调用对应 Server 的原始工具名，并传递模型提供的 JSON 参数。
- F17: `tools/call` 返回的 MCP content 必须转换成 HuiCode 的结构化 ToolResult；文本 content 应出现在 summary 或 data 中。
- F18: MCP 工具调用失败、超时、Server 断开、协议错误或返回 JSON-RPC error 时，必须返回结构化 ToolResult.failure，不得让 Agent Loop 崩溃。
- F19: MCP Server 的连接必须按 Server 缓存并复用，避免每次工具调用都重新初始化。
- F20: HuiCode 退出时必须尽力释放 MCP Server 资源；stdio 子进程应被关闭，HTTP 会话可清理本地状态。
- F21: 单个 MCP Server 启动失败、初始化失败或工具发现失败时，HuiCode 必须跳过该 Server，并继续注册其他 Server 和本地工具。
- F22: TUI 工具行必须能显示 MCP 工具调用，至少包含工具名和参数摘要；失败摘要应清楚说明来自 MCP Server 的失败。
- F23: MCP 工具必须进入现有权限系统的工具执行路径，不应绕过权限判断、Plan Mode 执行层限制或工具结果回灌。
- F24: Plan Mode 下，只有被判定为读类的 MCP 工具才能执行；本章如果无法可靠判断远端工具是否只读，默认必须把 MCP 工具视为有副作用。
- F25: `/config` 或等价配置摘要不得输出 MCP headers、env 中的敏感值。

## Non-Functional Requirements

- N1: 继续使用 Python 实现，保持现有 Tool 接口、Agent Loop 和 Provider 抽象兼容。
- N2: 不引入大型框架；如需新增依赖，应保持轻量并有明确理由。
- N3: 网络或远端 Server 不可用时，本地工具和普通聊天不应受影响。
- N4: MCP 协议错误、配置错误和工具调用错误必须可诊断，但不得泄露 API key、token、header secret 或 env secret。
- N5: MCP Client 应有单元测试覆盖 JSON-RPC 配对、stdio 传输、HTTP 传输、配置合并、工具适配和失败隔离。
- N6: 真实外部 MCP Server 不作为自动测试硬依赖；自动测试应使用本地假 server 或 fake transport。
- N7: 文档必须给出用户级和项目级 MCP 配置示例。
- N8: 本章完成后必须运行目标测试、全量测试和编译检查；tmux E2E 可用则运行，不可用则记录原因。

## Out of Scope

- 不实现 MCP resources 能力。
- 不实现 MCP prompts 能力。
- 不实现 MCP sampling 能力。
- 不实现 Server 健康检查。
- 不实现自动重连和断线恢复策略。
- 不实现 OAuth 或交互式认证流程。
- 不实现 MCP Server 市场、安装器或发现目录。
- 不实现针对 MCP 工具的细粒度权限分类 UI。
- 不实现长期缓存远端工具列表到磁盘。

## Configuration Shape

用户级和项目级配置都使用同一结构。项目级同名 Server 覆盖用户级 Server。

```yaml
mcp:
  filesystem:
    type: stdio
    command: npx
    args:
      - -y
      - '@modelcontextprotocol/server-filesystem'
      - ${PROJECT_ROOT}
    env:
      NODE_OPTIONS: ${NODE_OPTIONS}
  remote_search:
    type: http
    url: https://example.com/mcp
    headers:
      Authorization: Bearer ${MCP_TOKEN}
```

## Acceptance Criteria

- AC1: 没有 MCP 配置时，HuiCode 启动、默认本地工具列表和现有测试行为保持不变。
- AC2: 用户级和项目级 MCP 配置能合并；项目级同名 Server 覆盖用户级；不同名 Server 都保留。
- AC3: `${VAR}` 能在 stdio env、stdio args、HTTP headers、HTTP url 中展开；未定义变量有明确错误或明确空值策略。
- AC4: stdio MCP Server 能完成 `initialize`、`notifications/initialized`、`tools/list`，并把远端工具注册进工具中心。
- AC5: HTTP MCP Server 能完成 `initialize`、`notifications/initialized`、`tools/list`，并在服务端返回 `MCP-Session-Id` 后带 session 调用后续请求。
- AC6: Agent 调用一个 MCP 工具时，HuiCode 发送 `tools/call`，参数与模型工具调用参数一致，返回结果进入 ToolResult。
- AC7: MCP 工具结果会回灌进对话历史，下一轮模型能看到该工具结果。
- AC8: MCP 工具在 TUI 中显示为普通工具行，错误时显示清晰失败摘要。
- AC9: 一个 MCP Server 初始化失败时，其他 MCP Server 和本地工具仍可使用。
- AC10: JSON-RPC error、超时、连接断开、无效 JSON 都会变成结构化失败结果，Agent Loop 不崩溃。
- AC11: 多个 Server 暴露同名工具时，注册后的工具名不冲突，并保留来源信息。
- AC12: Plan Mode 下 MCP 工具默认不会执行副作用调用；无法证明只读的 MCP 工具会被拒绝。
- AC13: `/config` 或配置摘要不会泄露 MCP headers/env 的敏感值。
- AC14: README 包含 MCP 配置示例、合并规则、传输类型和本章不支持能力说明。
- AC15: MCP 相关单元测试、现有 Agent/Tool/CLI/TUI 测试、全量测试和编译检查通过。

## Self Check

- 每个功能要求都有可观察验收标准覆盖。
- spec 只描述外部行为和协议要求，未指定具体类名或文件拆分。
- 已把 MCP 真实协议约束、Provider 历史回灌经验、Plan Mode 执行层边界和配置分章经验纳入验收。
