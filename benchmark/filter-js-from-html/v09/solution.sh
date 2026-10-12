#!/bin/bash
set -euo pipefail

app_dir="${APP_DIR:-/app}"
mkdir -p "$app_dir"

cat > "$app_dir/filter.py" <<'PY'
#!/usr/bin/env python3
import html
import re
import sys
from pathlib import Path


URL_ATTRS = {
    "action",
    "background",
    "formaction",
    "href",
    "poster",
    "src",
    "xlink:href",
}

SCRIPT_OPEN_RE = re.compile(r"(?is)<\s*script\b")
SCRIPT_CLOSE_RE = re.compile(r"(?is)</\s*script\s*>")
OBJECT_CLOSE_RE = re.compile(r"(?is)</\s*object\s*>")
DANGEROUS_URL_RE = re.compile(r"^(?:javascript:|vbscript:|data:text/html\b)", re.IGNORECASE)


def normalize_url(value: str) -> str:
    decoded = html.unescape(value)
    return re.sub(r"[\x00-\x20]+", "", decoded).lower()


def is_dangerous_url(value: str) -> bool:
    return bool(DANGEROUS_URL_RE.match(normalize_url(value)))


def escape_attr_value(value: str, quote: str) -> str:
    value = value.replace("&", "&amp;")
    if quote == '"':
        return value.replace('"', "&quot;")
    return value.replace("'", "&#39;")


def find_tag_end(text: str, start: int) -> int:
    if text.startswith("<!--", start):
        end = text.find("-->", start + 4)
        return len(text) - 1 if end == -1 else end + 2

    quote = ""
    index = start + 1
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        else:
            if char in {'"', "'"}:
                quote = char
            elif char == ">":
                return index
        index += 1
    return len(text) - 1


def parse_tag(tag: str):
    if not tag.startswith("<") or tag.startswith("</") or tag.startswith("<!") or tag.startswith("<?"):
        return None

    end = len(tag) - 1
    index = 1
    while index < end and tag[index].isspace():
        index += 1
    name_start = index
    while index < end and not tag[index].isspace() and tag[index] not in "/>":
        index += 1
    if name_start == index:
        return None
    name_end = index

    attrs = []
    while index < end:
        ws_start = index
        while index < end and tag[index].isspace():
            index += 1
        leading_ws = tag[ws_start:index]
        if index >= end or tag[index] in "/>":
            return tag[:name_start], tag[name_start:name_end], attrs, tag[ws_start:]

        attr_name_start = index
        while index < end and not tag[index].isspace() and tag[index] not in "=>/":
            index += 1
        name = tag[attr_name_start:index]
        between_start = index
        while index < end and tag[index].isspace():
            index += 1
        between = tag[between_start:index]

        if index < end and tag[index] == "=":
            index += 1
            after_eq_start = index
            while index < end and tag[index].isspace():
                index += 1
            after_eq = tag[after_eq_start:index]
            quote = ""
            if index < end and tag[index] in {'"', "'"}:
                quote = tag[index]
                index += 1
                value_start = index
                while index < end and tag[index] != quote:
                    index += 1
                value = tag[value_start:index]
                if index < end:
                    index += 1
            else:
                value_start = index
                while index < end and not tag[index].isspace() and tag[index] not in ">/":
                    index += 1
                value = tag[value_start:index]

            attrs.append(
                {
                    "leading_ws": leading_ws,
                    "name": name,
                    "name_lower": name.lower(),
                    "between": between,
                    "after_eq": after_eq,
                    "quote": quote,
                    "value": value,
                }
            )
            continue

        attrs.append(
            {
                "leading_ws": leading_ws,
                "name": name,
                "name_lower": name.lower(),
                "between": between,
                "after_eq": "",
                "quote": "",
                "value": None,
            }
        )

    return tag[:name_start], tag[name_start:name_end], attrs, tag[index:]


def render_tag(prefix: str, tag_name: str, attrs, suffix: str) -> str:
    parts = [prefix, tag_name]
    for attr in attrs:
        if attr.get("remove"):
            continue
        parts.append(attr["leading_ws"])
        parts.append(attr["name"])
        parts.append(attr["between"])
        if attr["value"] is not None:
            parts.append("=")
            parts.append(attr["after_eq"])
            if attr["quote"]:
                parts.append(attr["quote"])
                parts.append(attr["value"])
                parts.append(attr["quote"])
            else:
                parts.append(attr["value"])
    parts.append(suffix)
    return "".join(parts)


