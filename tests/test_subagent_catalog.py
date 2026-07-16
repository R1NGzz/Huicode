import tempfile
import unittest
from pathlib import Path

from huicode.config import SubagentConfig
from huicode.subagents.catalog import AgentCatalog, SubagentConfigError
from huicode.tools.registry import create_default_registry


def write_role(root: Path, name: str, *, model: str = "inherit", body: str = "Do work") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(
        f"""---
name: {name}
description: {name} role
allowed_tools: [Read, Find]
denied_tools: []
model: {model}
max_iterations: 10
permission_mode: strict
---
{body}
""",
        encoding="utf-8",
    )


class RolePrecedenceTests(unittest.TestCase):
    def test_four_layers_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = {name: (base / name,) for name in ("plugin", "builtin", "user", "project")}
            for source in roots:
                write_role(roots[source][0], "same", body=source)
            catalog = AgentCatalog(roots, create_default_registry(base), SubagentConfig())
            snapshot = catalog.initialize()
        self.assertEqual(catalog.get("same").source, "project")
        self.assertEqual(catalog.get("same").instructions, "project")
        self.assertEqual(snapshot.overridden_count, 3)


class RoleValidationTests(unittest.TestCase):
    def test_bad_yaml_is_skipped_but_unknown_tool_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            (root / "bad.md").write_text("---\nname: [\n---\nbody", encoding="utf-8")
            roots = {name: () for name in ("plugin", "builtin", "user")}
            roots["project"] = (root,)
            snapshot = AgentCatalog(roots, create_default_registry(base), SubagentConfig()).initialize()
            self.assertEqual(snapshot.skipped_count, 1)
            write_role(root, "unknown")
            text = (root / "unknown.md").read_text(encoding="utf-8").replace("[Read, Find]", "[NoSuch]")
            (root / "unknown.md").write_text(text, encoding="utf-8")
            with self.assertRaises(SubagentConfigError) as caught:
                AgentCatalog(roots, create_default_registry(base), SubagentConfig()).initialize()
        self.assertIn("NoSuch", str(caught.exception))

    def test_unmapped_model_alias_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            write_role(root, "fast", model="haiku")
            roots = {"plugin": (), "builtin": (), "user": (), "project": (root,)}
            with self.assertRaises(SubagentConfigError) as caught:
                AgentCatalog(roots, create_default_registry(base), SubagentConfig()).initialize()
        self.assertIn("model_aliases", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
