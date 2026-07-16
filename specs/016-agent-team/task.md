# Agent Team 实施任务

## 文件清单

### 新建

- `huicode/teams/__init__.py`：导出 Team 公共接口。
- `huicode/teams/types.py`：团队、成员、任务、消息、审批、集成和事件类型。
- `huicode/teams/naming.py`：团队名、成员名、标识和路径安全校验。
- `huicode/teams/locking.py`：可重试、可回收过期锁的文件锁。
- `huicode/teams/storage.py`：团队目录布局、JSON 快照与 JSONL 持久化。
- `huicode/teams/tasks.py`：共享任务 CRUD、依赖图和乐观并发。
- `huicode/teams/mailbox.py`：名称注册表、单发、广播、收件与已读处理。
- `huicode/teams/approval.py`：计划申请、结构化决定和执行闸门。
- `huicode/teams/backends.py`：后端协议、能力探测、自动选择与协程后端。
- `huicode/teams/terminal_backends.py`：tmux 和 Windows Terminal 后端。
- `huicode/teams/worktrees.py`：长期成员与集成 Worktree 适配。
- `huicode/teams/scoping.py`：身份工具过滤、审批过滤和 Coordinator 限制。
- `huicode/teams/member_runner.py`：长期成员 Agent Loop、idle 与恢复。
- `huicode/teams/integration.py`：成员分支合并、验证、冲突处理和发布。
- `huicode/teams/tools.py`：Team、Task、Message、Plan 和 Integrate 工具。
- `huicode/teams/manager.py`：团队生命周期、成员后端和事件总编排。
- `huicode/teams/worker.py`：独立终端成员内部入口。
- `tests/test_team_config.py`
- `tests/test_team_naming_storage.py`
- `tests/test_team_tasks.py`
- `tests/test_team_mailbox.py`
- `tests/test_team_approval.py`
- `tests/test_team_backends.py`
- `tests/test_team_worktrees.py`
- `tests/test_team_scoping.py`
- `tests/test_team_member_runner.py`
- `tests/test_team_integration.py`
- `tests/test_team_manager.py`
- `tests/test_team_tools.py`
- `tests/test_team_cli.py`
- `specs/016-agent-team/acceptance_report.md`

### 修改

- `huicode/config.py`：增加并校验 `TeamConfig`。
- `huicode/__main__.py`：分流普通 CLI 和内部 Team Worker。
- `huicode/cli.py`：组装 TeamManager、事件泵、运行身份和关闭流程。
- `huicode/agent.py`：接入 Team 作用域 Registry、Prompt 状态和事件租约。
- `huicode/subagents/filtering.py`：禁止普通子 Agent 看到 Team 工具。
- `huicode/prompts/base.py`：承载团队动态 Prompt 数据。
- `huicode/prompts/modules.py`：渲染 Team Lead、成员和 Coordinator 指令。
- `huicode/tui.py`：渲染团队、成员、审批、消息与集成事件。
- `huicode/worktrees/manager.py`：增加状态检查和删除预检。
- `README.md`：补充 Team 配置与使用说明。
- `docs/mew-spec-pitfalls.md`：仅在出现真实返工时追加记录。

## 任务依赖

```text
T1 -> T2 -> T3
T3 -> T4 -> T6
T3 -> T5 -> T6
T1 -> T7
T1 -> T8 -> T9
           -> T10
T1 -> T11
T4 + T5 + T6 + T7 + T11 -> T12 -> T13
T3 + T4 + T5 + T6 + T7 + T8 + T9 + T10 + T13 -> T14 -> T15
T11 + T14 -> T16
T7 -> T17 -> T18
T15 + T16 + T18 -> T19 -> T20 -> T21
T15 + T18 -> T22
T21 + T22 -> T23 -> T24 -> T25
```

## 实施任务

### T1 Team 配置与领域类型

**依赖：** 无

**步骤：**

1. 在 `huicode/config.py` 增加不可变 `TeamConfig` 和安全默认值。
2. 解析 `teams` YAML 映射，校验能力开关、后端枚举、并发数、锁参数、轮询间隔、关闭超时和检查命令。
3. 将配置挂入 `LLMConfig`，保持旧配置无需新增字段即可启动。
4. 在 `huicode/teams/types.py` 定义计划中的领域类型、状态字面量和结构化异常。
5. 在 `huicode/teams/__init__.py` 导出稳定公共类型。

