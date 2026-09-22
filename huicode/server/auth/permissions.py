"""工作区角色判断。

角色语义见 spec.md 与 plan.md：viewer 只读；member 可创建会话、发起低风险任务
和响应自己有权限的审批；admin 可管理项目、成员、审计和用量；owner 可删除或
转移工作区。

顺序满足包含关系（admin 能做 member 的事），所以用等级比较而不是逐个罗列。
**未知角色一律按最低权限处理**：将来数据库里出现一个拼错的角色名时，
默认拒绝比默认放行安全。
"""

from __future__ import annotations

ROLE_ORDER: dict[str, int] = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

ROLE_NAMES = tuple(ROLE_ORDER)


class PermissionDenied(Exception):
    """当前用户在目标工作区没有所需角色。"""


def role_rank(role: str) -> int:
    """未知角色返回 -1，比任何合法角色都低。"""
    return ROLE_ORDER.get(role, -1)


def has_at_least(role: str, required: str) -> bool:
    return role_rank(role) >= role_rank(required)


def ensure_at_least(role: str, required: str) -> None:
    if not has_at_least(role, required):
        raise PermissionDenied(f"需要 {required} 及以上权限")
