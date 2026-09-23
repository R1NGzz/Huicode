# T11：SecretScrubber

## 状态与关联

- 日期与里程碑：2026-09-23，任务 T11，里程碑 M1。
- 状态：**已实现并验证**（19 项新增测试，含落库与 API 响应两条接入点）。
- 代码：`huicode/memory/scrub.py`（规则库，扩展）、`huicode/server/runtime/scrubber.py`
  （`SecretScrubber` 与日志过滤器）、`huicode/server/runtime/scrubbing.py`（进程级实例）。
- 接入点：`events/store.py`（事件落库）、`domain/audit.py`（审计落库）、
  `app.py`（日志过滤器与错误响应）。
- 测试：`tests/server/test_scrubber.py`。
- 设计文档：[plan.md](../../specs/017-web-studio/plan.md) 的 SecretScrubber 协议、
  [task.md](../../specs/017-web-studio/task.md) 的 T11、checklist C55–C58。
- 实际参与方式与用户理解状态：AI 辅助实现，**用户理解状态待自测**。

## 场景与问题

Agent 会把工具输出、模型消息和异常原文写进事件、审计和日志。这些内容里完全可能
夹着密钥：用户让 Agent 改一个配置文件，文件内容就进了工具参数；上游把 `Authorization`
回显在错误响应里；连接串出现在"连不上数据库"的异常里。

对照 C55–C58：日志、事件、存储、API 响应四处的密钥都要被脱敏。**只要有一处漏了，
密钥就会长期躺在数据库或日志里**——而审计和事件表是只追加的，删不干净。

## 原理与数据流

```text
规则库  huicode/memory/scrub.py
   SECRET_PATTERNS  文本规则（连接串密码、Bearer、私钥块、各供应商 key 形状、敏感环境变量、通用 key:value）
   SENSITIVE_KEY_RE 键名规则（给结构化脱敏用）
        │
        ├── memory 模块直接用 scrub_secrets()（既有行为不变）
        │
        └── SecretScrubber（server/runtime/scrubber.py）
               scrub_text / scrub_payload / scrub_event / scrub_exception
                    │
                    └── 进程级实例（runtime/scrubbing.py，create_app 时按配置装上）
                           ├─ events/store.py 写入前 → C56 / C57
                           ├─ domain/audit.py 写入前 → C57
                           ├─ 日志过滤器（逐 logger 装） → C55
                           └─ app.py 错误处理器 → C58
```

**规则只有一份。** 两处各写一套"什么算密钥"，迟早出现"记忆里脱敏了、事件里没有"。
所以 memory 模块的 `scrub_secrets` 与服务端共用同一个 `SECRET_PATTERNS`。

**脱敏放在写入路径里，不放在调用方。** `store.append` 自己调 `get_scrubber()` 脱敏，
而不是要求调用方先脱好再传。理由：漏传一处的后果是密钥落库，而"忘了也安全"的默认值
才是能长期守住的那种。

## 方案与取舍

- **标记固定为 `[REDACTED]`，不带种类。** memory 模块既有输出就是这个格式，改它
  （例如 `[REDACTED:api_key]`）会让既有测试和输出契约一起变，收益有限。
- **宁可多脱敏。** 规则有意包含会误伤的形态（任何 `token: xxx` 都会被脱敏）。
  漏脱敏的代价是密钥落库，误脱敏的代价只是日志难读——两者不对称。
- **但误伤要有边界。** `max_tokens` / `token_count` / `PORT` 这类常见配置必须放过，
  否则日志会被糊成一片，反而没人看。见下面"问题二"。
- **已知值脱敏作为兜底。** 除了形状匹配，还把配置里真实存在的密钥（JWT secret、
  连接串密码）按字面值抹掉，兜住"形状不匹配任何规则"的自定义密钥。
  但**只取连接串的密码部分，不取整条 URL**——整条抹掉会让"连不上数据库"这类
  错误信息失去主机名和库名。
- **短于 8 字符的"已知密钥"不参与字面替换。** 太短的值会在正常文本里到处命中。
- **进程级脱敏器，而不是层层传参。** 让"是否脱敏"变成一个可以被忘记传的东西是
  危险的默认值。代价是测试之间会互相影响，所以测试要显式 `reset()`。

## 实施难点与工程问题

### 问题一：规则重复施加会留下残片（真实问题）

- 触发条件：同一个字符串过两道脱敏（事件先脱一次、日志再脱一次，或测试里连调两次）。
- 症状：`api_key=[REDACTED]]`——多出一个 `]`；`Authorization: [REDACTED] [REDACTED]`——
  变成了两段。

  两个症状同一个根因的两个侧面：

  1. 通用 `key: value` 规则的值字符集排除了 `]`（为了避免吃掉 JSON 结构），所以
     第二次施加时它匹配到 `[REDACTED` 就停了，留下孤立的 `]`。
  2. `Authorization: Bearer <token>` 那条只吃掉了凭据、保留了 `Bearer` 关键字，
     于是第二轮里兜底规则把 `Bearer` 当成一个"值"又脱敏了一次。

