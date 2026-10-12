#!/usr/bin/env python3
"""
HTML JavaScript sanitizer – removes executable JS behavior from HTML files
while preserving legitimate document structure, visible content, and safe markup.

Usage: python3 filter.py <input.html>
Modifies the file in-place.

Dependencies: beautifulsoup4 (bs4) with html.parser (stdlib).
"""

import sys
import re
import html
import base64
import urllib.parse
from bs4 import BeautifulSoup, Comment, Tag

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

# Tags always removed entirely (with all children)
DANGEROUS_TAGS_REMOVE = {
    "script", "iframe", "object", "embed", "applet",
    "noembed", "frameset", "frame", "base",
}

# Tags removed when inside SVG/MathML context
SVG_DANGEROUS_TAGS = {
    "script", "handler", "foreignobject",
}

# Attributes that carry URLs which could execute JS
URL_ATTRS = {
    "href", "src", "action", "formaction", "data", "poster",
    "dynsrc", "lowsrc", "background", "srcdoc",
    "xlink:href", "xmlns:xlink",
    "usemap", "longdesc",
    "code", "codebase", "archive",
    "movie", "pluginspage", "classid",
}

DANGEROUS_SCHEMES = {"javascript:", "vbscript:", "livescript:"}

# ──────────────────────────────────────────────────────────────
# Decoding helpers
# ──────────────────────────────────────────────────────────────

def _decode_value(val):
    """Fully decode: HTML entities -> strip control chars -> URL-decode -> repeat."""
    if not isinstance(val, str):
        return ""
    prev = None
    current = val
    for _ in range(5):
        if current == prev:
            break
        prev = current
        current = html.unescape(current)
        # Strip control chars, null bytes, and Unicode replacement char (U+FFFD)
        # BS4 converts &#0; / &#x00; to U+FFFD
        current = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]', '', current)
        try:
            current = urllib.parse.unquote(current)
        except Exception:
            pass
    return current


def _normalize_tag_name(name):
    """Decode and normalize a tag name to catch entity-encoded tags like <scr&#105;pt>."""
    if not name:
        return ""
    decoded = html.unescape(name)
    decoded = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]', '', decoded)
    return decoded.lower()


# ──────────────────────────────────────────────────────────────
# Detection helpers
# ──────────────────────────────────────────────────────────────

def _is_dangerous_url(val):
    """Check if a URL value resolves to a dangerous scheme or dangerous data: payload."""
    decoded = _decode_value(val)
    collapsed = re.sub(r'\s+', '', decoded).lower()

    for scheme in DANGEROUS_SCHEMES:
        if collapsed.startswith(scheme):
            return True

    if collapsed.startswith("data:"):
        if "text/html" in collapsed or "application/xhtml" in collapsed:
            return True
        if "base64" in collapsed:
            try:
                b64_match = re.search(r'base64,(.*)', decoded, re.IGNORECASE | re.DOTALL)
                if b64_match:
                    decoded_b64 = base64.b64decode(b64_match.group(1)).decode('utf-8', errors='ignore')
                    if any(t in decoded_b64.lower() for t in
                           ['<script', '<iframe', '<object', '<embed', '<svg', '<img']):
                        return True
            except Exception:
                return True  # Can't decode → conservative removal
    return False


def _is_dangerous_srcset(val):
    """Check srcset (comma-separated URL descriptor pairs) for dangerous URLs."""
    if not isinstance(val, str):
        return False
    for part in val.split(","):
        url = part.strip().split()[0] if part.strip().split() else ""
        if url and _is_dangerous_url(url):
            return True
    return False


def _is_event_handler(attr_name):
    """True if the attribute is an on* event handler (decoded, case-insensitive)."""
    decoded = html.unescape(attr_name).lower().strip()
    decoded = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]', '', decoded)
    return decoded.startswith("on")


def _is_dangerous_style_attr(val):
    """Check if a style attribute value contains dangerous CSS constructs."""
    decoded = _decode_value(val).lower()
    collapsed = re.sub(r'\s+', '', decoded)
    patterns = [
        (r'expression\s*\(', r'expression\('),
        (r'-moz-binding\s*:', r'-moz-binding:'),
        (r'behavior\s*:', r'behavior:'),
        (r'javascript\s*:', r'javascript:'),
        (r'vbscript\s*:', r'vbscript:'),
    ]
    for normal, col in patterns:
        if re.search(normal, decoded) or re.search(col, collapsed):
            return True
    return False


