#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/filter.py
from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


ACTIVE_CONTAINER_TAGS = {"iframe", "object", "embed"}
URL_ATTRS = {
    "action",
    "formaction",
    "href",
    "src",
    "data",
    "poster",
    "background",
    "xlink:href",
}
SCRIPTABLE_DATA_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}


def fully_decode(value: str, rounds: int = 6) -> str:
    current = value
    for _ in range(rounds):
        decoded = html.unescape(unquote(current))
        if decoded == current:
            break
        current = decoded
    return current


def compact_for_scheme(value: str) -> str:
    return re.sub(r"[\x00-\x20]+", "", value).strip().lower()


def data_url_is_dangerous(value: str) -> bool:
    compact = compact_for_scheme(fully_decode(value))
    if not compact.startswith("data:"):
        return False

    header, _, _payload = compact[5:].partition(",")
    media_type = header.split(";", 1)[0] or "text/plain"
    return media_type in SCRIPTABLE_DATA_TYPES


def url_value_is_dangerous(value: str) -> bool:
    compact = compact_for_scheme(fully_decode(value))
    return (
        compact.startswith("javascript:")
        or compact.startswith("vbscript:")
        or data_url_is_dangerous(compact)
    )


def refresh_content_is_dangerous(value: str) -> bool:
    decoded = fully_decode(value)
    match = re.search(r"(?:^|;)\s*url\s*=\s*(.+)$", decoded, flags=re.IGNORECASE)
    if not match:
        return False
    target = match.group(1).strip().strip("\"'")
    return url_value_is_dangerous(target)


def contains_executable_markup(fragment: str) -> bool:
    soup = BeautifulSoup(fully_decode(fragment), "html.parser")
    for tag in soup.find_all(True):
        name = tag.name.lower()
        if name == "script" or name in ACTIVE_CONTAINER_TAGS:
            return True
        if name == "meta":
            equiv = str(tag.attrs.get("http-equiv", "")).lower()
            if equiv == "refresh" and refresh_content_is_dangerous(str(tag.attrs.get("content", ""))):
                return True
        for attr_name, attr_value in tag.attrs.items():
            attr = attr_name.lower()
            value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
            if attr.startswith("on"):
                return True
            if attr in URL_ATTRS and url_value_is_dangerous(value):
                return True
            if attr == "srcdoc" and contains_executable_markup(value):
                return True
    return False


def find_tag_end(source: str, start: int) -> int:
    quote = ""
    i = start
    while i < len(source):
        char = source[i]
        if quote:
            if char == quote:
                quote = ""
        elif char in {'"', "'"}:
            quote = char
        elif char == ">":
            return i
        i += 1
    return -1


def next_tag(source: str, start: int) -> tuple[int, int, str] | None:
    index = start
    while True:
        tag_start = source.find("<", index)
        if tag_start == -1:
            return None

        if source.startswith("<!--", tag_start):
            comment_end = source.find("-->", tag_start + 4)
            if comment_end == -1:
                return None
            return tag_start, comment_end + 3, source[tag_start : comment_end + 3]

        if source.startswith("<!", tag_start) or source.startswith("<?", tag_start):
            tag_end = find_tag_end(source, tag_start + 2)
            if tag_end == -1:
                return None
            return tag_start, tag_end + 1, source[tag_start : tag_end + 1]

        next_char = source[tag_start + 1 : tag_start + 2]
        if next_char and (next_char.isalpha() or next_char == "/"):
            tag_end = find_tag_end(source, tag_start + 1)
            if tag_end == -1:
                return None
            return tag_start, tag_end + 1, source[tag_start : tag_end + 1]

        index = tag_start + 1


def parse_attributes(tag_text: str) -> list[dict[str, object]]:
    match = re.match(r"<\s*[A-Za-z][A-Za-z0-9:-]*", tag_text)
    if not match:
        return []

    limit = len(tag_text) - 1
    while limit > 0 and tag_text[limit - 1].isspace():
        limit -= 1
    if limit > 0 and tag_text[limit - 1] == "/":
        limit -= 1

    attrs: list[dict[str, object]] = []
    i = match.end()
    while i < limit:
        span_start = i
        while i < limit and tag_text[i].isspace():
            i += 1
        span_start = span_start if span_start != i else i
        if i >= limit:
            break
        if tag_text[i] in "/>":
            break

        name_start = i
        while i < limit and not tag_text[i].isspace() and tag_text[i] not in "=>/":
            i += 1
        if name_start == i:
            i += 1
            continue

        name = tag_text[name_start:i]
        value = None

        while i < limit and tag_text[i].isspace():
            i += 1
        if i < limit and tag_text[i] == "=":
            i += 1
            while i < limit and tag_text[i].isspace():
                i += 1
            if i < limit and tag_text[i] in {'"', "'"}:
                quote = tag_text[i]
                value_start = i + 1
                i += 1
                while i < limit and tag_text[i] != quote:
                    i += 1
                value = tag_text[value_start:i]
                if i < limit:
                    i += 1
            else:
                value_start = i
                while i < limit and not tag_text[i].isspace() and tag_text[i] not in "/>":
                    i += 1
                value = tag_text[value_start:i]

        attrs.append(
            {
                "name": name,
                "lower": name.lower(),
                "value": value,
                "span": (span_start, i),
            }
        )

    return attrs


