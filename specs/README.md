# HuiCode Spec Documents

每个 mew-spec 阶段使用独立目录保存四份文档，避免覆盖历史：

```text
specs/
└── 003-agent-loop-plan-mode/
    ├── spec.md
    ├── plan.md
    ├── task.md
    └── checklist.md
```

规则：
- 新阶段先创建 `specs/<编号>-<阶段名>/`。
- 该阶段的 `spec.md`、`plan.md`、`task.md`、`checklist.md` 都写在该目录下。
- 根目录的 `spec.md`、`plan.md`、`task.md`、`checklist.md` 不再作为新阶段的主要文档位置。
- 已经完成的旧阶段保持归档，不再被后续阶段覆盖。

当前归档：
- `002-tool-system/`：工具系统阶段现存的 `plan.md`、`task.md`、`checklist.md`。
- `003-agent-loop-plan-mode/`：Agent Loop 与 Plan Mode 阶段，从 `spec.md` 开始继续。
