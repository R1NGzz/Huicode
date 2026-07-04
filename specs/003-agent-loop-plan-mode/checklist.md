# HuiCode Agent Loop 与 Plan Mode 验收清单

> 每一项都必须通过运行测试、执行命令或观察 TUI 行为验证。实现完成后，将实际证据记录到 `acceptance_report.md`。

## 实现完整性

- [ ] Agent 事件模型已实现，包含 text、thinking、tool_call、tool_result、progress、usage、error、done 事件。
  验证方式：运行 `python -m unittest tests.test_agent_events -v`，并确认事件默认值和字段测试通过。

- [ ] Agent 状态和选项已实现，默认迭代上限为 8，连续未知工具上限为 2，只读工具集包含 `Read`、`Find`、`Search`、`Glob`。
  验证方式：运行 `python -m unittest tests.test_agent_events -v`，确认默认配置测试通过。

- [ ] 工具注册中心能按允许名单导出 tool specs，并能解析 `Glob` 到 `Find`。
  验证方式：运行 `python -m unittest tests.test_tool_batching tests.test_tools_registry -v`，确认过滤和别名测试通过。

- [ ] 工具已区分读类和副作用类：`Read`、`Find`、`Search`、`Glob` 为读类，`Write`、`Edit`、`Bash` 为副作用类。
  验证方式：运行 `python -m unittest tests.test_tool_batching tests.test_tools_registry -v`，确认分类测试通过。

- [ ] 流式收集器能一边产生实时 text/thinking 事件，一边收集完整文本、thinking、signature、usage 和全部工具调用。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认文本双路和收集器测试通过。

- [ ] Agent Loop 能在同一次用户请求中执行“模型输出工具调用 -> 执行工具 -> 回灌结果 -> 再请求模型”的多轮 ReAct 流程。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认多轮工具调用后最终回答测试通过。

- [ ] 没有工具调用时，Agent Loop 会保存 assistant 文本并以正常 done 结束。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认无工具普通回答测试通过。

- [ ] 工具调用和工具结果会写回对话历史，下一轮模型请求能看到前一轮观察结果。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认历史回灌测试通过。

- [ ] 一次模型响应中的多个读类工具调用可以在同一批处理，并分别产生工具行和结果摘要。
  验证方式：运行 `python -m unittest tests.test_tool_batching -v`，确认读类批处理和事件输出测试通过。

- [ ] 多个副作用工具调用按顺序串行执行。
  验证方式：运行 `python -m unittest tests.test_tool_batching -v`，确认副作用串行顺序测试通过。

- [ ] 读类工具和副作用工具混合出现时，Agent 会按安全策略分批执行。
  验证方式：运行 `python -m unittest tests.test_tool_batching -v`，确认混合分批测试通过。

- [ ] DeepSeek Anthropic 兼容接口的 thinking 与 signature 在多轮工具循环中会保留并回传，不再触发缺少 thinking 回传的 400。
  验证方式：运行 `python -m unittest tests.test_agent_loop tests.test_anthropic_provider_tools -v`，并用真实 DeepSeek Anthropic 兼容配置做一次带工具调用的对话观察。

## 停止条件

- [ ] 模型输出最终文本且不再请求工具时，Agent Loop 正常结束。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认 final stop 测试通过。

- [ ] 达到迭代上限时，Agent Loop 停止并显示可读的上限提示。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认 max_iterations 测试通过。

- [ ] 用户取消当前任务时，Agent Loop 停止并回到可输入状态。
  验证方式：运行 CLI，在一次长任务中触发 KeyboardInterrupt，观察 TUI 返回提示符；或运行对应取消测试。

- [ ] 连续未知工具调用达到限制时，Agent Loop 停止并显示未知工具提示。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认 unknown tool limit 测试通过。

- [ ] Provider 或流式解析出错时，Agent Loop 停止并显示可读错误，不把异常堆栈直接暴露给普通用户。
  验证方式：运行 `python -m unittest tests.test_agent_loop -v`，确认 provider error 测试通过。

## TUI 与 CLI 集成

- [ ] TUI 能渲染实时文本流。
  验证方式：运行 `python -m unittest tests.test_tui -v`，并在 CLI 中观察模型回复逐步输出。

- [ ] TUI 能以 Claude Code 风格渲染工具调用行，例如 `● Read(path)`。
  验证方式：运行 `python -m unittest tests.test_tui -v`，并在 CLI 中观察真实工具调用行。

- [ ] TUI 能以 `⎿` 结果摘要渲染工具执行结果。
  验证方式：运行 `python -m unittest tests.test_tui -v`，并在 CLI 中观察工具结果摘要。

- [ ] TUI 能渲染 progress、usage、error、done 事件；无 usage 时不影响流程。
  验证方式：运行 `python -m unittest tests.test_tui tests.test_agent_loop -v`，确认相关事件测试通过。

