# HuiCode Plan Mode 权限与交互修复 Checklist

## Implementation Completeness

- [ ] C1: Plan Mode 在工具执行层拦截非读类工具。
  - Verification: 单测模拟模型返回 `Bash(echo 2 > hello.txt)`，文件未被创建或修改。
  - Maps to: AC1

- [ ] C2: Plan Mode 拦截结果以结构化 `permission_denied` 工具结果回灌进对话历史。
  - Verification: 单测检查会话历史中存在对应 tool result，并包含 Plan Mode 只允许读类工具的说明。
  - Maps to: AC1, AC2

- [ ] C3: Plan Mode 拒绝非读类工具后 Agent Loop 继续下一轮。
  - Verification: 单测使用两段 provider 响应，第一段工具被拒绝，第二段产生最终回答。
  - Maps to: AC2

- [ ] C4: Plan Mode 拦截发生在权限确认前。
  - Verification: 单测配置会失败的 confirmer 或统计 confirmer 调用次数，确认未触发确认。
  - Maps to: AC1

- [ ] C5: 每轮开始的 progress event 包含任务模式和权限模式。
  - Verification: 单测检查 `assistant_turn_start` event 的 `data.mode` 与 `data.permission_mode`。
  - Maps to: AC3

- [ ] C6: TUI 每轮开始输出当前任务模式和权限模式。
  - Verification: `tests/test_tui.py` 检查渲染文本包含 `mode` 和 `permission` 信息。
  - Maps to: AC3

- [ ] C7: 权限确认展示包含快捷键和默认拒绝说明。
  - Verification: `tests/test_tui.py` 检查文案包含 `d/o/s/a` 与 `enter=deny` 或中文等价说明。
  - Maps to: AC4

- [ ] C8: CLI 权限确认输入提示更短，并支持空输入默认拒绝。
  - Verification: `tests/test_cli.py` 覆盖 prompt 文本和空输入结果。
  - Maps to: AC4

- [ ] C9: `/perm` 是 `/permissions` 的等价别名。
  - Verification: `tests/test_cli.py` 覆盖 `/perm` 查询和 `/perm strict|default|permissive` 切换。
  - Maps to: AC5

- [ ] C10: README 记录 `/perm` 和权限确认快捷键。
  - Verification: 文档中可搜索到 `/perm` 与 `d/o/s/a`。
  - Maps to: AC5

## Integration Checks

- [ ] I1: 现有权限模式语义不变。
  - Verification: 既有 permission 相关测试继续通过。
  - Maps to: AC6

- [ ] I2: 读类工具在 Plan Mode 中仍可正常执行。
  - Verification: 既有或新增测试覆盖 `Read`/`Find` 等读类工具成功执行。
  - Maps to: AC1, AC6

- [ ] I3: 工具结果事件和 TUI 工具行格式不回归。
  - Verification: 既有 Agent Loop/TUI 测试继续通过。
  - Maps to: AC2, AC6

## Build And Test Checks

- [ ] T1: 目标测试通过。
  - Command: `python -m unittest tests.test_agent_loop tests.test_cli tests.test_tui -v`
  - Maps to: AC6

- [ ] T2: 全量测试通过。
  - Command: `python -m unittest discover -v`
  - Maps to: AC6

- [ ] T3: 编译检查通过。
  - Command: `python -m compileall -q huicode tests`
  - Maps to: AC6

- [ ] T4: tmux E2E 检查完成或记录不可用原因。
  - Command: `Get-Command tmux -ErrorAction SilentlyContinue`
  - Maps to: AGENT.md

## End-To-End Scenario

- [ ] E1: Plan Mode 越权写入被拒绝。
  - Scenario:
    1. 进入 `/plan`。
    2. 模型请求或用户诱导 `Bash(echo 2 > hello.txt)`。
    3. HuiCode 不弹出权限确认。
    4. HuiCode 显示工具被 Plan Mode 拒绝。
    5. `hello.txt` 不被写入。
    6. HuiCode 继续回答用户。
  - Verification: 自动测试覆盖核心行为；若 tmux 可用，再做终端 E2E。
  - Maps to: AC1, AC2, AC3

- [ ] E2: 权限交互更短。
  - Scenario:
    1. 普通模式下触发需要确认的副作用命令。
    2. TUI 展示 `d/o/s/a` 和默认拒绝。
    3. 输入 `o` 可本次放行。
    4. 直接回车会拒绝。
  - Verification: CLI/TUI 单测覆盖输入解析和展示文本。
  - Maps to: AC4, AC5

## Acceptance Report Requirements

- [ ] R1: `acceptance_report.md` 记录每个 checklist 项的实际结果。
- [ ] R2: 报告包含执行过的测试命令和结果摘要。
- [ ] R3: 报告包含 tmux 是否可用及 E2E 处理情况。
- [ ] R4: 报告说明是否已提交 Git commit。

## Self Check

- 每个 AC 至少映射到一个 checklist 项。
- 安全修复、TUI 展示、CLI 交互、测试和文档都有覆盖。
- E2E 场景直接复现用户报告的问题。
