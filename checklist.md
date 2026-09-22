# HuiCode 工具系统验收清单

> 每一项都必须通过运行测试、观察 TUI 行为或检查验收记录来验证。

## 实现完整性
- [ ] 六个核心工具已注册：读文件、写文件、改文件、执行命令、按模式找文件、搜代码内容。验证方法：运行 `python -m unittest tests.test_tools_registry -v`，观察默认注册中心测试通过。
- [ ] 每个工具都有名称、描述、参数 Schema 和执行行为。验证方法：运行 `python -m unittest tests.test_tools_registry -v`，观察工具规格测试通过。
- [ ] 读文件工具能读取 workspace 内文本文件。验证方法：运行 `python -m unittest tests.test_tools_files -v`，观察 read 成功用例通过。
- [ ] 写文件工具能写入 workspace 内文本文件。验证方法：运行 `python -m unittest tests.test_tools_files -v`，观察 write 成功用例通过。
- [ ] 改文件工具在原文唯一匹配时完成替换。验证方法：运行 `python -m unittest tests.test_tools_files -v`，观察 edit 唯一匹配用例通过。
- [ ] 改文件工具在匹配不到时不改文件并返回错误。验证方法：运行 `python -m unittest tests.test_tools_files -v`，观察 missing match 用例通过。
- [ ] 改文件工具在匹配多次时不改文件并返回错误。验证方法：运行 `python -m unittest tests.test_tools_files -v`，观察 multiple matches 用例通过。
- [ ] 执行命令工具返回退出码、stdout、stderr。验证方法：运行 `python -m unittest tests.test_tools_shell -v`，观察成功和非零退出用例通过。
- [ ] 执行命令工具超时时返回结构化超时结果。验证方法：运行 `python -m unittest tests.test_tools_shell -v`，观察 timeout 用例通过。
- [ ] 按模式找文件工具返回匹配文件列表。验证方法：运行 `python -m unittest tests.test_tools_search -v`，观察 find files 用例通过。
- [ ] 搜代码内容工具返回文件、行号和片段。验证方法：运行 `python -m unittest tests.test_tools_search -v`，观察 search code 用例通过。
- [ ] 文件类工具访问 workspace 外路径会失败。验证方法：运行 `python -m unittest tests.test_tools_files tests.test_tools_search -v`，观察路径越界用例通过。

## 集成检查
- [ ] 未知工具名返回结构化失败结果。验证方法：运行 `python -m unittest tests.test_tools_registry -v`，观察 unknown tool 用例通过。
- [ ] 工具参数不是 JSON 对象或缺少必要字段时返回结构化失败结果。验证方法：运行工具执行器相关测试，观察参数错误用例通过。
- [ ] 工具内部异常被捕获，不会让会话崩溃。验证方法：运行 `python -m unittest tests.test_tools_registry -v`，观察异常包装用例通过。
- [ ] OpenAI Provider 会把工具列表转换成 API 可识别的工具 schema。验证方法：运行 `python -m unittest tests.test_openai_provider_tools -v`，观察 schema 用例通过。
- [ ] Anthropic Provider 会把工具列表转换成 API 可识别的工具 schema。验证方法：运行 `python -m unittest tests.test_anthropic_provider_tools -v`，观察 schema 用例通过。
- [ ] OpenAI Provider 能从流式 `tool_calls` 分片中拼接完整 JSON 参数。验证方法：运行 `python -m unittest tests.test_openai_provider_tools -v`，观察 fragmented arguments 用例通过。
- [ ] Anthropic Provider 能从流式 `input_json_delta.partial_json` 分片中拼接完整 JSON 参数。验证方法：运行 `python -m unittest tests.test_anthropic_provider_tools -v`，观察 partial_json 用例通过。
- [ ] 工具调用和工具执行结果会回灌进对话历史。验证方法：运行 `python -m unittest tests.test_agent -v`，观察 history backfill 用例通过。
- [ ] 回灌历史包含工具名、参数、成功/失败状态和结果或错误。验证方法：运行 `python -m unittest tests.test_agent -v`，观察 tool result message 用例通过。
- [ ] 本阶段只执行一次工具调用回合。验证方法：运行 `python -m unittest tests.test_agent -v`，观察 second tool call not executed 用例通过。
- [ ] 无工具调用时普通聊天仍流式输出。验证方法：运行既有 provider 和 agent 文本路径测试，观察全部通过。

