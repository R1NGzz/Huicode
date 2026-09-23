# T6：工作区、项目与路径解析

## 状态与关联

- 日期与里程碑：2026-09-22 / 09-23，任务 T6，里程碑 M1。
- 状态：**已实现并验证**。14 项路径解析单测 + 17 项接口测试在 SQLite 上通过；
  另有 4 项在真实 PostgreSQL 上的接口级集成测试通过。
- 代码：`huicode/server/runtime/workspace_resolver.py`、`huicode/server/domain/audit.py`、
  `huicode/server/domain/projects.py`、`huicode/server/domain/errors.py`、
  `huicode/server/api/workspaces.py`、`huicode/server/api/projects.py`；
  `auth/dependencies.py` 增加 `require_project_role` 与 `get_resolver`。
- 测试：`tests/server/test_workspace_resolver.py`（14）、
  `tests/server/test_projects_api.py`（17）、`tests/integration/test_postgres_projects.py`（4）。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 API contracts 与
  `runtime/workspace_resolver.py`、[task.md](../../specs/017-web-studio/task.md) 的 T6。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

用户在浏览器里创建一个项目，填一个目录名。这个目录名会被服务端拼成真实路径，
之后 Agent 的读写、Shell 的工作目录都以它为根。

**不处理会怎样**：填 `../../` 就能让 Agent 在宿主机任意目录里读写；填一个指向
`C:\Users\` 的符号链接/junction，路径文本看起来还完全在项目目录内。而 Web 端
的调用者不再是坐在终端前的那个人——CLI 里用户对自己的机器负责，Web 里必须由
服务端来保证边界（C46–C48）。

## 原理与数据流

```text
请求 { "workspace_path": "demo" }
   │
   ├─ 词法检查   拒绝绝对路径 / 盘符 / UNC / ".." / NUL / Windows 保留设备名
   │
   ├─ 拼接并解析  project_root / "demo" → Path.resolve() 展开所有链接
   │
   ├─ 包含检查   解析后的真实路径是否仍在 project_root 之内
   │
   └─ 规范化落库 存 "demo"（相对 POSIX 路径），不存绝对路径
```

**为什么不能只做字符串前缀判断。** `str(path).startswith(root)` 会被三类输入骗过：

1. `..` —— 路径里没有可疑字符，但拼出来已经跳出目录；
2. 符号链接 / junction —— 文本完全在根目录内，链接指向根目录外；
3. Windows 大小写与分隔符变体 —— `C:\Root` 与 `c:/root/..` 文本不同、指向可以相同。

所以词法检查和解析后检查**两道都要有**：词法挡掉明显的越界并给出清晰错误，
解析后检查挡住链接逃逸。少任何一道都不成立。

**写不存在的文件时，锚点是最近的已存在祖先。** 这是最容易漏的一处。`root/link/new.txt`
里 `new.txt` 不存在，如果只对叶子调用 `resolve()`，`link` 不会被展开，检查会假通过。
所以 `_resolve_existing_ancestor()` 先向上找到真实存在的那一级，解析它，再把未存在的
后缀接回去。测试 `test_link_escaping_project_is_rejected` 同时覆盖了"叶子存在"和
"叶子不存在"两种情形。

**`workspace_id` 强制注入。** domain 层不提供 `get_project(session, project_id)`，
只有 `get_project(session, workspace_id, project_id)`。越权最典型的形状是"知道别人的
id 就能读"，去掉那个便利入口，调用方就算想越权也得自己把 workspace_id 编出来，
而不是"忘了传"。

## 方案与取舍

- **项目路径存相对形式，不存绝对路径。** 绝对路径会把宿主机目录结构写进数据库，
  也会让 C48「API 无法创建指向未授权宿主机路径的项目」更难守。落库前统一规范化为
  相对 POSIX 路径，`./demo/`、`demo\`、`demo` 在库里是同一个值。
- **`..` 一律拒绝，不做"归一化后仍在内部就放行"的宽容处理。** 宽容处理更难预测，
  也让审计里的尝试痕迹变得模糊。代价是某些客户端需要自己先规范化路径。
- **角色门槛按 C6**：创建/重命名/归档项目要求 `admin`；查看成员要求 `member`，
  查看项目列表要求 `viewer`。plan.md 写的是"admin 管理项目、成员、审计和用量"。
- **非成员一律 404。** 项目不存在、不在自己所在的工作区、是成员但角色不够——
  前两种返回 404，只有第三种是 403。若"不是成员"返回 403，就等于提供了一个
  "这个 project_id 是否存在"的探测接口。
- **`/api/projects/{id}` 的工作区从项目反查。** 路径里没有 workspace_id，
  所以 `require_project_role` 先按 id 取项目、再校验成员关系，最后才判角色。
- **预检查 + 数据库唯一约束，两层都要。** 见下节。

### 一个必须写清楚的取舍：预检查不是并发保护

`create_project` 先 `SELECT` 查重名，再 `INSERT`。两个请求可以同时查完、再同时插入，
所以真正拦住重复的是数据库上的 `uq_projects_workspace_id_name`。

如果只依赖预检查，并发下会漏一个 `IntegrityError` 出去，表现为 **500 而不是 409**。
处理方式是用 SAVEPOINT 包住这次写入：

```python
try:
    async with session.begin_nested():
        session.add(project)
        await session.flush()
