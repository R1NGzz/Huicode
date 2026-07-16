# Worktree 隔离实施任务

## 文件清单

### 新建

- `huicode/worktrees/__init__.py`：导出 Worktree 公共接口。
- `huicode/worktrees/types.py`：Worktree 标识、句柄、处置结果、清理记录和异常。
- `huicode/worktrees/naming.py`：逻辑名、分支名、根目录与最终路径校验。
- `huicode/worktrees/manifest.py`：管理清单读取、校验和原子写入。
- `huicode/worktrees/git.py`：无 shell 的 Git 命令封装和 Worktree 状态操作。
- `huicode/worktrees/initializer.py`：配置复制、忽略文件恢复、目录链接和 Hooks 初始化。
- `huicode/worktrees/manager.py`：创建、恢复、退出、删除和回滚编排。
- `huicode/worktrees/cleanup.py`：过期扫描、三层过滤和后台生命周期。
- `huicode/workspaces.py`：按规范绝对路径加载项目指令与记忆上下文。
- `tests/test_worktree_naming.py`
- `tests/test_worktree_manifest.py`
- `tests/test_worktree_git.py`
- `tests/test_worktree_initializer.py`
- `tests/test_worktree_manager.py`
- `tests/test_subagent_worktree.py`
- `specs/015-worktree-isolation/acceptance_report.md`

### 修改

- `huicode/config.py`：增加并解析 `WorktreeConfig`。
- `huicode/subagents/types.py`：隔离字段和 Worktree 结果元数据。
- `huicode/subagents/parser.py`：解析并校验 `isolation`。
- `huicode/subagents/runner.py`：准备隔离上下文并执行结束处置。
- `huicode/subagents/manager.py`：任务视图与后台结果保留 Worktree 元数据。
- CLI 运行时组装文件：创建、注入、启动和关闭 Worktree 管理器。
- `huicode/prompts/base.py` 或 `huicode/prompts/modules.py`：加入隔离工作区动态提示块。
- 内置子 Agent 角色文件：显式维持 `shared`，并补一份测试隔离角色时按测试夹具处理。
- `README.md`：增加 Worktree 配置、角色声明和保留规则。
- `docs/mew-spec-pitfalls.md`：发生真实返工时追加记录。

## 任务依赖

```text
T1 -> T2 -> T3 -> T4
             -> T5 -> T6
T1 -> T7 -> T8
T4 + T6 + T8 -> T9 -> T10
T9 -> T11 -> T12
T10 + T12 -> T13 -> T14 -> T15
```

## 实施任务

### T1 配置与领域类型

**依赖：** 无

**步骤：**

1. 在 `huicode/config.py` 增加不可变 `WorktreeConfig` 和安全默认值。
2. 解析顶层 `worktrees` YAML 映射，校验正数、字符串列表、可选 Hooks 路径和重复项。
3. 在 `LLMConfig` 中挂载 Worktree 配置。
4. 在 `huicode/worktrees/types.py` 定义 identity、handle、disposition、cleanup record 与结构化异常。
5. 在 `huicode/worktrees/__init__.py` 只导出稳定公共类型。

**验证：**

- 新增配置单元测试，覆盖默认值、完整配置、错误类型、非法期限和重复路径。
- 运行 `python -m unittest` 对应配置测试。

### T2 角色隔离字段

**依赖：** T1

**步骤：**

1. 给 `AgentDefinition` 增加 `isolation`，默认语义为 `shared`。
2. 把 `isolation` 加入 frontmatter 允许字段。
3. 解析缺省、`shared` 和 `worktree`。
4. 对未知值生成角色加载错误。
5. 确认 Fork 请求结构没有新增 Worktree 参数。

**验证：**

- 扩展角色解析测试，覆盖缺省、两种合法值和非法值。
- 运行现有子 Agent catalog/parser 测试，确认旧角色继续加载。

### T3 名称与路径安全

**依赖：** T2

**步骤：**

1. 实现逻辑名字符集、单段长度、总长度和嵌套深度常量。
2. 拒绝空段、`.`、`..`、反斜杠、绝对路径、盘符、控制字符和保留路径形式。
3. 将合法逻辑名映射为目录层级和安全分支片段。
4. 解析配置根目录并验证位于主仓库内。
5. 解析最终任务路径并再次执行 `relative_to` 边界验证。

**验证：**

- `tests/test_worktree_naming.py` 使用表驱动覆盖合法嵌套和各类逃逸输入。
- 使用 mock 断言非法输入发生时未触发 Git Backend 或文件写入。

### T4 可信管理清单

**依赖：** T3

**步骤：**

1. 定义带格式版本的清单序列化结构。
2. 使用临时文件加原子替换写入 UTF-8 JSON。
3. 读取时严格校验必需字段、字段类型和格式版本。
4. 校验仓库、任务、逻辑名、规范绝对路径、分支和基线。
5. 对缺失、损坏和不匹配返回不同错误码。

