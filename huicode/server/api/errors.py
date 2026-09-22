"""稳定的 API 错误码。

C62 要求超时、取消、权限拒绝、路径违规、队列失败和 Provider 错误都有稳定错误码
和用户可读提示；C58 又要求错误响应不返回敏感配置原文。所以响应里的 message
由调用方给定、面向用户，而异常原文只进日志。

调用方抛 ApiError，由 app.py 注册的处理器统一成
``{"error": {"code", "message"}, "request_id"}``，与既有错误响应同形。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def unauthenticated(message: str = "需要登录") -> ApiError:
    return ApiError(
        401, "unauthenticated", message, headers={"WWW-Authenticate": "Bearer"},
    )


def invalid_credentials() -> ApiError:
    """登录失败。刻意不区分"邮箱不存在"和"密码错误"。"""
    return ApiError(401, "invalid_credentials", "邮箱或密码不正确")


def forbidden(message: str = "没有权限执行该操作") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "资源不存在") -> ApiError:
    """找不到与无权访问返回同一个错误，避免用状态码探测资源是否存在。"""
    return ApiError(404, "not_found", message)


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def error_response(request: Request, error: ApiError) -> JSONResponse:
    """把 ApiError 渲染成与全局处理器同形的响应。

    给"先写库、再返回错误"的接口用（例如刷新令牌被重放时要撤销整条链）。
    抛异常会让请求级事务回滚，那次写库就白做了；改为正常 return 这个响应，
    事务照常提交，而错误体与其它接口保持一致。
    """
    return JSONResponse(
        status_code=error.status_code,
        headers=error.headers,
        content={
            "error": {"code": error.code, "message": error.message},
            "request_id": getattr(request.state, "request_id", None),
        },
    )
