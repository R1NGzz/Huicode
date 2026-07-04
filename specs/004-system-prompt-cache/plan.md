# HuiCode 结构化系统提示与缓存策略技术方案

## 架构概览

本阶段新增一层 Prompt 组装模块，位于 Agent 与 Provider 之间。Agent 每轮请求模型前，根据当前 workspace、任务模式、迭代轮次、工具集合和会话状态构造 `PromptBundle`；Provider 接收同一个 `PromptBundle`，再分别序列化为 OpenAI 兼容协议或 Anthropic 兼容协议能理解的请求结构。

稳定系统提示由固定模块和可选模块组成，顺序固定、内容可复用。动态信息不拼进稳定提示，而是通过系统级补充块注入，例如当前工作目录、平台、当前时间、任务模式、轮次指令和最近计划摘要。这样稳定前缀和工具描述尽量保持不变，给供应商自动缓存或显式缓存控制留下空间。

工具系统继续由 registry 提供工具列表，但工具描述会经过增强层补充关键约束。例如 `Edit` 描述会强调编辑前必须读文件、原文必须唯一匹配；`Bash` 描述会强调只在 workspace 内执行、优先使用专用文件/搜索工具。增强后的工具描述作为稳定内容输出给 Provider。

usage 解析从“原样透传供应商 usage”升级为“原样保留 + 归一化缓存字段”。TUI 仍消费 `usage` 事件，`/verbose` 复用现有开关显示 token 与缓存相关统计。

## 核心数据结构和接口

### `PromptModule`

```python
@dataclass(frozen=True)
class PromptModule:
    name: str
    title: str
    content: str
    priority: int
    stable: bool = True
    optional: bool = False
    cache_hint: bool = True
```

作用：表示一段系统提示模块。固定模块 `stable=True`；环境信息、轮次补充和模式提示 `stable=False`。

### `PromptBundle`

```python
@dataclass(frozen=True)
class PromptBundle:
    stable_modules: list[PromptModule]
    dynamic_modules: list[PromptModule]
    supplemental_modules: list[PromptModule]
```

作用：Provider 请求的系统级提示输入。Provider 可以按协议把稳定模块、动态模块和补充模块序列化为 top-level system、system message 或其他兼容形态。

### `PromptContext`

```python
@dataclass(frozen=True)
class PromptContext:
    workspace: Path
    platform: str
    shell: str
    now: datetime
    mode: AgentMode
    iteration: int
    max_iterations: int
    read_only_tool_names: frozenset[str]
    last_plan: str = ""
```

作用：生成环境模块和会话级指令。所有频繁变化的信息都从这里进入动态模块。

### `PromptInjectionPolicy`

```python
@dataclass(frozen=True)
class PromptInjectionPolicy:
    full_first_turn: bool = True
    repeat_every: int = 4
```

作用：控制 Plan Mode、Do Mode 等会话级提示的注入强度。每个用户请求的第 1 个模型轮次使用完整提示；之后每隔 `repeat_every` 轮重复关键约束；其他轮次只放精简标签。

### `CacheUsage`

```python
@dataclass(frozen=True)
class CacheUsage:
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cached_tokens: int = 0
```

作用：从供应商 usage 中提取缓存相关字段。保留原始 usage，同时额外提供统一的 `cache` 摘要。

### Provider 接口调整

```python
class Provider(Protocol):
    def stream_chat(
        self,
        messages: list[ConversationMessage],
        tools: list[ToolSpec] | None = None,
        allow_tool_calls: bool = True,
        prompt: PromptBundle | None = None,
    ) -> Iterator[StreamEvent]:
        ...
```

兼容策略：`prompt=None` 时保持旧行为，现有测试和旧调用不需要一次性全部重写。

### 工具描述增强接口

```python
def enhance_tool_specs(specs: list[ToolSpec]) -> list[ToolSpec]:
    ...
```

作用：在 registry 输出 specs 后补充规则，保持原工具实现不变。

## 模块设计

### `huicode.prompts.base`

**职责：** 定义 `PromptModule`、`PromptBundle`、`PromptContext`、`PromptInjectionPolicy`、`CacheUsage` 等结构。

**外部接口：** 提供数据类型，不直接依赖 Provider。

### `huicode.prompts.modules`

**职责：** 定义七个固定模块和三个可选模块槽位。