**验证：**

- `tests/test_team_config.py` 覆盖默认值、完整配置、错误映射、非法后端和非正数。
- 运行 `python -m unittest tests.test_team_config -v`。

### T2 名称、标识与路径安全

**依赖：** T1

**步骤：**

1. 定义团队名、成员名、任务 ID 的允许字符、长度和保留名规则。
2. 拒绝绝对路径、盘符、斜杠、反斜杠、`.`、`..`、控制字符和尾随空白。
3. 将安全团队名映射到用户级 Team 根目录，并做规范路径边界检查。
4. 生成稳定 Team ID、Member ID、内部邮箱名和分支片段。
5. 确保所有非法输入在目录创建或 Git 调用前失败。

**验证：**

- `tests/test_team_naming_storage.py` 表驱动覆盖合法中文显示字段与严格 ASCII 逻辑名、路径逃逸及保留名。
- Fake Store/Git 断言非法输入无副作用。

### T3 文件锁与基础持久化

**依赖：** T2

**步骤：**

1. 实现排他创建锁文件、重试、退避和上下文管理器释放。
2. 锁文件记录 token、PID 与时间戳；仅在超过阈值且拥有者不可确认存活时回收。
3. 实现 JSON 快照的版本校验、临时文件、flush、可用时 fsync 和原子替换。
4. 实现 UTF-8 JSONL 单行追加、坏行跳过和诊断信息。
5. 建立固定 Team 目录布局并校验所有派生路径仍在团队根内。

**验证：**

- 覆盖锁成功、竞争重试、活动锁拒绝、过期锁回收、异常释放。
- 覆盖快照往返、替换中断、JSONL 坏行和边界逃逸。

### T4 共享任务存储

**依赖：** T3

**步骤：**

1. 实现任务创建、列表、详情、认领、更新和删除。
2. 使用 `version` 做乐观并发，陈旧版本返回 `task_conflict`。
3. 校验不存在依赖、自依赖和 DFS 环路。
4. 根据依赖完成状态自动计算 pending/blocked，并限制合法状态转换。
5. 拒绝删除执行中任务或仍被其他任务依赖的任务。
6. 在单一任务锁内完成读取、校验和原子快照更新。

**验证：**

- `tests/test_team_tasks.py` 覆盖 CRUD、状态转换、依赖解阻、环路、删除保护和并发版本冲突。
- 两线程竞争认领时只允许一个成功。

### T5 名称注册表与邮箱

**依赖：** T3

**步骤：**

1. 实现 Lead 与成员名称注册、解析和重名拒绝。
2. 实现消息字段校验、单发、广播和成功/失败投递报告。
3. 每个邮箱使用独立锁追加 JSONL，消息默认未读。
4. 实现收取、按消息 ID 标记已读和坏行隔离。
5. 校验结构化消息的类型、correlation ID、task ID 和 payload。
6. 未知收件人必须在写入任何邮箱前失败；广播按收件结果返回诊断。

**验证：**

- `tests/test_team_mailbox.py` 覆盖单发、广播、未知名称、锁竞争、坏行、已读和结构化消息。
- 模拟一个邮箱写入失败，确认其他成功消息不丢且报告准确。

### T6 计划审批闸门

**依赖：** T4、T5

**步骤：**

1. 实现计划申请创建、当前请求查询和审批快照原子持久化。
2. 实现按 request ID 的 allow/deny，拒绝过期、重复和成员不匹配决定。
3. deny 保存反馈并使旧请求终止；重新申请生成新 ID。
4. 决定后发送 `plan_decision` 邮件，返回待唤醒成员。
5. 提供 `allows_side_effect(member, task)` 程序检查入口。
6. 确认普通文本消息没有任何路径可调用审批状态更新。

**验证：**

- `tests/test_team_approval.py` 覆盖申请、允许、拒绝、重试、错配、重复和重启恢复。
- 断言未批准、已拒绝和旧 request ID 均不能通过副作用检查。

### T7 Team Worktree 适配

**依赖：** T1

**步骤：**

