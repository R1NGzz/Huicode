# T9：Runtime 取消与资源预算

## 状态与关联

- 日期与里程碑：2026-09-28，任务 T9，里程碑 M1。
- 状态：**已实现并验证**（47 项单元测试）。
- 代码：`huicode/server/runtime/cancellation.py`、`limits.py`、`executor.py`、`errors.py`。
- 测试：`tests/server/test_runtime_limits.py`。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 Resource budget and execution boundary、
  [task.md](../../specs/017-web-studio/task.md) 的 T9。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

一个 Web 上的 Agent Run 有三个必须回答的问题：**能不能停**、**最多花多少**、**停下来之后是什么状态**。

CLI 里这三个问题都可以含糊：用户按 Ctrl+C 就是停，钱花超了下次注意，进程退出就完事。
服务端不行——Run 是数据库里的一行，它有租约、有 Worker 在跑、有前端在等。最糟的
状态不是失败，而是**永远停在运行中**：前端一直转圈、租约永不释放、用户不知道能不能重试。

所以 T9 的目标不是"限制得多严"，而是：**无论内部抛什么异常、取消从哪个方向来，
Run 都要落到一个明确的终态**。

## 原理与数据流

```text
CancelToken（cancellation.py）
   取消是协作式的：一层层往下传令牌，由各执行边界自己检查
   父 → 子 传播；子 ↛ 父（工具超时不该干掉整个 Run）

BudgetTracker（limits.py）
   账本 + 检查点：迭代数、工具调用数、输出字节、运行/工具/SHELL 时限

run_under_budget（executor.py）
   把 work 放进上面两者的边界里，保证一定返回 RunResult
        │
        ▼
   RunResult(status, error_code, usage)
        │  terminal_event_type ∈ {run_completed, run_cancelled, run_failed}
        ▼
   T16 转成 RuntimeEvent；T13 落 Run 状态机
```

**为什么不用 `asyncio.Task.cancel()`。** Agent 的大部分工作是**同步阻塞**的：工具
`run()` 是同步函数（`huicode/tools/*.py`），Shell 是 `subprocess.run`。这些代码块里
没有 await 点，Task.cancel() 根本传不进去。取消只能是协作式的。

**检查点分布在五处**（T16 把它们插进 Agent Loop 的调用点）：

| 位置 | 方法 | 管什么 |
| --- | --- | --- |
| 每轮循环开头 | `before_iteration()` | 迭代计数 + 运行时限 |
| 模型请求之前 | `before_model_request()` | 运行时限 |
| 工具调用之前 | `before_tool_call()` | 工具调用计数 + 本次工具时限 |
| 工具调用之后 | `after_tool_call()` | **只记录**超时，不抛异常 |
| 输出产生时 | `record_output(n)` | 累计输出字节 |

## 方案与取舍

### 取消：单向传播

父令牌取消必然导致子令牌取消（Run 停了，它的工具不能继续跑）；**反过来不成立**——
单个工具超时不该把整个 Run 干掉，Run 还有别的路可走。这个不对称是这里最容易写反的
地方，两个方向都有断言（`test_parent_cancellation_reaches_the_child` /
`test_child_cancellation_does_not_reach_the_parent`）。

已经取消的父令牌，派生出的子令牌**直接就是取消状态**。否则会出现"Run 已经停了，
新派生的工具令牌还活着、还能跑"。

### 最先到的原因胜出

用户点取消和运行超时可能几乎同时发生。后到的原因不覆盖先到的——先到的那个才是
真正解释这次停止的原因。`cancel()` 因此是幂等的，第二次调用返回 `False`。

### 超时不是用户取消

两者在运维上含义相反：一个是有人在操作（正常），一个是我们的限制在生效（要关注）。
所以 `run_cancelled` 和 `run_timeout` 是两个码。把所有失败塞进一个 `failed` 里，
运维侧就只能看到"失败率上升"，分不出是哪种。

### 工具超时：事前拦，事后只记录

