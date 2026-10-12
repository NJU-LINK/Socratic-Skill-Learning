#!/usr/bin/env python3
"""
HTML JavaScript sanitizer - removes executable JavaScript behavior from HTML files.
Handles SVG, MathML, and namespace-aware markup while preserving safe content.

Key design decisions:
- Dangerous URL attributes are REMOVED ENTIRELY, not replaced with about:blank
- Meta refresh with dangerous URLs: remove the ENTIRE meta tag
- CSS sanitization uses "clean or remove" philosophy: if sanitized CSS has empty/garbage
  property values, remove the entire style attribute
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
    'base',
])

# Attributes that can contain URLs
URL_ATTRIBUTES = frozenset([
    'href', 'src', 'action', 'formaction', 'data', 'codebase',
    'dynsrc', 'lowsrc', 'background', 'poster', 'srcset',
    'xlink:href',
    'usemap', 'longdesc', 'profile', 'cite',
    'manifest', 'ping',
])

# SVG animation elements
SVG_ANIMATION_TAGS = frozenset([
    'animate', 'animatecolor', 'animatemotion', 'animatetransform', 'set'
])

SVG_ANIM_URL_ATTRS = frozenset(['values', 'to', 'from', 'by'])

EVENT_HANDLER_RE = re.compile(r'^on[a-z]', re.IGNORECASE)

# Dangerous URL protocol pattern: javascript:, vbscript:, livescript:, mhtml:
# Note: [\s\x00] matches whitespace and null bytes for obfuscation handling
DANGEROUS_URL_RE = re.compile(
    r'^[\s\x00]*(?:'
    r'j[\s\x00]*a[\s\x00]*v[\s\x00]*a[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
    r'|v[\s\x00]*b[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
    r'|l[\s\x00]*i[\s\x00]*v[\s\x00]*e[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
    r'|m[\s\x00]*h[\s\x00]*t[\s\x00]*m[\s\x00]*l'
    r')[\s\x00]*:',
    re.IGNORECASE
)

DANGEROUS_CSS_RE = re.compile(
    r'(expression\s*\(|-moz-binding\s*:|behavior\s*:|url\s*\(\s*["\']?\s*(?:javascript|vbscript|livescript)\s*:)',
    re.IGNORECASE
)

REFRESH_RE = re.compile(r'^refresh$', re.IGNORECASE)
META_URL_RE = re.compile(r'url\s*=\s*(.+)', re.IGNORECASE)


def decode_entities(s):
    if not s:
        return s
    try:
        return html.unescape(s)
    except Exception:
        return s


def normalize_for_check(s):
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
    if not value:
        return False
    if DANGEROUS_URL_RE.match(value):
        return True
    normalized = normalize_for_check(value)
    if DANGEROUS_URL_RE.match(normalized):
        return True
    no_space = re.sub(r'\s+', '', normalized)
    if re.match(r'^(?:javascript|vbscript|livescript|mhtml):', no_space, re.IGNORECASE):
        return True
    return False


def is_dangerous_data_url(value):
    if not value:
        return False
    normalized = normalize_for_check(value)
    cleaned = re.sub(r'\s+', '', normalized)
    if re.match(r'^data:\s*(text/html|application/xhtml)', cleaned, re.IGNORECASE):
        return True
    return False


def has_dangerous_style(value):
    if not value:
        return False
    normalized = normalize_for_check(value)
    return bool(DANGEROUS_CSS_RE.search(normalized))


def sanitize_css_text(css_text):
    """Sanitize CSS text content."""
    if not css_text:
        return css_text
    normalized = normalize_for_check(css_text)
    
    cleaned = re.sub(r'expression\s*\([^()]*(?:\([^()]*\)[^()]*)*\)', '', normalized, flags=re.IGNORECASE)
    cleaned = re.sub(
        r'@import\s+[^;]*(?:javascript|vbscript|livescript|mhtml)[^;]*;?',
        '', cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r'url\s*\(\s*["\']?\s*(?:javascript|vbscript|livescript|mhtml)\s*:[^)]*\)',
        '', cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r'-moz-binding\s*:[^;{}]*;?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'behavior\s*:[^;{}]*;?', '', cleaned, flags=re.IGNORECASE)
    
    return cleaned


def is_clean_css(css_text):
    """Check if sanitized CSS has no empty/garbage property values."""
    if not css_text:
        return True
    
    declarations = re.findall(r'([a-zA-Z-]+)\s*:\s*([^;{}]+)', css_text)
    
    for prop, val in declarations:
        val_stripped = val.strip()
        if not re.search(r'[a-zA-Z0-9#]', val_stripped):
            return False
    
    return True


def sanitize_style_value(value):
    """Sanitize an inline style attribute value.
    
    Returns (cleaned_value, is_clean) tuple.
    """
    if not value:
        return value, True
    
    cleaned = sanitize_css_text(value)
    is_clean = is_clean_css(cleaned)
    
    return cleaned, is_clean


def is_event_handler(attr_name):
    return bool(EVENT_HANDLER_RE.match(attr_name))


def should_remove_tag_completely(tag):
    tag_name = tag.name.lower() if tag.name else ''
    return tag_name in DANGEROUS_TAGS_REMOVE


def sanitize_tag_attributes(tag):
    """Remove or neutralize dangerous attributes on a tag."""
    if not tag or not hasattr(tag, 'attrs'):
        return
    
    tag_name = tag.name.lower() if tag.name else ''
    is_svg_animation = tag_name in SVG_ANIMATION_TAGS
    
    attrs_to_remove = []
    attrs_to_modify = {}
    
    for attr_name in list(tag.attrs.keys()):
        attr_lower = attr_name.lower()
        
        # 1. Remove all event handlers
        if is_event_handler(attr_lower):
            attrs_to_remove.append(attr_name)
            continue
        
        # 2. Check URL-bearing attributes - REMOVE ENTIRELY if dangerous
        if attr_lower in URL_ATTRIBUTES:
            value = tag.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(str(v) for v in value)
            value_str = str(value)
            
            if is_dangerous_url(value_str) or is_dangerous_data_url(value_str):
                attrs_to_remove.append(attr_name)
            continue
        
        # 3. Check SVG animation attributes
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
        
        # 5. Check style attributes - "clean or remove" philosophy
        if attr_lower == 'style':
            value = tag.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(str(v) for v in value)
            value_str = str(value)
            
            if has_dangerous_style(value_str):
                cleaned, is_clean = sanitize_style_value(value_str)
                if is_clean and cleaned.strip():
                    attrs_to_modify[attr_name] = cleaned
                else:
                    attrs_to_remove.append(attr_name)
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
    
    # Second pass: handle meta refresh with dangerous URLs - remove ENTIRE meta tag
    for meta_tag in soup.find_all('meta'):
        http_equiv = meta_tag.get('http-equiv', '')
        if isinstance(http_equiv, list):
            http_equiv = ' '.join(str(h) for h in http_equiv)
        http_equiv_str = str(http_equiv).strip()
        
        if REFRESH_RE.match(http_equiv_str):
            content = meta_tag.get('content', '')
            if isinstance(content, list):
                content = ' '.join(str(c) for c in content)
            content_str = str(content)
            
            url_match = META_URL_RE.search(content_str)
            if url_match:
                url_part = url_match.group(1).strip().strip("'\"")
                if is_dangerous_url(url_part) or is_dangerous_data_url(url_part):
                    meta_tag.decompose()
                    continue
            
            if is_dangerous_url(content_str) or is_dangerous_data_url(content_str):
                meta_tag.decompose()
                continue
    
    # Third pass: sanitize all remaining tags' attributes
    for tag in soup.find_all(True):
        sanitize_tag_attributes(tag)
    
    # Fourth pass: sanitize <style> element text content
    for style_tag in soup.find_all('style'):
        if style_tag.string:
            original = style_tag.string
            cleaned = sanitize_css_text(original)
            if cleaned != original:
                style_tag.string = cleaned
    
    # Handle comments with scripts
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
