# HuiCode SWE-bench 快速提升实施任务

## File List

| Action | File | Responsibility |
| --- | --- | --- |
| Modify | `huicode/prompts/base.py` | 定义长任务执行阶段类型 |
| Modify | `huicode/prompts/builder.py` | 阶段判定、动态进度提示和环境提示精简 |
| Modify | `huicode/prompts/modules.py` | 稳定提示语义去重 |
| Modify | `huicode/prompts/tools.py` | 移除 Tool Schema 通用规则复制 |
| Modify | `huicode/subagents/tool.py` | 明确 Agent 工具合法调用与结构化纠错信息 |
| Create | `scripts/swebench_metrics.py` | 汇总 Agent 日志和 harness report 指标 |
| Modify | `tests/test_prompt_builder.py` | 覆盖阶段边界与进度提示 |
| Modify | `tests/test_prompt_modules.py` | 覆盖精简后必须保留的稳定约束 |
| Modify | `tests/test_prompt_tools.py` | 覆盖 Tool Schema 去重与专属规则 |
| Modify | `tests/test_subagent_tool.py` | 覆盖合法示例和可纠正错误详情 |
| Create | `tests/test_swebench_metrics.py` | 覆盖日志与 report 汇总 |
| Create | `specs/swebench-fast-lift/acceptance_report.md` | 记录验证和 A/B 评测证据 |

## T1: 建立执行阶段判定

**Files:** `huicode/prompts/base.py`, `huicode/prompts/builder.py`, `tests/test_prompt_builder.py`

**Dependencies:** None

**Steps:**

1. 增加四种执行阶段类型。
2. 实现纯函数阶段判定，最大轮次小于 20 时返回禁用状态。
3. 覆盖 20、40、50 最大轮次下的 30%/70%/90% 边界及非法轮次输入。

**Verification:** 运行 `python -m unittest tests.test_prompt_builder -v`；阶段边界测试和原有提示构建测试全部通过。

## T2: 注入长任务动态进度提示

**Files:** `huicode/prompts/builder.py`, `tests/test_prompt_builder.py`

**Dependencies:** T1

**Steps:**

1. 为调查、实现、验证、收尾阶段生成短动态模块。
2. 实现阶段包含公共签名传播检查；验证阶段包含相关测试和回归检查。
3. Plan Mode 和最大轮次小于 20 的任务不生成执行进度模块。
4. 将模块加入 PromptBundle，保持已有模块顺序约束。

**Verification:** 运行 `python -m unittest tests.test_prompt_builder -v`；四阶段文本、Plan Mode 和短任务兼容用例全部通过。

## T3: 精简环境动态提示

**Files:** `huicode/prompts/builder.py`, `tests/test_prompt_builder.py`

**Dependencies:** T2

**Steps:**

1. 移除与 API Tool Schema 重复的可用工具完整列表。
2. Plan Mode 仍保留必要的只读状态信息；执行模式不重复只读工具列表。
3. 保留 workspace、平台、shell、模式、轮次和最大轮次等运行事实。

**Verification:** 运行 `python -m unittest tests.test_prompt_builder -v`；环境事实仍存在，重复工具清单不再出现。

## T4: 精简稳定提示

**Files:** `huicode/prompts/modules.py`, `tests/test_prompt_modules.py`

**Dependencies:** None

**Steps:**

1. 合并身份、任务执行、工具使用和文本输出中重复的事实查证、禁止编造、最小范围和验证要求。
2. 保留 workspace 安全边界、破坏性操作审批、编辑前读取、失败后诊断、修改后验证等关键约束。
3. 保持固定模块名称和顺序兼容。
4. 记录修改前后稳定提示字符数。

**Verification:** 运行 `python -m unittest tests.test_prompt_modules tests.test_prompt_builder -v`；关键约束断言通过，稳定提示字符数低于基线。

## T5: 去除 Tool Schema 通用规则复制

**Files:** `huicode/prompts/tools.py`, `tests/test_prompt_tools.py`

**Dependencies:** T4

**Steps:**

1. 停止向每个工具描述追加相同的通用规则。
2. 仅保留 Read、Write、Edit、Bash、Find、Search 的专属操作提示。
3. 没有专属规则的工具保持原始描述，不追加空段落。
4. 记录默认工具集描述总字符数的前后变化。

**Verification:** 运行 `python -m unittest tests.test_prompt_tools -v`；专属规则存在、通用规则不重复、未知工具描述保持原样。

## T6: 改善 Agent 工具请求纠错

**Files:** `huicode/subagents/tool.py`, `tests/test_subagent_tool.py`

**Dependencies:** None

**Steps:**

1. 在工具描述和字段描述中明确 `defined` 与 `fork` 的必需、禁止字段。
2. 为缺少或非法 `type`、缺少 role、fork 错传 role 等错误增加结构化 details。
3. details 包含合法类型、必需字段和可直接模仿的合法请求对象。
4. 保持现有错误码和运行语义不变。

**Verification:** 运行 `python -m unittest tests.test_subagent_tool -v`；现有行为和新增结构化纠错用例全部通过。

