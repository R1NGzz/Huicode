"""工作区、项目、会话、Run、审批、审计和用量的业务规则。

本包不依赖 FastAPI 请求对象：领域错误用 DomainError 子类表达，
由 app.py 的统一处理器映射成 HTTP 响应。
"""