def parse_tag(tag_text: str) -> dict[str, object] | None:
    match = re.match(r"<\s*(/)?\s*([A-Za-z][A-Za-z0-9:-]*)", tag_text)
    if not match:
        return None
    return {
        "name": match.group(2).lower(),
        "is_end": bool(match.group(1)),
        "is_self_closing": bool(re.search(r"/\s*>$", tag_text)),
        "attrs": [] if match.group(1) else parse_attributes(tag_text),
    }


def find_matching_block_end(source: str, start: int, open_end: int, tag_name: str) -> int:
    if tag_name == "embed":
        return open_end

    if tag_name == "script":
        closing = re.search(r"</\s*script\b[^>]*>", source[open_end:], flags=re.IGNORECASE)
        return open_end + closing.end() if closing else open_end

    depth = 1
    cursor = open_end
    while True:
        tag = next_tag(source, cursor)
        if tag is None:
            return open_end
        tag_start, tag_end, tag_text = tag
        cursor = tag_end
        parsed = parse_tag(tag_text)
        if not parsed or parsed["name"] != tag_name:
            continue
        if parsed["is_end"]:
            depth -= 1
            if depth == 0:
                return tag_end
        elif not parsed["is_self_closing"]:
            depth += 1


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if start >= end:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def apply_removals(source: str, removals: list[tuple[int, int]]) -> str:
    if not removals:
        return source

    pieces = []
    cursor = 0
    for start, end in merge_ranges(removals):
        pieces.append(source[cursor:start])
        cursor = end
    pieces.append(source[cursor:])
    return "".join(pieces)


def sanitize_tag_text(tag_text: str, attrs: list[dict[str, object]]) -> str:
    removals: list[tuple[int, int]] = []
    for attr in attrs:
        name = str(attr["lower"])
        value = "" if attr["value"] is None else str(attr["value"])
        if name.startswith("on"):
            removals.append(attr["span"])
            continue
        if name == "srcdoc" and contains_executable_markup(value):
            removals.append(attr["span"])
            continue
        if name in URL_ATTRS and url_value_is_dangerous(value):
            removals.append(attr["span"])
    return apply_removals(tag_text, removals)


def sanitize_html(source: str) -> str:
    removals: list[tuple[int, int]] = []
    replacements: list[tuple[int, int, str]] = []
    cursor = 0

    while True:
        tag = next_tag(source, cursor)
        if tag is None:
            break

        tag_start, tag_end, tag_text = tag
        cursor = tag_end
        parsed = parse_tag(tag_text)
        if not parsed or parsed["is_end"]:
            continue

        name = str(parsed["name"])
        attrs = list(parsed["attrs"])
        attr_map = {}
        for attr in attrs:
            attr_map.setdefault(str(attr["lower"]), "" if attr["value"] is None else str(attr["value"]))

        if name == "script" or name in ACTIVE_CONTAINER_TAGS:
            block_end = find_matching_block_end(source, tag_start, tag_end, name)
            removals.append((tag_start, block_end))
            cursor = block_end
            continue

        if name == "meta" and attr_map.get("http-equiv", "").lower() == "refresh":
            if refresh_content_is_dangerous(attr_map.get("content", "")):
                removals.append((tag_start, tag_end))
                continue

        sanitized_tag = sanitize_tag_text(tag_text, attrs)
        if sanitized_tag != tag_text:
            replacements.append((tag_start, tag_end, sanitized_tag))

    if not removals and not replacements:
        return source

    chunks = []
    cursor = 0
    replacement_map = {(start, end): text for start, end, text in replacements}
    for start, end in merge_ranges(removals + [(start, end) for start, end, _ in replacements]):
        chunks.append(source[cursor:start])
        replacement = replacement_map.get((start, end))
        if replacement is not None:
            chunks.append(replacement)
        cursor = end
    chunks.append(source[cursor:])
    return "".join(chunks)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python /app/filter.py <html_file>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    path.write_text(sanitize_html(source), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
