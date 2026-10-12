#!/usr/bin/env python3
"""
HTML JavaScript sanitizer.
Removes executable JavaScript behavior from HTML files while preserving
legitimate document structure, visible content, vector graphics, equations,
forms, links, and non-dangerous attributes.

Usage: python filter.py <html_file>
Modifies the file in-place.
"""

import sys
import re
import html as html_module
from bs4 import BeautifulSoup, Comment, NavigableString, Tag


# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

DANGEROUS_TAGS_REMOVE = frozenset([
    'script', 'iframe', 'object', 'embed', 'applet',
    'frame', 'frameset',
])

URL_ATTRIBUTES = frozenset([
    'href', 'src', 'action', 'formaction', 'data', 'poster',
    'background', 'dynsrc', 'lowsrc', 'srcdoc',
    'xlink:href', 'ping', 'cite', 'usemap', 'longdesc',
])

SVG_ANIMATION_TAGS = frozenset([
    'animate', 'set', 'animatetransform',
    'animatemotion', 'animatecolor',
])

EVENT_HANDLER_RE = re.compile(r'^on[a-z]', re.IGNORECASE)

DANGEROUS_PROTOCOLS_RE = re.compile(
    r'^\s*(?:javascript|vbscript|livescript)\s*:', re.IGNORECASE
)

# CSS patterns used to DETECT danger (binary decision, not for stripping)
DANGEROUS_CSS_PATTERNS = [
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'javascript\s*:', re.IGNORECASE),
    re.compile(r'vbscript\s*:', re.IGNORECASE),
    re.compile(r'-moz-binding\s*:', re.IGNORECASE),
    re.compile(r'behavior\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*(?:javascript|vbscript|data\s*:\s*text/html)', re.IGNORECASE),
]

# Precompiled patterns for removing dangerous HTML tags from <style> content
_STYLE_HTML_CLEANUP = []
for _tag in ('script', 'iframe', 'object', 'embed', 'applet', 'frame', 'frameset'):
    _STYLE_HTML_CLEANUP.append(re.compile(
        r'<\s*' + _tag + r'[^>]*>.*?<\s*/\s*' + _tag + r'\s*>',
        re.IGNORECASE | re.DOTALL
    ))
_STYLE_ANY_TAG_RE = re.compile(r'<[^>]*>')

# Regex for meta refresh: tolerates whitespace around url=
_META_REFRESH_URL_RE = re.compile(r';\s*url\s*=\s*(.+)', re.IGNORECASE)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def strip_null_bytes(value):
    """Remove null bytes and control characters that browsers ignore."""
    if not value:
        return value
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)


def normalize_for_protocol_check(value):
    """
    Decode and normalize an attribute value so that protocol checks
    cannot be bypassed through entity encoding, null bytes, tabs,
    newlines, or other whitespace tricks.
    """
    if not value:
        return ""
    decoded = html_module.unescape(value)
    decoded = strip_null_bytes(decoded)
    decoded = re.sub(r'\s+', '', decoded)
    return decoded


def is_dangerous_url(value):
    """Return True if a URL attribute value is dangerous."""
    if not value:
        return False
    normalized = normalize_for_protocol_check(value)
    if DANGEROUS_PROTOCOLS_RE.match(normalized):
        return True
    normalized_lower = normalized.lower()
    if normalized_lower.startswith('data:'):
        safe_data_prefixes = (
            'data:image/png;base64,',
            'data:image/jpeg;base64,',
            'data:image/jpg;base64,',
            'data:image/gif;base64,',
            'data:image/webp;base64,',
            'data:image/bmp;base64,',
            'data:image/x-icon;base64,',
        )
        if normalized_lower.startswith('data:image/svg+xml'):
            return True
        for prefix in safe_data_prefixes:
            if normalized_lower.startswith(prefix):
                return False
        return True
    return False


def is_dangerous_style(value):
    """
    Binary check: returns True if a style attribute value contains ANY
    dangerous CSS pattern. Used to decide whether to REMOVE the entire
    attribute — not for partial sanitization.
    """
    if not value:
        return False
    decoded = html_module.unescape(value)
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(decoded):
            return True
    return False


def clean_style_content(css_text):
    """
    Remove dangerous CSS constructs and any embedded HTML tags from
    <style> block text content. Used ONLY for <style> tag bodies,
    NOT for style="" attribute values (those are removed entirely).
    """
    if not css_text:
        return css_text

    # Remove dangerous HTML tags and their content from CSS
    for pattern in _STYLE_HTML_CLEANUP:
        css_text = pattern.sub('', css_text)
    # Remove any remaining HTML-like tags
    css_text = _STYLE_ANY_TAG_RE.sub('', css_text)

    # Remove dangerous CSS patterns
    css_text = re.sub(r'expression\s*\([^)]*\)', 'none', css_text, flags=re.IGNORECASE)
    css_text = re.sub(
        r'url\s*\(\s*["\']?\s*(?:javascript|vbscript|data\s*:\s*text/html)[^)]*\)',
        'none', css_text, flags=re.IGNORECASE
    )
    css_text = re.sub(r'-moz-binding\s*:[^;}\n]*', '', css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'behavior\s*:[^;}\n]*', '', css_text, flags=re.IGNORECASE)
    css_text = re.sub(
        r'@import\s+url\s*\(\s*["\']?\s*(?:javascript|vbscript)[^)]*\)\s*;?',
        '', css_text, flags=re.IGNORECASE
    )
    return css_text


