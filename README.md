# HuiCode

HuiCode 是一个终端 AI 编程助手。当前阶段已经具备交互式对话、流式输出、工具调用、Agent Loop、Plan Mode、Rich Markdown 渲染，以及结构化系统提示。

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

## Agent Loop

普通输入会进入多轮 ReAct 流程：

1. 模型产出文本、thinking 或工具调用。
2. HuiCode 执行工具并显示结果摘要。
3. 工具结果回灌到历史。
4. 模型继续，直到给出最终回答或触发停止条件。

停止条件包括：模型不再请求工具、达到默认 8 轮迭代上限、用户中断、连续未知工具达到上限、Provider 或流式解析出错。

## Plan Mode

`/plan` 会让 HuiCode 只暴露读类工具，先分析项目并产出计划；`/do` 再基于最近计划切回全工具执行。

```text
You> /plan 帮我规划如何给 CLI 增加版本号参数
HuiCode> ...

You> /do
HuiCode> ...
```

Plan Mode 当前只做工具集合收窄和系统提示约束，不做权限系统、上下文压缩或交互式确认。

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

可选模块预留为自定义指令、已激活 Skill 和长期记忆。稳定模块会固定排在请求前部，便于供应商侧缓存；动态环境和模式指令会按轮次单独注入，不污染用户消息。

运行时补充信息使用特殊标签：

```xml
<huicode_context type="environment" scope="turn">...</huicode_context>
<huicode_instruction type="plan_mode" scope="turn">...</huicode_instruction>
<huicode_instruction type="execution_mode" scope="turn">...</huicode_instruction>
```

Plan/Do 指令注入频率为：首轮完整注入，每 4 轮重复关键约束，其余轮次注入精简提醒。

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

## 本阶段暂不包含

- 项目指令文件加载
- 自动记忆
- 真实 MCP 接入
- 自动化评估
- 权限系统
- 上下文压缩
- 用户交互式确认
