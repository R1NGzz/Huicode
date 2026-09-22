# T5：认证、令牌与工作区角色

## 状态与关联

- 日期与里程碑：2026-09-22，任务 T5，里程碑 M1。
- 状态：**已实现并验证**。注册、登录、刷新、退出、当前用户五条接口与角色依赖
  均有 API 测试覆盖；跑在真实 SQLite 文件上，迁移链全量执行。
- 代码：`huicode/server/auth/{passwords,tokens,permissions,dependencies}.py`、
  `huicode/server/api/auth.py`、`huicode/server/api/errors.py`；
  模型新增 `RefreshToken`（`migrations/versions/0002_auth_tokens.py`）。
- 测试：`tests/server/test_auth.py`（21 项）。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 API contracts 与 auth 模块、
  [task.md](../../specs/017-web-studio/task.md) 的 T5。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

用户注册后要在浏览器里保持登录，同时 C16 要求「过期、伪造、错误签名和**已注销**的
refresh token 都不能换取有效身份」。最后半句决定了整个令牌方案：**令牌必须能在
服务端被单独作废**。

这件事不处理会怎样：用户点了「退出登录」，攻击者手里那份 refresh token 仍然可以
在 14 天里不断换新的 access token，前台显示已退出，后台一直有效。

## 原理与数据流

两种令牌形态不同，是有意的：

```text
登录/注册 ──┬─→ access token  : JWT，自包含，15 分钟，不查库
            └─→ refresh token : 48 字节随机串，14 天，库里存 SHA-256

每次请求  Authorization: Bearer <access>
              └→ 验签 + 看 exp + 取 user_id + 查 users 表（确认未被停用）

access 过期 → POST /api/auth/refresh { refresh_token }
              └→ 按 hash 查 refresh_tokens → 吊销旧行 → 签发新一对（轮换）
```

**access token 用 JWT**：它每个请求都要校验，服务端不该为它查一次库。代价是签发后
无法单独撤销，所以有效期只有 15 分钟。

**refresh token 不用 JWT**：既然它必须可撤销、就必须查库，那么 JWT 的自包含就一文不值，
反而多一份签名实现要维护。所以用一个不透明随机串，服务端按哈希查一行。

**角色不放进令牌。** `require_workspace_role` 每次请求现查 `workspace_members`。
如果把角色写进 JWT，管理员把某人降权后，那人得等 access token 过期才真正降权——
测试 `test_role_dependency_allows_and_denies_by_rank` 里「改库后同一令牌立刻被拒」
就是在固定这个行为。

**信任边界**：浏览器只持有令牌，不持有角色和权限判断；一切以服务端每次请求的查询为准。
令牌原文不进日志、不进数据库、不进错误响应。

## 方案与取舍

- **刷新令牌的哈希用 SHA-256，不是 argon2。** 密码用 argon2 因为它可能是弱口令，
  需要慢哈希抵抗爆破；refresh token 是 48 字节密码学随机串，没有「猜到」的可能，
  慢哈希只会让每次刷新都多花几十毫秒。
- **邮箱统一小写存储并据此判重。** 解决了 T4 留下的「`Alice@x.com` 与 `alice@x.com`
  是两个账号」。代价是本地部分大小写敏感的邮箱（现实中极少）无法区分。
- **「账号不存在」与「密码错误」返回完全相同的错误。** 并且邮箱不存在时也跑一次
  argon2 校验（`_DUMMY_HASH`），让两条路径耗时接近。否则登录接口本身就是一个
  账号枚举器——响应时间会泄露账号是否存在。
- **非成员返回 404，不是 403。** 若「不是成员」与「是成员但权限不足」返回不同状态码，
  攻击者就能拿状态码探测某个 `workspace_id` 是否存在。
- **刷新令牌重放 → 撤销该用户整条链。** 已轮换的令牌再次出现，要么被窃取，要么客户端
  状态错乱，两种都不该继续信任这条链。代价是正常用户误重放（例如两个标签页同时刷新）
  会被强制登出——这是有意的取舍，安全优先。
- **`refresh_tokens` 表是补设计。** T4 点名的十一张表里没有它。见下文「实施难点」。

