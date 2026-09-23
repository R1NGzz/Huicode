"""进程级脱敏器。

事件存储与审计写入都要在落库前脱敏，但它们拿不到 `ServerSettings`。所以用一个
进程级实例：`create_app` 时按配置装上，测试里可以替换。

**为什么不是把 scrubber 当参数一层层传下去。** 那样"是否脱敏"就变成了一个可以被
忘记传的东西，而忘记传的后果是密钥直接落库——这类默认值必须是"忘了也安全"，
而不是"忘了就泄露"。进程级可变状态有它的代价（测试之间会互相影响），
所以 `configure` 只应由应用启动和测试调用。
"""

from __future__ import annotations

from huicode.server.runtime.scrubber import SecretScrubber

_scrubber: SecretScrubber = SecretScrubber()


def get_scrubber() -> SecretScrubber:
    return _scrubber


def configure(scrubber: SecretScrubber) -> None:
    """替换进程级脱敏器。应用启动时按配置调用。"""
    global _scrubber
    _scrubber = scrubber


def reset() -> None:
    """恢复成"只有规则、没有已知密钥"的默认实例。测试用。"""
    global _scrubber
    _scrubber = SecretScrubber()
