import tempfile
import unittest
from pathlib import Path

from huicode.config import TeamConfig
from huicode.teams.mailbox import MailboxStore, NameRegistry
from huicode.teams.storage import TeamStore
from huicode.teams.types import TeamError, TeamRecord


class TeamMailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        record = TeamRecord("team-1", "demo", "main", "repo", "C:/repo", "main", "abc", "active", "now", "now")
        self.store = TeamStore(Path(self.temp.name), "demo", TeamConfig())
        self.store.initialize(record)
        self.registry = NameRegistry(("lead", "alice", "bob"))
        self.mailbox = MailboxStore(self.store, self.registry)

    def tearDown(self):
        self.temp.cleanup()

    def test_direct_broadcast_and_read(self):
        sent = self.mailbox.send("alice", ("bob",), "hello")
        inbox, warnings = self.mailbox.inbox("bob", unread_only=True)
        self.assertFalse(warnings)
        self.assertEqual(sent.id, inbox[0].id)
        self.mailbox.mark_read("bob", sent.id)
        self.assertFalse(self.mailbox.inbox("bob", unread_only=True)[0])
        broadcast = self.mailbox.broadcast("lead", "notice")
        self.assertEqual(("alice", "bob"), broadcast.recipients)

    def test_unknown_recipient_writes_nothing(self):
        with self.assertRaises(TeamError):
            self.mailbox.send("alice", ("missing",), "hello")
        self.assertFalse(self.store.paths.mailbox("bob").exists())


if __name__ == "__main__":
    unittest.main()
