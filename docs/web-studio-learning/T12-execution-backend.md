# T12：受控执行边界

## 状态与关联

- 日期与里程碑：2026-09-28，任务 T12，里程碑 M1 收口。
- 状态：**已实现并验证**（37 项测试，全部跑真实进程）。
- 代码：`huicode/tools/execution.py`（执行机制，核心包）、
  `huicode/server/runtime/execution_backend.py`（服务端层：路径解析 + 预算收口）、
  `huicode/tools/shell.py`（Shell 工具改为走执行器）。
- 测试：`tests/integration/test_execution_backend.py`（不需要数据库，`pytest tests` 一定跑到）。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 Resource budget and execution boundary、
  [task.md](../../specs/017-web-studio/task.md) 的 T12、checklist C52。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

Shell 是这套系统里权限最大的一环：它不受工具能力声明约束（T10 里 `Bash` 声明成
"什么都能干"），能做任何事。所以这一层不看命令内容——那是黑名单和权限引擎的事——
只把**执行的外壳**钉死：在哪个目录跑、拿到什么环境、能跑多久、输出多大、停下来时
停到什么程度。

前三个问题都有显而易见的答法，第四个不是：

**`subprocess.run(timeout=...)` 超时之后杀掉的是直接子进程。** Windows 上
`shell=True` 意味着直接子进程是 `cmd.exe`，真正的命令是它的子进程；POSIX 上同理。
只杀 `cmd.exe` 会留下一堆孤儿进程继续跑——占着端口、继续写文件，**而调用方以为
已经停了**。这是这一层最值得写下来的东西。

## 原理与数据流

```text
ExecutionRequest（服务端；cwd 是相对路径）
        │
        ├─ resolve_within(workspace, cwd)     ← .. / 绝对路径 / 链接逃逸在这里被拒（C47）
        ├─ min(请求超时, budget.max_shell_seconds)   ← 调用方要不到更多（C54）
        ▼
CommandRequest（核心；cwd 已是绝对路径）
        │
        ├─ build_environment()   白名单 → 去掉敏感名 → 合并显式请求（敏感名报错）
        ├─ Popen(shell=True, 独立进程组)
        │      ├─ 两条读取线程按**共享的**字节账本记账
        │      └─ 到上限 → 立刻终止进程树
        └─ 超时 / 输出超限 → terminate_tree()
               Windows: taskkill /F /T /PID      POSIX: killpg(SIGKILL)
                    │
                    ▼
             ExecutionResult(error_code, ...)
```

## 方案与取舍

### 执行机制在核心包，服务端层只加两样东西

`huicode/tools/execution.py` 是执行机制；`server/runtime/execution_backend.py` 只在
它上面加**工作目录解析**和**预算收口**。

理由与 T10 的能力词表完全一样：**Shell 工具（CLI 与 Web 都走它）需要执行机制，
而工具不能反向依赖服务端**。差一点就写反了——第一版把整个后端放在
`server/runtime/` 下，Shell 工具 import 它，于是 `huicode/tools/` 依赖
`huicode/server/`。写 import 那一行时想起来的，没有测试会红（详见下面"问题一"）。

### 预算收口是取交集，不是覆盖

调用方可以在请求里写 `timeout_seconds=600`，但预算说 `max_shell_seconds=60`，
那就只能跑 60 秒。反过来，调用方要 1 秒、预算给 60 秒，就在 1 秒停。**两个方向
都取更严的那个**，这正是 C54"前端不可绕过资源预算"要的。

### 输出超限是"杀掉"，不是"截断后继续"

先读完 1GB 再截断，内存已经没了。所以在读取端按字节记账，到上限立刻终止进程并
上报失败。两条流**共享**一本账：分开记账的话 `cmd 2>&1` 这类写法等于把上限翻倍。

呈现层（工具返回给模型的那段）另有一次字符截断，两者不是一回事：前者是内存护栏，
后者是可读性。工具里 `max_output_chars * 4` 换算成字节下限，所以正常情况下先撞到
的总是字符截断，字节上限只在异常输出时才起作用。

### 环境变量：白名单 + 敏感名兜底；显式请求要报错

进程环境里有几百个变量，任何一个是密钥都不奇怪，靠"列出敏感名字"是必输的仗。
所以默认**只放行白名单**（PATH、SYSTEMROOT、HOME、LANG……），要额外的由调用方显式补。

补的时候分两种处理：