except IntegrityError:
    raise DuplicateProjectName("该项目名已存在") from None
```

`begin_nested()` 让这次失败只回滚到保存点，外层事务仍然可用——这一点很重要，
否则后续的审计写入会连带失败。

## 实施难点与工程问题

**T6 没有出现新的产品缺陷。** 按仓库约定，没有真实踩坑就不编造。这一节记录两件
确实发生、且值得留下的东西。

### 一次跨任务生效的经验（不是 T6 发现的，但在 T6 用上了）

T5 发现过一个隐蔽问题：请求级事务在异常时回滚，所以"先写库、再抛异常"的写法会把
写进去的东西悄悄丢掉。T6 的验收要求"所有非法路径均被拒绝**并记录审计事件**"——
正是同一个形状：拒绝（抛异常）与记录审计（写库）在同一请求里。

这次没有重新踩一遍，而是直接按 T5 的结论实现：路径被拒时**先写审计、再
`return error_response(...)` 正常返回错误**，让事务照常提交。

```python
except InvalidProjectPath as exc:
    await audit.record(..., action="project.path_rejected", ...)
    return error_response(request, ApiError(400, "invalid_project_path", exc.message))
```

对应的断言是 `test_traversal_paths_are_rejected_and_audited`：8 次非法尝试，
每一次都要求状态码 400 **且审计表里恰好留下 8 行**。只断言状态码的话，
审计被回滚掉这个 bug 依然会通过。

### 设计风险（已加固，但仍有限制）

重名并发的加固方式是用 SAVEPOINT 把 `IntegrityError` 转成领域错误。测试
`test_duplicate_name_race_yields_409_not_500` 把预检查打成"没查到"来模拟它被并发绕过，
断言结果是 409。

**这条测试模拟的是"预检查被绕过"，不是真实并发。** 另外单独验证过数据库约束确实
会触发（直接插入两条同名同工作区的记录，确认 `IntegrityError` 抛出）。两者合起来
才能说明 409 来自异常转换而不是预检查——分开看，任何一条都不足以证明。

## 验证证据

环境：仓库自带 `.venv`，Python 3.12.14，Windows 11。真库为 `postgres:18-alpine` 容器。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_workspace_resolver.py tests/server/test_projects_api.py -q
```

- 预计与实际：**31 passed**（14 + 17）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**525 passed, 9 skipped**（T5 时 495 + 31），47.99s。
  skipped 的 9 项是需要真库的集成测试，未设环境变量时不跑。

```powershell
$env:HUICODE_TEST_DATABASE_URL = 'postgresql+asyncpg://huicode:huicode-dev-password@localhost:5432/huicode'
.\.venv\Scripts\python.exe -m pytest tests/integration -v
```