## T7: 实现评测指标解析核心

**Files:** `scripts/swebench_metrics.py`, `tests/test_swebench_metrics.py`

**Dependencies:** None

**Steps:**

1. 定义逐题指标数据结构。
2. 解析日志中的 usage、最大轮次、工具失败、测试命令和 Agent 完成耗时。
3. 解析 report 的 resolved、FAIL_TO_PASS 和 PASS_TO_PASS 数量。
4. 缺少 report 时保留未知状态，不将其当成测试失败报告。
5. 汇总总 tokens、总耗时、resolved、回归题和最大轮次题数。

**Verification:** 运行 `python -m unittest tests.test_swebench_metrics -v`；使用临时日志/report fixture 的解析和缺失数据测试全部通过。

## T8: 增加指标汇总命令行

**Files:** `scripts/swebench_metrics.py`, `tests/test_swebench_metrics.py`

**Dependencies:** T7

**Steps:**

1. 接收 Agent 日志目录、report 根目录和可选 JSON 输出路径。
2. 控制台输出逐题紧凑行和总计。
3. JSON 输出使用 UTF-8、稳定字段名和可比较基线结构。
4. 参数或目录错误返回非零退出码和可读错误。

**Verification:** 运行 `python -m unittest tests.test_swebench_metrics -v`，再对基线日志执行一次命令；应生成 7 个条目并汇总出 3 resolved、约 465.6 万 prompt tokens、4 个最大轮次任务。

## T9: 运行代码级回归验证

**Files:** All modified source and test files

**Dependencies:** T1–T8

**Steps:**

1. 运行提示、Agent Loop、上下文、Provider、工具和子任务相关测试。
2. 修复由本次改动引入的失败。
3. 运行完整测试发现命令。
4. 检查 diff 中没有 API key、评测答案或题目特定硬编码。

**Verification:** 运行 `python -m unittest discover -s tests -v`；全部测试通过。运行 `git diff --check`；无空白错误。

## T10: 执行三题快速 A/B

**Files:** D 盘封存评测副本、Agent 日志、harness report；不修改题目基线

**Dependencies:** T9

**Steps:**

1. 从原始 base commit 重新建立三个单提交工作副本。
2. 使用与基线相同的 `gpt-5.6-sol/high`、任务描述、权限和非交互适配器运行三题。
3. 排除运行时目录和测试文件，生成 LF 补丁。
4. 运行正式 harness 评测。
5. 使用指标脚本生成三题新旧对照。

**Verification:** 三题均有完整 Agent 日志；非空补丁全部成功应用；指标 JSON 包含 resolved、回归、tokens、耗时、轮数和测试命令数。

## T11: 应用快速 A/B 晋级门槛

**Files:** `specs/swebench-fast-lift/acceptance_report.md`

**Dependencies:** T10

**Steps:**

1. 检查 `openai-1636` 是否保持 resolved。
2. 检查两个基线失败题是否至少新增一个 resolved，或两题是否均形成更完整补丁并减少目标失败。
3. 检查三题 tokens 或耗时是否至少下降 10%。
4. 检查是否出现新增回归。
5. 记录通过或停止决定及证据。

**Verification:** 四项门槛都有数值或 report 证据。若门槛失败，执行一次 T11R，停止 T12，不直接继续完整评测。

## T11R: 失败门槛后的单次提示跟进

**Files:** `huicode/prompts/builder.py`, `tests/test_prompt_builder.py`, `specs/swebench-fast-lift/plan.md`

**Dependencies:** T11 failed

**Steps:**

1. 将长任务 20% 边界设为实现闸门；50 轮任务在第 10 轮进入实现阶段。
2. 明确要求未产生生产代码改动时下一次工具调用必须使用 Edit/Write。
3. 明确要求首个生产改动后两轮内运行目标测试，禁止先编辑测试文件。
4. 增加阶段边界、实现闸门和调查截止点测试。

**Verification:** 运行提示构建测试；确认第 10 轮为 implement，动态提示包含生产代码、Edit/Write、目标测试和禁止改测试文件的约束。

## T12: 完整重跑七道有效题

**Files:** D 盘七题封存副本、predictions、Agent 日志、harness reports

**Dependencies:** T11 passed

**Steps:**

1. 为七题重新建立干净的单提交副本。
2. 使用与基线相同的模型、强度、任务输入和补丁过滤运行 HuiCode。
3. 先确认每个非空补丁可应用，再运行单 worker 正式评测。
4. 用指标脚本生成完整新旧对照。

**Verification:** 七题全部有明确的 resolved、failure 或 empty 状态；结果文件显示 harness error 和 incomplete 均为 0。

## T13: 完成验收报告

**Files:** `specs/swebench-fast-lift/acceptance_report.md`

**Dependencies:** T12

**Steps:**

1. 逐项填写 checklist 的实际证据。
2. 对比 3/7、465.6 万输入 tokens、2 小时 45 分和 4 个最大轮次题的基线。
3. 列出未通过题的目标失败、回归和日志行为。
4. 给出是否达到 AC1–AC8 的结论。

