#!/usr/bin/env python3
"""
HTML JavaScript sanitizer - removes executable JavaScript behavior from HTML
files while preserving legitimate document structure, SVG graphics, MathML
equations, forms, links, and non-dangerous content.

Usage:  python3 filter.py <html_file>
        Modifies the file in-place.
"""

import sys
import re
import html as html_module
from urllib.parse import unquote as _url_unquote
from bs4 import BeautifulSoup, Comment

# ============================================================================
# Configuration
# ============================================================================

REMOVE_ELEMENTS = frozenset({
    'script', 'iframe', 'object', 'embed', 'applet',
    'base', 'frame', 'frameset',
    'handler',    # SVG 1.2 script handler
    'listener',   # SVG 1.2 event listener
})

URL_ATTRIBUTES = frozenset({
    'href', 'src', 'action', 'formaction', 'data',
    'poster', 'background', 'dynsrc', 'lowsrc',
    'xlink:href', 'srcdoc', 'codebase', 'classid',
})

URL_TARGET_ATTRS = frozenset({
    'href', 'xlink:href', 'src', 'action', 'formaction',
    'data', 'poster', 'background',
})

SVG_ANIMATION_ELEMENTS = frozenset({
    'animate', 'animatetransform', 'animatemotion', 'set',
})

# ============================================================================
# URL helpers
# ============================================================================

_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\t\n\r]')


def _normalize(url):
    """Normalize a URL for dangerous-scheme detection.

    Pipeline:
      1. Join list-valued attributes (BS4 sometimes returns lists)
      2. Decode HTML entities  (handles &#106;avascript:, j&#x61;vascript:, etc.)
      3. Decode percent-encoding — applied **twice** to catch double-encoding
         like %256A%2561...  (browsers decode one layer; attackers double-encode)
      4. Strip control characters and whitespace
    """
    if not url:
        return ''
    if isinstance(url, list):
        url = ' '.join(url)
    url = html_module.unescape(str(url))
    # Decode percent-encoding twice for layered/double-encoding attacks
    url = _url_unquote(url)
    url = _url_unquote(url)
    url = _CONTROL_CHARS.sub('', url)
    return url.strip()


def is_dangerous_url(url):
    n = _normalize(url)
    if not n:
        return False
    if re.match(r'javascript\s*:', n, re.I):
        return True
    if re.match(r'vbscript\s*:', n, re.I):
        return True
    if re.match(r'data\s*:\s*text/html', n, re.I):
        return True
    if re.match(r'data\s*:\s*image/svg\+xml', n, re.I):
        return True
    if re.match(r'data\s*:\s*application/xhtml\+xml', n, re.I):
        return True
    return False

# ============================================================================
# CSS helpers
# ============================================================================

_DANGEROUS_CSS_CHECK = [
    re.compile(r'expression\s*\(',                              re.I),
    re.compile(r'url\s*\([^()]*(?:\([^()]*\)[^()]*)*\)*javascript\s*:',  re.I),
    re.compile(r'url\s*\([^()]*(?:\([^()]*\)[^()]*)*\)*vbscript\s*:',    re.I),
    re.compile(r'url\s*\([^()]*data\s*:\s*text/html',           re.I),
    re.compile(r'-moz-binding\s*:',                             re.I),
    re.compile(r'behavior\s*:',                                 re.I),
    re.compile(r'binding\s*:',                                  re.I),
    re.compile(r'@import\s+["\'][^"\']*javascript\s*:',         re.I),
    re.compile(r'@import\s+url\s*\([^)]*javascript\s*:',        re.I),
]


def is_dangerous_css(value):
    if not value:
        return False
    n = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))
    return any(pat.search(n) for pat in _DANGEROUS_CSS_CHECK)


def _replace_url_fn(m):
    """Replace dangerous url() values while handling nested parentheses."""
    inner = m.group(0)
    if re.search(r'javascript\s*:', inner, re.I):
        return 'none'
    if re.search(r'vbscript\s*:', inner, re.I):
        return 'none'
    if re.search(r'data\s*:\s*text/html', inner, re.I):
        return 'none'
    return inner

# Regex to match url(...) handling one level of nested parentheses
_URL_PAREN_RE = re.compile(
    r'url\s*\([^()]*(?:\([^()]*\)[^()]*)*\)', re.I
)


def sanitize_css(value):
    if not value:
        return value
    cdata_pre = cdata_suf = ''
    m = re.match(r'^(\s*<!\[CDATA\[)(.*?)(\]\]>\s*)$', value, re.S)
    if m:
        cdata_pre, value, cdata_suf = m.group(1), m.group(2), m.group(3)

    # expression(...)
    value = re.sub(r'expression\s*\([^()]*(?:\([^()]*\)[^()]*)*\)', 'none', value, flags=re.I)
    # url(javascript:...) / url(vbscript:...) / url(data:text/html...)
    value = _URL_PAREN_RE.sub(_replace_url_fn, value)
    # -moz-binding / behavior / binding
    value = re.sub(r'-moz-binding\s*:[^;"\'}]*', '', value, flags=re.I)
    value = re.sub(r'behavior\s*:[^;"\'}]*',     '', value, flags=re.I)
    value = re.sub(r'binding\s*:[^;"\'}]*',      '', value, flags=re.I)
    # @import with dangerous URL
    value = re.sub(r'@import\s+["\'][^"\']*javascript\s*:[^"\']*["\']', '', value, flags=re.I)
    value = re.sub(r'@import\s+url\s*\([^)]*javascript\s*:[^)]*\)',      '', value, flags=re.I)

    return cdata_pre + value + cdata_suf


