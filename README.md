# HuiCode

HuiCode 是一个终端 AI 编程助手。当前阶段已经具备交互式对话、流式输出、工具调用、Agent Loop、Plan Mode、Rich Markdown 渲染、结构化系统提示，以及五层权限系统。

## 能力概览

- 交互式命令行对话
- SSE 流式输出
- 多轮上下文记忆
- OpenAI 兼容协议
- Anthropic Claude 兼容协议
- Claude extended thinking 配置与 thinking 回传
- 统一 Provider 抽象
- 统一工具系统
- 多轮 ReAct Agent Loop
- `/plan` 只读规划模式
- `/do` 基于最近计划执行
- Rich Markdown 输出渲染
- prompt_toolkit 交互输入增强
- 结构化系统提示与缓存 usage 可观测
- 五层权限系统

## 工具系统

模型可以请求 HuiCode 执行六个核心工具：

- `Read`：读取 workspace 内文本文件
- `Write`：写入 workspace 内文本文件
- `Edit`：按原文唯一匹配替换文本
- `Bash`：在 workspace 内执行命令并返回退出码、标准输出和标准错误
- `Find`：按模式查找文件
- `Search`：搜索代码内容

工具调用会在 TUI 中显示为 Claude Code 风格工具行：

```text
● Read(huicode/cli.py)
  ⎿  ok, 83 lines, 2870 chars
```

当模型一次返回多个工具调用时，读类工具会优先并发执行，副作用工具会串行执行。工具结果会回灌到对话历史里，模型可据此继续下一轮。

## 权限系统

HuiCode 在工具执行前会经过五层防御：

1. 危险命令黑名单：例如递归强删、`git reset --hard`、`git clean -fdx`、磁盘格式化、大范围权限破坏等会被硬拦截。
2. 路径沙箱：文件路径会先解析绝对路径、`..` 和符号链接，再判断是否仍在 workspace 内。
3. 会话级规则：用户在当前会话中选择 `session` 后生成的临时规则，优先级最高。
4. 持久规则：本地级高于项目级，项目级高于用户级。
5. 权限模式和人在回路：规则未命中时，根据模式决定拒绝、确认或放行。

权限模式：

- `strict`：规则未命中时拒绝。
- `default`：低风险只读调用默认放行，副作用或风险操作需要确认。
- `permissive`：规则未命中时默认放行，但黑名单和路径沙箱仍然硬拦截。

查看或切换当前会话模式：

```text
/permissions
/permissions strict
/permissions default
/permissions permissive
```

确认提示支持四种输入：

- `deny`：拒绝本次工具调用
- `once`：仅本次放行
- `session`：本会话同类调用放行
- `always`：永久写入本地级规则

规则文件路径：

```text
用户级：~/.huicode/permissions.yaml
项目级：<workspace>/.huicode-permissions.yaml
本地级：<workspace>/.huicode-permissions.local.yaml
```

规则格式：

```yaml
mode: default
rules:
  Bash(git *): allow
  Bash(rm -rf *): deny
  Read(src/**/*.py): allow
  Edit(README.md): allow
```

每条规则只能是 `allow` 或 `deny`。规则按精确匹配和 glob 匹配工具参数；`Bash` 匹配命令文本，文件工具匹配路径。

## Agent Loop

普通输入会进入多轮 ReAct 流程：

1. 模型产出文本、thinking 或工具调用。
2. HuiCode 执行工具并显示结果摘要。
3. 工具结果回灌到历史。
4. 模型继续，直到给出最终回答或触发停止条件。

权限拒绝会作为结构化工具结果回灌给模型，Agent Loop 不会因为单次拒绝而崩溃。

停止条件包括：模型不再请求工具、达到默认 8 轮迭代上限、用户中断、连续未知工具达到上限、Provider 或流式解析出错。

## Plan Mode

