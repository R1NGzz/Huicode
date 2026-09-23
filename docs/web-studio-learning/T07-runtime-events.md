# T7：统一 Runtime Event 类型与映射

## 状态与关联

- 日期与里程碑：2026-09-23，任务 T7，里程碑 M1。
- 状态：**已实现并验证**（26 项单元测试）。
- 代码：`huicode/server/events/types.py`、`huicode/server/events/mapper.py`。
- 测试：`tests/server/test_event_types.py`。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 Append-only session events、
  [task.md](../../specs/017-web-studio/task.md) 的 T7。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

CLI 里 Agent 通过 `AgentEvent` 把过程告诉终端；Web 端需要的是另一套东西：能落库、
能按序号回放、能区分"谁能看见"的事件。如果两套各写各的，同一个 Agent Loop 就会
长出两种行为，而 C9 / AC9 明确要求 Web 与 CLI 用同一套语义。

所以 T7 只做一件事：**定义 Web 侧的规范事件类型，并把 Agent 现有的事件映射过去**。
映射是单向的，Agent 侧不改。

## 原理与数据流

```text
AgentEvent(kind="text"|"tool_call"|...)          huicode/agent_events.py
        │
        │  mapper.map_agent_event(session_id, run_id, sequence)
        ▼
RuntimeEvent(type=..., payload=..., visibility=...)
        │
        ├─ to_dict()/to_json()   →  T8 落库、SSE 推送
        └─ from_dict()           ←  从库里读回来
```

**载荷位置并不统一**，这是实现时才看清的：文本类（`text`/`thinking`）的内容在
`text` 字段；而 `error`/`memory`/`usage`/`context` 把内容放在 `data` 字典里；
`tool_call`/`tool_result` 放的是对象。映射器按实际产出逐个处理，没有假设统一形状。

`sequence` **不由映射器分配**。它是"单个会话内单调递增"的，只有持久化层知道当前
最大值，所以由 T8 的事件存储分配。

## 方案与取舍

- **计划外的三个类型是补的。** plan.md 的清单写"至少包括"14 种，但映射 `AgentEvent`
  时发现三种没有对应物：`memory_updated`（Agent 的 `kind="memory"`）、`error`
  （**运行中途**的错误，区别于结束整个 Run 的 `run_failed`）、以及反序列化的哨兵
  `unknown`。**plan.md 的清单需要补这三个。**
- **未知事件类型降级为 `unknown` 且强制 `internal` 可见性。** 一个我们看不懂的载荷
  可能包含任何东西。反过来做——"不认识就当作用户可见"——会让将来某个版本的内部
  事件泄露给所有人。注意生产者**自称** `visibility="user"` 也没用，未知类型一律 internal。
- **不认识的 `stop_reason` 一律判失败。** `done` 事件按 `stop_reason` 决定
  `run_completed` / `run_cancelled` / `run_failed`。取值表之外的一律按 `run_failed`
  处理并带 `error_code="unknown_stop_reason"`——把不认识的停止原因报成"成功完成"
  是最糟的默认值。
- **时间统一归一化成 aware UTC。** 在 `__post_init__` 里做，不依赖调用方自觉。
  数据库读出来的时间可能是 naive 的（SQLite 不存 tzinfo），不归一化就会在比较时抛
  `TypeError`——T5 已经踩过一次，不想踩第二次。
- **`visibility` 值不认识时按 `internal` 处理（fail closed）。**

### 一个刻意保守的取舍——已于 T11 还清

T7 落地时，`tool_call_started` 只带参数**名**（`argument_keys`），不带参数**值**。
理由是执行顺序：**T8 会先把事件写进数据库，T11 的 SecretScrubber 才落地**，
中间一段时间数据库里会躺着未经脱敏的载荷。

**T11 上线后这笔欠账已经还掉**：参数值现在进载荷（`arguments`），脱敏由写入路径
（`store.append`）负责。超过 4096 字符的参数仍只留键名并标记 `arguments_truncated`，
正文应当走 Artifact——事件表会被每个订阅者按 sequence 全量扫描，不该塞进去。

对应的链路验证在 `tests/server/test_scrubber.py` 的
`test_tool_arguments_are_scrubbed_on_the_way_to_the_database`：把这里的映射器与
T11 的落库接起来跑。**单独验证任一端都说明不了"这条路径是安全的"**——
映射器带上参数值只说明"值在"，store 脱敏只说明"store 会脱"。

## 实施难点与工程问题

**T7 没有出现产品缺陷。** 按仓库约定，没踩坑就不编。

实现过程中确实需要先读 `huicode/agent.py` 才能写对映射——因为 `text` 与 `data`
两种位置混用，且 `stop_reason` 有五种取值（`final` / `cancelled` / `error` /
`max_iterations` / `unknown_tool_limit`）。**这说明映射器不能凭类型定义写，
必须对着生产者的实际产出写。** 对应的回归是
`test_every_agent_kind_maps_to_an_expected_type` 与 `test_done_maps_by_stop_reason`。

## 验证证据

