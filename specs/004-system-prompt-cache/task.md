# HuiCode 结构化系统提示与缓存策略实施任务

## 文件清单

| 动作 | 文件 | 职责 |
| --- | --- | --- |
| 创建 | `huicode/prompts/__init__.py` | 暴露 Prompt 相关公共类型和构建函数。 |
| 创建 | `huicode/prompts/base.py` | 定义 `PromptModule`、`PromptBundle`、`PromptContext`、`PromptInjectionPolicy`、`CacheUsage`。 |
| 创建 | `huicode/prompts/modules.py` | 定义固定系统提示模块、可选模块槽位和模块渲染逻辑。 |
| 创建 | `huicode/prompts/builder.py` | 根据运行上下文构建稳定、动态、补充提示包。 |
| 创建 | `huicode/prompts/tools.py` | 增强工具描述中的关键使用规则。 |
| 创建 | `huicode/prompts/cache.py` | 归一化供应商 usage 中的缓存相关字段。 |
| 修改 | `huicode/providers/base.py` | 扩展 Provider 接口，支持 `PromptBundle` 参数和缓存 usage 摘要。 |
| 修改 | `huicode/providers/openai.py` | 序列化 OpenAI 兼容系统提示，解析 OpenAI 缓存 usage 字段。 |
| 修改 | `huicode/providers/anthropic.py` | 序列化 Anthropic 兼容 top-level system，解析 Anthropic/DeepSeek 缓存 usage 字段。 |
| 修改 | `huicode/agent.py` | 每轮构建 PromptContext、增强工具 specs、透传 PromptBundle、归一化 usage。 |
| 修改 | `huicode/tui.py` | usage 输出支持缓存字段摘要。 |
| 修改 | `README.md` | 说明结构化系统提示、缓存可观测和人工评估场景。 |
| 创建 | `specs/004-system-prompt-cache/manual_eval_scenarios.md` | 记录六类人工对比场景。 |
| 创建 | `specs/004-system-prompt-cache/acceptance_report.md` | 记录本阶段验收结果。 |
| 创建 | `tests/test_prompt_modules.py` | 覆盖固定模块顺序、分隔和可选模块槽位。 |
| 创建 | `tests/test_prompt_builder.py` | 覆盖动态环境信息、特殊标签、Plan/Do 注入频率。 |
| 创建 | `tests/test_prompt_tools.py` | 覆盖工具描述增强规则。 |
| 创建 | `tests/test_prompt_cache.py` | 覆盖缓存 usage 字段归一化。 |
| 创建 | `tests/test_openai_provider_prompts.py` | 覆盖 OpenAI 系统提示和 usage 缓存字段序列化/解析。 |
| 创建 | `tests/test_anthropic_provider_prompts.py` | 覆盖 Anthropic system 内容块、thinking/tool_result 兼容和缓存 usage。 |
| 修改 | 现有 `tests/test_agent*.py`、`tests/test_cli.py`、`tests/test_tui.py` | 适配新 Provider 参数和 usage 输出。 |

## T1: 定义 Prompt 基础数据结构

**文件：** `huicode/prompts/__init__.py`、`huicode/prompts/base.py`、`tests/test_prompt_modules.py`

**依赖：** 已批准的 `spec.md`、`plan.md`

**步骤：**
1. 创建 `huicode/prompts` 包。
2. 定义 `PromptModule`、`PromptBundle`、`PromptContext`、`PromptInjectionPolicy`、`CacheUsage`。
3. 给 `PromptBundle` 增加便于测试的模块名列表或渲染辅助方法。
4. 在 `__init__.py` 暴露公共类型。
5. 添加默认值测试，确认 `PromptInjectionPolicy.repeat_every=4`。

**验证：** 运行 `python -m unittest tests.test_prompt_modules -v`；预期全部通过。

## T2: 实现固定模块与可选模块槽位

**文件：** `huicode/prompts/modules.py`、`tests/test_prompt_modules.py`

**依赖：** T1

**步骤：**
1. 定义七个固定模块：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。
2. 定义环境模块生成函数，但标记为动态模块。
3. 定义三个可选模块槽位：自定义指令、已激活 Skill、长期记忆。
4. 实现模块排序和分隔渲染。
5. 测试模块顺序符合优先级，且模块之间存在清晰分隔。
6. 测试可选模块槽位存在，但默认不加载真实内容。

