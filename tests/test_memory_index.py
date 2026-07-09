import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.config import MemoryConfig
from huicode.memory.index import MemoryIndex
from huicode.memory.notes import NoteStore
from huicode.memory.types import MemoryNote


class MemoryIndexTests(unittest.TestCase):
    def test_rebuilds_index_with_sources_and_limits_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "work"
            home = root / "home"
            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                store = NoteStore(workspace)
                for index in range(20):
                    store.create_note(
                        MemoryNote(
                            note_id=f"mem-{index}",
                            scope="project",
                            category="project_knowledge",
                            title=f"Title {index}",
                            summary="x" * 80,
                            body="body",
                        )
                    )
                memory_index = MemoryIndex(
                    workspace,
                    MemoryConfig(enabled=True, index_max_lines=12, index_max_bytes=1000),
                    store,
                )
                result = memory_index.rebuild()
                text = memory_index.load_text()

        self.assertLessEqual(result.lines, 12)
        self.assertLessEqual(result.bytes, 1000)
        self.assertTrue(result.clipped)
        self.assertIn("source:", text)
        self.assertIn("Project Knowledge", text)

    def test_index_scrubs_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "work"
            home = Path(directory) / "home"
            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                store = NoteStore(workspace)
                store.create_note(
                    MemoryNote(
                        note_id="mem-secret",
                        scope="project",
                        category="reference",
                        title="Secret",
                        summary="token: abc123",
                        body="body",
                    )
                )
                text = MemoryIndex(workspace, MemoryConfig(enabled=True), store).load_text()

        self.assertNotIn("abc123", text)
        self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