- 根因：**规则没有对"已脱敏结果"免疫。**
- 修改：所有带值的规则，前缀之后统一加 `(?!\[REDACTED\])` 负向前瞻；
  `Authorization` 那条把方案关键字（`Bearer`/`Basic`）一起吃掉。
- 回归：`test_scrubbing_is_idempotent` 对全部 14 类样本断言"脱两次 == 脱一次"。

**这条约束写进了规则文件顶部**，因为新增规则时最容易再犯。

### 问题二：`(?i)` 让环境变量规则误伤普通配置（真实问题）

- 触发条件：给敏感环境变量规则加了忽略大小写。
- 症状：`token_count=5` 被脱敏成 `token_count=[REDACTED]`。
- 根因：`(?i)` 让字符类 `[A-Z0-9_]*` 也匹配小写字母，于是 `token_count` 整体被
  当成了"名字里含 TOKEN 的环境变量"。环境变量名按约定是全大写的。
- 修改：这条规则**去掉 `(?i)`**（其余规则保留）。
- 补充：通用键名规则也从"前面必须是空白或行首"改成"敏感名作为 `_`/`-` 分段后的
  词尾"，这样 `openai_api_key` 能匹配，而 `max_tokens`（分段为 `max`+`tokens`，
  `tokens` ≠ `token`）不会。
- 回归：`test_ordinary_config_values_are_not_touched` 覆盖了 `PORT` / `token_count`
  / `max_tokens` / `model` / `temperature` 五种常见配置。

这两个问题都是**写完之后用一组样本自己跑出来的**，不是上线才暴露——值得一提的
是它们的方向相反：问题一是漏（残片说明第一轮没脱干净），问题二是误伤。
脱敏器两个方向都会出错，所以验证必须同时覆盖"该脱的脱了"和"不该脱的没动"。

### 一个容易漏的运行时细节

**logger 上的 filter 不随记录向上传播。** `huicode.server.requests` 产生的记录会
冒泡到父 logger 的 handler，但**不会经过父 logger 自己的 filter**。所以只给
`huicode.server` 装过滤器是无效的，必须逐个 logger 装。这条写在
`install_log_scrubbing` 的文档字符串里。

## 验证证据

环境：`.venv` + Python 3.12.14；落库用例跑在真实 SQLite 文件上。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_scrubber.py -q
```

- 预计与实际：**19 passed**。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 实际：**598 passed, 14 skipped**。

关键断言（按"能挡住什么"排列）：

- `test_event_payload_is_scrubbed_before_it_reaches_the_database`：读回落库的行，
  断言密钥不在其中——**不是断言 scrubber 被调用过**。
- `test_tool_arguments_are_scrubbed_on_the_way_to_the_database`：把 T7 的映射器与
  T11 的落库接起来跑一遍。单独验任一端都说明不了"这条路径是安全的"。
- `test_error_response_is_scrubbed`：探针路由抛出把配置值拼进消息的错误，
  断言响应体里没有原文。
- `test_unscrubbed_payload_still_contains_the_value_before_wiring`：**反向对照**。
  不经过 store 的裸字典里值当然还在——用来证明上面那条不是空断言。
- `test_scrubbing_is_idempotent` / `test_ordinary_config_values_are_not_touched`。

**未覆盖场景与残余风险：**

- **Artifact 与 Diff 的脱敏没有接入**，因为这两个功能还不存在（T18）。T11 步骤 3
  要求接入，目前只完成了事件、审计、日志、错误响应四处。
- **memory 模块的既有调用点没有跟着扩展。** 它们仍走 `scrub_secrets`（规则已更新，
  但拿不到"已知值"那一层，因为它们没有 settings）。
- **只覆盖文本与 JSON 结构。** 二进制内容整个换成标记（不猜测），但不做格式识别。
- 规则是**启发式**的：自定义格式的密钥若形状不匹配、又没进 `known_secrets`，
  仍然会漏。没有做熵检测之类的手段。
- 没有任何性能测量。事件写入路径每次都要跑十几条正则，高吞吐下是否成为瓶颈未知。
- `SecretScrubFilter` 会改写 `record.msg`，**第三方 handler（例如结构化 JSON handler）
  若在 filter 之前已经格式化了消息**，仍可能拿到原文。当前没有这样的 handler。

## 自己动手

**复现实验**

1. 看规则库对一组样本的行为：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/server/test_scrubber.py -v
   ```
   预期：19 passed。

