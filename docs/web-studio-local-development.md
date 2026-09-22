# Web Studio 开发环境

当前进度：T1 配置与旧配置回归、T2 API 测试及真实 Uvicorn 离线依赖场景已通过。Worker 尚未实现，当前就绪探测只覆盖 PostgreSQL 与 Redis，不代表完整任务执行系统就绪。真实依赖在线验证留待数据库阶段。

## 安装

在项目根目录的 PowerShell 中执行以下命令。已有 .venv 时跳过创建步骤；不要使用共享解释器安装项目包。

```powershell
Set-Location 'C:\Users\Administrator\Documents\Huicode'
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -e '.[server,server-test]'
.\.venv\Scripts\python.exe -m unittest tests.server.test_config tests.test_config tests.server.test_app -v
```

如果安装显示找不到 setuptools 等基础包，先检查包源可达性和 pip 配置，不能把它当作应用测试失败。此次排查确认曾错误使用 `https://pypi.org` 作为索引，导致请求 `/setuptools/` 返回 404；pip 的索引应使用 `https://pypi.org/simple`。安装成功后再运行后续步骤。

## 启动 API

以下配置仅用于本地开发；项目目录需要预先存在。环境变量仅在当前终端有效。示例数据库凭据是假值，真正的 ready=200 需要换成可用的 PostgreSQL 和 Redis。本阶段不自动创建数据库或启动容器。

```powershell
$env:HUICODE_SERVER_ENV = 'development'
$env:HUICODE_DATABASE_URL = 'postgresql+asyncpg://demo:demo@localhost:5432/huicode'
$env:HUICODE_REDIS_URL = 'redis://localhost:6379/0'
$env:HUICODE_JWT_SECRET = & .\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(32))'
$env:HUICODE_PROJECT_ROOT = (Get-Location).Path
$env:HUICODE_CORS_ORIGINS = 'http://localhost:5173'
.\.venv\Scripts\python.exe -m uvicorn huicode.server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

另开 PowerShell 查看：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
curl.exe -i http://127.0.0.1:8000/health/ready
```

预期：live 返回 200 和 alive；无数据库/Redis 时 ready 返回 503，dependencies 标记 unavailable。依赖都连通时 ready 返回 200。响应头 X-Request-ID 可用于关联应用请求记录。关闭默认 Uvicorn access log 是为了避免记录含敏感参数的原始 URL；后续统一部署日志配置。

在服务所在终端按 Ctrl+C 退出，lifespan 会关闭 Redis 客户端和数据库连接池。
