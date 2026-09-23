# T8：事件持久化、发布与补偿

## 状态与关联

- 日期与里程碑：2026-09-23，任务 T8，里程碑 M1。
- 状态：**已实现并验证**。21 项单测（SQLite）+ 5 项集成测试（真实 PostgreSQL + 真实 Redis）。
- 代码：`huicode/server/events/store.py`、`publisher.py`、`subscriber.py`、`errors.py`。
- 测试：`tests/server/test_event_store.py`、`tests/integration/test_event_store.py`。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 `huicode/server/events/`、
  [task.md](../../specs/017-web-studio/task.md) 的 T8。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

任务执行期间浏览器要实时看到文本、工具状态和结果；用户刷新页面或断网重连后，
还要能补齐错过的事件（C22、AC4）。

难点在"实时"和"不丢"这两件事本身是矛盾的：实时靠推送，推送会丢；不丢靠全量读取，
全量读取不实时。T8 要同时满足，且不能依赖推送通道可靠。

## 原理与数据流

```text
写入：  业务事务（创建 Run + 写排队事件）── 同一个事务 ──→ commit
                                                            │
                                          提交成功后才发布通知 ──→ Redis
                                                                    │
读取：  客户端带 last_sequence                                      │
            ├─ 1. 从数据库补齐 sequence > last  ────────────────────┤
            └─ 2. 进入实时跟随 ←───────── 收到通知就读库 ───────────┘
                    └─ 静默超过 safety_poll_seconds 也读一次（兜底丢通知）
```

**三条不变量由数据库保证，不由调用方自觉：**

1. **`sequence` 单会话内单调唯一。** 分配方式：先 `SELECT ... FOR UPDATE` 锁住父
   `sessions` 行，再取 `MAX(sequence) + 1`。**锁父行而不是锁事件行**——要防的是
   "两个并发追加同时读到同一个 MAX"，不存在的行锁不住。唯一约束
   `uq_session_events_session_id_sequence` 是兜底：锁若失效，写入失败而不是产生
   重复序号（重复序号会让补偿静默丢事件）。
2. **同一 `event_id` 重复写入幂等。** `SessionEvent.id` 就是事件 id，重复 append
   返回已有行，**且不推进序号**——否则重试会让序号出现空洞，补偿查询就得处理
   "序号跳号但事件不存在"。至少一次投递和重试都依赖这一点。
3. **`workspace_id` 取自父会话行**，不取自调用方。调用方无法把事件写进别人的工作区。

`append` **复用调用方的事务**，不自己提交——这样"创建 Run + 写排队事件"才是原子的。

## 方案与取舍

- **Redis 发的是通知，不是事件本体。** 载荷只有会话 id 和序号。三个好处：数据库是
  唯一事实来源，丢一条通知只损失一次延迟不损失正确性；不存在"Redis 里的载荷和数据库
  不一致"；通知体很小。代价是每次通知都要回数据库读一次。
- **发布失败不抛异常，返回 `False`。** 事件此时已经提交，把发布失败当成请求失败是错的
  ——调用方会以为事件没写进去。
- **`safety_poll_seconds` 不能省。** 如果只在收到通知时读库，那么"Redis 连着但某条通知
  丢了"会让订阅者永久停在原地，而且看不出哪里错了。宁可有这一次多余查询。
- **`FOR UPDATE` 在 SQLite 上是空操作。** SQLAlchemy 的 SQLite 方言会忽略它，SQLite 靠
  整库写锁串行化。所以**并发追加的串行化只在 PostgreSQL 上被真正验证过**——这也是
  T8 必须有一个真库集成测试的原因。
- **列出接口 `list_after` 带 limit 且分批排空**，避免一次断线重连把整个会话的事件
  全读进内存。

## 实施难点与工程问题

### 问题一：Windows 上 `localhost` 连不上 Redis（真实问题，影响部署配置）

- 触发条件：集成测试连 `redis://localhost:6379/0`。
- 症状：**测试被静默跳过**而不是失败。`skipTest` 的触发条件是 `redis.ping()` 抛异常，
  而真实原因是连接超时。
- 排查假设与证据：容器在跑（`redis-cli ping` 返回 PONG），但主机上：

  ```text
  redis://localhost:6379/0   -> FAIL TimeoutError Timeout connecting to server
  redis://127.0.0.1:6379/0   -> True
  ```

- 根因：**Windows 把 `localhost` 优先解析成 IPv6 的 `::1`**，而 Docker Desktop 发布的
  端口只监听 IPv4。表现为**超时而不是拒绝**，所以更难看出是解析问题。
