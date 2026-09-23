"""领域错误。

每个子类带一个稳定的 ``code`` 和 ``status_code``，由 app.py 的处理器统一成
``{"error": {"code", "message"}, "request_id"}``（C62 要求稳定错误码）。

放在 domain 而不是 api 里，是为了让业务层不必 import FastAPI——plan.md 明确要求
domain 不依赖请求对象。message 是写给用户看的，不含内部路径或异常原文。
"""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidProjectPath(DomainError):
    status_code = 400
    code = "invalid_project_path"


class DuplicateProjectName(DomainError):
    status_code = 409
    code = "project_name_taken"


class ArchivedProject(DomainError):
    status_code = 409
    code = "project_archived"


class InvalidName(DomainError):
    status_code = 422
    code = "invalid_name"
