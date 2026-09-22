# T1：服务端配置与依赖边界

日期：2026-09-19；2026-09-22 补充验证。状态：配置实现、依赖安装、旧配置回归及 API 基础启动已验证。AI 辅助实现，用户理解状态待自测。下文保留首次验证的环境问题，最终结果见本段及 T2 记录：配置/API 合计 31 项、CLI 回归 13 项通过，pip check 通过。

## 场景和代码

Web 服务需要数据库、队列地址和认证密钥。错误配置应在启动期间被识别，避免等用户请求到来才失败。配置加载入口是 [load_server_settings](../../huicode/server/config.py)，测试见 [test_config.py](../../tests/server/test_config.py)，环境变量清单见 [.env.example](../../.env.example)。

数据流为：进程环境或显式测试映射 → 字段及关联约束校验 → 不可变 ServerSettings → 后续应用工厂消费。当前没有连接数据库，也没有启动 API。

## 原理与取舍

- 可选依赖：Web 库放在 `server` extra，后续通过 `pip install -e '.[server,server-test]'` 安装。CLI 默认依赖不变，避免给终端用户增加不使用的数据库和 Web 包。版本范围已声明，但未做依赖解析和锁定，不能声称这些组合已集成验证。
- 配置注入：函数接收 Mapping，测试无需修改全局环境。模块导入不读取环境、不建目录、不连接服务，减少测试相互干扰。使用标准库 dataclass 保持当前边界轻量；如果配置层级显著增加，可考虑独立配置库。
- 启动前校验：所有环境显式提供数据库、Redis、密钥和项目根目录。时限要求 Shell ≤ Tool ≤ Run。这里定义的是预算配置，真正执行限制要在后续工具和 Runtime 中接入。
- 密钥保护：敏感字段设置 repr=False；验证错误只报字段名。它不意味着对象无法被序列化泄露：仍不能随意调用 asdict 后写日志。长度和字符多样性检查也不能证明随机性，密钥应由 secrets 生成。
- CORS：默认不开放跨域；配置时只接受精确 Origin，生产跨域来源要求 HTTPS。CORS 是浏览器跨域控制，不代替认证与资源授权。
- 项目目录：配置阶段只检查目录存在、绝对路径和非磁盘根。它不等于工具路径沙箱，更不能隔离 Shell 或 MCP；后续仍需执行时检查及明确隔离能力。

## 真实问题及排查

1. 默认 python.exe 指向 WindowsApps，启动时报登录会话不可用。改用已定位的桌面运行时 Python 3.12 执行测试。此操作只解决解释器启动，不代表项目依赖已齐全。
2. 首次 9 项测试有 1 项失败：`https://*.example.com` 被当成有效来源。原因是仅比较 hostname 是否等于 `*`。修改为拒绝 hostname 内含 `*` 后，同一用例通过。
3. 合并运行旧配置测试时，导入现有 huicode.config 因缺少 PyYAML 失败。没有据此判断旧代码回归，也没有把旧测试记为通过。

## 验证证据

运行环境：Windows PowerShell，桌面附带 Python 3.12；工作目录为仓库根目录。

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.server.test_config
```

实际结果：9 tests，OK。覆盖必填项、运行模式、密钥表示、URL 错误堆栈不含输入值、目录边界、预算数值与顺序、CORS、日志级别。`git diff --check` 无空白错误；存在 CRLF 转换提示。

旧配置测试：`-m unittest tests.server.test_config tests.test_config` 在导入时因缺少 yaml 失败，尚未完成回归。尚未进行 API 启动、实际数据库连接、依赖兼容性和 CLI 交互测试。

## 自己动手

这次先做一个约 10 分钟的小实验：亲眼看到“正确配置可以加载，错误配置被拒绝”。不需要启动 Web、安装 PostgreSQL 或 Redis，也不需要修改项目文件。命令中的数据库地址只是用于格式校验，没有真实连接。

### 第一步：打开 PowerShell 并进入项目

在 Windows 开始菜单搜索 PowerShell 并打开，把下面两行复制进去执行：

```powershell
Set-Location 'C:\Users\Administrator\Documents\Huicode'
$studioPython = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
```

第一行切换工作目录；第二行保存这次实验使用的 Python 路径。下面命令要在同一个终端里运行。

```powershell
Test-Path $studioPython
& $studioPython --version
```

预期第一条显示 True，第二条显示 Python 版本。若显示 False，说明这台机器的解释器路径已变化，先定位有效 Python，不能继续照抄后面的命令。`&` 是 PowerShell 调用路径所指程序的运算符。

### 第二步：先确认现有测试可以运行

```powershell
& $studioPython -m unittest tests.server.test_config -v
```

预期最后显示 `Ran 9 tests` 和 `OK`。`-m unittest` 表示用 Python 的测试运行器运行模块；`-v` 会显示每个测试名称。即使测试验证的是“配置报错”，测试本身也可以成功：它检查的就是错误配置是否按预期被拒绝。

如果出现 `No module named tests.server`，先重新执行第一步的 Set-Location。若出现 `No module named yaml`，检查是否误运行了旧的 `tests.test_config`；本篇专用测试不需要 PyYAML。

### 第三步：手动观察一次成功和一次失败

完整复制下面一块到同一个 PowerShell 终端。开头的 `@'` 和结尾的 `'@` 必须各自放在单独一行。它将 Python 代码保存在终端变量里，没有写入项目文件。

```powershell
$configExercise = @'
import secrets
from pathlib import Path
from huicode.server.config import load_server_settings, ServerConfigError