- 影响面：`.env.example` 和 `docs/web-studio-local-development.md` 里写的都是
  `localhost`。**照文档配置，`/health/ready` 会报 Redis 不可用。**
- 修改：两处都改成 `127.0.0.1`，并写明原因（`127.0.0.1` 在各平台都正确）。
- 回归：集成测试由 2 skipped 变成 5 passed。
- **值得记住的一点**：用 `skipTest` 处理"环境不可用"会让真问题伪装成"没跑"。
  如果那次运行没有打印跳过原因，这个配置缺陷会一直留到部署才暴露。

### 问题二：我自己把兜底逻辑写反了（实现错误，写测试时发现）

`_follow_redis` 初版有两个错，都在写测试时暴露：

1. 兜底分支里重置了空闲计时器，导致 `idle_timeout` **永远不会触发**；
2. 循环每一轮都查一次数据库，**与是否收到通知无关**——那样 Redis 就白接了，
   延迟和纯轮询一模一样。

修改后读库的时机明确为两个：收到通知时立刻读（低延迟），`safety_poll_seconds`
内没有通知时读一次（兜底）。用 `get_message` 的等待当节拍，而不是每轮都查。

对应测试：`test_missed_notification_is_recovered_by_the_safety_poll`
（假 pubsub 永远不发消息，事件仍须被读到）与 `test_redis_error_degrades_to_polling`。

### 设计风险（未验证）

`test_for_update_serialises_concurrent_appends` 只用了**三个**并发事务。行锁在更高
并发下的行为（锁等待、超时、死锁处理）没有测过，也没有任何超时配置。生产上
一个会话被多个 Worker 同时追加以外的情况本来也不该发生，但**这不构成"并发已被验证"**。

## 验证证据

环境：`.venv` + Python 3.12.14；真库为 `postgres:18-alpine`，真 Redis 为 `redis:7-alpine`。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_event_store.py -q
```

- 预计与实际：**21 passed**（10.8s）。

```powershell
$env:HUICODE_TEST_DATABASE_URL = 'postgresql+asyncpg://huicode:huicode-dev-password@127.0.0.1:5432/huicode'
.\.venv\Scripts\python.exe -m pytest tests/integration -q
```

- 实际：**14 passed**（10.4s），其中 5 项属于 T8。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**577 passed, 14 skipped**（不设环境变量时集成测试跳过，无容器的机器不受影响）。

真库上专门验证的两条（SQLite 上无法成立）：

- `test_for_update_serialises_concurrent_appends`：三个并发事务抢同一会话的序号，
  最终序号必须是 `[1, 2, 3]`，既不能重复也不能跳号。
- `test_publish_reaches_a_real_subscriber`：通知真的经 Redis 到达订阅者，
  订阅者再回数据库取到事件。

**未覆盖场景与残余风险：**

- **没有 SSE 层。** 订阅者是一个返回异步迭代器的类，还没有包成 HTTP 流；服务端断开、
  客户端重连、心跳都发生在 T17。
- **没有真实 Agent 产出的事件流。** 事件都是测试手工构造的；接线在 T16。
- **Redis 的降级路径只用假 pubsub 验过**（抛异常→退化为轮询）。真实 Redis 掉线、
  重启、主从切换都没测过。
- `safety_poll_seconds` 默认 2 秒、`poll_seconds` 默认 1 秒都是**拍的**，没有任何
  延迟或负载测量。N8 要求"事件推送不能明显阻塞其他会话"，这条完全没验。
- 并发行锁只用了 3 个并发事务；没有锁等待超时配置。
- 事件表会无限增长：**没有归档或清理策略**，也没有按会话的留存上限。

## 自己动手

**复现实验**

前置：PowerShell，仓库根目录，两个容器已在运行（见本地开发文档）。

1. 跑单测：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_event_store.py -v
   ```
   预期：21 passed。

2. **亲手复现 Windows 的 localhost 陷阱**：

   ```powershell
   .\.venv\Scripts\python.exe -c "import asyncio; from redis.asyncio import Redis; async def m():`n for u in ('redis://localhost:6379/0','redis://127.0.0.1:6379/0'):`n  r=Redis.from_url(u,socket_connect_timeout=2,socket_timeout=2)`n  try: print(u,'->',await r.ping())`n  except Exception as e: print(u,'-> FAIL',type(e).__name__)`n  await r.aclose()`nasyncio.run(m())"
   ```

   预期：`localhost` 报 TimeoutError，`127.0.0.1` 返回 True。这一条解释了为什么
   配置里不能写 `localhost`。

