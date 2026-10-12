#!/usr/bin/env python3
"""
Filter executable JavaScript behavior from HTML files.
Takes an HTML file as argv[1], modifies in-place.
"""

import sys
import re
import html
from urllib.parse import unquote
from bs4 import BeautifulSoup, Comment

# Tags to remove entirely (unconditionally dangerous)
UNCONDITIONALLY_DANGEROUS_TAGS = {
    'script', 'iframe', 'frame', 'frameset',
    'object', 'embed', 'applet', 'base',
    'foreignobject',  # SVG foreignObject embeds full HTML
    'maction',  # MathML maction can trigger URLs
}

# SVG animation tags that need conditional checking
SVG_ANIMATION_TAGS = {'animate', 'set', 'animatemotion', 'animatecolor', 'animatetransform'}

# URL-bearing attributes to check
URL_ATTRIBUTES = {
    'href', 'src', 'action', 'formaction', 'data', 'poster',
    'background', 'dynsrc', 'lowsrc', 'xlink:href', 'srcdoc',
}

# Dangerous URL schemes
DANGEROUS_SCHEMES = {'javascript:', 'vbscript:', 'livescript:'}


def normalize_url(value):
    """Normalize a URL value for checking against dangerous patterns."""
    if not value:
        return ''
    # Decode HTML entities
    decoded = html.unescape(value)
    # Multiple rounds of URL decoding
    for _ in range(5):
        prev = decoded
        decoded = unquote(decoded)
        if decoded == prev:
            break
    # Strip whitespace and control characters (including replacement char)
    cleaned = re.sub(r'[\s\x00-\x1f\x7f\ufffd]', '', decoded)
    return cleaned.lower()


def is_dangerous_url(value):
    """Check if a URL value is dangerous."""
    if not value:
        return False
    normalized = normalize_url(value)
    if not normalized:
        return False
    # Check dangerous schemes
    for scheme in DANGEROUS_SCHEMES:
        if normalized.startswith(scheme):
            return True
    # Check dangerous data URLs
    if normalized.startswith('data:text/html'):
        return True
    return False


def is_event_handler(attr_name):
    """Check if an attribute name is an event handler (starts with 'on')."""
    return attr_name.lower().startswith('on')


def is_dangerous_animation_element(tag):
    """
    Check if an SVG animation element (<animate>, <set>, etc.) is dangerous.
    
    Dangerous if:
    - attributeName is an event handler (on*)
    - to attribute contains a dangerous URL
    - xlink:href contains a dangerous URL
    - href contains a dangerous URL
    """
    if tag.name not in SVG_ANIMATION_TAGS:
        return False
    
    # Check attributeName - if it's an event handler, dangerous
    attr_name = tag.get('attributename', '')
    if attr_name and is_event_handler(attr_name):
        return True
    
    # Check 'to' attribute for dangerous URLs
    to_value = tag.get('to', '')
    if to_value and is_dangerous_url(to_value):
        return True
    
    # Check xlink:href for dangerous URLs
    xlink_href = tag.get('xlink:href', '')
    if xlink_href and is_dangerous_url(xlink_href):
        return True
    
    # Check href for dangerous URLs (non-namespaced)
    href_val = tag.get('href', '')
    if href_val and is_dangerous_url(href_val):
        return True
    
    # Check if it's setting any URL-bearing attribute to a dangerous value
    # (This catches cases like attributeName="href" to="javascript:...")
    if attr_name and attr_name.lower() in URL_ATTRIBUTES:
        if to_value and is_dangerous_url(to_value):
            return True
    
    return False


# Dangerous CSS patterns (case-insensitive)
DANGEROUS_CSS_PATTERNS = [
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'behavior\s*:', re.IGNORECASE),
    re.compile(r'-moz-binding\s*:', re.IGNORECASE),
    re.compile(r'-o-link\s*:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*javascript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*vbscript:', re.IGNORECASE),
    re.compile(r'url\s*\(\s*["\']?\s*data\s*:\s*text/html', re.IGNORECASE),
    re.compile(r'@import\s+["\']?\s*javascript:', re.IGNORECASE),
    re.compile(r'@import\s+["\']?\s*vbscript:', re.IGNORECASE),
    re.compile(r'@import\s+["\']?\s*data\s*:\s*text/html', re.IGNORECASE),
]


