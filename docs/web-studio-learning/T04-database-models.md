# T4：核心业务模型与初始迁移

## 状态与关联

- 日期与里程碑：2026-09-22，任务 T4，里程碑 M1（服务端与 Runtime 基础）。
- 状态：**已实现并验证（结构层面）**。迁移与模型的一致性、upgrade/downgrade 往返、
  外键与唯一/检查约束均由测试实际执行验证；**真实 PostgreSQL 在线执行仍未验证**，
  原因与 T3 相同（Docker 引擎不可用）。
- 代码：`huicode/server/db/models.py`、`huicode/server/db/base.py`、
  `migrations/versions/0001_initial.py`。
- 测试：`tests/server/test_models.py`（13 项）；顺带修复 `tests/server/test_database.py`。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 Core Data Structures 一节、
  [task.md](../../specs/017-web-studio/task.md) 的 T4。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

用户在浏览器里创建项目、发起一次 Agent 任务，系统要同时写下「Run 已排队」和一条排队事件。
如果 Run 存下了、事件没存下，前端就会显示一个永远没有后续的任务；反过来事件先到而 Run 不存在，
断线重连时就补不回一次真实的执行。

所以这一层要回答的是：**哪些事实必须先落库、它们之间的引用关系是什么、哪些不变量必须由数据库
而不是应用代码来保证**。T4 就是把 spec 里 F1–F19 涉及的所有持久化对象一次定义清楚，
并生成第一版迁移。

## 原理与数据流

十一张表按信任边界分成四组：

```text
身份与授权   users ─┬─ workspaces ─┬─ workspace_members
                    │              │
项目与会话          │              ├─ projects ── sessions ── runs
                    │              │
事件与审批          │              ├─ session_events
                    │              ├─ tool_approvals
                    │
审计与产物          │              ├─ audit_logs
                                   ├─ artifacts
                                   └─ usage_records
```

有两条设计线索值得单独看。

**第一条：`workspace_id` 被有意冗余到子表。** `sessions`、`runs`、`session_events`、
`tool_approvals`、`audit_logs`、`artifacts`、`usage_records` 都同时存了 `workspace_id`，
而它本可以顺着 `project → session → run` 推出来。这么做是因为 C12–C15 要求
「即使用户知道别人的 session_id / run_id，也不能读到数据」——每一次子资源读取都必须带上
工作区条件。冗余一份 `workspace_id`，这个条件就是一次索引命中，而不是每层一次 join。
代价是它可能与父行的 `workspace_id` 不一致，**这个一致性由 service 层保证，数据库不保证**。
这是本项目里第一个「用冗余换隔离」的取舍，后面 T6 的角色校验会依赖它。

**第二条：哪些表可以 `updated_at`，哪些不行。** `session_events`、`audit_logs`、`usage_records`
是只追加的：事件是 SSE 的补偿游标，审计是事后证据，用量是一次执行的记账。给它们加
`updated_at` 等于承认这些行会被改，与「只追加」的前提矛盾。所以 `base.py` 里分成了
`CreatedAtMixin`（只写一次）和 `TimestampMixin`（会改名/改状态，如 `sessions`）。

`sequence` 是事件回放的核心。它在**单个会话内**单调递增，`(session_id, sequence)` 上的唯一约束
同时充当回放索引——断线重连时客户端带上最后收到的 sequence，服务端按区间补齐。
这条唯一约束如果缺失，并发写入就可能产生重复 sequence，回放会静默丢事件。

## 方案与取舍

**初始迁移由 metadata 渲染生成，不是手抄。** `0001_initial.py` 的表、列、约束和索引，
是用 `alembic.autogenerate.render_python_code` 把 `Base.metadata` 渲染出来再整理表头得到的。
手写两百行 DDL 一定会和模型漂移，而漂移在线上表现为「模型有这一列、数据库没有」。
选这个做法还有一个好处：`compare_metadata` 可以直接断言迁移与模型的差异为 0。

替代方案是用 `alembic revision --autogenerate`。没选它是因为 autogenerate 需要连上真实
PostgreSQL，而当前 Docker 引擎不可用——这正是 T3 留下的阻塞。渲染方案不需要连接。

**两处与 plan.md 不一致，都是有意为之：**