固定模块顺序：

```text
10 identity
20 system_constraints
30 task_mode
40 action_execution
50 tool_usage
60 tone_style
70 text_output
80 environment
```

可选模块顺序：

```text
90 custom_instructions
100 active_skills
110 long_term_memory
```

### `huicode.prompts.builder`

**职责：** 根据 `PromptContext` 和 `PromptInjectionPolicy` 生成 `PromptBundle`。

**核心函数：**

```python
def build_prompt_bundle(context: PromptContext, policy: PromptInjectionPolicy) -> PromptBundle:
    ...
```

行为：

- 固定稳定模块每次内容一致。
- 环境模块使用 `<huicode_context type="environment" scope="turn">...</huicode_context>`。
- Plan Mode 使用 `<huicode_instruction type="plan_mode" scope="turn">...</huicode_instruction>`。
- Do Mode 使用 `<huicode_instruction type="execution_mode" scope="turn">...</huicode_instruction>`。
- 可选模块本阶段保留空槽位或占位标题，不加载外部内容。

### `huicode.prompts.tools`

**职责：** 增强工具描述。

增强规则：

- `Read`：强调读取 UTF-8 文本文件，分析或编辑前优先读取相关文件。
- `Find`/`Search`：强调查找文件和搜索内容优先使用专用工具，不要用命令替代简单搜索。
- `Write`：强调会覆盖目标内容，写入前确认目标路径和完整内容。
- `Edit`：强调编辑前必须读取文件，`old_text` 必须唯一匹配。
- `Bash`：强调只在需要命令时使用，文件读写搜索优先使用专用工具。

### `huicode.prompts.cache`

**职责：** 归一化缓存 usage 字段。

**核心函数：**

```python
def normalize_cache_usage(usage: dict[str, Any]) -> dict[str, Any]:
    ...
```

支持字段：

- Anthropic/DeepSeek 常见字段：`cache_creation_input_tokens`、`cache_read_input_tokens`
- OpenAI 常见字段：`prompt_tokens_details.cached_tokens`
- 其他供应商原样保留，不存在时返回空 cache 摘要

### `huicode.agent`

**职责变化：** 在每轮 `provider.stream_chat` 前创建 `PromptContext`，调用 prompt builder，并把增强后的工具 specs 和 `PromptBundle` 一起传给 Provider。

影响点：

- `run_agent_loop` 创建每轮上下文。
- `select_tools` 返回增强后的工具 specs。
- `collect_model_response` 接收并透传 `PromptBundle`。
- `usage` 事件中包含归一化缓存摘要。

### `huicode.providers.openai`

**职责变化：** 支持 `prompt` 参数。

序列化策略：

- 稳定模块序列化为请求最前面的 system message。
- 动态模块和补充模块序列化为紧随其后的 system message。
- 历史消息保持在系统消息之后。
- 工具描述使用增强后的 `ToolSpec`。
- OpenAI 若返回 `prompt_tokens_details.cached_tokens`，由 usage 解析进入缓存摘要。

### `huicode.providers.anthropic`

**职责变化：** 支持 `prompt` 参数。

序列化策略：

- 稳定模块序列化为 top-level `system` 内容块。
- 动态模块和补充模块追加到同一个 top-level `system` 列表中，但不与稳定模块合并成同一块。
- 若兼容端支持显式缓存控制，则稳定模块和工具描述可带 cache hint；若兼容端忽略该字段，应保持请求可用。
- 历史消息仍通过 `messages` 字段发送，tool_use/tool_result 结构保持上一章修复后的形态。
- `cache_creation_input_tokens` 和 `cache_read_input_tokens` 进入 usage 缓存摘要。

### `huicode.tui`

**职责变化：** usage 渲染增加缓存字段摘要。

示例：

```text
tokens: input_tokens=1000, output_tokens=80, cache_read_input_tokens=800
```

现有 `show_usage` 和 `/verbose` 继续控制是否显示。

### `docs/evals`

本阶段不做自动评估，只创建人工对比场景文档：

```text
specs/004-system-prompt-cache/manual_eval_scenarios.md
```

覆盖六类场景：入口文件分析、编辑前读取、Plan Mode 只读规划、工具优先使用、错误工具结果修正、输出风格稳定性。

## 模块交互和数据流