def sanitize_style(style_value: str):
    changed = False
    safe_declarations = []

    for declaration in style_value.split(";"):
        stripped = declaration.strip()
        if not stripped:
            continue
        if ":" not in declaration:
            safe_declarations.append(declaration.strip())
            continue

        prop, raw_value = declaration.split(":", 1)
        value = raw_value.strip()
        lowered = value.lower()
        updated = re.sub(
            r"url\(\s*(?:['\"])?\s*(?:javascript|vbscript)\s*:[^)]*\)",
            "none",
            value,
            flags=re.IGNORECASE,
        )
        if updated != value:
            changed = True
            value = updated
            lowered = value.lower()

        if "expression(" in lowered or "-moz-binding" in lowered or "behavior:" in lowered:
            changed = True
            continue

        safe_declarations.append(f"{prop.strip()}:{value.strip()}")

    if not changed:
        return style_value, False

    sanitized = ";".join(safe_declarations)
    if sanitized and style_value.rstrip().endswith(";"):
        sanitized += ";"
    return sanitized, True


def sanitize_srcdoc(srcdoc_value: str):
    decoded = html.unescape(srcdoc_value)
    sanitized = sanitize_html(decoded)
    return sanitized, sanitized != decoded


def sanitize_tag(tag: str) -> str:
    if re.match(r"(?is)<\s*/?\s*(?:object|embed)\b", tag):
        return ""

    parsed = parse_tag(tag)
    if parsed is None:
        return tag

    prefix, tag_name, attrs, suffix = parsed
    lowered_tag_name = tag_name.lower()
    changed = False

    http_equiv = None
    content_attr = None
    for attr in attrs:
        if attr["name_lower"].startswith("on"):
            attr["remove"] = True
            changed = True
            continue
        if attr["value"] is None:
            continue

        quote = attr["quote"] or '"'
        decoded_value = html.unescape(attr["value"])

        if attr["name_lower"] in URL_ATTRS and is_dangerous_url(decoded_value):
            attr["value"] = ""
            attr["quote"] = quote
            changed = True
            continue

        if attr["name_lower"] == "style":
            sanitized_style, style_changed = sanitize_style(decoded_value)
            if style_changed:
                attr["value"] = escape_attr_value(sanitized_style, quote)
                attr["quote"] = quote
                changed = True
            continue

        if attr["name_lower"] == "srcdoc":
            sanitized_srcdoc, srcdoc_changed = sanitize_srcdoc(attr["value"])
            if srcdoc_changed:
                attr["value"] = escape_attr_value(sanitized_srcdoc, quote)
                attr["quote"] = quote
                changed = True
            continue

        if attr["name_lower"] == "http-equiv":
            http_equiv = decoded_value.strip().lower()
        elif attr["name_lower"] == "content":
            content_attr = attr

    if lowered_tag_name == "meta" and http_equiv == "refresh" and content_attr is not None:
        normalized = normalize_url(content_attr["value"])
        if "url=javascript:" in normalized or "url=vbscript:" in normalized or "url=data:text/html" in normalized:
            return ""

    if not changed:
        return tag

    return render_tag(prefix, tag_name, attrs, suffix)


def sanitize_html(text: str) -> str:
    output = []
    index = 0

    while index < len(text):
        next_lt = text.find("<", index)
        if next_lt == -1:
            output.append(text[index:])
            break

        output.append(text[index:next_lt])

        if SCRIPT_OPEN_RE.match(text, next_lt):
            open_end = find_tag_end(text, next_lt)
            close_match = SCRIPT_CLOSE_RE.search(text, open_end + 1)
            index = len(text) if close_match is None else close_match.end()
            continue

        if re.match(r"(?is)<\s*object\b", text[next_lt:]):
            tag_end = find_tag_end(text, next_lt)
            close_match = OBJECT_CLOSE_RE.search(text, tag_end + 1)
            index = tag_end + 1 if close_match is None else close_match.end()
            continue

        tag_end = find_tag_end(text, next_lt)
        output.append(sanitize_tag(text[next_lt:tag_end + 1]))
        index = tag_end + 1

    return "".join(output)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: filter.py <html-file>", file=sys.stderr)
        return 1

    html_path = Path(sys.argv[1])
    original = html_path.read_text(encoding="utf-8")
    sanitized = sanitize_html(original)
    html_path.write_text(sanitized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x "$app_dir/filter.py"
