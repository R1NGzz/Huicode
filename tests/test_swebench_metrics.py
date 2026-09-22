import json
import tempfile
import unittest
from pathlib import Path

from scripts.swebench_metrics import summarize_run


class SwebenchMetricsTests(unittest.TestCase):
    def test_summarizes_log_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            reports = root / "reports" / "case-1"
            logs.mkdir()
            reports.mkdir(parents=True)
            (logs / "case-1.log").write_text(
                "tokens: total_tokens=100, prompt_tokens=80, completion_tokens=20\n"
                "  ✗ Bash(pytest tests/test_x.py) - 命令退出码为 1\n"
                "已达到最大迭代次数 50，停止执行。\n"
                "AGENT_DONE id=case-1 exit=0 seconds=12.5 changed=1\n",
                encoding="utf-8",
            )
            (reports / "report.json").write_text(
                json.dumps(
                    {
                        "instance_id": "case-1",
                        "resolved": False,
                        "FAIL_TO_PASS": {"success": [], "failure": ["target"]},
                        "PASS_TO_PASS": {"success": ["old"], "failure": ["regression"]},
                    }
                ),
                encoding="utf-8",
            )

            result = summarize_run(logs, root / "reports")

            task = result["tasks"][0]
            self.assertEqual(task["instance_id"], "case-1")
            self.assertFalse(task["resolved"])
            self.assertEqual(task["prompt_tokens"], 80)
            self.assertEqual(task["completion_tokens"], 20)
            self.assertEqual(task["duration_seconds"], 12.5)
            self.assertTrue(task["max_iteration_reached"])
            self.assertEqual(task["tool_failures"], 1)
            self.assertEqual(task["test_commands"], 1)
            self.assertEqual(task["pass_to_pass_failure"], 1)

    def test_missing_report_is_unknown_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            (logs / "empty-case.log").write_text(
                "AGENT_DONE id=empty-case exit=0 seconds=1.0\n", encoding="utf-8"
            )

            result = summarize_run(logs, root / "reports")

            self.assertIsNone(result["tasks"][0]["resolved"])
            self.assertEqual(result["summary"]["unknown_reports"], 1)

    def test_reads_jsonl_agent_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            (logs / "case.jsonl").write_text(
                "tokens: total_tokens=12, prompt_tokens=9, completion_tokens=3\n"
                "AGENT_DONE id=case exit=0 seconds=2.0\n",
                encoding="utf-8",
            )

            result = summarize_run(logs, root / "reports")

            task = result["tasks"][0]
            self.assertEqual(task["instance_id"], "case")
            self.assertEqual(task["prompt_tokens"], 9)
            self.assertEqual(task["completion_tokens"], 3)

    def test_writes_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            (logs / "case.log").write_text("AGENT_DONE id=case exit=0 seconds=1\n", encoding="utf-8")
            output = root / "out" / "metrics.json"

            summarize_run(logs, root / "reports", output)

            self.assertTrue(output.exists())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["summary"]["task_count"], 1)


if __name__ == "__main__":
    unittest.main()