- [ ] 普通输入默认使用全工具 Agent Loop，不需要用户每一步手动催促。
  验证方式：运行 CLI，输入“当前项目入口文件有哪些”，观察 HuiCode 自动多轮读取/搜索后给出最终回答。

- [ ] `/clear` 会清空对话历史、最近计划、取消状态和循环状态。
  验证方式：运行 `python -m unittest tests.test_cli tests.test_cli_plan_mode -v`，确认 clear 行为测试通过。

## Plan Mode

- [ ] `/plan <任务>` 会进入只读计划流程，并只向模型暴露 `Read`、`Find`、`Search`、`Glob`。
  验证方式：运行 `python -m unittest tests.test_cli_plan_mode -v`，确认 Plan Mode tool specs 过滤测试通过。

- [ ] `/plan` 不带任务时，会切换到 Plan Mode，下一条普通输入作为计划任务执行。
  验证方式：运行 `python -m unittest tests.test_cli_plan_mode -v`，确认延迟计划输入测试通过。

- [ ] Plan Mode 不会执行 `Write`、`Edit`、`Bash` 等副作用工具。
  验证方式：运行 `python -m unittest tests.test_cli_plan_mode tests.test_tool_batching -v`，确认副作用工具不在 Plan Mode specs 中。

- [ ] Plan Mode 能产出用户可读的计划，并保存为最近计划。
  验证方式：运行 CLI 使用 `/plan 分析入口文件修改方案`，观察输出计划，并确认随后 `/do` 能引用该计划。

- [ ] `/do <任务>` 会切换到全工具执行模式，并结合最近计划与新任务继续执行。
  验证方式：运行 `python -m unittest tests.test_cli_plan_mode -v`，确认 `/do <任务>` 注入计划上下文测试通过。

- [ ] `/do` 不带任务时，会基于最近计划继续执行。
  验证方式：运行 `python -m unittest tests.test_cli_plan_mode -v`，确认 `/do` 默认执行最近计划测试通过。

## 构建与测试

- [ ] 全部单元测试通过。
  验证方式：运行 `python -m unittest discover -v`，预期全部通过。

- [ ] Python 编译检查通过。
  验证方式：运行 `python -m compileall -q huicode tests`，预期无错误输出。

- [ ] README 已说明 Agent Loop、`/plan`、`/do`、迭代上限和本阶段不做的能力。
  验证方式：阅读 `README.md`，确认说明与实现一致。

- [ ] 不输出或记录 `huicode.yaml` 中的 API key。
  验证方式：运行测试和一次真实 CLI 对话，确认错误摘要、事件输出和 README 均未打印密钥。

## 端到端场景

- [ ] 场景 1：普通多步项目分析。
  验证方式：启动 `python -m huicode --config huicode.yaml`，输入“当前项目入口文件有哪些”，观察 HuiCode 自动搜索/读取多个文件，并输出最终总结。

- [ ] 场景 2：Plan Mode 只读计划。
  验证方式：在 CLI 输入 `/plan 帮我规划如何给入口命令增加一个版本号参数`，观察只出现读类工具调用，最终输出计划，不发生写文件、改文件或命令执行。

- [ ] 场景 3：`/do` 基于最近计划执行。
  验证方式：紧接场景 2 输入 `/do`，观察 HuiCode 使用全工具继续执行，并能引用刚才的计划上下文。

- [ ] 场景 4：停止条件可见。
  验证方式：使用测试替身或配置低迭代上限触发 max_iterations，观察 CLI 显示上限停止提示并回到输入状态。

- [ ] 场景 5：DeepSeek Anthropic 兼容 thinking 多轮工具调用。
  验证方式：使用 DeepSeek Anthropic 兼容配置发起一次需要工具调用的问题，观察多轮工具调用后不再出现 `content[].thinking` 缺失导致的 HTTP 400。

- [ ] 场景 6：tmux 端到端验收。
  验证方式：如果当前环境可用 tmux，在 tmux 中启动 HuiCode，完成场景 1、2、3、4；如果 Windows 环境没有 tmux，则在 `acceptance_report.md` 记录 tmux 不可用，并用普通终端手动 E2E 结果替代。

## 验收标准映射

- AC1-AC2：由“实现完整性”中的 ReAct Loop、无工具结束项和“端到端场景 1”覆盖。
- AC3-AC6：由“停止条件”覆盖。
- AC7-AC8：由“TUI 与 CLI 集成”中的事件渲染和文本流覆盖。
- AC9：由“工具调用和工具结果会写回对话历史”覆盖。
- AC10-AC12：由多工具读类批处理、副作用串行和混合分批覆盖。
- AC13-AC16：由“Plan Mode”覆盖。
- AC17-AC18：由普通输入、实时文本、工具行和结果摘要覆盖。
- AC19：由 DeepSeek Anthropic thinking 多轮工具调用检查覆盖。
- AC20：由“构建与测试”覆盖。
