# HuiCode Slash Command Plan

## 架构概览

本章新增 `huicode.commands` 包，把命令元数据、注册、解析、分发、补全和内置处理器从 `cli.py` 中拆出。CLI 只负责创建运行时适配器、读取输入并把输入交给统一路由器；命令注册中心成为帮助、补全和分发的唯一真相源。

整体分为六层：

1. **定义层**：声明命令类型、命令元数据、别名元数据、解析结果和处理结果。
2. **注册层**：登记命令，规范化名称，启动时检查名称和别名冲突。
3. **解析层**：识别斜杠输入，分离命令名和参数，保留参数原始大小写。
4. **分发层**：查找命令、处理未知命令、调用处理器，并统一兜住命令异常。
5. **运行时接口层**：用协议接口向命令暴露显示消息、发送用户消息、切换模式、查询 Token 和刷新状态等能力。
6. **交互适配层**：把注册中心接入 prompt_toolkit 补全和状态栏，把运行时接口接到现有 Agent、Context、Memory、Permission 和 MCP 实例。

数据流：

```text
用户回车
  -> InputRouter
     -> 空输入：忽略
     -> 普通文本：CommandUI.send_user_message(text)
     -> 斜杠输入：CommandParser -> CommandDispatcher
        -> 未知命令：本地错误 + /help
        -> LOCAL/STATE：处理器调用本地服务和界面接口
        -> PROMPT：处理器展开固定提示词 -> send_user_message(expanded_prompt)
```

## 模块设计

### `huicode/commands/types.py`

定义核心数据结构：

```python
class CommandType(str, Enum):
    LOCAL = "local"
    STATE = "state"
    PROMPT = "prompt"


@dataclass(frozen=True)
class CommandAlias:
    name: str
    hidden: bool = False


@dataclass(frozen=True)
class CommandSpec:
    name: str
    aliases: tuple[CommandAlias, ...]
    description: str
    usage: str
    command_type: CommandType
    handler: CommandHandler
    argument_hint: str = ""
    hidden: bool = False


@dataclass(frozen=True)
class ParsedCommand:
    raw: str
    name: str
    arguments: str


@dataclass(frozen=True)
class CommandResult:
    ok: bool = True
    exit_requested: bool = False
    message: str = ""
```

约定：

- `CommandSpec.name` 和 alias 内部不带 `/`，展示时统一补上。
- 名称只允许 ASCII 字母、数字、`-` 和 `_`，并在注册时转小写。
- 参数字符串不做全局小写转换；具体处理器只规范化自己的关键字参数。
- `CommandResult.message` 由分发器通过 UI 展示，处理器也可以直接调用 UI 完成多段输出。

### `huicode/commands/ui.py`

定义命令与界面、运行时服务之间的协议：

```python
class CommandUI(Protocol):
    def show_message(self, message: str, *, error: bool = False) -> None: ...
    def send_user_message(self, message: str) -> None: ...
    def get_mode(self) -> Literal["default", "plan"]: ...
    def set_mode(self, mode: Literal["default", "plan"]) -> None: ...
    def get_token_status(self) -> dict[str, object]: ...
    def refresh_status(self) -> None: ...


class CommandServices(Protocol):
    def compact(self) -> str: ...
    def clear(self) -> str: ...
    def session(self, arguments: str) -> str: ...
    def memory(self, arguments: str) -> str: ...
    def permission(self, arguments: str) -> str: ...
    def status(self) -> str: ...
    def legacy_last(self, arguments: str) -> str: ...
    def toggle_verbose(self) -> str: ...
    def request_exit(self) -> None: ...


@dataclass
class CommandContext:
    ui: CommandUI
    services: CommandServices
    registry: CommandRegistry
```

拆成 `CommandUI` 和 `CommandServices`，避免把所有领域操作都伪装成界面能力；内置命令只依赖协议，可用 fake 实现测试。

### `huicode/commands/registry.py`

`CommandRegistry` 维护：

- 按规范化名称保存主命令。
- 按规范化 key 保存名称和别名到命令的映射。
- 保留注册顺序，保证 `/help` 和补全稳定。
- 提供 `register()`、`resolve()`、`visible_commands()`、`completion_entries()`。

冲突检查：

- 主名称与已有主名称冲突。
- 主名称与已有别名冲突。
- 新别名与已有主名称冲突。
- 新别名与已有别名冲突。
- 同一命令内部出现重复别名或别名等于主名称。
- 大小写不同但规范化后相同同样视为冲突。

