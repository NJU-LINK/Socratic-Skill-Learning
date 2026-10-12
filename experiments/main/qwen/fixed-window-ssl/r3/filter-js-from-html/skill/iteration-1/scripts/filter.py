#!/usr/bin/env python3
"""
HTML JavaScript sanitizer - removes executable JavaScript behavior from HTML files.
Handles SVG, MathML, and namespace-aware markup while preserving safe content.

Design principles:
- Remove only tags that are inherently script-execution containers (script, iframe, object, embed, applet)
- Remove <base> tags (combination attack: rewrites all relative URLs)
- For all other tags (forms, links, meta, SVG elements, MathML elements), sanitize at the attribute level
- Neutralize javascript:/vbscript:/livescript:/mhtml: URLs, event handlers, dangerous CSS, and data: URLs
- Handle SVG animation elements that can dynamically set dangerous attributes
- Decode percent-encoding and HTML entities to catch obfuscated payloads
- Sanitize <style> element text content for dangerous CSS
- Preserve document structure, visible content, forms, links, images, and non-dangerous attributes
"""

import sys
import re
import html
from urllib.parse import unquote
from bs4 import BeautifulSoup, Comment

# Tags that are entirely dangerous and should be removed completely.
DANGEROUS_TAGS_REMOVE = frozenset([
    'script',
    'iframe',
    'object',
    'embed',
    'applet',
    'isindex',
    'base',  # Combination attack: rewrites all relative URLs
])

# Attributes that can contain URLs (potential javascript: or data: vectors)
URL_ATTRIBUTES = frozenset([
    'href', 'src', 'action', 'formaction', 'data', 'codebase',
    'dynsrc', 'lowsrc', 'background', 'poster', 'srcset',
    'xlink:href',
    'usemap', 'longdesc', 'profile', 'cite',
    'manifest', 'ping',
])

# SVG animation elements that can dynamically change attributes
SVG_ANIMATION_TAGS = frozenset([
    'animate', 'animatecolor', 'animatemotion', 'animatetransform', 'set'
])

# SVG animation attributes that can contain URLs or target dangerous attributes
SVG_ANIM_URL_ATTRS = frozenset(['values', 'to', 'from', 'by'])

# Event handler attribute pattern: on* followed by event name
EVENT_HANDLER_RE = re.compile(r'^on[a-z]', re.IGNORECASE)

# Dangerous URL protocol pattern: javascript:, vbscript:, livescript:, mhtml:
# Handles whitespace, entities, case variations between characters
DANGEROUS_URL_RE = re.compile(
    r'^[\s\x00]*(?:'
    r'j[\s\x00]*a[\s\x00]*v[\s\x00]*a[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
    r'|v[\s\x00]*b[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
    r'|l[\s\x00]*i[\s\x00]*v[\s\x00]*e[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
    r'|m[\s\x00]*h[\s\x00]*t[\s\x00]*m[\s\x00]*l'
    r')[\s\x00]*:',
    re.IGNORECASE
)

# Dangerous CSS patterns
DANGEROUS_CSS_RE = re.compile(
    r'(expression\s*\(|-moz-binding\s*:|behavior\s*:|url\s*\(\s*["\']?\s*(?:javascript|vbscript|livescript)\s*:)',
    re.IGNORECASE
)

# http-equiv refresh pattern
REFRESH_RE = re.compile(r'^refresh$', re.IGNORECASE)


def decode_entities(s):
    """Decode HTML entities in a string for inspection."""
    if not s:
        return s
    try:
        return html.unescape(s)
    except Exception:
        return s


def normalize_for_check(s):
    """Normalize a string for dangerous pattern checking.
    Removes null bytes, decodes entities and percent-encoding, collapses whitespace."""
    if not s:
        return s
    decoded = decode_entities(s)
    try:
        decoded = unquote(decoded)
    except Exception:
        pass
    cleaned = decoded.replace('\x00', '')
    return cleaned


