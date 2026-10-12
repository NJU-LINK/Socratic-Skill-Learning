#!/bin/bash

set -euo pipefail

cat > /app/filter.py <<'PY'
import pathlib
import re
import sys
import urllib.parse


SCRIPT_TAG_RE = re.compile(r"<\s*script\b.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)
ACTIVE_CONTAINER_RE = re.compile(
    r"<\s*(?:iframe|object|embed|frame|frameset|applet)\b.*?(?:<\s*/\s*(?:iframe|object|embed|frame|frameset|applet)\s*>|/\s*>)",
    re.IGNORECASE | re.DOTALL,
)
ACTIVE_CONTAINER_OPEN_RE = re.compile(
    r"<\s*(?:iframe|object|embed|frame|frameset|applet)\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
META_REFRESH_TAG_RE = re.compile(
    r"<\s*meta\b(?=[^>]*\bhttp-equiv\s*=\s*(?:\"[^\"]*refresh[^\"]*\"|'[^']*refresh[^']*'|refresh\b))(?=[^>]*\bcontent\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
EVENT_HANDLER_RE = re.compile(
    r"""(?P<prefix>\s)(?P<name>on[a-z0-9_:-]+)(?P<space>\s*=\s*)(?P<value>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s>]+)""",
    re.IGNORECASE,
)
JS_URL_ATTR_RE = re.compile(
    r"""(?P<prefix>\s)(?P<name>(?:href|src|xlink:href|formaction|action|data|poster|background|srcdoc|xml:base))(?P<space>\s*=\s*)(?:\"(?P<dvalue>[^\"]*)\"|'(?P<svalue>[^']*)'|(?P<uvalue>[^\s>]+))""",
    re.IGNORECASE,
)
ANIMATE_TO_RE = re.compile(
    r"""(?P<prefix>\s)(?P<name>to)(?P<space>\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)
STYLE_ATTR_RE = re.compile(
    r"""(?P<prefix>\s)(?P<name>style)(?P<space>\s*=\s*)(?:\"(?P<dvalue>[^\"]*)\"|'(?P<svalue>[^']*)')""",
    re.IGNORECASE | re.DOTALL,
)
HTML_ENTITY_RE = re.compile(r"&#(?:x[0-9a-f]+|[0-9]+);", re.IGNORECASE)
WHITESPACE_ENTITY_RE = re.compile(r"(?:\s|&#(?:x0*9|x0*a|x0*c|x0*d|0*9|0*10|0*12|0*13);)+", re.IGNORECASE)
CONTAINER_ATTR_RE = re.compile(
    r"""(?P<name>[a-z0-9_:-]+)(?:\s*=\s*(?:\"(?P<dvalue>[^\"]*)\"|'(?P<svalue>[^']*)'|(?P<uvalue>[^\s>]+)))?""",
    re.IGNORECASE,
)


def decode_entities(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)[2:-1]
        base = 16 if token[:1].lower() == "x" else 10
        digits = token[1:] if base == 16 else token
        try:
            return chr(int(digits, base))
        except ValueError:
            return match.group(0)

    return HTML_ENTITY_RE.sub(replace, value)


def normalize_attr_value(value: str) -> str:
    value = decode_entities(value)
    previous = None
    while value != previous:
        previous = value
        value = urllib.parse.unquote(value)
    value = WHITESPACE_ENTITY_RE.sub("", value)
    return value.strip().lower()


def is_dangerous_url(value: str) -> bool:
    normalized = normalize_attr_value(value)
    return normalized.startswith("javascript:") or normalized.startswith("data:text/html")


def has_dangerous_style(value: str) -> bool:
    normalized = normalize_attr_value(value)
    return "expression(" in normalized or "url(javascript:" in normalized or "behavior:" in normalized


def strip_script_tags(html: str) -> str:
    return SCRIPT_TAG_RE.sub("", html)


def get_container_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    opening_tag = tag.split(">", 1)[0]
    for match in CONTAINER_ATTR_RE.finditer(opening_tag):
        name = match.group("name").lower()
        if name.startswith("<"):
            continue
        if name in {"iframe", "object", "embed", "frame", "frameset", "applet"}:
            continue
        value = match.group("dvalue") or match.group("svalue") or match.group("uvalue") or ""
        attrs[name] = value
    return attrs


def is_dangerous_container(tag: str) -> bool:
    tag_name_match = re.match(r"<\s*(?P<name>[a-z0-9]+)", tag, re.IGNORECASE)
    if not tag_name_match:
        return False

    tag_name = tag_name_match.group("name").lower()
    if tag_name in {"frameset", "applet"}:
        return True

    attrs = get_container_attrs(tag)
    if "srcdoc" in attrs:
        return True

    for name in ("src", "data", "codebase", "archive", "classid"):
        if name in attrs and is_dangerous_url(attrs[name]):
            return True

    return False


def strip_active_containers(html: str) -> str:
    html = ACTIVE_CONTAINER_RE.sub(lambda m: "" if is_dangerous_container(m.group(0)) else m.group(0), html)
    return ACTIVE_CONTAINER_OPEN_RE.sub(lambda m: "" if is_dangerous_container(m.group(0)) else m.group(0), html)


def strip_meta_refresh(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        content_match = re.search(
            r"\bcontent\s*=\s*(?:\"(?P<dvalue>[^\"]*)\"|'(?P<svalue>[^']*)'|(?P<uvalue>[^\s>]+))",
            tag,
            re.IGNORECASE | re.DOTALL,
        )
        if not content_match:
            return tag
        value = content_match.group("dvalue") or content_match.group("svalue") or content_match.group("uvalue") or ""
        normalized = normalize_attr_value(value)
        refresh_target = normalized.split("url=", 1)[1] if "url=" in normalized else normalized
        if is_dangerous_url(refresh_target):
            return ""
        return tag

    return META_REFRESH_TAG_RE.sub(replace, html)


def strip_event_handlers(html: str) -> str:
    return EVENT_HANDLER_RE.sub(lambda m: m.group("prefix"), html)


def strip_dangerous_url_attrs(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group("dvalue") or match.group("svalue") or match.group("uvalue") or ""
        if is_dangerous_url(value):
            return match.group("prefix")
        return match.group(0)

    return JS_URL_ATTR_RE.sub(replace, html)


def strip_svg_animation_targets(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if is_dangerous_url(match.group("value")):
            return match.group("prefix")
        return match.group(0)

    return ANIMATE_TO_RE.sub(replace, html)


def strip_dangerous_style_attrs(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group("dvalue") or match.group("svalue") or ""
        if has_dangerous_style(value):
            return match.group("prefix")
        return match.group(0)

    return STYLE_ATTR_RE.sub(replace, html)


def sanitize_html(html: str) -> str:
    sanitized = strip_script_tags(html)
    sanitized = strip_active_containers(sanitized)
    sanitized = strip_meta_refresh(sanitized)
    sanitized = strip_event_handlers(sanitized)
    sanitized = strip_dangerous_url_attrs(sanitized)
    sanitized = strip_svg_animation_targets(sanitized)
    sanitized = strip_dangerous_style_attrs(sanitized)
    sanitized = re.sub(r"<([A-Za-z][A-Za-z0-9:_-]*)\s+>", r"<\1>", sanitized)
    return sanitized


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python /app/filter.py <html-file>", file=sys.stderr)
        return 1

    path = pathlib.Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    path.write_text(sanitize_html(original), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
