---
name: commit
description: 检查当前改动并创建符合项目习惯的 Git 提交
allowed_tools:
  - Read
  - Bash
mode: shared
---
你正在执行 Git 提交流程。

用户补充要求：{{args}}

先检查 `git status`、相关 diff 和最近提交风格，确认改动范围与用户目标一致。不要提交无关文件，不要改写用户已有改动。拟定简洁、准确的提交说明后执行提交；提交仍须遵守当前权限确认。完成后报告 commit id 和实际提交内容。
