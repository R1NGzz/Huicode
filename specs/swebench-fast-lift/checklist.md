# HuiCode SWE-bench 快速提升验收清单

> 每一项必须通过运行命令、读取日志或观察 harness 报告验证。只有实际证据可以勾选。

## Implementation Completeness

- [ ] 长任务能根据轮次进入调查、实现、验证和收尾四个阶段。[AC3] 验证：运行 `python -m unittest tests.test_prompt_builder -v`，观察四阶段边界用例通过。
- [ ] 最大轮次小于 20 的短任务不注入阶段流程。[AC8] 验证：运行短任务提示构建测试，观察不存在 execution progress 模块。
- [ ] Plan Mode 不收到实现、写代码或测试阶段指令。[AC8] 验证：运行 Plan Mode 提示测试，观察仍保持只读要求。
- [ ] 实现阶段明确要求检查公共接口的定义、实现、直接调用方和 mock。[AC6] 验证：构建 implement 阶段提示并观察四类检查要求均存在。
- [ ] 验证阶段明确要求停止宽泛探索、运行相关测试并检查回归。[AC5] 验证：构建 verify 阶段提示并观察测试与回归要求存在。
- [ ] 收尾阶段禁止开启新方向，并要求完成当前修复和差异检查。[AC3] 验证：构建 finalize 阶段提示并观察收尾约束存在。
- [ ] 评测闸门默认关闭且可由配置打开。[AC9] 验证：配置测试断言默认值为 false，评测 YAML 读取为 true。
- [ ] 生产 Edit/Write 成功后形成待验证状态，成功验证后清除。[AC9] 验证：运行 Agent Loop 状态转移测试并检查 state 字段。
- [ ] 待验证时无工具最终回复不会发出 final done，而会追加验证反馈继续请求。[AC9] 验证：运行脚本化 Provider 集成测试。
- [ ] 闸门打开时测试文件 Write/Edit 在写盘前被拒绝，读取仍可用。[AC9] 验证：运行文件工具测试并确认文件内容不变。
- [ ] Edit 多匹配错误提供行号或上下文，便于一次修正。[AC9] 验证：运行多匹配文件工具测试并检查结构化 details。
- [ ] 稳定提示精简后仍保留 workspace、安全审批、编辑前读取、失败诊断和修改后验证约束。[AC8] 验证：运行 `python -m unittest tests.test_prompt_modules -v`，相关约束断言全部通过。
- [ ] 环境提示不再重复 API Tool Schema 已表达的完整工具清单。[AC2] 验证：运行 `python -m unittest tests.test_prompt_builder -v`，观察执行模式环境文本没有 available_tools/read_only_tools 列表。
- [ ] 每个 Tool Schema 不再复制相同的通用规则，无专属规则的工具保持原描述。[AC2] 验证：运行 `python -m unittest tests.test_prompt_tools -v`。
- [ ] Agent 工具对 `defined` 和 `fork` 的合法字段组合描述清晰。[AC4] 验证：检查工具 Schema 测试中的描述和字段约束断言通过。
- [ ] Agent 工具格式错误返回可直接纠正的 details，且保持现有错误码。[AC4] 验证：运行 `python -m unittest tests.test_subagent_tool -v`，观察非法 type、缺 role、fork 错传 role 用例通过。
- [ ] 指标汇总器能提取 resolved、目标测试、回归、tokens、耗时、轮数、工具失败和测试命令数。[AC6] 验证：运行 `python -m unittest tests.test_swebench_metrics -v`。
- [ ] 指标汇总器遇到空补丁或缺少 report 时输出未知状态，不伪造测试结果。[AC6] 验证：运行缺失 report fixture 测试。

## Integration

