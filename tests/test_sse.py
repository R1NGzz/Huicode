import ssl
import unittest
from urllib.error import URLError
from unittest.mock import patch

from huicode.sse import APIError, _format_http_error_detail, iter_sse_events, post_sse


class FakeResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    def __iter__(self):  # noqa: ANN204
        return iter(self.lines)


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

    def test_retries_connection_before_response(self) -> None:
        eof = URLError(ssl.SSLEOFError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"))
        response = FakeResponse([b"data: ok\n", b"\n"])

        with patch("huicode.sse.urlopen", side_effect=[eof, response]) as mocked_urlopen:
            events = list(
                post_sse(
                    "https://example.test/messages",
                    headers={"x-api-key": "key"},
                    payload={"stream": True},
                    max_retries=1,
                    retry_delay_seconds=0,
                )
            )

        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(events[0].data, "ok")

    def test_formats_tls_eof_after_retry_exhausted(self) -> None:
        eof = URLError(ssl.SSLEOFError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"))

        with patch("huicode.sse.urlopen", side_effect=eof):
            with self.assertRaisesRegex(APIError, "TLS 连接被提前关闭"):
                list(
                    post_sse(
                        "https://example.test/messages",
                        headers={"x-api-key": "key"},
                        payload={"stream": True},
                        max_retries=0,
                    )
                )


if __name__ == "__main__":
    unittest.main()
