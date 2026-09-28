"""集成测试：把真实的组件接起来跑，而不是各自打桩。

这里有两种：

1. **需要真实 PostgreSQL / Redis 的**（迁移、并发追加、租约）。默认跳过——依赖
   docker 容器，不该让 `pytest tests` 在没有环境的机器上失败。设置
   HUICODE_TEST_DATABASE_URL 后启用，见 tests/integration/test_postgres_migrations.py。
2. **不需要外部依赖、但集成的是真实组件的**，例如 test_permission_bridge.py
   （真实工具注册表 + 真实权限引擎 + 真实临时工作目录）。这些**不设 skip**，
   `pytest tests` 一定跑得到——把它们挂在环境变量后面等于平时不跑。

"集成"说的是**被测对象**把几个真实部件连在了一起，不是"需要外部服务"。
"""
