# HuiCode Context Management Checklist

## Implementation Completeness

- [ ] C1: `context` 配置块有默认值，并能从 YAML 覆盖。
  - Verification: `python -m unittest tests.test_config -v`
  - Maps to: AC18

- [ ] C2: 非法 `context.enabled`、非法 token/字符阈值会给出配置错误。
  - Verification: `tests.test_config` 覆盖非法布尔值、0、负数、非数字。
  - Maps to: AC18

- [ ] C3: `AgentState` 包含可重置的上下文状态。
  - Verification: `tests.test_context_manager` 检查默认值、摘要失败计数、熔断状态和 reset。
  - Maps to: AC15

- [ ] C4: 近似 token 估算支持文本、消息列表、prompt 和工具 schema。
  - Verification: `python -m unittest tests.test_context_estimator -v`
  - Maps to: AC5, AC18

- [ ] C5: API usage 能更新估算锚点。
  - Verification: `tests.test_context_estimator` 检查 `input_tokens` 优先、`prompt_tokens` 兜底、字符增量修正。
  - Maps to: AC5

- [ ] C6: 单个超大工具结果会落盘，并在历史中只保留摘要、预览和相对路径。
  - Verification: `tests.test_context_lightweight` 构造超大 `ToolResult`，断言 `.huicode/tool-results/...json` 存在且历史结果被压缩。
  - Maps to: AC1, AC3

- [ ] C7: 落盘文件保存完整工具结果。
  - Verification: `tests.test_context_lightweight` 读取落盘 JSON，断言包含完整 data/error/summary。
  - Maps to: AC1

- [ ] C8: 工具结果落盘路径必须在 workspace 内。
  - Verification: `tests.test_context_lightweight` 检查返回路径是相对路径，解析后位于临时 workspace 内。
  - Maps to: AC1

- [ ] C9: 同一轮多个工具结果合计超阈值时，会优先压缩最大的结果。
  - Verification: `tests.test_context_lightweight` 构造大中小三个结果，断言最大结果先被 spill，小结果可保留内联。
  - Maps to: AC2

- [ ] C10: 轻量压缩不会改写用户原始消息。
  - Verification: `tests.test_context_lightweight` 压缩前后比较 user message content 完全一致。
  - Maps to: AC4

- [ ] C11: MCP 工具结果和本地工具结果走同一轻量压缩路径。
  - Verification: `tests.test_agent_context` 使用 `mcp__fake__echo` 返回大结果，断言结果落盘。
  - Maps to: AC14

- [ ] C12: 历史消息按协议安全段切分。
  - Verification: `python -m unittest tests.test_context_history -v`
  - Maps to: AC13

- [ ] C13: assistant tool_calls 和紧随 tool messages 不会被摘要 cutoff 拆开。
  - Verification: `tests.test_context_history` 构造多工具调用历史，断言该组消息在同一段。
  - Maps to: AC13

- [ ] C14: 整体摘要保留最近约 1 万 token 或至少 5 条消息的原文。
  - Verification: `tests.test_context_history` 使用小阈值模拟长历史，断言近期保留区满足 token/条数规则。
  - Maps to: AC5

- [ ] C15: 整体摘要只替换较早历史，近期消息原文不变。
  - Verification: `tests.test_context_history` 压缩后逐条比较近期消息对象内容。
  - Maps to: AC5, AC12

- [ ] C16: 摘要边界消息包含“需要细节请重新读取/重新调用工具，不能凭摘要脑补”的约束。
  - Verification: `tests.test_context_history` 断言 boundary message 包含重新读取和不能脑补相关文字。
  - Maps to: AC10

- [ ] C17: 摘要输出只保留 `<summary>` 内容，不保留 `<draft>`。
  - Verification: `python -m unittest tests.test_context_summarizer -v`
  - Maps to: AC7, AC9

- [ ] C18: 摘要请求禁用工具调用。
  - Verification: `tests.test_context_summarizer` 的 fake provider 记录 `allow_tool_calls=False` 且 tools 为空。
  - Maps to: AC8

- [ ] C19: 摘要期间如果模型返回 tool_call，压缩失败且原历史不变。
  - Verification: `tests.test_context_summarizer` 和 `tests.test_context_manager` 覆盖 tool_call 失败路径。
  - Maps to: AC8, AC12

