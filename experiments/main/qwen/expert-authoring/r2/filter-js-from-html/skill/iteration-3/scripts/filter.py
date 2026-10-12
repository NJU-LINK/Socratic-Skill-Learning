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

DANGEROUS_TAGS_REMOVE = {
    "script", "iframe", "object", "embed", "applet",
    "noembed", "frameset", "frame", "base",
}

SVG_DANGEROUS_TAGS = {
    "script", "handler", "foreignobject",
}

URL_ATTRS = {
    "href", "src", "action", "formaction", "data", "poster",
    "dynsrc", "lowsrc", "background", "srcdoc",
    "xlink:href", "xmlns:xlink",
    "usemap", "longdesc",
    "code", "codebase", "archive",
    "movie", "pluginspage", "classid",
}

DANGEROUS_SCHEMES = {"javascript:", "vbscript:", "livescript:"}

SVG_ANIMATION_ELEMENTS = {"set", "animate", "animatetransform"}

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
                return True
    return False


def _is_dangerous_srcset(val):
    if not isinstance(val, str):
        return False
    for part in val.split(","):
        url = part.strip().split()[0] if part.strip().split() else ""
        if url and _is_dangerous_url(url):
            return True
    return False


def _is_event_handler(attr_name):
    decoded = html.unescape(attr_name).lower().strip()
    decoded = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]', '', decoded)
    return decoded.startswith("on")


def _is_dangerous_style_attr(val):
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
    if not isinstance(css_text, str):
        return css_text
    css_text = re.sub(r'expression\s*\([^;{}]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'-moz-binding\s*:\s*[^;}\n]+', '', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'behavior\s*:\s*[^;}\n]+', '', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'url\s*\(\s*["\']?\s*javascript:[^)]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'url\s*\(\s*["\']?\s*vbscript:[^)]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'url\s*\(\s*["\']?\s*data\s*:\s*text/html[^)]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'@import\s+[^;]+;', '', css_text, flags=re.IGNORECASE)
    return css_text


def _is_dangerous_meta(tag):
    http_equiv = (tag.get("http-equiv") or "").lower().strip()
    return http_equiv == "refresh"


def _is_in_svg_or_math(tag):
    """Check if a tag is inside an SVG or MathML context."""
    parent = tag.parent
    while parent:
        if parent.name and _normalize_tag_name(parent.name) in ("svg", "math"):
            return True
        parent = parent.parent
    return False


def _is_dangerous_svg_animation_element(tag):
    """Check if an SVG animation element is dangerous as a whole.

    <set>, <animate>, <animatetransform> set/animate attribute values.
    Dangerous when:
    1. Target (attributename) is an on* event handler
    2. Any attribute value on the element is a dangerous URL
    """
    tag_name = _normalize_tag_name(tag.name)
    if tag_name not in SVG_ANIMATION_ELEMENTS:
        return False
    if not _is_in_svg_or_math(tag):
        return False

    # Rule 1: target attribute is an event handler
    target_attr = (tag.get("attributename") or "").lower()
    if _is_event_handler(target_attr):
        return True

    # Rule 2: any attribute value is a dangerous URL
    for attr_name, attr_val in tag.attrs.items():
        if isinstance(attr_val, list):
            attr_val = " ".join(attr_val)
        if not isinstance(attr_val, str):
            continue
        if _is_dangerous_url(attr_val):
            return True

    return False


def _is_svg_dangerous_attr(tag, attr_name, attr_val):
    """Check per-attribute SVG dangers (for non-animation elements)."""
    tag_name = _normalize_tag_name(tag.name)
    if tag_name == "use":
        if attr_name.lower() in ("href", "xlink:href"):
            if isinstance(attr_val, str) and _is_dangerous_url(attr_val):
                return True
    return False


def _tag_is_dangerous(tag):
    return _normalize_tag_name(tag.name) in DANGEROUS_TAGS_REMOVE


def _tag_is_svg_dangerous(tag):
    normalized = _normalize_tag_name(tag.name)
    if normalized not in SVG_DANGEROUS_TAGS:
        return False
    return _is_in_svg_or_math(tag)


# ──────────────────────────────────────────────────────────────
# Sanitization pipeline
# ──────────────────────────────────────────────────────────────

def sanitize(soup):
    """Sanitize a BeautifulSoup tree in-place."""

    # 1. Remove dangerous comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        lc = comment.lower()
        if "script" in lc:
            comment.extract()
        elif "if" in lc and ("ie" in lc or "mso" in lc):
            comment.extract()

    # 2. Remove dangerous tags entirely
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _tag_is_dangerous(tag):
            tag.decompose()

    # 3. Remove dangerous SVG/MathML child elements
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _tag_is_svg_dangerous(tag):
            tag.decompose()

    # 4. Remove dangerous SVG animation elements as whole elements
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _is_dangerous_svg_animation_element(tag):
            tag.decompose()

    # 5. Sanitize <style> tag text content
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            style_tag.string = _sanitize_style_content(style_tag.string)
        elif style_tag.contents:
            for child in list(style_tag.contents):
                if hasattr(child, 'string') and child.string:
                    child.string = _sanitize_style_content(child.string)
                elif isinstance(child, str):
                    child.replace_with(_sanitize_style_content(child))

    # 6. Clean attributes on every remaining tag
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

    # 7. Remove <meta http-equiv="refresh">
    for meta in soup.find_all("meta"):
        if _is_dangerous_meta(meta):
            meta.decompose()

    # 8. Remove <link> with dangerous href
    for link in soup.find_all("link"):
        href = link.get("href", "")
        if isinstance(href, str) and _is_dangerous_url(href):
            link.decompose()

    # 9. Clean dangerous action from <form>
    for form in soup.find_all("form"):
        action = form.get("action", "")
        if isinstance(action, str) and _is_dangerous_url(action):
            del form.attrs["action"]

    # 10. Final sweep
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _tag_is_dangerous(tag):
            tag.decompose()

    return soup


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
