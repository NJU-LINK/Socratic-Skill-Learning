#!/bin/bash
set -euo pipefail

mkdir -p /app

cat > /app/filter.py <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import sys
from urllib.parse import unquote
from pathlib import Path


TAG_BLOCKLIST = {
    "script",
    "iframe",
    "object",
    "embed",
}

ATTR_DROP = {
    "formaction",
    "srcdoc",
}

URL_ATTRS = {
    "href",
    "src",
    "xlink:href",
    "action",
    "formaction",
    "poster",
    "data",
}


DANGEROUS_STYLE_PATTERNS = (
    "expression(",
    "@import",
    "behavior:",
    "-moz-binding",
)


def normalize_value(value: str) -> str:
    decoded = value
    for _ in range(3):
        updated = html.unescape(unquote(decoded))
        if updated == decoded:
            break
        decoded = updated
    return re.sub(r"[\x00-\x20]+", "", decoded).lower()


def is_dangerous_url(value: str) -> bool:
    normalized = normalize_value(value.strip().strip("\"'"))
    return normalized.startswith(("javascript:", "vbscript:", "data:text/html"))


def replace_dangerous_css_urls(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        candidate = match.group(1)
        if is_dangerous_url(candidate):
            return "url(none)"
        return match.group(0)

    return re.sub(r"url\(\s*([^)]*?)\s*\)", repl, text, flags=re.IGNORECASE | re.DOTALL)


def css_is_dangerous(text: str) -> bool:
    normalized = normalize_value(text)
    return any(pattern in normalized for pattern in DANGEROUS_STYLE_PATTERNS) or "url(javascript:" in normalized or "url(vbscript:" in normalized or "url(data:text/html" in normalized


def protect_entities(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        token = f"__ENTITY_{len(replacements)}__"
        replacements[token] = match.group(0)
        return token

    protected = re.sub(r"&(?:#x[0-9a-fA-F]+|#[0-9]+|[A-Za-z][A-Za-z0-9]+);", repl, text)
    return protected, replacements


def restore_entities(text: str, replacements: dict[str, str]) -> str:
    for token, original in replacements.items():
        text = text.replace(token, original)
    return text


def sanitize_css_declarations(text: str) -> str:
    protected, replacements = protect_entities(text)
    trailing_semicolon = text.rstrip().endswith(";")
    cleaned_parts: list[str] = []

    for declaration in protected.split(";"):
        if declaration.strip() == "":
            continue
        declaration = restore_entities(declaration, replacements)
        if css_is_dangerous(declaration):
            continue
        candidate = replace_dangerous_css_urls(declaration)
        if css_is_dangerous(candidate):
            continue
        cleaned_parts.append(candidate.strip())

    if not cleaned_parts:
        return ""

    cleaned = "; ".join(cleaned_parts)
    if trailing_semicolon:
        cleaned += ";"
    return cleaned


def sanitize_css_stylesheet(text: str) -> str:
    cleaned_rules: list[str] = []

    for chunk in text.split("}"):
        if "{" not in chunk:
            if chunk.strip() and not css_is_dangerous(chunk):
                cleaned_rules.append(chunk)
            continue

        selector, body = chunk.split("{", 1)
        cleaned_body = sanitize_css_declarations(body)
        if cleaned_body:
            cleaned_rules.append(f"{selector}{{{cleaned_body}}}")

    return "".join(cleaned_rules)


def obfuscated_tag_pattern(tag: str) -> str:
    separators = r"(?:[\x00-\x20]+)?"
    return separators.join(re.escape(char) for char in tag)


def strip_blocked_tags(text: str) -> str:
    for tag in TAG_BLOCKLIST:
        pattern = obfuscated_tag_pattern(tag)
        paired = re.compile(rf"<\s*{pattern}\b[^>]*>.*?<\s*/\s*{pattern}\s*>", re.IGNORECASE | re.DOTALL)
        self_closing = re.compile(rf"<\s*{pattern}\b[^>]*?/\s*>", re.IGNORECASE | re.DOTALL)
        open_only = re.compile(rf"<\s*{pattern}\b[^>]*>", re.IGNORECASE | re.DOTALL)
        while True:
            updated = paired.sub("", text)
            updated = self_closing.sub("", updated)
            updated = open_only.sub("", updated)
            if updated == text:
                break
            text = updated
    return text


def sanitize_style_blocks(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(1)
        attrs = match.group(2) or ""
        body = match.group(3)
        cleaned = sanitize_css_stylesheet(body)
        return f"<{tag}{attrs}>{cleaned}</{tag}>"

    return re.sub(r"<\s*(style)\b([^>]*)>(.*?)<\s*/\s*style\s*>", repl, text, flags=re.IGNORECASE | re.DOTALL)


def sanitize_meta_refresh(text: str) -> str:
    pattern = re.compile(r"<\s*meta\b([^>]*)>", re.IGNORECASE | re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        attrs = sanitize_attrs(match.group(1))
        if re.search(r"\bhttp-equiv\s*=\s*(['\"]?)\s*refresh\s*\1", attrs, flags=re.IGNORECASE):
            return ""
        return f"<meta{attrs}>"

    return pattern.sub(repl, text)


def sanitize_attrs(attr_text: str) -> str:
    attr_re = re.compile(
        r"(?P<space>\s+)(?P<name>[A-Za-z_:][-A-Za-z0-9_:.]*)(?:\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?",
        re.DOTALL,
    )

    def repl(match: re.Match[str]) -> str:
        space = match.group("space")
        name = match.group("name")
        value = match.group("value")
        lower_name = name.lower()

        if lower_name.startswith("on"):
            return ""
        if lower_name in ATTR_DROP:
            return ""
        if value is None:
            return match.group(0)

        quote = value[0] if value[0] in "\"'" else ""
        inner = value[1:-1] if quote else value
        compact = normalize_value(inner)

        if lower_name in URL_ATTRS and (
            compact.startswith("javascript:")
            or compact.startswith("data:text/html")
            or compact.startswith("vbscript:")
        ):
            return ""

        if lower_name == "style":
            cleaned = sanitize_css_declarations(inner)
            if cleaned.strip() == "":
                return ""
            escaped = cleaned.replace(quote, f"\\{quote}") if quote else cleaned
            return f"{space}{name}={quote}{escaped}{quote}" if quote else f"{space}{name}={escaped}"

        return match.group(0)

    return attr_re.sub(repl, attr_text)


def sanitize_tags(text: str) -> str:
    tag_re = re.compile(r"<(?P<closing>/)?(?P<name>[A-Za-z][A-Za-z0-9:-]*)(?P<attrs>[^<>]*?)(?P<self>/)?>", re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        closing = match.group("closing") or ""
        name = match.group("name")
        attrs = match.group("attrs") or ""
        self_close = match.group("self") or ""
        if closing:
            return match.group(0)
        lower_name = name.lower()
        if lower_name in TAG_BLOCKLIST:
            return ""
        cleaned_attrs = sanitize_attrs(attrs)
        return f"<{name}{cleaned_attrs}{self_close}>"

    return tag_re.sub(repl, text)


def sanitize_html(text: str) -> str:
    text = strip_blocked_tags(text)
    text = sanitize_style_blocks(text)
    text = sanitize_meta_refresh(text)
    text = sanitize_tags(text)
    return text


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: filter.py <html-file>")

    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    cleaned = sanitize_html(original)
    path.write_text(cleaned, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x /app/filter.py
