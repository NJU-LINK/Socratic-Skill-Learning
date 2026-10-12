#!/usr/bin/env python3
"""
HTML JavaScript sanitizer - removes executable JavaScript behavior from HTML files.

Uses html5lib for namespace-aware HTML5 parsing, walks the DOM tree to neutralize
dangerous elements and attributes, then serializes safely.

Handles SVG, MathML, and related namespace-aware markup.
"""

import sys
import re
import urllib.parse
import html5lib
from html5lib import serialize

# Namespace constants
HTML_NS = "http://www.w3.org/1999/xhtml"
SVG_NS = "http://www.w3.org/2000/svg"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"
XLINK_NS = "http://www.w3.org/1999/xlink"

# Category A: Elements to remove entirely (with all children)
DANGEROUS_ELEMENTS = frozenset({
    'script',
    'iframe', 'frame', 'frameset',
    'object', 'embed', 'applet',
    'base',
})

# SVG-specific elements to remove entirely
SVG_DANGEROUS_ELEMENTS = frozenset({
    'handler',
    'foreignobject',
})

# SVG animation elements whose attributeName must be checked
SVG_ANIMATION_ELEMENTS = frozenset({
    'animate', 'animatetransform', 'set',
})

# URL-bearing attributes (local names)
URL_ATTRS = frozenset({
    'href', 'src', 'action', 'formaction',
    'data', 'poster', 'background',
    'dynsrc', 'lowsrc',
    'usemap', 'longdesc', 'ping', 'srcset', 'cite', 'manifest',
    'srcdoc',
})

# URL attributes for SVG animation attributeName targeting
URL_ATTRS_FOR_ANIMATION = frozenset({
    'href', 'src', 'action', 'formaction',
    'data', 'poster', 'background',
    'dynsrc', 'lowsrc',
    'xlink:href',
})


def get_local_name(tag):
    """Extract local name from a Clark-notation tag name."""
    if isinstance(tag, str) and '}' in tag:
        return tag.split('}', 1)[1].lower()
    if isinstance(tag, str):
        return tag.lower()
    return ''


def get_namespace(tag):
    """Extract namespace URI from a Clark-notation tag name."""
    if isinstance(tag, str) and tag.startswith('{'):
        return tag.split('}', 1)[0][1:]
    return None


def is_dangerous_url(value):
    """Check if a URL value uses a dangerous scheme.
    
    Normalizes: strips whitespace/null bytes, decodes HTML entities,
    then iteratively percent-decodes (handles layered encoding).
    """
    if not value:
        return False
    # Strip all whitespace and null bytes
    cleaned = re.sub(r'[\s\x00]+', '', value).lower()
    # Strip HTML entities (parser may leave some in edge cases)
    cleaned = re.sub(r'&#x[0-9a-f]+;?', '', cleaned)
    cleaned = re.sub(r'&#\d+;?', '', cleaned)
    cleaned = re.sub(r'&[a-zA-Z]+;', '', cleaned)
    # Iteratively percent-decode (handles layered encoding like %256a -> %6a -> j)
    for _ in range(5):
        try:
            decoded = urllib.parse.unquote(cleaned)
        except Exception:
            decoded = cleaned
        if decoded == cleaned:
            break
        cleaned = decoded
    
    for scheme in ('javascript:', 'vbscript:', 'data:text/html'):
        if cleaned.startswith(scheme):
            return True
    return False


def is_dangerous_meta_refresh(content):
    """Check if meta refresh content contains a dangerous URL."""
    if not content:
        return False
    match = re.search(r'url\s*=\s*(.+)', content, re.I)
    if match:
        url = match.group(1).strip().strip('"').strip("'")
        return is_dangerous_url(url)
    return is_dangerous_url(content)


def has_dangerous_css(text):
    """Check if CSS text contains any dangerous patterns."""
    if not text:
        return False
    patterns = [
        r'expression\s*\(',
        r'-moz-binding\s*:',
        r'behavior\s*:',
        r'url\s*\(\s*["\']?\s*javascript:',
        r'@import\s+url\s*\(\s*["\']?\s*javascript:',
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.I):
            return True
    return False


def sanitize_css(text):
    """Sanitize CSS text content to remove dangerous constructs.
    Used for <style> element text content (in-place sanitization).
    """
    if not text:
        return text
    text = re.sub(r'expression\s*\(', '(', text, flags=re.I)
    text = re.sub(r'-moz-binding\s*:', 'removed:', text, flags=re.I)
    text = re.sub(r'behavior\s*:', 'removed:', text, flags=re.I)
    text = re.sub(r'url\s*\(\s*["\']?\s*javascript:', 'url(removed:', text, flags=re.I)
    text = re.sub(r'@import\s+url\s*\(\s*["\']?\s*javascript:', '@import url(removed:', text, flags=re.I)
    return text


