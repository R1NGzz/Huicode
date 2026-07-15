# HuiCode Hook 系统 Checklist

> 每一项都必须通过运行代码、检查输出或观察文件状态验证。实现阶段只在证据存在后勾选。

## 配置加载与校验

- [x] C01 三层配置按“用户级 `<` 启动配置 `<` 项目级”合并，相同 id 由高层整体覆盖，不同 id 全部保留。（验证：在临时 HOME、`huicode.yaml`、项目 `.huicode/hooks.yaml` 分别声明规则，加载目录并比对 id、source、内容和顺序；覆盖 AC1/F1）
- [x] C02 同一来源重复 id 会阻止启动，并明确显示规则 id、来源文件和重复原因。（验证：使用重复 id 配置启动 CLI，预期退出码 2 且 stderr/stdout 含三项信息；覆盖 AC1/F1）
- [x] C03 `enabled: false` 规则仍被完整校验，但不会运行，并计入 disabled 数量。（验证：分别使用合法与缺字段的禁用规则；合法目录统计 disabled=1，非法配置启动失败；覆盖 AC1/F1）
- [x] C04 主配置能解析 Hook 所需的列表内映射和多层条件，同时现有 protocol、thinking、context、memory、mcp 配置保持兼容。（验证：运行 `tests.test_config` 并加载一份包含全部配置段的真实 YAML；覆盖 AC1、AC11/F1/N1）
- [x] C05 未知事件、未知动作、非法 timeout、未定义环境变量、非法事件动作组合均在启动阶段集中报错。（验证：参数化配置测试逐项断言 HookConfigError 字段路径；覆盖 AC1/F1）

## 条件表达式

- [x] C06 exact、glob、regex 对匹配和不匹配输入都返回正确结果，glob 保持大小写敏感。（验证：运行条件矩阵测试；覆盖 AC3/F3）
- [x] C07 `not` 正确反转 exact、glob、regex，字段不存在时正向不匹配、反向匹配。（验证：运行缺失字段和三种 not 测试；覆盖 AC3/F3）
- [x] C08 all 要求全部满足，any 只需一个满足；省略 if 时每次事件都触发。（验证：同一事件依次发布不同 payload，检查动作运行次数；覆盖 AC3/F3）
- [x] C09 all/any 混用、空条件组、单叶子多个匹配器和非法 regex 都会阻止启动。（验证：运行配置负例测试并检查字段级错误；覆盖 AC3/F3）
- [x] C10 Hook 与权限规则共享精确/glob 语义，`Glob` 与 `Find` 工具名得到一致结果，现有权限规则行为不变。（验证：同时运行 `tests.test_hooks_matching` 与 `tests.test_permissions_rules`；覆盖 AC3、AC11/F3/N1）

## 生命周期事件

- [x] C11 一次普通对话按顺序产生 session_start、turn_start、message_received、message_completed、turn_end、session_end，且 session/turn 结束事件各恰好一次。（验证：fake Provider 完成最终回答后读取 Hook JSONL 事件序列；覆盖 AC2/F2）
- [x] C12 中间模型响应包含工具调用时也产生 message_completed，并正确标记“中间响应/含工具调用”。（验证：fake Provider 第一轮发 ToolCall、第二轮 final，检查两次消息事件载荷；覆盖 AC2/F2）
- [x] C13 Provider/API 请求错误产生 agent_error 和带 error 原因的 turn_end；Hook 自身错误不产生 agent_error。（验证：分别让 Provider 和 Hook 抛错，比较日志事件；覆盖 AC2、AC8/F2/F8）
- [x] C14 自动重量压缩和 `/compact` 手动压缩均产生 context_before_compact/context_after_compact，summary、skip、failure 状态可区分。（验证：运行自动/手动压缩集成测试并检查 payload；覆盖 AC2/F2）
- [x] C15 轻量工具结果落盘不会误报重量压缩 before/after 事件。（验证：返回超阈值工具结果但不触发摘要，检查 Hook 运行次数为 0；覆盖 AC2/F2）
- [x] C16 isolated Skill 内的事件带 `skill:<name>` scope，工具 Hook 生效，但子会话 turn/next-request Prompt 状态不进入主 AgentState。（验证：运行 isolated Skill 集成测试并比较父子状态；覆盖 AC2、AC6/F2/F6）

