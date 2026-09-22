# HuiCode SWE-bench 快速提升技术方案

## Architecture Overview

本周期采用“编排层三轮渐进改造 + 评测指标自动汇总”的方案。模型固定为 `gpt-5.6-sol/high`，不修改 Provider 协议，不把运行时验证闸门作为第一轮主路径。

提示构建层根据当前轮次与最大轮次计算执行阶段，并生成一段很短的动态进度指令：前段完成事实定位，中段进入实现，后段停止扩散并测试，末段只允许收尾。状态同时记录只读工具调用、生产编辑和最近验证，提示只反馈必要的计数和下一步纪律，不硬切断正常工具调用。涉及公共接口时，阶段指令要求检查定义、实现、调用点和兼容性测试，从而针对跨模块传播遗漏。

稳定提示和工具说明进行去重：通用工具规则只在稳定提示中出现一次，不再复制到每一个 Tool Schema；环境模块不再重复列出已由 API Tool Schema 表达的工具清单；计划摘要和 Skill/Agent 目录只在首轮及低频检查点完整注入。Agent 工具继续使用严格 JSON Schema，同时在描述和失败反馈中提供两种合法请求形态，降低模型漏传 `type` 的概率。

评测侧新增只读汇总器，从 Agent 日志和 harness report 中提取统一指标。先对三道代表题做快速 A/B；达到晋级门槛后再完整重跑七道题。

## Core Data Structures and Interfaces

### `ExecutionPhase`

```python
ExecutionPhase = Literal["investigate", "implement", "verify", "finalize"]
```

表示长程 Agent 当前应处于的工作阶段。阶段按 `iteration / max_iterations` 计算：

- `investigate`：小于 20%，定位根因、验收条件和相关调用链；最迟第 20% 轮完成首次生产代码修改。
- `implement`：达到 20% 且不超过 60%，停止泛读并实施最可能方案；首次生产修改后两轮内运行目标测试。
- `verify`：超过 60% 且不超过 85%，运行相关测试、检查调用方和修复失败。
- `finalize`：超过 85%，只完成当前修复、最小验证和差异检查，不开启新方向。

当最大轮次小于 20 时不启用阶段约束，保证短任务和短子任务行为兼容。

### `execution_phase(iteration, max_iterations)`

```python
def execution_phase(iteration: int, max_iterations: int) -> ExecutionPhase | None
```

纯函数，负责边界校验和阶段判定，供提示构建与单元测试使用。

### `execution_progress_module(context)`

```python
def execution_progress_module(context: PromptContext) -> PromptModule | None
```

根据阶段返回不可缓存的短动态指令。Plan Mode 不生成实现/测试阶段指令；普通执行模式与 Do Mode启用。

阶段指令包括：

- investigate：明确验收条件、根因和受影响路径，避免重复读取。
- implement：立即产生源代码改动；修改签名时搜索定义、实现、直接调用方和 mock。
- verify：停止宽泛探索，运行相关测试并检查回归。
- finalize：不再开新方案，只完成修复、验证和 `git diff` 检查。

### `EvalRunMetrics`

```python
@dataclass(frozen=True)
class EvalRunMetrics:
    instance_id: str
    resolved: bool | None
    fail_to_pass_success: int
    fail_to_pass_failure: int
    pass_to_pass_success: int
    pass_to_pass_failure: int
    prompt_tokens: int
    completion_tokens: int
    duration_seconds: float | None
    max_iteration_reached: bool
    tool_failures: int
    test_commands: int
```

### 评测汇总接口

```python
def summarize_run(
    agent_logs: Path,
    report_root: Path,
    output_path: Path | None = None,
) -> dict[str, object]
```

输入日志目录和 harness 报告目录，输出逐题指标及合计；缺少 report 的空补丁题保留为 `resolved=None`，不伪造测试结果。

## Module Design

### Prompt Base

**Responsibility:** 定义执行阶段类型及长任务阶段启用边界。

**External Interface:** `ExecutionPhase`；现有 `PromptContext` 字段足以完成阶段计算，不增加运行时状态。

**Dependencies:** 无新增依赖。

**Requirements:** F1、F2。

### Prompt Builder

**Responsibility:** 计算当前执行阶段、注入短进度提示；精简环境模块中的重复字段；增强跨模块传播与测试收尾要求。

**External Interface:** `execution_phase()` 可由测试直接验证；`build_prompt_bundle()` 保持签名兼容。

**Dependencies:** Prompt Base、现有 Prompt Module。

**Requirements:** F1、F2、F3、F4。

### Stable Prompt Modules

**Responsibility:** 合并语义重复的动作、工具和完成条件规则；安全边界只保留一份，不能因精简而删除。

