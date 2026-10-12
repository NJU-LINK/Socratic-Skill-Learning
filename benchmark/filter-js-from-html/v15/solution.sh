#!/bin/bash
set -euo pipefail

mkdir -p /app

cat <<'PY' > /app/filter.py
from __future__ import annotations

import html
import pathlib
import re
import sys
import urllib.parse


URL_ATTRS = {
    "action",
    "data",
    "formaction",
    "href",
    "poster",
    "src",
    "xlink:href",
}

WHOLE_BLOCK_PATTERNS = (
    re.compile(r"(?is)<script\b[^>]*>.*?</script\s*>") ,
    re.compile(r"(?is)<object\b[^>]*>.*?</object\s*>") ,
    re.compile(r"(?is)<embed\b[^>]*?/?>") ,
)


def repeated_decode(value: str) -> str:
    decoded = value
    for _ in range(4):
        updated = urllib.parse.unquote(html.unescape(decoded))
        if updated == decoded:
            break
        decoded = updated
    return decoded


def normalize_for_scheme_check(value: str) -> str:
    decoded = repeated_decode(value)
    return "".join(ch for ch in decoded if ch > " " and ch != "\x7f").lower()


def is_dangerous_data_url(value: str) -> bool:
    normalized = normalize_for_scheme_check(value)
    if not normalized.startswith("data:"):
        return False

    payload = normalized[5:]
    header, _, body = payload.partition(",")
    mediatype = header.split(";", 1)[0]

    if mediatype in {"", "text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml"}:
        return True

    decoded_body = repeated_decode(body)
    lowered_body = decoded_body.lower()
    return "<script" in lowered_body or "<svg" in lowered_body or "javascript:" in lowered_body


def is_dangerous_url(value: str) -> bool:
    normalized = normalize_for_scheme_check(value)
    return normalized.startswith("javascript:") or normalized.startswith("vbscript:") or is_dangerous_data_url(value)


def unquote_attr_value(raw_value: str | None) -> tuple[str | None, str | None]:
    if raw_value is None:
        return None, None
    if len(raw_value) >= 2 and raw_value[0] in {'"', "'"} and raw_value[-1] == raw_value[0]:
        return raw_value[1:-1], raw_value[0]
    return raw_value, None


def has_meaningful_srcdoc_content(fragment: str) -> bool:
    text_only = re.sub(r"(?is)<[^>]+>", "", fragment)
    return bool(text_only.strip())


def render_attr_value(value: str, quote: str | None) -> str:
    quote_char = quote or '"'
    escaped = html.escape(value, quote=True)
    return f"{quote_char}{escaped}{quote_char}"


def parse_start_tag(raw_tag: str) -> tuple[str, list[dict[str, object]], str]:
    pos = 1
    tag_end = len(raw_tag) - 1
    while pos < tag_end and raw_tag[pos].isspace():
        pos += 1

    name_start = pos
    while pos < tag_end and raw_tag[pos] not in " \t\r\n\f/>":
        pos += 1
    tag_name = raw_tag[name_start:pos]

    attrs: list[dict[str, object]] = []
    last_end = pos

    while pos < tag_end:
        ws_start = pos
        while pos < tag_end and raw_tag[pos].isspace():
            pos += 1
        if pos >= tag_end:
            break
        if raw_tag[pos] == "/":
            break

        name_start = pos
        while pos < tag_end and raw_tag[pos] not in " \t\r\n\f=>/":
            pos += 1
        if name_start == pos:
            break

        raw_name = raw_tag[name_start:pos]
        pre_eq_start = pos
        while pos < tag_end and raw_tag[pos].isspace():
            pos += 1
        pre_eq_ws = raw_tag[pre_eq_start:pos]

        has_equals = pos < tag_end and raw_tag[pos] == "="
        post_eq_ws = ""
        raw_value = None

        if has_equals:
            pos += 1
            post_eq_start = pos
            while pos < tag_end and raw_tag[pos].isspace():
                pos += 1
            post_eq_ws = raw_tag[post_eq_start:pos]

            if pos < tag_end and raw_tag[pos] in {'"', "'"}:
                quote = raw_tag[pos]
                value_start = pos
                pos += 1
                while pos < tag_end:
                    if raw_tag[pos] == quote:
                        pos += 1
                        break
                    pos += 1
                raw_value = raw_tag[value_start:pos]
            else:
                value_start = pos
                while pos < tag_end and raw_tag[pos] not in " \t\r\n\f>":
                    pos += 1
                raw_value = raw_tag[value_start:pos]

        full_end = pos
        attrs.append(
            {
                "leading_ws": raw_tag[ws_start:name_start],
                "raw_name": raw_name,
                "pre_eq_ws": pre_eq_ws,
                "has_equals": has_equals,
                "post_eq_ws": post_eq_ws,
                "raw_value": raw_value,
                "start": ws_start,
                "end": full_end,
            }
        )
        last_end = full_end

    return tag_name, attrs, raw_tag[last_end:-1]