**Verification:** 报告包含代码测试、三题门槛、七题结果、效率指标和端到端结论；每个结论都有文件路径或命令输出证据。

## Execution Order

```text
T1 -> T2 -> T3
T4 -> T5
T6
T7 -> T8
(T3, T5, T6, T8) -> T9 -> T10 -> T11
T11 passed -> T12 -> T13
T11 failed -> T11R -> T11R2 -> T11R2A -> T10（复测） -> T11
T11R2A 失败 -> stop and return to design review
```

## T11R2: 实现配置化运行时验证闸门

**Files:** `huicode/config.py`, `huicode/agent_events.py`, `huicode/agent.py`, `huicode/prompts/base.py`, `huicode/prompts/builder.py`, `huicode/tools/files.py`, `huicode.eval.yaml`, `tests/test_config.py`, `tests/test_agent_loop.py`, `tests/test_prompt_builder.py`, `tests/test_tools_files.py`

**Dependencies:** T11R

**Steps:**

1. 增加默认关闭的 `agent_guard` 配置，评测配置显式打开验证闸门和测试文件保护。
2. 在 AgentState 保存待验证状态；成功生产 Edit/Write 设置状态，成功测试/导入/编译/最小复现 Bash 清除状态。
3. 待验证状态注入高优先级动态提示；无工具最终回复被运行时拦回继续执行，不能直接完成。
4. 评测闸门打开时拒绝测试文件 Write/Edit；补充 Edit 多匹配的行号/上下文反馈。
5. 为配置、状态转移、最终回复拦截、验证清除、测试文件拒绝和默认兼容增加测试。

**Verification:** 运行新增 Agent、配置、提示和文件工具测试；再运行完整测试集与 `git diff --check`。使用一个脚本化 Provider 验证“生产编辑 -> 失败验证 -> 修正/成功验证 -> final”的完整状态链。

## T11R2A: 运行 1633 canary

**Files:** D 盘封存副本、Agent 日志、过滤补丁、harness report、`acceptance_report.md`

**Dependencies:** T11R2

**Steps:**

1. 从 1633 的原始 base commit 新建单提交副本并启用 `agent_guard`。
2. 使用 `gpt-5.6-sol/high`、localhost API、原任务描述和相同非交互适配器运行到自然结束。
3. 过滤运行时目录和测试文件，生成预测补丁并运行 1633 的 gold 校验与正式 harness。
4. 读取完整 Agent 日志，确认测试文件编辑被挡下、生产编辑后有验证、目标测试完成，记录 tokens/耗时。

**Verification:** 1633 的 FAIL_TO_PASS 达到 1/1，PASS_TO_PASS 保持 566/566；若 canary 未通过，不启动三题或七题正式评测。

## Revised Three-Round Execution (takes precedence)

1633 guard canary 已完成但未通过，以下任务替代旧的 `T11R -> T11R2 -> T11R2A` 主顺序；guard 代码保留为可选能力，不在 Round 1 评测配置中打开。

### R1. 成本与执行纪律

**Files:** `huicode/prompts/base.py`, `huicode/prompts/builder.py`, `huicode/agent_events.py`, `huicode/agent.py`, `huicode.eval.yaml`, related tests

**Steps:**

1. 降低完整执行指令、计划摘要和 Skill/Agent 目录的重复注入频率，并保持首轮完整信息。
2. 记录只读工具调用、生产编辑和最近验证的轻量状态；在实现截止点和验证阶段将计数转成短提示。
3. 关闭评测配置中的运行时验证闸门，收紧子任务等待/并发，避免把 guard 重试和长等待算进第一轮收益。
4. 不改变模型、Provider、权限边界、测试过滤和单提交封存方式。

**Verification:** 提示构建、Agent Loop、配置和上下文相关测试通过；`git diff --check` 通过；产生一份不含密钥的编排配置摘要。

### R2. 复杂任务成功率

**Dependencies:** R1 verification and Round 1 gate

**Steps:**

1. 强化公共接口定义、实现、直接调用方、mock 和兼容默认参数的闭环提示。
2. 为失败测试保留修正预算，要求最小生产代码修正后重跑目标测试和相关回归。
3. 只做通用编排改动，不加入题目或仓库特判。

**Verification:** 以 `a2aproject__a2a-python-443` 和一题需求遗漏题做定向日志检查，确认完整调用链和测试重跑均可观察。

### R3. 三题门槛与七题确认

**Dependencies:** R2 verification

**Steps:**

1. 用相同 `gpt-5.6-sol/high` 运行 `1633`、`443`、`1636` 三题，读取 report 与完整 JSONL。
2. 只有 `1636` 不回退、无新增回归且 token 或耗时下降至少 10% 才进入七题。
3. 七题仍先 gold 校验，剔除环境失效题，再运行 predictions 正式评测。

**Verification:** 指标汇总包含 resolved、FAIL_TO_PASS、PASS_TO_PASS、tokens、耗时、轮数、工具失败和测试命令数；门槛失败时不启动七题。
