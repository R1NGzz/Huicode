# T10：工具能力声明与权限桥接

## 状态与关联

- 日期与里程碑：2026-09-28，任务 T10，里程碑 M1。
- 状态：**已实现并验证**（41 项测试）。
- 代码：`huicode/server/runtime/capabilities.py`（策略）、`huicode/server/runtime/permission_bridge.py`、
  `huicode/tools/base.py`（能力词表）、六个内置工具与 `huicode/mcp/tools.py` 的能力声明。
- 测试：`tests/integration/test_permission_bridge.py`（不需要数据库，`pytest tests` 一定跑到）。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 Runtime adapters、
  [task.md](../../specs/017-web-studio/task.md) 的 T10、checklist C49–C51、C54。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

CLI 里"这个工具能不能跑"由 `huicode/permissions/engine.py` 判断：危险命令黑名单、
路径沙箱、内部状态保护、规则匹配、三种权限模式。这套东西已经在跑了，Web 端需要的
是同一套语义——C9/AC9 明确要求 Web 与 CLI 行为一致。

于是有两个错误做法：

1. **在服务端重写一套权限判断。** 两边会慢慢分叉，最后没人说得清"到底哪套在生效"。
2. **直接把 CLI 的那份搬过来用。** 它假设有一个能阻塞等人的 `confirmer`，而且它
   只有一个布尔 `side_effect`，回答不了"这个工具会不会出网"。

T10 做的是**适配**：把服务端的情况译成那套引擎能吃的输入，在它前面补两道服务端
特有的检查，在它后面把结论译成事件。

## 原理与数据流

```text
PermissionSnapshot（服务端构造：工作区、允许的工具集、模式、Plan Mode、规则）
        │
        ├─ build_permission_context() ──→ PermissionContext（既有引擎的输入）
        │
        └─ evaluate_call(call, registry, snapshot)
              ├─ 1. 工具必须存在且在允许集合内 ──────── C54
              ├─ 2. Plan Mode 只放行"只能读"的工具 ───── C50
              ├─ 3. 未声明能力的工具不得自动放行 ─────── C49
              └─ 4. 既有引擎：黑名单/沙箱/内部状态/规则/模式
                          │
                          ▼
              allow            → 无事件
              request_approval → tool_approval_requested（T14 补 approval_id）
              deny             → error 事件（只带安全分类）── C51
```

**能力词表在 `huicode/tools/base.py`，策略在 `server/runtime/capabilities.py`。**
工具要声明能力，而工具不能反向依赖服务端——所以"有哪些能力"必须在核心包，
"怎么由能力推风险"才属于服务端策略。

## 方案与取舍

### 未声明 = 高风险，而不是"按只读放行"

这是本任务唯一最重要的默认值。声明写在工具类上，新工具的作者会被测试和评审推着
想清楚它到底能干什么；而"没写就按只读放行"会让一个新工具在没人注意的时候拿到写
权限。两种默认值的代价不对称。

同一条思路还有两个推论：**能力名不认识也按高风险**（将来有人把 `file_write` 拼成
`filesystem_write`，忽略它等于把这个工具当成只读），**Plan Mode 下未声明的工具不放行**
（不能因为没写就当成只读）。

### Bash 声明成"什么都能干"

`RunCommandTool.capabilities` 是全部五项，不是只写 `shell`。这是**准确**而非保守：
一条任意命令既能读、能写文件、能出网、也能调用外部副作用。少声明会让信任声明的
策略低估它。

注意只读命令（`dir`、`git status`）的低风险处理**不在这里**——那是 `engine.py` 按
**命令内容**判断的。能力描述的是"这个工具能做什么"，不是"这一次调用做了什么"。

### 没有同步确认器：需要确认 = 一次审批请求

CLI 可以阻塞等用户敲 y/n；服务端不能占着线程等人。所以 `build_permission_context`
**不传 confirmer**，引擎返回"需要确认"时桥接把它翻译成 `tool_approval_requested`，
Run 停在等待审批（T14 的 ApprovalBroker 负责唤醒）。

顺带一个副作用是好的：`persistent_path` 也留空，"永久允许"不能写到本地 YAML，
必须落库走审批流程。

### 拒绝事件只带分类，不带引擎的原始原因

