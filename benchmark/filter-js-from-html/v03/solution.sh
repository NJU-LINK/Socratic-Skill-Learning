#!/bin/bash
set -euo pipefail

cat >/app/filter.py <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


DROP_TAGS = {
    "script",
    "iframe",
    "object",
    "embed",
}

URL_ATTRS = {
    "href",
    "src",
    "action",
    "formaction",
    "xlink:href",
    "poster",
    "data",
}

SAFE_DATA_IMAGE_TYPES = {
    "image/avif",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}


def decode_repeatedly(value: str) -> str:
    current = value
    for _ in range(4):
        decoded = html.unescape(unquote(current))
        if decoded == current:
            break
        current = decoded
    return current


def compact_for_scheme_checks(value: str) -> str:
    return re.sub(r"[\x00-\x20]+", "", value).strip().lower()


def is_dangerous_protocol(value: str) -> bool:
    normalized = compact_for_scheme_checks(decode_repeatedly(value))
    return normalized.startswith(("javascript:", "vbscript:"))


def is_dangerous_data_url(value: str, tag_name: str, attr_name: str) -> bool:
    normalized = compact_for_scheme_checks(decode_repeatedly(value))
    if not normalized.startswith("data:"):
        return False

    header = normalized[5:].split(",", 1)[0]
    media_type = header.split(";", 1)[0] or "text/plain"
    if tag_name == "img" and attr_name == "src" and media_type in SAFE_DATA_IMAGE_TYPES:
        return False
    return True


def is_dangerous_style(value: str) -> bool:
    normalized = compact_for_scheme_checks(decode_repeatedly(value))
    return any(
        marker in normalized
        for marker in (
            "expression(",
            "javascript:",
            "vbscript:",
            "data:text/html",
            "data:image/svg+xml",
        )
    )


def flatten_attr_value(value: object) -> str:
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value)


def sanitize_srcset(value: str, tag_name: str) -> str | None:
    kept = []
    for candidate in value.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        parts = candidate.split()
        url = parts[0]
        if is_dangerous_protocol(url) or is_dangerous_data_url(url, tag_name, "src"):
            continue
        kept.append(" ".join(parts))
    return ", ".join(kept) or None


def sanitize_meta_refresh(tag) -> bool:
    http_equiv = decode_repeatedly(flatten_attr_value(tag.get("http-equiv", ""))).strip().lower()
    if http_equiv != "refresh":
        return False

    content = flatten_attr_value(tag.get("content", ""))
    match = re.search(r";\s*url\s*=\s*(.*)$", content, flags=re.IGNORECASE)
    if not match:
        return False

    target = match.group(1).strip().strip('"\'')
    if is_dangerous_protocol(target) or is_dangerous_data_url(target, "meta", "content"):
        tag.decompose()
        return True

    return False


def sanitize_tag(tag) -> None:
    if tag.name in DROP_TAGS:
        tag.decompose()
        return

    if tag.name == "meta" and sanitize_meta_refresh(tag):
            return

    for attr_name in list(tag.attrs.keys()):
        lower_name = attr_name.lower()
        value = flatten_attr_value(tag.attrs[attr_name])

        if lower_name.startswith("on"):
            del tag.attrs[attr_name]
            continue

        if lower_name == "srcdoc":
            del tag.attrs[attr_name]
            continue

        if lower_name == "style" and is_dangerous_style(value):
            del tag.attrs[attr_name]
            continue

        if lower_name == "srcset":
            sanitized = sanitize_srcset(value, tag.name)
            if sanitized is None:
                del tag.attrs[attr_name]
            else:
                tag.attrs[attr_name] = sanitized
            continue

        if lower_name in URL_ATTRS and (
            is_dangerous_protocol(value) or is_dangerous_data_url(value, tag.name, lower_name)
        ):
            del tag.attrs[attr_name]


def sanitize_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    for tag in list(soup.find_all(True)):
        sanitize_tag(tag)
    return soup.decode(formatter="minimal")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: filter.py <html-file>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    path.write_text(sanitize_html(path.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
