# SWE-bench-Live 快速提分路线验收报告

状态：三轮实施及 R3 七题正式复测已完成；成本/提示精简和执行纪律已有量化证据，复杂任务的质量结果保持在 3/7，尚未达到预设的 4/7 提升目标。

## 已交付

- 稳定提示去重：公共规则不再复制到每个工具描述。
- 长任务执行阶段提示：调查、实现、验证、收尾四阶段；第二轮调优将切换点提前到 20%/60%/85%。
- Agent 工具参数错误改为结构化反馈，并附合法 JSON 示例。
- 新增 SWE-bench 日志、report、token、耗时、迭代和测试结果汇总脚本。
- 运行配置曾切换到 `https://www.cctq.ai/v1`；最近一次已切回 `http://localhost:8080/v1`。密钥只通过环境变量注入，未写入仓库或日志。

## 本地验证

- 定向测试：36 项通过，包含新增的第 10 轮实现闸门测试。
- 全量测试：423 项中 419 项通过，1 项因 Windows 未授予创建目录符号链接权限而报错（WinError 1314），另有 3 项因同一环境限制跳过。该错误发生在未改动的 worktree 初始化能力中。
- `git diff --check` 无代码格式错误。

## 三题 quick gate

| 题目 | Agent 过程 | 补丁 | resolved | FAIL_TO_PASS | PASS_TO_PASS | 结论 |
|---|---:|---:|---:|---:|---:|---|
| `openai__openai-agents-python-1633` | 1776.6s，50 次迭代 | 1 个源码文件 | false | 0/1 | 566/566 | 目标测试未过，未回归；在 SDK 探索中耗尽迭代 |
| `a2aproject__a2a-python-443` | 562.8s，50 次迭代 | 4 个源码文件 | false | 2/25 | 641/641 | 目标测试大部分未过，未回归；改到存储层但未完成 handler 传播链 |
| `openai__openai-agents-python-1636` | 605.2s，50 次迭代 | 1 个源码文件 | true | 4/4 | 572/572 | 通过，未回归 |

quick gate 结果为 1/3（33.3%）。原始 7 题 gold-valid 基线为 3/7（42.9%），因此当前改动尚未证明 SWE-bench 通过率提升，也不应直接扩展到 7 题。

## 2026-08-27 cctq.ai 后续 quick gate

健康检查通过：`/v1/models`、非流式 `chat/completions` 和带工具的 SSE 均返回 200；HuiCode 实际 smoke test 正常返回 `API_SMOKE_OK`。长会话运行统一使用启动器级 600 秒 SSE 读等待，未修改 HuiCode Provider 源码。

| 运行 | 1633 | a2a-443 | 1636 | 结论 |
|---|---|---|---|---|
| cctq v1 | API/补丁失败 | API/补丁失败 | true | 1/3；两题不能作为能力分数 |
| cctq v2（提示闸门） | false，测试收集因模型引入 `AsyncRealtimeConnection` 导入失败 | false，FTP 23/25、PTP 640/641 | true，FTP 4/4、PTP 572/572 | 1/3；a2a 显著改善但有 1 个回归 |
| cctq v3（依赖兼容提示） | 仍生成同一类不兼容导入，未再送 harness | TLS EOF，中止且无可用补丁 | 未重跑，沿用 v2 通过结果 | 基础设施/实现信号不足，停止实验 |

v2 的 a2a Agent 日志还记录了生产改动后存储层测试 `90 passed, 2 skipped`；但正式 harness 仍有两个目标测试失败和一个原有测试回归。当前没有在相同有效条件下完成的全 7 题 token/耗时 A/B，因此不能宣称已经达到效率验收目标。

## 日志中的可疑点

- 1633：一次工具调用失败后 Agent 成功恢复，但连续读取 OpenAI SDK 细节，最终没有运行目标测试。
- a2a：第一轮因旧 API 502 无效；新 API v4 完成后通过了全部原有测试，但 25 个目标测试只通过 2 个；v5 因 Python TLS EOF 在一次编辑后中止，未计入评测。
- 1636：只读 explorer 子 Agent 被副本严格权限拒绝，但主 Agent 继续定向读取并完成修复；该题 resolved=true。
- cctq.ai 的短 SSE 探针和 HuiCode smoke test 均成功，但多轮运行仍出现 TLS 提前 EOF；A/B 运行临时将读取窗口放宽到 600 秒，仅用于诊断，不属于 HuiCode 源码改动。
- 第一次提示闸门调整使 a2a 从 FTP 0/25 提升到 23/25，但保留了 `TaskManager` 无 context 时旧 mock 调用不兼容及 `SimpleRequestContextBuilder` 回归。
- 依赖兼容提示仍未阻止 1633 引入仓库锁定环境不存在的 `openai.resources.realtime.realtime.AsyncRealtimeConnection`，说明仅靠提示难以解决全局 SDK 与题目依赖版本漂移。