## 工具拦截与协议安全

- [x] C17 `tool_before` command 以退出码 2 拒绝 Write 后，目标文件不创建或不改变，权限确认器调用次数为 0。（验证：记录文件哈希和 confirmer spy；覆盖 AC4/F4）
- [x] C18 Hook 拒绝生成错误码 `hook_denied` 的结构化 ToolResult，包含 rule id 与原因，并立即触发一次 tool_after。（验证：检查工具消息和 Hook 日志；覆盖 AC4/F4）
- [x] C19 模型收到 Hook 拒绝结果后 Agent Loop 不停止，能够在下一轮改用其他工具或给出最终回答。（验证：fake Provider 先请求被拒工具、再返回替代方案，预期 stop_reason=final；覆盖 AC4/F4）
- [x] C20 多个 tool_before 规则遇到首个明确拒绝后停止执行剩余规则。（验证：三个计数动作中第二个拒绝，预期第三个计数为 0；覆盖 AC4/F4）
- [x] C21 Hook 未拒绝时执行顺序为 Hook、Plan Mode、权限、工具；Plan/权限拒绝和工具失败仍各产生一次 tool_after。（验证：带调用记录的 spy 比较顺序与次数；覆盖 AC4/F4）
- [x] C22 一次响应含多个并行和串行 ToolCall 时，每个 tool_use 都紧随一个相同 id 的 tool_result，调用顺序稳定，不触发 Anthropic 缺失 tool_result 错误。（验证：运行多工具集成测试并序列化 Anthropic 请求；覆盖 AC4、AC11/F4/N4）

## 四类动作

- [x] C23 command 动作从 stdin 收到 UTF-8 标准事件 JSON，能正确读取中文字段，事件参数没有被拼进命令行。（验证：测试脚本回显 argv 与 stdin；argv 只含配置参数，stdin JSON 含中文；覆盖 AC5、AC9/F5/F9）
- [x] C24 command 退出码 0、tool_before 退出码 2、其他非零、命令不存在和超时分别得到 success、denied、failed、failed、timeout。（验证：运行五种本地子进程动作并检查 ActionResult；覆盖 AC5、AC7、AC8/F5/F7/F8）
- [x] C25 HTTP 动作收到与 command 核心字段结构一致的 JSON body，默认 POST 和自定义 method/header 均生效。（验证：本地 HTTP Server 记录请求并与 command stdin payload 对比；覆盖 AC5、AC9/F5/F9）
- [x] C26 HTTP 2xx deny JSON 只在 tool_before 形成明确拒绝；断连、非预期状态、无效 JSON 和超时只记失败并继续主流程。（验证：本地 Server/未监听端口覆盖各状态；覆盖 AC4、AC5、AC8/F4/F5/F8）
- [x] C27 prompt 动作以 `<huicode_instruction type="hook">` 动态系统模块注入，不出现在用户消息、稳定缓存模块或摘要历史中。（验证：检查 Provider 收到的 PromptBundle 与 ConversationMessage；覆盖 AC5、AC6/F5/F6）
- [x] C28 subagent 动作只记录 skipped/not-implemented，不调用 Provider、不修改主历史、不阻断 Agent。（验证：Provider spy 调用数不增加，日志状态为 skipped；覆盖 AC5/F5）

## Prompt 作用域

- [x] C29 next_request 指令只出现在下一次 Provider 请求中，请求成功或失败后都被清除。（验证：连续两次请求及一次失败重试场景比较 PromptBundle；覆盖 AC6/F6）
- [x] C30 turn 指令在同一 Agent 轮次的多次模型请求中持续存在，turn_end 后消失。（验证：一轮两次工具循环后开始下一用户轮，比较三次 Prompt；覆盖 AC6/F6）
- [x] C31 session 指令跨多个用户轮和 isolated Skill 保留，直到 session_end；`/clear` 不清除 session 指令。（验证：session_start prompt Hook 后执行普通轮、clear、Skill 轮并检查 Prompt；覆盖 AC6/F6）
- [x] C32 `/clear` 清除当前主 Agent 的 turn 和 next-request Hook 块，但不清 once 标记。（验证：注入临时块并触发 once 规则，执行 clear 后检查状态与二次事件运行次数；覆盖 AC6、AC7/F6/F7）