2. **亲手制造一次"残片"**，确认幂等断言真的在挡东西：把 `memory/scrub.py` 里
   `_NOT_YET_REDACTED` 的定义改成空字符串 `""`，重跑第 1 步。

   预期：`test_scrubbing_is_idempotent` 失败，输出里能看到 `[REDACTED]]` 这类残片。
   改回后恢复。

3. 看已知值脱敏和规则脱敏的差别：

   ```powershell
   .\.venv\Scripts\python.exe -c "from huicode.server.runtime.scrubber import SecretScrubber; print(SecretScrubber(['my-custom-secret-value']).scrub_text('用它 my-custom-secret-value 去连'))"
   ```
   预期：`用它 [REDACTED] 去连`。这个值不匹配任何形状规则，只靠"已知值"那一层。

**小改动练习**

给规则库加一条"邮箱地址"的脱敏，再想清楚为什么**不该**加。

- 会影响什么：邮箱不是密钥，脱掉它会让审计里"谁改了这个项目"变得不可读。
  但它确实是个人信息（C18 提到敏感信息保护）。
- 如何验证：跑全量测试，看有多少条既有断言因为邮箱被脱敏而失败——这个数量本身就
  说明"脱敏范围"和"可用性"之间的张力。

**自测问题**

1. 原理：为什么脱敏要放在 `store.append` 里，而不是要求调用方先脱好再传？
2. 异常路径：一个自定义格式的密钥（例如 `myco_` 开头、长度 40）出现在工具输出里，
   现有的哪一层能挡住它？哪一层挡不住？
3. 取舍：`max_tokens` 这类误伤为什么要专门防？少脱一点不是更省事吗？

**答案核对**

1. 因为"忘了脱敏"的默认值必须是安全的。放在调用方，漏一处就是密钥进库且删不干净
   （事件表只追加）。见 `store.py` 的 `_to_row`。
2. 只有 `known_secrets` 那一层能挡——前提是它出现在配置里（JWT secret、连接串密码）。
   形状规则挡不住，因为它不匹配任何已知形态。**这正是已知值脱敏存在的理由**，
   但反过来说，一个既非配置、形状又陌生的密钥是挡不住的。
3. 因为误伤会让日志不可读，而不可读的日志等于没有日志。安全措施如果让排查变难，
   实际使用时就会被人为绕过。

## 面试表达

**一分钟讲法**（仅基于本次已验证事实）：

> 我把"什么算密钥"收敛成一份规则，memory 和服务端共用。在它之上做了三件事：
> 按**键名**判断的结构化脱敏（纯文本规则看不穿 `{"password": {...}}` 这种嵌套）、
> 按**已知值**的字面替换（兜住形状不匹配的自定义密钥）、以及异常脱敏（保留类型名，
> 丢掉原值）。接入点选了写入路径而不是调用方——漏传一处的后果是密钥进只追加的
> 事件表，删不干净，所以默认值必须是"忘了也安全"。过程中踩了两个方向相反的坑：
> 规则重复施加会留下残片（说明第一轮没脱干净），以及忽略大小写让 `token_count`
> 这类普通配置被误伤。脱敏器两个方向都会错，验证必须同时断言"该脱的脱了"和
> "不该脱的没动"。

**深入追问**

- 问：你怎么证明密钥真的没落库？答：落库用例是把行读回来断言原文不在其中，
  而不是断言脱敏函数被调用过；并且配了一条反向对照——不经过 store 的裸字典里
  值当然还在。另外有一条把 T7 的工具参数映射和 T11 的落库接起来跑的用例。
- 问：这套规则能挡住所有密钥吗？答：**不能。** 它是启发式的。自定义格式、又没进
  配置的密钥会漏。这是必须主动说明的边界，不能说成"已解决密钥泄露"。

**简历候选表述**：证据到「统一规则库 + 三个脱敏接口 + 四处接入点 + 19 项测试」。
可表述为「实现敏感信息脱敏并接入事件、审计与日志」，**不要**说成
"实现了完善的密钥防护"——Artifact 与 Diff 还没接，也没有熵检测。

**不能声称的能力或结果**：

- 不能说「所有出口都脱敏了」——Artifact 和 Diff（T18）还没有。
- 不能说「能识别任意密钥」——纯启发式，自定义格式会漏。
- 不能说「性能没有影响」——没有任何测量。
- 不能说「第三方日志 handler 也安全」——过滤器只覆盖自己装的 logger。

## 后续

- **还清的欠账**：T7 里"工具参数值不进载荷"的临时措施已经撤销，值现在进载荷，
  脱敏由写入路径保证（超过 4096 字符的参数仍只留键名，正文走 Artifact）。
- **交给 T18**：Artifact 与 Diff 的脱敏接入。
- **交给 T23/T25**：部署时的日志配置若引入结构化 handler，要确认它在过滤器之后
  取消息。
- **待决定**：是否给 memory 模块也接上"已知值"那一层（需要让它们能拿到配置）。
- 用户练习反馈：**待用户自测**。