**接口与 plan.md 的差异**：plan 的 API contracts 只列了 register/login/logout/me，
但 task.md 的 T5 步骤 3 明确要求「刷新」接口，`可轮换的 refresh token` 也需要它。
所以增加了 `POST /api/auth/refresh`。**plan.md 需要补这一行。**

## 实施难点与工程问题

这一节是本次最有价值的部分：三个问题都是**测试跑出来的**，不是设想出来的。

### 问题一：naive 与 aware 的 datetime 无法比较（真实问题）

- 触发条件：调用 `POST /api/auth/refresh` 校验刷新令牌是否过期。
- 症状：接口返回 500。因为中间件会把未捕获异常转成 500 且不外泄原文，日志里只有
  `{"route": "/api/auth/refresh", "status": 500}`，看不到原因。
- 排查假设与证据：用一个不挂中间件的最小应用重放同一请求，拿到真实栈：

  ```text
  File "huicode/server/api/auth.py", line 190, in refresh
      if row.expires_at <= now:
  TypeError: can't compare offset-naive and offset-aware datetimes
  ```

- 根因：**SQLite 不保存 `tzinfo`**。写进去的是 aware 的 UTC，读出来是 naive 的；
  与 `datetime.now(timezone.utc)` 比较即抛异常。PostgreSQL 的 `TIMESTAMPTZ` 会带回
  tzinfo，所以**在 PostgreSQL 上这个问题根本不出现**——它是「开发库比生产库更宽松」
  的反例，只在 SQLite 上暴露。
  **这正是 T4 学习记录里写下的那条保留（"SQLite 读取时间字段的时区行为不同"）第一次真实发生。**
- 修改：在 `huicode/server/db/base.py` 增加 `as_utc()`，约定「写库一律写 aware UTC，
  读库一律过 `as_utc`」，而不是在各比较点各自加判断。
- 回归：`test_refresh_rotates_tokens_and_old_one_stops_working` 等 2 项由 500 转为通过。

### 问题二：抛异常会把刚做的撤销回滚掉（真实问题，最隐蔽）

- 触发条件：刷新令牌被重放时，先 `_revoke_all_active()` 撤销整条链，再 `raise` 401。
- 症状：`test_replaying_a_rotated_token_revokes_the_whole_chain` 失败——重放旧令牌后，
  手上的新 refresh token 仍然可用，也就是说**撤销根本没生效**。
- 排查假设与证据：`get_session` 的实现是 `async with database.transaction() as session:
  yield session`；SQLAlchemy 的 `begin()` 上下文**异常时回滚、正常退出时提交**。
  路由里抛异常 → 依赖生成器收到异常 → 事务回滚 → 撤销被丢弃。
- 根因：这是「请求级事务」这个设计的一个反直觉后果：**任何"先写库再报错"的写法，
  写的那部分都会消失**。而这里"撤销整条链"恰恰是唯一有价值的部分。
- 修改：新增 `error_response(request, error)`，在 `api/errors.py` 里把 `ApiError` 渲染成
  与全局处理器**同形**的响应。重放分支改为 `return error_response(...)` 而不是 `raise`，
  于是路由正常返回、事务正常提交、错误体与其它接口一致。
- 回归：该用例通过；重放后新旧两个 refresh token 都返回 401。
- **这条值得记住**：它不报错、不崩溃，只是安静地什么都不做。如果不是先写了断言
  "重放后新令牌也必须失效"，这个漏洞会一直到线上才被发现。

### 问题三：策略异常逃逸成 500（真实问题）

- 触发条件：注册时提交过短的密码。
- 症状：`PasswordPolicyError` 继承 `ValueError`，不是 `ApiError`，于是绕过全局处理器
  变成 500，而不是 422。
- 修改：在注册路由里捕获并转成 `ApiError(422, "validation_error", ...)`。
- 回归：`test_register_rejects_weak_password_and_bad_email` 断言 422 且 code 正确。

### 设计风险（非真实故障）

`_DUMMY_HASH` 在模块导入时计算一次（约几十毫秒），用于登录时的耗时对齐。
这是在"启动稍慢"和"登录接口可枚举账号"之间的取舍，选了前者。若将来觉得导入成本
不可接受，应改成进程启动时显式初始化，而不是删掉对齐逻辑。