`/plan` 会让 HuiCode 只暴露读类工具，先分析项目并产出计划；`/do` 再基于最近计划切回全工具执行。

```text
You> /plan 帮我规划如何给 CLI 增加版本号参数
HuiCode> ...

You> /do
HuiCode> ...
```

## 结构化系统提示

HuiCode 会把系统提示按优先级拼装成固定模块：

1. 身份
2. 系统约束
3. 任务模式
4. 动作执行
5. 工具使用
6. 语气风格
7. 文本输出
8. 环境信息

固定模块用于约束模型的长期行为：HuiCode 应像终端里的编程助手一样协助代码任务；优先输出安全、正确、可维护的代码；不要编造工具结果；编辑前先读文件；有专用工具时不要用 `Bash` 代替；高风险或破坏性操作需要先获得用户确认；回复默认使用中文、简洁、无 emoji。

可选模块预留为自定义指令、已激活 Skill 和长期记忆。稳定模块会固定排在请求前部，便于供应商侧缓存；动态环境和模式指令会按轮次单独注入，不污染用户消息。

运行时补充信息使用特殊标签：

```xml
<huicode_context type="environment" scope="turn">...</huicode_context>
<huicode_instruction type="plan_mode" scope="turn">...</huicode_instruction>
<huicode_instruction type="execution_mode" scope="turn">...</huicode_instruction>
```

Plan/Do 指令注入频率为：首轮完整注入，每 4 轮重复关键约束，其余轮次注入精简提醒。

这些提示词只约束模型行为，不代表实现了新的底层能力。当前 HuiCode 还没有子 Agent、`TaskCreate`、真实 MCP 接入或 `ToolSearch` 工具；模型只能使用工具列表中真实暴露的能力。

## 缓存 Usage

开启 `/verbose` 后，TUI 会显示 token usage。HuiCode 会归一化常见缓存字段：

- Anthropic/DeepSeek Anthropic 兼容：`cache_creation_input_tokens`、`cache_read_input_tokens`
- OpenAI 兼容：`prompt_tokens_details.cached_tokens`

示例：

```text
tokens: input_tokens=1200, output_tokens=200, cache_creation_input_tokens=800, cache_read_input_tokens=400
```

当前实现会优先保持协议兼容，不强制向 DeepSeek Anthropic 兼容接口加入可能不支持的 `cache_control` 字段。

## 启动

```powershell
python -m huicode --config .\huicode.yaml
```

安装为包后也可以运行：

```powershell
huicode --config .\huicode.yaml
```

## OpenAI 兼容配置

```yaml
protocol: openai
model: gpt-4.1-mini
base_url: https://api.openai.com/v1
api_key: sk-...
show_usage: false
headers:
  HTTP-Referer: https://example.test
  X-Title: HuiCode
```

## Anthropic Claude 兼容配置

```yaml
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com/v1
api_key: sk-ant-...
max_tokens: 4096
thinking:
  enabled: true
  budget_tokens: 1024
  show: false
```

## 交互命令

- `/exit` 或 `/quit`：退出 HuiCode
- `/clear`：清空本次会话记忆和最近计划
- `/config`：查看当前协议和模型，不显示 API key
- `/plan [任务]`：进入只读计划模式；带任务时立即执行规划
- `/do [任务]`：基于最近计划执行；不带任务时继续最近计划
- `/verbose`：切换 token 用量显示，默认关闭
- `/last [数量]`：展开最近工具结果，默认 1 条，最大 5 条
- `/permissions [strict|default|permissive]`：查看或切换权限模式

## 本阶段暂不包含

- 项目指令文件加载
- 自动记忆
- 真实 MCP 接入
- 自动化评估
- 网络请求限制
- CPU、内存、磁盘、进程数等资源配额
- 完整审计日志
- 操作系统级容器沙箱
- 上下文压缩
- 用户交互式确认之外的权限 UI
- 子 Agent 或 `TaskCreate`
- `ToolSearch`