def _sanitize_style_content(css_text):
    """Remove dangerous CSS from <style> tag content; keep safe rules."""
    if not isinstance(css_text, str):
        return css_text
    css_text = re.sub(r'expression\s*\([^;{}]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'-moz-binding\s*:\s*[^;}\n]+', '', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'behavior\s*:\s*[^;}\n]+', '', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'url\s*\(\s*["\']?\s*javascript:[^)]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'url\s*\(\s*["\']?\s*vbscript:[^)]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'@import\s+[^;]+;', '', css_text, flags=re.IGNORECASE)
    return css_text


def _is_dangerous_meta(tag):
    http_equiv = (tag.get("http-equiv") or "").lower().strip()
    return http_equiv == "refresh"


def _is_svg_dangerous_attr(tag, attr_name, attr_val):
    tag_name = _normalize_tag_name(tag.name)
    if tag_name in ("set", "animate", "animatetransform"):
        target_attr = (tag.get("attributename") or "").lower()
        if _is_event_handler(target_attr):
            return True
    if tag_name == "use":
        for href_attr in ("href", "xlink:href"):
            val = tag.get(href_attr, "")
            if isinstance(val, str) and _is_dangerous_url(val):
                return True
    return False


def _tag_is_dangerous(tag):
    return _normalize_tag_name(tag.name) in DANGEROUS_TAGS_REMOVE


def _tag_is_svg_dangerous(tag):
    normalized = _normalize_tag_name(tag.name)
    if normalized not in SVG_DANGEROUS_TAGS:
        return False
    parent = tag.parent
    while parent:
        if parent.name and _normalize_tag_name(parent.name) in ("svg", "math"):
            return True
        parent = parent.parent
    return False


# ──────────────────────────────────────────────────────────────
# Sanitization pipeline
# ──────────────────────────────────────────────────────────────

def sanitize(soup):
    """Sanitize a BeautifulSoup tree in-place."""

    # 1. Remove dangerous comments (IE conditional comments, script-containing)
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        lc = comment.lower()
        if "script" in lc:
            comment.extract()
        elif "if" in lc and ("ie" in lc or "mso" in lc):
            comment.extract()

    # 2. Remove dangerous tags entirely (handles entity-encoded names)
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _tag_is_dangerous(tag):
            tag.decompose()

    # 3. Remove dangerous SVG/MathML elements
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _tag_is_svg_dangerous(tag):
            tag.decompose()

    # 4. Sanitize <style> tag text content
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            style_tag.string = _sanitize_style_content(style_tag.string)
        elif style_tag.contents:
            for child in list(style_tag.contents):
                if hasattr(child, 'string') and child.string:
                    child.string = _sanitize_style_content(child.string)
                elif isinstance(child, str):
                    child.replace_with(_sanitize_style_content(child))

    # 5. Clean attributes on every remaining tag
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        attrs_to_remove = []
        for attr_name in list(tag.attrs.keys()):
            attr_lower = attr_name.lower()
            attr_val = tag.attrs[attr_name]
            if isinstance(attr_val, list):
                attr_val = " ".join(attr_val)

            if _is_event_handler(attr_name):
                attrs_to_remove.append(attr_name); continue
            if attr_lower in URL_ATTRS and isinstance(attr_val, str) and _is_dangerous_url(attr_val):
                attrs_to_remove.append(attr_name); continue
            if attr_lower == "srcset" and isinstance(attr_val, str) and _is_dangerous_srcset(attr_val):
                attrs_to_remove.append(attr_name); continue
            if attr_lower == "srcdoc":
                attrs_to_remove.append(attr_name); continue
            if attr_lower == "style" and isinstance(attr_val, str) and _is_dangerous_style_attr(attr_val):
                attrs_to_remove.append(attr_name); continue
            if _is_svg_dangerous_attr(tag, attr_name, attr_val):
                attrs_to_remove.append(attr_name); continue

        for a in attrs_to_remove:
            del tag.attrs[a]

    # 6. Remove <meta http-equiv="refresh">
    for meta in soup.find_all("meta"):
        if _is_dangerous_meta(meta):
            meta.decompose()

    # 7. Remove <link> with dangerous href
    for link in soup.find_all("link"):
        href = link.get("href", "")
        if isinstance(href, str) and _is_dangerous_url(href):
            link.decompose()

    # 8. Clean dangerous action from <form>
    for form in soup.find_all("form"):
        action = form.get("action", "")
        if isinstance(action, str) and _is_dangerous_url(action):
            del form.attrs["action"]

    # 9. Final sweep for any remaining dangerous tags
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _tag_is_dangerous(tag):
            tag.decompose()

    return soup


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 filter.py <html_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    soup = BeautifulSoup(content, "html.parser")
    sanitize(soup)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(str(soup))


if __name__ == "__main__":
    main()