## 验证证据

环境：仓库自带 `.venv`，Python 3.12.14，Windows 11。命令在仓库根目录执行。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_auth.py -q
```

- 预期：覆盖注册、重复邮箱、弱密码、错误密码、账号枚举、过期 access token、
  伪造签名、refresh 冒充 access、轮换、重放、退出幂等、日志与响应无凭据、角色放行/拒绝。
- 实际：**21 passed**。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**495 passed**（T4 时 474 + 新增 21），39.43s。

```powershell
$env:HUICODE_DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/huicode"
.\.venv\Scripts\alembic.exe heads
```

- 实际：`0002_auth_tokens (head)`；`upgrade head --sql` 渲染出 0001 + 0002 的建表与索引语句。

**测试跑在什么上**：真实 SQLite 文件，先执行**全量迁移链**（0001 + 0002）建表，
应用再通过自己的连接池接入，走真实的 SQL 与事务。`tests/server/test_models.py` 的
迁移加载已改为按 `down_revision` 自动串链，新增迁移不再需要改测试。

**未覆盖场景与残余风险：**

- **仍未在真实 PostgreSQL / Redis 上运行过。** 问题一已经证明 SQLite 与 PG 在时间类型上
  行为不同；令牌过期时间的实际往返必须在有 PG 实例后重验。
- 刷新令牌重放会**撤销该用户全部会话**，没有"仅撤销这一条链"的粒度。多设备用户误触发时
  会全体登出，这是当前有意的安全取舍，但尚未经真实多设备场景检验。
- access token 的有效期（15 分钟）和 refresh token（14 天）是**拍的，不是测的**。
  没有任何关于"撤销后多久生效"的端到端计时验证。
- 没有登录失败次数限制或锁定。当前只有 argon2 的成本作为暴力破解阻力。
- `_DUMMY_HASH` 只在"邮箱不存在"时使用；账号存在但被停用时走的是另一条分支，
  两条分支的耗时差异未经测量。
- T6 的路径解析、T9 的取消、T15 的恢复都还没有；角色依赖目前只有一个测试探针路由，
  没有任何真实业务路由在用。

## 自己动手

**复现实验**

前置：PowerShell，仓库根目录，存在 `.venv`。

1. 跑认证测试：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_auth.py -v
   ```

   预期：21 passed。重点看 `test_replaying_a_rotated_token_revokes_the_whole_chain`
   和 `test_role_dependency_allows_and_denies_by_rank` 两条。

2. 亲手触发问题二（事务回滚吞掉写入）。把 `huicode/server/api/auth.py` 里重放分支的
   `return error_response(request, unauthenticated("刷新令牌无效"))` 改回
   `raise unauthenticated("刷新令牌无效")`，重跑第 1 步。

   预期：`test_replaying_a_rotated_token_revokes_the_whole_chain` **失败**——
   重放后新 refresh token 仍然可用。这条测试是本任务里唯一能挡住这个漏洞的东西。