**验证：**

- `tests/test_worktree_manifest.py` 覆盖往返、坏 JSON、旧版本、字段缺失和各字段不匹配。
- 模拟写入中断，确认旧清单仍可读取或明确不存在，不产生半截有效文件。

### T5 Git Backend

**依赖：** T3

**步骤：**

1. 实现参数数组、`shell=False`、显式 `cwd` 和超时的 Git 执行器。
2. 实现仓库根、公共 Git 目录、当前 HEAD 和稳定仓库标识读取。
3. 实现独立分支 Worktree 创建、注册移除和任务分支删除。
4. 实现 porcelain 脏状态检测。
5. 实现上游存在与无上游两种未推送提交检测。
6. 实现 per-worktree Hooks 配置。
7. 把 stderr 和操作上下文转换为不泄密的 `WorktreeError`。

**验证：**

- `tests/test_worktree_git.py` 在临时 Git 仓库配置局部用户名和邮箱后运行。
- 覆盖创建、独立修改、干净、未提交、已提交无上游、配置上游后的 ahead 判断和删除。
- mock `subprocess.run` 确认所有调用 `shell=False` 且带显式 `cwd`。

### T6 环境初始化器

**依赖：** T4、T5

**步骤：**

1. 实现默认可选配置文件复制与显式配置缺失报错。
2. 实现忽略文件 glob 展开、逐项边界检查和相对结构复制。
3. 实现目录链接，拒绝文件来源、越界来源和已存在目标。
4. 调用 Git Backend 配置 Hooks。
5. 最后写管理清单，确保半初始化目录不会被识别为可恢复。
6. 汇总具体失败步骤，供 Manager 执行回滚。

**验证：**

- `tests/test_worktree_initializer.py` 覆盖复制、glob、空匹配、越界、链接和 Hooks 调用。
- 平台允许时验证链接指向源目录；不允许时验证明确失败而非复制降级。
- 验证初始化失败前不会写有效清单。

### T7 工作区上下文加载器

**依赖：** T1

**步骤：**

1. 新增 `WorkspaceContextLoader`，规范化工作目录绝对路径。
2. 复用 `InstructionLoader` 加载该目录的项目指令。
3. 复用 `NoteStore`/`MemoryIndex` 读取该目录对应的项目记忆索引，不启动会话记录或自动记忆更新。
4. 缓存键包含规范绝对工作目录和相关文件快照。
5. 提供不启用缓存或清除单个绝对目录条目的测试入口。

**验证：**

- 创建两个临时工作区，放入不同指令和记忆，验证结果不串线。
- 修改其中一个目录，验证仅该目录缓存失效。

### T8 隔离 Prompt

**依赖：** T7

**步骤：**

1. 给 Prompt 上下文增加可选 Worktree 路径和分支字段，或通过 Runner 角色补充块传入等价数据。
2. 渲染高优先级动态指令，包含目录、分支、禁止修改主工作区和不自动合并说明。
3. 对路径文本做现有 Prompt 安全转义或结构化标签包裹。
4. 共享工作区任务不渲染该块。

**验证：**

- Prompt 测试断言隔离任务包含准确绝对路径和分支。
- 共享定义式与 Fork Prompt 均不出现 Worktree 说明。

### T9 WorktreeManager 创建与恢复

**依赖：** T4、T6、T8

**步骤：**

1. 实现 `prepare()` 的仓库检查、名称验证和目标路径计算。
2. 目标不存在时从当前 HEAD 创建独立分支与 Worktree。
3. 执行环境初始化并返回 `WorktreeHandle`。
4. 初始化失败时移除刚创建的 Worktree 和任务分支；回滚失败时合并错误信息并保留目录。
5. 目标已存在时只读取清单并进行完全匹配，不调用 Git Backend。
6. 实现幂等退出标记，不改变进程当前目录。

**验证：**

- `tests/test_worktree_manager.py` 覆盖新建、基线、独立目录、回滚和重复退出。
- 用会在任意调用时报错的 Fake Git Backend 验证已有目录恢复全程零 Git 调用。
- 校验清单缺失或不匹配时拒绝接管。

### T10 删除保护与结束处置

**依赖：** T9

**步骤：**

1. 实现 `finalize()`：失败、取消直接保留；成功任务继续检查 Git 状态。
2. dirty 或 unpushed 时返回 retained，不调用删除。
3. 成功、干净且无未推送提交时执行安全删除。
4. 删除前重新核对根目录边界和管理清单。
5. 删除 Worktree 后清理任务分支和残留空父目录。
6. 生成稳定的状态和用户可读原因。

**验证：**