1. **`UsageRecord` 在 plan.md 里不存在。** 它只出现在 task.md 的 T4 步骤里，而 plan.md 的
   Core Data Structures 只定义到 `Artifact`。这里按 F10（管理员看任务次数、耗时、Token）和
   C20（Run / 时间线 / 用量视图三处数字一致）补齐：一次 Run 一行，`run_id` 唯一。
   按 Run 汇总而不是按模型调用逐条记，是为了让三处读同一个来源，天然相等。
   **这是补设计，不是实现计划；plan.md 需要回填这一节。**
2. **`Project.workspace_path` 存相对路径。** plan.md 只写了 `workspace_path: str`。这里规定它
   相对 `HUICODE_PROJECT_ROOT`，由 `ProjectRootResolver` 解析后再校验。存绝对路径会把宿主机
   目录结构写进数据库，也让 C48「API 无法创建指向未授权宿主机路径的项目」更难守。

**一个有意不建的模块：工具调用的幂等记录。** task.md 的 T4 步骤 4 要求为 Tool Call
「预留幂等键或执行记录字段」，C32 也要求重复处理同一 `tool_call_id` 不能重复产生副作用。
但它的形状取决于 T12/T14 的执行设计（是记在 Run 上、还是单独一张执行表、还是复用事件表），
现在定下来会先入为主。本阶段只保证 `tool_approvals` 的 `(run_id, tool_call_id)` 唯一，
够 T14 的审批幂等用；执行幂等留到建执行路径时一起定。**这是一处明确的欠账。**

## 实施难点与工程问题

**真实问题：测试用的探针表污染了生产 metadata。**

- 触发条件：`tests/server/test_database.py` 里 `class Probe(IdentityMixin, TimestampMixin, Base)`
  直接继承 `Base`。只要该模块被 import，`test_transaction_probe` 就注册进 `Base.metadata`。
- 症状：单独跑 `test_models.py` 时 `compare_metadata` 返回 0 个差异；跑整个 `tests/server`
  时报出 `('add_table', Table('test_transaction_probe', ...))`。同一个测试在两种命令下结论相反。
- 排查假设与证据：差异里多出来的表叫 `test_transaction_probe`，只可能来自测试模块。
  `import tests.server.test_database` 之后打印 `Base.metadata.tables` 得到 12 张表，
  不 import 时是 11 张，假设成立。
- 根因：`migrations/env.py` 里 `target_metadata = Base.metadata`。测试模型挂到同一个 `Base`
  上，等于告诉 alembic「生产库也该有这张表」——下一次 autogenerate 就会生成
  `create_table('test_transaction_probe')`。这不是测试卫生问题，是会写进迁移的缺陷。
- 修改：给探针单独一个 `_ProbeBase(DeclarativeBase)`，只复用 mixin，不共用 `Base`。
- 回归：`tests/server` 32 项通过；`import` 测试模块后 `Base.metadata` 仍是 11 张表，
  `'test_transaction_probe' in Base.metadata.tables` 为 `False`。

**设计风险（非真实故障）：`metadata` 是 SQLAlchemy 声明式的保留属性名。**
`audit_logs` 这一列在 plan.md 里叫 `metadata`，但 ORM 类上 `metadata` 指向 `Base.metadata`。
若把属性也命名为 `metadata`，`insert(AuditLog).values(metadata={...})` 会去找 `MetaData` 对象，
报 `'MetaData' object has no attribute '_bulk_update_tuples'`。处理方式是把**属性**命名为
`audit_metadata`、用 `mapped_column("metadata", ...)` 保留**列名**，并在测试里同时断言列名是
`metadata`、且能通过 `Table` 构造正常写入。这是注入出来的场景，不是线上事故。

## 验证证据

环境：仓库自带 `.venv`，Python 3.12.14，Windows 11。命令均在仓库根目录执行。

```powershell
# 1. 迁移与模型是否漂移（结构一致的硬断言）
.\.venv\Scripts\python.exe -m pytest tests/server/test_models.py -q
```

- 预期：全部通过；其中 `test_migration_matches_model_metadata` 断言
  `compare_metadata(...) == []`。
- 实际：**13 passed**。差异数为 0，说明表、列、外键、检查约束、唯一约束和索引全部一致。