def sanitize_style_attribute(style_value):
    """Sanitize a style attribute value, removing dangerous declarations."""
    if not style_value:
        return style_value
    
    # Check if any dangerous patterns exist
    has_danger = False
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(style_value):
            has_danger = True
            break
    
    if not has_danger:
        return style_value
    
    # Parse declarations more carefully to handle url() with special chars
    # Split by semicolons, but be aware of url() content
    result_parts = []
    current = ''
    in_url = False
    url_depth = 0
    
    for char in style_value:
        if char == '(' and current.lower().endswith('url'):
            in_url = True
            url_depth = 1
            current += char
        elif char == '(' and in_url:
            url_depth += 1
            current += char
        elif char == ')' and in_url:
            url_depth -= 1
            current += char
            if url_depth == 0:
                in_url = False
        elif char == ';' and not in_url:
            # End of declaration
            decl = current.strip()
            if decl:
                # Check if this declaration is dangerous
                is_dangerous = False
                for pattern in DANGEROUS_CSS_PATTERNS:
                    if pattern.search(decl):
                        is_dangerous = True
                        break
                if not is_dangerous:
                    result_parts.append(decl)
            current = ''
        else:
            current += char
    
    # Handle last declaration (no trailing semicolon)
    decl = current.strip()
    if decl:
        is_dangerous = False
        for pattern in DANGEROUS_CSS_PATTERNS:
            if pattern.search(decl):
                is_dangerous = True
                break
        if not is_dangerous:
            result_parts.append(decl)
    
    if not result_parts:
        return None
    
    return '; '.join(result_parts)


def sanitize_style_content_robust(content):
    """Sanitize <style> element content by removing dangerous CSS patterns."""
    if not content:
        return content
    
    # If any dangerous pattern is found, remove the entire style content
    # This is conservative but safe - CSS with embedded HTML/script is inherently dangerous
    for pattern in DANGEROUS_CSS_PATTERNS:
        if pattern.search(content):
            return ''
    
    return content


def process_element(element):
    """Process a single element: filter dangerous attributes."""
    if not hasattr(element, 'attrs') or element.attrs is None:
        return
    
    attrs_to_remove = []
    attrs_to_modify = {}
    
    for attr_name in list(element.attrs.keys()):
        attr_lower = attr_name.lower()
        
        # Remove srcdoc entirely
        if attr_lower == 'srcdoc':
            attrs_to_remove.append(attr_name)
            continue
        
        # Remove event handlers
        if is_event_handler(attr_name):
            attrs_to_remove.append(attr_name)
            continue
        
        # Check URL attributes
        if attr_lower in URL_ATTRIBUTES:
            value = element.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(value)
            if is_dangerous_url(value):
                attrs_to_remove.append(attr_name)
                continue
        
        # Sanitize style attribute
        if attr_lower == 'style':
            value = element.attrs[attr_name]
            if isinstance(value, list):
                value = ' '.join(value)
            sanitized = sanitize_style_attribute(value)
            if sanitized is None:
                attrs_to_remove.append(attr_name)
            elif sanitized != value:
                attrs_to_modify[attr_name] = sanitized
    
    for attr_name in attrs_to_remove:
        del element.attrs[attr_name]
    
    for attr_name, new_value in attrs_to_modify.items():
        element.attrs[attr_name] = new_value


def filter_html(content):
    """Filter dangerous JavaScript from HTML content."""
    # Detect if this is a fragment
    stripped = content.strip().lower()
    is_fragment = not (stripped.startswith('<!doctype') or '<html' in content[:500].lower())
    
    soup = BeautifulSoup(content, 'html.parser')
    
    # Remove unconditionally dangerous tags
    for tag_name in UNCONDITIONALLY_DANGEROUS_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    
    # Conditionally remove dangerous SVG animation elements
    for tag_name in SVG_ANIMATION_TAGS:
        for tag in soup.find_all(tag_name):
            if is_dangerous_animation_element(tag):
                tag.decompose()
    
    # Handle <meta http-equiv="refresh"> - only remove if dangerous URL
    for meta in soup.find_all('meta'):
        http_equiv = meta.get('http-equiv', '')
        if http_equiv and http_equiv.lower() == 'refresh':
            meta_content = meta.get('content', '')
            # Extract URL from content like "0;url=javascript:..." or "0; URL = javascript:..."
            url_part = meta_content
            if ';' in meta_content:
                parts = meta_content.split(';', 1)
                if len(parts) > 1:
                    url_part = parts[1].strip()
                    # Use regex to extract URL after "url=" (handles spaces around =)
                    m = re.search(r'url\s*=\s*(.*)', url_part, re.IGNORECASE)
                    if m:
                        url_part = m.group(1).strip()
            if is_dangerous_url(url_part):
                meta.decompose()
    
    # Handle <link> - apply URL filtering
    for link in soup.find_all('link'):
        href = link.get('href', '')
        if href and is_dangerous_url(href):
            link.decompose()
    
    # Process all remaining elements for attributes
    for element in soup.find_all(True):  # True matches all tags
        process_element(element)
    
    # Sanitize <style> element content
    for style in soup.find_all('style'):
        if style.string:
            style.string = sanitize_style_content_robust(style.string)
    
    # Serialize
    if is_fragment:
        body = soup.body
        if body:
            output = ''.join(str(c) for c in body.contents)
        else:
            output = str(soup)
    else:
        output = str(soup)
    
    return output


def main():
    if len(sys.argv) < 2:
        print("Usage: filter.py <html_file>", file=sys.stderr)
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    filtered = filter_html(content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(filtered)


if __name__ == '__main__':
    main()
