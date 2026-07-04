# 004 结构化系统提示与缓存策略验收报告

## 结论

已完成本章目标：HuiCode 现在会按模块构建结构化系统提示，区分稳定提示与动态运行信息，按轮次注入 Plan/Do 补充指令，增强工具描述，并归一化 Provider usage 中的缓存字段。

## 已完成项

- 新增 `huicode.prompts` 包，包含 Prompt 数据结构、固定模块、Builder、工具描述增强和缓存 usage 归一化。
- Agent Loop 每轮都会构建 `PromptContext` 和 `PromptBundle`，并传给 Provider。
- OpenAI 兼容协议会把 PromptBundle 序列化为前置 `system` messages。
- Anthropic/DeepSeek Anthropic 兼容协议会把 PromptBundle 序列化为 top-level `system` 内容块。
- 工具描述中强化“优先用专用工具”“编辑前必须先读”“不要编造工具结果”“遵守 workspace 边界”等规则。
- usage 事件会保留原始字段，并补充统一 `cache` 摘要。
- TUI `/verbose` 输出会展示 `cache_creation_input_tokens`、`cache_read_input_tokens` 和 `cached_tokens`。
- README 已补充结构化系统提示、缓存 usage 可观测和阶段边界。
- 已创建人工评估场景文档。

## 验证记录

```text
python -m unittest discover -v
结果：92 tests OK
```

```text
python -m compileall -q huicode tests
结果：通过
```

```text
Get-Command tmux -ErrorAction SilentlyContinue
结果：tmux 不可用
```

## 缓存命中验证说明

真实缓存命中依赖具体供应商 API 返回 usage 字段。本地测试覆盖了字段解析和展示：

- Anthropic/DeepSeek Anthropic 兼容：`cache_creation_input_tokens`、`cache_read_input_tokens`
- OpenAI 兼容：`prompt_tokens_details.cached_tokens`

当前实现未强制向 DeepSeek Anthropic 兼容接口加入 `cache_control`，以避免兼容层不支持该字段时造成请求失败。稳定系统提示仍固定排在请求前部，便于后续在确认供应商支持后启用更强缓存控制。

## 未覆盖或后续项

- 未做真实 API 人工对比，需要按 `manual_eval_scenarios.md` 在有网络和密钥的环境执行。
- 未做项目指令文件加载、自动记忆、真实 MCP 接入和自动化评估。
- 未做权限系统、上下文压缩、用户交互式确认。