引擎的 `decision.reason` 在命中规则时是 `命中权限规则 Bash(rm -rf *): deny`——
**那是用户的权限配置**，而事件对工作区所有成员可见。所以事件载荷里的 `message`
只能从 `CATEGORY_MESSAGES` 这张表里查，测试里有一条断言"载荷里的 message 必须能在
分类表里查到"，把这条路堵死。

审批请求是例外：它必须带上 `target`（要跑的命令 / 要写的路径），否则审批人不知道
自己在批准什么。那部分内容可能含密钥，但它走 `store.append` 落库，脱敏在那条路径上
（T11）。

### 权限状态由服务端构造，传什么都覆盖掉

`evaluate_call` 无论调用方传进来什么 `ToolContext`，都会用快照重建的
`PermissionContext` 覆盖掉里面的 `permissions`。这不是洁癖：只要"用哪个权限模式"
存在一条从请求参数到判断的路径，C54 就不成立。

配套地，T9 的 `AgentRunRequest` 把 `permission_snapshot` 改成**必填**。让它可选会留出
一条"忘了传就当没有权限限制"的路径，而这正是 C54 要挡的；必填的话漏传是启动就报错。

### permissive 模式不被"未声明"升级架空

未声明能力的工具不走自动放行——但 `permissive` 模式除外。那是运维明确选择的
"放行未匹配规则的调用"，不该被一条默认值架空。同理，**显式允许规则**也算人的决定，
优先于默认值（测试 `test_an_explicit_allow_rule_lifts_the_undeclared_escalation`）。

判断"是不是自动放行"用的是引擎给的 `decision.source == "mode"`，而不是去重新匹配
一遍规则。**这是一个刻意的选择**：自己再匹配一次等于把规则逻辑抄了一份，将来必然
分叉。

## 实施难点与工程问题

### 问题一：能力词表放错了包

- 触发条件：第一版把 `READ`/`FILE_WRITE` 等常量放在 `server/runtime/capabilities.py`，
  工具从那里 import。
- 症状：没有测试失败——`huicode/tools/files.py` 开始依赖 `huicode/server/`。
- 根因：**工具是 CLI 与 Web 共用的，服务端不是它的上游。** 这个方向一旦建立，
  "服务端能改的东西"就变成了"CLI 也依赖的东西"。
- 修改：词表挪到 `huicode/tools/base.py`（`Tool` 协议就在那里，能力的声明契约也在
  那里），策略留在服务端并反向 import。改之前确认过：`huicode/tools` 与
  `huicode/server` 在此之前互不依赖。

这条是**自己审出来的**，没有测试会红——记在这里是因为它是个容易反复犯的方向错误。

### 问题二：测试里的期望搞错了系统工具在 Plan Mode 下的行为

- 触发条件：`test_system_tools_still_pass_in_plan_mode` 断言系统工具在 Plan Mode 下
  是 `allow`。
- 症状：实际是 `request_approval`。
- 根因：**被测代码是对的，测试的期望错了。** CLI 的 `_plan_mode_denial` 对系统工具
  返回 `None`（不受 Plan Mode 限制），然后它照常走常规权限判断——一个能写文件的
  系统工具在 default 模式下本来就需要确认。"不受 Plan Mode 限制"不等于"放行"。
- 修改：断言改成"**不是**被 Plan Mode 挡下的"，并补了一条只读系统工具确实放行的用例。
- 教训：把"某个检查不生效"写成"结果是 allow"是很容易犯的断言错误。**区分"这道闸
  没拦"和"整个流程通过"。**

## 验证证据

