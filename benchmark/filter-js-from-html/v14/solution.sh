#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/filter.py
from __future__ import annotations

import re
import sys
from html import unescape
from pathlib import Path
from urllib.parse import unquote


BLOCKED_TAGS = ("script", "iframe", "object", "embed", "template")


def is_dangerous_url(value: str) -> bool:
    normalized = unescape(value).strip()
    while len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    normalized = normalized.replace("\x00", "")
    for _ in range(3):
        decoded = unquote(normalized)
        if decoded == normalized:
            break
        normalized = decoded
    normalized = re.sub(r"\s+", "", normalized).lower()
    return normalized.startswith((
        "javascript:",
        "vbscript:",
        "data:text/html",
        "data:application/xhtml+xml",
    ))


def strip_blocked_tags(html: str) -> str:
    for tag in BLOCKED_TAGS:
        pattern = re.compile(rf"<{tag}\b[^>]*>.*?</{tag}\s*>", re.IGNORECASE | re.DOTALL)
        html = pattern.sub("", html)
        self_closing = re.compile(rf"<{tag}\b[^>]*?/\s*>", re.IGNORECASE | re.DOTALL)
        html = self_closing.sub("", html)
    return html


def strip_event_handlers(html: str) -> str:
    pattern = re.compile(r"(?P<lead>\s+)on[a-zA-Z0-9:_-]+\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
    return pattern.sub("", html)


def sanitize_attribute_urls(html: str) -> str:
    attr_pattern = re.compile(
        r"(?P<lead>\s+)(?P<name>href|src|xlink:href|formaction|action|poster|background)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s>]+)",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        raw_value = match.group("value")
        if raw_value[:1] in {'"', "'"}:
            value = raw_value[1:-1]
        else:
            value = raw_value
        if is_dangerous_url(value):
            return ""
        return match.group(0)

    return attr_pattern.sub(replace, html)


def sanitize_meta_refresh(html: str) -> str:
    meta_pattern = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        http_equiv = re.search(r"http-equiv\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag, re.IGNORECASE)
        content = re.search(r"content\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag, re.IGNORECASE)
        if not http_equiv or not content:
            return tag

        http_equiv_value = next(group for group in http_equiv.groups()[1:] if group is not None)
        content_value = next(group for group in content.groups()[1:] if group is not None)
        if http_equiv_value.strip().lower() != "refresh":
            return tag

        parts = content_value.split(";", 1)
        if len(parts) != 2:
            return tag
        target = parts[1].split("=", 1)[-1].strip()
        if not is_dangerous_url(target):
            return tag

        content_pattern = re.compile(r"\s+content\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
        return content_pattern.sub("", tag, count=1)

    return meta_pattern.sub(replace, html)


def sanitize_html(html: str) -> str:
    html = strip_blocked_tags(html)
    html = strip_event_handlers(html)
    html = sanitize_attribute_urls(html)
    html = sanitize_meta_refresh(html)
    return html


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python /app/filter.py <html-path>")

    path = Path(sys.argv[1])
    html = path.read_text(encoding="utf-8")
    path.write_text(sanitize_html(html), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