```powershell
# 2. 全套回归
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 预期：不低于 T3 时的 461 项，且无失败。
- 实际：**474 passed**（461 + 新增 13），34.12s。

```powershell
# 3. 迁移可被 alembic 识别并渲染出 PostgreSQL DDL（离线，不连库）
$env:HUICODE_DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/huicode"
.\.venv\Scripts\alembic.exe heads
.\.venv\Scripts\alembic.exe upgrade head --sql
```

- 预期：`heads` 显示 `0001_initial (head)`；`--sql` 渲染出建表语句。
- 实际：`0001_initial (head)`。渲染出的 DDL 使用 PostgreSQL 类型——
  `id UUID NOT NULL`、`created_at TIMESTAMP WITH TIME ZONE NOT NULL`、`metadata JSON NOT NULL`、
  `is_active BOOLEAN NOT NULL`。这一点很重要：说明迁移不是按 SQLite 的类型生成的。

**未覆盖场景与残余风险：**

- **从未在真实 PostgreSQL 上执行过 upgrade / downgrade。** 测试跑的是 SQLite。
  SQLite 没有真正的并发锁、隔离级别语义不同、时区行为也不同（它不保留 tzinfo）。
  `TIMESTAMP WITH TIME ZONE` 的实际往返、以及 `JSON` 在 PG 上是否应改为 `JSONB`，
  都必须在有 PG 实例后重验。
- `compare_metadata` 的「0 差异」是在 SQLite 上比较的。它能抓住列名、索引、约束的漏抄，
  但不能证明类型选择在 PostgreSQL 上正确。
- 冗余的 `workspace_id` 与父行的一致性目前**只靠约定**，没有任何约束或触发器保证；
  要等 T6 的 service 层落地后才有测试。
- `users.email` 的唯一约束区分大小写。`Alice@x.com` 与 `alice@x.com` 会是两个账号。
  是否需要 `citext` 或规范化存储，等 T5 做认证时决定。

## 自己动手

**复现实验**

前置：PowerShell，工作目录为仓库根目录，已存在 `.venv`。

1. 看迁移与模型是否真的一致——这是本任务最重要的一条断言：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_models.py::ModelSchemaTests::test_migration_matches_model_metadata -v
   ```

   预期输出：`1 passed`。这条测试不检查代码长什么样，只把数据库里建出来的 schema 和
   `Base.metadata` 对比，差异必须是空列表。

2. 亲手制造一次漂移，确认它会失败。编辑 `huicode/server/db/models.py`，给 `User` 加一列
   （例如 `nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)`），
   然后**不要**动迁移文件，重跑第 1 步。

   预期：失败，差异里出现 `('add_column', ... 'nickname' ...)`。
   恢复方式：删掉这一列，或按下面的练习补齐迁移。

3. 看迁移在 PostgreSQL 方言下渲染成什么：

   ```powershell
   $env:HUICODE_DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/huicode"
   .\.venv\Scripts\alembic.exe upgrade head --sql | Select-String "CREATE TABLE|UUID|TIMESTAMP"
   ```

   预期：看到 `CREATE TABLE users`、`id UUID NOT NULL`、`TIMESTAMP WITH TIME ZONE`。
   这条命令**不连数据库**，`--sql` 只是把 SQL 打印出来。

4. 确认探针表没有再污染 metadata：

   ```powershell
   .\.venv\Scripts\python.exe -c "import tests.server.test_database; from huicode.server.db.models import Base; print(len(Base.metadata.tables), 'test_transaction_probe' in Base.metadata.tables)"
   ```

   预期：`11 False`。若打印 `12 True`，说明 `_ProbeBase` 的修复被改回去了。

**小改动练习**

给 `Run` 加一个 `max_iterations` 列（整数，非空，默认 50），走完整条链路：
改 `models.py` → 重跑第 1 步看它失败 → 生成新的 `op.add_column` 迁移 → 再重跑看它通过。

- 会影响什么：`Run` 的每一行都需要这个值，所以非空列必须有 `server_default`，
  否则在已有数据的表上加列会失败。这是迁移里最容易踩的一类坑。
- 如何验证：`compare_metadata` 归零，且 `pytest tests/server` 全绿。
- 建议不要直接改主工作区，先开分支或用临时副本。

**自测问题**

1. 原理：`session_events` 上为什么是 `(session_id, sequence)` 唯一，而不是全局唯一的 `sequence`？
   如果换成全局唯一，断线补偿会多出什么问题？
2. 异常路径：`runs.idempotency_key` 是可空列，唯一约束建在 `(session_id, idempotency_key)` 上。
   同一会话里连续插入两个 `idempotency_key` 都为 `NULL` 的 Run，会不会冲突？为什么？