## 执行控制与关闭

- [x] C33 `once: true` 规则同一进程第一次匹配后只运行一次，即使第一次动作失败也不重试；重启后可再次运行。（验证：同进程发布两次事件，再新建 Manager 发布一次；覆盖 AC7/F7）
- [x] C34 async command/HTTP 提交后 Agent 主流程立即继续，日志先出现 scheduled，完成后出现最终状态。（验证：500ms 动作下主流程返回耗时明显小于动作耗时，并轮询 JSONL；覆盖 AC7/F7）
- [x] C35 async tool_before、async prompt、tool_before subagent 在配置校验阶段被拒绝。（验证：三份非法配置均返回 HookConfigError；覆盖 AC7/F7）
- [x] C36 同步动作达到 timeout 后被终止或取消并记为 timeout，Agent 原任务继续完成。（验证：短 timeout + 长进程，检查运行时长、日志和 stop_reason；覆盖 AC7、AC8/F7/F8）
- [x] C37 正常退出最多等待后台任务 2 秒，不会无限卡住；未完成项被取消或记录 skipped。（验证：启动 10 秒后台动作后 `/exit`，测量总退出时长并检查日志；覆盖 AC10/F10）

## 故障隔离与日志

- [x] C38 Hook 动作异常、匹配异常、模板渲染保护、HTTP 错误和日志写入失败均不会让 TUI 崩溃或改变 Agent stop_reason。（验证：参数化故障注入后预期 Agent final；覆盖 AC8/F8）
- [x] C39 Hook 日志为追加式单行 JSONL，状态至少覆盖 success、denied、failed、timeout、skipped、scheduled，坏行不影响后续追加。（验证：运行各状态动作，手工插入坏行后再写一条并逐行容错读取；覆盖 AC8/F8）
- [x] C40 日志和事件 payload 不包含 API key、Authorization、Cookie、password、secret、token 或 thinking 原文。（验证：向嵌套参数、headers、错误文本植入哨兵值，搜索日志和 HTTP body 均无原文；覆盖 AC2、AC8、AC9、AC11/F2/F8/F9/N5）
- [x] C41 大文本、集合和动作输出被限制为有界预览，不会复制完整上下文或无限增大单条日志。（验证：输入超大消息/工具结果/stdout，断言 payload 和日志行字节上限；覆盖 AC8、AC9/F8/F9）
- [x] C42 `.huicode/logs` 不能通过 Write/Edit 或有副作用 Bash 被模型修改，但可通过正常文件读取路径查看。（验证：权限引擎分别评估写、改、Bash 写和 Read；覆盖 AC9/F9）
- [x] C43 危险 command Hook 和越界 cwd 在动作执行前被拒绝，不运行子进程；该状态只记 Hook 失败，不终止 Agent。（验证：命令副作用哨兵不存在，日志含安全边界原因，Agent final；覆盖 AC9/F9）

## CLI 与可观测性

- [x] C44 启动输出包含 Hooks effective、disabled 和 user/config/project 来源数量；无 Hook 时显示零值且正常进入交互。（验证：分别用三层配置和空配置启动 CLI；覆盖 AC10/F10）
- [x] C45 `/status` 显示 Hook effective、pending、failed 和日志路径，运行后台任务前后状态会更新。（验证：触发慢后台 Hook 并连续执行 status；覆盖 AC10/F10）
- [x] C46 Hook 配置错误发生时，已启动的 Memory/MCP 资源会关闭，CLI 返回状态码 2。（验证：使用 close spy 和非法 Hook 配置；覆盖 AC1、AC10/F1/F10）
- [x] C47 EOF、`/exit` 和正常测试退出路径都恰好触发一次 session_end，并按 Hook、Memory、MCP 顺序关闭。（验证：三种输入场景记录 close 顺序；覆盖 AC2、AC10/F2/F10）
- [x] C48 本地 `/help`、`/status`、`/permission` 等 Slash Command 不触发 turn/message Hook，`/compact` 只触发 context 事件。（验证：输入命令序列后检查日志事件集合；覆盖 AC2/F2）