1. 给 `WorktreeManager` 增加无删除副作用的状态检查与删除预检。
2. 实现稳定 `team-id/member-id` 到 Worktree task ID、逻辑名和句柄的映射。
3. 新成员创建独立 Worktree，已有成员使用清单做可信快速恢复。
4. 一轮任务结束只保留 Worktree；团队删除才调用保护性删除。
5. 实现集成 Worktree 的独立命名空间，禁止与成员目录复用。
6. 确认只读成员也经过同一创建路径。

**验证：**

- `tests/test_team_worktrees.py` 在临时仓库覆盖双成员隔离、恢复、保留、删除预检和集成目录隔离。
- 恢复路径用禁止调用 Git 的 Fake Backend 验证零 Git 探测。

### T8 后端协议与选择器

**依赖：** T1

**步骤：**

1. 定义后端 availability、launch spec、handle 和生命周期 Protocol。
2. 实现 tmux、Windows Terminal、协程的注入式能力探测接口。
3. 实现 auto 固定优先级选择。
4. 实现 explicit terminal 仅在终端后端中选择，不可用时明确失败。
5. 实现 explicit coroutine 直接选择和 actual backend 事件数据。

**验证：**

- `tests/test_team_backends.py` 参数化覆盖所有能力组合与优先级。
- 断言显式 terminal 永不返回 coroutine。

### T9 协程成员后端

**依赖：** T8

**步骤：**

1. 创建独立于普通 SubagentManager 的 Team Worker Pool。
2. 为每个成员维护 Future、停止事件、唤醒事件和运行句柄。
3. launch 提交长期成员函数，wake 触发事件，stop 设置停止信号并有限等待。
4. alive 结合 Future 和成员状态判断。
5. 单个成员异常转换为失败事件，不退出 Worker Pool。

**验证：**

- Fake Runner 覆盖启动、唤醒、自然 idle、停止、超时和异常隔离。
- 启动两个成员，确认状态和唤醒事件不串线。

### T10 终端成员后端

**依赖：** T8

**步骤：**

1. 实现 tmux 可执行文件和当前会话探测。
2. 用参数数组创建 pane，记录 session/window/pane，wake 使用目标 pane 的 `send-keys`。
3. 实现 Windows Terminal `wt` 探测和 `split-pane` 启动内部 worker。
4. 为 Windows Worker 创建稳定本地唤醒事件标识，wake 不依赖解析任务正文。
5. stop 只终止匹配 handle 的 pane/worker，超时返回诊断。
6. 启动命令只传 team path、member ID 和 config path，不传 API Key。

**验证：**

- mock `subprocess` 覆盖命令参数、`shell=False`、显式 cwd、handle 和错误转换。
- 无真实 tmux/wt 时探测返回不可用；测试不启动用户真实终端。

### T11 运行身份与工具作用域

**依赖：** T1

**步骤：**

1. 实现 main、team_lead、team_member、subagent 四类运行身份。
2. 实现 Registry 包装器，在 `to_specs()`、`get()`、`resolve_name()` 和副作用判断保持一致。
3. main 仅开放 Team 入口；Lead 和成员分别开放其协作工具；普通子 Agent 全部禁用。
4. 实现审批感知过滤：未批准成员看不到副作用工具，历史调用返回结构化拒绝。
5. 实现 coordinator 双锁判定并去除 Write/Edit 等直接写工具。
6. 用受限 Git 包装器替换 Coordinator 的 Bash，拒绝 shell 控制符、重定向和非允许 Git 子命令。

**验证：**

- `tests/test_team_scoping.py` 对四类身份逐一断言工具列表和直接执行结果。
- 覆盖只开一把 coordinator 锁、双锁、Bash 重定向、非 Git 命令和允许诊断命令。

### T12 成员会话与上下文恢复

**依赖：** T4、T5、T6、T7、T11

**步骤：**

1. 为成员创建独立 JSONL recorder，记录消息、状态、用量和任务事件。
2. 恢复时复用协议安全工具配对截断，坏行跳过并记录警告。
3. 恢复后根据成员 Worktree 创建独立 `AgentState`、权限、ContextManager 和 FileReadCache。
4. 超出上下文预算时在首次请求前执行现有压缩流程。
5. 恢复失败时标记成员失败，不从空白历史继续。
6. 保存 idle 后再次唤醒所需的最小运行快照。

**验证：**