**验证：** 运行 `python -m unittest tests.test_prompt_modules -v`；预期全部通过。

## T3: 实现 Prompt Builder 和动态补充指令

**文件：** `huicode/prompts/builder.py`、`tests/test_prompt_builder.py`

**依赖：** T1、T2

**步骤：**
1. 实现 `build_prompt_bundle(context, policy)`。
2. 生成 `<huicode_context type="environment" scope="turn">` 环境模块。
3. 环境模块包含 workspace、platform、shell、now、mode、iteration、max_iterations、可用能力摘要。
4. Plan Mode 生成 `<huicode_instruction type="plan_mode" scope="turn">`。
5. Do Mode 生成 `<huicode_instruction type="execution_mode" scope="turn">`。
6. 实现首轮完整、每 4 轮重复关键约束、其余精简的注入策略。
7. 测试当前时间和 workspace 只出现在动态模块，不改变稳定模块内容。
8. 测试 Plan/Do 注入频率和标签格式。

**验证：** 运行 `python -m unittest tests.test_prompt_builder -v`；预期全部通过。

## T4: 增强工具描述

**文件：** `huicode/prompts/tools.py`、`tests/test_prompt_tools.py`

**依赖：** T1

**步骤：**
1. 实现 `enhance_tool_specs(specs)`。
2. 针对 `Read`、`Find`、`Search`、`Write`、`Edit`、`Bash` 增加规则补充。
3. 保持工具 name、parameters 不变。
4. 确认增强函数不修改输入对象。
5. 测试 `Edit` 描述包含编辑前读取和唯一匹配约束。
6. 测试 `Bash` 描述包含优先使用专用工具和 workspace 边界约束。

**验证：** 运行 `python -m unittest tests.test_prompt_tools -v`；预期全部通过。

## T5: 实现缓存 usage 归一化

**文件：** `huicode/prompts/cache.py`、`tests/test_prompt_cache.py`

**依赖：** T1

**步骤：**
1. 实现 `normalize_cache_usage(usage)`。
2. 支持 Anthropic/DeepSeek 字段：`cache_creation_input_tokens`、`cache_read_input_tokens`。
3. 支持 OpenAI 字段：`prompt_tokens_details.cached_tokens`。
4. 保留原始 usage 字段，并增加统一 `cache` 摘要。
5. 不存在缓存字段时返回空 cache 摘要，不报错。

**验证：** 运行 `python -m unittest tests.test_prompt_cache -v`；预期全部通过。

## T6: 扩展 Provider 基础接口

**文件：** `huicode/providers/base.py`、相关 provider 测试

**依赖：** T1

**步骤：**
1. 在 `Provider.stream_chat` 协议中增加 `prompt: PromptBundle | None = None`。
2. 避免运行时循环 import；必要时使用 `TYPE_CHECKING`。
3. 保持 `prompt=None` 时旧调用兼容。
4. 调整测试替身 Provider 的函数签名。

**验证：** 运行 `python -m unittest tests.test_agent tests.test_agent_loop -v`；预期全部通过。

## T7: 接入 OpenAI 兼容系统提示

**文件：** `huicode/providers/openai.py`、`tests/test_openai_provider_prompts.py`、`tests/test_openai_provider_tools.py`

**依赖：** T3、T5、T6

**步骤：**
1. 给 `OpenAIProvider.stream_chat` 增加 `prompt` 参数。
2. 将稳定模块序列化为最前面的 system message。
3. 将动态模块和补充模块序列化为后续 system message。
4. 历史 messages 保持在 system messages 之后。
5. 工具 specs 继续按 OpenAI function tool 结构序列化。
6. 对 usage 调用 `normalize_cache_usage`。
7. 添加测试确认 system message 顺序、标签内容和历史消息位置。
8. 添加测试确认 OpenAI `cached_tokens` 被归一化。

**验证：** 运行 `python -m unittest tests.test_openai_provider_prompts tests.test_openai_provider_tools -v`；预期全部通过。

## T8: 接入 Anthropic 兼容系统提示