冲突抛出 `CommandRegistrationError`，消息包含冲突 key、已有命令和新命令。`create_builtin_registry()` 在 `_run_chat()` 初始化外部资源前完成；CLI 捕获后打印“命令注册错误”并返回退出码 2。

### `huicode/commands/parser.py`

接口：

```python
class CommandParser:
    def parse(self, text: str) -> ParsedCommand | None: ...
```

规则：

- `None` 不作为输入类型；空字符串和全空白返回 `None`。
- 去掉首尾空白后，如果首字符不是 `/`，返回 `None`，交给普通消息路径。
- 第一个空白前是命令 token；移除开头 `/`，转小写。
- 剩余文本仅去掉命令与参数之间的空白和尾部空白，内部内容和大小写保留。
- 单独 `/` 解析为未知空名称，由分发器给 `/help` 引导。

### `huicode/commands/dispatcher.py`

`CommandDispatcher.dispatch(parsed, context)`：

- 从 registry 解析主名称或别名。
- 未命中时显示 `未知命令 /xxx。输入 /help 查看可用命令。`。
- 调用 handler，并展示 `CommandResult.message`。
- 参数错误由处理器返回稳定用法；不抛到 CLI 主循环。
- 未预期异常转换为 `命令 /xxx 执行失败: ...`，保持下一轮输入可用。
- `exit_requested` 交给主循环统一关闭资源，处理器不直接调用 `sys.exit()`。

`InputRouter.route(text, context)`：

- 空输入返回 `IGNORED`。
- parser 返回命令时调用 dispatcher，返回 `COMMAND`。
- 普通输入调用 `ui.send_user_message(text)`，返回 `MESSAGE`。
- 只有 `PROMPT` 命令处理器会在命令路径中调用 `send_user_message()`。

### `huicode/commands/completion.py`

实现 `SlashCommandCompleter`，适配 prompt_toolkit `Completer`：

- 候选来自 `registry.completion_entries()`，不维护静态 `COMMANDS`。
- 只在光标位于第一个命令 token 时补全；进入参数区后不提供动态参数候选。
- 主命令和非隐藏 alias 可作为候选，隐藏命令和隐藏 alias 跳过。
- 匹配大小写不敏感，插入文本统一使用小写规范形式。
- completion 的 `display_meta` 显示简短描述；有参数提示时显示 argument hint。
- prompt_toolkit 默认 Tab 行为负责单匹配插入和多匹配菜单；测试直接验证候选集合与 start position。

### `huicode/commands/builtin.py`

提供 `create_builtin_registry()` 和处理器。可见命令按固定顺序注册：

| 命令 | 类型 | 参数 | 行为 |
| --- | --- | --- | --- |
| `/help` | LOCAL | `[command]` | 列出可见命令或显示单命令详情 |
| `/compact` | LOCAL | 无 | 调用现有手动上下文压缩 |
| `/clear` | STATE | 无 | 清空工作上下文并开启新 session |
| `/plan` | STATE | 无 | 切换到 `[PLAN]`，不调用模型 |
| `/do` | STATE | 无 | 切换到 `[DEFAULT]`，不执行计划 |
| `/session` | LOCAL | `[resume <id>\|clean]` | 默认列表，支持恢复和清理 |
| `/memory` | LOCAL | `[update\|rebuild]` | 默认状态，支持更新和重建 |
| `/permission` | STATE | `[strict\|default\|permissive]` | 默认状态，支持模式切换 |
| `/status` | LOCAL | 无 | 聚合模式、Token 和运行时状态 |
| `/review` | PROMPT | `[focus]` | 展开固定代码审查提示并发送 Agent |

处理器共用参数验证帮助函数，所有不接受参数的命令在收到参数时返回用法，不默默忽略。

`/review` 固定提示词：

```text
请以代码审查模式检查当前项目或当前改动。优先发现可复现的缺陷、行为回归、协议或安全风险，以及缺失的关键测试。先调查相关代码和改动，再按严重程度给出带文件定位的发现；如果没有发现问题，明确说明并指出剩余测试风险。
```

存在 focus 时追加：

```text
本次额外审查重点：<原始参数>
```

提示词通过 `CommandUI.send_user_message()` 进入当前模式。`[PLAN]` 下仍保持只读工具限制；`[DEFAULT]` 下使用默认工具集，但审查提示明确要求不主动修改代码。