def _css_has_meaningful_declarations(value):
    """Check if sanitized CSS still contains any useful property declarations.

    Returns False when the value is empty, whitespace-only, or contains
    only declarations with 'none' values (which are placeholders left
    after replacing dangerous content).
    """
    if not value:
        return False
    for decl in value.split(';'):
        decl = decl.strip()
        if not decl or ':' not in decl:
            continue
        prop, _, val = decl.partition(':')
        val = val.strip()
        if val and val.lower() != 'none':
            return True
    return False

# ============================================================================
# SVG animation helpers
# ============================================================================

def _check_animation_values(el, check_fn):
    """Check SVG animation value attributes using check_fn.

    For 'values', split by semicolons and check each value individually
    since semicolon-separated lists may contain individual dangerous URLs.
    """
    for val_attr in ('to', 'from'):
        v = el.get(val_attr, '')
        if v and check_fn(v):
            return True
    vals = el.get('values', '')
    if vals:
        for part in vals.split(';'):
            part = part.strip()
            if part and check_fn(part):
                return True
    return False


def is_dangerous_svg_animation(el):
    tag = el.name.lower() if el.name else ''
    if tag not in SVG_ANIMATION_ELEMENTS:
        return False

    target_attr = (el.get('attributename') or '').lower().strip()

    if target_attr.startswith('on'):
        return True

    if target_attr in URL_TARGET_ATTRS:
        if _check_animation_values(el, is_dangerous_url):
            return True

    if target_attr == 'style':
        if _check_animation_values(el, is_dangerous_css):
            return True

    for href_attr in ('href', 'xlink:href'):
        v = el.get(href_attr, '')
        if v and is_dangerous_url(v):
            return True

    return False

# ============================================================================
# Main sanitizer
# ============================================================================

def sanitize_html(content):
    # --- pre-processing ---
    content = content.replace('\x00', '')

    # --- parse ---
    soup = BeautifulSoup(content, 'html.parser')

    # ---- Phase 1: remove inherently dangerous elements ----
    changed = True
    while changed:
        changed = False
        for tag_name in REMOVE_ELEMENTS:
            found = soup.find_all(tag_name)
            if found:
                for el in found:
                    el.decompose()
                changed = True

    # ---- Phase 2: conditional element removal ----
    for meta in soup.find_all('meta'):
        he = meta.get('http-equiv', '')
        if isinstance(he, list):
            he = ' '.join(he)
        if str(he).lower().strip() == 'refresh':
            meta.decompose()

    for link in soup.find_all('link'):
        rel = link.get('rel', [])
        if isinstance(rel, list):
            rel_vals = [r.lower() for r in rel]
        else:
            rel_vals = [str(rel).lower()]
        if 'import' in rel_vals:
            link.decompose()

    for fo in soup.find_all('foreignobject'):
        fo.decompose()

    # ---- Phase 3: sanitize remaining elements ----
    for el in list(soup.find_all(True)):
        if el.name is None:
            continue
        tag = el.name.lower()

        if tag in SVG_ANIMATION_ELEMENTS:
            if is_dangerous_svg_animation(el):
                el.decompose()
            continue

        to_remove = []
        for attr_name in list(el.attrs.keys()):
            attr_lower = attr_name.lower()

            if attr_lower.startswith('on'):
                to_remove.append(attr_name)
                continue

            if attr_lower in URL_ATTRIBUTES or attr_lower.endswith(':href'):
                val = el[attr_name]
                if is_dangerous_url(val):
                    to_remove.append(attr_name)
                    continue

            if attr_lower == 'style':
                val = el[attr_name]
                if isinstance(val, list):
                    val = ' '.join(val)
                if is_dangerous_css(val):
                    sanitized = sanitize_css(val)
                    if _css_has_meaningful_declarations(sanitized):
                        el[attr_name] = sanitized
                    else:
                        # All declarations were dangerous; remove the attribute
                        to_remove.append(attr_name)

            if attr_lower == 'srcdoc':
                to_remove.append(attr_name)

        for attr in to_remove:
            if attr in el.attrs:
                del el[attr]

    # ---- Phase 4: sanitize <style> element contents ----
    for style_el in soup.find_all('style'):
        if style_el.string is not None:
            style_el.string = sanitize_css(style_el.string)
        else:
            for child in style_el.contents:
                if hasattr(child, 'string') and child.string is not None:
                    child.string = sanitize_css(child.string)

    return str(soup)


# ============================================================================
# Entry point
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: filter.py <html_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    filtered = sanitize_html(content)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(filtered)


if __name__ == '__main__':
    main()