环境：仓库自带 `.venv`，Python 3.12.14，Windows 11。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_event_types.py -q
```

- 预计与实际：**26 passed**。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**577 passed, 14 skipped**（T6 时 525 + 26，加上后续 T8 的 21 项在内）。

关键断言：

- `test_every_known_type_round_trips`：**每个**已知类型都跑一遍 `to_dict → from_dict`，
  不是挑一两个代表。
- `test_tool_arguments_values_are_not_copied_into_the_payload`：断言参数值不出现在
  载荷和 JSON 里——这条是上面那个取舍的护栏。
- `test_unknown_type_ignores_a_claimed_user_visibility`：生产者自称 user 可见也没用。
- `test_unrecognised_stop_reason_fails_rather_than_reports_success`。
- `test_error_message_does_not_echo_the_payload`：解码异常不把载荷回显进消息。

**未覆盖场景与残余风险：**

- **没有任何真实事件流跑过。** 映射器只被单元测试调用；真正的接线在 T16（接入现有
  Agent Loop）。现在验证的是"映射正确"，不是"运行时会话能跑通"。
- 载荷里出现密钥时不会被脱敏——这是 T11 的职责，且已知晚于 T8 的持久化。
- `visibility` 的推送过滤（`visible_to`）只有单元测试，SSE 层的实际过滤在 T17。
- 单条文本增量上限 8192 字符是**拍的**，没有测量过正常输出会被切成多大。

## 自己动手

**复现实验**

1. ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_event_types.py -v
   ```
   预期：26 passed。

2. 看"未知类型被隔离"到底是什么行为：

   ```powershell
   .\.venv\Scripts\python.exe -c "from uuid import uuid4; from huicode.server.events.types import RuntimeEvent, visible_to; e=RuntimeEvent.from_dict({'type':'from_the_future','session_id':str(uuid4()),'sequence':1,'payload':{'secret':'x'},'visibility':'user'}); print(e.type, e.visibility, e.payload, visible_to(e,'owner'))"
   ```
   预期：`unknown internal {'original_type': 'from_the_future', 'raw': {'secret': 'x'}} False`

3. 确认不认识的停止原因不会变成"成功"：

   ```powershell
   .\.venv\Scripts\python.exe -c "from uuid import uuid4; from huicode.agent_events import AgentEvent; from huicode.server.events.mapper import map_agent_event; print(map_agent_event(AgentEvent(kind='done', stop_reason='something_new'), session_id=uuid4(), sequence=1).type)"
   ```
   预期：`run_failed`

**小改动练习**

给 `tool_call_finished` 加一个耗时字段（`duration_ms`）。

- 会影响什么：`AgentEvent` 里没有耗时信息，所以要么改 Agent（超出 T7 范围），要么在
  mapper 里按 `tool_call_id` 记住开始时间再配对。后者需要 mapper 变成有状态的，
  而这会破坏它当前"纯函数、无状态"的性质——这正是一个值得想清楚的取舍。
- 如何验证：想清楚"映射器该不该有状态"。若要有，重启后未配对的调用怎么办？

**自测问题**

1. 原理：为什么未知事件类型要强制成 `internal`，而不是保留生产者声明的可见性？
2. 异常路径：`stop_reason` 出现一个没见过的值时，为什么选"判失败"而不是"判完成"？
3. 取舍：`sequence` 为什么不由映射器分配？

**答案核对**

1. 因为"看不懂"和"安全"是同一个方向。载荷对我们不透明，就无法保证它不含内部细节；
   生产者声明的可见性在类型未知时不可信。见 `types.py` 的 `from_dict`。
2. 因为两种错误的代价不对称：把失败报成完成会让用户以为任务成功、错过补救；
   把完成报成失败只是一次误报，可人工确认。见 `mapper.py` 的取值表说明。
3. 序号要"单会话内单调唯一"，只有持久化层知道当前最大值，且分配必须在事务内
   与写入一起完成。映射器是纯函数，不碰数据库。见 `store.py`。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> 我把 Agent 现有的事件类型映射成一套 Web 侧的规范事件。三个决定值得一提：
> 第一，遇到不认识的**事件类型**时，不丢弃也不当成普通事件，而是降级成一个
> `unknown` 类型并强制成内部可见——我们看不懂的载荷不能推给普通成员，
> 生产者自称可见也没用；第二，遇到不认识的**停止原因**时一律判失败，
> 因为把失败报成完成和把完成报成失败，代价不对称；第三，工具调用的参数名进载荷、
> 参数值不进——因为持久化会先于脱敏能力落地，先不带值可以避免数据库里躺着
> 未脱敏的内容。

**深入追问**

- 问：事件怎么保证跨版本兼容？答：反序列化时未知类型不抛错、不丢事件，归一化成
  `unknown` 并保留原文，同时按最严格可见性处理。测试 `test_unknown_type_is_quarantined_not_rejected`
  覆盖了这条。
- 问：这套事件真的跑起来过吗？答：**没有。** 只有单元测试调用过映射器，真正的接线
  在 T16。现在能说的是"映射逻辑正确"，不能说"运行时事件流可用"。

**简历候选表述**：证据到「16 种事件类型 + 映射 + 26 项测试」。可以表述为
「设计并实现了统一运行时事件模型」，**暂时不要**说成"实现了实时事件推送"——
推送是 T8/T17。

**不能声称的能力或结果**：

- 不能说「实时事件流已经可用」——映射器还没有接进 Agent Loop。
- 不能说「事件载荷已脱敏」——SecretScrubber 是 T11，且还没做。
- 不能说「8192 字符的切分经过调优」——是拍的。

## 后续

- **欠账 1**：plan.md 的事件类型清单需要补 `memory_updated`、`error`、`unknown` 三个。
- **欠账 2**：T11 落地后，把工具参数**值**加进 `tool_call_started`，并确保先过脱敏。
- **交给 T16**：把 `map_agent_event` 接进真实 Agent Loop，届时才有端到端验证。
- **交给 T17**：SSE 层用 `visible_to` 做实际过滤。
- 用户练习反馈：**待用户自测**。