def find_tag_end(text: str, start: int) -> int:
    quote = None
    pos = start + 1
    while pos < len(text):
        char = text[pos]
        if quote:
            if char == quote:
                quote = None
        else:
            if char in {'"', "'"}:
                quote = char
            elif char == ">":
                return pos
        pos += 1
    return len(text) - 1


def sanitize_meta_refresh(attrs: list[dict[str, object]]) -> bool:
    attr_map: dict[str, str] = {}
    for attr in attrs:
        value_text, _ = unquote_attr_value(attr["raw_value"])
        attr_map[html.unescape(str(attr["raw_name"])) .lower()] = value_text or ""

    if attr_map.get("http-equiv", "").strip().lower() != "refresh":
        return False

    content = attr_map.get("content", "")
    lowered = repeated_decode(content).lower()
    if "url=" not in lowered:
        return False
    url = lowered.split("url=", 1)[1].strip()
    return is_dangerous_url(url)


def rebuild_start_tag(tag_name: str, attrs: list[str], tail: str) -> str:
    return f"<{tag_name}{''.join(attrs)}{tail}>"


def sanitize_start_tag(raw_tag: str) -> str:
    tag_name, attrs, tail = parse_start_tag(raw_tag)
    lowered_tag = tag_name.lower()

    if lowered_tag == "meta" and sanitize_meta_refresh(attrs):
        return ""

    rendered_attrs: list[str] = []

    for attr in attrs:
        raw_name = str(attr["raw_name"])
        lowered_name = html.unescape(raw_name).lower()
        raw_value = attr["raw_value"]
        value_text, quote = unquote_attr_value(raw_value)

        if lowered_name.startswith("on"):
            continue

        if lowered_name in URL_ATTRS and value_text is not None and is_dangerous_url(value_text):
            continue

        if lowered_name == "srcdoc" and value_text is not None:
            sanitized_fragment = sanitize_html(html.unescape(value_text))
            if not has_meaningful_srcdoc_content(sanitized_fragment):
                continue
            rendered_attrs.append(
                f"{attr['leading_ws']}{raw_name}{attr['pre_eq_ws']}={attr['post_eq_ws']}{render_attr_value(sanitized_fragment, quote)}"
            )
            continue

        if lowered_name == "sandbox" and value_text is not None:
            tokens = [token for token in value_text.split() if token.lower() != "allow-scripts"]
            if not tokens:
                continue
            rendered_attrs.append(
                f"{attr['leading_ws']}{raw_name}{attr['pre_eq_ws']}={attr['post_eq_ws']}{render_attr_value(' '.join(tokens), quote)}"
            )
            continue

        rendered_attrs.append(raw_tag[int(attr["start"]):int(attr["end"])])

    return rebuild_start_tag(tag_name, rendered_attrs, tail)


def sanitize_html(text: str) -> str:
    sanitized = text
    for pattern in WHOLE_BLOCK_PATTERNS:
        sanitized = pattern.sub("", sanitized)

    output: list[str] = []
    pos = 0

    while pos < len(sanitized):
        char = sanitized[pos]
        if char != "<":
            output.append(char)
            pos += 1
            continue

        if sanitized.startswith("<!--", pos):
            end = sanitized.find("-->", pos + 4)
            if end == -1:
                output.append(sanitized[pos:])
                break
            output.extend(sanitized[pos:end + 3])
            pos = end + 3
            continue

        if pos + 1 < len(sanitized) and sanitized[pos + 1] in {"!", "?"}:
            end = sanitized.find(">", pos + 2)
            if end == -1:
                output.append(sanitized[pos:])
                break
            output.extend(sanitized[pos:end + 1])
            pos = end + 1
            continue

        if pos + 1 < len(sanitized) and sanitized[pos + 1] == "/":
            output.append(char)
            pos += 1
            continue

        if pos + 1 >= len(sanitized) or not sanitized[pos + 1].isalpha():
            output.append(char)
            pos += 1
            continue

        end = find_tag_end(sanitized, pos)
        raw_tag = sanitized[pos:end + 1]
        new_tag = sanitize_start_tag(raw_tag)

        if new_tag:
            output.extend(new_tag)
            pos = end + 1
            continue

        line_start = len(output)
        while line_start > 0 and output[line_start - 1] not in {"\n", "\r"}:
            line_start -= 1
        prefix = output[line_start:]
        next_pos = end + 1
        while next_pos < len(sanitized) and sanitized[next_pos] in " \t":
            next_pos += 1

        if all(ch in " \t" for ch in prefix) and next_pos < len(sanitized) and sanitized[next_pos] == "\n":
            del output[line_start:]
            pos = next_pos + 1
        else:
            pos = end + 1

    return "".join(output)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: filter.py <html-file>")

    path = pathlib.Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    sanitized = sanitize_html(original)
    path.write_text(sanitized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
