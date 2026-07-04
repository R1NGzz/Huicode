# 004 结构化系统提示与缓存策略验收清单

## 实现完整性

- [x] Prompt 基础数据结构已实现：`PromptModule`、`PromptBundle`、`PromptContext`、`PromptInjectionPolicy`、`CacheUsage`。
- [x] 固定系统提示模块已实现：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。
- [x] 环境信息作为动态模块注入，不改变稳定模块内容。
- [x] 可选模块槽位已预留：自定义指令、已激活 Skill、长期记忆。
- [x] 模块之间用清晰空行分隔，并按优先级拼装。

## 动态注入

- [x] 环境信息使用 `<huicode_context type="environment" scope="turn">` 标签。
- [x] 环境信息包含 workspace、platform、shell、now、mode、iteration、max_iterations、available_tools。
- [x] Plan Mode 使用 `<huicode_instruction type="plan_mode" scope="turn">` 标签。
- [x] Do/执行模式使用 `<huicode_instruction type="execution_mode" scope="turn">` 标签。
- [x] 首轮完整注入，每 4 轮重复关键约束，其余轮次精简注入。
- [x] 动态补充指令不写入用户消息文本。

## 工具描述

- [x] `enhance_tool_specs` 不改变工具名称和参数 schema。
- [x] `Read`、`Find`、`Search` 强化专用读类工具优先规则。
- [x] `Edit` 强化编辑前读取与唯一匹配规则。
- [x] `Write` 强化覆盖风险。
- [x] `Bash` 强化专用工具优先和 workspace 边界。
- [x] 全局提示与工具描述同时强化关键规则。

## Provider 集成

- [x] Provider 接口支持 `prompt: PromptBundle | None = None`。
- [x] `prompt=None` 的旧调用保持兼容。
- [x] OpenAI 兼容请求会把 PromptBundle 序列化为历史消息前的 system messages。
- [x] Anthropic 兼容请求会把 PromptBundle 序列化为 top-level `system` 内容块。
- [x] Anthropic 多 `tool_result` 合并和 thinking signature 回传未回归。
- [x] Agent 每轮都会构建 PromptBundle 并传给 Provider。

## 缓存与 Usage

- [x] Anthropic/DeepSeek 字段 `cache_creation_input_tokens`、`cache_read_input_tokens` 会归一化到 `cache` 摘要。
- [x] OpenAI 字段 `prompt_tokens_details.cached_tokens` 会归一化到 `cache` 摘要。
- [x] 不存在缓存字段时正常降级，不报错。
- [x] `/verbose` 开启时 TUI 能显示 token 与缓存统计。
- [x] usage 输出和配置展示不泄露 API key。

## 文档与人工场景

- [x] README 已说明结构化系统提示、动态补充指令、缓存 usage 可观测和阶段边界。
- [x] `manual_eval_scenarios.md` 已覆盖入口文件分析、编辑前读取、Plan Mode 只读、工具优先、缓存 usage、输出风格。
- [x] `acceptance_report.md` 已记录测试证据和环境限制。

## 验证

- [x] `python -m unittest discover -v` 通过，92 tests OK。
- [x] `python -m compileall -q huicode tests` 通过。
- [x] tmux E2E 已检查但当前 Windows 环境不可用，见 `acceptance_report.md`。

## 本阶段明确不做

- [x] 不做项目指令文件加载。
- [x] 不做自动记忆。
- [x] 不做真实 MCP 接入。
- [x] 不做自动化评估。
- [x] 不做权限系统、上下文压缩、用户交互式确认。
