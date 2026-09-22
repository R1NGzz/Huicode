"""需要真实 PostgreSQL / Redis 的集成测试。

默认跳过：这些用例依赖 docker 容器，不该让 `pytest tests` 在没有环境的机器上失败。
设置 HUICODE_TEST_DATABASE_URL 后启用，见 tests/integration/test_postgres_migrations.py。
"""
