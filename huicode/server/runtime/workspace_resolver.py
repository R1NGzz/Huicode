"""项目路径解析与越界防护。

对应 checklist 的 C46–C48：`..`、绝对路径、编码变体、符号链接和 Windows junction
都不能把读写带出项目根目录。

**为什么不能只用字符串前缀判断。** `str(path).startswith(root)` 会被三类输入骗过：

1. `..` —— 字符串里没有可疑字符，但拼出来已经跳出目录。
2. 符号链接 / junction —— 路径文本完全在根目录内，链接指向根目录外。
3. 大小写与分隔符变体（Windows）—— `C:\\Root` 与 `c:/root/..` 文本不同，指向可以相同。

所以这里的顺序是：先做**词法检查**（拒绝绝对路径、盘符、UNC、`..`），再做
**解析后检查**（`Path.resolve()` 展开所有链接，再判断是否真的在根目录内）。
两步都不能省：词法检查挡住明显的越界并给出清晰错误，解析后检查挡住链接逃逸。

**写不存在的文件时，检查的是它最近的已存在祖先。** 否则 `root/link/new.txt` 里
`link` 指向外部时，叶子不存在就不会被 resolve 展开，检查会假通过。
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_RELATIVE_PATH_LENGTH = 1024

# Windows 保留设备名。用作文件名时会被解释成设备而不是文件。
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class PathViolation(Exception):
    """路径形态非法或解析后越出允许的根目录。

    异常消息只描述原因，**不带宿主机绝对路径**——错误响应不应泄露目录结构
    （C58 要求错误响应不返回敏感配置原文）。
    """


def _normalised(path: Path) -> str:
    """用于比较的规范形式；Windows 下统一大小写与分隔符。"""
    return os.path.normcase(os.path.abspath(str(path)))


def _is_within(candidate: Path, base: Path) -> bool:
    candidate_text = _normalised(candidate)
    base_text = _normalised(base)
    return candidate_text == base_text or candidate_text.startswith(base_text + os.sep)


def _validate_relative(relative_path: str) -> PurePosixPath:
    """词法检查。返回 POSIX 形式的相对路径，供后续拼接。"""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise PathViolation("路径不能为空")
    if len(relative_path) > MAX_RELATIVE_PATH_LENGTH:
        raise PathViolation("路径过长")
    if "\x00" in relative_path:
        raise PathViolation("路径包含非法字符")

    # Windows 与 POSIX 两种解释都要挡：请求可能来自任意客户端。
    windows = PureWindowsPath(relative_path)
    if relative_path.startswith("/") or relative_path.startswith("\\"):
        raise PathViolation("不接受绝对路径")
    if windows.is_absolute() or windows.drive or _DRIVE_PREFIX.match(relative_path):
        raise PathViolation("不接受绝对路径或盘符路径")
    if windows.root or windows.anchor:
        raise PathViolation("不接受绝对路径")
    if PurePosixPath(relative_path).is_absolute():
        raise PathViolation("不接受绝对路径")

    parts = []
    for raw in re.split(r"[\\/]+", relative_path):
        if raw in ("", "."):
            continue
        if raw == "..":
            # 不做"归一化后仍在内部就算合法"的宽容处理：拒绝更可预测，
            # 也让日志里的尝试痕迹更清楚。
            raise PathViolation("不接受 .. 路径段")
        stem = raw.split(".")[0].lower()
        if stem in _WINDOWS_RESERVED:
            raise PathViolation("路径包含保留设备名")
        parts.append(raw)

    if not parts:
        raise PathViolation("路径不能为空")
    return PurePosixPath(*parts)


def _resolve_existing_ancestor(path: Path) -> Path:
    """解析掉所有链接，对不存在的叶子用最近的已存在祖先。

    直接对不存在的路径调用 `resolve(strict=True)` 会抛错；而 `resolve()` 的
    非严格模式虽然也会展开父级链接，但这里显式写出来是为了让意图可见：
    **检查的锚点是真实存在的那个祖先目录**。
    """
    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    try:
        resolved_ancestor = probe.resolve(strict=True)
    except OSError as exc:
        raise PathViolation("路径无法解析") from exc
    # 把未存在的后缀接回解析后的祖先上。
    try:
        suffix = path.relative_to(probe)
    except ValueError:
        raise PathViolation("路径无法解析") from None
    return resolved_ancestor / suffix


class WorkspacePathResolver:
    """把项目相对路径解析成绝对路径，并保证结果不越出配置的项目根目录。"""

    def __init__(self, project_root: Path):
        try:
            root = Path(project_root).resolve(strict=True)
        except OSError as exc:
            raise PathViolation("项目根目录不存在或不可访问") from exc
        if not root.is_dir():
            raise PathViolation("项目根目录不是目录")
        if root == Path(root.anchor):
            # 根目录不能是文件系统根：否则"越界检查"等于没有检查。
            raise PathViolation("项目根目录不能是文件系统根")
        self.project_root = root

    # -- 公开接口 -------------------------------------------------------

    def resolve_project_directory(self, relative_path: str, *, must_exist: bool = True) -> Path:
        """解析项目在配置根目录下的相对路径，要求它确实位于根目录内。"""
        relative = _validate_relative(relative_path)
        candidate = self.project_root.joinpath(*relative.parts)
        resolved = _resolve_existing_ancestor(candidate) if not candidate.exists() else candidate.resolve(strict=True)

        if not _is_within(resolved, self.project_root):
            raise PathViolation("项目路径超出服务端配置的项目根目录")
        if must_exist and not resolved.is_dir():
            raise PathViolation("项目目录不存在或不是目录")
        return resolved

    def resolve_within(self, base: Path, relative_path: str) -> Path:
        """在给定目录内解析一个相对路径；叶子可以不存在（用于创建文件）。"""
        relative = _validate_relative(relative_path)
        base_resolved = base.resolve(strict=True)
        candidate = base_resolved.joinpath(*relative.parts)
        resolved = _resolve_existing_ancestor(candidate)

        if not _is_within(resolved, base_resolved):
            raise PathViolation("路径超出项目目录")
        return resolved

    def assert_inside(self, base: Path, candidate: Path) -> None:
        """断言一个已存在的路径位于 base 之内（例如工具返回的路径）。"""
        resolved = _resolve_existing_ancestor(Path(candidate))
        if not _is_within(resolved, Path(base).resolve(strict=True)):
            raise PathViolation("路径超出项目目录")
