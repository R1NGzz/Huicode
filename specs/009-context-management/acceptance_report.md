# HuiCode 上下文管理 Acceptance Report

## Summary

本章实现了 HuiCode 的上下文管理能力，核心包括两层压缩策略：

- 轻量预防：单个超大工具结果或同轮工具结果总量超阈值时，优先把完整结果落盘到 `<workspace>/.huicode/tool-results/`，历史里只保留摘要、预览和相对路径。
- 重量兜底：整体对话逼近上下文窗口时，先保留最近约 1 万 token 或至少 5 条原始消息，再把更早历史压成结构化摘要，并插入边界消息提醒模型需要细节时重新读取文件或重新调用工具。

同时，本章补齐了 `/compact`、`/context`、`/clear` 的上下文控制链路，把压缩事件接进 Agent/TUI/CLI，并保证 OpenAI 与 Anthropic 序列化后的历史仍满足工具调用协议顺序。

结果：通过。

## Checklist Results

| Item | Result | Evidence |
| --- | --- | --- |
| C1 | PASS | `tests.test_config.ConfigTests.test_context_defaults_and_rejects_invalid_values` 覆盖 `context` 默认值和 YAML 覆盖。 |
| C2 | PASS | 同一配置测试覆盖非法布尔、负数和非数字阈值报错。 |
| C3 | PASS | `tests.test_context_manager.ContextManagerTests.test_reset_clears_context_state` 验证 `AgentState.context` 可重置。 |
| C4 | PASS | `tests.test_context_estimator.py` 覆盖文本、消息、prompt、tool schema 的近似 token 估算。 |
| C5 | PASS | `tests.test_context_estimator.ContextEstimatorTests.test_usage_anchor_updates_future_estimates` 与 `test_prompt_tokens_fallback_is_recorded` 覆盖 usage 锚点更新。 |
| C6 | PASS | `tests.test_context_lightweight.ContextLightweightTests.test_spills_large_single_tool_result` 验证超大单工具结果落盘并回写压缩摘要。 |
| C7 | PASS | 同一轻量压缩测试读取落盘 JSON，验证完整 data/error/summary 被保留。 |
| C8 | PASS | `tests.test_context_lightweight.ContextLightweightTests.test_spills_large_single_tool_result` 验证返回相对路径，解析后位于 workspace 内。 |
| C9 | PASS | `tests.test_context_lightweight.ContextLightweightTests.test_group_compacts_largest_results_first` 验证同轮总量超阈值时优先压缩最大结果。 |
| C10 | PASS | `tests.test_context_lightweight.ContextLightweightTests.test_user_messages_are_not_changed` 验证用户原始消息不被改写。 |
| C11 | PASS | `tests.test_agent_context.AgentContextTests.test_large_mcp_tool_result_is_spilled` 验证 MCP 工具结果走同一轻量压缩路径。 |
| C12 | PASS | `tests.test_context_history.ContextHistoryTests.test_build_history_segments_keeps_tool_pairs_together` 覆盖协议安全分段。 |
| C13 | PASS | 同一历史分段测试验证 assistant tool_calls 与紧随其后的 tool messages 不被拆开。 |
| C14 | PASS | `tests.test_context_history.ContextHistoryTests.test_split_recent_messages_respects_minimum_recent_messages` 验证最近消息保留策略。 |
| C15 | PASS | `tests.test_context_history.ContextHistoryTests.test_apply_summary_inserts_boundary_message` 与最近消息保留测试共同证明只替换较早历史。 |
| C16 | PASS | `tests.test_context_history.ContextHistoryTests.test_apply_summary_inserts_boundary_message` 验证边界消息包含“需要细节请重新读取/重新调用工具”的约束。 |
| C17 | PASS | `tests.test_context_summarizer.ContextSummarizerTests.test_summarizes_and_drops_draft` 验证仅保留 `<summary>`，丢弃 `<draft>`。 |
| C18 | PASS | `tests.test_context_summarizer.ContextSummarizerTests.test_tool_call_during_summary_is_failure` 内部 fake provider 断言 `allow_tool_calls=False` 且 `tools=[]`。 |
| C19 | PASS | `tests.test_context_summarizer.ContextSummarizerTests.test_tool_call_during_summary_is_failure` 与 `tests.test_context_manager.ContextManagerTests.test_summary_failures_open_fuse_after_three_attempts` 验证摘要期间出现 tool_call 会失败且保留原历史。 |
| C20 | PASS | `tests.test_context_summarizer.ContextSummarizerTests.test_missing_summary_tag_is_failure` 验证缺失正式 `<summary>` 时压缩失败且原历史不变。 |
| C21 | PASS | `tests.test_context_manager.ContextManagerTests.test_prepare_before_request_triggers_summary_when_over_budget` 验证自动压缩使用窗口上限和自动安全余量。 |
| C22 | PASS | `tests.test_context_manager.ContextManagerTests.test_manual_compact_ignores_auto_threshold` 与 `tests.test_cli_context.CLIContextTests.test_compact_and_context_commands` 验证 `/compact` 可主动触发更激进压缩。 |
| C23 | PASS | `tests.test_context_manager.ContextManagerTests.test_summary_failures_open_fuse_after_three_attempts` 验证连续 3 次摘要失败后打开自动摘要熔断。 |
| C24 | PASS | `tests.test_context_manager.ContextManagerTests.test_fuse_still_allows_lightweight_spill` 验证熔断后轻量工具结果压缩仍继续生效。 |
| C25 | PASS | `tests.test_cli_context.CLIContextTests.test_clear_resets_context_state` 验证 `/clear` 重置上下文状态。 |
| I1 | PASS | `tests.test_agent_context.AgentContextTests.test_summary_runs_before_main_provider_call` 验证每次主请求前先做上下文预处理。 |
| I2 | PASS | `tests.test_agent.AgentTests.test_large_tool_result_is_spilled_to_disk` 与 `tests.test_agent_context.AgentContextTests.test_large_mcp_tool_result_is_spilled` 验证工具结果会在进入下一轮前被压缩。 |
| I3 | PASS | `tests.test_agent_context.AgentContextTests.test_summary_runs_before_main_provider_call` 与 context estimator 测试共同覆盖 usage 锚点更新。 |
| I4 | PASS | `tests.test_tui.TUITests.test_context_events_render` 验证 TUI 可见压缩结果、摘要状态和失败原因。 |
| I5 | PASS | `tests.test_cli_context.CLIContextTests.test_compact_and_context_commands` 验证 `/context` 输出窗口、摘要次数、失败次数和熔断状态。 |
| I6 | PASS | `tests.test_cli_context.CLIContextTests.test_config_shows_context_summary_without_secrets` 验证 `/config` 显示上下文摘要且不泄露 secret。 |
| I7 | PASS | `tests.test_openai_provider_tools.OpenAIProviderToolTests.test_serializes_summary_and_boundary_messages_before_tool_history` 验证 OpenAI 序列化兼容。 |
| I8 | PASS | `tests.test_anthropic_provider_tools.AnthropicProviderToolTests.test_serializes_summary_and_boundary_messages_without_breaking_tool_results` 验证 Anthropic `tool_use` / `tool_result` 顺序合法。 |
| I9 | PASS | `tests.test_context_manager.ContextManagerTests.test_summary_failures_open_fuse_after_three_attempts` 与 Agent/CLI 全量回归测试证明摘要失败或跳过后流程继续。 |
| I10 | PASS | `README.md` 已补充上下文管理策略、命令、配置、落盘位置和限制说明。 |
| T1 | PASS | `python -m unittest tests.test_context_estimator tests.test_context_lightweight tests.test_context_history tests.test_context_summarizer tests.test_context_manager -v`，19 tests，OK。 |
| T2 | PASS | `python -m unittest tests.test_agent_context tests.test_cli_context tests.test_tui -v`，16 tests，OK。 |
| T3 | PASS | `python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v`，11 tests，OK。 |
| T4 | PASS | `python -m unittest tests.test_agent tests.test_agent_loop tests.test_cli tests.test_tools_files tests.test_tools_search tests.test_tools_shell -v`，40 tests，OK。 |
| T5 | PASS | `python -m unittest discover -v`，174 tests，OK。 |
| T6 | PASS | `python -m compileall -q huicode tests`，OK。 |
| T7 | PASS_WITH_NOTE | `Get-Command tmux -ErrorAction SilentlyContinue` 返回空，当前 Windows 环境不可用 tmux，人工 tmux E2E 未执行并已记录。 |
| E1 | PASS | `tests.test_agent.AgentTests.test_large_tool_result_is_spilled_to_disk` 与 `tests.test_agent_context.AgentContextTests.test_large_mcp_tool_result_is_spilled` 覆盖大结果自动落盘。 |
| E2 | PASS | `tests.test_context_lightweight.ContextLightweightTests.test_group_compacts_largest_results_first` 覆盖多工具结果分组压缩。 |
| E3 | PASS | `tests.test_context_manager.ContextManagerTests.test_prepare_before_request_triggers_summary_when_over_budget` 与 `tests.test_agent_context.AgentContextTests.test_summary_runs_before_main_provider_call` 覆盖自动整体摘要。 |
| E4 | PASS | `tests.test_cli_context.CLIContextTests.test_compact_and_context_commands` 覆盖手动 `/compact`。 |
| E5 | PASS | `tests.test_context_manager.ContextManagerTests.test_summary_failures_open_fuse_after_three_attempts` 与 `test_fuse_still_allows_lightweight_spill` 覆盖摘要失败熔断。 |
| E6 | PASS | OpenAI/Anthropic provider 序列化测试覆盖压缩后的协议顺序合法性。 |
| E7 | PASS | `tests.test_cli_context.CLIContextTests.test_clear_resets_context_state` 覆盖 `/clear` 后状态回到初始值。 |
| D1 | PASS | `README.md` 说明轻量工具结果压缩。 |
| D2 | PASS | `README.md` 说明整体历史摘要策略。 |
| D3 | PASS | `README.md` 说明 `/compact` 和 `/context`。 |
| D4 | PASS | `README.md` 说明 `.huicode/tool-results/` 落盘位置。 |
| D5 | PASS | `README.md` 说明近似 token 估算限制。 |
| D6 | PASS | `README.md` 明确摘要不是文件事实来源，细节需重新读取。 |
| D7 | PASS | `README.md` 给出 `context` 配置字段示例和默认策略说明。 |
| R1 | PASS | 本报告逐项记录 checklist 结果。 |
| R2 | PASS | 本报告包含专项测试、全量测试和编译检查的实际结果。 |
| R3 | PASS | 本报告记录了 tmux E2E 未运行的环境原因。 |
| R4 | PASS | 本报告说明当前证据以 fake provider / 自动化回归为主，未包含真实远程 API 长对话压缩实测。 |
| R5 | PASS_WITH_NOTE | Git commit hash 待本章提交后回填。 |

