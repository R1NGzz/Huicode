# HuiCode 记忆系统验收清单

> 每项都必须通过运行测试、执行命令或观察输出验证。实现完成后在 `acceptance_report.md` 记录证据。

## 实现完整性

- [ ] 已解析 `memory` 配置，并提供默认值和非法值校验。
  - 验证：运行 `python -m unittest tests.test_config -v`，确认覆盖默认配置和非法配置。

- [ ] 用户级和项目级指令文件都会加载，且项目级优先排在前面。
  - 验证：运行 `python -m unittest tests.test_memory_instructions -v`，确认项目指令文本早于用户指令文本。

- [ ] `@include` 能展开合法文件，并安全跳过循环、过深、缺失和路径逃逸引用。
  - 验证：运行 `python -m unittest tests.test_memory_instructions -v`，确认危险 include 有 warning，且不会读取边界外文件。

- [ ] 项目指令以系统级上下文注入，不作为用户消息追加进对话历史。
  - 验证：运行 `python -m unittest tests.test_prompt_builder -v`，确认指令出现在 prompt 模块中，消息历史没有新增伪用户消息。

- [ ] JSONL 会话记录能保留 user、assistant、thinking、tool calls、tool results 和时间戳。
  - 验证：运行 `python -m unittest tests.test_memory_sessions -v`，确认消息往返后字段一致。

- [ ] 会话列表的 ID、标题、更新时间、消息数都来自扫描 JSONL，不依赖 meta 文件。
  - 验证：运行 `python -m unittest tests.test_memory_sessions -v`，确认元信息由 JSONL 计算得到。

- [ ] 恢复会话时会跳过坏 JSONL 行，并报告 warning。
  - 验证：运行 `python -m unittest tests.test_memory_sessions -v`，确认坏行计数和可用消息恢复正确。

- [ ] 恢复会话时会把未配对或孤立的工具历史截断到 provider 安全边界。
  - 验证：运行 `python -m unittest tests.test_memory_recovery -v`，确认破损 tool 尾部不会进入后续 provider 请求。

- [ ] 恢复久远会话时会插入时间跨度提醒。
  - 验证：运行 `python -m unittest tests.test_memory_sessions -v`，确认恢复结果包含 `session_time_gap` 上下文。

- [ ] 过期会话会被清理，但当前活动会话不会被误删。
  - 验证：运行 `python -m unittest tests.test_memory_sessions -v`，确认只删除非活动过期文件。

- [ ] 自动笔记支持四类：用户偏好、纠正反馈、项目知识、参考资料。
  - 验证：运行 `python -m unittest tests.test_memory_notes tests.test_memory_updater -v`，确认四类合法，非法分类被拒绝。

- [ ] 用户级笔记和项目级笔记分开保存。
  - 验证：运行 `python -m unittest tests.test_memory_notes -v`，确认用户级写入 `HUICODE_HOME`，项目级写入 workspace `.huicode`。

- [ ] 记忆索引由笔记重建，并控制在 200 行和 25KB 以内。
  - 验证：运行 `python -m unittest tests.test_memory_index -v`，确认超大笔记集合会被裁剪。

- [ ] 记忆索引包含原始笔记定位信息。
  - 验证：运行 `python -m unittest tests.test_memory_index -v`，确认每条索引包含 note id 或 source 路径提示。

- [ ] 记忆状态、笔记、索引和 warning 都经过 secret 脱敏。
  - 验证：运行 `python -m unittest tests.test_memory_notes tests.test_memory_index tests.test_cli_memory -v`，确认 API key 和 bearer token 不出现在输出中。

## 集成检查

- [ ] Agent Loop 会把 user、assistant 和 tool 消息写入当前 JSONL 会话。
  - 验证：运行 `python -m unittest tests.test_agent_memory -v`，确认工具轮后 session 文件包含三类消息。

- [ ] Agent Loop 在 provider 调用前刷新项目指令和记忆索引。
  - 验证：运行 `python -m unittest tests.test_agent_memory -v`，确认 provider 收到的 prompt 包含最新记忆索引。

- [ ] 自动记忆更新只在自然 final 且最后回复无工具调用时排队。
  - 验证：运行 `python -m unittest tests.test_agent_memory -v`，确认错误、取消、迭代上限和仍在请求工具的轮次不会触发更新。

- [ ] 自动记忆更新禁用工具，并且不阻塞最终回答展示。
  - 验证：运行 `python -m unittest tests.test_memory_updater tests.test_agent_memory -v`，确认 `allow_tool_calls=False`，且 final 事件先返回。

- [ ] 自动记忆更新失败不会导致 Agent Loop 崩溃。
  - 验证：运行 `python -m unittest tests.test_memory_updater tests.test_agent_memory -v`，确认失败只形成 report 或 warning，最终回复仍成功。

- [ ] `/clear` 清空当前对话并开启新会话，但不删除旧会话和长期笔记。
  - 验证：运行 `python -m unittest tests.test_cli_memory -v`，确认 clear 后旧 session 文件和 notes 仍存在。

- [ ] `/memory` 能显示记忆状态且不泄露 secret。
  - 验证：运行 `python -m unittest tests.test_cli_memory -v`，确认输出包含 session/index/note 统计，且不包含 secret。

- [ ] `/memory update` 能从最近对话手动触发记忆整理。
  - 验证：运行 `python -m unittest tests.test_cli_memory -v`，确认命令会调用 updater，或在没有可整理内容时给出清楚提示。