- 覆盖成功干净自动删除、脏修改保留、提交无上游保留、失败保留和取消保留。
- mock Git Backend 断言保护命中时未调用删除。

### T11 过期清理器

**依赖：** T10

**步骤：**

1. 只枚举专用根目录下固定位置的管理清单，不跟随链接。
2. 依次执行根目录边界、清单有效性和仓库归属三层过滤。
3. 根据清单创建时间和配置期限筛选候选。
4. 调用 Manager 的受保护删除路径，不复制删除逻辑。
5. 每个候选独立捕获错误并生成清理记录。
6. 实现可停止的后台线程、启动时扫描和周期扫描。

**验证：**

- 覆盖未过期、伪造清单、错误仓库、路径链接、dirty、unpushed 和安全过期目录。
- 验证一个候选异常不阻止后续候选处理。
- 使用短间隔和停止事件验证线程可关闭。

### T12 子 Agent Runner 集成

**依赖：** T8、T10

**步骤：**

1. 向 Runner 注入 `WorktreeManager` 和 `WorkspaceContextLoader`。
2. 仅对定义式 `isolation=worktree` 调用 `prepare()`。
3. 用实际 Worktree 创建权限上下文、`ToolContext`、`ContextManager` 和项目上下文。
4. 确认所有读写搜索和 Bash 工具继承同一个显式 workspace。
5. 在 `finally` 调用 `finalize()`，异常和取消也执行。
6. 扩展结果、任务视图、后台结果和通知，保留路径、分支、状态和原因。
7. 准备失败时直接结束，不回退主工作区。

**验证：**

- `tests/test_subagent_worktree.py` 使用 Fake Provider 与临时仓库验证隔离工具实际 cwd。
- 验证共享定义式与 Fork 不调用 WorktreeManager。
- 验证准备失败、Agent 异常、取消、保留和自动清理结果。

### T13 CLI 生命周期与诊断

**依赖：** T11、T12

**步骤：**

1. 在 CLI 运行时创建 WorktreeManager 和 WorkspaceContextLoader。
2. 将它们注入子 Agent Runner。
3. 启动后台清理器，并把启动警告接入现有界面消息。
4. CLI 关闭时停止清理器，再关闭子 Agent 管理器，避免新任务与清理竞态。
5. 在子 Agent 状态和结果展示中加入简洁的 Worktree 路径、分支与保留原因。

**验证：**

- CLI 组装测试确认构造、注入和关闭顺序。
- Fake Manager 测试清理异常只显示警告，不中断启动和对话。

### T14 文档与端到端场景

**依赖：** T13

**步骤：**

1. 在 README 增加 `isolation: worktree` 角色示例。
2. 记录 `worktrees` YAML 完整字段和默认值。
3. 说明主工作区未提交修改不会带入、Fork 不隔离、失败/脏/未推送会保留。
4. 说明本章不自动合并，并给出用户检查目录与分支的方法。
5. 通过真实临时 Git 仓库、Fake Provider 和定义式子 Agent 执行一次端到端修改。

**验证：**

- 检查 README 示例可被当前 YAML 和角色解析器接受。
- 端到端验证主工作区文件不变，Worktree 文件已修改，结果包含保留路径和分支。

### T15 全量回归与验收

**依赖：** T14

**步骤：**

1. 运行 Worktree 专项测试。
2. 运行完整 unittest 测试集。
3. 运行 `python -m compileall huicode tests`。
4. 检查 `git diff --check`。
5. 逐项执行 `checklist.md`，记录实际证据。
6. 如出现真实返工，更新 `docs/mew-spec-pitfalls.md`。
7. 生成 `acceptance_report.md`。
8. 仅暂存本章相关文件并按 `AGENT.md` 创建 Git 提交。

**验证：**

- 所有自动化测试通过且无编译、空白错误。
- 验收报告包含每个 AC 的对应证据和端到端结果。
- `git status --short` 中用户已有未跟踪文件未被暂存或删除。

## 执行顺序

1. T1 配置与领域类型
2. T2 角色隔离字段
3. T3 名称与路径安全
4. T4 可信管理清单
5. T5 Git Backend
6. T6 环境初始化器
7. T7 工作区上下文加载器
8. T8 隔离 Prompt
9. T9 WorktreeManager 创建与恢复
10. T10 删除保护与结束处置
11. T11 过期清理器
12. T12 子 Agent Runner 集成
13. T13 CLI 生命周期与诊断
14. T14 文档与端到端场景
15. T15 全量回归与验收

## 任务覆盖自检

- `plan.md` 中的配置、角色、命名、清单、Git、初始化、上下文、Runner、清理和 CLI 组件均至少有一项实施任务。
- 所有任务都声明依赖、具体步骤和验证方法。
- 安全底座先于任何生命周期与 Agent 集成任务。
- 端到端验收和全量回归排在所有实现任务之后。