- 实际：**9 passed / 320s**，其中 4 项是 T6 的接口级真库用例：
  项目全生命周期、路径穿越被拒且审计保留、链接逃逸被拒、跨工作区隔离。

真库那一轮特意覆盖了 `audit_logs`：SQLAlchemy 声明式基类把 `metadata` 用作保留属性，
模型里属性叫 `audit_metadata`、列名保留 `metadata`。这条映射在 SQLite 上通过不代表
在 PostgreSQL 上通过（保留字与参数绑定都可能不同），所以单独验了一次。

**未覆盖场景与残余风险：**

- **链接逃逸只在 Windows 上验过**（用 junction 构造，不需要管理员权限）。
  POSIX 符号链接、以及 `\\?\` 长路径前缀、挂载点（mount point）都没有实测。
  测试里建不出链接时会 **skip 而不是假装通过**，并说明原因。
- **resolver 目前没有被任何文件工具使用。** 它只被项目创建接口调用。真正的读写路径
  要等 T10（能力与权限桥接）和 T12（受控执行后端）接上去之后才算闭合。
  现在验证的是"解析器本身正确"，不是"文件操作安全"。
- **"归档项目写入"只覆盖了重命名。** 在已归档项目里创建会话、发起 Run，要等 T13。
- **列表接口没有分页。** 项目数量大的工作区会一次性返回全部。
- 真实并发下的重名冲突没有被真正跑过（见上一节）。
- 工作区成员管理（增删成员、改角色）没有接口，只有列表。T6 的 Files 里也没有它，
  但 plan.md 的 API contracts 同样没列——**这是一个尚未规划的功能点**。

## 自己动手

**复现实验**

前置：PowerShell，仓库根目录，存在 `.venv` 与一个可写临时目录。

1. 跑路径解析测试：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_workspace_resolver.py -v
   ```

   预期：14 passed。注意 `test_link_escaping_project_is_rejected` 是否真的执行
   （出现 `skipped` 说明当前环境建不出 junction）。

2. 亲眼确认"叶子不存在"这条防线。把 `workspace_resolver.py` 里
   `resolve_within` 的 `_resolve_existing_ancestor(candidate)` 改成
   `candidate.resolve()`（非严格模式也会展开父级，但语义上放弃了"锚在已存在祖先"），
   再重跑第 1 步，观察 `escape/brand-new.txt` 那条子用例是否变化。

   预期：这一步**不一定**失败——`Path.resolve()` 的非严格模式在多数实现里同样会展开
   父级链接。真正的差别在语义与可读性上。做完请改回，并想清楚：如果换成"只对
   已存在的叶子做检查"的写法，会在哪里漏。