def sanitize_meta_refresh(meta_tag):
    """
    Check <meta http-equiv="refresh"> for dangerous URLs.
    Handles whitespace variations: url=, URL =, url = , etc.
    Uses both regex extraction and full-content normalization as fallback.
    """
    content = meta_tag.get('content', '')
    if isinstance(content, list):
        content = ' '.join(content)
    content = str(content)

    # Approach 1: Regex with \s* tolerates whitespace around url=
    match = _META_REFRESH_URL_RE.search(content)
    if match:
        url_part = match.group(1).strip().strip("'\"")
        if is_dangerous_url(url_part):
            return True

    # Approach 2 (fallback): Normalize entire content, check for dangerous protocols
    normalized = normalize_for_protocol_check(content)
    if 'javascript:' in normalized.lower() or 'vbscript:' in normalized.lower():
        return True

    return False


def is_svg_animation_dangerous(tag):
    """
    Check if an SVG animation element targets dangerous attributes.
    Note: BS4 lowercases attributeName to attributename.
    """
    attr_name = tag.get('attributename', '') or tag.get('attributeName', '')
    if isinstance(attr_name, list):
        attr_name = ' '.join(attr_name)
    attr_name = str(attr_name).strip().lower()
    if not attr_name:
        return False

    if EVENT_HANDLER_RE.match(attr_name):
        return True

    url_target_attrs = {'href', 'xlink:href', 'src', 'action', 'formaction'}
    if attr_name in url_target_attrs:
        for val_attr in ('from', 'to', 'values', 'by'):
            val = tag.get(val_attr, '')
            if isinstance(val, list):
                val = ' '.join(val)
            if is_dangerous_url(str(val)):
                return True

    if attr_name == 'style':
        for val_attr in ('from', 'to', 'values', 'by'):
            val = tag.get(val_attr, '')
            if isinstance(val, list):
                val = ' '.join(val)
            if is_dangerous_style(str(val)):
                return True

    return False


# ---------------------------------------------------------------------------
#  Main sanitization
# ---------------------------------------------------------------------------

def sanitize_html(html_content):
    """
    Sanitize HTML content to remove all JavaScript execution vectors
    while preserving legitimate document structure and content.
    """
    # Preprocess: strip null bytes before parsing
    html_content = strip_null_bytes(html_content)
    soup = BeautifulSoup(html_content, 'html.parser')

    # Phase 1: Remove inherently dangerous tags (decompose entire subtree)
    for tag_name in DANGEROUS_TAGS_REMOVE:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Phase 2: SVG-specific dangers
    for fo in soup.find_all('foreignobject'):
        fo.decompose()
    for anim_tag_name in SVG_ANIMATION_TAGS:
        for tag in soup.find_all(anim_tag_name):
            if is_svg_animation_dangerous(tag):
                tag.decompose()

    # Phase 3: Meta refresh with dangerous URLs
    for meta in soup.find_all('meta'):
        http_equiv = meta.get('http-equiv', '')
        if isinstance(http_equiv, list):
            http_equiv = ' '.join(http_equiv)
        if str(http_equiv).lower().strip() == 'refresh':
            if sanitize_meta_refresh(meta):
                meta.decompose()

    # Phase 4: Base tag with dangerous protocol
    for base in soup.find_all('base'):
        href = base.get('href', '')
        if isinstance(href, list):
            href = ' '.join(href)
        if is_dangerous_url(str(href)):
            base.decompose()

    # Phase 5: Link tags with dangerous protocol
    for link in soup.find_all('link'):
        href = link.get('href', '')
        if isinstance(href, list):
            href = ' '.join(href)
        if is_dangerous_url(str(href)):
            link.decompose()

    # Phase 6: Clean <style> tag text content (only for tag bodies)
    for style_tag in soup.find_all('style'):
        if style_tag.string:
            style_tag.string = clean_style_content(style_tag.string)
        elif style_tag.contents:
            for child in list(style_tag.children):
                if isinstance(child, NavigableString):
                    child.replace_with(clean_style_content(str(child)))

    # Phase 7: Attribute sanitization on ALL remaining elements
    for tag in soup.find_all(True):
        attrs_to_remove = []
        for attr_name in list(tag.attrs.keys()):
            attr_lower = attr_name.lower()

            # Remove event handler attributes entirely
            if EVENT_HANDLER_RE.match(attr_name):
                attrs_to_remove.append(attr_name)
                continue

            # Remove dangerous URL-bearing attributes entirely
            if attr_lower in URL_ATTRIBUTES:
                value = tag.attrs[attr_name]
                if isinstance(value, list):
                    value = ' '.join(value)
                if is_dangerous_url(str(value)):
                    attrs_to_remove.append(attr_name)
                    continue

            # Remove dangerous style attributes ENTIRELY
            # DO NOT attempt partial sanitization — regex-based stripping
            # of CSS url() is unreliable with nested parentheses
            if attr_lower == 'style':
                value = tag.attrs[attr_name]
                if isinstance(value, list):
                    value = ' '.join(value)
                if is_dangerous_style(str(value)):
                    attrs_to_remove.append(attr_name)
                    continue

        for attr_name in attrs_to_remove:
            if attr_name in tag.attrs:
                del tag.attrs[attr_name]

    # Phase 8: Remove IE conditional comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment_text = str(comment)
        if re.search(r'\[if\s+', comment_text, re.IGNORECASE):
            comment.extract()
        elif re.search(r'\[endif\]', comment_text, re.IGNORECASE):
            comment.extract()

    return str(soup)


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python filter.py <html_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]

    try:
        with open(filepath, 'r', encoding='utf-8', errors='surrogateescape') as f:
            content = f.read()
    except (OSError, IOError) as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        sys.exit(1)

    sanitized = sanitize_html(content)

    try:
        with open(filepath, 'w', encoding='utf-8', errors='surrogateescape') as f:
            f.write(sanitized)
    except (OSError, IOError) as e:
        print(f"Error writing {filepath}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