## 构建与回归

- [x] C49 所有 Hook 专项测试通过。（验证：运行 `python -m unittest tests.test_hooks_config tests.test_hooks_matching tests.test_hooks_events tests.test_hooks_actions tests.test_hooks_manager tests.test_agent_hooks tests.test_cli_hooks -v`；覆盖 AC1-AC10）
- [x] C50 完整测试套件通过，只有已知 Windows 符号链接权限测试允许跳过且必须记录数量和原因。（验证：运行 `python -m unittest discover -s tests -v`；覆盖 AC11/N1-N6）
- [x] C51 项目源码和测试可完整编译。（验证：运行 `python -m compileall huicode tests`，退出码为 0；覆盖 AC11/N1-N6）
- [x] C52 Git 差异没有尾随空白、冲突标记或意外生成文件。（验证：运行 `git diff --check` 并检查 `git status --short`；覆盖 AC11/N3-N4）
- [x] C53 使用用户实际启动 HuiCode 的 Python 解释器重复 Hook/CLI 专项验证，PyYAML 和运行依赖均从该解释器可导入。（验证：记录 `sys.executable`，运行专项测试和 `python -m huicode --config ...`；覆盖 AC11/N1/N6）
- [x] C54 无 Hook 配置时，普通对话、Agent Loop、权限确认、上下文、记忆、MCP、Slash Command 和 Skill 原有测试均无行为回归。（验证：运行完整套件并执行一段空 Hook CLI fake-provider 对话；覆盖 AC11/N1）
- [x] C55 README 示例能被真实 Hook 配置加载器解析，示例字段与当前实现一致。（验证：逐个抽取示例写入临时 YAML 并加载；覆盖 AC1、AC5/F1/F5）

## 端到端场景

- [x] E01 工具安全拦截：启动 HuiCode，用户要求写文件，tool_before Hook 明确拒绝；界面不弹权限确认，文件不变，模型读到原因后改用安全方案或解释无法执行。（验证：真实 CLI 输入流 + fake Provider，保存完整输出、文件哈希和 hooks.jsonl；覆盖 AC4、AC8、AC9）
- [x] E02 自动格式化与后台通知：Edit 成功后 tool_after command 格式化目标文件，同时 async HTTP 向本地服务发送事件；Agent 不等待 HTTP 完成，退出时日志完整。（验证：检查格式化文件、本地 HTTP 记录、交互耗时和 JSONL 状态；覆盖 AC5、AC7、AC8、AC10）
- [x] E03 上下文注入：session_start 注入项目约束、turn_start 注入本轮提示；连续两轮和一次 `/clear` 后，Provider 看到正确作用域且用户历史中没有 Hook 文本。（验证：记录每次 PromptBundle 与 messages；覆盖 AC2、AC6）
- [x] E04 跨子系统流程：项目级 Hook 覆盖用户级同 id，isolated review Skill 调用工具时被 Hook 拦截，结果安全回流主会话，随后 `/compact` 产生系统事件并正常 `/exit`。（验证：真实 CLI 路由 + fake Provider/Skill，检查来源、tool_result 配对、上下文日志和 session_end；覆盖 AC1、AC2、AC4、AC10）

## 验收映射

| 验收标准 | Checklist |
| --- | --- |
| AC1 | C01-C05、C46、C55、E04 |
| AC2 | C11-C16、C40、C47-C48、E03-E04 |
| AC3 | C06-C10 |
| AC4 | C17-C22、C26、E01、E04 |
| AC5 | C23-C28、C55、E02 |
| AC6 | C16、C27、C29-C32、E03 |
| AC7 | C24、C33-C37、E02 |
| AC8 | C13、C24、C26、C38-C41、E01-E02 |
| AC9 | C23、C25、C40-C43、E01 |
| AC10 | C37、C44-C47、E02、E04 |
| AC11 | C04、C10、C22、C40、C49-C54 |
