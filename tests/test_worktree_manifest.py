from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from huicode.worktrees.manifest import manifest_path, read_manifest, require_matching_manifest, write_manifest
from huicode.worktrees.types import WorktreeError, WorktreeIdentity


class WorktreeManifestTests(unittest.TestCase):
    def identity(self, root: Path) -> WorktreeIdentity:
        return WorktreeIdentity("repo", "task-1234abcd", "review", "a" * 40, "branch", root.resolve(), 1.5)

    def test_round_trip_and_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = self.identity(Path(directory))
            write_manifest(identity)
            self.assertEqual(read_manifest(identity.path), identity)
            with self.assertRaises(WorktreeError) as raised:
                require_matching_manifest(replace(identity, branch="other"))
            self.assertEqual(raised.exception.code, "manifest_mismatch")

    def test_rejects_bad_json_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = self.identity(Path(directory))
            path = manifest_path(identity.path)
            path.parent.mkdir(parents=True)
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(WorktreeError):
                read_manifest(identity.path)
            write_manifest(identity)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["version"] = 999
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(WorktreeError) as raised:
                read_manifest(identity.path)
            self.assertEqual(raised.exception.code, "manifest_version")
            payload["version"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(WorktreeError) as raised:
                read_manifest(identity.path)
            self.assertEqual(raised.exception.code, "manifest_invalid")


if __name__ == "__main__":
    unittest.main()
