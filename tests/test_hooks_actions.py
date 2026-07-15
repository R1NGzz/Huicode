import json
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from huicode.hooks.actions import HookActionExecutor
from huicode.hooks.types import CommandAction, HookRule, HttpAction, PromptAction, SubagentAction


class RecordingHandler(BaseHTTPRequestHandler):
    requests = []
    response_status = 200
    response_body = b"{}"

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).requests.append((self.command, dict(self.headers), body))
        self.send_response(type(self).response_status)
        self.end_headers()
        self.wfile.write(type(self).response_body)

    do_PUT = do_POST

    def log_message(self, format, *args):  # noqa: A002, ANN001
        return


class HookActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.executor = HookActionExecutor(self.workspace)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_command_receives_utf8_json_and_distinguishes_denial(self) -> None:
        script = "import json,sys; d=json.load(sys.stdin); print(d['turn']['input'])"
        rule = HookRule("ok", "turn_start", CommandAction(command=sys.executable, args=("-c", script)))
        result = self.executor.execute(rule, {"turn": {"input": "中文"}})
        self.assertEqual(result.status, "success")
        self.assertIn("中文", result.data["stdout"])

        deny_script = "import sys; print('policy denied', file=sys.stderr); raise SystemExit(2)"
        deny_rule = HookRule("deny", "tool_before", CommandAction(command=sys.executable, args=("-c", deny_script)))
        denied = self.executor.execute(deny_rule, {"tool": {"name": "Write"}})
        self.assertEqual(denied.status, "denied")
        self.assertIn("policy denied", denied.deny_reason)

    def test_command_timeout_blacklist_and_cwd_sandbox(self) -> None:
        timeout_rule = HookRule(
            "slow",
            "turn_start",
            CommandAction(command=sys.executable, args=("-c", "import time; time.sleep(2)")),
            timeout_seconds=1,
        )
        self.assertEqual(self.executor.execute(timeout_rule, {}).status, "timeout")
        dangerous = HookRule("danger", "turn_start", CommandAction(command="git reset --hard"))
        self.assertEqual(self.executor.execute(dangerous, {}).status, "failed")
        outside = HookRule("outside", "turn_start", CommandAction(command="echo ok", cwd=".."))
        self.assertEqual(self.executor.execute(outside, {}).status, "failed")
        nonzero = HookRule(
            "nonzero",
            "turn_start",
            CommandAction(command=sys.executable, args=("-c", "raise SystemExit(3)")),
        )
        self.assertEqual(self.executor.execute(nonzero, {}).status, "failed")
        missing = HookRule("missing", "turn_start", CommandAction(command="huicode-command-that-does-not-exist"))
        self.assertEqual(self.executor.execute(missing, {}).status, "failed")

    def test_http_prompt_and_subagent(self) -> None:
        RecordingHandler.requests = []
        RecordingHandler.response_body = b'{"decision":"deny","reason":"remote policy"}'
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/hook"
            rule = HookRule("http", "tool_before", HttpAction(url=url))
            result = self.executor.execute(rule, {"tool": {"name": "Write"}})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(result.status, "denied")
        self.assertEqual(json.loads(RecordingHandler.requests[0][2])["tool"]["name"], "Write")

        RecordingHandler.response_body = b"not-json"
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            bad = self.executor.execute(
                HookRule("bad-http", "turn_start", HttpAction(url=f"http://127.0.0.1:{server.server_port}", method="PUT")),
                {"turn": {"input": "x"}},
            )
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(bad.status, "failed")
        self.assertEqual(RecordingHandler.requests[-1][0], "PUT")

        disconnected = self.executor.execute(
            HookRule("offline", "turn_start", HttpAction(url="http://127.0.0.1:1"), timeout_seconds=1),
            {"turn": {"input": "x"}},
        )
        self.assertEqual(disconnected.status, "failed")

        injected = []
        prompt_rule = HookRule("prompt", "turn_start", PromptAction(content="任务 {{turn.input}}", scope="turn"))
        prompt_result = self.executor.execute(prompt_rule, {"turn": {"input": "检查"}}, injected.append)
        self.assertEqual(prompt_result.status, "success")
        self.assertEqual(injected[0].content, "任务 检查")

        sub_rule = HookRule("sub", "turn_start", SubagentAction(task="review"))
        self.assertEqual(self.executor.execute(sub_rule, {}).status, "skipped")


if __name__ == "__main__":
    unittest.main()