- **继承来的**敏感变量：静默丢弃。调用方没提过它们，"按策略过滤"就是这个意思。
- **显式请求的**敏感变量：**报错**。静默丢弃会让命令在一个与调用方认知不同的环境里
  运行——它可能因此连到别的服务、写到别的地方。这种"看起来成功了但环境和你想的
  不一样"比直接失败难查得多。

`HUICODE_*` 整段挡掉，不逐个论证哪个安全：服务端自己的配置没有一条是子进程需要的，
论证漏一个就是一次泄露。

### 错误码分两层，刻意不合并

执行边界给运维和事件流看（`shell_timeout`、`shell_output_exceeded`、
`shell_env_rejected`、`shell_spawn_failed`、`shell_path_violation`），工具给模型看
（`timeout`、`nonzero_exit`、`exec_error`……）。合并之后，改一个给运维看的码就会
改变模型看到的东西。

`shell_*` 的常量定义在 `huicode/tools/execution.py`（执行机制所在处），
`server/runtime/errors.py` 反向 import 做聚合——同一套词汇表不能有两份，T10 已经
踩过一次这个坑。

## 实施难点与工程问题

### 问题一：又差点把核心包依赖到服务端上

- 触发条件：按任务书的 Files 把后端整个写在 `huicode/server/runtime/execution_backend.py`，
  Shell 工具 import 它。
- 症状：没有测试会失败——只是 `huicode/tools/` 多了一条指向 `huicode/server/` 的边。
- 根因：**同一个方向错误在 T10 刚写过一次**（能力词表）。这次是在敲 import 那一行
  时想起来的，不是测试抓到的。
- 修改：执行机制下沉到 `huicode/tools/execution.py`，服务端层只留"cwd 解析 + 预算
  收口 + 异步包装 + 进程表"。任务书的 Files 清单跟着改了一行。
- **值得记的是：这类错误没有任何自动化的东西会提醒你。** 两次都是靠"写这一行时
  想一下方向对不对"拦下来的。

### 问题二：T11 的规则漏了 `AWS_SECRET_ACCESS_KEY`（真实缺口）

- 触发条件：写环境过滤时，顺手拿几个真实变量名试 T11 的 `SENSITIVE_KEY_RE`。
- 症状：`GITHUB_TOKEN`、`MY_API_KEY`、`PASSWORD` 都命中，**`AWS_SECRET_ACCESS_KEY`
  不命中**。
- 根因：`_KEY_TOKEN` 要求敏感词是 `_`/`-` 分段的**最后一段**，而 `_KEY_NAMES` 里只有
  `api_key`、`private_key` 这类组合词，没有光秃秃的 `key`——`AWS_SECRET_ACCESS_KEY`
  的末段正是 `KEY`。当初不收裸 `key` 是有道理的（否则 JSON 里随处可见的 `"key"` 会被
  误脱敏），所以这不是"改一行就好"的疏漏，而是**两个用途需要两套规则**。
- 修改：新增 `SENSITIVE_ENV_NAME_RE` + `RESERVED_ENV_PREFIX`，专用于判断**变量名**，
  刻意比文本规则宽：误判只是少传一个变量并给出明确错误，漏判是密钥进子进程。
- **没有改 T11 的文本规则。** 放宽它会重新引入误脱敏；文本与变量名是两个领域。
  这条缺口在 T11 的记录里没有被发现，是 T12 才暴露的。

### 问题三：一个"从来没启动过"的孙进程也能让测试通过

- 触发条件：进程树用例先跑超时命令，再比较标记文件前后是否一致。
- 症状：如果孙进程**根本没起来**，标记文件不存在，前后比较是 `"" == ""`——**通过**。
- 根因：断言的是"它停了"，没有先断言"它跑过"。
- 修改：先等到标记文件出现（带 5 秒上限），再比较。
- 补充验证：把 `taskkill /T` 的 `/T` 去掉重跑，这条用例确实变红，报出
  `孙进程还在写文件——说明只杀了直接子进程，没有终止整棵树`。**护栏是活的**，
  不是摆设。改回后恢复。

### 问题四：测试期望写错了 `shell=True` 下"命令不存在"的行为

- 触发条件：断言"跑一个不存在的命令"会得到 `shell_spawn_failed`。
- 症状：`error_code` 是 `None`，退出码非零，stderr 里有外壳的报错。
- 根因：**被测代码是对的。** `shell=True` 下外壳（cmd.exe / sh）起来了，是它找不到
  要跑的东西——那是外壳自己的退出码，属于"命令的结果"，不是"我们的执行边界出问题"。
  两件事不能混。
- 修改：断言改成"退出码非零且 stderr 非空"，另加一条平台限定的用例（换掉
  `COMSPEC`）来覆盖真正的启动失败。

