from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: str

    def json(self) -> dict[str, Any]:
        return json.loads(self.data)


class APIError(RuntimeError):
    pass


def post_sse(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int = 120,
) -> Iterator[SSEEvent]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": "HuiCode/0.1",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **headers,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            yield from iter_sse_events(response)
    except HTTPError as exc:
        detail = _format_http_error_detail(exc.read().decode("utf-8", errors="replace"))
        raise APIError(f"API 请求失败: HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise APIError(f"无法连接 API: {exc.reason}") from exc


def iter_sse_events(lines: Any) -> Iterator[SSEEvent]:
    event_name: str | None = None
    data_lines: list[str] = []

    for raw_line in lines:
        line = _decode_line(raw_line)
        if line == "":
            if data_lines:
                yield SSEEvent(event=event_name, data="\n".join(data_lines))
            event_name = None
            data_lines = []
            continue

        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())

    if data_lines:
        yield SSEEvent(event=event_name, data="\n".join(data_lines))


def _decode_line(raw_line: bytes | str) -> str:
    if isinstance(raw_line, bytes):
        return raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
    return raw_line.rstrip("\r\n")


def _format_http_error_detail(detail: str, limit: int = 600) -> str:
    text = detail.strip()
    if _looks_like_html(text):
        title = _extract_html_title(text)
        plain = _html_to_text(text)
        if "Cloudflare" in plain or "cloudflare" in plain:
            prefix = "上游服务返回 Cloudflare 访问限制页面"
            if title:
                prefix += f"（{title}）"
            prefix += "。请确认三方 API 提供的是可供程序访问的 OpenAI/Anthropic 兼容接口。"
            return prefix
        text = title or plain
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _looks_like_html(text: str) -> bool:
    lowered = text[:200].lower()
    return "<html" in lowered or "<!doctype html" in lowered


def _extract_html_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _html_to_text(match.group(1))


def _html_to_text(text: str) -> str:
    text = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())
