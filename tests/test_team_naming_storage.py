import tempfile
import unittest
from pathlib import Path

from huicode.config import TeamConfig
from huicode.teams.naming import team_path, validate_name
from huicode.teams.storage import TeamStore, read_jsonl
from huicode.teams.types import TeamError, TeamRecord


class TeamStorageTests(unittest.TestCase):
    def test_names_and_path_escape_are_rejected(self):
        for value in ("../x", "a/b", " a", "CON", ""):
            with self.subTest(value=value), self.assertRaises(TeamError):
                validate_name(value)

    def test_team_roundtrip_and_bad_jsonl_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = TeamRecord("team-1", "demo", "main", "repo", "C:/repo", "main", "abc", "active", "now", "now")
            store = TeamStore(root, "demo", TeamConfig())
            store.initialize(record)
            self.assertEqual(record, store.load_team())
            store.paths.events.write_text('{"ok": 1}\nnot-json\n{"ok": 2}\n', encoding="utf-8")
            rows, warnings = read_jsonl(store.paths.events)
            self.assertEqual(2, len(rows))
            self.assertEqual(1, len(warnings))
            self.assertEqual(root.resolve() / "demo", team_path(root, "demo"))


if __name__ == "__main__":
    unittest.main()
