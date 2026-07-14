---
name: test
description: 识别并运行最相关的测试，归纳失败原因和剩余风险
allowed_tools:
  - Read
  - Find
  - Search
  - Bash
mode: isolated
history_messages: 6
---
你正在执行测试验证任务。

用户补充要求：{{args}}

先根据项目结构和当前改动识别最相关、范围最小的测试命令，再运行测试。不要修改项目文件或测试来掩盖失败。总结实际运行的命令、通过与失败情况、失败根因和尚未覆盖的风险。