**External Interface:** `fixed_prompt_modules()` 保持返回结构兼容。

**Dependencies:** 无。

**Requirements:** F4。

### Tool Prompt Enhancer

**Responsibility:** 只为确实需要补充的工具添加工具专属说明，不再向每个工具复制 workspace、禁止编造结果等通用规则。

**External Interface:** `enhance_tool_specs()` 保持签名兼容。

**Dependencies:** Provider ToolSpec。

**Requirements:** F4。

### Agent Subtask Tool

**Responsibility:** 在 Schema 描述和验证失败结果中明确合法请求组合；保持 `defined`/`fork` 运行语义不变。

**External Interface:**

```text
defined: {"type":"defined","task":"检查调用链并返回结论","role":"<catalog role>","background":false}
fork:    {"type":"fork","task":"独立检查测试失败原因"}
```

失败结果继续使用 `invalid_request`，但 `details` 包含合法类型、必需字段和示例。

**Dependencies:** Subagent Manager、Agent Catalog。

**Requirements:** F5。

### Evaluation Metrics Utility

**Responsibility:** 从现有文本日志和 `report.json` 统一提取质量、成本、耗时和行为指标，生成 JSON 与控制台摘要。

**External Interface:** `summarize_run()` 和命令行入口。

**Dependencies:** 仅使用 Python 标准库。

**Requirements:** F6、F7。

## Module Interactions and Data Flow

```text
Agent iteration/max_iterations
        |
        v
PromptContext
        |
        +--> execution_phase() --> execution_progress_module()
        |
        +--> stable prompt modules（去重）
        |
        +--> environment module（精简）
        v
PromptBundle + concise ToolSpecs
        |
        v
Provider request --> model tool calls --> existing executor
                                      |
                                      +--> AgentTool structured correction

agent log + harness report.json
        |
        v
evaluation metrics utility
        |
        +--> 3-task quick A/B gate
        +--> 7-task full comparison
```

### 快速 A/B 晋级门槛

代表题固定为：

- `openai__openai-agents-python-1633`：需求验收条件遗漏。
- `a2aproject__a2a-python-443`：跨模块传播不完整。
- `openai__openai-agents-python-1636`：已通过但耗尽 50 轮。

进入完整七题复测前，三题结果必须满足：

1. `openai-1636` 继续 resolved。
2. 两道基线失败题至少新增一道 resolved，或两题的 FAIL_TO_PASS 失败数均明显下降且已形成完整调用链补丁。
3. 三题合计输入 tokens 或 Agent 耗时至少下降 10%。
4. 不出现新增 PASS_TO_PASS 回归。

如果未达到门槛，只根据日志做一次提示调整后复测三题，不直接消耗完整七题预算。

## Optional Runtime Verification Guard

此前 1633 canary 表明，运行时验证闸门虽然能拦截未验证收尾，但会引入拒绝/重试和工具识别开销，未改善该题 resolved。因此它降为可选诊断能力：配置中的 `agent_guard.verification_gate` 控制验证闸门，`agent_guard.protect_test_edits` 控制测试文件编辑保护；两者默认关闭，下一轮主评测不启用。

Agent 状态保存 `pending_verification`、受影响生产路径和最近一次验证状态。Edit/Write 成功修改生产源文件后设置待验证状态；Bash 成功执行测试、导入、编译或最小复现命令后清除状态，非零验证结果保留状态并把失败交给下一轮处理。模型在待验证状态下返回无工具调用的最终文本时，循环不发出 `done(final)`，而是追加一条高优先级验证反馈并继续请求；达到迭代上限时保留 `max_iterations`，日志可观察到未完成验证。

待验证状态会作为短动态 Prompt 模块注入，列出受影响路径并要求下一次工具调用优先验证。测试路径识别集中在 Agent 辅助函数中；启用保护时，Write/Edit 在真正写盘前返回结构化拒绝。Edit 的 `multiple_matches` 错误补充匹配行号和短上下文，减少重复失败调用。

该改动不依赖题目、仓库或答案内容，不改变 Provider 协议和默认工具权限；验证命令识别只用于评测闭环提示，不代替 harness 判分。

## File Organization

