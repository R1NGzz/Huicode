# HuiCode Skill System 验收报告

## 结论

Skill 系统已按批准的 spec、plan、task 和 checklist 实现。单文件与目录型 Skill、三级覆盖、两阶段 Prompt 加载、shared/isolated 执行、工具白名单、动态 Slash Command、热更新、模型覆盖和三个内置样板均已接入现有 Agent、权限、上下文、记忆和 MCP 流程。

验收结论：**通过，存在两项环境限制，不影响功能判定。**

## 自动验证

- 全量测试：`python -m unittest discover -v`
  - 结果：283 项通过，2 项跳过，0 失败。
  - 跳过项：Windows 当前账户无创建符号链接权限，Skill 与权限沙箱各一项真实 symlink 测试跳过；路径解析和越界拒绝的非 symlink 测试通过。
- 编译检查：`python -m compileall -q huicode tests`
  - 结果：通过。
- Diff 检查：`git diff --check`
  - 结果：通过；只有 Git 的 LF/CRLF 提示，无空白错误。
- 硬编码迁移检查：源码与测试中搜索 `REVIEW_PROMPT`。
  - 结果：无匹配，`/review` 完全来自 Skill Catalog。

测试使用 Codex 工作区 Python 3.12。为该运行时安装了项目声明的 `PyYAML`、`rich` 和 `prompt_toolkit` 依赖；`pyproject.toml` 已新增 `PyYAML>=6`。

## AC 验收证据

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC1 | 通过 | parser/discovery 测试覆盖两种布局、字段错误、空正文、坏文件隔离和路径边界。 |
| AC2 | 通过 | catalog 测试验证项目 > 用户 > 内置，同层重复可回退低层。 |
| AC3 | 通过 | Prompt 测试用正文哨兵确认未激活时只注入 name/description/mode。 |
| AC4 | 通过 | SkillTool 测试验证参数原样替换，下一轮出现最高动态优先级 SOP。 |
| AC5 | 通过 | Manager 测试验证同名替换、多 Skill 有序保持和重建。 |
| AC6 | 通过 | 未知本地/MCP 名称触发 SkillConfigError；系统 Skill 工具在过滤后保留。 |
| AC7 | 通过 | chat/plan、多 Skill、空白名单及 Plan + strict 组合测试通过；普通工具仍被权限拒绝。 |
| AC8 | 通过 | shared 主历史、工具结果回灌和当前轮模型覆盖/清理测试通过。 |
| AC9 | 通过 | isolated 使用独立 AgentState，协议安全选择历史，主路径只接收请求与摘要。 |
| AC10 | 通过 | 子会话错误、迭代上限和四层嵌套转换为结构化失败。 |
| AC11 | 通过 | 动态 `/help`、补全、命令分发及原始大小写参数测试通过。 |
| AC12 | 通过 | 核心 registry 不再登记 review，上层 Skill 覆盖由三级 Catalog 统一处理。 |
| AC13 | 通过 | CLI 集成验证同一次输入热加载；非法白名单保留上一有效 SOP 和命令。 |
| AC14 | 通过 | `/clear` 后 active=none、工具恢复基础集合，Catalog 和命令仍存在。 |
| AC15 | 通过 | 启动 Catalog 自动发现 commit/review/test，元数据与命令均通过校验。 |
| AC16 | 通过 | 启动摘要和 `/status` 输出数量、active、reload errors、工具摘要，不输出 SOP/secret。 |
| AC17 | 通过 | Anthropic/OpenAI Provider 工具历史测试与 isolated 安全切片测试全部通过，thinking/signature 原逻辑保持。 |
| AC18 | 通过 | 283 项测试、compileall、diff check 和 README 对照通过；tmux 受环境限制，使用 CLI fake-provider 场景替代。 |

## 端到端场景

在 `tests/test_cli_skills.py` 和 `tests/test_cli_commands.py` 中完成非网络 CLI 集成：

1. 启动显示三个内置 Skill，`/help` 动态展示 commit/review/test，Provider 零调用。
2. 项目 shared Skill 通过 Slash Command 激活，完整 SOP 注入，普通工具收窄为 Read + 系统 Skill。
3. 内置 `/review` 以 isolated 模式运行，Plan Mode 下只暴露 Read/Find/Search/Skill，最终摘要回流。
4. 新建 Skill 后，本次顶层输入分流前完成热加载并立即执行。
5. 热更新加入未知工具时保留旧快照，旧命令和 SOP 继续可用，TUI 输出 reload error。
6. `/clear` 清空 active 和工具限制，`/status` 显示 active=none，Catalog 仍存在。
7. Plan Mode + strict 权限下系统 Skill 可激活，随后普通 Read 仍被 strict 权限拒绝。
8. shared/isolated model 覆盖均只作用于规定范围，后续恢复主模型。

## 环境限制与剩余风险

- 当前 Windows 环境没有 tmux，未执行 AGENT.md 中的真实 tmux TUI 步骤；fake Provider 覆盖了输入分流、Prompt、工具列表、子循环和输出状态，但不替代真实第三方模型的人工观感测试。
- 当前账户无符号链接创建权限，因此未实际创建逃逸链接；实现使用 `resolve()` 加 `relative_to()`，并保留可在有权限环境运行的 symlink 测试。
- 未使用真实 OpenAI、Anthropic 或 DeepSeek 请求做联网验收，避免消耗用户密钥；现有 Provider 序列化测试覆盖 thinking、tool_use/tool_result 和 OpenAI tool_calls 配对。

## 文档与返工记录

- README 已补充 Skill 格式、目录、优先级、两阶段加载、执行模式、白名单、动态命令、热更新和内置样板。
- `docs/mew-spec-pitfalls.md` 新增“系统工具通过可见列表过滤后仍被执行前二次防线拒绝”，记录本章实际发现并修复的双层校验问题。