3. 看审计有没有被回滚：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_projects_api.py -q -k traversal
   ```

   预期：通过。若把 `api/workspaces.py` 里的 `return error_response(...)` 改回
   `raise ApiError(...)`，这条测试会失败——审计行会随事务回滚一起消失。

**小改动练习**

给项目加一个"描述"字段（`description`，可空字符串，最长 500）。

- 会影响什么：模型加列 → 需要新迁移（`0003_...`）→ 创建/重命名的请求模型与响应模型
  都要加 → 迁移链测试会自动发现"模型改了但迁移没跟"。
- 如何验证：`pytest tests/server/test_models.py::ModelSchemaTests::test_migration_matches_model_metadata`
  必须通过；它比对迁移建出来的 schema 与模型 metadata，差异必须为空。
- 建议在分支上做。

**自测问题**

1. 原理：为什么 `..` 要在词法层直接拒绝，而不是先规范化再判断是否越界？
   两种做法各自的失效场景是什么？
2. 异常路径：`/api/projects/{project_id}` 里，如果工作区不是从项目反查、
   而是要求客户端在请求体里传 `workspace_id`，会引入什么问题？
3. 取舍：非成员返回 404 而不是 403，代价是什么？什么情况下你会反过来选 403？

**答案核对**

1. 词法拒绝可预测、审计痕迹清楚，但要求客户端自己规范化；先规范化再判断更宽松，
   但 `..` 与链接的组合（`a/../link`）会让判断依赖解析时机，且"被拒绝"与"被接受但
   归一化了"的界限变模糊。见 `workspace_resolver.py` 顶部的说明。
2. 客户端可以传一个自己属于的 workspace_id 来"认领"别人的 project_id，
   或者用不匹配的 workspace_id 做探测。所以必须从资源本身反查归属，
   绝不能相信请求里带的归属信息。见 `require_project_role`。
3. 代价是调试困难——用户看不出"我没有权限"和"这东西不存在"的区别。
   若产品明确要求可解释的权限提示，且资源 id 不可枚举（如随机 UUID 且不泄露），
   可以改为 403 + 明确的权限说明。见 `auth/dependencies.py` 的说明。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> 项目路径是用户输入的，Web 端不能让调用者自己保证边界，所以服务端做两道检查：
> 先词法上拒绝绝对路径、盘符、UNC 和 `..`，再把路径 `resolve()` 展开所有符号链接和
> junction，确认真实位置仍在配置的项目根目录内。只有字符串前缀判断是不够的——
> `..` 和链接都能骗过它。有个容易漏的点：写一个还不存在的文件时，要检查它最近的
> 已存在祖先，否则叶子不存在、链接不会被展开，检查会假通过。落库存的是相对路径
> 而不是绝对路径，避免把宿主机目录结构写进数据库。另外所有查询都强制带
> workspace_id，非成员一律 404 而不是 403，否则状态码本身就变成了资源探测器。

**深入追问**

- 问：你怎么证明非法路径真的被挡住了？答：14 项解析单测覆盖词法拒绝、链接逃逸
  （叶子存在与不存在两种）、前缀相近的兄弟目录；17 项接口测试覆盖穿越与逃逸被拒，
  并在真库上重跑了其中 4 项。链接逃逸用真实 junction 构造，不是 mock。
- 问：用户提交重名项目会怎样？答：返回 409。**但要主动说明**：重名判断有两层——
  预检查给友好错误，真正拦住的是数据库唯一约束；并发下由 SAVEPOINT 把
  `IntegrityError` 转成 409。这条路径我只用"把预检查绕过"的方式模拟过，没有跑真实并发。

**简历候选表述**：证据到「路径解析与越界防护 + 工作区隔离 + 31 项测试」。
可表述为「实现了多租户项目模型与路径沙箱」，但**不要**说成"实现了完整的文件系统沙箱"
——resolver 还没接进任何文件操作，那是 T10/T12 的事。

**不能声称的能力或结果**：

- 不能说「文件读写是安全的」——resolver 目前只被项目创建接口调用。
- 不能说「验证了符号链接防护」——Windows 上验的是 junction；POSIX symlink 没测。
- 不能说「并发重名已被正确处理」——只模拟了预检查被绕过，没有真实并发验证。
- 不能说「有完整的成员管理」——只能列出成员，不能增删改角色。

## 后续

- **交给 T10/T12**：把 resolver 接进真正的文件读写与 Shell 工作目录；届时需要
  重新验证"越界被拒"是在文件操作路径上成立，而不只是解析器本身。
- **交给 T13**：已归档项目内禁止创建会话与发起 Run。
- **尚未规划**：工作区成员管理接口（增删成员、改角色）。plan.md 的 API contracts
  里没有，需要补设计再实现。
- **待决定**：列表接口是否要分页；`..` 的宽容处理是否需要为某些客户端放开。
- **环境**：真实 PostgreSQL/Redis 已可用（Docker 容器），真库集成测试成为常规手段，
  见 [本地开发文档](../web-studio-local-development.md)。
- 按 Execution Order，T6 完成后 T5→T6 支线结束；接下来是 T7→T8（统一 Runtime Event
  类型与事件持久化）与 T11（SecretScrubber）。
- 用户练习反馈：**待用户自测**。本文的动手实验尚未由用户实际执行。
