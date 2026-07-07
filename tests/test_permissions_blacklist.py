import unittest

from huicode.permissions.blacklist import check_dangerous_command


class PermissionBlacklistTests(unittest.TestCase):
    def test_blocks_representative_dangerous_commands(self) -> None:
        commands = [
            "rm -rf /",
            "rm -rf *",
            "git reset --hard",
            "git clean -fdx",
            "format C:",
            "diskpart",
            "mkfs.ext4 /dev/sda",
            "chmod -R 777 .",
            "takeown /f C:\\Windows /r",
        ]
        for command in commands:
            with self.subTest(command=command):
                decision = check_dangerous_command(command)
                self.assertIsNotNone(decision)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.source, "blacklist")

    def test_allows_ordinary_commands(self) -> None:
        for command in ["git status", "dir", "python -m unittest", "git diff -- README.md"]:
            with self.subTest(command=command):
                self.assertIsNone(check_dangerous_command(command))


if __name__ == "__main__":
    unittest.main()

