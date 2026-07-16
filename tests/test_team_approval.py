import tempfile
import unittest
from pathlib import Path

from huicode.config import TeamConfig
from huicode.teams.approval import ApprovalGate
from huicode.teams.mailbox import MailboxStore, NameRegistry
from huicode.teams.storage import TeamStore
from huicode.teams.types import TeamError, TeamRecord


class TeamApprovalTests(unittest.TestCase):
    def test_structured_decision_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            record = TeamRecord("team-1", "demo", "main", "repo", "C:/repo", "main", "abc", "active", "now", "now")
            store = TeamStore(Path(temp), "demo", TeamConfig())
            store.initialize(record)
            mailbox = MailboxStore(store, NameRegistry(("lead", "alice")))
            gate = ApprovalGate(store, mailbox)
            request = gate.submit_plan("alice", "task-1", "read then edit")
            self.assertFalse(gate.allows_side_effect("alice", "task-1"))
            with self.assertRaises(TeamError):
                gate.decide("wrong", "allow")
            gate.decide(request.request_id, "allow")
            restored = ApprovalGate(store, mailbox)
            self.assertTrue(restored.allows_side_effect("alice", "task-1"))
            with self.assertRaises(TeamError):
                restored.decide(request.request_id, "allow")


if __name__ == "__main__":
    unittest.main()
