#!/usr/bin/env python3
"""HTML JavaScript Filter - Removes executable JavaScript from HTML files."""

import sys
import re
from bs4 import BeautifulSoup

# Active data: mediatypes that browsers render as documents
_ACTIVE_DATA_RE = re.compile(
    r'^data:\s*(text/html|application/xhtml\+xml|image/svg\+xml|application/xml|text/xml)',
    re.IGNORECASE
)

# URL attributes that may contain executable content
URL_ATTRIBUTES = frozenset([
    'href', 'src', 'data', 'action', 'formaction',
    'background', 'dynsrc', 'lowsrc', 'xlink:href',
    'poster', 'profile', 'cite', 'longdesc'
])

# SMIL animation elements that can rewrite attributes
SMIL_ELEMENTS = ('animate', 'set', 'animatemotion', 'animatetransform')

# Elements that are always removed (embedding contexts)
ALWAYS_REMOVE = ('script', 'foreignobject')


def canonicalize_url(url):
    """Strip \x00-\x20 and lowercase for browser-equivalent comparison."""
    if not url:
        return ''
    return re.sub(r'[\x00-\x20]+', '', str(url)).lower()


def is_dangerous_url(url):
    """Check if URL can execute JavaScript."""
    if not url:
        return False
    canon = canonicalize_url(url)
    if canon.startswith('javascript:'):
        return True
    # Match against canonicalized URL (handles leading spaces/tabs)
    if _ACTIVE_DATA_RE.match(canon):
        return True
    return False


def css_canonicalize(s):
    """Normalize CSS: remove comments, decode hex escapes (1-6 digits), strip controls."""
    s = re.sub(r'\/\*.*?\*\/', '', str(s), flags=re.S)  # Remove comments
    # Decode hex escapes: \X to \XXXXXX (1-6 hex digits) with optional trailing space
    def decode_hex(m):
        try:
            code = int(m.group(1), 16)
            if 32 <= code <= 126:  # Printable ASCII
                return chr(code)
            return ' '
        except:
            return m.group(0)
    s = re.sub(r'\\([0-9a-fA-F]{1,6})\s?', decode_hex, s)
    return re.sub(r'[\x00-\x20]+', '', s).lower()


def has_dangerous_css_url(style_value):
    """Check if CSS contains dangerous javascript: URLs."""
    if not style_value:
        return False
    canon = css_canonicalize(style_value)
    return 'javascript:' in canon or 'expression(' in canon


def filter_html(content):
    soup = BeautifulSoup(content, 'html.parser')
    
    # 1. Remove script elements and foreignObject (always dangerous)
    for tag in list(soup.find_all(True)):
        if hasattr(tag, 'name') and tag.name:
            name_lower = tag.name.lower()
            if name_lower in ALWAYS_REMOVE or name_lower.endswith(':script'):
                tag.decompose()
    
    # 2. Remove dangerous containers (iframe/object/embed with dangerous URLs)
    for tag in list(soup.find_all(['iframe', 'object', 'embed'])):
        src = tag.get('src', '')
        data = tag.get('data', '')
        if is_dangerous_url(src) or is_dangerous_url(data):
            tag.decompose()
    
    # 3. Process SMIL elements - remove if they target URL attributes with dangerous payloads
    for tag in soup.find_all(SMIL_ELEMENTS):
        target = (tag.get('attributename') or '').lower()
        if target in URL_ATTRIBUTES or ':' in target:
            payloads = []
            for attr in ('to', 'from', 'by', 'values'):
                v = tag.get(attr)
                if v:
                    payloads.extend(str(v).split(';'))
            if any(is_dangerous_url(p.strip()) for p in payloads):
                tag.decompose()
    
    # 4. Process attributes on remaining elements
    for tag in soup.find_all(True):
        if not hasattr(tag, 'attrs'):
            continue
        
        attrs_to_remove = []
        attrs_to_update = {}
        
        for attr_name in list(tag.attrs.keys()):
            attr_lower = attr_name.lower()
            value = tag.attrs[attr_name]
            
            if isinstance(value, list):
                value = ' '.join(value)
            
            # Event handlers (on* attributes)
            if attr_lower.startswith('on') and len(attr_name) > 2:
                attrs_to_remove.append(attr_name)
                continue
            
            # Style attributes - check for dangerous CSS
            if attr_lower == 'style':
                if has_dangerous_css_url(value):
                    attrs_to_remove.append(attr_name)
                    continue
            
            # URL attributes (skip src/data on containers already handled)
            tag_name = tag.name.lower() if tag.name else ''
            is_container = tag_name in ('iframe', 'object', 'embed')
            
            if attr_lower in URL_ATTRIBUTES or ':' in attr_name:
                if not (is_container and attr_lower in ('src', 'data')):
                    if is_dangerous_url(value):
                        attrs_to_remove.append(attr_name)
                        continue
            
            # srcdoc - recursive sanitization
            if attr_lower == 'srcdoc':
                attrs_to_update[attr_name] = filter_html(value)
        
        for attr in attrs_to_remove:
            del tag.attrs[attr]
        for attr, new_val in attrs_to_update.items():
            tag.attrs[attr] = new_val
    
    # 5. Check <style> element text - handle foreign content (SVG/MathML)
    for tag in soup.find_all('style'):
        text = tag.get_text()  # Use get_text() to handle comments
        # Check if in foreign content (SVG/MathML)
        in_foreign = any((p.name or '').lower() in ('svg', 'math') for p in tag.parents)
        if in_foreign:
            # In foreign content, browsers parse style contents as markup, not raw text
            # Check for element-like content (starts with < then letter)
            if re.search(r'<\s*[a-zA-Z]', text):
                tag.decompose()
            elif has_dangerous_css_url(text):
                tag.decompose()
        else:
            # In HTML, style is raw text - check for dangerous CSS
            if has_dangerous_css_url(text):
                tag.decompose()
    
    # 6. Meta refresh
    for meta in soup.find_all('meta'):
        if meta.get('http-equiv', '').lower() == 'refresh':
            content = meta.get('content', '')
            match = re.search(r'url\s*=\s*["\']?([^"\';\s]*)', content, re.I)
            if match and is_dangerous_url(match.group(1)):
                meta.decompose()
    
    return str(soup)


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