## 下一步

1. 若继续实验，先换用能稳定完成长 SSE 会话的上游；600 秒客户端等待只能减少读超时，不能修复 TLS EOF。
2. 下一次 HuiCode 改动应从“仓库锁定依赖兼容检查”和“生产改动后强制验证”转向运行时可观察的硬约束，而不是继续堆提示文字。
3. 只有 1633/a2a/1636 quick gate 至少达到 2/3 且没有 PASS_TO_PASS 回归，才继续 7 题正式评测。

评测产物根目录：`D:\SWE-bench-Live-eval`。关键日志位于 `logs\gpt56-fast-v2`、`logs\gpt56-fast-v4`、`logs\gpt56-fast-v5`；过滤后补丁位于 `patches-gpt56-fast-v2`、`patches-gpt56-fast-v4`。

## 2026-08-29 localhost:8080 quick gate

配置已切回 `http://localhost:8080/v1`，使用 `gpt-5.6-sol`、`high`。健康检查通过：`/v1/models`、非流式 `chat/completions` 和带工具的 SSE 均返回 200；HuiCode 端到端 smoke test 返回 `API_SMOKE_OK`。首次尝试因副本缺少 permissive 权限且将多行 stdin 拆成多回合而作废，未计入结果；之后从单提交干净副本重跑。

Gold 校验 3/3 通过（补丁应用成功、`Error=0`）。正式 harness 结果为 1/3（33.3%），因此不扩展到 7 题。

| 题目 | Agent 日志耗时* | tokens（prompt/completion/total） | 补丁 | resolved | FAIL_TO_PASS | PASS_TO_PASS | 判断 |
|---|---:|---:|---:|---:|---:|---:|---|
| `openai__openai-agents-python-1636` | 1514s | 20022/201/20223 | 778B，1 个源码文件 | true | 4/4 | 572/572 | 通过，无回归 |
| `openai__openai-agents-python-1633` | 1435s | 22241/429/22670 | 2628B，1 个源码文件 | false | 0/1 | 566/566 | 目标测试未过：自定义 headers 仍被默认 headers 覆盖；无回归 |
| `a2aproject__a2a-python-443` | 1419s | 22118/77/22195 | 8930B，5 个源码文件 | false | 15/25 | 641/641 | 目标测试未过：10 个 handler 调用仍未传 context；无回归 |

\*耗时按日志文件创建到最后写入的时间跨度估算；本轮 localhost 单题约 24 分钟，明显高于短请求健康检查。

### 日志可疑点

- 1636：4 次工具失败，其中一次测试命令因 HuiCode 外层 10 秒工具限制超时；Agent 随后用副本 `.venv` 验证并报告 18 项通过。它额外编辑了测试文件，但正式补丁已过滤。
- 1633：2 次工具失败（读取命令/内联 async 探测），之后成功恢复；Agent 修改了生产文件和测试文件，但日志末尾没有完整 pytest 汇总，正式 harness 只显示唯一目标测试失败。
- a2a：explorer 子 Agent 未能读取工作区；主 Agent 回退成功。期间有 6 次工具失败（含多次 Edit 多匹配/无匹配），随后完成生产修改，但结束前没有完整 pytest 汇总。

本轮结果与此前 cctq quick gate 的 1/3 相同；由于上游、启动方式和运行时长不同，不把它宣称为严格 token/耗时 A/B。当前最明确的下一步仍是运行时硬约束：生产改动后必须验证，并让 realtime/handler 调用链的上下文传递成为可检查条件。

## 2026-08-29 runtime guard 1633 canary

本轮按 `T11R2 -> T11R2A` 执行，模型固定为 `gpt-5.6-sol/high`，API 回切 `http://localhost:8080/v1`，评测配置打开 `agent_guard.verification_gate` 与 `agent_guard.protect_test_edits`。1633 使用重新归档并 `git init` 的单提交副本；Agent 日志、会话、补丁和 harness 报告均保存在 `D:\SWE-bench-Live-eval`。

