# 004 结构化系统提示与缓存策略人工评估场景

本文件用于真实 API 环境下做定性对比。建议使用同一配置分别记录“本章前”和“本章后”的模型行为。

## 1. 入口文件分析

输入：

```text
当前项目入口文件有哪些？
```

期望工具行为：

- 优先使用 `Find` 查找 `__main__.py`、CLI 相关文件或项目配置。
- 必要时使用 `Read` 读取 `pyproject.toml`、`huicode/__main__.py`、`huicode/cli.py`。
- 不使用 `Bash` 代替专用查找工具。

期望输出倾向：

- 明确列出入口文件和原因。
- 如果信息不足，说明依据来自哪些文件。

观察记录：

```text
待填写
```

## 2. 编辑前读取

输入：

```text
把 README 里的启动命令说明改得更清楚。
```

期望工具行为：

- 先调用 `Read(README.md)`。
- 再调用 `Edit` 或 `Write`。
- `Edit` 失败时根据唯一匹配错误调整参数，不把失败当成功。

期望输出倾向：

- 简短说明改了哪里。
- 不输出工具内部 JSON。

观察记录：

```text
待填写
```

## 3. Plan Mode 只读规划

输入：

```text
/plan 给配置文件增加 provider profile，该怎么做？
```

期望工具行为：

- 只出现 `Read`、`Find`、`Search` 或 `Glob`。
- 不出现 `Write`、`Edit`、`Bash`。

期望输出倾向：

- 输出调查依据和可执行计划。
- 不实际修改文件。

观察记录：

```text
待填写
```

## 4. Do Mode 根据最近计划执行

输入：

```text
/do
```

前置条件：

- 已完成上一条 `/plan`。

期望工具行为：

- 动态指令进入 execution mode。
- 可使用全量工具，但仍遵守“编辑前先读”和 workspace 边界。

期望输出倾向：

- 按最近计划推进，不机械复述整份计划。

观察记录：

```text
待填写
```

## 5. 工具优先级

输入：

```text
查一下哪里定义了 ToolRegistry。
```

期望工具行为：

- 优先使用 `Search` 或 `Find`。
- 不直接使用 `Bash(dir/findstr/grep)` 做第一选择。

期望输出倾向：

- 给出文件位置和职责说明。

观察记录：

```text
待填写
```

## 6. 缓存 Usage 可观测

输入：

```text
/verbose
当前项目有哪些主要模块？
```

期望工具行为：

- 正常完成问答。

期望输出倾向：

- TUI 显示 `tokens:` 行。
- 如果供应商返回缓存字段，应显示 `cache_creation_input_tokens`、`cache_read_input_tokens` 或 `cached_tokens`。

观察记录：

```text
待填写
```

## 7. 输出风格稳定性

输入：

```text
总结一下这个项目目前能做什么，不要太长。
```

期望工具行为：

- 可按需读取 README 或配置文件。

期望输出倾向：

- 中文、简洁、先给结论。
- 不泄露 `<huicode_context>` 或 `<huicode_instruction>` 标签。

观察记录：

```text
待填写
```
