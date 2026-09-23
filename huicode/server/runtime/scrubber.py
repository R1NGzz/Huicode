"""统一脱敏入口（checklist C55–C58）。

规则来自 `huicode/memory/scrub.py`——全仓库只有那一份"什么算密钥"的定义。
本模块在它之上补三件事：

1. **结构化脱敏。** 按**键名**判断（`{"password": ...}` 整个值抹掉），并递归处理
   嵌套结构。纯文本规则会被结构骗过：`{"password": {"v": "hunter2"}}` 里没有
   任何 `password=...` 形态的文本，但值确实是密码。
2. **已知值脱敏。** 把配置里真实存在的密钥（JWT secret、连接串里的密码）按**字面值**
   抹掉。这条兜住"形状不匹配任何规则"的密钥——包括将来换成的自定义格式。
3. **异常脱敏。** 异常消息常常把参数拼了进去，`scrub_exception` 只保留类型名和
   脱敏后的消息（T11 步骤 4：保留分类，不保留原值）。

`scrub_text` 是幂等的（见 memory/scrub.py 里的两条约束），所以重复施加安全——
这条性质被 store 和审计两条写入路径依赖。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from huicode.memory.scrub import MARKER, SENSITIVE_KEY_RE, scrub_secrets
from huicode.server.events.types import RuntimeEvent

# 比这短的"已知密钥"不按字面值替换：太短的值会在正常文本里到处命中，
# 把日志糊成一片 [REDACTED] 反而没人看。
MIN_KNOWN_SECRET_LENGTH = 8
MAX_DEPTH = 12


def _url_password(value: str) -> str | None:
    """取连接串里的密码部分；没有则返回 None。"""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return parsed.password or None


class SecretScrubber:
    def __init__(self, known_secrets: Iterable[str] = (), *, marker: str = MARKER):
        self.marker = marker
        # 长的排前面：短的若是长的前缀，先替换短的会在长值里留下残片。
        self._known = tuple(sorted(
            {
                secret for secret in known_secrets
                if isinstance(secret, str) and len(secret) >= MIN_KNOWN_SECRET_LENGTH
            },
            key=len, reverse=True,
        ))

    @classmethod
    def from_settings(cls, settings) -> "SecretScrubber":
        """从服务端配置里取真实密钥。

        只取密码部分而不是整条连接串：整条抹掉会让"连不上数据库"这类错误信息
        失去主机名和库名，排查时反而更难。
        """
        secrets: list[str] = [settings.jwt_secret]
        for url in (settings.database_url, settings.redis_url):
            password = _url_password(url)
            if password:
                secrets.append(password)
        return cls(secrets)

    # -- 公开接口 -------------------------------------------------------

    def scrub_text(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            return value
        result = scrub_secrets(value)
        for secret in self._known:
            if secret in result:
                result = result.replace(secret, self.marker)
        return result

    def scrub(self, value: Any, _depth: int = 0) -> Any:
        """递归脱敏任意 JSON 形状的数据。"""
        if _depth > MAX_DEPTH:
            # 深到不正常的嵌套：不再往下走，整个换成标记。
            return self.marker
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, Mapping):
            return {key: self._scrub_mapping_value(key, item, _depth) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(item, _depth + 1) for item in value]
        if isinstance(value, (bytes, bytearray)):
            # 二进制内容解不出文本，不做猜测：不原样保留。
            return self.marker
        return value

    def scrub_payload(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        """事件与审计载荷的入口。非字典输入返回空字典而不是原样透传。"""
        if not isinstance(payload, Mapping):
            return {}
        return self.scrub(dict(payload))

    def scrub_event(self, event: RuntimeEvent) -> RuntimeEvent:
        """返回脱敏后的副本。事件是 frozen 的，不改原对象。"""
        return replace(event, payload=self.scrub_payload(event.payload))

    def scrub_exception(self, error: BaseException) -> str:
        """类型名 + 脱敏后的消息。保留分类，不保留原值。"""
        name = type(error).__name__
        try:
            message = str(error)
        except Exception:
            return name
        return f"{name}: {self.scrub_text(message)}" if message else name

    # -- 内部 -----------------------------------------------------------

    def _scrub_mapping_value(self, key: Any, value: Any, depth: int) -> Any:
        if isinstance(key, str) and SENSITIVE_KEY_RE.match(key.strip()):
            # 键名本身就是敏感名：整个值抹掉，**不管它长什么样**。
            # 这一步覆盖了 `{"password": {"v": "..."}}` 这类纯文本规则看不穿的结构。
            return self.marker
        return self.scrub(value, depth + 1)


class SecretScrubFilter(logging.Filter):
    """给日志记录做脱敏的过滤器（C55）。

    装在 logger 上，覆盖"将来有人往日志里塞了请求体或异常原文"的情况——
    当前服务端的请求日志只记路由、状态和耗时，本身不含用户内容，但那是一时的，
    过滤器是长期的。
    """

    def __init__(self, scrubber: SecretScrubber):
        super().__init__()
        self.scrubber = scrubber

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # 格式化失败不该让日志丢掉。
            return True
        scrubbed = self.scrubber.scrub_text(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def install_log_scrubbing(logger_name: str, scrubber: SecretScrubber) -> None:
    """幂等地给某一个 logger 装上脱敏过滤器。

    **注意：logger 上的过滤器不会随记录向上传播。** `huicode.server.requests`
    产生的记录会冒泡到 `huicode.server` 的 handler，但**不会**经过
    `huicode.server` 这个 logger 自己的 filter——filter 只在记录直接经过该 logger
    时生效。所以每个会记日志的 logger 都要单独装，不能只装父级。
    """
    target = logging.getLogger(logger_name)
    for existing in target.filters:
        if isinstance(existing, SecretScrubFilter):
            return
    target.addFilter(SecretScrubFilter(scrubber))