## 验证证据

环境：仓库自带 `.venv`，Python 3.12.14，Windows 11。**用例跑的都是真实进程。**

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_execution_backend.py -q
```

- 预计与实际：**37 passed**（约 16 秒，其中好几条是等超时）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**724 passed, 14 skipped**（T10 时 687 + 37）。

```powershell
$env:HUICODE_TEST_DATABASE_URL='postgresql+asyncpg://huicode:huicode-dev-password@127.0.0.1:5432/huicode'
.\.venv\Scripts\python.exe -m pytest tests/integration -q
```

- 实际：**92 passed**（14 项真库真 Redis + 41 项权限桥接 + 37 项执行后端）。

关键断言（按"能挡住什么"排列）：

- `test_a_timed_out_command_takes_its_grandchildren_with_it`：**C52 的核心**。
  先生成"孙进程写过文件"的证据，再断言它停了。上面"问题三"的护栏。
- `test_both_streams_share_one_budget`：两条流共享账本，`2>&1` 不能把上限翻倍。
- `test_the_budget_wins_over_a_longer_request` / `test_a_short_request_is_not_stretched_by_a_large_budget`：
  收口是取交集，两个方向都测。
- `test_a_sensitive_variable_cannot_be_requested_explicitly`：显式请求敏感变量报错。
- `test_the_child_really_does_not_see_the_inherited_secret`：**读的是子进程的实际
  输出**，不是断言函数被调用过。
- `test_the_allowlist_itself_contains_nothing_sensitive`：白名单自己得是干净的，
  否则纵深防御的第一层就漏了。
- `test_limits_and_policy_rejections_are_told_apart`：超限与策略拒绝的分类不重叠。

**未覆盖场景与残余风险：**

- **`max_child_processes` 没有实现。** 限制进程数需要 OS 级设施（Linux cgroup v2 的
  `pids.max`、Windows Job Object），标准库不提供；没有它们就只能轮询枚举进程树，既不
  准（进程在两次采样之间生灭）又很贵（Windows 上每次要起 PowerShell 查 CIM，几百
  毫秒）。**留一个看起来生效、实际不生效的配置项比不写更糟**，所以这个字段留在
  plan.md 里并标注未实现。T9 的记录里说"欠账记给 T12"——**现在这笔账转成了明确的不做，
  理由如上**。
- **POSIX 的终止路径没有跑过。** 所有用例都在 Windows 上跑的，`start_new_session` +
  `killpg` 那条分支只有代码审查，没有执行证据。
- **取消没有和 T9 的取消令牌接起来。** `ExecutionBackend.cancel(execution_id)` 是按
  id 找进程树的接口，但"Run 被取消 → 工具进程被终止"这条链要 T16 接线。现在的中断
  只能靠超时。
- **输出的字节上限是"每次执行"，不是"每个 Run"。** T9 的 `record_output` 才是 Run
  级的累计预算，两者还没有接起来。
- **环境变量白名单可能会挡住需要的变量。** 某个工具链依赖一个不在白名单里的变量时，
  它会在子进程里静默消失，表现为工具行为异常而不是报错。补的办法是调用方显式加。
- **没有性能测量。** 每次执行起两个读取线程，代价应当可以忽略，但没测过。
- **强杀不保证副作用一致。** 命令可能在写文件的中途被强杀——这一条与 T9 的残余风险
  是同一个，兜底在 T15 的幂等与恢复。

## 自己动手

**复现实验**

1. ```powershell
   $env:PYTHONIOENCODING="utf-8"
   .\.venv\Scripts\python.exe -m pytest tests/integration/test_execution_backend.py -q
   ```
   预期：37 passed。

2. **亲手把"杀整棵树"改坏**，看护栏是不是活的：把
   `huicode/tools/execution.py` 里 `taskkill` 那行的 `"/T"` 参数删掉，重跑：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/integration/test_execution_backend.py -q -k grandchildren
   ```
   预期：1 failed，报 `孙进程还在写文件——说明只杀了直接子进程，没有终止整棵树`。
   改回后恢复。**注意这条会留下一个跑 15 秒的孤儿进程**，脚本里有界循环就是为它准备的。

3. 看环境过滤实际丢掉了什么：

   ```powershell
   .\.venv\Scripts\python.exe -c "import os; os.environ['AWS_SECRET_ACCESS_KEY']='AKIAIOSFODNN7EXAMPLE'; from huicode.tools.execution import build_environment, is_sensitive_env_name; print('AWS_SECRET_ACCESS_KEY 敏感?', is_sensitive_env_name('AWS_SECRET_ACCESS_KEY')); print('传下去了?', 'AWS_SECRET_ACCESS_KEY' in build_environment())"
   ```
   预期：`敏感? True` / `传下去了? False`。

