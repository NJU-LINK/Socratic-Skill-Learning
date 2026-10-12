#!/bin/bash
set -euo pipefail

target_dir="${TARGET_DIR:-/app}"
mkdir -p "$target_dir"

cat <<'PY' > "$target_dir/filter.py"
#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


DANGEROUS_TAGS = {
    "script",
    "iframe",
    "frame",
    "frameset",
    "object",
    "embed",
    "foreignobject",
    "base",
}

URL_ATTRS = {
    "href",
    "xlink:href",
    "src",
    "action",
    "formaction",
    "poster",
    "background",
    "data",
}

CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]+")
REFRESH_URL_RE = re.compile(r"(?:^|;)\s*url\s*=\s*([^;]+)", re.IGNORECASE)


def decode_layers(value: str) -> str:
    decoded = value
    for _ in range(3):
        next_value = html.unescape(unquote(decoded))
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def normalized_token(value: str) -> str:
    return CONTROL_OR_SPACE.sub("", decode_layers(value)).lower()


def is_dangerous_url(value: str) -> bool:
    token = normalized_token(value)
    if token.startswith(("javascript:", "vbscript:")):
        return True
    if token.startswith("data:"):
        metadata = token[5:].split(",", 1)[0]
        return any(
            marker in metadata
            for marker in ("text/html", "image/svg+xml", "application/xhtml+xml")
        )
    return False


def is_dangerous_style(value: str) -> bool:
    token = normalized_token(value)
    return any(
        marker in token
        for marker in (
            "expression(",
            "javascript:",
            "vbscript:",
            "data:text/html",
            "data:image/svg+xml",
        )
    )


def extract_refresh_target(value: str) -> str | None:
    match = REFRESH_URL_RE.search(decode_layers(value))
    if not match:
        return None
    return match.group(1).strip(" \t\r\n\"'")


def should_drop_animation(tag) -> bool:
    name = (tag.name or "").lower().split(":")[-1]
    if name not in {"animate", "set"}:
        return False

    attribute_name = tag.attrs.get("attributeName") or tag.attrs.get("attributename")
    if attribute_name and normalized_token(str(attribute_name)) in {"href", "xlink:href"}:
        return True

    for attr_name in ("to", "from", "values", "href", "xlink:href"):
        value = tag.attrs.get(attr_name)
        if value is not None and is_dangerous_url(str(value)):
            return True
    return False


def sanitize_html(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    for tag in list(soup.find_all(True)):
        tag_name = (tag.name or "").lower()
        local_name = tag_name.split(":")[-1]

        if local_name in DANGEROUS_TAGS or should_drop_animation(tag):
            tag.decompose()
            continue

        if local_name == "meta":
            http_equiv = normalized_token(str(tag.attrs.get("http-equiv", "")))
            content = str(tag.attrs.get("content", ""))
            refresh_target = extract_refresh_target(content)
            if http_equiv == "refresh" and refresh_target and is_dangerous_url(refresh_target):
                tag.decompose()
                continue

        if not tag.attrs:
            continue

        for attr_name in list(tag.attrs):
            attr_value = tag.attrs[attr_name]
            attr_text = " ".join(str(part) for part in attr_value) if isinstance(attr_value, list) else str(attr_value)
            lowered = attr_name.lower()
            local_attr = lowered.split(":")[-1]

            if lowered.startswith("on") or local_attr.startswith("on"):
                del tag.attrs[attr_name]
                continue

            if lowered == "srcdoc" or local_attr == "srcdoc":
                del tag.attrs[attr_name]
                continue

            if lowered == "style" and is_dangerous_style(attr_text):
                del tag.attrs[attr_name]
                continue

            if lowered in URL_ATTRS or local_attr in URL_ATTRS:
                if is_dangerous_url(attr_text):
                    del tag.attrs[attr_name]

    return str(soup)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: filter.py <html-file>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    path.write_text(sanitize_html(original), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x "$target_dir/filter.py"