- `tests/test_team_member_runner.py` 先覆盖正常恢复、坏行、孤立工具调用、超限压缩和失败保护。
- 两成员使用相同相对路径时，断言缓存和历史仍独立。

### T13 长期成员运行循环

**依赖：** T12

**步骤：**

1. 实现等待 assignment/wake/stop 邮件的长期循环。
2. 收到任务后校验依赖和归属，认领任务并更新 working 状态。
3. 对审批成员先运行只读规划阶段，提交结构化申请并进入 waiting_approval。
4. allow 后动态开放副作用工具；deny 后把反馈注入新一轮规划。
5. 运行 `run_agent_loop()` 到 final/error/cancel，更新任务结果和 Token 用量。
6. 发送 completion 与 idle 消息，持久化后继续等待而不销毁上下文。

**验证：**

- Fake Provider 场景覆盖无需审批、allow、deny 后重提、工具调用被拦、失败和停止。
- 证明 idle 后第二个任务继续使用上一轮历史且不重新创建 Worktree。

### T14 TeamManager 生命周期

**依赖：** T3、T4、T5、T6、T7、T8、T9、T10、T13

**步骤：**

1. 实现团队创建、列表、详情、恢复和关闭。
2. 创建时记录仓库 ID、目标分支和基线提交，原子建立 TeamStore。
3. 实现成员添加、重名/上限检查、Worktree 准备、后端选择和启动。
4. 按“停止后端 → 更新状态”顺序实现成员停止。
5. 实现消息发送后的 backend wake；失败只产生警告，不回滚已投递消息。
6. 实现线程安全 TeamEvent 队列和实际后端可见事件。
7. 单个成员失败只更新该成员并通知 Lead。

**验证：**

- `tests/test_team_manager.py` 覆盖创建/恢复、双成员、显式后端失败、wake 警告、停止顺序和故障隔离。
- 重启 Manager 后恢复相同 roster、任务和审批状态。

### T15 Team 管理与协作工具

**依赖：** T14

**步骤：**

1. 实现 `Team` 的 create/resume/list/status/spawn/stop/close 操作与 Schema 校验。
2. 实现 `TeamTask` 的 CRUD、认领和状态操作。
3. 实现 `TeamMessage` 的 send/broadcast/inbox/read 操作。
4. 实现 `TeamPlanRequest` 和 Lead 专属 `TeamPlanDecision`。
5. 所有异常转换为带 code、details 和摘要的 `ToolResult`。
6. 工具结果只返回必要状态，不泄露完整会话、密钥或环境变量。

**验证：**

- `tests/test_team_tools.py` 覆盖参数错误、未知对象、正常结果和角色越权。
- 工具集通过 Provider ToolSpec 序列化测试。

### T16 Agent 工具选择与审批执行复核

**依赖：** T11、T14、T15

**步骤：**

1. 扩展 Agent 每轮工具选择，接受 TeamRuntimeIdentity 和 Scoped Registry。
2. 在批处理前复核审批与 coordinator 策略，历史或伪造调用也不能绕过。
3. Team 工具不进入 Plan Mode 的普通读工具交集，但按作用域保留必要系统操作。
4. 普通 Subagent 过滤集合加入所有 Team 工具。
5. 保持 Skill 白名单、Hook 拒绝、权限引擎和 Team 过滤的确定顺序。
6. 增加回归测试，确认现有 Skill/Plan/Agent 工具行为不变。

**验证：**

- `tests/test_team_scoping.py` 增加 Agent Loop Fake Provider 越权调用场景。
- 运行现有 `test_agent*`、`test_skills_*`、`test_subagent_filtering.py`。

### T17 集成 Git 基础流程

**依赖：** T7

**步骤：**

1. 定义并原子持久化 `IntegrationRecord`。
2. 从已完成任务构造成员分支拓扑顺序，去重同一成员的多个任务。
3. 校验成员 Worktree 干净且分支相对基线存在提交。
4. 创建专用集成 Worktree 和分支，记录目标提交与尝试前提交。
5. 用参数数组、`shell=False` 按序合并成员分支并记录进度。
6. 冲突时保留集成 Worktree 并标记 conflicted，不修改用户工作区。

**验证：**

- `tests/test_team_integration.py` 在临时仓库覆盖拓扑顺序、重复成员、未提交/脏状态、双分支无冲突合并和冲突保留。