- [ ] `/memory rebuild` 能从笔记重建索引。
  - 验证：运行 `python -m unittest tests.test_cli_memory -v`，确认索引文件更新或输出重建成功。

- [ ] `/sessions` 能列出可恢复会话的 ID、标题、更新时间和消息数。
  - 验证：运行 `python -m unittest tests.test_cli_memory -v`，确认输出包含扫描得到的元信息。

- [ ] `/resume <session-id>` 能恢复会话，并继续追加到同一个 JSONL 文件。
  - 验证：运行 `python -m unittest tests.test_cli_memory -v`，确认 state 包含恢复消息，后续消息写入同一 session。

- [ ] `/sessions clean` 能清理过期非活动会话并显示数量。
  - 验证：运行 `python -m unittest tests.test_cli_memory -v`，确认输出包含清理数量。

- [ ] 恢复超预算会话时会先尝试上下文压缩。
  - 验证：运行 `python -m unittest tests.test_cli_memory tests.test_agent_memory -v`，确认恢复历史接近预算时调用 `ContextManager.manual_compact()`。

- [ ] Plan Mode、权限模式、MCP 工具和记忆注入可以共存。
  - 验证：运行 `python -m unittest tests.test_agent_memory tests.test_cli_plan_mode tests.test_mcp_tools -v`，确认模式限制和 MCP 工具结果不回退。

- [ ] OpenAI provider 在记忆注入和恢复工具历史后仍能序列化合法请求。
  - 验证：运行 `python -m unittest tests.test_openai_provider_tools -v`，确认 assistant `tool_calls` 与 tool messages 保持配对。

- [ ] Anthropic provider 在记忆注入和恢复工具历史后仍能序列化合法请求。
  - 验证：运行 `python -m unittest tests.test_anthropic_provider_tools -v`，确认 `tool_use` id 后有立即匹配的 `tool_result` blocks。

## 构建和测试

- [ ] 记忆系统专项测试通过。
  - 验证：运行 `python -m unittest tests.test_memory_instructions tests.test_memory_sessions tests.test_memory_recovery tests.test_memory_notes tests.test_memory_index tests.test_memory_updater tests.test_agent_memory tests.test_cli_memory -v`。

- [ ] Prompt、provider、context 和 TUI 回归测试通过。
  - 验证：运行 `python -m unittest tests.test_prompt_builder tests.test_openai_provider_tools tests.test_anthropic_provider_tools tests.test_context_manager tests.test_tui -v`。

- [ ] 全量单元测试通过。
  - 验证：运行 `python -m unittest discover -v`。

- [ ] Python 文件能正常编译。
  - 验证：运行 `python -m compileall -q huicode tests`。

- [ ] README 已说明记忆文件、命令、行为和限制。
  - 验证：打开 `README.md`，确认包含项目指令、会话、笔记、索引、命令和边界说明。

## 端到端场景

- [ ] 场景 1：新会话回答前加载项目指令和记忆索引。
  - 验证：在临时 workspace 创建指令和笔记，用 fake provider 启动 HuiCode，提问后观察 provider prompt 同时包含指令和索引。

- [ ] 场景 2：带工具调用的对话能存档并安全恢复。
  - 验证：fake provider 触发 `Read`，确认 JSONL 包含 user/assistant/tool，恢复后继续提问不会触发 provider 工具配对错误。

- [ ] 场景 3：损坏会话文件仍能部分恢复。
  - 验证：往 JSONL 插入坏行和未配对工具调用，执行 `/resume`，观察 warning 和安全截断。

- [ ] 场景 4：自然 final 回复会创建或更新记忆，且不阻塞回答。
  - 验证：fake memory provider 返回 create 操作，运行一轮 final 回复，观察最终文本先出现，随后 note/index 更新。

- [ ] 场景 5：`/clear` 开启干净工作上下文，同时长期记忆仍可用。
  - 验证：运行 `/clear` 后再运行 `/memory`，观察当前消息清空但 notes/index 仍存在。

- [ ] 场景 6：过期非活动会话被清理，当前活动会话保留。
  - 验证：创建一个旧非活动 session 和一个旧活动 session，运行 cleanup，确认只删除非活动文件。

- [ ] 场景 7：疑似 secret 的值不会显示或写入记忆输出。
  - 验证：构造包含 `Authorization: Bearer test-secret` 的对话，运行 memory update/status/index，确认 `test-secret` 不出现。

## 验收项映射

| 验收项 | 对应清单 |
| --- | --- |
| AC1 | 项目指令优先级、prompt 注入 |
| AC2 | include 展开和安全检查 |
| AC3 | JSONL 消息记录 |
| AC4 | 会话元信息扫描 |
| AC5 | 坏行恢复 |
| AC6 | 工具历史安全截断、provider 序列化 |
| AC7 | 超预算恢复压缩 |
| AC8 | 久远会话时间跨度提醒 |
| AC9 | 过期会话清理 |
| AC10 | 自动更新触发规则 |
| AC11 | 自动更新 noop/去重行为 |
| AC12 | 用户级/项目级笔记分离 |
| AC13 | 索引大小限制 |
| AC14 | 记忆索引注入 |
| AC15 | `/memory` 状态 |
| AC16 | `/sessions` 和 `/resume` |
| AC17 | `/clear` 语义 |
| AC18 | 失败 warning 和继续运行 |
| AC19 | OpenAI/Anthropic 序列兼容 |
| AC20 | README 文档 |
| AC21 | 构建和测试 |