```text
Huicode/
├── huicode/
│   ├── prompts/
│   │   ├── base.py                 # 执行阶段类型
│   │   ├── builder.py              # 阶段判定和动态进度提示
│   │   ├── modules.py              # 稳定提示去重
│   │   └── tools.py                # Tool Schema 描述去重
│   ├── agent_guard.py              # 评测验证状态、路径和命令识别
│   ├── agent.py                    # 运行时验证闸门接入
│   ├── agent_events.py             # AgentState 验证状态
│   ├── config.py                   # agent_guard 配置
│   └── tools/files.py               # 测试文件编辑保护和 Edit 位置反馈
│   └── subagents/
│       └── tool.py                 # Agent 工具合法形态与纠错反馈
├── scripts/
│   └── swebench_metrics.py         # 评测指标汇总 CLI
├── tests/
│   ├── test_prompt_builder.py      # 阶段边界和动态提示
│   ├── test_prompt_modules.py      # 精简后稳定约束
│   ├── test_prompt_tools.py        # 工具描述不重复
│   ├── test_subagent_tool.py       # 可纠正的结构化错误
│   └── test_swebench_metrics.py    # 日志/report 汇总
└── specs/
    └── swebench-fast-lift/
        ├── spec.md
        └── plan.md
```

## Technical Decisions

| Decision Point | Choice | Rationale |
| --- | --- | --- |
| 提升路径 | 提示构建层最小改造 | 不触碰 Provider 和执行器，开发与回归风险最低 |
| 轮次控制 | 动态提示，不硬切断工具 | 直接降低 50 轮可能使现有通过题失分 |
| 阶段阈值 | 30%/70%/90% 比例 | 适配不同最大轮次，同时给实现和验证保留预算 |
| 短任务兼容 | 最大轮次小于 20 时禁用 | 避免简单问答和短子任务被过度流程化 |
| 接口传播 | 在实现和验证阶段明确检查 | 直接针对 a2a-443 失败模式，且对普通任务成本很低 |
| 提示精简 | 去除 Tool Schema 中通用规则复制 | 同一请求每个工具都重复规则，收益稳定且风险可控 |
| Agent 工具纠错 | 保持错误码，增加 details 和合法示例 | 不破坏调用方，同时让模型下一轮能直接修正 |
| 指标工具 | 标准库独立脚本 | 不引入运行时依赖，不耦合 harness 内部实现 |
| 评测顺序 | 3 题筛选后 7 题确认 | 最快获得信号并控制 API 成本 |
| 模型控制 | 保持 gpt-5.6-sol/high | 隔离 Agent 改动带来的真实效果 |
| 运行时闭环 | 配置化状态闸门，默认关闭 | 让评测具备硬验证约束，同时不改变普通会话语义 |
| 测试文件保护 | 在评测配置下由 Write/Edit 在写盘前拒绝 | 避免模型通过改测试文件掩盖目标失败，并保留读取测试的能力 |

## First-Gate Follow-up

首轮 quick gate 为 1/3，失败日志显示一个任务直到迭代上限才首次修改生产代码，另一个任务修改后未及时运行目标测试。因此只执行一次提示层跟进：将 20% 边界（50 轮时为第 10 轮）视为实现闸门；若尚未产生生产代码改动，下一次工具调用必须进入 Edit/Write；首次生产改动后两轮内运行目标测试，并明确禁止先修改测试文件。跟进仍保持模型、强度、工具和评测规则不变；若第二次 quick gate 仍低于 2/3，则不启动完整七题评测。

运行时闸门 canary 已完成并失败，后续不再作为进入三题复测的前置条件。主执行顺序改由下方“三轮实施修订”定义。

## Three-Round Implementation Amendment

本节优先于前文旧的 T11R/T11R2 顺序。

### Round 1 — 成本与执行纪律

- `PromptInjectionPolicy` 默认降低完整执行指令重发频率；长计划做有界摘要，Skill/Agent 目录只在首轮和低频检查点完整注入。
- `PromptContext` 携带本轮只读调用、生产编辑和最近验证计数；实现截止点、修改后验证和后段收尾提示根据计数增强，但不默认拒绝工具。
- 评测配置关闭 `agent_guard`，把子任务前台等待和后台并发调回短、可控值；保留完整日志和每题指标。

### Round 2 — 复杂任务成功率

- 只在 Round 1 通过成本/已通过题保护门槛后实施。
- 对公共接口变更形成“定义 → 实现 → 直接调用方 → mock/兼容调用 → 目标测试”的短闭环提示。
- 对失败验证要求最小生产修正和目标测试重跑；不引入题目特定规则，不改测试文件。

### Round 3 — 评测决策

- 先跑 `1633`、`443`、`1636` 三题，检查 `1636` 不回退、无新增 PASS_TO_PASS 回归、三题 token 或耗时至少下降 10%。
- Round 2 若带来质量正向信号，再跑七道 gold 有效题；否则根据日志只做一次小调整，不启动完整评测。
- 所有轮次使用同一模型、强度、任务文本、封存副本和补丁过滤规则。