### 隐藏兼容命令

隐藏命令同样注册到 registry，但 `hidden=True`：

- `/sessions [clean]`：适配为 `/session` 或 `/session clean`。
- `/resume [session-id]`：无参数时展示 session 列表，有 ID 时适配为 `/session resume <id>`。
- `/permissions`、`/perm`：委托 `/permission`。
- `/config`：委托 `/status`。
- `/context`：保留现有上下文详细摘要，通过 services 输出。
- `/verbose`：保留现有 usage 显示开关。
- `/last [count]`：保留最近工具结果展开。
- `/exit`、`/quit`：返回退出请求。

隐藏命令不出现在帮助和补全中，但仍经过统一解析、注册和分发，不允许回到 `cli.py` 条件分支。

## CLI 运行时适配

### `CLICommandRuntime`

位置建议：`huicode/commands/runtime.py`。

该适配器持有当前会话需要的对象：

- `Provider`
- 工具注册中心和 `ToolContext`
- `AgentState`
- `LLMConfig`
- `ContextManager`
- `MemoryManager | None`
- `MCPManager | None`
- `PermissionContext`
- 当前 `mode`
- `show_usage`
- prompt_toolkit session 的弱引用或刷新回调

职责：

- 实现 `CommandUI` 和 `CommandServices`。
- `send_user_message()` 调用现有 `_run_request()`，模式映射为 `default -> chat`、`plan -> plan`。
- `set_mode()` 修改运行时状态并调用 `refresh_status()`。
- `/clear` 复用现有 reset、MemoryManager 新 session 和模式复位逻辑。
- `/compact`、session、memory、permission、status 复用现有 manager API 和格式化函数。
- `request_exit()` 只设置退出标记；主循环在本轮 dispatch 后统一关闭资源。

避免让 `builtin.py` 直接导入 `cli.py`，消除循环依赖。

### 主循环改造

`_run_chat()` 调整顺序：

1. 创建命令 registry，冲突时立即返回 2。
2. 初始化工具、MCP、权限、上下文和记忆。
3. 创建 `CLICommandRuntime`、dispatcher、router。
4. 用 registry 创建 prompt_toolkit completer 和底部状态栏。
5. 每轮读取原始输入，不在主循环提前 `.lower()`。
6. 调用 `router.route()`。
7. 如果 runtime 收到退出请求，统一关闭 MCP 和 MemoryManager 后返回。

`cli.py` 中原有命令 `if` 分支、静态 `COMMANDS`、`current_mode` 和直接命令格式化调用全部移除或迁入 runtime。

## 状态栏设计

交互终端使用 prompt_toolkit `bottom_toolbar`：

```text
[DEFAULT]  tokens: 1842/128000  permission: default  memory: ready
```

Plan Mode：

```text
[PLAN]  tokens: 1842/128000  permission: default  memory: ready
```

规则：

- 模式标记必须位于最前，使用 `[DEFAULT]` 或 `[PLAN]`。
- Token 显示最近输入 token，未知时显示 `tokens: -/window`。
- memory 根据启用、pending 或 error 显示 `off/ready/updating/error`。
- `refresh_status()` 调用 prompt_toolkit application invalidate；无真实 application 时安全无操作。
- 非 TTY 回退 `input()` 时，输入提示改为 `[DEFAULT] You>` 或 `[PLAN] You>`，保证测试和管道环境也能观察模式。

## `/status` 输出设计

采用多行、可扫描的稳定输出：

```text
mode: [DEFAULT]
provider: anthropic / model-name
context: last=1842 window=128000 summaries=1 fuse=false
permission: default rules=3
mcp: servers=1/1 tools=2 errors=0
memory: enabled=true session=... notes=4 pending=0 error=none
```

不输出 `api_key`、headers 值、环境变量值、MCP header 值或笔记正文。

## 帮助输出设计

`/help` 按三种类型分组，并只显示可见命令：

```text
本地命令
  /help [command]       查看命令帮助
  ...

状态命令
  /plan                 进入计划模式
  ...

提示词命令
  /review [focus]       让 Agent 审查当前改动
```

`/help permission` 展示：

```text
/permission [strict|default|permissive]
切换或查看权限模式。
类型: 状态
示例: /permission strict
```

隐藏命令和隐藏 alias 不显示；显式 `/help resume` 返回未知命令帮助并提示使用 `/session`，避免继续宣传旧入口。

## 测试计划

### 新增测试文件