1. 用户输入普通请求、`/plan` 或 `/do`。
2. CLI 维持现有模式状态和 `/verbose` 开关。
3. Agent 进入某一轮模型调用。
4. Agent 创建 `PromptContext`，包含 workspace、平台、当前时间、模式、迭代数、最近计划等。
5. Prompt builder 生成 `PromptBundle`。
6. registry 输出工具 specs，工具描述增强层返回增强后的 specs。
7. Agent 调用 Provider：`messages + tools + prompt`。
8. Provider 按协议序列化系统提示、动态补充、历史消息和工具。
9. SSE 返回 text/thinking/tool_call/usage。
10. usage 经过缓存字段归一化后作为 `AgentEvent(kind="usage")` 发给 TUI。
11. Agent Loop 按原流程执行工具、回灌历史、继续下一轮。
12. `/verbose` 开启时，TUI 展示 token 和 cache 统计；关闭时静默保留事件。

## 文件组织

```text
Huicode/
├── specs/
│   └── 004-system-prompt-cache/
│       ├── spec.md
│       ├── plan.md
│       ├── task.md
│       ├── checklist.md
│       ├── manual_eval_scenarios.md
│       └── acceptance_report.md
├── huicode/
│   ├── agent.py
│   ├── agent_events.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── openai.py
│   │   └── anthropic.py
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── modules.py
│   │   ├── builder.py
│   │   ├── tools.py
│   │   └── cache.py
│   ├── tools/
│   │   └── registry.py
│   └── tui.py
└── tests/
    ├── test_prompt_modules.py
    ├── test_prompt_builder.py
    ├── test_prompt_tools.py
    ├── test_prompt_cache.py
    ├── test_openai_provider_prompts.py
    ├── test_anthropic_provider_prompts.py
    └── existing tests...
```

## 技术决策

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 提示层位置 | Agent 和 Provider 之间新增 `huicode.prompts` | Agent 管业务状态，Provider 管协议序列化，提示组装独立可测。 |
| 系统提示结构 | `PromptBundle` 拆 stable/dynamic/supplemental | 明确缓存边界，避免动态内容污染稳定提示。 |
| 动态补充形式 | 使用 `<huicode_context>` 和 `<huicode_instruction>` 标签 | 模型能识别为系统上下文，不会误认为用户提问。 |
| Provider 接口 | `stream_chat(..., prompt=None)` 兼容扩展 | 旧测试、旧调用可逐步迁移，降低改动风险。 |
| OpenAI 系统提示 | 前置 system messages | 与当前 Chat Completions 风格最兼容。 |
| Anthropic 系统提示 | top-level `system` 内容块 | 保持 messages 历史干净，也符合 tool_result 紧跟 tool_use 的结构约束。 |
| 缓存控制 | 抽象 cache hint，Provider 支持则应用，不支持则降级 | 不把 HuiCode 绑定到某一家缓存字段或兼容端行为。 |
| 工具规则强化 | 全局提示 + 工具描述双重强化 | 提高模型在工具选择时看到关键约束的概率。 |
| Plan/Do 注入频率 | 首轮完整、每 4 轮重复、其余精简 | 在遵守率和上下文占用之间取保守平衡。 |
| 缓存观测 | usage 原样保留并增加 cache 摘要 | 不丢供应商细节，又给 TUI 一个稳定显示口径。 |
| 人工评估 | 文档化场景，不做自动评分 | 满足本阶段范围，给后续自动评估留素材。 |

## 需求覆盖自检

- F1-F4：由 `PromptModule`、`PromptBundle`、`huicode.prompts.modules` 覆盖。
- F5-F10：由 stable/dynamic/supplemental 分层、特殊标签和 Provider `prompt` 参数覆盖。
- F11-F12：由固定工具使用模块和 `enhance_tool_specs` 覆盖。
- F13-F16：由 `PromptInjectionPolicy` 和 Plan/Do 模式动态模块覆盖。
- F17：由 Provider 接口扩展和 OpenAI/Anthropic 序列化策略覆盖。
- F18-F20：由 `normalize_cache_usage`、usage 事件和现有 `/verbose` 覆盖。
- F21：通过兼容 `prompt=None`、保留现有消息历史和全量回归测试覆盖。
- F22：由 `manual_eval_scenarios.md` 覆盖。
- F23：通过文件组织和范围控制明确不实现。
