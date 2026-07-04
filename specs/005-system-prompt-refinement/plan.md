# HuiCode 系统提示词完善 Plan

## Architecture Overview

本次变更保持现有 Prompt 架构不变：`PromptModule` 仍是最小系统提示单元，`fixed_prompt_modules()` 继续返回七个固定稳定模块，`build_prompt_bundle()` 继续把稳定模块、动态环境模块和轮次补充指令拆开交给 Provider。变更重点是重写固定模块内容，并补充测试保证关键规则存在。

## Core Data Structures

### PromptModule

继续使用现有结构：

```python
PromptModule(
    name: str,
    content: str,
    stable: bool = True,
    cacheable: bool = True,
)
```

本次不新增字段。模块内容更新为 UTF-8 中文长文本。

### FIXED_MODULE_NAMES

继续保留七个固定模块名：

```python
(
    "identity",
    "system_constraints",
    "task_mode",
    "action_execution",
    "tool_usage",
    "tone_style",
    "text_output",
)
```

其中参考截图里的语义映射如下：

| 截图层 | HuiCode 模块 |
| --- | --- |
| Identity | `identity` |
| System | `system_constraints` |
| DoingTasks | `task_mode` + `action_execution` |
| ExecutingActions | `action_execution` |
| UsingTools | `tool_usage` |
| ToneStyle | `tone_style` |
| TextOutput | `text_output` |

## Module Design

### `huicode/prompts/modules.py`

**Responsibility:** 维护固定系统提示模块和可选模块槽位。

**Changes:**

- 用干净 UTF-8 中文重写七个固定模块内容。
- `identity` 强调 HuiCode 身份、任务范围和安全代码优先。
- `system_constraints` 强调用户可见输出、Markdown、URL、system-reminder、hook/事件上下文等边界。
- `task_mode` 强调普通模式、Plan Mode、Do Mode，以及模糊需求和探索性任务处理方式。
- `action_execution` 强调小步推进、编辑前读取、错误后诊断、测试验证、破坏性操作确认。
- `tool_usage` 强调 HuiCode 已有工具的正确优先级，不写不存在的工具能力。
- `tone_style` 强调中文、简洁、无 emoji、引用位置格式。
- `text_output` 强调面向用户的有用输出、工具前后短提示、最终总结短小。

### `tests/test_prompt_modules.py`

**Responsibility:** 验证固定模块顺序、分隔、可选槽位和新增关键规则。

**Changes:**

- 保留已有顺序和分隔测试。
- 增加每个模块的关键短语断言。
- 增加“不包含不存在工具名”的断言。

### `tests/test_prompt_builder.py`

**Responsibility:** 验证 PromptBundle 稳定/动态拆分与标签注入。

**Changes:**

- 保留已有动态环境、Plan/Do 注入频率测试。
- 可补充断言：稳定文本不包含动态环境标签，动态文本不包含固定模块标题。

### `README.md`

**Responsibility:** 说明系统提示词边界。

**Changes:**

- 补充“系统提示完善”说明。
- 明确提示词会约束行为，但不代表实现了截图中不存在的子 Agent、TaskCreate、真实 MCP 等能力。

### `specs/005-system-prompt-refinement/acceptance_report.md`

**Responsibility:** 记录测试证据、未执行项和边界。

**Changes:**

- 实现后创建。
- 记录单测、编译检查、tmux 可用性。

## Module Interactions

```text
fixed_prompt_modules()
  -> PromptBundle.stable_modules
  -> OpenAIProvider: system messages
  -> AnthropicProvider: top-level system blocks

build_prompt_bundle()
  -> stable modules unchanged
  -> environment dynamic module unchanged
  -> plan/do supplemental module unchanged
```

工具描述增强仍由 `huicode/prompts/tools.py` 负责，本次不改变它的接口；固定提示中的工具规则会与工具描述形成双重强化。

## File Organization

```text
Huicode/
├── huicode/
│   └── prompts/
│       ├── modules.py
│       └── builder.py
├── tests/
│   ├── test_prompt_modules.py
│   └── test_prompt_builder.py
├── specs/
│   └── 005-system-prompt-refinement/
│       ├── spec.md
│       ├── plan.md
│       ├── task.md
│       ├── checklist.md
│       └── acceptance_report.md
└── README.md
```

## Technical Decisions

| Decision Point | Choice | Rationale |
| --- | --- | --- |
| 是否新增模块名 | 不新增，复用七个固定模块 | 保持上一章结构和 Provider 序列化测试稳定 |
| 是否照搬截图文本 | 不逐字照搬，转写为 HuiCode 版本 | 避免引入 MewCode 名称和不存在能力 |
| 是否实现确认权限 | 不实现，只在提示词中要求高风险操作先确认 | 本章目标是完善提示词，不改执行机制 |
| 是否加入 TaskCreate/Agent 工具规则 | 不加入真实能力规则 | HuiCode 当前没有这些工具，避免误导模型 |
| 编码处理 | 重写相关提示文本为 UTF-8 中文 | 修复可读性和测试断言稳定性 |

## Coverage Mapping

- F1-F2 -> `identity`
- F3-F4 -> `system_constraints`
- F5 -> `task_mode`、`action_execution`
- F6 -> `action_execution`
- F7-F8 -> `tool_usage`
- F9 -> `tone_style`
- F10-F11 -> `text_output`
- F12 -> `builder` 和 Provider 回归测试
