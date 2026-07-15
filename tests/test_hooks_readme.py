import re
import tempfile
import unittest
from pathlib import Path

import yaml

from huicode.hooks.config import HookConfigPaths, load_hook_catalog


class HookReadmeTests(unittest.TestCase):
    def test_hook_yaml_example_uses_current_configuration_schema(self) -> None:
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Hook 系统", 1)[1].split("\n## ", 1)[0]
        match = re.search(r"```yaml\s+(.*?)```", section, re.DOTALL)
        self.assertIsNotNone(match)
        parsed = yaml.safe_load(match.group(1))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = load_hook_catalog(
                HookConfigPaths(root / "user.yaml", root / "project.yaml"),
                parsed["hooks"],
            )
        self.assertEqual(catalog.effective_count, 4)


if __name__ == "__main__":
    unittest.main()
