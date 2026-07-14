import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.skills.parser import (
    SkillDependencyError,
    SkillParseError,
    parse_skill_file,
    render_skill_body,
)


VALID = """---
name: review
description: Review code safely
allowed_tools:
  - Read
  - Glob
mode: isolated
history_messages: 12
model: alternate-model
---
Review this request: {{args}}
"""


class SkillParserTests(unittest.TestCase):
    def test_parses_frontmatter_and_renders_literal_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "review.md"
            entry.write_text(VALID, encoding="utf-8")

            definition = parse_skill_file(entry, root, "project")

        self.assertEqual(definition.name, "review")
        self.assertEqual(definition.allowed_tools, ("Read", "Glob"))
        self.assertEqual(definition.mode, "isolated")
        self.assertEqual(definition.history_messages, 12)
        self.assertEqual(definition.model, "alternate-model")
        self.assertEqual(render_skill_body(definition, "Focus {{x}}"), "Review this request: Focus {{x}}")

    def test_accepts_utf8_bom_from_windows_editors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "review.md"
            entry.write_text(VALID, encoding="utf-8-sig")

            definition = parse_skill_file(entry, root, "project")

        self.assertEqual(definition.name, "review")

    def test_rejects_invalid_documents(self) -> None:
        cases = {
            "no-frontmatter": "name: x",
            "bad-name": VALID.replace("name: review", "name: Review!"),
            "bad-tools": VALID.replace("allowed_tools:\n  - Read\n  - Glob", "allowed_tools: Read"),
            "bad-mode": VALID.replace("mode: isolated", "mode: background"),
            "bad-history": VALID.replace("history_messages: 12", "history_messages: -1"),
            "empty-body": VALID.split("---\n", 2)[0] + "---\n" + VALID.split("---\n", 2)[1] + "---\n",
            "unknown-field": VALID.replace("mode: isolated", "extra: true\nmode: isolated"),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in cases.items():
                with self.subTest(name=name):
                    entry = root / f"{name}.md"
                    entry.write_text(content, encoding="utf-8")
                    with self.assertRaises(SkillParseError):
                        parse_skill_file(entry, root, "project")

    def test_missing_yaml_dependency_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "review.md"
            entry.write_text(VALID, encoding="utf-8")
            with patch("huicode.skills.parser.yaml", None):
                with self.assertRaisesRegex(SkillDependencyError, "PyYAML"):
                    parse_skill_file(entry, root, "project")


if __name__ == "__main__":
    unittest.main()
