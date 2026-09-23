"""T6 路径解析与越界防护（checklist C46–C48）。

链接逃逸用**真实链接**验证，不是 mock：Windows 上优先建 junction（不需要管理员
权限），POSIX 上建符号链接。建不出来时跳过而不是假装通过——一个"永远跳过"的
安全测试比没有测试更危险，所以跳过时会说明原因。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from huicode.server.runtime.workspace_resolver import (
    MAX_RELATIVE_PATH_LENGTH,
    PathViolation,
    WorkspacePathResolver,
)


def _make_link(link: Path, target: Path) -> bool:
    """建立指向 target 的链接，失败返回 False。"""
    try:
        if sys.platform == "win32":
            # junction 不需要管理员权限或开发者模式，符号链接需要。
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True, text=True,
            )
            return result.returncode == 0 and link.exists()
        link.symlink_to(target, target_is_directory=True)
        return link.exists()
    except (OSError, NotImplementedError):
        return False


class ResolverLexicalTests(unittest.TestCase):
    """词法层：不碰文件系统就能拒绝的输入。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        (self.root / "demo").mkdir()
        self.resolver = WorkspacePathResolver(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_plain_relative_path(self):
        resolved = self.resolver.resolve_project_directory("demo")
        self.assertEqual(resolved, (self.root / "demo").resolve())

    def test_rejects_parent_traversal(self):
        for candidate in ("..", "../outside", "demo/../../outside", r"demo\..\..\x"):
            with self.subTest(candidate=candidate), self.assertRaises(PathViolation):
                self.resolver.resolve_project_directory(candidate)

    def test_rejects_absolute_paths_in_both_dialects(self):
        candidates = (
            "/etc/passwd",
            "\\Windows\\System32",
            "C:/Windows",
            "C:\\Windows",
            "c:demo",
            "//server/share",
            r"\\?\C:\Windows",
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(PathViolation):
                self.resolver.resolve_project_directory(candidate)

    def test_rejects_empty_and_control_characters(self):
        for candidate in ("", "   ", ".", "a\x00b"):
            with self.subTest(candidate=repr(candidate)), self.assertRaises(PathViolation):
                self.resolver.resolve_project_directory(candidate)

    def test_rejects_overlong_path(self):
        with self.assertRaises(PathViolation):
            self.resolver.resolve_project_directory("a" * (MAX_RELATIVE_PATH_LENGTH + 1))

    def test_rejects_windows_reserved_device_names(self):
        for candidate in ("con", "NUL", "com1", "aux.txt", "lpt9"):
            with self.subTest(candidate=candidate), self.assertRaises(PathViolation):
                self.resolver.resolve_project_directory(candidate)

    def test_resolver_rejects_filesystem_root_as_project_root(self):
        anchor = Path(self.root.anchor)
        with self.assertRaises(PathViolation):
            WorkspacePathResolver(anchor)

    def test_resolver_rejects_missing_root(self):
        with self.assertRaises(PathViolation):
            WorkspacePathResolver(Path(self.temp.name) / "does-not-exist")


class ResolverContainmentTests(unittest.TestCase):
    """解析层：路径文本合法，但链接可能把它带到外面去。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "root"
        self.root.mkdir()
        self.project = self.root / "demo"
        self.project.mkdir()
        self.outside = base / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")
        self.resolver = WorkspacePathResolver(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_allows_nonexistent_leaf_inside_project(self):
        """写一个新文件时叶子还不存在，必须允许。"""
        target = self.resolver.resolve_within(self.project, "sub/new.txt")
        self.assertTrue(str(target).startswith(str(self.project.resolve())))

    def test_link_escaping_project_is_rejected(self):
        link = self.project / "escape"
        if not _make_link(link, self.outside):
            self.skipTest("当前环境无法创建 junction/symlink（Windows 需要开发者模式或管理员）")

        # 链接本身在项目内，目标在项目外。叶子存在与不存在都要挡住：
        # 存在时 resolve() 展开链接；不存在时要检查最近的已存在祖先。
        for candidate in ("escape/secret.txt", "escape/brand-new.txt"):
            with self.subTest(candidate=candidate), self.assertRaises(PathViolation):
                self.resolver.resolve_within(self.project, candidate)

    def test_link_escaping_project_root_is_rejected(self):
        link = self.root / "linked"
        if not _make_link(link, self.outside):
            self.skipTest("当前环境无法创建 junction/symlink")

        with self.assertRaises(PathViolation):
            self.resolver.resolve_project_directory("linked")

    def test_assert_inside_flags_escaping_path(self):
        with self.assertRaises(PathViolation):
            self.resolver.assert_inside(self.project, self.outside / "secret.txt")

    def test_assert_inside_allows_contained_path(self):
        inside = self.project / "ok.txt"
        inside.write_text("ok", encoding="utf-8")
        self.resolver.assert_inside(self.project, inside)

    def test_sibling_with_shared_prefix_is_not_treated_as_inside(self):
        """`root-evil` 与 `root` 有共同前缀，但不是子目录。"""
        sibling = Path(self.temp.name) / "root-evil"
        sibling.mkdir()
        with self.assertRaises(PathViolation):
            self.resolver.assert_inside(self.root, sibling)


if __name__ == "__main__":
    unittest.main()
