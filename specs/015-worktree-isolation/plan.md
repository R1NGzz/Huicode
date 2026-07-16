# Worktree 隔离技术计划

## 架构概览

本章在现有子 Agent Runner 与工具上下文之间加入独立的 Worktree 生命周期层：

```text
角色目录加载
  -> 解析 isolation
  -> 子 Agent Runner 请求 WorktreeManager.prepare()
  -> 创建或可信恢复 WorktreeHandle
  -> 用 handle.path 构建 ToolContext / ContextManager / 项目上下文
  -> 子 Agent Loop
  -> WorktreeManager.finalize()
  -> 自动删除或保留
  -> 结果携带目录、分支和保留原因回流
```

Worktree 管理层只负责 Git 多工作目录、路径安全、初始化和清理判断，不负责分支合并。所有 Git 命令通过统一执行器以参数数组和显式 `cwd` 运行；Agent 工具继续只依赖 `ToolContext.workspace`，不改变进程全局当前目录。

## 核心数据结构与接口

### 1. 角色隔离声明

扩展 `AgentDefinition`：

```python
AgentIsolation = Literal["shared", "worktree"]

@dataclass(frozen=True)
class AgentDefinition:
    ...
    isolation: AgentIsolation = "shared"
```

- frontmatter 新增可选字段 `isolation`。
- 缺省值为 `shared`。
- 只接受 `shared` 和 `worktree`；非法值在目录加载阶段报告。
- Runner 仅在 `type == "defined"` 且定义值为 `worktree` 时准备隔离目录。

### 2. Worktree 配置

在顶层 `LLMConfig` 增加 `worktrees: WorktreeConfig`：

```python
@dataclass(frozen=True)
class WorktreeConfig:
    root: str = ".huicode/worktrees"
    stale_after_days: int = 7
    cleanup_interval_seconds: int = 3600
    copy_files: tuple[str, ...] = (
        "huicode.yaml",
        ".huicode-permissions.local.yaml",
    )
    symlink_directories: tuple[str, ...] = ()
    restore_ignored: tuple[str, ...] = ()
    hooks_path: str | None = None
```

YAML 示例：

```yaml
worktrees:
  root: .huicode/worktrees
  stale_after_days: 7
  cleanup_interval_seconds: 3600
  copy_files:
    - huicode.yaml
    - .huicode-permissions.local.yaml
  symlink_directories:
    - node_modules
  restore_ignored:
    - .env.local
    - fixtures/**/*.bin
  hooks_path: .githooks
```

配置规则：

- `root` 必须是仓库内的相对目录，并经过解析后边界校验。
- 初始化来源路径均相对主工作区，目标保持相同相对路径。
- 复制与恢复规则允许文件或 glob；目录链接规则只允许单个相对目录，不接受 glob。
- 所有解析结果必须同时位于主工作区或目标 Worktree 对应边界内。
- 清理间隔与过期期限必须为正数。

### 3. Worktree 标识与运行句柄

```python
@dataclass(frozen=True)
class WorktreeIdentity:
    repository_id: str
    task_id: str
    logical_name: str
    base_commit: str
    branch: str
    path: Path

@dataclass(frozen=True)
class WorktreeHandle:
    identity: WorktreeIdentity
    recovered: bool = False

@dataclass(frozen=True)
class WorktreeDisposition:
    state: Literal["removed", "retained", "skipped"]
    reason: str
    dirty: bool = False
    unpushed: bool = False
```

- `repository_id` 由主仓库规范绝对路径和 Git 公共目录标识生成稳定摘要。
- 分支使用固定命名空间加安全逻辑名与任务 ID，避免与用户分支混淆。
- 实际目录位于 `<root>/tasks/<logical-name>/<task-id>`。
- 目录内 `.huicode/worktree.json` 保存版本化管理清单；`.huicode/` 已被仓库忽略，不污染工作树状态。
- 清单使用原子替换写入，包含格式版本、仓库标识、任务标识、路径、分支、基线和创建时间。

### 4. WorktreeManager

```python
class WorktreeManager:
    def prepare(self, task_id: str, logical_name: str) -> WorktreeHandle: ...
    def finalize(self, handle: WorktreeHandle, task_status: str) -> WorktreeDisposition: ...
    def remove(self, handle: WorktreeHandle) -> WorktreeDisposition: ...
    def cleanup_stale(self) -> tuple[WorktreeCleanupRecord, ...]: ...
    def close(self) -> None: ...
```

职责：

- 在任何副作用前验证逻辑名、专用根目录和仓库状态。
- 新建路径走 Git 创建、环境初始化、清单写入的事务流程。
- 已存在路径走纯文件系统可信恢复，不调用 Git；清单任一字段不匹配即拒绝。
- 结束时检测任务状态、脏修改和未推送提交，决定删除或保留。
- 清理时执行根目录、清单、仓库归属三层过滤，再复用正常删除保护。
- 后台清理线程只记录结果和警告，不向 Agent 主流程抛出异常。