def is_dangerous_url(value):
    """Check if a value starts with a dangerous URL protocol."""
    if not value:
        return False
    
    # Check raw value
    if DANGEROUS_URL_RE.match(value):
        return True
    
    # Decode entities and percent-encoding, then check
    normalized = normalize_for_check(value)
    if DANGEROUS_URL_RE.match(normalized):
        return True
    
    # Remove all whitespace and check
    no_space = re.sub(r'\s+', '', normalized)
    if re.match(r'^(?:javascript|vbscript|livescript|mhtml):', no_space, re.IGNORECASE):
        return True
    
    return False


def is_dangerous_data_url(value):
    """Check if a data: URL could embed executable HTML."""
    if not value:
        return False
    normalized = normalize_for_check(value)
    cleaned = re.sub(r'\s+', '', normalized)
    if re.match(r'^data:\s*(text/html|application/xhtml)', cleaned, re.IGNORECASE):
        return True
    return False


def has_dangerous_style(value):
    """Check if a style attribute contains dangerous CSS."""
    if not value:
        return False
    normalized = normalize_for_check(value)
    return bool(DANGEROUS_CSS_RE.search(normalized))


def sanitize_css_text(css_text):
    """Sanitize CSS text content (from <style> elements or style attributes).
    Removes dangerous expressions, -moz-binding, behavior, and url(javascript:...) patterns.
    Returns the cleaned CSS text."""
    if not css_text:
        return css_text
    normalized = normalize_for_check(css_text)
    
    # Remove expression(...) with nested parentheses support
    cleaned = re.sub(r'expression\s*\([^()]*(?:\([^()]*\)[^()]*)*\)', '', normalized, flags=re.IGNORECASE)
    
    # Remove @import with dangerous URLs - match entire @import statement up to semicolon
    # This handles nested parentheses in the URL (like alert(1))
    cleaned = re.sub(
        r'@import\s+[^;]*(?:javascript|vbscript|livescript|mhtml)[^;]*;?',
        '', cleaned, flags=re.IGNORECASE
    )
    
    # Remove url(javascript:...) or url(vbscript:...) etc.
    cleaned = re.sub(
        r'url\s*\(\s*["\']?\s*(?:javascript|vbscript|livescript|mhtml)\s*:[^)]*\)',
        '', cleaned, flags=re.IGNORECASE
    )
    
    # Remove -moz-binding
    cleaned = re.sub(r'-moz-binding\s*:[^;{}]*;?', '', cleaned, flags=re.IGNORECASE)
    # Remove behavior
    cleaned = re.sub(r'behavior\s*:[^;{}]*;?', '', cleaned, flags=re.IGNORECASE)
    
    return cleaned


def sanitize_style_value(value):
    """Sanitize an inline style attribute value."""
    if not value:
        return value
    return sanitize_css_text(value)


def is_event_handler(attr_name):
    """Check if an attribute name is an event handler (on*)."""
    return bool(EVENT_HANDLER_RE.match(attr_name))


def should_remove_tag_completely(tag):
    """Determine if a tag should be completely removed from the document."""
    tag_name = tag.name.lower() if tag.name else ''
    return tag_name in DANGEROUS_TAGS_REMOVE


