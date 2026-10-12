#!/usr/bin/env python3
"""
HTML JavaScript sanitizer - removes executable JavaScript behavior from HTML files.
Handles SVG, MathML, and namespace-aware markup.
Preserves legitimate document structure, visible content, vector graphics,
equations, forms, links, and non-dangerous attributes.
"""

import sys
import re
from bs4 import BeautifulSoup, Comment


# ---------------------------------------------------------------------------
# Configuration: tags to remove entirely
# ---------------------------------------------------------------------------

REMOVE_TAGS_COMPLETELY = {
    'script',
    'iframe',
    'object',
    'embed',
    'applet',
}


# ---------------------------------------------------------------------------
# URL-based danger detection
# ---------------------------------------------------------------------------

URL_ATTRIBUTES = {
    'href', 'src', 'action', 'formaction', 'data', 'poster',
    'dynsrc', 'lowsrc', 'background', 'codebase', 'classid',
    'usemap', 'longdesc', 'ping', 'srcdoc',
    # SVG-specific URL attributes
    'xlink:href',
    'cursor',
    # MathML
    'actionurl',
    'altimg',
}

URL_ATTRIBUTES_LOWER = {a.lower() for a in URL_ATTRIBUTES}


def _strip_for_url_check(value):
    """Strip whitespace, null bytes, and control characters for URL protocol detection."""
    if not value or not isinstance(value, str):
        return ''
    return re.sub(r'[\s\x00-\x1f\x7f]+', '', value).lower()


def is_javascript_url(value):
    """Check if a value is a javascript: or vbscript: URL after normalization."""
    cleaned = _strip_for_url_check(value)
    if not cleaned:
        return False
    return cleaned.startswith('javascript:') or cleaned.startswith('vbscript:')


def is_dangerous_data_url(value):
    """Check if a data: URL could embed executable HTML/SVG/XML."""
    cleaned = _strip_for_url_check(value)
    if not cleaned:
        return False
    if cleaned.startswith('data:'):
        mime_match = re.match(r'data:([^,;]+)', cleaned)
        if mime_match:
            mime = mime_match.group(1).strip()
            dangerous_mimes = {
                'text/html', 'application/xhtml+xml', 'image/svg+xml',
                'application/xml', 'text/xml', 'text/x-html-cgi',
            }
            if mime in dangerous_mimes:
                return True
        if cleaned.startswith('data:text/html') or cleaned.startswith('data:image/svg'):
            return True
    return False


def is_event_handler_attr(attr_name):
    """Check if an attribute name is an on* event handler."""
    return attr_name.lower().startswith('on')


# ---------------------------------------------------------------------------
# CSS danger detection and sanitization
# ---------------------------------------------------------------------------

DANGEROUS_CSS_PATTERNS = [
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'behavior\s*:', re.IGNORECASE),
    re.compile(r'-moz-binding\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*javascript\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*vbscript\s*:', re.IGNORECASE),
    re.compile(r'@import\s+["\']?\s*javascript\s*:', re.IGNORECASE),
    re.compile(r'@import\s+url\s*\(\s*["\']?\s*javascript\s*:', re.IGNORECASE),
]


def has_dangerous_css(content):
    """Check if CSS content contains dangerous constructs."""
    if not content:
        return False
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(content):
            return True
    return False


def _remove_balanced_parens(text, keyword_pattern, flags=re.IGNORECASE):
    """
    Remove keyword(...) where ... may contain nested parentheses.
    E.g., expression(alert('XSS')) -> ''
    """
    result = text
    while True:
        match = re.search(keyword_pattern, result, flags)
        if not match:
            break
        start = match.start()
        paren_pos = match.end() - 1
        if paren_pos >= len(result) or result[paren_pos] != '(':
            result = result[:start] + result[match.end():]
            continue
        paren_count = 0
        i = paren_pos
        found = False
        while i < len(result):
            if result[i] == '(':
                paren_count += 1
            elif result[i] == ')':
                paren_count -= 1
                if paren_count == 0:
                    result = result[:start] + result[i+1:]
                    found = True
                    break
            i += 1
        if not found:
            result = result[:start]
            break
    return result


