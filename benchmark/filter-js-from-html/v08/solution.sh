#!/bin/bash
set -euo pipefail

mkdir -p /app

cat <<'PY' >/app/filter.py
#!/usr/bin/env python3
import html
import re
import sys
from urllib.parse import unquote


WHOLE_BLOCK_PATTERNS = [
    re.compile(r"(?is)<\s*script\b[^>]*>.*?</\s*script\s*>") ,
    re.compile(r"(?is)<\s*iframe\b[^>]*>.*?</\s*iframe\s*>") ,
    re.compile(r"(?is)<\s*object\b[^>]*>.*?</\s*object\s*>") ,
]

LONE_DANGEROUS_TAG = re.compile(r"(?is)<\s*/?\s*(script|iframe|object|embed)\b[^>]*>")
TAG_RE = re.compile(r"(?is)<[^>]+>")
ATTR_RE = re.compile(
    r'''(?is)(\s+)([A-Za-z_:][-A-Za-z0-9_:.]*)(\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?'''
)

URL_ATTRS = {
    "href",
    "src",
    "action",
    "formaction",
    "xlink:href",
    "poster",
    "data",
    "srcdoc",
}

URL_LIST_ATTRS = {
    "srcset",
    "imagesrcset",
}


def decode_value(value: str) -> str:
    decoded = html.unescape(value)
    for _ in range(4):
        unquoted = unquote(decoded)
        if unquoted == decoded:
            break
        decoded = unquoted
    return decoded


def normalized_compact(value: str) -> str:
    decoded = decode_value(value)
    decoded = decoded.replace("\x00", "")
    decoded = re.sub(r"[\x00-\x20\x7f\u0085\u00a0]+", "", decoded)
    return decoded.lower()


def is_dangerous_url(value: str) -> bool:
    compact = normalized_compact(value)
    return compact.startswith((
        "javascript:",
        "vbscript:",
        "data:text/html",
        "data:application/xhtml+xml",
        "data:image/svg+xml",
    ))


def is_dangerous_style(value: str) -> bool:
    compact = normalized_compact(value)
    return (
        "expression(" in compact
        or "url(javascript:" in compact
        or "url(data:text/html" in compact
        or "url(data:image/svg+xml" in compact
    )


def is_dangerous_srcset(value: str) -> bool:
    for candidate in value.split(","):
        item = candidate.strip()
        if not item:
            continue
        url = item.split()[0]
        if is_dangerous_url(url):
            return True
    return False


def attr_value(match: re.Match[str]) -> str:
    return match.group(4) or match.group(5) or match.group(6) or ""


def tag_name(tag: str) -> str:
    match = re.match(r"(?is)<\s*/?\s*([A-Za-z0-9:_-]+)", tag)
    return match.group(1).lower() if match else ""


def attr_values(tag: str, name: str) -> list[str]:
    values = []
    for match in ATTR_RE.finditer(tag):
        if match.group(2).lower() == name:
            values.append(attr_value(match))
    return values


def dangerous_meta_refresh(tag: str) -> bool:
    if tag_name(tag) != "meta":
        return False
    http_equiv = [normalized_compact(value) for value in attr_values(tag, "http-equiv")]
    if "refresh" not in http_equiv:
        return False
    for content in attr_values(tag, "content"):
        decoded = decode_value(content)
        match = re.search(r"(?is)url\s*=\s*([^;]+)", decoded)
        if match and is_dangerous_url(match.group(1).strip().strip("\"'")):
            return True
    return False


def sanitize_tag(tag: str) -> str:
    if tag.startswith("<!--") or tag.startswith("<!") or tag.startswith("<?"):
        return tag
    if dangerous_meta_refresh(tag):
        return ""

    def replace_attr(match: re.Match[str]) -> str:
        spacing = match.group(1)
        name = match.group(2)
        lowered = name.lower()
        full_value = match.group(3) or ""
        value = attr_value(match)

        if lowered.startswith("on"):
            return ""
        if lowered == "style" and value and is_dangerous_style(value):
            return ""
        if lowered in URL_LIST_ATTRS and value and is_dangerous_srcset(value):
            return ""
        if lowered in URL_ATTRS:
            if lowered == "srcdoc":
                return ""
            if value and is_dangerous_url(value):
                return ""
        return f"{spacing}{name}{full_value}"

    return ATTR_RE.sub(replace_attr, tag)


def sanitize_html(text: str) -> str:
    sanitized = text
    for pattern in WHOLE_BLOCK_PATTERNS:
        sanitized = pattern.sub("", sanitized)
    sanitized = LONE_DANGEROUS_TAG.sub("", sanitized)
    sanitized = TAG_RE.sub(lambda match: sanitize_tag(match.group(0)), sanitized)
    return sanitized


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: filter.py <html-file>")
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as handle:
        original = handle.read()
    sanitized = sanitize_html(original)
    if sanitized != original:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(sanitized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
