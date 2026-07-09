import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.memory.notes import NoteStore
from huicode.memory.types import MemoryNote


class MemoryNoteTests(unittest.TestCase):
    def test_create_list_update_delete_and_scope_separation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "work"
            home = root / "home"
            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                store = NoteStore(workspace)
                project_path = store.create_note(
                    MemoryNote(
                        note_id="mem-project",
                        scope="project",
                        category="project_knowledge",
                        title="Project",
                        summary="Uses Python",
                        body="Body",
                    )
                )
                user_path = store.create_note(
                    MemoryNote(
                        note_id="mem-user",
                        scope="user",
                        category="preference",
                        title="Preference",
                        summary="Likes concise answers",
                        body="Body",
                    )
                )

                self.assertIn(".huicode", project_path.as_posix())
                self.assertIn("home", user_path.as_posix())
                self.assertEqual(len(store.list_notes("project")), 1)
                self.assertEqual(len(store.list_notes("user")), 1)

                store.update_note("mem-project", {"summary": "Uses Python 3"})
                self.assertEqual(store.list_notes("project")[0].summary, "Uses Python 3")
                self.assertTrue(store.delete_note("mem-user"))
                self.assertEqual(store.list_notes("user"), [])

    def test_secret_is_scrubbed_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "work"
            home = Path(directory) / "home"
            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                store = NoteStore(workspace)
                path = store.create_note(
                    MemoryNote(
                        note_id="mem-secret",
                        scope="project",
                        category="reference",
                        title="Token",
                        summary="Authorization: Bearer super-secret",
                        body="api_key: key-secret",
                    )
                )
                text = path.read_text(encoding="utf-8")

        self.assertNotIn("super-secret", text)
        self.assertNotIn("key-secret", text)
        self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