### T18 Resolver、验证与安全发布

**依赖：** T17

**步骤：**

1. 实现 resolver 对集成 Worktree 的独占租约，其他成员不能进入。
2. Resolver 成功提交后继续集成；失败时仅在可信集成清单内执行 merge abort 和恢复。
3. 在集成 Worktree 顺序运行 `integration_checks`，记录命令、退出码和裁剪摘要。
4. 发布前再次比较目标分支与 expected commit，并检查目标工作树状态。
5. 目标未变化时优先 `ff-only`；已检出且脏或已变化时拒绝发布并保留 ready 分支。
6. 实现显式 abort 和重复调用幂等。

**验证：**

- 覆盖 resolver 成功/失败、检查失败、目标漂移、目标脏、发布成功、重复发布和 abort。
- 每个失败场景断言用户工作区文件与原目标 ref 未被意外修改。

### T19 TeamIntegrate 工具与 Lead 状态注入

**依赖：** T15、T16、T18

**步骤：**

1. 实现 `TeamIntegrate` 的 check/start/status/continue/abort/publish 操作。
2. 限制模型提供任意 Git 参数，所有分支来源由 TeamStore 推导。
3. 为 PromptContext 增加精简 Team 快照和 Coordinator 状态。
4. 渲染高优先级 Lead/成员指令块，列出阻塞任务、待审批和未读消息摘要。
5. 团队事件采用租约式动态上下文，API 请求成功后确认，失败时释放。
6. 控制状态块大小，不注入完整邮箱或完整任务历史。

**验证：**

- Prompt 测试覆盖普通 main、Lead、成员和 Coordinator 四种块。
- Fake Provider 测试事件在请求失败后仍可重投，成功后不重复。

### T20 内部 Team Worker 入口

**依赖：** T19

**步骤：**

1. 给 `huicode/__main__.py` 和 CLI 参数解析增加隐藏的 `--team-worker`、team path、member ID、config path 参数。
2. Worker 启动时验证 Team 路径、成员身份、仓库和 Worktree 清单。
3. 从配置文件加载 Provider，不从命令行接收密钥。
4. 组装 TeamMemberRunner 并持续显示成员状态，收到 stop 后有序退出。
5. 普通 CLI 参数和 `python -m huicode --config ...` 行为保持不变。

**验证：**

- `tests/test_team_cli.py` 通过 Fake Runner 验证参数分流、身份不匹配、密钥不在命令和正常关闭。
- 运行现有 CLI 参数与启动测试。

### T21 CLI 生命周期、事件泵与 TUI

**依赖：** T20

**步骤：**

1. 普通 CLI 在 teams enabled 时构造 TeamManager 和 Team 入口工具。
2. 创建/恢复团队后动态切换 main/team_lead 身份，并在状态栏显示 Team、模式和 Coordinator。
3. 启动 TeamEvent 通知泵，使用 `run_in_terminal` 渲染成员、消息、审批、idle 和集成事件。
4. `/clear` 仅清主聊天状态，不销毁长期团队；退出 CLI 关闭本进程资源但保留可恢复团队。
5. CLI 关闭顺序为事件泵、TeamManager 后端、普通 Subagent、Worktree 清理和其他既有管理器。
6. 配置错误和恢复错误在进入 TUI 前给出中文诊断。

**验证：**

- `tests/test_team_cli.py` 覆盖初始化、身份切换、状态栏、事件渲染、关闭顺序和旧配置回归。
- Fake prompt session 验证后台事件不会破坏当前输入缓冲。

### T22 团队删除与故障恢复保护

**依赖：** T15、T18

**步骤：**

1. 删除前汇总活动成员、未完成任务、未读消息、待审批、未发布集成和 Worktree 保护状态。
2. 任一保护命中时返回逐项原因，不执行删除。
3. 安全删除按“停止后端 → 删除可删 Worktree → 删除 Team 元数据”执行。
4. 任一步失败停止后续破坏性步骤，并保留可恢复状态。
5. 关闭团队只停止成员并标记 closed，不删除邮箱、会话、分支或 Worktree。
6. 重复 close/delete 保持幂等或返回明确终态。

**验证：**

- `tests/test_team_manager.py` 覆盖每一种保护条件、部分清理失败、重复关闭和安全删除。
- 断言一个团队删除失败不会触及另一个团队目录。

