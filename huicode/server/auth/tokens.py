"""access token 用 JWT，refresh token 用不透明随机串。

两者形态不同是有意的：

- **access token 是自包含 JWT**，因为它每次请求都要校验，服务端不该为它查库。
  代价是签发后无法单独撤销，所以有效期短（默认 15 分钟）。
- **refresh token 是不透明随机串**，因为 C16 要求"已注销的 refresh token 不能
  换取有效身份"。自包含令牌做不到撤销，必须落库；既然要查库，JWT 的自包含
  就没有价值，反而多一份签名密钥的暴露面。

刷新令牌的哈希用 SHA-256 而不是 argon2：它是 48 字节的密码学随机串，没有
"弱口令"可猜，不需要慢哈希；而每次刷新都要按哈希查一行，慢哈希会把延迟放大。
密码用 argon2、令牌用 SHA-256，是因为两者的威胁模型不同，不是因为偷懒。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=14)

_TOKEN_TYPE_ACCESS = "access"
_REFRESH_TOKEN_BYTES = 48


class TokenError(Exception):
    """令牌缺失、过期、签名错误或类型不符。

    异常消息固定，不携带令牌原文，也不区分具体失败原因——调用方统一按
    未认证处理，避免把"签名错误"和"已过期"的差别暴露给客户端。
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    secret: str, user_id: UUID, *, issued_at: datetime | None = None, ttl: timedelta = ACCESS_TOKEN_TTL,
) -> str:
    issued = issued_at or _now()
    payload = {
        "sub": str(user_id),
        "typ": _TOKEN_TYPE_ACCESS,
        "jti": uuid4().hex,
        "iat": int(issued.timestamp()),
        "exp": int((issued + ttl).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(secret: str, token: str) -> UUID:
    """校验签名与有效期，返回用户 id。任何问题都抛 TokenError。"""
    if not isinstance(token, str) or not token:
        raise TokenError("access token 无效")
    try:
        payload = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        raise TokenError("access token 无效") from None
    if payload.get("typ") != _TOKEN_TYPE_ACCESS:
        # 用 refresh token 冒充 access token 是最容易漏掉的一条。
        raise TokenError("access token 无效")
    try:
        return UUID(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise TokenError("access token 无效") from None


def generate_refresh_token() -> str:
    """返回交给客户端的原文；服务端只保存它的哈希。"""
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def hash_refresh_token(raw: str) -> str:
    if not isinstance(raw, str):
        raise TokenError("refresh token 无效")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_token_expiry(issued_at: datetime | None = None) -> datetime:
    return (issued_at or _now()) + REFRESH_TOKEN_TTL
