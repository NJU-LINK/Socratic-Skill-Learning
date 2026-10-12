#!/bin/bash
set -euo pipefail

mkdir -p /app

cat > /app/filter.py <<'PY'
import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


URL_ATTRS = {
    "href",
    "src",
    "action",
    "formaction",
    "xlink:href",
    "poster",
    "background",
    "data",
}

DROP_TAGS = {"script", "iframe", "frame", "object", "embed"}


def decode_repeatedly(value: str) -> str:
    current = value
    for _ in range(6):
        decoded = html.unescape(unquote(current))
        if decoded == current:
            break
        current = decoded
    return current


def normalize_for_scheme_check(value: str) -> str:
    decoded = decode_repeatedly(value)
    return re.sub(r"[\x00-\x20\x7f]+", "", decoded).lower()


def is_dangerous_url(value: str) -> bool:
    normalized = normalize_for_scheme_check(value)
    if normalized.startswith(("javascript:", "vbscript:")):
        return True
    if normalized.startswith("data:"):
        media_type = normalized[5:].split(",", 1)[0].split(";", 1)[0]
        return media_type in {
            "text/html",
            "application/xhtml+xml",
            "image/svg+xml",
            "text/xml",
        }
    return False


def has_dangerous_style(value: str) -> bool:
    normalized = normalize_for_scheme_check(value)
    return "expression(" in normalized or "url(javascript:" in normalized


def sanitize_meta(tag) -> None:
    if tag.name != "meta":
        return
    http_equiv = tag.get("http-equiv")
    if not isinstance(http_equiv, str):
        return
    if normalize_for_scheme_check(http_equiv) != "refresh":
        return
    content = tag.get("content", "")
    normalized = normalize_for_scheme_check(content)
    if "url=" not in normalized:
        return
    target = normalized.split("url=", 1)[1]
    if is_dangerous_url(target):
        tag.decompose()


def sanitize_tag(tag) -> None:
    if tag.name in DROP_TAGS:
        tag.decompose()
        return

    sanitize_meta(tag)
    if not tag.parent:
        return

    for attr_name in list(tag.attrs):
        attr_value = tag.attrs.get(attr_name)
        joined = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
        lowered = attr_name.lower()

        if lowered.startswith("on"):
            del tag.attrs[attr_name]
            continue

        if lowered == "srcdoc":
            del tag.attrs[attr_name]
            continue

        if lowered in URL_ATTRS and is_dangerous_url(joined):
            if tag.name == "base" and lowered == "href":
                del tag.attrs[attr_name]
                continue
            if lowered in {"href", "xlink:href"}:
                tag.attrs[attr_name] = "#"
            else:
                del tag.attrs[attr_name]
            continue

        if lowered == "style" and has_dangerous_style(joined):
            del tag.attrs[attr_name]


def sanitize_html(source: str) -> str:
    soup = BeautifulSoup(source, "html.parser")

    for tag in list(soup.find_all(True)):
        sanitize_tag(tag)

    return str(soup)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python /app/filter.py <html-file>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    sanitized = sanitize_html(original)
    path.write_text(sanitized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