# 只在这个 Python 进程中使用的练习配置。
env = {
    "HUICODE_DATABASE_URL": "postgresql+asyncpg://demo:demo@localhost/studio",
    "HUICODE_REDIS_URL": "redis://localhost:6379/0",
    "HUICODE_JWT_SECRET": secrets.token_urlsafe(32),
    "HUICODE_PROJECT_ROOT": str(Path.cwd()),
}

settings = load_server_settings(env)
print("1. Valid configuration loaded")
print("Run seconds:", settings.limits.max_run_seconds)
print("Tool seconds:", settings.limits.max_tool_seconds)
print("Shell seconds:", settings.limits.max_shell_seconds)

# 保留其他配置，只把总任务时限改为 1 秒。
env["HUICODE_MAX_RUN_SECONDS"] = "1"
try:
    load_server_settings(env)
except ServerConfigError as error:
    print("2. Invalid configuration rejected:", error)
else:
    raise AssertionError("Expected invalid configuration to be rejected")

# 改回合理时限，验证能够恢复加载。
env["HUICODE_MAX_RUN_SECONDS"] = "1800"
load_server_settings(env)
print("3. Configuration restored")
'@
& $studioPython -X utf8 -c $configExercise
```

预期输出依次包括：

```text
1. Valid configuration loaded
Run seconds: 1800
Tool seconds: 120
Shell seconds: 60
2. Invalid configuration rejected: ...时限应满足 Shell ≤ Tool ≤ Run
3. Configuration restored
```

发生了什么：默认允许整个任务运行 1800 秒、单个工具 120 秒、Shell 60 秒。如果总任务只允许 1 秒，却配置工具可以运行 120 秒，这组预算不满足我们制定的包含关系，因此加载器提前拒绝。错误来自配置检查；本次没有真的运行一个 120 秒的工具。

这里的 `env` 是一个普通 Python 字典，调用时交给加载器。它不会修改 Windows 环境变量或真实 `.env`，所以运行结束不需要恢复文件。

### 第四步：只改一个值，预测再验证

重新复制第三步代码，把 `env["HUICODE_MAX_RUN_SECONDS"] = "1"` 中的 `"1"` 改成 `"120"`。先想一下它是否应该通过，再运行。

预期出现 `AssertionError: Expected invalid configuration to be rejected`。原因是 `60 ≤ 120 ≤ 120` 合法，加载器没有报错，但练习代码仍然断言“这里必须失败”。这是练习预期与输入不匹配，并不是配置实现坏了。

改回 `"1"` 后重跑，应恢复第三步的输出。这个实验帮助你区分“程序故障”和“测试期望不正确”。

### 第五步：回到源码核对

打开本篇前面链接的 `huicode/server/config.py`，用编辑器查找：

1. `class RuntimeLimits`：找到 1800、120、60 的默认值。
2. `def _positive_int`：看环境变量字符串如何转换为正整数，以及为什么 0 被拒绝。
3. `limits.max_shell_seconds <=`：找到刚才触发的关联校验。
4. `environ is None`：确认传入字典时不会读取真实进程环境。

能把实验输出对应到这四处代码，就完成了本次练习。不要求现在新增配置字段。

后续进阶练习再考虑增加预算字段；届时要同时补默认值、环境变量、测试和说明，并明确运行时是否真正执行了该限制。

自测与核对：

1. 为什么 repr=False 不能保证密钥不泄露？它只控制对象表示，序列化和直接访问仍能读取字段。
2. 为什么 CORS 不能保护其他工作区数据？非浏览器客户端不依赖 CORS，后端仍需逐资源授权。
3. 为什么测试可以不启动 PostgreSQL？本次测试配置解析；真实连接和迁移属于集成测试，二者不能互相替代。

## 面试表达与限制

可讲述：在服务端入口建立显式配置边界，用可注入映射隔离测试；校验环境变量、预算关联约束和 CORS 来源，避免错误消息包含敏感输入；通过失败用例发现并修复子域通配符检查遗漏。

当前不形成独立简历成果条目。不能声称完成认证、运行资源限制、生产沙箱或全量回归；这些都尚未实现或验证。