def _remove_element_preserving_tail(elem, parent):
    """Remove an element while preserving its tail text."""
    tail = elem.tail
    if tail:
        children = list(parent)
        try:
            idx = children.index(elem)
        except ValueError:
            idx = -1
        
        if idx > 0:
            prev = children[idx - 1]
            prev.tail = (prev.tail or '') + tail
        else:
            parent.text = (parent.text or '') + tail
    
    parent.remove(elem)


def should_remove_element(local_name, namespace, elem):
    """Determine if an element should be removed entirely."""
    if local_name in DANGEROUS_ELEMENTS:
        return True
    
    if namespace == SVG_NS and local_name in SVG_DANGEROUS_ELEMENTS:
        return True
    
    if namespace == SVG_NS and local_name in SVG_ANIMATION_ELEMENTS:
        target_attr = (elem.get('attributeName') or '').lower().strip()
        if target_attr.startswith('on'):
            return True
        if target_attr in URL_ATTRS_FOR_ANIMATION:
            return True
    
    if namespace == MATHML_NS and local_name == 'annotation-xml':
        encoding = (elem.get('encoding') or '').lower().strip()
        if encoding in ('application/xhtml+xml', 'text/html'):
            return True
    
    # Category D: meta refresh with dangerous URL - remove entire element
    if local_name == 'meta':
        http_equiv = (elem.get('http-equiv') or '').lower().strip()
        if http_equiv == 'refresh':
            content = elem.get('content') or ''
            if is_dangerous_meta_refresh(content):
                return True
    
    return False


def sanitize_attributes(elem):
    """Remove or neutralize dangerous attributes on an element."""
    attrs_to_remove = []
    
    for attr_name in list(elem.attrib.keys()):
        attr_local = get_local_name(attr_name)
        attr_ns = get_namespace(attr_name)
        attr_val = elem.attrib[attr_name]
        
        if attr_local.startswith('on'):
            attrs_to_remove.append(attr_name)
            continue
        
        if attr_local == 'srcdoc':
            attrs_to_remove.append(attr_name)
            continue
        
        if attr_local in URL_ATTRS and is_dangerous_url(attr_val):
            attrs_to_remove.append(attr_name)
            continue
        
        if attr_ns == XLINK_NS and attr_local == 'href' and is_dangerous_url(attr_val):
            attrs_to_remove.append(attr_name)
            continue
    
    for attr_name in attrs_to_remove:
        del elem.attrib[attr_name]


def sanitize_element(elem, parent):
    """Recursively sanitize an element and its children."""
    # Skip non-element nodes (comments, processing instructions)
    if not isinstance(elem.tag, str):
        for child in list(elem):
            sanitize_element(child, elem)
        return
    
    local_name = get_local_name(elem.tag)
    namespace = get_namespace(elem.tag)
    
    if should_remove_element(local_name, namespace, elem):
        if parent is not None:
            _remove_element_preserving_tail(elem, parent)
        return
    
    sanitize_attributes(elem)
    
    # Style element CSS sanitization (in-place for <style> elements)
    if local_name == 'style' and (namespace is None or namespace == HTML_NS):
        if elem.text:
            elem.text = sanitize_css(elem.text)
    
    # Inline style attribute: delete entirely if dangerous patterns found
    style_val = elem.get('style')
    if style_val:
        if has_dangerous_css(style_val):
            del elem.attrib['style']
        else:
            # No dangerous patterns - keep as-is
            pass
    
    if local_name == 'noscript':
        _sanitize_noscript(elem)
    
    for child in list(elem):
        sanitize_element(child, elem)


def _sanitize_noscript(noscript_elem):
    """Defend against noscript mXSS."""
    def _check_for_noscript_close(element):
        if element.text and '</noscript>' in element.text.lower():
            return True
        if element.tail and '</noscript>' in element.tail.lower():
            return True
        for attr_val in element.attrib.values():
            if '</noscript>' in attr_val.lower():
                return True
        for child in element:
            if _check_for_noscript_close(child):
                return True
        return False
    
    if _check_for_noscript_close(noscript_elem):
        for child in list(noscript_elem):
            noscript_elem.remove(child)
        noscript_elem.text = None


def main():
    if len(sys.argv) < 2:
        print("Usage: filter.py <html_file>", file=sys.stderr)
        sys.exit(1)
    
    filename = sys.argv[1]
    
    with open(filename, 'r', encoding='utf-8', errors='replace') as f:
        html_content = f.read()
    
    doc = html5lib.parse(html_content, treebuilder='etree', namespaceHTMLElements=True)
    
    sanitize_element(doc, None)
    
    output = serialize(
        doc, tree='etree',
        quote_attr_values='always',
        omit_optional_tags=False,
        escape_lt_in_attrs=True,
        resolve_entities=True,
        sanitize=False,
    )
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(output)


if __name__ == '__main__':
    main()
