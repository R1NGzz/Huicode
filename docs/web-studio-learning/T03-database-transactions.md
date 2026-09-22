# T3：连接池、Session、事务与迁移入口

状态：2026-09-22，数据库基础实现及 SQLite 事务测试通过；PostgreSQL 在线验证未完成。AI 辅助实现，用户理解状态待自测。

## 业务场景

以后用户提交一句话，系统需要同时创建 Run 和写入排队事件。如果 Run 保存成功、事件保存失败，系统可能显示一个没有后续进度的任务。因此这两次写入应该放在同一个事务中：一起成功，或一起撤销。

本阶段还没有 Run 表，使用测试专用 Probe 表验证这个机制，不把测试表当成业务模型。业务模型在 T4 添加。

## 源码与数据流

- [session.py](../../huicode/server/db/session.py)：Database 创建 Engine 和 Session 工厂，transaction 管理提交/回滚。
- [base.py](../../huicode/server/db/base.py)：约定 UUID、时间字段和约束名称。
- [repositories](../../huicode/server/db/repositories/__init__.py)：绑定工作区的查询和添加入口，不提供 commit。
- [env.py](../../migrations/env.py)：Alembic 异步迁移入口。
- [test_database.py](../../tests/server/test_database.py)：真正写入临时 SQLite 文件，再从新会话读取，验证提交和回滚。

数据流：应用共享 Database/Engine → 每笔业务创建独立 Session → 多个 Repository 使用同一 Session → 正常退出提交 / 异常退出回滚 → 关闭 Session、连接归还池中 → 应用退出释放连接池。

## 三个容易混淆的概念

Engine 管理数据库连接及连接池；Session 跟踪一笔业务访问和修改的 ORM 对象；事务是数据库对这组操作的提交或撤销边界。Session 不应在多个异步任务之间并发共享。应用可以共享 Engine，但每笔业务需要独立 Session。

`flush()` 把待处理 SQL 发到数据库，可以发现约束错误或获取生成字段，但没有完成最终提交。异常发生在 flush 之后仍应回滚。因此测试特意在 flush 后抛错，而不是仅在 add 后抛错。

`async with database.transaction()` 正常退出时提交，异常或任务取消时回滚。Repository 不自行提交，业务才能将多个写操作组成一个整体。业务代码如果捕获异常并继续正常退出，就可能提交已做的修改，所以事务内不能无意吞掉失败。

## 选型及边界

- 使用 SQLAlchemy 自带事务上下文，减少手工 commit/rollback 遗漏；连接池启用 pre_ping 检查取出的连接是否存活，它不保证随后整个事务绝不会断线。
- SQLite 用于本地快速验证 Session 和事务行为。它不能代替 PostgreSQL 的并发锁、时区、隔离级别和特定索引测试。SQLite 读取时间字段的时区行为也不同，不据此声称 PostgreSQL 时间处理已验证。
- UUID 和时间默认值在 ORM 写入时生成，直接 SQL 写入不能假设存在数据库默认值；T4 建表时再明确是否需要服务端默认值。
- 工作区 Repository 自动带 workspace_id 条件，但这不是完整租户安全：调用方首先要验证用户确实属于这个工作区，直接使用原始 Session 仍可能绕过封装。
- Alembic 只读取 HUICODE_DATABASE_URL，不要求启动迁移时还提供 JWT 等 Web 配置；URL 不放进 ini，避免把密码写入版本库。
- API 健康检查复用 Database 封装，业务后续使用同一应用生命周期内的实例。迁移进程使用独立短生命周期 Engine 和 NullPool。

## 实际验证与工程问题

命令：`.\.venv\Scripts\python.exe -m unittest tests.server.test_database tests.server.test_app tests.server.test_config tests.test_config -q`。结果：36 项通过，其中新增数据库测试 5 项，覆盖正常提交、flush 后异常回滚、真实异步任务取消回滚、跨工作区访问和两个 Repository 原子回滚。

`alembic upgrade head --sql` 成功加载迁移环境，输出 BEGIN/COMMIT；`alembic heads` 无版本输出，因为业务迁移尚未创建。这验证了离线入口，不是建表升级成功。

尝试 Docker PostgreSQL 在线验证时，Docker CLI 存在，但引擎命名管道不存在；无法连接 Docker 引擎，因此未创建容器、未修改已有数据库。PostgreSQL 在线连接与升级留待引擎可用后验证。

## 自己动手：从五个测试理解事务

第一步：打开 PowerShell，完整复制执行：

```powershell
Set-Location 'C:\Users\Administrator\Documents\Huicode'
.\.venv\Scripts\python.exe -m unittest tests.server.test_database -v
```

预期看到 5 个测试都是 ok，最后 `Ran 5 tests` 和 `OK`。测试自己创建和清理临时数据库，不依赖 Docker，也不使用真实项目数据库。若提示缺少 aiosqlite，运行 `.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -e '.[server,server-test]'` 后重试。

第二步：打开本篇链接的 test_database.py，找到 `test_exception_rolls_back_flushed_changes`。逐行对照：添加行 → flush → 故意抛错 → 用新 Session 统计，结果为 0。只运行这一项：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.server.test_database.DatabaseTests.test_exception_rolls_back_flushed_changes -v
```

预期 OK。这里业务操作故意失败，测试成功表示失败后的数据确实被撤销。

第三步：找到 `test_commit_visible_from_new_session_and_defaults`，对比没有抛错时行数为 1。再找到 `test_task_cancellation_rolls_back`：先等待 SQL 发出，再 cancel，最后计数 0。取消不是普通 Exception，但事务上下文仍负责清理。

小改动练习（可选）：在 `test_two_repositories_share_one_business_transaction` 中，复制一行 second.add，改名字为 third，再运行该测试。预期仍为 OK、最终 0 行：原子性覆盖整个事务，并不只回滚最后一条。练习后只删除你新增的那一行，不用 git restore 覆盖其他未提交修改。

## 自测和面试表达

1. 为什么不让 Repository 每次 add 就 commit？这样跨 Repository 的业务无法整体回滚。
2. flush 成功能否通知用户任务已经创建？不能，需要等事务提交；通知的一致性还要在后续事件/队列任务中处理。
3. workspace_id 条件是否已经解决权限问题？没有，身份与工作区成员关系还要验证。

可据实说明：建立统一事务边界，并验证异常和取消后的回滚行为；不要声称已验证 PostgreSQL 高并发、分布式事务或完整多租户安全。
