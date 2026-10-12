#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path

script = r'''#!/usr/bin/env python3
import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


URL_ATTRS = {
    "action",
    "background",
    "data",
    "formaction",
    "href",
    "poster",
    "src",
    "xlink:href",
}

ACTIVE_CONTAINER_TAGS = {"iframe", "object", "embed"}
SKIP_CONTENT_TAGS = {"script", "iframe", "object"}

CONTROL_WS_RE = re.compile(r"[\x00-\x20\x7f]+")
UNSAFE_STYLE_RE = re.compile(
    r"expression\s*\(|javascript\s*:|vbscript\s*:|behavior\s*:|-moz-binding",
    re.IGNORECASE,
)


def repeatedly_unescape(value: str) -> str:
    for _ in range(3):
        next_value = html.unescape(value)
        if next_value == value:
            break
        value = next_value
    return value


def normalize_protocol_value(value: str) -> str:
    decoded = repeatedly_unescape(value)
    return CONTROL_WS_RE.sub("", decoded).lower()


def is_dangerous_url(value: str) -> bool:
    normalized = normalize_protocol_value(value)
    if normalized.startswith(("javascript:", "vbscript:")):
        return True
    if normalized.startswith("data:"):
        payload = normalized[5:]
        return payload.startswith((
            "text/html",
            "application/xhtml+xml",
            "image/svg+xml",
        ))
    return False


def sanitize_style(value: str) -> str | None:
    kept = []
    for declaration in value.split(";"):
        piece = declaration.strip()
        if not piece:
            continue
        if UNSAFE_STYLE_RE.search(repeatedly_unescape(piece)):
            continue
        kept.append(piece)
    if not kept:
        return None
    return "; ".join(kept)


def meta_refresh_is_dangerous(tag) -> bool:
    if tag["name"] != "meta":
        return False
    attrs = tag["attrs"]
    equiv = attrs.get("http-equiv")
    content = attrs.get("content")
    if not equiv or not content or str(equiv).strip().lower() != "refresh":
        return False
    decoded = repeatedly_unescape(str(content))
    match = re.search(r"url\s*=\s*([^;]+)", decoded, re.IGNORECASE)
    if not match:
        return False
    return is_dangerous_url(match.group(1).strip())


def sanitize_attrs(tag_name: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    current = []
    for attr_name, attr_value in attrs:
        lower_name = attr_name.lower()
        raw_value = "" if attr_value is None else str(attr_value)

        if lower_name.startswith("on"):
            continue

        if lower_name == "srcdoc":
            continue

        if lower_name == "style":
            cleaned = sanitize_style(raw_value)
            if cleaned is None:
                continue
            current.append((attr_name, cleaned))
            continue

        if lower_name in URL_ATTRS and is_dangerous_url(raw_value):
            continue

        current.append((attr_name, attr_value))

    tag = {"name": tag_name, "attrs": {name: value for name, value in current}}
    if meta_refresh_is_dangerous(tag):
        current = [(name, value) for name, value in current if name.lower() != "content"]

    return current


def render_attrs(attrs: list[tuple[str, str | None]]) -> str:
    rendered = []
    for name, value in attrs:
        if value is None or value == "":
            rendered.append(name)
        else:
            escaped = html.escape(value, quote=True)
            rendered.append(f'{name}="{escaped}"')
    return (" " + " ".join(rendered)) if rendered else ""


class SanitizingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.skip_stack: list[str] = []

    def handle_decl(self, decl: str) -> None:
        if not self.skip_stack:
            self.out.append(f"<!{decl}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower_tag = tag.lower()
        if self.skip_stack:
            if lower_tag == self.skip_stack[-1]:
                self.skip_stack.append(lower_tag)
            return
        if lower_tag in SKIP_CONTENT_TAGS:
            self.skip_stack.append(lower_tag)
            return
        if lower_tag in ACTIVE_CONTAINER_TAGS:
            return
        sanitized = sanitize_attrs(tag, attrs)
        self.out.append(f"<{tag}{render_attrs(sanitized)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower_tag = tag.lower()
        if self.skip_stack or lower_tag in SKIP_CONTENT_TAGS or lower_tag in ACTIVE_CONTAINER_TAGS:
            return
        sanitized = sanitize_attrs(tag, attrs)
        self.out.append(f"<{tag}{render_attrs(sanitized)}/>")

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if self.skip_stack:
            if lower_tag == self.skip_stack[-1]:
                self.skip_stack.pop()
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip_stack:
            self.out.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.skip_stack:
            self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_stack:
            self.out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self.skip_stack:
            self.out.append(f"<!--{data}-->")


def sanitize_html(text: str) -> str:
    parser = SanitizingHTMLParser()
    parser.feed(text)
    parser.close()
    return "".join(parser.out)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: filter.py <html-file>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    path.write_text(sanitize_html(text), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

Path('/app/filter.py').write_text(script, encoding='utf-8')
PY

chmod +x /app/filter.py