### 5. Git 执行与状态模型

`GitWorktreeBackend` 封装所有 Git 子进程：

- 使用 `subprocess.run([...], cwd=..., shell=False)`。
- 命令超时、退出码、标准输出和标准错误统一转换为 `WorktreeError`。
- 创建前读取当前 `HEAD`，执行独立分支的 `git worktree add`。
- Hooks 使用 Git 的 per-worktree 配置能力；必要时启用仓库的 `extensions.worktreeConfig`，再为目标工作目录设置 `core.hooksPath`。
- 工作树状态使用 porcelain 输出判断。
- 有上游时比较本地分支与上游；无上游时比较当前分支与清单中的 `base_commit`。基线后出现提交即视为未推送。
- 删除成功后移除 Worktree 注册和专用任务分支；任何保护条件命中时不执行删除命令。

快速恢复是特例：`prepare()` 发现目标目录存在后直接进入只读清单校验分支，不实例化任何会调用 Git 的恢复探测。测试用禁止调用的 Backend 验证这一约束。

### 6. 环境初始化器

`WorktreeInitializer` 按固定顺序执行：

1. 复制本地配置文件。
2. 恢复配置声明的忽略文件或 glob 结果。
3. 建立大型依赖目录链接。
4. 配置目标 Worktree 的 Git Hooks。
5. 写入管理清单。

具体规则：

- 复制使用元数据友好的文件复制，目标父目录按需创建；不存在的默认可选文件跳过，用户显式配置但不存在的来源报错。
- glob 结果逐项做源边界和目标边界校验，并保持相对目录结构。
- 链接目标必须是主工作区内已存在的目录；目标位置必须不存在。
- Windows 链接创建失败时返回包含平台原因的明确错误，不静默退化成复制。
- 初始化任一步失败时，在子 Agent 尚未执行的前提下回滚刚创建的 Worktree 和分支；回滚失败信息与原错误一并保留。
- 快速恢复不再次执行初始化器，避免覆盖已有内容。

### 7. 工作区上下文隔离

增加 `WorkspaceContextLoader`，统一按规范绝对目录读取：

- 项目指令。
- 项目记忆索引。
- 需要进入 Prompt 的工作区环境说明。

其缓存键使用 `str(workspace.resolve())` 加文件快照；不同 Worktree 永远不会共用同一个键。现有 `FileReadCache` 已以规范绝对文件路径作为键，子 Agent 继续为每个任务创建独立实例。`ContextManager` 继续按子 Agent 工作目录单独创建。

Worktree 子 Agent 不直接继承父任务已经渲染的项目指令，而是从 Worktree 目录重新加载；用户级指令仍按现有优先级参与。Prompt 增加高优先级动态块，包含：

- 当前隔离目录绝对路径。
- 当前独立分支。
- 禁止修改主工作区的提醒。
- 合并由主 Agent 或用户另行处理的说明。

### 8. 子 Agent 集成与结果回流

`IsolatedSubagentRunner` 调整为：

1. 解析定义并决定共享或 Worktree 工作区。
2. Worktree 模式调用 `prepare()`，失败直接返回 `worktree_prepare_failed`。
3. 用实际工作区创建权限上下文、`ToolContext`、`ContextManager` 和工作区 Prompt 数据。
4. 正常运行 Agent Loop。
5. 在 `finally` 中调用 `finalize()`，确保异常和取消也执行保留判定。
6. 把 Worktree 信息写入 `SubagentResult`。

扩展 `SubagentResult`、`SubagentTask` 和 `SubagentTaskView`：

```python
worktree_path: str = ""
worktree_branch: str = ""
worktree_state: str = ""
worktree_reason: str = ""
```

后台通知和结果注入仅暴露必要信息，不泄露配置内容。失败、取消、有修改或未推送提交时结果明确提示目录已保留。

### 9. 后台清理生命周期

- `WorktreeManager` 随 CLI Runtime 创建，并注入子 Agent Runner。
- 启动后执行一次异步过期扫描，随后按配置间隔运行。
- 扫描只枚举专用根目录的管理清单，不跟随目录链接。
- 候选必须依次通过：解析路径仍在根目录内、清单格式和路径匹配、仓库标识匹配。
- 失败或不安全项形成诊断记录，不终止线程和主会话。
- CLI 关闭时停止清理线程；不等待长时间 Git 操作，也不强制删除任何任务目录。

## 模块职责

### 新增模块

- `huicode/worktrees/types.py`：配置外的领域类型、状态与错误。
- `huicode/worktrees/naming.py`：逻辑名称、分支名和路径边界校验。
- `huicode/worktrees/manifest.py`：管理清单的原子读写与可信匹配。
- `huicode/worktrees/git.py`：Git 命令执行、创建、状态、上游与删除。
- `huicode/worktrees/initializer.py`：复制、恢复、链接和 Hooks 初始化。
- `huicode/worktrees/manager.py`：生命周期编排、事务回滚和删除保护。
- `huicode/worktrees/cleanup.py`：后台过期扫描与三层过滤。
- `huicode/workspaces.py`：绝对路径键控的项目指令和记忆上下文加载。