3. 取舍：`sessions.workspace_id` 是冗余字段。如果只保留 `project_id`、
   每次靠 join 推出工作区，会牺牲什么？如果反过来，加一个数据库层的复合外键
   `(project_id, workspace_id) → projects(id, workspace_id)` 来强制一致，代价是什么？

**答案核对**

1. 单会话内递增才能让「客户端带上最后收到的 sequence」成为一次范围查询；
   若全局唯一，一个会话的 sequence 会稀疏跳号，区间里混进别的会话的事件，既是正确性问题也是越权风险。
   见 `models.py` 的 `SessionEvent.__table_args__` 与 C21。
2. 不冲突。SQL 标准里 `NULL` 互不相等，多行 `NULL` 可以并存于唯一约束中，
   `test_run_idempotency_key_unique_within_session_but_null_repeatable` 覆盖了这个行为——
   这既是便利也是漏洞：忘记传幂等键就等于关掉了幂等保护。
3. 只留 `project_id` 会让每次子资源鉴权都多一次 join，且容易被写漏；
   复合外键能强制一致，但要求 `projects` 上有一个 `(id, workspace_id)` 的唯一约束，
   并让所有子表都引用这对列，索引更宽、迁移更难改。当前选了「冗余 + service 层保证」。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> 这个阶段我把整个 Web 平台要用到的十一张表一次定义清楚，并生成了第一版迁移。
> 关键决定有三个。第一，子表冗余存 `workspace_id`，因为租户隔离要求每一次子资源读取
> 都带工作区条件，冗余让它变成一次索引命中而不是层层 join，代价是一致性交给 service 层。
> 第二，事件表按只追加设计，`(session_id, sequence)` 唯一，这个约束同时是 SSE 断线补偿的游标。
> 第三，迁移不是手写的，是从模型 metadata 渲染出来的，这样可以直接断言
> 「迁移与模型的 schema 差异为 0」——测试里就是这么验的。
> 过程里还抓到一个真实缺陷：测试用的探针表挂在生产 `Base` 上，
> 会让后续 autogenerate 往迁移里写一张测试表，已经修掉并加了回归。

**深入追问**

- 问：你怎么证明迁移和模型没有漂移？答：不是靠人看，`test_migration_matches_model_metadata`
  把迁移建出来的库用 `compare_metadata` 和 `Base.metadata` 比，断言差异为空列表。
  这条测试还能反向用：故意给模型加一列不动迁移，它会立刻失败。
- 问：这些验证跑在什么数据库上？答：SQLite，因为这台机器 Docker 引擎不可用、连不上 PostgreSQL。
  所以「结构一致」是验过的，**「在 PostgreSQL 上能建表」没有验过**。这是必须主动说明的边界。

**简历候选表述**：目前证据只到「11 张表 + 迁移 + 13 项结构测试」。
**暂不形成简历条目**——等真实 PostgreSQL 上跑通 upgrade/downgrade、并有 T6 的租户隔离测试之后，
再表述为「设计并实现了多租户数据模型与迁移体系」才有支撑。

**不能声称的能力或结果**：

- 不能说「在 PostgreSQL 上验证过迁移」——没有，只有 SQLite 和离线 DDL 渲染。
- 不能说「做了性能优化」——没有测过任何查询耗时，索引是按访问模式设计的，不是压出来的。
- 不能说「实现了完整的租户隔离」——`workspace_id` 冗余的一致性靠约定，T6 才落校验。

## 后续

- **欠账 1**：`UsageRecord` 需要回填进 plan.md 的数据模型一节；目前它只有 task.md 里的一个名字。
- **欠账 2**：工具调用幂等记录（C32）未建表，等 T12/T14 的执行设计。
- **欠账 3**：真实 PostgreSQL 上的 upgrade / downgrade 验证，与 T3 的阻塞同源（Docker 引擎不可用）。
- **交给 T5 决定**：`users.email` 是否需要大小写不敏感的唯一性。
- **交给 T6**：`workspace_id` 冗余一致性的强制方式，以及 `ProjectRootResolver` 对
  `workspace_path` 相对路径的解析与越界校验。
- 按 Execution Order，T4 是 M1 剩余 9 个任务的入口；下一步分三支：T5→T6、T7→T8、T11。
- 用户练习反馈：**待用户自测**。本文中的动手实验尚未由用户实际执行。
