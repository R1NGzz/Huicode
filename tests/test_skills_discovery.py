import os
import tempfile
import unittest
from pathlib import Path

from huicode.skills.discovery import discover_skill_layer, fingerprint_skill_root


def skill_text(name: str, description: str = "desc") -> str:
    return f"""---
name: {name}
description: {description}
allowed_tools: []
mode: shared
---
Do {name}: {{{{args}}}}
"""


class SkillDiscoveryTests(unittest.TestCase):
    def test_discovers_single_and_directory_skills_and_skips_bad_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.md").write_text(skill_text("one"), encoding="utf-8")
            package = root / "two"
            package.mkdir()
            (package / "SKILL.md").write_text(skill_text("two"), encoding="utf-8")
            (package / "reference.txt").write_text("secret helper", encoding="utf-8")
            (root / "bad.md").write_text("bad", encoding="utf-8")

            result = discover_skill_layer(root, "project")

        self.assertEqual(set(result.definitions), {"one", "two"})
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(len(result.warnings), 1)
        self.assertTrue(any(item.path.endswith("reference.txt") for item in result.fingerprint))

    def test_duplicate_name_invalidates_layer_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.md").write_text(skill_text("same"), encoding="utf-8")
            (root / "b.md").write_text(skill_text("same"), encoding="utf-8")

            result = discover_skill_layer(root, "user")

        self.assertEqual(result.definitions, {})
        self.assertEqual(result.skipped_count, 2)
        self.assertEqual(result.warnings[0].code, "duplicate_name")

    def test_auxiliary_file_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "pkg"
            package.mkdir()
            (package / "SKILL.md").write_text(skill_text("pkg"), encoding="utf-8")
            helper = package / "example.txt"
            helper.write_text("one", encoding="utf-8")
            before = fingerprint_skill_root(root, "project")
            helper.write_text("two-two", encoding="utf-8")
            after = fingerprint_skill_root(root, "project")

        self.assertNotEqual(before, after)

    def test_symlink_escape_is_skipped_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside) / "escape.md"
            target.write_text(skill_text("escape"), encoding="utf-8")
            link = root / "escape.md"
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("当前 Windows 环境不允许创建符号链接")

            result = discover_skill_layer(root, "project")

        self.assertNotIn("escape", result.definitions)
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
