# HuiCode 系统提示词完善 Checklist

## Implementation Completeness

- [x] 七个固定模块仍按既定顺序输出：identity、system_constraints、task_mode、action_execution、tool_usage、tone_style、text_output。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `identity` 明确 HuiCode 是终端 AI 编程助手，并覆盖代码任务、调试、重构、解释代码、运行命令、安全代码优先。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `system_constraints` 覆盖用户可见输出、Markdown、URL 不猜测、system-reminder 不暴露、hook/事件上下文。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `task_mode` 和 `action_execution` 覆盖模糊需求、探索性问题、用户建议、错误诊断、测试验证、避免过度实现。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `action_execution` 覆盖删除、重置、发布、推送、批量修改等高风险操作先确认。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `tool_usage` 覆盖 Read/Write/Edit/Bash/Find/Search/Glob 的使用优先级。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `tool_usage` 不宣称 HuiCode 当前没有的 TaskCreate、子 Agent、真实 MCP、ToolSearch 能力。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `tone_style` 覆盖中文、简洁、默认不使用 emoji、引用位置用 `file_path:line_number`。验证：`python -m unittest tests.test_prompt_modules -v` 通过。
- [x] `text_output` 覆盖只输出有用沟通、工具前后短提示、最终一到两句总结、简单任务直接回答。验证：`python -m unittest tests.test_prompt_modules -v` 通过。

## Integration

- [x] PromptBundle 稳定模块仍不包含 `<huicode_context>` 或 `<huicode_instruction>`。验证：`python -m unittest tests.test_prompt_builder -v` 通过。
- [x] 动态环境模块仍使用 `<huicode_context type="environment" scope="turn">`。验证：`python -m unittest tests.test_prompt_builder -v` 通过。
- [x] Plan Mode 和执行模式补充指令仍按原频率注入。验证：`python -m unittest tests.test_prompt_builder -v` 通过。
- [x] OpenAI 和 Anthropic Provider prompt 序列化测试不回归。验证：`python -m unittest tests.test_openai_provider_prompts tests.test_anthropic_provider_prompts -v` 通过。
- [x] Agent Loop、工具调用、thinking/tool_result 回传不回归。验证：`python -m unittest tests.test_agent_loop tests.test_anthropic_provider_tools -v` 通过。

## Build and Tests

- [x] Prompt 相关测试通过。验证：`python -m unittest tests.test_prompt_modules tests.test_prompt_builder -v` 通过。
- [x] 全量单元测试通过。验证：`python -m unittest discover -v`，98 tests OK。
- [x] Python 编译检查通过。验证：`python -m compileall -q huicode tests` 通过。

## Documentation

- [x] README 说明系统提示词完善后的行为约束。验证：已阅读 `README.md`。
- [x] README 明确提示词不代表实现了子 Agent、TaskCreate、真实 MCP 或 ToolSearch。验证：已阅读 `README.md`。
- [x] 验收报告记录测试结果和环境限制。验证：见 `specs/005-system-prompt-refinement/acceptance_report.md`。

## End-to-End Scenarios

- [x] 场景 1：构建 PromptBundle 后，稳定系统提示中能看到七个固定模块，动态标签单独出现在 dynamic/supplemental 文本中。验证：`tests.test_prompt_builder` 通过。
- [x] 场景 2：模型在工具提示中只会看到 HuiCode 真实可用工具能力，不会被提示去调用未实现的 TaskCreate、子 Agent、真实 MCP 或 ToolSearch。验证：`tests.test_prompt_modules` 通过。
- [x] 场景 3：完整 Agent Loop 回归仍能执行工具、回灌结果并最终回答。验证：`tests.test_agent_loop` 通过。

## Environment Notes

- [x] tmux E2E 已检查但当前 Windows 环境不可用，已记录在验收报告。