工具已经跑完了，副作用（改了文件、发了请求）已经发生。此时再抛超时异常只是丢掉一个
已经产生的结果，**撤不回副作用**。所以 `after_tool_call` 返回"是否超时"并记进
`BudgetUsage.tool_overruns`，真正的截断交给 T12 在进程层面杀子进程树。

### 完成还是取消：两种误报取轻的

工作可能在取消生效的同时正常返回。这时报 `cancelled`：

- 报错方向的代价：用户以为任务完成了、实际只做了一半，于是**不再检查**。
- 这个方向的代价：用户偶尔看到一次"其实已经做完"的取消，检查一下就明白了。

不对称，选小的那个。

### 时间源可注入

`BudgetTracker(clock=...)`。否则"等了 1800 秒"这类测试只能真的 sleep，既慢又不稳。

## 实施难点与工程问题

### 问题一：已经取消的 Run 还是会跑

- 触发条件：父令牌已取消时调用 `run_under_budget`。
- 症状：测试 `test_an_already_cancelled_parent_does_not_run_the_work` 失败——
  `work` 里第一行就执行的代码**跑了**。
- 根因：派生出的子令牌确实已经是取消状态，但 `ensure_future(work(...))` 仍然会把
  协程调度起来；它要等到**第一个检查点**才会发现取消。也就是说"取消"和"没开始"
  是两件事，中间有一段什么都不设防的空窗。
- 修改：`derive()` 之后立即判断，已取消就直接返回终态，一个字节的工作都不开始。

这条是**测试写出来才发现的**，不是设计时想到的。

### 问题二：自己强杀的进程被当成外部取消抛了出去

- 触发条件：工作者不检查令牌（例如卡在不可中断的调用里），宽限期到期后被强制停下。
- 症状：`asyncio.CancelledError` 从 `run_under_budget` 里冒出来，而不是返回终态。
- 根因：区分"外部 cancel 了这个任务"和"我们自己强杀了工作者"时，只看
  `work_task.cancelled()`——而**强杀也会让它为真**。
- 修改：`_wind_down` 返回 `(detail, 是否强杀)`，只有非强杀的那条才重新抛出。
- 回归：`test_worker_that_ignores_the_token_is_force_stopped`。

### 问题三：测试助手绕过了自己刚写的校验

- 触发条件：测试里写 `_budget(max_run_seconds=100)`，其余字段保持默认
  （`max_tool_seconds=120`）。
- 症状：13 个测试在 `setUp` 里就 `ValueError`，看起来像被测代码坏了。
- 根因：`ResourceBudget.__post_init__` 强制 `shell ≤ tool ≤ run`，而测试助手只改了
  运行时限。
- 修改：测试助手在改小运行时限时同步收窄。**这条其实是校验在正常工作**——
  它挡住了一个真实的不合理组合。唯一需要调整的是那个专门测校验本身的用例，
  它改成直接构造 `ResourceBudget`，不再经过会收窄的助手。

### 一处刻意的删除

`CancelToken.wait_for_cancel(timeout)` 写完之后发现**没有任何生产调用方**——执行器
用的是 `asyncio.wait` 竞速。没有调用方的公开 API 是负债（将来别人会以为它在被用），
所以删掉了。T12 真需要时再加。

## 验证证据