### T23 文档与配置示例

**依赖：** T21、T22

**步骤：**

1. README 增加 `teams` YAML 完整字段、默认值和 `HUICODE_COORDINATOR=1` 双锁说明。
2. 说明 auto 后端优先级、explicit terminal 失败语义及实际后端展示。
3. 说明 Team/Task/Message/Plan/Integrate 工具的典型工作流。
4. 说明所有成员强制 Worktree、idle 恢复和集成分支保护。
5. 给出 Windows PowerShell 与 Linux/macOS 的环境变量示例。
6. 若实现中发生真实返工，追加 `docs/mew-spec-pitfalls.md`，否则不制造记录。

**验证：**

- README YAML 示例通过当前配置解析器。
- 文档中的工具名和参数与实际 Schema 对照一致。

### T24 端到端验收场景

**依赖：** T23

**步骤：**

1. 在临时 Git 仓库启动 Fake Provider CLI，创建团队与两个协程成员。
2. 建立有依赖的两个任务，让成员在各自 Worktree 提交不同修改并互发消息。
3. 让其中一名成员经过计划申请、驳回、重提和批准后执行。
4. 验证成员完成后 idle，再发送新任务并恢复原历史。
5. 在专用集成 Worktree 合并、运行检查并发布，确认发布前主工作区不变。
6. 单独运行冲突场景，确认中止后目标分支与用户工作区不变。
7. 无 tmux 环境使用 Mock Terminal Backend 验证选择和命令；在验收报告明确记录替代方式。

**验证：**

- `tests/test_team_cli.py` 或独立 E2E 测试完整通过。
- 端到端证据包含 Team 状态、后端、任务、审批、消息、Worktree、idle 恢复和集成结果。

### T25 全量回归、验收报告与提交

**依赖：** T24

**步骤：**

1. 运行全部 Team 专项测试。
2. 运行完整 unittest 测试集。
3. 运行 `python -m compileall huicode tests`。
4. 运行 `git diff --check`。
5. 逐项执行 `checklist.md` 并记录实际证据。
6. 生成 `specs/016-agent-team/acceptance_report.md`。
7. 检查用户已有未跟踪文件未被修改、删除或暂存。
8. 仅暂存本章相关文件，按 `AGENT.md` 创建 Git 提交。

**验证：**

- 自动化测试、编译和 diff 检查全部通过。
- 验收报告将每个 AC 映射到测试或端到端证据。
- `git diff --cached --name-only` 只包含本章文档、实现、测试和必要 README/踩坑文档。

## 执行顺序

1. T1 Team 配置与领域类型
2. T2 名称、标识与路径安全
3. T3 文件锁与基础持久化
4. T4 共享任务存储
5. T5 名称注册表与邮箱
6. T6 计划审批闸门
7. T7 Team Worktree 适配
8. T8 后端协议与选择器
9. T9 协程成员后端
10. T10 终端成员后端
11. T11 运行身份与工具作用域
12. T12 成员会话与上下文恢复
13. T13 长期成员运行循环
14. T14 TeamManager 生命周期
15. T15 Team 管理与协作工具
16. T16 Agent 工具选择与审批执行复核
17. T17 集成 Git 基础流程
18. T18 Resolver、验证与安全发布
19. T19 TeamIntegrate 工具与 Lead 状态注入
20. T20 内部 Team Worker 入口
21. T21 CLI 生命周期、事件泵与 TUI
22. T22 团队删除与故障恢复保护
23. T23 文档与配置示例
24. T24 端到端验收场景
25. T25 全量回归、验收报告与提交

## 任务覆盖自检

- `plan.md` 中的配置、类型、命名、锁、存储、任务、邮箱、审批、后端、Worktree、作用域、Runner、Manager、集成、Prompt、CLI 和 TUI 均有实施任务。
- 每项任务都声明依赖、具体步骤和可执行验证方法。
- 并发存储与安全闸门先于成员运行；成员运行先于工具和 CLI 接线；集成基础先于发布。
- 普通子 Agent 工具隔离、Coordinator Bash 绕过、目标分支漂移和用户工作区保护均有专门测试任务。
- 端到端与全量回归位于实现任务之后，最终提交只包含本章相关文件。
