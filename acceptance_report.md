# HuiCode 工具系统验收报告

## 已通过
- [x] 项目可编译。证据：`python -m compileall -q huicode tests` 退出码为 0。
- [x] 全部单元测试通过。证据：`python -m unittest discover -v` 运行 37 个测试，全部 `ok`。
- [x] 六个核心工具已实现并注册。证据：`tests.test_tools_registry` 验证默认注册中心包含 `Read`、`Write`、`Edit`、`Bash`、`Find`、`Search`。
- [x] 文件工具可读、写、唯一匹配替换，并拒绝 workspace 外路径。证据：`tests.test_tools_files` 全部通过。
- [x] 改文件在匹配不到或匹配多次时不修改文件并返回结构化错误。证据：`tests.test_tools_files` 覆盖 missing 和 multiple matches。
- [x] 搜索工具可按模式找文件和搜索代码内容。证据：`tests.test_tools_search` 全部通过。
- [x] 命令工具返回退出码、stdout、stderr，并支持超时。证据：`tests.test_tools_shell` 全部通过。
- [x] 未知工具和工具异常会被包装成结构化失败结果。证据：`tests.test_tools_registry` 覆盖 unknown tool 和 exception wrapping。
- [x] OpenAI Provider 可发送工具 schema、拼接流式工具调用 JSON 参数、序列化工具历史。证据：`tests.test_openai_provider_tools` 全部通过。
- [x] Anthropic Provider 可发送工具 schema、拼接 `input_json_delta.partial_json`、序列化工具历史。证据：`tests.test_anthropic_provider_tools` 全部通过。
- [x] Agent 能执行一次工具调用、回灌工具调用与工具结果、生成最终回复，并拒绝第二次自动工具调用。证据：`tests.test_agent` 全部通过。
- [x] TUI 能显示 Claude Code 风格工具行和结果摘要。证据：`tests.test_tui` 和 `tests.test_cli` 覆盖 `● Read(path)` 与 `⎿` 摘要输出。
- [x] 普通无工具聊天路径仍可用。证据：既有 provider、agent、cli 文本路径测试全部通过。
- [x] `/config` 不泄露 API key。证据：`tests.test_cli` 覆盖密钥不出现在输出中。

## 受环境阻塞
- [ ] tmux 端到端真实对话。原因：当前 Windows shell 中未找到 `tmux` 命令。

## 端到端状态
- 当前 workspace 存在 `huicode.yaml`，但验收过程中未读取或打印其内容，避免泄露 API key。
- 可离线验证的工具系统、Provider 流式工具调用解析、历史回灌、TUI 工具行、单次工具回合边界均已通过测试。
- 需要在具备 tmux 的环境中继续执行 `checklist.md` 的端到端场景 1-8。