环境：仓库自带 `.venv`，Python 3.12.14，Windows 11。

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m pytest tests/server/test_runtime_limits.py -q
```

- 预计与实际：**47 passed**（T10 时该文件增至 48 项：`AgentRunRequest` 的
  `permission_snapshot` 变成必填之后补的一条用例，加在 `ResultContractTests` 里）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**645 passed, 14 skipped**（T11 时 598 + 47）。

关键断言（按"能挡住什么"排列）：

- `test_an_already_cancelled_parent_does_not_run_the_work`：**断言的是"没跑"，
  不是"返回了 cancelled"**。上面问题一的护栏。
- `test_external_task_cancellation_is_not_swallowed`：外部 `task.cancel()` 必须
  原样抛 `CancelledError`。吞掉它会破坏 asyncio 的结构化并发。
- `test_a_worker_that_finishes_anyway_after_cancel_is_not_reported_as_success`：
  终态的误报方向。
- `test_the_deadline_checkpoint_reports_the_same_code_as_the_watchdog`：
  超时的两条路径必须是同一个码。
- `test_child_cancellation_does_not_reach_the_parent` / 反向那条：传播方向。
- `test_result_never_exceeds_the_limit`（按 limit 参数化 4 次）+
  `test_multibyte_characters_are_not_split`：字节截断不能切碎 UTF-8。
- `test_from_limits_does_not_silently_drop_a_new_field`：字段集合必须与
  `RuntimeLimits` 一致，加新配置项而忘了搬运时这条会失败。

**未覆盖场景与残余风险：**

- **没有接进任何真实 Agent Loop。** 现在验证的是"检查点本身正确"，不是"运行时真的
  会被停住"。接线是 T16（`huicode/agent.py` 在 T16 的 Files 里，不在 T9 的）。
- **强杀工作者时不保证副作用回滚。** 工作者可能在改文件的中途被强杀。这需要 T15 的
  幂等记录 + 恢复扫描，T9 只管"停住"。
- **`max_child_processes` 没实现。** plan.md 的 `ResourceBudget` 有七项，这里只做了
  有执行者的六项。先加一个没人执行的配置项比不加更糟——它会让配置文件看起来已经
  限制了进程数。**欠账记给 T12**（它才有子进程树终止）。
- **没有集成测试。** T9 不碰数据库，全部逻辑在进程内，所以这项能力本来就没有持久化
  边界可测。这不是省略。
- **`CancellationState.requested_at` 目前没有消费方。** 取消时刻会由 T13 的取消接口
  写进审计。现在留着是因为一个没有时间戳的取消记录很难用。
- **`output_bytes` 的上限与 `ToolContext.max_output_chars`（6000 字符）不是一套。**
  前者是 Run 级累计字节预算，后者是单次工具输出的字符截断。两者都生效，但**没有
  对齐过**，一个中文密集的任务可能先撞字符截断、也可能先撞字节预算。
- **没有任何真实的超时/取消性能测量。** 看门狗是 `asyncio.sleep` + 一个令牌，代价
  应当可以忽略，但没测过。
- 输出预算按**字节**记账而 `record_output` 的调用方要给对数字——T16 接线时若传的是
  字符数，中文场景会低估 3 倍。这条只能靠 T16 的用例兜住。

## 自己动手

**复现实验**

1. ```powershell
   $env:PYTHONIOENCODING="utf-8"
   .\.venv\Scripts\python.exe -m pytest tests/server/test_runtime_limits.py -q
   ```
   预期：47 passed。

2. 亲眼看到"取消传播是单向的"：

   ```powershell
   .\.venv\Scripts\python.exe -c "from huicode.server.runtime.cancellation import CancelToken; p=CancelToken(); c=p.derive(); c.cancel('timeout'); print('子:', c.is_cancelled(), '父:', p.is_cancelled())"
   ```
   预期：`子: True 父: False`。反过来再做一次
   （`p.cancel('user')` 之后 `print(c.is_cancelled())`）预期是 `True`。

3. 看"完成与取消同时发生时报什么"：

   ```powershell
   .\.venv\Scripts\python.exe -c "import asyncio; from huicode.server.runtime.cancellation import CancelToken; from huicode.server.runtime.executor import run_under_budget; from huicode.server.runtime.limits import ResourceBudget; async def w(t,k): await t.wait(); return 'partial'; async def m(): tok=CancelToken(); task=asyncio.ensure_future(run_under_budget(w, budget=ResourceBudget(), token=tok)); await asyncio.sleep(0); tok.cancel('user'); r=await task; print(r.status, r.error_code); asyncio.run(m())"
   ```
   预期：`cancelled run_cancelled`。注意工作者其实**正常返回了值**，仍然报取消。

**小改动练习**

把 `run_under_budget` 改成"完成优先"（工作正常返回就报 completed，不管令牌），
然后回答：这个改动让哪个用户场景变得危险？

- 会影响什么：`test_a_worker_that_finishes_anyway_after_cancel_is_not_reported_as_success`
  会失败。
- 如何验证：跑上面第 3 步，输出会变成 `completed None`。再想清楚：一个被取消的
  Agent 任务，如果前端显示"已完成"，用户会不会去检查它到底改了什么？

**自测问题**

1. 原理：为什么取消要用令牌传递，而不是 `asyncio.Task.cancel()`？
2. 异常路径：工作者不检查令牌、一直卡着，`run_under_budget` 会怎么处理？终态是什么？
3. 取舍：为什么"工具已经超时"只在事后记录，而不是抛异常？

**答案核对**

1. 因为 Agent 的多数工作是同步阻塞的（工具 `run()`、`subprocess.run`），中间没有
   await 点，Task.cancel() 传不进去。见 `cancellation.py` 的模块文档。
2. 宽限期（默认 5 秒）后强制 `work_task.cancel()`，返回 `cancelled`，并把
   `detail="cancellation_wind_down_timeout"` 记进终态——**这个标记也是区分"外部取消"
   和"我们强杀"的依据**。见 `_wind_down`。
3. 因为工具已经执行完，副作用已经发生；抛异常只丢结果，撤不回副作用。见
   `limits.py` 的模块文档与 `after_tool_call`。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> 服务端的一次 Agent 运行最糟的终态不是失败，而是永远停在运行中。所以我做的不是
> "限制得多严"，而是保证无论抛什么异常、取消从哪个方向来，都有一个明确的终态。
> 三个决定值得一提：第一，取消用令牌往下传而不是 `Task.cancel()`，因为 Agent 的
> 大部分工作是同步阻塞的，Task.cancel() 传不进去——只能协作式地一层层检查；
> 第二，传播是**单向**的，Run 取消必然停掉它的工具，但单个工具超时不会干掉整个 Run；
> 第三，工具超时只在事前拦、事后只记录，因为工具跑完时副作用已经发生，抛异常只是
> 丢掉结果、撤不回副作用。测试里真正抓到问题的两条是：已取消的父令牌派生出的工作
> **仍然会被调度起来**跑到第一个检查点，以及自己强杀的工作者会被误判成外部取消。

**深入追问**

- 问：你怎么保证 Run 不会永远停在运行中？答：`run_under_budget` 有五条出口，每条都
  返回 `RunResult`；唯一重新抛出的是**外部** `CancelledError`——那不是 Run 的取消，
  是调用方在收回协程，吞掉它会破坏结构化并发。
- 问：这套东西真的停住过任务吗？答：**没有。** 只有单元测试，接线在 T16。现在能说的
  是"检查点与终态正确"，不能说"运行时取消已经可用"。

**简历候选表述**：证据到「取消令牌 + 六项预算 + 统一错误码 + 47 项测试」。
可表述为「实现协作式取消与资源预算，并保证运行一定有终态」，**不要**说成
"实现了任务超时中断"——真正的进程级中断是 T12。

**不能声称的能力或结果**：

- 不能说「运行时取消已经生效」——没有接进 Agent Loop（T16）。
- 不能说「超时的工具会被杀掉」——进程树终止是 T12。
- 不能说「子进程数受控」——`max_child_processes` 没实现。
- 不能说「强杀之后状态一致」——副作用回滚要等 T15 的幂等与恢复。

## 后续

- **欠账 1（给 T12）**：`max_child_processes` 落地时，`RuntimeLimits`、`ResourceBudget`
  和 `README` 的字段对照要一起更新——`test_from_limits_does_not_silently_drop_a_new_field`
  会失败，这是刻意的路标。
- **欠账 2（给 T16）**：把五个检查点插进 `huicode/agent.py` 的调用点，
  `record_output` 的实参必须是**字节数**。
- **欠账 3（给 T13）**：取消时刻（`CancellationState.requested_at`）写进审计。
- **交给 T15**：强杀工作者时的副作用一致性，靠幂等记录 + 恢复扫描兜。
- 用户练习反馈：**待用户自测**。