3. 跑真库集成测试：

   ```powershell
   $env:HUICODE_TEST_DATABASE_URL = 'postgresql+asyncpg://huicode:huicode-dev-password@127.0.0.1:5432/huicode'
   .\.venv\Scripts\python.exe -m pytest tests/integration/test_event_store.py -v
   ```
   预期：5 passed。重点看 `test_for_update_serialises_concurrent_appends`。

**小改动练习**

把 `EventSubscriber.poll_seconds` 从 1 秒改成 0.05 秒，观察
`test_stream_without_redis_catches_up_then_polls` 的行为变化。

- 会影响什么：轮询更密，测试更快，但数据库压力上升。想清楚"多久轮一次"应该由什么决定
  ——是延迟要求还是负载上限？现在两者都没有数据支撑。
- 如何验证：跑单测观察耗时；想清楚在生产规模下这个值应该怎么定。

**自测问题**

1. 原理：为什么 `sequence` 要锁**父会话行**而不是"锁事件行"或"直接取 MAX+1"？
2. 异常路径：Redis 连接正常，但某一条通知在网络上丢了。订阅者会怎样？为什么？
3. 取舍：发布通知失败时不抛异常、只返回 False，代价是什么？

**答案核对**

1. 要防的是"两个事务同时读到同一个 MAX"；`session_events` 里那一行还不存在，锁不住。
   父会话行一定存在，锁它就能把同一会话的并发追加串行化。见 `store.py` 的 `_lock_session`。
2. 不会永久卡住：`safety_poll_seconds` 到点会主动回数据库读一次。这是兜底存在的
   全部理由。见 `subscriber.py` 的 `_follow_redis`。
3. 代价是"发布失败"变成静默事件，只在日志里留一行。若不接受，就得在通知通道上做
   确认或重试——但那会把数据库已经成功的事实绑死在 Redis 的可用性上，正是这个设计
   要避免的。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> 事件的实时推送和不丢事件本身是矛盾的，我的做法是把数据库当唯一事实来源，
> Redis 只做"去看一眼"的通知。写的时候先提交数据库、再发通知；读的时候客户端带上
> 最后收到的序号，先从数据库补齐错过的事件，再进入实时跟随，并且即使没收到通知也会
> 周期性回数据库确认一次——因为"Redis 连着但通知丢了"是最难排查的一类故障。
> 序号分配在事务内锁住父会话行再做 MAX+1，唯一约束兜底。这块我在真实 PostgreSQL 上
> 用三个并发事务验证过序号不重不跳——这一点在 SQLite 上验不了，因为它会忽略
> `FOR UPDATE`。

**深入追问**

- 问：Redis 挂了会怎样？答：延迟变差，事件不丢。轮询路径有测试覆盖
  （`test_redis_error_degrades_to_polling`）。但要说明：这只是用假 pubsub 验证的，
  真实 Redis 的主从切换没测过。
- 问：怎么保证不重复推送？答：订阅者只产出 `sequence > last` 的事件，且序号在会话内
  唯一，所以天然去重；重复的 `event_id` 写入也是幂等的。

**简历候选表述**：证据到「事件存储 + 发布订阅 + 补偿路径 + 26 项测试（含 5 项真库）」。
可表述为「实现了基于数据库事实源的事件流与断线补偿」，但**不要说**成"实现了实时推送"
——SSE 层是 T17，还没做。

**不能声称的能力或结果**：

- 不能说「SSE / WebSocket 已实现」——只有订阅者类，没有 HTTP 流。
- 不能说「验过高并发」——只跑了 3 个并发事务，且没有锁超时配置。
- 不能说「性能经过调优」——轮询间隔是拍的，没有任何延迟或吞吐测量。
- 不能说「Redis 高可用已处理」——降级路径只用一个抛异常的假客户端验过。

## 后续

- **交给 T16 / T17**：把订阅者接进 SSE，届时才验证"浏览器实时看到事件"。
- **交给 T23/T25**：Docker Compose 编排里 Redis 与 API 的连接串要用 `127.0.0.1`
  的等价写法（容器内用服务名），别把本机这个坑带进去。
- **待决定**：事件表的留存与归档策略；`poll_seconds` / `safety_poll_seconds` 的取值依据。
- **已知欠账**：工具参数值要等 T11 脱敏落地后再进载荷（见 T7 记录）。
- 用户练习反馈：**待用户自测**。
