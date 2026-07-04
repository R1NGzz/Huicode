import unittest

from huicode.sse import _format_http_error_detail, iter_sse_events


class SSETests(unittest.TestCase):
    def test_parses_single_event(self) -> None:
        events = list(iter_sse_events([b"event: message\n", b"data: hello\n", b"\n"]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "message")
        self.assertEqual(events[0].data, "hello")

    def test_parses_multiline_data_and_comments(self) -> None:
        events = list(
            iter_sse_events(
                [
                    b": keepalive\n",
                    b"event: update\n",
                    b"data: line1\n",
                    b"data: line2\n",
                    b"\n",
                ]
            )
        )

        self.assertEqual(events[0].event, "update")
        self.assertEqual(events[0].data, "line1\nline2")

    def test_flushes_remaining_event_at_end(self) -> None:
        events = list(iter_sse_events(["data: tail\n"]))

        self.assertEqual(events[0].event, None)
        self.assertEqual(events[0].data, "tail")

    def test_formats_cloudflare_html_error(self) -> None:
        detail = _format_http_error_detail(
            "<!doctype html><html><head><title>Access denied | Cloudflare</title></head>"
            "<body><h1>Error 1010</h1><p>Cloudflare</p></body></html>"
        )

        self.assertIn("Cloudflare 访问限制页面", detail)
        self.assertIn("Access denied", detail)
        self.assertNotIn("<html", detail)


if __name__ == "__main__":
    unittest.main()