**文件：** `huicode/providers/anthropic.py`、`tests/test_anthropic_provider_prompts.py`、`tests/test_anthropic_provider_tools.py`

**依赖：** T3、T5、T6

**步骤：**
1. 给 `AnthropicProvider.stream_chat` 增加 `prompt` 参数。
2. 将稳定模块序列化为 top-level `system` 内容块。
3. 将动态模块和补充模块追加为独立 system 内容块。
4. 保持 `messages` 历史不混入动态系统提示。
5. 保持上一章多 tool_result 合并和 thinking signature 回传行为。
6. 对 usage 调用 `normalize_cache_usage`。
7. 添加测试确认 system 内容块顺序、动态标签、历史消息结构。
8. 添加测试确认 `cache_creation_input_tokens` 和 `cache_read_input_tokens` 被归一化。

**验证：** 运行 `python -m unittest tests.test_anthropic_provider_prompts tests.test_anthropic_provider_tools -v`；预期全部通过。

## T9: Agent 接入 PromptBundle 与增强工具 specs

**文件：** `huicode/agent.py`、`tests/test_agent_loop.py`、`tests/test_agent.py`

**依赖：** T3、T4、T6-T8

**步骤：**
1. 在每轮模型请求前创建 `PromptContext`。
2. 将 workspace、platform、shell、当前时间、mode、iteration、max_iterations、read_only_tool_names、last_plan 写入上下文。
3. 调用 `build_prompt_bundle` 并传给 Provider。
4. `select_tools` 返回 `enhance_tool_specs(registry.to_specs(...))`。
5. `collect_model_response` 接收 `prompt` 并传给 Provider。
6. usage 事件保留归一化后的 usage 数据。
7. 更新测试替身 Provider，断言收到 prompt 和增强后的工具描述。

**验证：** 运行 `python -m unittest tests.test_agent_loop tests.test_agent -v`；预期全部通过。

## T10: TUI usage 展示缓存统计

**文件：** `huicode/tui.py`、`tests/test_tui.py`

**依赖：** T5

**步骤：**
1. 更新 usage 渲染摘要，优先展示原始 token 字段和 `cache` 摘要字段。
2. 缓存字段不存在时保持当前输出风格。
3. 添加测试覆盖 `cache_creation_input_tokens`、`cache_read_input_tokens`、`cached_tokens` 输出。
4. 确认 `/verbose` 仍由 CLI 控制是否渲染 usage 事件。

**验证：** 运行 `python -m unittest tests.test_tui tests.test_cli -v`；预期全部通过。

## T11: 编写人工对比场景与 README

**文件：** `specs/004-system-prompt-cache/manual_eval_scenarios.md`、`README.md`

**依赖：** T9、T10

**步骤：**
1. 创建人工对比场景文档。
2. 覆盖入口文件分析、编辑前读取、Plan Mode 只读规划、工具优先使用、错误工具结果修正、输出风格稳定性。
3. 每个场景写明输入、期望工具行为、期望输出倾向和观察记录位。
4. README 增加结构化系统提示和缓存 usage 可观测说明。
5. 明确本阶段不做项目指令文件、自动记忆、真实 MCP 和自动化评估。

**验证：** 阅读 `manual_eval_scenarios.md` 和 `README.md`，确认与 spec 范围一致。

## T12: 完整测试、编译检查和验收报告

**文件：** 全部实现文件、`specs/004-system-prompt-cache/acceptance_report.md`

**依赖：** T1-T11

**步骤：**
1. 运行全量单元测试。
2. 运行 Python 编译检查。
3. 修复所有失败。
4. 记录哪些验收项已通过。
5. 若无法做真实 API 缓存命中验证，在报告中记录环境限制和替代测试证据。

**验证：** 运行 `python -m unittest discover -v` 和 `python -m compileall -q huicode tests`；预期全部通过，并生成验收报告。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12
```

## 任务自检

- Prompt 数据结构和模块由 T1-T3 覆盖。
- 工具描述双重强化由 T4 和 T9 覆盖。
- 缓存 usage 解析由 T5、T7、T8、T10 覆盖。
- Provider 请求适配由 T6-T8 覆盖。
- Agent 接入由 T9 覆盖。
- 人工评估场景由 T11 覆盖。
- 完整回归和验收报告由 T12 覆盖。
