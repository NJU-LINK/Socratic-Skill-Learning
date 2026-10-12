#!/bin/bash
set -euo pipefail

mkdir -p /app

cat <<'PY' > /app/filter.py
#!/usr/bin/env python3
import html
import re
import sys
from pathlib import Path


URL_ATTRS = {
    "action",
    "formaction",
    "href",
    "poster",
    "src",
    "xlink:href",
}


def compact_for_detection(value: str) -> str:
    decoded = html.unescape(value).lower()
    return "".join(ch for ch in decoded if not ch.isspace() and ch >= " ")


def is_dangerous_url(value: str) -> bool:
    compact = compact_for_detection(value)
    if compact.startswith(("javascript:", "vbscript:")):
        return True
    if compact.startswith("data:"):
        header = compact[5:].split(",", 1)[0]
        return "text/html" in header or "image/svg+xml" in header
    return False


def split_top_level(text: str, delimiter: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote = ""

    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            continue

        if char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == delimiter and depth == 0:
            parts.append(text[start:index])
            start = index + 1

    parts.append(text[start:])
    return parts


def iter_css_chunks(style_value: str) -> list[tuple[str, bool]]:
    chunks: list[tuple[str, bool]] = []
    start = 0
    depth = 0
    quote = ""

    for index, char in enumerate(style_value):
        if quote:
            if char == quote:
                quote = ""
            continue

        if char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == ";" and depth == 0:
            chunks.append((style_value[start:index], True))
            start = index + 1

    chunks.append((style_value[start:], False))
    return chunks


def top_level_colon_index(chunk: str) -> int:
    depth = 0
    quote = ""

    for index, char in enumerate(chunk):
        if quote:
            if char == quote:
                quote = ""
            continue

        if char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == ":" and depth == 0:
            return index

    return -1


def remove_dangerous_css_urls(value: str) -> str:
    pieces: list[str] = []
    cursor = 0
    changed = False

    while True:
        match = re.search(r"url\(", value[cursor:], flags=re.IGNORECASE)
        if not match:
            pieces.append(value[cursor:])
            break

        start = cursor + match.start()
        pieces.append(value[cursor:start])

        index = start + 4
        depth = 1
        quote = ""
        while index < len(value):
            char = value[index]
            if quote:
                if char == quote:
                    quote = ""
            else:
                if char in {'"', "'"}:
                    quote = char
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        break
            index += 1

        if depth != 0:
            pieces.append(value[start:])
            break

        inner = value[start + 4:index].strip()
        candidate = inner.strip().strip("\"'")
        if is_dangerous_url(candidate):
            changed = True
        else:
            pieces.append(value[start:index + 1])

        cursor = index + 1

    if not changed:
        return value

    sanitized = "".join(pieces)
    items = [item for item in split_top_level(sanitized, ",") if item.strip()]
    return ", ".join(items)


def sanitize_style(style_value: str) -> str:
    sanitized_chunks: list[str] = []

    for raw_chunk, had_semicolon in iter_css_chunks(style_value):
        if not raw_chunk.strip():
            continue

        colon = top_level_colon_index(raw_chunk)
        if colon == -1:
            sanitized = raw_chunk
        else:
            prop = raw_chunk[:colon]
            value = raw_chunk[colon + 1 :]
            prop_name = prop.strip().lower()
            compact_value = compact_for_detection(value)

            if prop_name in {"behavior", "-moz-binding"} or "expression(" in compact_value:
                continue

            new_value = remove_dangerous_css_urls(value)
            if not new_value.strip():
                continue
            sanitized = prop + ":" + new_value

        if had_semicolon:
            sanitized_chunks.append(sanitized + ";")
        else:
            sanitized_chunks.append(sanitized)

    return "".join(sanitized_chunks)


def sanitize_attr(name: str, value: str) -> str:
    if name.startswith("on"):
        return ""
    if name == "srcdoc":
        return ""
    if name == "style":
        return sanitize_style(value)
    if name in URL_ATTRS and is_dangerous_url(value):
        return ""
    return value


def sanitize_tag(tag: str) -> str:
    if tag.startswith(("<!--", "<!", "<?", "</")):
        return tag

    index = 1
    while index < len(tag) and tag[index].isspace():
        index += 1
    while index < len(tag) and tag[index] not in "\t\r\n />":
        index += 1

    replacements: list[tuple[int, int, str]] = []

    while index < len(tag):
        while index < len(tag) and tag[index].isspace():
            index += 1
        if index >= len(tag) or tag[index] in "/>":
            break

        name_start = index
        while index < len(tag) and tag[index] not in "\t\r\n =>/":
            index += 1
        name = tag[name_start:index]

        while index < len(tag) and tag[index].isspace():
            index += 1
        if index >= len(tag) or tag[index] != "=":
            continue
        index += 1

        while index < len(tag) and tag[index].isspace():
            index += 1
        if index >= len(tag):
            break

        if tag[index] in {'"', "'"}:
            quote = tag[index]
            index += 1
            value_start = index
            while index < len(tag) and tag[index] != quote:
                index += 1
            value_end = index
            if index < len(tag):
                index += 1
        else:
            value_start = index
            while index < len(tag) and not tag[index].isspace() and tag[index] not in "/>":
                index += 1
            value_end = index

        original = tag[value_start:value_end]
        sanitized = sanitize_attr(name.lower(), original)
        if sanitized != original:
            replacements.append((value_start, value_end, sanitized))

    if not replacements:
        return tag

    updated = tag
    for start, end, replacement in reversed(replacements):
        updated = updated[:start] + replacement + updated[end:]
    return updated


def sanitize_html(document: str) -> str:
    output: list[str] = []
    index = 0

    while index < len(document):
        if document.startswith("<!--", index):
            end = document.find("-->", index + 4)
            if end == -1:
                output.append(document[index:])
                break
            output.append(document[index : end + 3])
            index = end + 3
            continue

        if document[index] != "<":
            output.append(document[index])
            index += 1
            continue

        cursor = index + 1
        quote = ""
        while cursor < len(document):
            char = document[cursor]
            if quote:
                if char == quote:
                    quote = ""
            else:
                if char in {'"', "'"}:
                    quote = char
                elif char == ">":
                    break
            cursor += 1

        if cursor >= len(document):
            output.append(document[index:])
            break

        output.append(sanitize_tag(document[index : cursor + 1]))
        index = cursor + 1

    return "".join(output)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: filter.py <html-file>")

    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    sanitized = sanitize_html(original)
    path.write_text(sanitized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