## TUI 检查
- [ ] 工具调用开始时显示 Claude Code 风格工具行。验证方法：运行 `python -m unittest tests.test_tui -v`，观察 `● Read(path)` 风格用例通过。
- [ ] 工具执行结束时显示简洁成功摘要。验证方法：运行 `python -m unittest tests.test_tui -v`，观察成功摘要用例通过。
- [ ] 工具执行失败时显示简洁失败摘要。验证方法：运行 `python -m unittest tests.test_tui -v`，观察失败摘要用例通过。
- [ ] CLI 中可观察到工具行和结果摘要。验证方法：运行 `python -m unittest tests.test_cli -v`，观察工具 TUI 输出用例通过。
- [ ] `/config` 仍不输出 API key。验证方法：运行 `python -m unittest tests.test_cli -v`，观察密钥不泄露用例通过。

## 构建和测试
- [ ] 所有单元测试通过。验证方法：运行 `python -m unittest discover -v`，预期全部为 `ok`。
- [ ] 项目 Python 文件可编译。验证方法：运行 `python -m compileall -q huicode tests`，预期退出码为 0。
- [ ] README 说明工具系统、六个核心工具、一次工具回合和 workspace 边界。验证方法：阅读 `README.md`，确认说明与实现一致。

## 端到端场景
- [ ] 场景 1：读取文件。验证方法：在 tmux 中启动 `python -m huicode --config huicode.yaml`，请求读取 workspace 内文件，观察出现 `● Read(...)` 和结果摘要，最终回复引用文件内容。
- [ ] 场景 2：写入文件。验证方法：请求创建一个测试文本文件，观察出现 `● Write(...)` 和成功摘要，再确认文件内容正确。
- [ ] 场景 3：唯一匹配改文件。验证方法：请求把测试文件中唯一文本替换为新文本，观察 `● Edit(...)` 成功摘要，并确认文件被正确修改。
- [ ] 场景 4：改文件失败路径。验证方法：请求替换不存在文本或多次出现文本，观察失败摘要，确认文件未被修改。
- [ ] 场景 5：执行命令。验证方法：请求运行一个无破坏命令，观察 `● Bash(...)` 或等价命令工具行、退出码和输出摘要。
- [ ] 场景 6：查找和搜索。验证方法：请求查找 `*.py` 并搜索一个已知函数名，观察工具行和匹配摘要。
- [ ] 场景 7：普通聊天。验证方法：输入不需要工具的问题，观察无工具行且普通文本仍流式输出。
- [ ] 场景 8：一次工具回合边界。验证方法：构造可能需要第二次工具调用的问题，观察本阶段不会自动执行第二次工具调用。

## 验收标准映射
- AC1: 实现完整性第 1-2 项。
- AC2: 集成检查第 1 项。
- AC3: 实现完整性第 2 项。
- AC4: 实现完整性第 3 项、端到端场景 1。
- AC5: 实现完整性第 4 项、端到端场景 2。
- AC6: 实现完整性第 5 项、端到端场景 3。
- AC7: 实现完整性第 6-7 项、端到端场景 4。
- AC8: 实现完整性第 8 项、端到端场景 5。
- AC9: 实现完整性第 9 项。
- AC10: 实现完整性第 10 项、端到端场景 6。
- AC11: 实现完整性第 11 项、端到端场景 6。
- AC12: 集成检查第 1-3 项。
- AC13: 集成检查第 4-5 项。
- AC14: 集成检查第 6-7 项。
- AC15: TUI 检查第 1 项、端到端场景 1-6。
- AC16: TUI 检查第 2-3 项、端到端场景 1-6。
- AC17: 集成检查第 8 项、端到端场景 1。
- AC18: 集成检查第 9 项。
- AC19: 集成检查第 10 项、端到端场景 8。
- AC20: 集成检查第 11 项、端到端场景 7。
- AC21: 实现完整性第 12 项。
