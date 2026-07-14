import tempfile
import unittest
from pathlib import Path

from huicode.skills.catalog import SkillCatalogBuilder, SkillConfigError
from huicode.tools.registry import create_default_registry


def write_skill(root: Path, filename: str, name: str, description: str, tools=("Read",)) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tool_lines = "\n".join(f"  - {tool}" for tool in tools)
    (root / filename).write_text(
        f"""---
name: {name}
description: {description}
allowed_tools:
{tool_lines}
mode: shared
---
Run {name}
""",
        encoding="utf-8",
    )


class SkillCatalogTests(unittest.TestCase):
    def test_layer_priority_and_alias_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = {name: base / name for name in ("builtin", "user", "project")}
            write_skill(roots["builtin"], "same.md", "same", "builtin")
            write_skill(roots["user"], "same.md", "same", "user")
            write_skill(roots["project"], "same.md", "same", "project", ("Glob",))

            snapshot = SkillCatalogBuilder(roots, create_default_registry(base)).build()

        self.assertEqual(snapshot.definitions["same"].description, "project")
        self.assertEqual(snapshot.definitions["same"].allowed_tools, ("Find",))
        self.assertEqual(snapshot.overridden_count, 2)

    def test_unknown_tool_and_reserved_command_fail_globally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = {name: base / name for name in ("builtin", "user", "project")}
            write_skill(roots["project"], "bad.md", "bad", "bad", ("Missing",))
            builder = SkillCatalogBuilder(roots, create_default_registry(base))
            with self.assertRaisesRegex(SkillConfigError, "Missing"):
                builder.build()

            (roots["project"] / "bad.md").unlink()
            write_skill(roots["project"], "help.md", "help", "conflict")
            builder = SkillCatalogBuilder(roots, create_default_registry(base), {"help"})
            with self.assertRaisesRegex(SkillConfigError, "冲突"):
                builder.build()


if __name__ == "__main__":
    unittest.main()