- [ ] C20: 缺失正式 `<summary>` 时压缩失败且原历史不变。
  - Verification: `tests.test_context_summarizer` 和 `tests.test_context_manager` 覆盖缺失 summary。
  - Maps to: AC12

- [ ] C21: 自动整体压缩接近窗口上限时触发，并使用 13K 安全余量。
  - Verification: `tests.test_context_manager` 使用小窗口模拟，断言超过 `window - auto_margin` 时触发。
  - Maps to: AC5

- [ ] C22: 手动 `/compact` 使用 3K 安全余量，并可主动触发摘要。
  - Verification: `tests.test_context_manager` 和 `tests.test_cli_context` 覆盖 manual margin。
  - Maps to: AC6

- [ ] C23: 连续 3 次摘要失败后自动整体摘要熔断。
  - Verification: `tests.test_context_manager` 连续三次 fake summary 失败，断言 `summary_fuse_open=True`。
  - Maps to: AC11

- [ ] C24: 熔断后轻量工具结果压缩仍继续生效。
  - Verification: `tests.test_context_manager` 在熔断状态下压缩大工具结果，断言仍落盘。
  - Maps to: AC11

- [ ] C25: `/clear` 重置上下文管理状态。
  - Verification: `python -m unittest tests.test_cli_context -v`
  - Maps to: AC15

## Integration Checks

- [ ] I1: Agent Loop 每次请求前执行上下文预处理。
  - Verification: `tests.test_agent_context` 断言 provider 收到的是压缩后的 messages。
  - Maps to: AC1, AC5

- [ ] I2: 工具执行后，单个超大结果会在进入下一轮前压缩。
  - Verification: `tests.test_agent_context` 运行 Read 大文件场景，断言下一轮 provider messages 中为压缩结果。
  - Maps to: AC1, AC3

- [ ] I3: usage 事件能更新上下文估算锚点。
  - Verification: `tests.test_agent_context` fake provider 发 usage event，断言 `state.context.last_input_tokens` 更新。
  - Maps to: AC5

- [ ] I4: 压缩事件在 TUI 中可见。
  - Verification: `tests.test_tui` 渲染 `AgentEvent(kind="context")`，断言包含落盘数量、摘要结果或失败原因。
  - Maps to: AC3, AC17

- [ ] I5: `/context` 输出当前上下文状态。
  - Verification: `tests.test_cli_context` 输入 `/context`，断言包含 window、summary_count、failure_count、fuse。
  - Maps to: AC16

- [ ] I6: `/config` 输出上下文摘要，但不泄露 secret。
  - Verification: `tests.test_cli_context` 使用含 api key/header/MCP env 的 fake 配置，断言输出不包含 secret 值。
  - Maps to: AC16

- [ ] I7: OpenAI provider 能序列化压缩后的 history。
  - Verification: `python -m unittest tests.test_openai_provider_tools -v`
  - Maps to: AC13

- [ ] I8: Anthropic provider 能序列化压缩后的 history，tool_use 后仍紧跟 tool_result。
  - Verification: `python -m unittest tests.test_anthropic_provider_tools -v`
  - Maps to: AC13

- [ ] I9: 摘要失败、跳过或熔断后 Agent 仍能继续正常回答。
  - Verification: `tests.test_agent_context` 构造摘要失败后下一轮文本回复。
  - Maps to: AC12

- [ ] I10: README 与实现一致。
  - Verification: 手动检查 README 包含策略、命令、配置、落盘位置和限制。
  - Maps to: AC17

## Build And Test Checks

- [ ] T1: Context 模块目标测试通过。
  - Command: `python -m unittest tests.test_context_estimator tests.test_context_lightweight tests.test_context_history tests.test_context_summarizer tests.test_context_manager -v`
  - Maps to: AC18

- [ ] T2: Agent/CLI/TUI 上下文集成测试通过。
  - Command: `python -m unittest tests.test_agent_context tests.test_cli_context tests.test_tui -v`
  - Maps to: AC18

- [ ] T3: Provider 序列化兼容测试通过。
  - Command: `python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v`
  - Maps to: AC13, AC18

- [ ] T4: 既有 Agent、CLI、Provider、工具测试不回归。
  - Command: `python -m unittest tests.test_agent tests.test_agent_loop tests.test_cli tests.test_tools_files tests.test_tools_search tests.test_tools_shell -v`
  - Maps to: AC18