## Verification Commands

```powershell
python -m unittest tests.test_context_estimator tests.test_context_lightweight tests.test_context_history tests.test_context_summarizer tests.test_context_manager -v
```

Result: 19 tests, OK.

```powershell
python -m unittest tests.test_agent_context tests.test_cli_context tests.test_tui -v
```

Result: 16 tests, OK.

```powershell
python -m unittest tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v
```

Result: 11 tests, OK.

```powershell
python -m unittest tests.test_agent tests.test_agent_loop tests.test_cli tests.test_tools_files tests.test_tools_search tests.test_tools_shell -v
```

Result: 40 tests, OK.

```powershell
python -m unittest discover -v
```

Result: 174 tests, OK.

```powershell
python -m compileall -q huicode tests
```

Result: OK.

```powershell
Get-Command tmux -ErrorAction SilentlyContinue
```

Result: no command found. Current Windows environment does not provide tmux, so tmux-based manual E2E was skipped.

## Notes

- 本章实现默认沿用 `.huicode/tool-results/` 作为工具结果落盘目录。
- `single_tool_result_tokens` 默认值当前为 `1000`，这是为了兼容既有工具结果落盘行为与测试；早期计划文档中出现过 `2000`，最终实现以代码和 README 为准。
- 手动 `/compact` 目前会优先执行轻量压缩；如果这一轮已经通过轻量压缩释放了足够空间，就不会再强制继续做一次整体摘要。这一行为已被测试接受，但如果后续产品体验希望“手动压缩总是尽量做摘要”，可在下一章单独调整。
- 真实第三方 API 的长对话压缩效果与质量，本章未做联网实测；现阶段证据主要来自 fake provider、序列化测试和 Agent/CLI/TUI 自动化回归。

## Git

本报告将与第 009 章实现、测试、README 更新和 spec 文档一起提交。提交范围不包含 `.huicode-mcp.yaml` 和根目录历史遗留临时文档。