环境：仓库自带 `.venv`，Python 3.12.14，Windows 11。

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_permission_bridge.py -q
```

- 预计与实际：**41 passed**。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**687 passed, 14 skipped**（T9 时 645 + 41 + 1）。
  多出来的那 1 项在 `tests/server/test_runtime_limits.py`：`AgentRunRequest` 的
  `permission_snapshot` 变成必填之后补的一条，见下。

关键断言（按"能挡住什么"排列）：

- `test_arguments_cannot_smuggle_a_permission_override`：调用参数里塞
  `permission_mode=permissive`、`skip_permissions=True`、`allowed_tools=["*"]`，
  结论与不带这些参数时**逐字段相同**。这是 C54 最直接的那条。
- `test_a_caller_supplied_context_cannot_change_the_decision`：传进来一个
  `permissions` 是 permissive 的 `ToolContext`，`rm -rf /` 仍然被拒。
- `test_the_same_calls_get_the_same_verdict_on_both_paths`：3 种模式 × 6 个样本，
  直接问引擎与经过桥接问，结论必须一致——"适配而不是重写"的证据。
- `test_the_payload_never_carries_the_rule_text` + `test_payload_messages_come_only_from_the_category_table`：
  C51 的两条护栏。
- `test_side_effect_and_capabilities_do_not_contradict_each_other`：`side_effect`
  与能力声明说的是同一件事，不一致就说明有一处写错了。
- `test_an_unknown_permission_mode_falls_back_to_strict`：认不出的模式按最严格来。
- `test_mcp_tools_declare_network_and_external_side_effects`。

**未覆盖场景与残余风险：**

- **没有接进真实 Agent Loop。** 桥接目前只被测试调用，接线是 T16（`huicode/agent.py`
  在 T16 的 Files 里）。
- **`tests/integration/` 里但没有数据库。** 它集成的是真实注册表、真实工具、真实
  权限引擎与真实临时目录，不需要 PostgreSQL，所以不设 skip。相应地 `__init__.py` 的
  说明也改了——把这类用例挂在环境变量后面等于平时不跑。
- **审批只是发出了事件，没有人实现"等待"。** 唤醒、超时、幂等都在 T14。
- **C53（网络策略）没有归属。** "deny 模式阻止网络访问、allowlist 只允许配置目标"
  既不在 T10 的步骤里也不在 T12 的步骤里。现在能做的只是**声明** Bash 有 `network`
  能力，没有实际的网络出口管控。**这条要补进 plan.md 的任务划分。**
- **只声明了 6 个内置工具 + MCP。** skills、subagents、teams 下的工具没有声明，
  因此按高风险处理（需要审批）。这是默认值在正常工作，不是遗漏；但**没有为它们
  写过任何验证**。
- **`allowed_tool_names` 的生成逻辑还不存在。** 快照由谁按什么规则构造（项目设置？
  工作区角色？）是 T13/T16 的事。现在空集合就等于全拒，语义上是安全的。
- **Plan Mode 按工具能力判断，不看命令内容。** default 模式下 `dir` 是低风险放行的，
  Plan Mode 下 `Bash` 整个被拒。这是**有意的**：一条命令的只读性只是启发式，而能力
  是声明出来的。代价是 Plan Mode 下连 `dir` 都不能跑。

## 自己动手

**复现实验**

1. ```powershell
   $env:PYTHONIOENCODING="utf-8"
   .\.venv\Scripts\python.exe -m pytest tests/integration/test_permission_bridge.py -q
   ```
   预期：41 passed。

2. 看六个内置工具的能力声明与推导出的风险：

   ```powershell
   .\.venv\Scripts\python.exe -c "from huicode.tools.registry import create_default_registry; from huicode.server.runtime.capabilities import summarise; r=create_default_registry('.'); [print(f'{t.name:8} {summarise(t)}') for t in r.list()]"
   ```
   预期：Read/Find/Search 是 `low`，Write/Edit 是 `medium`，Bash 是 `high`
   且列出全部五项能力。

3. **亲手制造一次"未声明就放行"**：把 `huicode/tools/shell.py` 里的
   `capabilities = ...` 那一行删掉，重跑第 1 步。

   预期：多条用例失败（`test_every_builtin_tool_declares_capabilities`、
   `test_shell_is_high_risk_because_it_can_do_everything` 等）。改回后恢复。
   这一步的目的是看到**默认值确实是"高风险"**，而不是"没写就跳过检查"。

**小改动练习**

给 `SearchCodeTool` 加上"只读 + 不出网"以外的第三种能力，比如声明它也可以
`file_write`（假设将来加一个"搜索并替换"的参数），然后回答：这会让 Plan Mode 下
`Search` 的行为怎么变？

- 会影响什么：`is_read_only` 变成 False，Plan Mode 下 `Search` 被拒；
  `test_read_tools_are_low_risk_and_read_only` 失败。
- 如何验证：跑第 1 步。再想清楚：一个新参数改变了工具的能力，是应该新增一个工具，
  还是给已有工具加能力？**能力是工具的属性，不是某次调用的属性**——所以答案通常
  是新增工具。

**自测问题**

1. 原理：为什么能力词表放在 `huicode/tools/base.py` 而不是服务端的策略模块里？
2. 异常路径：一个没有声明任何能力的工具，在 default 模式下会发生什么？在
   permissive 模式下呢？为什么两者不同？
3. 取舍：为什么拒绝事件不带引擎的原始 reason？

**答案核对**

1. 因为工具是 CLI 与 Web 共用的，服务端不是它的上游；工具反向依赖服务端会让
   "服务端能改的东西"变成"CLI 也依赖的东西"。见 `permission_bridge.py` 顶部注释。
2. default 下走"未声明能力的工具不得自动放行"→ `request_approval`；permissive 下
   放行，因为那是运维明确选择的"放行未匹配规则的调用"，不该被默认值架空。
   见 `evaluate_call` 里 `decision.source == "mode"` 那一段。
3. 因为 reason 在命中规则时包含规则原文，那是用户的权限配置，而事件对工作区所有
   成员可见。载荷里的 message 只能从分类表查。见 `CATEGORY_MESSAGES`。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> Web 端要复用 CLI 已有的权限判断，而不是另写一套——两边语义分叉之后没人说得清
> 哪套在生效。我做的事是**适配**：把服务端的情况译成那套引擎的输入，在它前面补两道
> 检查，在它后面把结论译成事件。三个决定值得一提：第一，工具的能力从"有没有副作用"
> 这个布尔量拆成了五项声明，而**未声明按高风险处理**——"没写就按只读放行"会让一个
> 新工具在没人注意的时候拿到写权限；第二，服务端没有同步确认器，所以引擎说"需要
> 确认"时，我把它翻译成一次审批请求事件，Run 停在等待审批，而不是占着线程等人；
> 第三，权限状态由服务端构造，调用方传进来的 `ToolContext` 里的权限部分一律被快照
> 覆盖——只要存在一条从请求参数到权限判断的路径，就谈不上"前端不可绕过"。
> 验证上我特意加了一条对照：同样一批调用，直接问引擎和经过桥接问，结论必须逐条
> 一致，这才说明桥接没有偷偷加判断。

**深入追问**

- 问：怎么证明参数改不了权限？答：有一条用例把 `permission_mode=permissive`、
  `skip_permissions=True`、`allowed_tools=["*"]` 塞进调用参数，断言结论与不带这些
  参数时逐字段相同；另有一条传进来一个 permissive 的 `ToolContext`，`rm -rf /` 仍被拒。
- 问：这套现在真的拦住过东西吗？答：**没有。** 只有测试调用过桥接，真实接线在 T16。
  现在能说的是"桥接自身的判断与非绕过性正确"，不能说"Web 运行时已经受控"。

**简历候选表述**：证据到「五项能力声明 + 权限桥接 + 41 项测试，含 CLI 一致性对照」。
可表述为「实现工具能力声明与权限桥接，复用既有权限引擎并保证服务端不可绕过」，
**不要**说成"实现了完整的权限系统"——它复用的是既有引擎，且尚未接进运行时。

**不能声称的能力或结果**：

- 不能说「Web 运行时已经受权限控制」——桥接还没接进 Agent Loop（T16）。
- 不能说「审批流程可用」——只发出了审批事件，等待与唤醒是 T14。
- 不能说「网络访问受控」——只有能力声明，没有出口管控（C53 无归属）。
- 不能说「所有工具都声明了能力」——skills/subagents/teams 下的工具没有，它们靠
  默认值兜底，没有验证。

## 后续

- **欠账 1（给 plan.md）**：C53 网络策略没有归属任务，需要补进 T10 或 T12。
- **欠账 2（给 T16）**：把 `evaluate_call` 接到工具执行之前，并把
  `PermissionSnapshot` 的构造接进会话创建流程。
- **欠账 3（给 T13/T16）**：`allowed_tool_names` 由谁按什么规则生成。
- **交给 T14**：审批请求的 approval_id、等待、超时与幂等。
- 用户练习反馈：**待用户自测**。
