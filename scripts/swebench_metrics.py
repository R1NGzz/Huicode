from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class EvalRunMetrics:
    instance_id: str
    resolved: bool | None
    fail_to_pass_success: int
    fail_to_pass_failure: int
    pass_to_pass_success: int
    pass_to_pass_failure: int
    prompt_tokens: int
    completion_tokens: int
    duration_seconds: float | None
    max_iteration_reached: bool
    tool_failures: int
    test_commands: int


_DONE_RE = re.compile(r"\bAGENT_DONE\s+id=(\S+)\s+exit=\d+\s+seconds=([0-9.]+)")
_TOKEN_RE = re.compile(
    r"total_tokens=(\d+),\s+prompt_tokens=(\d+),\s+completion_tokens=(\d+)"
)


def _log_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    paths = [*root.rglob("*.log"), *root.rglob("*.jsonl")]
    return sorted(set(paths))


def _report_files(root: Path) -> list[Path]:
    if root.is_file() and root.name == "report.json":
        return [root]
    return sorted(root.rglob("report.json")) if root.exists() else []


def _parse_log(path: Path) -> tuple[str, dict[str, object]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    done = _DONE_RE.search(text)
    instance_id = done.group(1) if done else path.stem
    duration = float(done.group(2)) if done else None
    prompt_tokens = 0
    completion_tokens = 0
    for match in _TOKEN_RE.finditer(text):
        prompt_tokens += int(match.group(2))
        completion_tokens += int(match.group(3))
    tool_failures = sum(1 for line in text.splitlines() if line.lstrip().startswith("✗"))
    test_commands = sum(
        1
        for line in text.splitlines()
        if "Bash(" in line and re.search(r"pytest|unittest|tox|ruff|mypy", line, re.I)
    )
    max_iteration = bool(
        re.search(r"已达到最大迭代次数|reached max iterations|stop_reason=max_iterations", text, re.I)
    )
    return instance_id, {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "duration_seconds": duration,
        "max_iteration_reached": max_iteration,
        "tool_failures": tool_failures,
        "test_commands": test_commands,
    }


def _count_tests(report: dict[str, object], group: str, result: str) -> int:
    value = report.get(group, {})
    if not isinstance(value, dict):
        return 0
    entries = value.get(result, [])
    return len(entries) if isinstance(entries, list) else 0


def _parse_report(path: Path) -> tuple[str, dict[str, object]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    instance_id = str(report.get("instance_id") or path.parent.name)
    return instance_id, {
        "resolved": report.get("resolved") if isinstance(report.get("resolved"), bool) else None,
        "fail_to_pass_success": _count_tests(report, "FAIL_TO_PASS", "success"),
        "fail_to_pass_failure": _count_tests(report, "FAIL_TO_PASS", "failure"),
        "pass_to_pass_success": _count_tests(report, "PASS_TO_PASS", "success"),
        "pass_to_pass_failure": _count_tests(report, "PASS_TO_PASS", "failure"),
    }


def summarize_run(
    agent_logs: Path,
    report_root: Path,
    output_path: Path | None = None,
) -> dict[str, object]:
    """Combine per-task Agent logs and harness reports into stable metrics."""
    by_id: dict[str, dict[str, object]] = {}
    for path in _log_files(agent_logs):
        instance_id, values = _parse_log(path)
        by_id.setdefault("" if not instance_id else instance_id, {}).update(values)
    for path in _report_files(report_root):
        instance_id, values = _parse_report(path)
        by_id.setdefault(instance_id, {}).update(values)

    tasks: list[EvalRunMetrics] = []
    for instance_id in sorted(by_id):
        values = by_id[instance_id]
        tasks.append(
            EvalRunMetrics(
                instance_id=instance_id,
                resolved=values.get("resolved"),
                fail_to_pass_success=int(values.get("fail_to_pass_success", 0)),
                fail_to_pass_failure=int(values.get("fail_to_pass_failure", 0)),
                pass_to_pass_success=int(values.get("pass_to_pass_success", 0)),
                pass_to_pass_failure=int(values.get("pass_to_pass_failure", 0)),
                prompt_tokens=int(values.get("prompt_tokens", 0)),
                completion_tokens=int(values.get("completion_tokens", 0)),
                duration_seconds=values.get("duration_seconds"),
                max_iteration_reached=bool(values.get("max_iteration_reached", False)),
                tool_failures=int(values.get("tool_failures", 0)),
                test_commands=int(values.get("test_commands", 0)),
            )
        )

    resolved = sum(task.resolved is True for task in tasks)
    result: dict[str, object] = {
        "tasks": [asdict(task) for task in tasks],
        "summary": {
            "task_count": len(tasks),
            "resolved": resolved,
            "resolved_rate": (resolved / len(tasks)) if tasks else 0.0,
            "unknown_reports": sum(task.resolved is None for task in tasks),
            "prompt_tokens": sum(task.prompt_tokens for task in tasks),
            "completion_tokens": sum(task.completion_tokens for task in tasks),
            "duration_seconds": sum(
                task.duration_seconds or 0.0 for task in tasks
            ),
            "max_iteration_tasks": sum(task.max_iteration_reached for task in tasks),
            "tool_failures": sum(task.tool_failures for task in tasks),
            "test_commands": sum(task.test_commands for task in tasks),
            "regression_tasks": sum(task.pass_to_pass_failure > 0 for task in tasks),
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="汇总 HuiCode SWE-bench Agent 日志和 harness 报告")
    parser.add_argument("--agent-logs", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.agent_logs.exists():
        print(f"Agent 日志目录不存在: {args.agent_logs}", file=sys.stderr)
        return 2
    if not args.reports.exists():
        print(f"harness 报告目录不存在: {args.reports}", file=sys.stderr)
        return 2
    result = summarize_run(args.agent_logs, args.reports, args.output)
    summary = result["summary"]
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