- `tests/test_commands_registry.py`
  - 正常注册和按名称/alias 查找。
  - 名称、别名、大小写和内部重复冲突。
  - visible/help/completion 过滤隐藏项。

- `tests/test_commands_parser.py`
  - 空输入、普通输入、裸 `/`、大小写不敏感名称。
  - 参数原文大小写和内部空格保留。

- `tests/test_commands_dispatcher.py`
  - 本地命令、状态命令、提示词命令分流。
  - 未知命令不调用 send/Provider。
  - 参数错误和处理器异常保持循环可用。

- `tests/test_commands_completion.py`
  - 单匹配、多匹配、大小写匹配。
  - 隐藏命令/alias 不出现。
  - 参数区不做动态补全。

- `tests/test_commands_builtin.py`
  - 十个命令元数据完整且类型正确。
  - help 分组和详情。
  - plan/do 模式切换与 refresh。
  - session/memory/permission/status 参数矩阵。
  - review 固定提示词、focus 追加和 send_user_message。
  - exit/quit 与隐藏兼容入口。

- `tests/test_cli_commands.py`
  - 真正 `_run_chat()` 输入分流。
  - 本地命令 Provider 零调用。
  - 普通消息和 `/review` 进入相同 Agent 流程。
  - `[DEFAULT]/[PLAN]` 状态展示。
  - 资源关闭和退出码。

### 更新现有测试

- `tests/test_cli.py`：迁移 config、verbose、last、permission 旧命令断言。
- `tests/test_cli_context.py`：`/compact` 和隐藏 `/context` 兼容。
- `tests/test_cli_memory.py`：迁移 `/session`、`/memory` 和旧 resume 兼容。
- `tests/test_cli_plan_mode.py`：改为 `/plan` 与 `/do` 仅切模式，删除自动执行最近计划断言。
- `tests/test_tui.py`：补充状态栏文本或模式标签格式测试。

### 回归验证

- `python -m unittest discover -v`
- `python -m compileall -q huicode tests`
- `git diff --check`
- 当前环境有 tmux 时执行真实交互：`/help`、`/plan`、普通请求、`/do`、`/session`、`/review`、未知命令、Tab 单匹配和多匹配。

## 实施顺序

1. 建立 types、UI/Services 协议和 registry，先锁定元数据与冲突规则。
2. 实现 parser、dispatcher、router，用 fake UI 验证 Provider 零调用边界。
3. 实现 builtin registry 和十个可见命令，再实现隐藏兼容命令。
4. 实现 CLICommandRuntime，把现有命令逻辑迁移为 services 方法。
5. 改造 `_run_chat()`，删除静态 `COMMANDS` 和长条件分支。
6. 接入 prompt_toolkit completer、底部状态栏和非 TTY 模式提示。
7. 更新现有测试与 README，执行完整回归和端到端验收。

## 风险与控制

- **命令重构导致旧行为遗漏**：建立旧命令到新 handler 的映射表，每个隐藏兼容入口单独测试。
- **`/do` 行为改变导致旧测试失败**：按新需求更新测试，明确不再自动发送最近计划。
- **prompt_toolkit 状态刷新依赖 application 生命周期**：用回调注入和安全空操作，测试不创建真实终端。
- **runtime 变成新的巨型对象**：界面协议与服务协议分离，具体 manager 调用集中在适配器，不进入 registry/parser。
- **本地命令意外调用 Provider**：fake Provider 计数断言覆盖每个 LOCAL/STATE 命令和参数错误路径。
- **隐藏兼容命令重新污染帮助或补全**：registry 提供统一 visible 过滤，不让 help/completer 自己判断。
- **状态输出泄密**：只拼接白名单字段，沿用现有 memory/config 脱敏测试构造 secret 验证。

## 完成定义

- 注册中心是命令元数据、帮助、补全和分发的唯一来源。
- 十个可见命令和全部隐藏兼容入口通过统一 dispatcher 执行。
- LOCAL/STATE 命令及其错误路径 Provider 调用次数为零。
- `/review` 通过统一 Agent 入口发送固定提示词。
- `[DEFAULT]/[PLAN]` 在交互状态栏和非 TTY 输入提示中正确联动。
- 旧 `cli.py` 命令条件分支和静态 `COMMANDS` 被删除。
- 全量测试、编译检查、diff 检查和可用环境下的 tmux 验收通过。
- README、checklist 和 acceptance report 与实现一致。