3. 亲眼看一下 500 时日志为什么不给线索：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_auth.py -q --log-cli-level=INFO 2>&1 | Select-String "auth/refresh"
   ```

   预期：只能看到 `{"route": "/api/auth/refresh", "status": 500}`，没有异常原文。
   这是 `RequestContextMiddleware` 有意为之（不泄露内部细节），代价是排查时必须
   用不挂中间件的最小应用复现。

**小改动练习**

把 `ACCESS_TOKEN_TTL` 从 15 分钟改成 1 秒，重跑认证测试。

- 会影响什么：`test_refresh_rotates_tokens_and_old_one_stops_working` 里"新 access token
  可用"那一步可能因过期而失败，暴露出测试对 TTL 的隐含依赖。
- 如何验证：想清楚哪些断言依赖 TTL、哪些不依赖；把不依赖 TTL 的断言与依赖的分开，
  后者显式传入 `issued_at` 构造，而不是靠等待。
- 建议在分支上改，或改完立刻改回。

**自测问题**

1. 原理：为什么 access token 用 JWT、refresh token 用不透明随机串？如果两者都用 JWT，
   C16 的「已注销 refresh token 不能换取有效身份」还能满足吗？
2. 异常路径：用户点退出登录后，手里那个还没过期的 access token 还能用多久？为什么？
   这是缺陷还是设计？
3. 取舍：刷新令牌重放时撤销"该用户整条链"而不是"这一条链"，各自的代价是什么？
   什么场景下你会改成后者？

**答案核对**

1. access 每次请求都要校验，JWT 免去查库；refresh 必须可撤销、必须查库，JWT 的自包含
   就没价值。两者都用 JWT 则无法撤销，C16 不满足。见 `auth/tokens.py` 顶部注释。
2. 最长还能用 15 分钟（`ACCESS_TOKEN_TTL`），因为 access token 是无状态 JWT、
   服务端不查它的吊销状态。这是**有意的设计取舍**（换取免查库），缓解手段是短有效期；
   若要立即失效，就得给 access token 也加吊销检查，那就失去了 JWT 的意义。
3. 撤销整条链：安全性高，代价是多设备误登出。撤销单条：误伤小，但窃取者可能保留
   另一条并行链。若将来做多设备会话管理，应按"设备/会话"分组，重放时只撤销同组。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> 认证这块我做了两种令牌。access token 是自包含 JWT，15 分钟，每次请求不查库；
> refresh token 是服务端存哈希的不透明随机串，因为需求要求"已注销的令牌不能再用"，
> 这个用无状态 JWT 做不到。角色不进令牌，每次请求现查数据库，所以管理员降权是立即生效的。
> 登录失败时"账号不存在"和"密码错误"返回完全一样的响应、并且耗时也对齐，
> 否则登录接口就成了账号枚举器；非成员访问工作区返回 404 而不是 403，同理。
> 过程中踩到两个真实的坑：一个是 SQLite 不保存时区，读出来的时间和带时区的 now
> 比较会抛异常，而 PostgreSQL 不会有这个问题；另一个更隐蔽——请求级事务在异常时回滚，
> 所以"检测到刷新令牌重放、先撤销整条链、再抛 401"这个写法，撤销会被静静回滚掉，
> 是断言"重放后新令牌也必须失效"才把它逼出来的。

**深入追问**

- 问：你怎么验证"退出登录后令牌真的不能用了"？答：`test_logout_revokes_refresh_token_and_is_idempotent`
  退出后拿同一 refresh token 去换，断言 401；退出本身重复调用也是 204。
- 问：如果攻击者拿到了 access token 但没拿到 refresh token，你能做什么？
  答：当前什么也做不了，只能等它 15 分钟内自然过期——这是选 JWT 的既定代价。
  **这一点必须主动说，不能把"短有效期"讲成"已解决令牌泄露"。**

**简历候选表述**：证据到「五条认证接口 + 21 项测试 + 刷新令牌轮换与重放检测」。
可以表述为「设计并实现双令牌认证与工作区角色校验」，但**不要**说成「完成了认证安全加固」
或「实现了令牌泄露防护」——后者没有做。

**不能声称的能力或结果**：

- 不能说「在 PostgreSQL 上验证过」——所有测试跑在 SQLite 上。
- 不能说「有登录限流/防爆破」——没有实现。
- 不能说「撤销是即时的」——access token 最长 15 分钟仍然有效。
- 不能说「支持多设备会话管理」——重放检测是整用户级别的。

## 后续

- **欠账 1**：`POST /api/auth/refresh` 需要补进 plan.md 的 API contracts 一节。
- **欠账 2**：`refresh_tokens` 表需要补进 plan.md 的数据模型一节（T4 的十一张表里没有它）。
- **交给 T6**：`require_workspace_role` 目前只被测试探针路由使用；T6 的工作区与项目接口
  是第一批真实使用者，届时需要确认"路由里忘记加依赖"不会静默变成越权。
- **交给 T9/T15**：`as_utc()` 应成为读库时间字段的统一入口；新增涉及时间比较的代码要过它。
- **待决策**：登录失败次数限制；多设备会话分组。
- 按 Execution Order，T5 之后是 T6（工作区、项目与路径解析），也是 T7→T8、T11 两条支线的起点。
- 用户练习反馈：**待用户自测**。本文的动手实验尚未由用户实际执行。
