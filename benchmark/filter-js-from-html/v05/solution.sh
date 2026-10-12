#!/bin/bash
set -euo pipefail

mkdir -p /app

cat <<'PY' > /app/filter.py
#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii
import html
import re
import sys
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup


URL_ATTRS = {
    "action",
    "data",
    "formaction",
    "href",
    "poster",
    "src",
    "xlink:href",
}

FORBIDDEN_TAGS = {"script"}
STYLE_DANGERS = (
    "expression(",
    "behavior:",
    "url(javascript:",
    "url(data:text/html",
    "url(data:image/svg+xml",
)


def strip_controls(value: str) -> str:
    return "".join(ch for ch in value if ch >= " " or ch in "\t\n\r")


def recursive_unquote(value: str, rounds: int = 3) -> str:
    current = value
    for _ in range(rounds):
        decoded = urllib.parse.unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def normalize_url(value: str) -> str:
    current = html.unescape(strip_controls(value))
    current = recursive_unquote(current)
    current = re.sub(r"[\x00-\x20]+", "", current)
    return current.lower()


def data_url_is_unsafe(value: str) -> bool:
    normalized = normalize_url(value)
    if not normalized.startswith("data:"):
        return False

    header, _, payload = normalized.partition(",")
    mediatype = header[5:]
    if ";base64" in mediatype:
        mediatype = mediatype.split(";base64", 1)[0]
    mediatype = mediatype or "text/plain"

    if mediatype.startswith(("text/html", "image/svg+xml", "application/xhtml+xml", "application/xml", "text/xml")):
        return True

    if ";base64" in header:
        try:
            decoded = base64.b64decode(payload, validate=False).decode("utf-8", errors="ignore").lower()
        except (binascii.Error, ValueError):
            return False
        return any(token in decoded for token in ("<script", "<svg", "javascript:", "onload=", "onerror="))

    return any(token in payload for token in ("<script", "<svg", "javascript:"))


def url_is_unsafe(value: str) -> bool:
    normalized = normalize_url(value)
    return (
        normalized.startswith("javascript:")
        or normalized.startswith("vbscript:")
        or data_url_is_unsafe(value)
    )


def meta_refresh_is_unsafe(value: str) -> bool:
    decoded = recursive_unquote(html.unescape(value))
    match = re.search(r"url\s*=\s*([^;]+)", decoded, flags=re.IGNORECASE)
    if not match:
        return False
    return url_is_unsafe(match.group(1).strip(" \t\n\r\"'"))


def style_is_unsafe(value: str) -> bool:
    normalized = normalize_url(value)
    return any(token in normalized for token in STYLE_DANGERS)


def strip_malformed_script_blocks(source: str) -> str:
    cleaned = re.sub(
        r"(?is)<+\s*script\b[^>]*>.*?<+\s*/\s*script\s*>",
        "",
        source,
    )
    cleaned = re.sub(r"(?is)<+\s*/?\s*script\b[^>]*>", "", cleaned)
    return cleaned


def sanitize_html(source: str) -> str:
    soup = BeautifulSoup(strip_malformed_script_blocks(source), "html.parser")

    for tag in list(soup.find_all(True)):
        name = tag.name.lower() if tag.name else ""
        if name in FORBIDDEN_TAGS:
            tag.decompose()
            continue

        attrs = list(tag.attrs.items())
        for attr_name, attr_value in attrs:
            attr_key = attr_name.lower()
            if attr_key.startswith("on"):
                del tag.attrs[attr_name]
                continue

            if attr_key == "srcdoc":
                del tag.attrs[attr_name]
                continue

            value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)

            if attr_key in URL_ATTRS and url_is_unsafe(value):
                del tag.attrs[attr_name]
                continue

            if attr_key == "style" and style_is_unsafe(value):
                del tag.attrs[attr_name]
                continue

            if name == "meta" and attr_key == "content" and meta_refresh_is_unsafe(value):
                tag.decompose()
                break

        if tag.parent is None:
            continue

        if name in {"iframe", "object", "embed"}:
            tag.decompose()

    return str(soup)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: filter.py <html-file>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8", errors="ignore")
    sanitized = sanitize_html(original)
    path.write_text(sanitized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
