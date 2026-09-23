"""敏感值识别规则与文本脱敏。

**这是全仓库唯一一份"什么算密钥"的定义。** memory 模块直接用 `scrub_secrets`，
服务端用 `huicode/server/runtime/scrubber.py` 的 `SecretScrubber`（它复用这里的
`SECRET_PATTERNS`）。两处各写一套规则，迟早会出现"记忆里脱敏了、事件里没有"。

标记固定为 `[REDACTED]`，不带种类：既有的 memory 输出就是这个格式，改它没有收益。

**两条让规则可重复施加的约束**（踩过才知道）：

1. 每条带值的规则，前缀之后都要有 `(?!\\[REDACTED\\])` 负向前瞻。否则第二次施加时
   会把 `[REDACTED]` 再当成一个值匹配掉，而值字符集里排除了 `]`，结果是留下一个
   孤立的 `]`（`api_key=[REDACTED]]`）。
2. 环境变量那条**不能加 `(?i)`**。加了之后 `[A-Z0-9_]` 也匹配小写，`token_count=5`
   会被当成敏感环境变量脱敏掉。

**取舍：宁可多脱敏。** 规则里有意包含一些会误伤的形态（任何 `token: xxx` 都会被脱敏，
哪怕那个值不是密钥）。漏脱敏的代价是密钥落库，误脱敏的代价只是日志难读一点。
"""

from __future__ import annotations

import re

MARKER = "[REDACTED]"

# 已经脱敏过的地方不要再匹配一次。
_NOT_YET_REDACTED = r"(?!\[REDACTED\])"

# 敏感键名。作为**词尾段**匹配，前面可以有下划线分隔的前缀（`openai_api_key`、
# `HUICODE_JWT_SECRET`）。
#
# 为什么不用"前面是空白或行首"来界定：那样匹配不到 `openai_api_key`。
# 为什么不用"任意词字符前缀"：那样 `max_tokens=4096` 会因为以 `token` 结尾而被
# 误脱敏，而这是 LLM 配置里最常见的键之一。要求前缀以 `_`/`-` 分段就能把
# `max_tokens` 排除掉（`tokens` ≠ `token`）。
_KEY_NAMES = (
    r"authorization|proxy-authorization|x-api-key|api[_-]?key|apikey|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|"
    r"jwt[_-]?secret|secret|token|password|passwd|pwd|cookie|set-cookie|private[_-]?key"
)
_KEY_TOKEN = r"(?:[A-Za-z0-9]+[_\-])*(?:" + _KEY_NAMES + r")"

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 私钥整块。必须排在最前：块内第一行是 `-----BEGIN ... KEY-----`，
    # 先匹配整块，否则内部内容会被后面的规则零散替换，留下残片。
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    # 连接串里的密码：scheme://user:password@host
    re.compile(r"(?i)([a-z][a-z0-9+.\-]*://[^:/\s@]+:)[^@/\s]+(?=@)"),
    # Authorization: <方案> <凭据>。**方案关键字要一起吃掉**：只吃凭据的话，
    # 剩下的 `Authorization: Bearer` 会被后面的兜底规则再把 `Bearer` 当成一个值
    # 脱敏一次，变成 `Authorization: [REDACTED] [REDACTED]`。
    re.compile(
        r"(?i)(authorization\s*[:=]\s*)"
        + _NOT_YET_REDACTED + r"(?:[A-Za-z]+\s+)?[^\s,;\"']+"
    ),
    # 单独出现的 `Bearer <凭据>`（例如日志里只贴了这一行）
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/=]{12,}"),
    # 已知供应商的密钥形态
    re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),             # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),       # Google API key
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),  # Slack
    # JWT：三段点分 base64url
    re.compile(r"\beyJ[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}"),
    # 敏感环境变量赋值。**故意不加 (?i)**：环境变量名按约定全大写，加了忽略大小写
    # 之后 `token_count=5` 这种普通变量也会被误伤。
    re.compile(
        r"(?m)^([ \t]*(?:export[ \t]+)?[A-Z][A-Z0-9_]*"
        r"(?:SECRET|TOKEN|KEY|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*[ \t]*=[ \t]*)"
        + _NOT_YET_REDACTED + r".+$"
    ),
    # 通用 key: value 赋值，兜底。值里不允许出现空白与引号，避免吃掉后续结构；
    # 也不允许以 `[` 开头，避免把 JSON 数组或标记本身当成值。
    re.compile(
        r"(?i)((?:^|[^\w])" + _KEY_TOKEN + r"\s*[\"']?\s*[:=]\s*[\"']?)"
        + _NOT_YET_REDACTED + r"[^\s,;\"'}\]]+"
    ),
)


# 判定"这个键名本身是不是敏感"用的全匹配版本，与文本规则共用 _KEY_TOKEN。
# 结构化脱敏（例如 `{"password": {...}}`）需要按键判断，而不是按值的长相判断。
SENSITIVE_KEY_RE = re.compile(r"(?i)^" + _KEY_TOKEN + r"$")


def scrub_secrets(text: str) -> str:
    """对文本做脱敏。空值和非字符串原样返回。"""
    if not isinstance(text, str) or not text:
        return text
    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(_replace_secret, result)
    return result


def _replace_secret(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}{MARKER}"
    return MARKER
