"""工具能力声明（checklist C49）。

现有工具只有一个布尔 `side_effect`，它回答不了"能不能写文件"和"会不会出网"的区别：
两者在策略上完全不同（前者在工作区内，后者出了这台机器）。所以这里把能力拆成五项，
由**工具自己声明**，而不是在别处维护一张名字到能力的映射表——映射表的问题是新工具
加进来时没有人会想起去更新它，而默认值就是"没有限制"。

**未声明 = 高风险。** 这是本模块唯一重要的默认值。声明写在工具类上时，新工具的作者
会被测试和代码审查推着去想清楚它到底能干什么；而"没写就按只读放行"会让一个新工具
在没人注意的情况下拿到写权限。两种默认值的代价不对称。

**能力名不认识也按高风险。** 例如将来声明了 `"filesystem_write"`（拼错了）——如果
忽略它，这个工具会被当成"只读"；如果保留它并判为高风险，最坏情况是多一次审批。
"""

from __future__ import annotations

from typing import Any

# 能力**词表**在 huicode/tools/base.py —— 工具要声明它，而工具不能反向依赖服务端。
# 这个模块只放**策略**：怎么由能力推出风险与是否放行。
from huicode.tools.base import (
    ALL_CAPABILITIES,
    EXTERNAL_SIDE_EFFECT,
    FILE_WRITE,
    NETWORK,
    READ,
    READ_ONLY_CAPABILITIES,
    SHELL,
)

__all__ = [
    "ALL_CAPABILITIES",
    "EXTERNAL_SIDE_EFFECT",
    "FILE_WRITE",
    "NETWORK",
    "READ",
    "READ_ONLY_CAPABILITIES",
    "SHELL",
    "capabilities_of",
    "is_declared",
    "is_read_only",
    "risk_of",
    "summarise",
]

_MEDIUM_CAPABILITIES: frozenset[str] = frozenset({FILE_WRITE, SHELL})
_HIGH_CAPABILITIES: frozenset[str] = frozenset({NETWORK, EXTERNAL_SIDE_EFFECT})

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

UNDECLARED_REASON = "工具未声明能力，按高风险处理"


def capabilities_of(tool: Any) -> frozenset[str] | None:
    """工具声明的能力。`None` 表示**没有声明**——注意它与"声明为空"等价处理。"""
    raw = getattr(tool, "capabilities", None)
    if raw is None:
        return None
    if isinstance(raw, str):
        # 声明成单个字符串是最容易犯的错（`capabilities = "read"` 会被逐字符拆开），
        # 这里把它当成一个名字，而不是一组字符。
        return frozenset({raw})
    try:
        return frozenset(str(item) for item in raw)
    except TypeError:
        return None


def is_declared(tool: Any) -> bool:
    caps = capabilities_of(tool)
    if caps is None or not caps:
        # 空集合不是"这个工具什么都不能干"，而是"没说"。工具不可能什么都不干。
        return False
    return not (caps - ALL_CAPABILITIES)


def risk_of(tool: Any) -> str:
    """按能力推风险。工具本身的风险等级由它**能做什么**决定，不由名字决定。"""
    caps = capabilities_of(tool)
    if caps is None or not caps:
        return RISK_HIGH
    if caps - ALL_CAPABILITIES:
        return RISK_HIGH
    if caps & _HIGH_CAPABILITIES:
        return RISK_HIGH
    if caps & _MEDIUM_CAPABILITIES:
        return RISK_MEDIUM
    return RISK_LOW


def is_read_only(tool: Any) -> bool:
    """Plan Mode 的判据。**未声明时返回 False**——不能因为没写就当成只读。"""
    caps = capabilities_of(tool)
    if caps is None or not caps:
        return False
    return caps <= READ_ONLY_CAPABILITIES


def summarise(tool: Any) -> dict[str, Any]:
    """给事件载荷用的能力摘要。用排序后的列表，方便前端展示与测试断言。"""
    caps = capabilities_of(tool)
    return {
        "declared": is_declared(tool),
        "capabilities": sorted(caps) if caps else [],
        "risk": risk_of(tool),
    }