远端 HF 当前无法解析 `SWE-bench-Live/MultiLang` 的 `python` split，因此使用此前保存的 `data\selected_full.jsonl` 作为本地等价输入，仍调用同一份 official `evaluation.main` 和 Docker 测试流程。gold 校验成功：1633 `resolved=true`，目标测试 1/1，原有测试 566/566，`Error=0`。

| 运行 | 有效耗时 | 模型调用 | prompt / completion / 汇总 total | 补丁 | resolved | FAIL_TO_PASS | PASS_TO_PASS |
|---|---:|---:|---:|---:|---:|---:|---:|
| localhost-v2 基线 | 约 1435s | 50 | 623709 / 9100 / 632809 | 2628B | false | 0/1 | 566/566 |
| runtime guard v3 | 1740s | 50 | 578650 / 9657 / 588307 | 4020B | false | 0/1 | 566/566 |

与同一 localhost-v2 单题日志相比，汇总 token 下降约 7.0%，但耗时增加约 21.3%；因此只满足“效率至少一项改善”，没有证明 resolved 提升。过滤后的预测补丁只有 `src/agents/realtime/openai_realtime.py`，未包含测试文件或 `.huicode` 运行时目录。

正式失败原因是目标测试 `tests/realtime/test_openai_realtime.py::TestConnectionLifecycle::test_connect_with_custom_headers_overrides_defaults`：Agent 修复了默认 Azure 客户端、Azure URL、API key/token 认证，但没有保留显式 `headers` 的覆盖语义，结果仍注入 `Authorization` 与 `OpenAI-Beta`，而测试要求只使用调用方给出的 `api-key` 和 `x-custom`。`PASS_TO_PASS` 为 566/566，无回归。

日志复盘：一次 `Start-Sleep` 因实际 shell 为 cmd 失败；两次使用 `uv`/仓库 `.venv` 的导入检查超时，Agent 改用编译检查后继续；一次 `API_KEY_SENTINEL` 私有导入不兼容被定位并撤回；生产修改后 guard 多次迫使 Agent 先跑目标测试。另发现 guard 尚未识别带路径的 `.venv\\Scripts\\python.exe -m py_compile`，属于识别器边界，不计入 Agent 分数。

结论：本 canary 未达到 `FAIL_TO_PASS=1/1`，按计划不启动三题或七题正式评测，回到设计复盘。下一轮最高优先级是加入“兼容性收口”检查：修改公共连接/配置接口后，逐项审查显式 `headers`、`url`、`api_key` 和旧 mock 的优先级，完成 `git diff` 兼容性回看后再结束；同时修正 venv 路径验证命令识别，避免 guard 自身拦截合法检查。

## 2026-08-27 续跑记录

- `78code.cc` 非流式最小请求返回 200；按 HuiCode 的请求头做完整 Python SSE 小请求也返回 200 并正常收到 `[DONE]`。
- v6 重新运行 1633 时在 50 次迭代内未产生补丁，随后遇到 Python TLS EOF；a2a v6 在源码修改前也遇到同一 TLS EOF。两次均不计入 harness。
- 因此当前仍不能把 7 题结果归因于 HuiCode 改动；需要先解决新 API 对大请求/长会话的 Python SSE 稳定性，再重跑 quick gate。

## 2026-08-30 三轮改进最终验收（R3 full）

本轮保持 `gpt-5.6-sol`、`high`、`http://localhost:8080/v1`、原题目、单提交封存副本、非交互启动方式和 harness 参数不变；R3 配置使用 `agent_guard.protect_test_edits=true`、`max_production_files=5`，不启用强制验证闸门。10 道候选题中 3 道 gold 环境无效，先剔除；其余 7 道 gold 校验全部 `resolved=true`、`Error=0`，再进行 Agent 正式评测。

### 三轮结果