def sanitize_css_content(css_text):
    """Remove dangerous CSS constructs while preserving safe styles."""
    if not css_text:
        return css_text

    result = _remove_balanced_parens(css_text, r'expression\s*\(')
    result = re.sub(r'behavior\s*:[^;{}]*;?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'-moz-binding\s*:[^;{}]*;?', '', result, flags=re.IGNORECASE)
    result = re.sub(
        r'url\s*\(\s*["\']?\s*(?:javascript|vbscript)\s*:[^)]*\)',
        "url('about:blank')",
        result,
        flags=re.IGNORECASE
    )
    result = re.sub(
        r'@import\s+(?:url\s*\(\s*["\']?\s*)?(?:javascript|vbscript)\s*:[^;]*;?',
        '',
        result,
        flags=re.IGNORECASE
    )
    return result


# ---------------------------------------------------------------------------
# SVG animation element sanitization
# ---------------------------------------------------------------------------

SVG_ANIMATION_TAGS = {'set', 'animate', 'animatetransform', 'animatemotion', 'animatecolor'}


def _value_contains_dangerous_url(value):
    """
    Check if a value (or semicolon-separated list of values) contains a dangerous URL.
    SVG animation 'values' attributes use semicolons to separate keyframe values.
    """
    if not value:
        return False
    # Check the whole value first
    if is_javascript_url(value) or is_dangerous_data_url(value):
        return True
    # For 'values' attribute, check each semicolon-separated value
    for part in value.split(';'):
        part = part.strip()
        if is_javascript_url(part) or is_dangerous_data_url(part):
            return True
    return False


def is_dangerous_svg_animation(tag):
    """
    Check if an SVG animation element is dangerous.

    SVG animation elements (<set>, <animate>, <animateTransform>, <animateMotion>,
    <animateColor>) can modify ANY attribute on a target element. They are dangerous if:

    1. The animation element itself has on* event handlers
    2. The animation element has javascript:/vbscript: URLs in its own URL attributes
    3. The animation targets (via attributeName) an event handler attribute
    4. The animation targets a URL-bearing attribute and sets it to a javascript:/vbscript:/dangerous data URL
    5. The animation targets a style attribute and sets it to dangerous CSS
    """
    tag_name = tag.name.lower() if tag.name else ''
    if tag_name not in SVG_ANIMATION_TAGS:
        return False

    # Check 1: on* handlers on the animation element itself
    for attr_name in tag.attrs:
        if is_event_handler_attr(attr_name):
            return True

    # Check 2: javascript:/vbscript: URLs in the animation element's own URL attributes
    for attr_name in ('href', 'xlink:href'):
        val = tag.get(attr_name, '')
        if is_javascript_url(str(val)):
            return True

    # Check 3-5: What attribute is being targeted?
    target_attr = (tag.get('attributename') or '').lower()

    if target_attr:
        # 3: Setting an event handler (e.g., attributeName="onmouseover")
        if target_attr.startswith('on'):
            return True

        # 4: Setting a URL-bearing attribute with a dangerous value
        if target_attr in URL_ATTRIBUTES_LOWER:
            for val_attr in ('to', 'from', 'values'):
                val = tag.get(val_attr, '')
                if val and _value_contains_dangerous_url(str(val)):
                    return True

        # 5: Setting a style attribute with dangerous CSS
        if target_attr == 'style':
            for val_attr in ('to', 'from', 'values'):
                val = tag.get(val_attr, '')
                if val and has_dangerous_css(str(val)):
                    return True

    return False


# ---------------------------------------------------------------------------
# Main sanitization logic
# ---------------------------------------------------------------------------

def sanitize_soup(soup):
    """Apply all sanitization rules to a BeautifulSoup tree."""

    # --- Pass 1: Remove entirely dangerous tags ---
    for tag_name in REMOVE_TAGS_COMPLETELY:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # --- Pass 2: Handle <base> tags ---
    for base in soup.find_all('base'):
        href = base.get('href', '')
        if is_javascript_url(href):
            base.decompose()

    # --- Pass 3: Handle <meta http-equiv="refresh"> ---
    for meta in soup.find_all('meta'):
        http_equiv = meta.get('http-equiv', '')
        if http_equiv and http_equiv.lower() == 'refresh':
            content = meta.get('content', '')
            if is_javascript_url(content):
                meta.decompose()
            else:
                cleaned = _strip_for_url_check(content)
                if 'javascript:' in cleaned or 'vbscript:' in cleaned:
                    meta.decompose()

    # --- Pass 4: Handle <link> tags with dangerous URLs ---
    for link in soup.find_all('link'):
        href = link.get('href', '')
        if is_javascript_url(href):
            link.decompose()

    # --- Pass 5: Sanitize <style> tags ---
    for style_tag in soup.find_all('style'):
        css = style_tag.string or ''
        if has_dangerous_css(css):
            sanitized_css = sanitize_css_content(css)
            stripped = sanitized_css.strip()
            if not stripped:
                style_tag.decompose()
            else:
                style_tag.string = sanitized_css

    # --- Pass 6: Remove dangerous SVG animation elements ---
    for tag_name in SVG_ANIMATION_TAGS:
        for tag in soup.find_all(tag_name):
            if is_dangerous_svg_animation(tag):
                tag.decompose()

    # --- Pass 7: Walk all remaining tags and sanitize attributes ---
    for tag in soup.find_all(True):
        attrs_to_remove = []

        for attr_name in list(tag.attrs.keys()):
            attr_value = tag.attrs[attr_name]

            if isinstance(attr_value, list):
                attr_value_str = ' '.join(str(v) for v in attr_value)
            else:
                attr_value_str = str(attr_value) if attr_value else ''

            # Remove on* event handlers
            if is_event_handler_attr(attr_name):
                attrs_to_remove.append(attr_name)
                continue

            # Check URL-bearing attributes for javascript: URLs
            attr_lower = attr_name.lower()
            if attr_lower in URL_ATTRIBUTES_LOWER:
                if is_javascript_url(attr_value_str):
                    attrs_to_remove.append(attr_name)
                    continue
                if is_dangerous_data_url(attr_value_str):
                    attrs_to_remove.append(attr_name)
                    continue

            # Check style attributes for dangerous CSS
            if attr_lower == 'style':
                if has_dangerous_css(attr_value_str):
                    sanitized = sanitize_css_content(attr_value_str)
                    if sanitized.strip():
                        tag[attr_name] = sanitized.strip()
                    else:
                        attrs_to_remove.append(attr_name)
                    continue

        for attr_name in attrs_to_remove:
            if attr_name in tag.attrs:
                del tag[attr_name]

    # --- Pass 8: Handle <template> contents ---
    for template in soup.find_all('template'):
        for script in template.find_all('script'):
            script.decompose()
        for tag in template.find_all(True):
            for attr_name in list(tag.attrs.keys()):
                if is_event_handler_attr(attr_name):
                    del tag[attr_name]

    # --- Pass 9: Remove dangerous comments ---
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment_text = str(comment)
        if re.search(r'\[if\s+', comment_text, re.IGNORECASE):
            comment.extract()
        if '<script' in comment_text.lower():
            comment.extract()

    # --- Pass 10: Handle <foreignObject> in SVG ---
    for fo in soup.find_all('foreignobject'):
        for dangerous_tag in fo.find_all(['script', 'iframe', 'object', 'embed']):
            dangerous_tag.decompose()
        for tag in fo.find_all(True):
            for attr_name in list(tag.attrs.keys()):
                if is_event_handler_attr(attr_name):
                    del tag[attr_name]
                attr_lower = attr_name.lower()
                if attr_lower in URL_ATTRIBUTES_LOWER:
                    val = tag.attrs.get(attr_name, '')
                    if isinstance(val, list):
                        val = ' '.join(str(v) for v in val)
                    if is_javascript_url(str(val)):
                        del tag[attr_name]

    # --- Pass 11: Handle form-related elements ---
    for form in soup.find_all('form'):
        action = form.get('action', '')
        if is_javascript_url(action):
            del form['action']

    for tag_name in ('input', 'button'):
        for tag in soup.find_all(tag_name):
            formaction = tag.get('formaction', '')
            if is_javascript_url(formaction):
                del tag['formaction']


def sanitize_html(html_content):
    """Main entry point: sanitize HTML content string."""
    # Pre-process: handle null bytes
    html_content = html_content.replace('\x00', '')

    # Parse with html.parser to preserve document structure
    soup = BeautifulSoup(html_content, 'html.parser')

    # Apply sanitization
    sanitize_soup(soup)

    # Serialize back to string
    return str(soup)


def main():
    if len(sys.argv) < 2:
        print("Usage: filter.py <html_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)

    sanitized = sanitize_html(content)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(sanitized)
    except Exception as e:
        print(f"Error writing file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