**小改动练习**

把 `ENV_ALLOWLIST` 里的 `"PATH"` 删掉，然后想清楚会发生什么。

- 会影响什么：Windows 上 `cmd.exe` 仍然能被找到（Popen 用的是绝对路径或 COMSPEC），
  但脚本里所有 `python`、`git` 这类**按名字**调用的命令都会失败。多条用例会红。
- 如何验证：跑第 1 步。再想清楚：白名单收紧到什么程度会开始破坏正常功能？
  **"安全"和"能用"的边界在哪里，是这个模块最需要说清楚的东西。**

**自测问题**

1. 原理：为什么执行机制放在 `huicode/tools/` 而不是 `huicode/server/runtime/`？
2. 异常路径：`shell=True` 下跑一个不存在的命令，`error_code` 是什么？为什么不是
   `shell_spawn_failed`？
3. 取舍：为什么输出超限要杀掉进程，而不是截断后让命令继续跑完？

**答案核对**

1. Shell 工具（CLI 与 Web 都走它）需要执行机制，而工具不能反向依赖服务端——
   服务端不是工具的上游。见 `execution.py` 的模块文档。
2. 是 `None`，退出码非零。外壳本身起来了，是它找不到要跑的东西；那是命令的结果，
   不是执行边界的问题。见 `test_a_missing_command_is_the_shell_reporting_a_nonzero_exit`。
3. 因为"先读完再截断"意味着内存已经涨到 1GB 了——护栏就没起作用。见 `_OutputBudget`。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> Shell 是权限最大的一环，所以这一层不看命令内容，只把执行的外壳钉死：在哪个目录跑、
> 拿什么环境、跑多久、输出多大、停下来时停到什么程度。最值得说的是最后一条：
> `subprocess.run(timeout=...)` 超时后杀掉的是**直接子进程**，而 `shell=True` 下直接
> 子进程是 `cmd.exe`，真正的命令是它的孙子——只杀 `cmd.exe` 会留下孤儿进程继续写
> 文件，而调用方以为已经停了。所以启动时就把子进程放进独立进程组，终止时用
> `taskkill /T` 或 `killpg` 整棵带走。环境变量用的是白名单而不是黑名单：进程环境里
> 几百个变量，靠列敏感名字是必输的仗；显式请求敏感变量要**报错**而不是静默丢弃，
> 因为静默丢弃会让命令在一个和调用方认知不同的环境里跑，那种问题比直接失败难查得多。

**深入追问**

- 问：怎么证明进程树真的被杀了？答：用例里先让孙进程写文件、确认它写过，再断言
  文件停止变化。我还把 `taskkill /T` 的 `/T` 去掉验证过这条用例会变红。
- 问：`max_child_processes` 实现了吗？答：**没有。** 限制进程数需要 cgroup 或 Job
  Object 这类 OS 设施，标准库不提供；轮询枚举既不准又很贵。留一个看起来生效的配置项
  比不写更糟。**能确定做到的是超时后终止整棵树，那才是进程边界的实质。**
- 问：这套在 POSIX 上验证过吗？答：**没有。** 所有用例都跑在 Windows 上，
  `killpg` 那条分支只有代码审查。

**简历候选表述**：证据到「受控执行边界 + 进程树终止 + 环境白名单 + 37 项真实进程测试」。
可表述为「实现受控命令执行边界，保证超时后整棵子进程树退出」，**不要**说成
"实现了沙箱"——路径校验不等于沙箱，也没有容器隔离。

**不能声称的能力或结果**：

- 不能说「实现了 Shell 沙箱」——只是进程边界 + 环境过滤，没有隔离机制。
- 不能说「进程数受控」——`max_child_processes` 未实现。
- 不能说「POSIX 上也验证过」——只在 Windows 上跑过。
- 不能说「取消能中断正在跑的命令」——链路要 T16 才接上。

## 后续

- **明确不做（曾是 T9 的欠账）**：`max_child_processes`。理由见上，**这条要在 M1
  复盘和 plan.md 里对齐**。
- **交给 T16**：把 `cancel(execution_id)` 接上 T9 的取消令牌；把每次执行的输出字节
  记进 T9 的 `record_output`（Run 级累计预算）。
- **交给 T15**：强杀时的副作用一致性。
- **待补**：POSIX 终止路径的验证。
- 用户练习反馈：**待用户自测**。