- Round 1：三题 prompt tokens 从 1,792,364 降到 1,484,055，下降 17.2%；无新增 `PASS_TO_PASS` 回归，resolved 仍为 1/3。成本目标有证据，质量未提升。
- Round 2：接口闭环提示使 443 的目标测试最高达到 15/25，但仍有 1 个原有测试回归；随后将硬约束降为 R3 canary 验证。
- Round 3 canary：443 在 scope guard 下达到 `FAIL_TO_PASS 25/25`、`PASS_TO_PASS 641/641`；Agent 尝试扩展到第 6 个生产文件时被拦截一次，并继续在已有文件内完成修复。
- Round 3 full：3/7 resolved（42.9%），与该七题保存基线的 3/7 相比没有证明整体通过率提升；但 443、8211、1636 均通过，且 harness `error=0`、`incomplete=0`。

### R3 full 逐题结果

| 题目 | 耗时 | 补丁 | resolved | FAIL_TO_PASS | PASS_TO_PASS | 失败原因 | 日志可疑点 |
|---|---:|---:|---:|---:|---:|---|---|
| `a2aproject__a2a-python-443` | 1978.6s | 5 个生产文件 | true | 25/25 | 641/641 | 通过 | 13 次工具失败；1 次 scope limit；多次 Edit 多匹配/无匹配，之后恢复并完成闭环 |
| `django-guardian__django-guardian-896` | 689.1s | 2 个源码文件 + `pyproject.toml` | false | 0/2 | 308/308 | 2 个索引目标测试未过 | 6 次工具失败；测试文件编辑被拒 1 次；本地依赖缺失；还改了 warning 配置 |
| `django-guardian__django-guardian-899` | 418.2s | 1 个源码文件 | false | 0/1 | 290/293 | 目标缓存事务测试未过，并造成 3 个原有测试回归 | 2 次工具失败；完整测试未能运行，依赖/配置不足 |
| `networkx__networkx-8211` | 333.6s | 1 个源码文件 | true | 1/1 | 6691/6691 | 通过 | 3 次工具失败；2 次 `git` 命令拼接导致 bad revision，已恢复 |
| `openai__openai-agents-python-1619` | 220.6s | 空补丁 | false | 未运行 | 未运行 | Agent 无生产改动，harness 标记 empty patch | 6 轮后无最终文本、无源码 Edit；1 次 shell 变量命令失败 |
| `openai__openai-agents-python-1633` | 1290.1s | 2 个源码文件 | false | 0/1 | 566/566 | Azure realtime 自定义 headers 目标测试未过 | 9 次工具失败；2 次超时；`pyright` 缺失；1 次危险命令被安全层拦截；最终自报测试通过但目标测试仍失败 |
| `openai__openai-agents-python-1636` | 1322.1s | 1 个源码文件 | true | 4/4 | 572/572 | 通过 | 12 次工具失败；pyright/环境超时；内联 async 探针两次写法错误，但未阻止最终修复 |

R3 Agent JSONL 合计：prompt `3,859,522`、completion `67,206`、total `3,926,728` tokens；七题串行墙钟约 `6,252.3s`（104.2 分钟）；工具失败 46 次，达到最大迭代上限 0 题。该轮的效率改善仍以 Round 1 的同题 prompt 下降 17.2% 为主要证据，没有把不同运行批次的耗时宣称为严格 A/B。

### 结论与下一步

本轮结果支持“主要瓶颈在 Agent 编排”的判断：不换模型，scope guard canary 将 443 从存在回归提升到目标和原有测试全通过；但 full 7 的失败仍集中在接口兼容性收口、任务理解/目标测试闭环和空回复恢复，而不是 API 连通性或 harness 环境错误。下一步优先级应为：

1. 为空回复/空补丁增加循环级恢复：要求至少一次生产定位或明确阻塞报告，避免 1619 直接结束。
2. 在公共接口改动后自动生成“显式参数优先级、旧 mock、直接调用方、目标测试”的收口清单；重点修复 1633 的 headers 语义和 899 的缓存兼容性回归。
3. 把 `max_production_files=5` 改为按调用链动态预算或仅对明显旁支扩展限流，避免复杂题被固定文件数误伤。
4. 保留 `protect_test_edits`，但把环境依赖缺失与临时验证命令错误从 Agent 主循环中更快隔离，减少 46 次工具失败带来的 token/耗时浪费。

最终产物根目录：`D:\SWE-bench-Live-eval`；R3 Agent 日志：`logs\gpt56-orch-r3-v1`；补丁汇总：`predictions\gpt56-orch-r3-v1\predictions.json`；harness 结果：`logs\eval-gpt56-orch-r3-v1\results.json`。
