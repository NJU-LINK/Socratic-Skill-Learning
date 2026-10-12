#!/usr/bin/env python3
"""
HTML sanitizer that removes executable JavaScript behavior while preserving
legitimate document structure, visible content, and safe markup.

Surgical approach:
- Remove tags that have no legitimate non-executable purpose
- Strip dangerous attributes from otherwise-safe tags
- Preserve forms, links, meta, tables, etc. with only dangerous parts excised
"""

import sys
import re
import html as html_module
from bs4 import BeautifulSoup, Comment
from urllib.parse import urlparse, unquote


# Tags that have no legitimate non-executable purpose - remove entirely
INHERENTLY_DANGEROUS_TAGS = {
    'script',
    'iframe',
    'object',
    'embed',
    'applet',
}

# SVG elements that can execute scripts - remove entirely
DANGEROUS_SVG_TAGS = {
    'script',
    'set',  # Can set arbitrary attributes to dangerous values
    'foreignobject',  # Can embed arbitrary HTML including scripts
}

# SVG animation elements - NOT inherently dangerous, only check their attributes
# animate, animateTransform, animateMotion are safe unless they have dangerous attributes

# MathML elements that can execute scripts
DANGEROUS_MATHML_TAGS = {
    'script',
}

# Attributes that start with 'on' are event handlers
def is_event_handler(attr_name):
    """Check if an attribute is an event handler (starts with 'on').
    Decodes HTML entities for defense-in-depth against partially encoded payloads."""
    # Decode HTML entities for XHTML/XML contexts and partially encoded payloads
    decoded_name = html_module.unescape(attr_name).lower()
    return decoded_name.startswith('on')


# Attributes that can contain URLs that might execute scripts
URL_ATTRIBUTES = {
    'href', 'src', 'action', 'formaction', 'data', 'poster',
    'dynsrc', 'lowsrc', 'background', 'codebase', 'classid',
    'usemap', 'longdesc', 'profile', 'xmlns',
    # SVG/MathML specific
    'xlink:href', 'href',
    # SVG animation URL attributes
    'to', 'from', 'by', 'values',
}


def is_dangerous_url(url):
    """
    Check if a URL is dangerous (javascript:, data:, vbscript:, etc.).
    Handles various encodings and obfuscation techniques.
    """
    if not url:
        return False
    
    # Convert to string if it's a list
    if isinstance(url, list):
        url = ' '.join(url)
    
    # Decode the URL to handle percent-encoding
    decoded = url
    try:
        # Decode multiple times to handle layered encoding
        for _ in range(5):
            new_decoded = unquote(decoded)
            if new_decoded == decoded:
                break
            decoded = new_decoded
    except:
        pass
    
    # Remove whitespace, tabs, newlines, and control characters
    # This handles obfuscation like "java\tscript:alert(1)"
    # Also strips U+FFFD (Unicode replacement character) which BeautifulSoup
    # converts from &#x0; (null byte entity)
    cleaned = re.sub(r'[\s\x00-\x1f\x7f\ufffd]+', '', decoded)
    
    # Also handle HTML entities
    # Decode common entities
    cleaned = cleaned.replace('&tab;', '\t').replace('&newline;', '\n')
    cleaned = re.sub(r'&#x([0-9a-fA-F]+);?', lambda m: chr(int(m.group(1), 16)), cleaned)
    cleaned = re.sub(r'&#(\d+);?', lambda m: chr(int(m.group(1))), cleaned)
    cleaned = re.sub(r'&([a-zA-Z]+);', '', cleaned)  # Remove named entities
    
    # Remove whitespace again after entity decoding
    cleaned = re.sub(r'[\s\x00-\x1f\x7f\ufffd]+', '', cleaned)
    
    # Check for dangerous protocols (case-insensitive)
    dangerous_protocols = [
        r'^javascript:',
        r'^vbscript:',
        r'^data:\s*text/html',
        r'^data:\s*application/xhtml',
        r'^data:\s*image/svg\+xml',  # SVG can contain scripts
    ]
    
    for pattern in dangerous_protocols:
        if re.match(pattern, cleaned, re.IGNORECASE):
            return True
    
    return False


