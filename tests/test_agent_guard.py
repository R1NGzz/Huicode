import unittest

from huicode.agent_guard import is_production_source_path, is_test_path, is_verification_command


class AgentGuardHelperTests(unittest.TestCase):
    def test_classifies_source_and_test_paths(self) -> None:
        self.assertTrue(is_production_source_path("src\\service.py"))
        self.assertTrue(is_test_path("tests/test_service.py"))
        self.assertTrue(is_test_path("src/service_test.go"))
        self.assertFalse(is_production_source_path("tests/test_service.py"))
        self.assertFalse(is_production_source_path(".huicode/sessions/session.jsonl"))
        self.assertFalse(is_production_source_path("README.md"))

    def test_recognizes_tests_and_static_checks(self) -> None:
        self.assertTrue(is_verification_command("uv run pytest tests/test_service.py -q"))
        self.assertTrue(is_verification_command("python -m py_compile src/service.py"))
        self.assertTrue(is_verification_command("python -c \"import package\""))
        self.assertTrue(is_verification_command("cargo check"))
        self.assertFalse(is_verification_command("python -c \"print('inspect')\""))


if __name__ == "__main__":
    unittest.main()