- [ ] T5: 全量测试通过。
  - Command: `python -m unittest discover -v`
  - Maps to: AC18

- [ ] T6: 编译检查通过。
  - Command: `python -m compileall -q huicode tests`
  - Maps to: AC18

- [ ] T7: tmux E2E 检查完成或记录不可用原因。
  - Command: `Get-Command tmux -ErrorAction SilentlyContinue`
  - Maps to: AC19

## End-To-End Scenarios

- [ ] E1: 大文件读取自动落盘。
  - Scenario:
    1. 创建一个超过单工具阈值的文本文件。
    2. 让 HuiCode 读取该文件。
    3. 观察 TUI 出现工具结果和 spill notice。
    4. 下一轮模型收到的是摘要、预览和 `.huicode/tool-results/...json` 路径。
  - Verification: `tests.test_agent_context` 自动覆盖；若 tmux 可用则人工复核。
  - Maps to: AC1, AC3

- [ ] E2: 多工具结果分组压缩。
  - Scenario:
    1. 模型同一轮返回多个 Read/Search/MCP 工具调用。
    2. 多个结果合计超过分组阈值。
    3. HuiCode 优先落盘最大的结果，较小结果保留内联。
  - Verification: `tests.test_context_lightweight` 和 `tests.test_agent_context` 覆盖。
  - Maps to: AC2, AC14

- [ ] E3: 自动整体摘要。
  - Scenario:
    1. 构造长历史逼近窗口上限。
    2. 发送下一条用户消息。
    3. HuiCode 请求前生成结构化摘要。
    4. 历史中出现 summary 和 boundary，最近消息仍是原文。
  - Verification: `tests.test_context_manager` 和 `tests.test_agent_context` 覆盖。
  - Maps to: AC5, AC7, AC10

- [ ] E4: 手动压缩。
  - Scenario:
    1. 长会话中输入 `/compact`。
    2. HuiCode 显示压缩成功、跳过或失败。
    3. `/context` 显示 summary_count 或 failure_count 变化。
  - Verification: `tests.test_cli_context` 覆盖。
  - Maps to: AC6, AC16

- [ ] E5: 摘要失败熔断。
  - Scenario:
    1. fake summarizer 连续三次失败。
    2. HuiCode 打开自动摘要熔断。
    3. 下一轮仍可轻量压缩工具结果并继续对话。
  - Verification: `tests.test_context_manager` 和 `tests.test_agent_context` 覆盖。
  - Maps to: AC11, AC12

- [ ] E6: 协议序列合法。
  - Scenario:
    1. 历史里包含 assistant 多工具调用和多个 tool results。
    2. 整体压缩发生。
    3. OpenAI 和 Anthropic 序列化后的请求仍满足工具调用顺序。
  - Verification: provider 序列化测试覆盖。
  - Maps to: AC13

- [ ] E7: 清空会话。
  - Scenario:
    1. 先产生 usage 锚点、摘要失败计数或 summary_count。
    2. 输入 `/clear`。
    3. `/context` 显示状态回到初始值。
  - Verification: `tests.test_cli_context` 覆盖。
  - Maps to: AC15

## Documentation Checks

- [ ] D1: README 说明轻量工具结果压缩。
- [ ] D2: README 说明整体历史摘要策略。
- [ ] D3: README 说明 `/compact` 和 `/context`。
- [ ] D4: README 说明 `.huicode/tool-results` 落盘位置。
- [ ] D5: README 说明近似 token 估算限制。
- [ ] D6: README 明确摘要不是文件事实来源，需要细节应重新读取。
- [ ] D7: README 说明 context 配置字段和默认值。

## Acceptance Report Requirements

- [ ] R1: `acceptance_report.md` 逐项记录 checklist 结果。
- [ ] R2: 报告包含目标测试、全量测试和编译检查的实际结果。
- [ ] R3: 报告包含 tmux E2E 是否运行及原因。
- [ ] R4: 报告说明是否存在未覆盖的真实 API 行为。
- [ ] R5: 报告记录最终 Git commit hash。

## Self Check

- 每个 AC 至少映射到一个 checklist 项。
- 覆盖了配置、估算、轻量压缩、整体摘要、手动命令、失败熔断、协议序列、TUI、README 和验收报告。
- E2E 场景包含真实用户路径，而不只覆盖内部函数。
- 明确要求不泄露 secret，不提交 `.huicode-mcp.yaml`。