- [ ] PromptBundle 中稳定、动态和补充模块的原有顺序约束没有被破坏。[AC8] 验证：运行 `python -m unittest tests.test_prompt_builder -v`。
- [ ] OpenAI 和 Anthropic Provider 都能接受精简后的 PromptBundle 与 ToolSpecs。[AC8] 验证：运行 `python -m unittest tests.test_openai_provider_prompts tests.test_anthropic_provider_prompts tests.test_openai_provider_tools tests.test_anthropic_provider_tools -v`。
- [ ] 普通聊天、Do Mode 和 Plan Mode 的 Agent Loop 均保持可用。[AC8] 验证：运行 `python -m unittest tests.test_agent_loop tests.test_cli_plan_mode -v`。
- [ ] 子 Agent 的 defined 前台、defined 后台和 fork 流程保持原行为。[AC4][AC8] 验证：运行 `python -m unittest tests.test_subagent_tool tests.test_subagent_cli_e2e -v`。
- [ ] 基线日志可由指标工具重现为 3 resolved、约 465.6 万 prompt tokens、约 2 小时 45 分、4 个最大轮次任务。[AC6][AC7] 验证：对基线日志和 report 目录运行指标 CLI，比较已保存基线。
- [ ] 新实现中不存在 API key、gold patch、题号分支或仓库名特判。[AC7] 验证：检查 `git diff` 并搜索七个 instance_id、`model_patch` 和密钥前缀，预期实现文件无匹配。

## Build and Tests

- [ ] 提示构建相关测试全部通过。[AC8] 验证：运行 `python -m unittest tests.test_prompt_builder tests.test_prompt_modules tests.test_prompt_tools -v`。
- [ ] Agent 与上下文相关测试全部通过。[AC8] 验证：运行 `python -m unittest tests.test_agent tests.test_agent_loop tests.test_agent_context tests.test_context_manager tests.test_context_lightweight -v`。
- [ ] 子 Agent 相关测试全部通过。[AC4][AC8] 验证：运行 `python -m unittest tests.test_subagent_tool tests.test_subagent_manager tests.test_subagent_cli_e2e -v`。
- [ ] 指标工具测试全部通过。[AC6] 验证：运行 `python -m unittest tests.test_swebench_metrics -v`。
- [ ] 完整测试集没有新增失败。[AC8] 验证：运行 `python -m unittest discover -s tests -v`，退出码为 0。
- [ ] 代码差异没有空白错误。[AC8] 验证：运行 `git diff --check`，退出码为 0。

## Quick A/B Gate

- [ ] 三道代表题均从原始 base commit 生成新的单提交封存副本。[AC6][AC7] 验证：每个副本 `git rev-list --count HEAD` 输出 1，且初始 `git status --short` 为空。
- [ ] 三题使用与基线相同的 `gpt-5.6-sol/high`、任务描述、权限和非交互运行方式。[AC7] 验证：保存运行配置摘要和三份完整日志。
- [ ] `openai-1636` 继续 resolved，目标和原有测试无失败。[AC1] 验证：读取新 report.json。
- [ ] `openai-1633` 与 `a2a-443` 至少新增一道 resolved；若没有，则两题必须均减少 FAIL_TO_PASS 失败并形成更完整调用链补丁，才可视为弱正向信号。[AC1][AC6] 验证：比较新旧 report 和模型补丁。
- [ ] 三题没有新增 PASS_TO_PASS 回归。[AC1] 验证：三个 report 的 PASS_TO_PASS.failure 均为空。
- [ ] 三题合计 prompt tokens 或 Agent 耗时相比基线至少降低 10%。[AC2] 验证：运行指标 CLI 并计算同题差值。
- [ ] 三题日志不再出现 `type 只允许 defined 或 fork`。[AC4] 验证：在完整 Agent 日志中搜索该文本，匹配数为 0。
- [ ] 每个非空源代码补丁对应的日志至少包含一个相关测试/验证命令或具体环境阻塞证据。[AC5] 验证：逐题检查测试命令指标和日志片段。
- [ ] 快速门槛结论有明确证据；失败时完整七题评测未启动。[AC6] 验证：读取 acceptance report 中的 gate 决定和时间戳。
- [ ] 首轮门槛失败时只执行一次提示跟进：50 轮任务第 10 轮进入实现，未改生产代码时优先 Edit/Write，首个改动后两轮内运行目标测试且不先修改测试文件。[AC1][AC3][AC5] 验证：读取新提示测试和复测日志；若再次低于 2/3，不启动完整七题评测。
- [ ] 1633 canary 在运行时闸门启用后目标测试通过且无回归。[AC1][AC5][AC9] 验证：读取单题 report、补丁和完整日志；FAIL_TO_PASS 为 1/1，PASS_TO_PASS 为 566/566。