def sanitize_tag_attributes(tag):
    """Remove or neutralize dangerous attributes on a tag while preserving safe ones."""
    if not tag or not hasattr(tag, 'attrs'):
        return
    
    tag_name = tag.name.lower() if tag.name else ''
    is_svg_animation = tag_name in SVG_ANIMATION_TAGS
    
    attrs_to_remove = []
    attrs_to_modify = {}
    
    for attr_name in list(tag.attrs.keys()):
        attr_lower = attr_name.lower()
        
        # 1. Remove all event handlers (on* attributes)
        if is_event_handler(attr_lower):
            attrs_to_remove.append(attr_name)
            continue
        
        # 2. Check URL-bearing attributes for dangerous URLs
        if attr_lower in URL_ATTRIBUTES:
            value = tag.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(str(v) for v in value)
            value_str = str(value)
            
            if is_dangerous_url(value_str):
                attrs_to_modify[attr_name] = 'about:blank'
            elif is_dangerous_data_url(value_str):
                attrs_to_modify[attr_name] = 'about:blank'
            continue
        
        # 3. Check SVG animation attributes for dangerous URLs
        if is_svg_animation and attr_lower in SVG_ANIM_URL_ATTRS:
            value = tag.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(str(v) for v in value)
            value_str = str(value)
            
            values_list = re.split(r'[;\s]+', value_str)
            has_dangerous = False
            for v in values_list:
                if is_dangerous_url(v) or is_dangerous_data_url(v):
                    has_dangerous = True
                    break
            
            if has_dangerous:
                attrs_to_remove.append(attr_name)
            continue
        
        # 4. Check SVG animation attributeName targeting event handlers
        if is_svg_animation and attr_lower == 'attributename':
            value = tag.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(str(v) for v in value)
            value_str = str(value).strip()
            if is_event_handler(value_str):
                attrs_to_remove.append(attr_name)
            continue
        
        # 5. Check style attributes for dangerous CSS
        if attr_lower == 'style':
            value = tag.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(str(v) for v in value)
            value_str = str(value)
            if has_dangerous_style(value_str):
                cleaned = sanitize_style_value(value_str)
                if cleaned:
                    attrs_to_modify[attr_name] = cleaned
                else:
                    attrs_to_remove.append(attr_name)
            continue
        
        # 6. Handle meta http-equiv=refresh with dangerous content
        if attr_lower == 'http-equiv' and tag_name == 'meta':
            value = str(tag.attrs[attr_name])
            if REFRESH_RE.match(value.strip()):
                content = tag.get('content', '')
                if isinstance(content, list):
                    content = ' '.join(str(c) for c in content)
                content_str = str(content)
                # Check if content contains dangerous URL
                if is_dangerous_url(content_str) or is_dangerous_data_url(content_str):
                    # Remove both http-equiv AND content to fully neutralize
                    attrs_to_remove.append(attr_name)
                    if 'content' in tag.attrs:
                        attrs_to_remove.append('content')
                elif 'url=' in content_str.lower():
                    url_match = re.search(r'url\s*=\s*(.+)', content_str, re.IGNORECASE)
                    if url_match:
                        url_part = url_match.group(1).strip().strip("'\"")
                        if is_dangerous_url(url_part):
                            attrs_to_remove.append(attr_name)
                            if 'content' in tag.attrs:
                                attrs_to_remove.append('content')
            continue
    
    # Apply changes
    for attr_name in attrs_to_remove:
        if attr_name in tag.attrs:
            del tag.attrs[attr_name]
    
    for attr_name, new_value in attrs_to_modify.items():
        tag.attrs[attr_name] = new_value


def process_html(html_content):
    """Process HTML content and remove executable JavaScript."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # First pass: remove entirely dangerous tags
    for tag in soup.find_all(list(DANGEROUS_TAGS_REMOVE)):
        tag.decompose()
    
    # Second pass: sanitize all remaining tags' attributes
    for tag in soup.find_all(True):
        sanitize_tag_attributes(tag)
    
    # Third pass: sanitize <style> element text content
    for style_tag in soup.find_all('style'):
        if style_tag.string:
            original = style_tag.string
            cleaned = sanitize_css_text(original)
            if cleaned != original:
                style_tag.string = cleaned
    
    # Handle comments that might contain conditional compilation scripts
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment_text = str(comment)
        if re.search(r'<script', comment_text, re.IGNORECASE):
            comment.extract()
    
    return str(soup)


def main():
    if len(sys.argv) < 2:
        print("Usage: filter.py <html_file>", file=sys.stderr)
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found.", file=sys.stderr)
        sys.exit(1)
    
    sanitized = process_html(html_content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(sanitized)


if __name__ == '__main__':
    main()