### 修改模块

- `huicode/config.py`：解析并校验 `worktrees` 配置。
- `huicode/subagents/types.py`：角色隔离字段和任务结果 Worktree 元数据。
- `huicode/subagents/parser.py`：解析 `isolation`。
- `huicode/subagents/runner.py`：准备实际工作区并在结束后处理保留策略。
- CLI 组装模块：创建、注入和关闭 `WorktreeManager`。
- `huicode/prompts/modules.py`：渲染隔离目录动态说明。
- `README.md`：补充角色声明、配置示例、保留和合并边界。
- `docs/mew-spec-pitfalls.md`：仅在实现或验收出现真实返工时追加本章踩坑。

### 测试模块

- `tests/test_worktree_naming.py`：名称与路径逃逸测试。
- `tests/test_worktree_manifest.py`：清单、原子写入和纯文件恢复测试。
- `tests/test_worktree_git.py`：临时仓库中的分支、状态和未推送判断。
- `tests/test_worktree_initializer.py`：复制、glob、链接、Hooks 与回滚测试。
- `tests/test_worktree_manager.py`：生命周期、保留和清理过滤测试。
- `tests/test_subagent_worktree.py`：角色解析、Runner 注入和结果回流集成测试。

## 数据流

### 新建隔离任务

```text
Agent(name=role)
  -> SubagentManager 分配 task_id
  -> Runner 读取 role.isolation
  -> 名称/根目录安全校验
  -> 读取主仓库 HEAD
  -> git worktree add + 独立分支
  -> 初始化环境 + 写清单
  -> ToolContext(workspace=worktree_absolute_path)
  -> 子 Agent Loop
  -> 检查结果/dirty/unpushed
  -> 删除或保留
  -> 主 Agent 收到摘要和 Worktree 元数据
```

### 快速恢复

```text
目标目录已存在
  -> 只读 .huicode/worktree.json
  -> 校验格式、仓库、任务、逻辑名、规范路径
  -> 匹配：返回 recovered handle
  -> 不匹配：拒绝
  -> 全程不调用 Git
```

### 过期清理

```text
后台定时器
  -> 枚举专用根目录清单
  -> 根目录边界过滤
  -> 清单可信过滤
  -> 仓库归属过滤
  -> 到期判断
  -> dirty/unpushed 保护
  -> 安全删除或记录跳过原因
```

## 技术决策与理由

### D1 仅定义式子 Agent 支持 Worktree

隔离由角色 frontmatter 声明，配置入口单一且可审计。Fork 保持历史继承和主工作区语义，本章不扩展 Agent 工具参数。

### D2 从当前 HEAD 创建，不复制未提交修改

Git Worktree 以提交为稳定基线。隐式复制主工作区半成品会模糊版本来源，也会让恢复和删除保护难以可靠判断。

### D3 管理清单放在 Worktree 的被忽略目录内

清单随目录存在，支持纯文件系统恢复；同时不会让工作树永久显示为脏。清单只用于身份校验，不代替 Git 状态判断。

### D4 恢复路径严格禁止 Git 调用

遵守快速恢复约束，并避免对可能不是本系统创建的目录执行 Git 探测。可信度由清单中的多字段匹配和路径边界提供。

### D5 Git 命令不用 shell

参数数组避免任务名、路径或模型输入进入 shell 解析层，减少命令注入和平台 quoting 差异。

### D6 初始化失败立即事务回滚

子 Agent 尚未运行时不存在需要保留的成果，回滚可避免遗留半初始化目录。若回滚自身失败，保留目录并明确报告，绝不继续执行任务。

### D7 删除采用默认拒绝

脏修改、未推送提交、失败和取消都可能包含有价值成果。自动清理只处理成功且干净的目录，后台清理同样不能绕过保护。

### D8 缓存使用规范绝对路径键

继续沿用现有 `FileReadCache` 的正确模式，并把项目指令与记忆加载统一到同一规则。无需切换时清缓存，也不会把一个 Worktree 的上下文串给另一个。

## 需求覆盖自检

- F1：角色类型、解析和 Runner 分流。
- F2-F4：名称、Git Backend、清单和 Manager 生命周期。
- F5：Initializer 与事务回滚。
- F6：显式 `ToolContext.workspace`、独立 ContextManager 和绝对路径缓存。
- F7-F8：Runner finalize、结果字段和删除保护。
- F9：Cleanup 后台扫描与三层过滤。
- F10：WorktreeConfig、事件元数据和结构化错误。

所有功能需求均有对应模块、数据流和测试入口；模块依赖方向为“Runner -> Manager -> Git/Manifest/Initializer”，底层模块不反向依赖 Agent。
