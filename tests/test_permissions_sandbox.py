import os
import tempfile
import unittest
from pathlib import Path

from huicode.permissions.sandbox import extract_tool_paths, resolve_workspace_path


class PermissionSandboxTests(unittest.TestCase):
    def test_resolves_paths_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = resolve_workspace_path(workspace, "src/../README.md")

        self.assertEqual(path, (workspace / "README.md").resolve())

    def test_rejects_parent_and_absolute_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            outside = workspace.parent / "outside.txt"

            with self.assertRaises(ValueError):
                resolve_workspace_path(workspace, "../outside.txt")
            with self.assertRaises(ValueError):
                resolve_workspace_path(workspace, outside)

    def test_rejects_symlink_escape_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            outside = Path(directory) / "outside"
            workspace.mkdir()
            outside.mkdir()
            link = workspace / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            with self.assertRaises(ValueError):
                resolve_workspace_path(workspace, "link/secret.txt")

    def test_extract_tool_paths(self) -> None:
        self.assertEqual(extract_tool_paths("Read", {"path": "README.md"}), ["README.md"])
        self.assertEqual(extract_tool_paths("Find", {"pattern": "src/**/*.py"}), ["src/**/*.py"])
        self.assertEqual(extract_tool_paths("Search", {"pattern": "TODO"}), [])
        self.assertEqual(extract_tool_paths("Search", {"pattern": "TODO", "glob": "../*.py"}), ["../*.py"])


if __name__ == "__main__":
    unittest.main()

