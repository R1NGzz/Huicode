# T2：应用生命周期、健康检查与请求边界

日期：2026-09-22。状态：接口测试及真实 Uvicorn 离线依赖场景已验证；真实数据库在线场景、Worker 尚未验证。AI 辅助实现，用户理解状态待自测。

代码：[应用工厂](../../huicode/server/app.py)、[依赖探测](../../huicode/server/health.py)、[HTTP 路由](../../huicode/server/api/health.py)、[接口测试](../../tests/server/test_app.py)。

## 为什么要这样做

数据库暂时掉线时，API 进程可能仍然健康。若把数据库故障等同进程死亡，部署系统就会反复重启 API，而数据库故障不会因此修复。因此 live 只报告 API 能响应，ready 则尝试 SELECT 1 与 Redis PING，失败返回 503。

应用工厂接收配置和健康检查工厂，测试可以注入 FakeHealth，精确模拟依赖在线和离线。真实探测仍需要独立集成验证；假依赖测试不能证明真实 PostgreSQL 已连通。

lifespan 管理应用整个生命周期：启动创建客户端，关闭释放连接池。它与每次请求的处理函数不同。API 不启动独立 Worker；Worker 心跳探测在 T15 接入，目前不能声称系统已能接收并执行任务。

## 工程取舍

- 依赖探测并行且各设 2 秒期限，避免一个不可用依赖无限拖住健康接口。客户端按需连接，应用可以在依赖离线时启动。
- 请求 ID 由服务端生成，不盲信外部输入。纯 ASGI 中间件直接转发消息，避免未来 SSE 被完整缓冲。
- 错误响应使用统一结构，参数验证错误不回显原始输入。请求日志只记录路由模板、状态码、耗时和请求 ID。当前暂时丢弃详细异常，不具备完整根因诊断能力；后续安全日志与错误分类需补齐。
- AsyncExitStack 管理连接清理，创建后续资源失败时也清理已创建的资源。

## 实际阻碍与证据

已成功创建仓库内 .venv。默认 pip 安装停留在构建依赖阶段；显式使用 https://pypi.org 重试和 isolated 模式均报告找不到 setuptools 的可用版本。这不能证明 setuptools 不存在，也不能证明具体网络根因；目前只能确认此安装路径无法获得必需包。

后续排查纠正：前一次显式索引命令漏写 `/simple`，详细日志证实请求 `https://pypi.org/setuptools/` 返回 404。那次“找不到版本”来自错误索引路径，不是包不存在。使用正确索引后安装成功。默认安装挂起的根因没有进一步证实，不将两次现象混为一谈。

验证结果：`python -m unittest tests.server.test_config tests.test_config tests.server.test_app -v` 共 31 项通过；`python -m unittest tests.test_cli -q` 共 13 项通过；`pip check` 无依赖冲突，CLI `--help` 正常退出。当前 Starlette 对 httpx TestClient 发出弃用警告，测试仍通过，后续依赖锁定时处理兼容性，不把警告当作失败或忽略不记。

真实 Uvicorn 进程绑定临时本地端口，以不可达端口 1 作为数据库/Redis 地址：live=200，ready=503 且两个依赖均 unavailable，未知路由=404；响应体和响应头的请求 ID 一致。验证后终止该测试子进程；优雅清理由生命周期接口测试覆盖，未声称强制终止验证了优雅关闭。

## 自己动手

前置条件：先按 [开发环境指南](../web-studio-local-development.md) 安装依赖成功。当前项目 .venv 已完成安装，可以从指南的启动 API 步骤开始。

1. 打开 PowerShell，进入 `C:\Users\Administrator\Documents\Huicode`，复制指南的启动 API 命令块执行，保持终端打开。
2. 另开终端执行 `curl.exe -i http://127.0.0.1:8000/health/live`，预期看到 HTTP 200 和 alive。
3. 执行 `curl.exe -i http://127.0.0.1:8000/health/ready`，未启动数据库/Redis 时预期 HTTP 503 和 unavailable。这是预期结果，不是 API 崩溃。
4. 执行 `curl.exe -i http://127.0.0.1:8000/missing`，预期 HTTP 404，JSON 内有 error 与 request_id，响应头也有相同编号。
5. 回到启动终端按 Ctrl+C 停止服务；这些操作没有写业务数据，不需要恢复文件。

小练习：在测试的 FakeHealth 中只把 redis 改成 unavailable，预测 live/ready 的状态码，运行 `.\.venv\Scripts\python.exe -m unittest tests.server.test_app.AppTests.test_dependency_outage_only_affects_readiness -v` 核对已有测试。这是模拟故障，不是真实断开 Redis。

自测：数据库断线为什么不让 live 失败？连接池为什么放 lifespan？FakeHealth 测试通过能说明什么？答案分别是避免无效重启、管理跨请求共享资源、只能证明 API 对模拟依赖状态的行为。

## 面试边界

可以说明应用骨架、错误响应、模拟依赖和真实离线启动已经验证；不能声明真实数据库已连通、Worker 已就绪或生产日志已完善。
