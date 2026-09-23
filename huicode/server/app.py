"""应用工厂及 HTTP 边界；不在 API 进程中启动任务 Worker。"""

import json
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from huicode.server.api.auth import router as auth_router
from huicode.server.api.errors import ApiError
from huicode.server.api.health import router
from huicode.server.api.projects import router as projects_router
from huicode.server.api.workspaces import router as workspaces_router
from huicode.server.config import ServerSettings, load_server_settings
from huicode.server.domain.errors import DomainError
from huicode.server.health import DependencyHealth
from huicode.server.runtime.scrubber import SecretScrubber, install_log_scrubbing
from huicode.server.runtime.scrubbing import configure as configure_scrubber

logger = logging.getLogger("huicode.server.requests")


class RequestContextMiddleware:
    """纯 ASGI 包装，避免缓冲未来的 SSE 响应。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.monotonic()
        status = 500
        response_started = False

        async def send_with_id(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"] = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode("ascii"))]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            if response_started:
                # 流已开始，不能伪造第二个 HTTP 响应。
                raise
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error", "message": "服务内部错误"}, "request_id": request_id},
            )
            await response(scope, receive, send_with_id)
        finally:
            # 仅记录路由模板，不记录任意路径、查询参数、请求体或异常原文。
            route = scope.get("route")
            logger.info(json.dumps({
                "event": "http_request", "request_id": request_id,
                "route": getattr(route, "path", "unmatched"),
                "status": status, "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }))


def create_app(settings: ServerSettings | None = None, *, health_factory=DependencyHealth) -> FastAPI:
    settings = settings if settings is not None else load_server_settings()

    @asynccontextmanager
    async def lifespan(app):
        health = health_factory(settings)
        app.state.health = health
        await health.open()
        # 业务路由通过 app.state.database 取连接池，而不是自己再建一个。
        # health_factory 可被测试替换，替换品不一定持有 database，故用 getattr。
        app.state.database = getattr(health, "database", None)
        try:
            yield
        finally:
            await health.close()

    app = FastAPI(title="HuiCode Studio", debug=False, lifespan=lifespan)
    app.state.settings = settings
    logger.setLevel(settings.log_level)

    # 脱敏器按配置装一次：事件与审计的写入路径都从进程级取它。
    # 日志过滤器要**逐个 logger 装**——logger 上的 filter 不随记录向上传播。
    scrubber = SecretScrubber.from_settings(settings)
    configure_scrubber(scrubber)
    for name in ("huicode.server", "huicode.server.requests", "huicode.server.events"):
        install_log_scrubbing(name, scrubber)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        # message 是写给用户的；再过一道脱敏，防止调用方把配置值拼进消息（C58）。
        return JSONResponse(
            status_code=exc.status_code, headers=exc.headers,
            content={
                "error": {"code": exc.code, "message": scrubber.scrub_text(exc.message)},
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        # 领域错误自带稳定 code 与 status_code；message 面向用户，不含内部细节。
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": scrubber.scrub_text(exc.message)},
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, headers=exc.headers, content={
            "error": {"code": f"http_{exc.status_code}", "message": "请求无法处理"},
            "request_id": request.state.request_id,
        })

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={
            "error": {"code": "validation_error", "message": "请求参数不符合接口要求"},
            "request_id": request.state.request_id,
        })

    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(workspaces_router)
    app.include_router(projects_router)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )
    return app
