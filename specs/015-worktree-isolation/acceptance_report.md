# Worktree 隔离验收报告

## 结论

Worktree 隔离章节通过验收。`spec.md` 中 AC1-AC11 均有实现和自动化证据，`checklist.md` 的 C1-C50 已完成。定义式子 Agent 可通过 `isolation: worktree` 在独立 Git Worktree 中运行；Fork 与未声明隔离的定义式角色保持共享工作区行为。

## 验收环境

- 操作系统：Windows
- 项目目录：`C:\Users\Administrator\Documents\Huicode`
- 测试解释器：Codex bundled Python 3.12
- 测试依赖：安装到 Git 已忽略的 `.huicode/test-deps`
- Git：本机 Git，测试使用临时仓库与本地 bare 远端
- tmux：Windows 环境不可用，使用真实临时 Git 仓库、Fake Provider 和完整 Runner 代替交互式 tmux 验收

## 自动化结果

### Worktree 专项

覆盖以下模块：

- 安全名称、嵌套路径和逃逸拒绝
- 管理清单原子写入、字段匹配和零 Git 快速恢复
- Git Worktree 创建、dirty、无上游提交、有上游 ahead/push 和删除
- 配置复制、忽略文件恢复、目录链接、Hooks 与专属 exclude
- 初始化失败回滚、成功清理、dirty 保留和失败终态持久保护
- 过期清理、仓库过滤、链接逃逸拒绝和后台线程关闭
- 绝对路径键控的项目指令与记忆上下文
- 定义式子 Agent 的真实 Worktree 工具执行与结果回流

结果：全部通过。

### 全量回归

```text
Ran 378 tests in 19.690s
OK
```

覆盖聊天、Provider、工具、权限、Hook、MCP、上下文、记忆、Slash Command、Skill、子 Agent 和本章 Worktree 功能。

### 静态检查

- `python -m compileall -q huicode tests`：通过。
- `git diff --check`：通过，仅显示仓库既有的 LF/CRLF 转换提示。
- `git worktree list --porcelain`：验收后只剩主工作区，没有测试 Worktree 遗留。

## 端到端场景

### E2E-1 隔离写入并保留成果

1. 创建真实临时 Git 仓库并提交基线文件。
2. 加载声明 `isolation: worktree`、允许 `Write` 的定义式角色。
3. Fake Provider 发出 `Write(result.txt, "isolated")` 工具调用。
4. Runner 创建独立 Worktree 和分支，并把 `ToolContext.workspace` 绑定到隔离目录。
5. 工具在隔离目录写入文件，主工作区没有出现 `result.txt`。
6. 任务正常回复后检测到未提交修改，结果返回 `retained`、独立路径、分支和保留原因。

结果：通过。对应 AC1、AC6、AC7、C42。

### E2E-2 干净任务自动清理

真实临时仓库中创建隔离 Worktree，不产生修改后正常结束。Manager 检查工作树干净且没有基线后的提交，删除 Worktree 注册、目录和任务分支。

结果：通过。对应 AC7、C29、C43。

### E2E-3 未推送提交保护

临时 bare 仓库作为本地远端：任务分支首次 push 后判定无未推送提交；新增本地提交后判定 ahead 并拒绝删除；再次 push 后恢复为可安全删除。

结果：通过。对应 AC8、C31、C32。

### E2E-4 可信快速恢复

预先创建匹配清单并注入任意属性访问都会失败的 Fake Git Backend。Manager 成功恢复句柄，证明已有目录路径没有调用 Git；篡改字段、缺失清单和错误版本均被拒绝。

结果：通过。对应 AC4、C9-C11。

## AC 对照

- AC1：独立 HEAD 基线、唯一目录/分支、主目录不受写入影响，通过。
- AC2：shared 默认、Fork 共享、非法隔离值加载失败，通过。
- AC3：名称、长度、路径段、盘符和边界前置校验，通过。
- AC4：完全匹配才恢复，恢复零 Git 调用，通过。
- AC5：复制、恢复、链接、Hooks、专属 exclude 和失败回滚，通过。
- AC6：显式 cwd、独立权限/缓存/上下文和 Worktree Prompt，通过。
- AC7：干净清理，dirty/失败/取消保留，结果元数据回流，通过。
- AC8：未提交、无上游提交、上游 ahead 和身份篡改保护，通过。
- AC9：到期、三层过滤、终态保护、链接逃逸和单项失败隔离，通过。
- AC10：配置与 Git/路径/链接错误均提供明确错误，通过。
- AC11：全量 378 项回归通过。

## 实施返工记录

本章出现三项真实返工，已更新 `docs/mew-spec-pitfalls.md`：

- 快速恢复分支最初仍间接初始化 Git。
- 失败/取消终态最初只存在内存，未来清理可能忘记保护。
- `git check-ignore` 对不存在目录的裸路径不会匹配尾斜杠目录规则。

## 用户文件保护

实施前已有的根目录未跟踪文件保持未跟踪状态，未删除、未覆盖，也不会加入本章暂存清单。本章只提交源码、测试、README、踩坑文档和 `specs/015-worktree-isolation/`。