## Revised Three-Round Route

- [ ] Round 1 不更换模型、Provider 或评测题目，仅降低重复提示、目录注入和子任务等待，并关闭 guard。[AC10][AC11] 验证：比较配置摘要和 git diff。
- [ ] Round 1 长任务日志能观察只读调用、生产编辑和验证节奏；实现截止点不再只靠重复长提示。[AC10] 验证：读取 `execution_progress` 和 Agent 事件序列。
- [ ] Round 1 三题门槛至少降低 token 或耗时 10%，且 `1636` 不回退、无新增 PASS_TO_PASS 回归。[AC10] 验证：读取三题 reports 与指标 JSON。
- [ ] Round 2 复杂题提示覆盖定义、实现、直接调用方、mock/兼容路径和目标测试重跑。[AC1][AC6] 验证：检查 `443` 及需求遗漏题完整日志。
- [ ] Round 3 只有三题门槛通过后才启动七题正式评测；guard canary 不再作为前置条件。[AC7][AC11] 验证：读取 acceptance report 的时间线和配置摘要。

## Full Seven-Task Evaluation

- [ ] 完整复测仅在 Quick A/B Gate 通过后启动。[AC6] 验证：acceptance report 中 gate 状态为 passed。
- [ ] 七题使用与基线相同的题目、模型、强度、封存方式、过滤规则和 harness 参数。[AC7] 验证：对比基线与新运行配置摘要。
- [ ] 七题 resolved 至少为 4/7，且基线通过的 1636、1619、8211 仍全部通过。[AC1] 验证：读取新 `results.json` 和逐题 report。
- [ ] prompt tokens 至少降低 20%，或 Agent 总耗时至少降低 15%。[AC2] 验证：指标 CLI 输出与 465.6 万 tokens、2 小时 45 分基线比较，至少一项达标。
- [ ] 达到最大迭代上限的题目不超过 2/7。[AC3] 验证：指标 CLI 的 max_iteration_reached 合计不超过 2。
- [ ] 七题日志中已知 Agent 工具类型错误为 0。[AC4] 验证：指标和文本搜索均无匹配。
- [ ] 每个非空源代码补丁均运行相关验证，或记录具体环境阻塞证据。[AC5] 验证：逐题测试命令指标及日志证据齐全。
- [ ] 正式 harness 的 error 和 incomplete 都为 0。[AC7] 验证：读取 `results.json`。

## End-to-End Scenarios

- [ ] 场景一：长程接口变更任务从事实定位进入实现，检查完整调用链，在预算后段运行测试并产生可应用补丁。[AC1][AC3][AC5][AC6] 验证：检查 `a2a-443` 新日志时间线、补丁路径和 report。
- [ ] 场景二：已通过但曾耗尽轮次的任务提前完成实现和验证，同时保持 resolved。[AC1][AC2][AC3] 验证：比较 `openai-1636` 的新旧轮数、tokens、耗时和 report。
- [ ] 场景三：模型发出非法 Agent 工具请求时，结构化反馈使下一次请求使用合法类型且任务继续执行。[AC4] 验证：运行模拟两轮 Provider 的 Agent Loop 集成测试，观察第二次调用合法并成功。
- [ ] 场景四：从日志和 harness 目录运行指标 CLI，生成逐题 JSON 和总计，可直接判断 Quick Gate 与完整验收是否通过。[AC2][AC6][AC7] 验证：对实际评测目录运行命令并核对输出文件。
