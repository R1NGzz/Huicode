import tempfile
import unittest
from pathlib import Path

from huicode.agent import batch_tool_calls
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolContext, ToolResult
from huicode.tools.executor import execute_tool_call
from huicode.tools.registry import ToolRegistry, create_default_registry


class BrokenTool:
    name = "Broken"
    description = "故意抛异常的测试工具"
    parameters = {"type": "object", "properties": {}}

    def run(self, args, context):
        raise RuntimeError("boom")


class SystemTool:
    name = "System"
    description = "system"
    parameters = {"type": "object", "properties": {}}
    side_effect = False

    def run(self, args, context):
        return ToolResult.success({}, "ok")


class RegistryTests(unittest.TestCase):
    def test_default_registry_has_six_tools_and_specs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = create_default_registry(Path(directory))

        names = {tool.name for tool in registry.list()}
        self.assertEqual(names, {"Read", "Write", "Edit", "Bash", "Find", "Search"})
        self.assertIs(registry.get("Glob"), registry.get("Find"))
        specs = registry.to_specs()
        self.assertEqual(len(specs), 6)
        self.assertTrue(all(spec.name and spec.description and spec.parameters for spec in specs))
        self.assertEqual([spec.name for spec in specs[:3]], ["Read", "Find", "Search"])
        self.assertGreater([spec.name for spec in specs].index("Bash"), [spec.name for spec in specs].index("Search"))
        self.assertIn("优先使用本工具", registry.get("Find").description)
        self.assertIn("优先使用本工具", registry.get("Search").description)
        self.assertFalse(registry.is_side_effect("Read"))
        self.assertTrue(registry.is_side_effect("Write"))

    def test_can_filter_specs_and_resolve_alias(self) -> None:
        registry = create_default_registry(Path.cwd())

        specs = registry.to_specs({"Read", "Glob", "Search"})

        self.assertEqual({spec.name for spec in specs}, {"Read", "Find", "Search"})
        self.assertEqual(registry.resolve_name("Glob"), "Find")

    def test_system_tool_survives_filters(self) -> None:
        registry = create_default_registry(Path.cwd())
        registry.register(SystemTool(), system=True)

        names = {spec.name for spec in registry.to_specs(set())}

        self.assertEqual(names, {"System"})
        self.assertEqual(registry.system_tool_names(), frozenset({"System"}))
        self.assertNotIn("System", registry.ordinary_tool_names())

    def test_unknown_tool_returns_structured_error(self) -> None:
        result = execute_tool_call(
            ToolRegistry(),
            ToolCall(id="1", name="Missing", arguments={}),
            ToolContext(workspace=Path.cwd()),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "unknown_tool")

    def test_tool_exception_is_wrapped(self) -> None:
        registry = ToolRegistry()
        registry.register(BrokenTool())
        result = execute_tool_call(
            registry,
            ToolCall(id="1", name="Broken", arguments={}),
            ToolContext(workspace=Path.cwd()),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "tool_exception")

    def test_batch_tool_calls_groups_read_and_side_effect_tools(self) -> None:
        registry = create_default_registry(Path.cwd())
        calls = [
            ToolCall(id="1", name="Read", arguments={"path": "README.md"}),
            ToolCall(id="2", name="Write", arguments={"path": "a.txt", "content": "x"}),
            ToolCall(id="3", name="Glob", arguments={"pattern": "*.py"}),
            ToolCall(id="4", name="Bash", arguments={"command": "dir"}),
        ]

        batch = batch_tool_calls(calls, registry)

        self.assertEqual([call.name for call in batch.parallel_read_calls], ["Read", "Glob"])
        self.assertEqual([call.name for call in batch.serial_calls], ["Write", "Bash"])


if __name__ == "__main__":
    unittest.main()