def is_dangerous_css_rule(rule):
    """
    Check if a single CSS rule contains dangerous patterns.
    """
    if not rule:
        return False
    
    # Decode and clean the CSS
    cleaned = rule
    try:
        for _ in range(3):
            new_decoded = unquote(cleaned)
            if new_decoded == cleaned:
                break
            cleaned = new_decoded
    except:
        pass
    
    # Remove whitespace for pattern matching
    normalized = re.sub(r'[\s\x00-\x1f\x7f]+', '', cleaned)
    
    # Check for dangerous CSS patterns
    dangerous_patterns = [
        r'expression\s*\(',  # IE expression()
        r'-moz-binding\s*:',  # Firefox XBL
        r'behavior\s*:',  # IE behavior
        r'url\s*\(\s*["\']?\s*javascript:',  # url(javascript:...)
        r'url\s*\(\s*["\']?\s*data:',  # url(data:...)
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    
    return False


def is_dangerous_css(css_content):
    """
    Check if CSS content contains dangerous patterns that can execute JavaScript.
    """
    if not css_content:
        return False
    
    # Parse CSS rules and check each one
    rules = re.split(r'([^{}]+)\{([^{}]*)\}', css_content)
    for i in range(1, len(rules), 3):
        if i + 1 < len(rules):
            rule = rules[i] + '{' + rules[i+1] + '}'
            if is_dangerous_css_rule(rule):
                return True
    
    return False


def sanitize_style_attribute(style_value):
    """
    Sanitize a style attribute value by removing dangerous CSS properties
    while preserving safe ones.
    Returns the sanitized style value, or None if the entire style should be removed.
    """
    if not style_value:
        return None
    
    # Split into individual properties
    properties = style_value.split(';')
    safe_properties = []
    
    for prop in properties:
        prop = prop.strip()
        if not prop:
            continue
        
        # Check if this property is dangerous
        if not is_dangerous_css_rule(prop):
            safe_properties.append(prop)
    
    if not safe_properties:
        return None
    
    return '; '.join(safe_properties)


def sanitize_style_tag(style_content):
    """
    Sanitize the content of a <style> tag by removing dangerous CSS rules
    while preserving safe ones.
    Returns the sanitized content, or None if the entire tag should be removed.
    """
    if not style_content:
        return None
    
    # Split CSS into rules (selector { properties })
    # This is a simple parser that handles basic CSS structure
    safe_rules = []
    
    # Use regex to find all rule blocks
    rule_pattern = re.compile(r'([^{}]+)\{([^{}]*)\}')
    
    # Find all matches and their positions
    matches = list(rule_pattern.finditer(style_content))
    
    if not matches:
        # No rule blocks found - check if the content itself is dangerous
        if is_dangerous_css_rule(style_content):
            return None
        return style_content
    
    # Process each rule
    last_end = 0
    for match in matches:
        # Add any content before this rule (comments, whitespace, etc.)
        before = style_content[last_end:match.start()]
        safe_rules.append(before)
        
        selector = match.group(1)
        properties = match.group(2)
        full_rule = selector + '{' + properties + '}'
        
        # Check if this rule is dangerous
        if not is_dangerous_css_rule(full_rule):
            safe_rules.append(full_rule)
        
        last_end = match.end()
    
    # Add any remaining content after the last rule
    if last_end < len(style_content):
        safe_rules.append(style_content[last_end:])
    
    result = ''.join(safe_rules).strip()
    
    if not result:
        return None
    
    return result


def extract_meta_refresh_url(content):
    """
    Extract the URL from a meta refresh content attribute.
    Format: "5;url=javascript:alert(1)" or "5;URL=javascript:..."
    Returns the URL portion, or the entire content if no URL= is found.
    """
    if not content:
        return content
    
    # Look for url= pattern (case-insensitive)
    match = re.search(r';\s*url\s*=\s*(.+)', content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    return content


def sanitize_element(element):
    """
    Recursively sanitize an element and its children.
    Returns True if the element should be kept, False if it should be removed.
    """
    if not hasattr(element, 'name') or element.name is None:
        # Text node - keep as is
        return True
    
    tag_name = element.name.lower()
    
    # Remove namespace prefix if present (e.g., svg:script -> script)
    if ':' in tag_name:
        tag_name = tag_name.split(':', 1)[1]
    
    # Check if this is an inherently dangerous tag
    if tag_name in INHERENTLY_DANGEROUS_TAGS:
        return False
    
    # Check for dangerous SVG tags
    if tag_name in DANGEROUS_SVG_TAGS:
        return False
    
    # Check for dangerous MathML tags
    if tag_name in DANGEROUS_MATHML_TAGS:
        return False
    
    # Handle special cases for meta tags
    if tag_name == 'meta':
        http_equiv = element.get('http-equiv', '').lower()
        if http_equiv == 'refresh':
            # Extract the URL from the content attribute
            content = element.get('content', '')
            url = extract_meta_refresh_url(content)
            if is_dangerous_url(url):
                return False
            # URL is safe — leave the tag completely untouched
    
    # Handle style tags
    if tag_name == 'style':
        style_content = element.string
        if style_content:
            sanitized = sanitize_style_tag(style_content)
            if sanitized is None:
                return False
            element.string = sanitized
    
    # Remove dangerous attributes
    attrs_to_remove = []
    for attr_name in list(element.attrs.keys()):
        attr_lower = attr_name.lower()
        
        # Remove event handlers
        if is_event_handler(attr_lower):
            attrs_to_remove.append(attr_name)
            continue
        
        # Check URL attributes for dangerous protocols
        if attr_lower in URL_ATTRIBUTES:
            attr_value = element.get(attr_name, '')
            if is_dangerous_url(attr_value):
                attrs_to_remove.append(attr_name)
                continue
        
        # Sanitize style attributes
        if attr_lower == 'style':
            style_value = element.get(attr_name, '')
            sanitized = sanitize_style_attribute(style_value)
            if sanitized is None:
                attrs_to_remove.append(attr_name)
            elif sanitized != style_value:
                element.attrs[attr_name] = sanitized
    
    for attr in attrs_to_remove:
        del element.attrs[attr]
    
    # Recursively sanitize children
    for child in list(element.children):
        if not sanitize_element(child):
            child.extract()
    
    return True


def filter_js_from_html(html_content):
    """
    Remove executable JavaScript behavior from HTML content.
    Preserves legitimate document structure and visible content.
    """
    # Parse the HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Sanitize the document
    sanitize_element(soup)
    
    # Return the sanitized HTML
    return str(soup)


def main():
    if len(sys.argv) != 2:
        print("Usage: filter.py <html_file>", file=sys.stderr)
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    # Read the input file
    with open(input_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Filter the HTML
    filtered_html = filter_js_from_html(html_content)
    
    # Write back to the same file (in-place modification)
    with open(input_file, 'w', encoding='utf-8') as f:
        f.write(filtered_html)


if __name__ == '__main__':
    main()
