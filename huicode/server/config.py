"""服务端配置边界：显式加载，失败时只报告字段名。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class ServerConfigError(ValueError):
    """配置不满足启动条件。异常不得包含配置原值。"""


@dataclass(frozen=True)
class RuntimeLimits:
    max_run_seconds: int = 1800
    max_tool_seconds: int = 120
    max_shell_seconds: int = 60
    max_iterations: int = 50
    max_tool_calls: int = 100
    max_output_bytes: int = 1048576


@dataclass(frozen=True)
class ServerSettings:
    environment: str
    database_url: str = field(repr=False)
    redis_url: str = field(repr=False)
    jwt_secret: str = field(repr=False)
    project_root: Path
    cors_origins: tuple[str, ...]
    log_level: str
    limits: RuntimeLimits


def _error(name: str, reason: str) -> ServerConfigError:
    return ServerConfigError(f"{name}: {reason}")


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise _error(name, "必须显式配置")
    return value


def _service_url(env: Mapping[str, str], name: str, schemes: set[str]) -> str:
    value = _required(env, name)
    valid = False
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in schemes
            and bool(parsed.hostname)
            and not parsed.fragment
            and not any(char.isspace() for char in value)
            and (parsed.port is None or parsed.port > 0)
        )
        if name == "HUICODE_DATABASE_URL":
            valid = valid and bool(parsed.path.strip("/"))
    except ValueError:
        # 在 except 外抛出安全异常，避免异常上下文保留原始 URL。
        pass
    if not valid:
        raise _error(name, "服务 URL 格式无效或协议不支持")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default)).strip()
    if not raw.isascii() or not raw.isdigit() or len(raw) > 9:
        raise _error(name, "必须是正整数")
    value = int(raw)
    if value <= 0:
        raise _error(name, "必须是正整数")
    return value


def _origins(raw: str, production: bool) -> tuple[str, ...]:
    origins = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    for origin in origins:
        valid = False
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme in ({"https"} if production else {"http", "https"})
                and bool(parsed.hostname)
                and "*" not in parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and not any(char.isspace() for char in origin)
                and (parsed.port is None or parsed.port > 0)
            )
        except ValueError:
            pass
        if not valid:
            raise _error("HUICODE_CORS_ORIGINS", "必须为明确的来源；生产跨域来源要求 HTTPS")
    return origins


def load_server_settings(environ: Mapping[str, str] | None = None) -> ServerSettings:
    """从显式映射或进程环境构造配置，不自动加载 .env 或创建目录。"""
    env = os.environ if environ is None else environ
    environment = env.get("HUICODE_SERVER_ENV", "development").strip()
    if environment not in {"development", "test", "production"}:
        raise _error("HUICODE_SERVER_ENV", "仅支持 development、test、production")
    database_url = _service_url(env, "HUICODE_DATABASE_URL", {"postgresql+asyncpg"})
    redis_url = _service_url(env, "HUICODE_REDIS_URL", {"redis", "rediss"})
    jwt_secret = _required(env, "HUICODE_JWT_SECRET")
    if len(jwt_secret.encode("utf-8")) < 32 or len(set(jwt_secret)) < 8:
        raise _error("HUICODE_JWT_SECRET", "需要至少 32 字节且非简单重复的随机密钥")
    root = Path(_required(env, "HUICODE_PROJECT_ROOT"))
    if not root.is_absolute():
        raise _error("HUICODE_PROJECT_ROOT", "必须为预先创建的绝对目录")
    resolved = None
    try:
        candidate = root.resolve(strict=True)
        if candidate.is_dir() and candidate != Path(candidate.anchor):
            resolved = candidate
    except (OSError, RuntimeError, ValueError):
        pass
    if resolved is None:
        raise _error("HUICODE_PROJECT_ROOT", "必须是存在的非文件系统根目录")
    log_level = env.get("HUICODE_LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise _error("HUICODE_LOG_LEVEL", "日志级别无效")
    defaults = RuntimeLimits()
    values = {
        name: _positive_int(env, f"HUICODE_{name.upper()}", getattr(defaults, name))
        for name in RuntimeLimits.__dataclass_fields__
    }
    limits = RuntimeLimits(**values)
    if not limits.max_shell_seconds <= limits.max_tool_seconds <= limits.max_run_seconds:
        raise _error("HUICODE_MAX_SHELL_SECONDS/HUICODE_MAX_TOOL_SECONDS/HUICODE_MAX_RUN_SECONDS", "时限应满足 Shell ≤ Tool ≤ Run")
    return ServerSettings(
        environment=environment,
        database_url=database_url,
        redis_url=redis_url,
        jwt_secret=jwt_secret,
        project_root=resolved,
        cors_origins=_origins(env.get("HUICODE_CORS_ORIGINS", ""), environment == "production"),
        log_level=log_level,
        limits=limits,
    )
