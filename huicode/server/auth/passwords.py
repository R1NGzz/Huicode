"""密码哈希。只保存哈希，任何地方都不记录或返回密码原文。"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# 默认参数（argon2id、按当前硬件选定的时间/内存成本）够用；
# 调参属于运维决定，这里不写死具体数值。
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


class PasswordPolicyError(ValueError):
    """密码不满足最低要求。异常只说明原因，不回显密码。"""


def validate_password_policy(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"密码至少需要 {MIN_PASSWORD_LENGTH} 个字符")
    if len(password) > 1024:
        # 上限不是为了安全，是为了不让超长输入把哈希成本变成拒绝服务。
        raise PasswordPolicyError("密码过长")


def hash_password(password: str) -> str:
    validate_password_policy(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """校验失败一律返回 False，不区分"哈希损坏"和"密码不对"。

    区分这两者会给攻击者一个探测口：能判断某个邮箱是否真的注册过。
    """
    if not isinstance(password, str) or not password:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """哈希参数是否需要随实现默认值升级；登录成功后可据此静默重算。"""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
