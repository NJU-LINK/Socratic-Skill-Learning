---
name: filter-js-from-html
description: >
  Remove executable JavaScript behavior from HTML files while preserving
  legitimate document structure, visible content, SVG graphics, MathML
  equations, forms, links, and non-dangerous attributes. Handles direct script
  tags, inline event handlers, javascript: URLs, data: URLs embedding HTML,
  active container tags (iframe, object, embed), SVG/MathML executable
  elements, CSS-based attacks, and various obfuscation techniques including
  entity encoding, case variation, whitespace injection, and null bytes.
---

# Filter JavaScript from HTML

## Task Overview

Create a Python script (`/app/filter.py`) that:
- Takes an HTML file path as `argv[1]`
- Modifies the file **in-place** to remove all executable JavaScript behavior
- Preserves legitimate document structure, visible content, vector graphics, equations, forms, links, and non-dangerous attributes
- Handles SVG, MathML, and namespace-aware markup

## Environment

- Python 3.13 with `beautifulsoup4` available
- `lxml` can be installed via pip but `html.parser` (stdlib) is preferred for structure preservation
- The script must work without network access

## Architecture

### Parser Choice

Use **BeautifulSoup with `html.parser`** backend. Key reasons:
- `html.parser` preserves fragment structure (no auto-wrapping in `<html><body>`)
- Automatically decodes HTML entities in attribute values (critical for detecting encoded `javascript:` URLs)
- Tolerant of malformed HTML
- Does NOT decode entities in attribute names (which is correct — browsers don't either)

### Multi-Pass Sanitization Strategy

Apply sanitization in ordered passes to handle interactions between elements:

1. **Remove entirely dangerous tags**: `<script>`, `<iframe>`, `<object>`, `<embed>`, `<applet>`
2. **Handle `<base>` tags**: Remove if `href` is a `javascript:` URL
3. **Handle `<meta http-equiv="refresh">`**: Remove if content contains `javascript:` URL
4. **Handle `<link>` tags**: Remove if `href` is a `javascript:` URL
5. **Sanitize `<style>` tags**: Remove CSS expressions, behaviors, -moz-binding, javascript: URLs in CSS
6. **Remove dangerous SVG animation elements**: `<set>` with `attributeName` starting with "on", animation elements with `on*` handlers or `javascript:` URLs
7. **Walk all remaining tags**: Remove `on*` event handlers, `javascript:`/`vbscript:` URLs in URL-bearing attributes, `data:text/html` URLs, dangerous CSS in `style` attributes
8. **Handle `<template>` contents**: Remove scripts and event handlers inside templates
9. **Remove dangerous comments**: IE conditional comments, comments containing `<script`
10. **Handle `<foreignObject>` in SVG**: Recursively sanitize embedded HTML
11. **Handle form elements**: Remove `javascript:` from `action`/`formaction` attributes

## Executable HTML Vectors (Comprehensive List)

### Direct Script Execution
- `<script>` tags (any case, any attributes)
- `<script src="...">` external scripts

### Inline Event Handlers
- All `on*` attributes: `onclick`, `onerror`, `onload`, `onmouseover`, `onfocus`, `onblur`, etc.
- Case-insensitive: `ONCLICK`, `OnClick`, etc.
- On any element: `<div>`, `<img>`, `<svg>`, `<body>`, `<input>`, etc.

### JavaScript URLs
- `javascript:` protocol in any URL-bearing attribute
- `vbscript:` protocol (IE legacy)
- Attributes to check: `href`, `src`, `action`, `formaction`, `data`, `poster`, `dynsrc`, `lowsrc`, `background`, `codebase`, `classid`, `usemap`, `longdesc`, `ping`, `srcdoc`, `xlink:href`, `actionurl`, `cursor`, `altimg`

### Data URLs with Executable Content
- `data:text/html,...` in `src`, `srcdoc`, `data` attributes
- `data:image/svg+xml,...` in `src` attributes
- `data:application/xhtml+xml,...`

### Active Container Tags
- `<iframe>` — can load external pages with scripts
- `<object>` — can load plugins and external content
- `<embed>` — can load plugins
- `<applet>` — Java applets

### SVG-Specific Vectors
- `<svg onload="...">` — event handler on SVG root
- `<svg><script>...</script></svg>` — script inside SVG
- `<use xlink:href="javascript:...">` — JavaScript URL in use element
- `<a xlink:href="javascript:...">` — JavaScript URL in SVG link
- `<set attributeName="onmouseover" value="...">` — dynamically setting event handlers
- `<animate onbegin="...">` — event handlers on animation elements
- `<foreignObject>` — can embed HTML with scripts
- `<image xlink:href="javascript:...">` — JavaScript URL in SVG image
- **SVG Animation URL Injection**: `<animate attributeName="href" to="javascript:...">` or `<set attributeName="href" to="javascript:...">` — animation elements can modify URL-bearing attributes (href, src, action, xlink:href, etc.) on target elements. The `to`, `from`, and `values` attributes may contain javascript: URLs. The `values` attribute uses semicolons to separate keyframe values (e.g., `values="safe;javascript:alert(1)"`), so each semicolon-separated value must be checked individually. Animation elements can also target `style` attributes with dangerous CSS values.

### MathML-Specific Vectors
- `<maction actionurl="javascript:...">` — JavaScript URL in MathML action
- Event handlers on MathML elements

### Form-Related Vectors
- `<form action="javascript:...">` — JavaScript form action
- `<input formaction="javascript:...">` — JavaScript form action on input
- `<button formaction="javascript:...">` — JavaScript form action on button

### Navigation/Refresh Vectors
- `<meta http-equiv="refresh" content="0;url=javascript:...">` — meta refresh redirect
- `<base href="javascript:...">` — base URL redirect

### CSS-Based Vectors
- `style="background: expression(alert(1))"` — IE CSS expressions
- `style="behavior: url(evil.htc)"` — IE CSS behavior
- `style="-moz-binding: url(evil.xml#xss)"` — Firefox XBL binding
- `style="background: url(javascript:...)"` — JavaScript URL in CSS
- `<style>` tags containing any of the above

## Obfuscation Handling

### Entity Encoding
- BeautifulSoup automatically decodes HTML entities in attribute values
- `&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;` → `javascript:`
- `&#x6A;avascript:` → `javascript:`
- `javascript&#58;alert(1)` → `javascript:alert(1)`

### Whitespace/Control Character Injection
- Strip all whitespace (spaces, tabs, newlines) and control characters before protocol detection
- `java\tscript:` → `javascript:`
- `java\nscript:` → `javascript:`
- `java\x00script:` → `javascript:` (null bytes pre-stripped)
- `  javascript:` → `javascript:`

### Case Variation
- All comparisons are case-insensitive
- `<ScRiPt>`, `JAVASCRIPT:`, `OnClIcK` all detected

### Mixed Techniques
- Entity-encoded + whitespace: `&#106;ava\tscript:` 
- The parser decodes entities first, then whitespace stripping catches the rest

## Preservation Fidelity

### What Must Be Preserved
- Document structure (DOCTYPE, html, head, body, sections)
- Text content and visible elements
- Safe attributes (class, id, style without dangerous constructs, data-* attributes)
- Tables, forms (with safe actions), lists, semantic HTML
- Images with safe src, links with safe href
- SVG graphics (shapes, paths, safe animations, transforms)
- MathML equations
- Entity references in text content
- Comments (except dangerous ones)

### What Gets Modified
- Dangerous tags are removed entirely (decompose)
- Dangerous attributes are removed from their elements
- `javascript:` URLs in href/src/action are removed (attribute deleted, element kept)
- CSS expressions/behaviors are sanitized in style attributes and style tags
- Attribute order may change (BeautifulSoup normalization)
- Void elements may be self-closed (`<img/>` instead of `<img>`)
- Character encoding in meta tags may be lowercased

## Implementation Pattern

```python
#!/usr/bin/env python3
import sys, re
from bs4 import BeautifulSoup, Comment

def is_javascript_url(value):
    """Detect javascript:/vbscript: URLs after stripping whitespace/control chars."""
    if not value or not isinstance(value, str):
        return False
    cleaned = re.sub(r'[\s\x00-\x1f\x7f]+', '', value).lower()
    return cleaned.startswith('javascript:') or cleaned.startswith('vbscript:')

def is_event_handler_attr(attr_name):
    return attr_name.lower().startswith('on')

def is_dangerous_data_url(value):
    cleaned = re.sub(r'[\s\x00-\x1f\x7f]+', '', value).lower()
    if cleaned.startswith('data:'):
        return any(cleaned.startswith(f'data:{mime}') for mime in 
                   ['text/html', 'image/svg+xml', 'application/xhtml+xml'])
    return False

def sanitize_html(content):
    content = content.replace('\x00', '')
    soup = BeautifulSoup(content, 'html.parser')
    
    # 1. Remove dangerous tags entirely
    for tag_name in ['script', 'iframe', 'object', 'embed', 'applet']:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    
    # 2. Remove dangerous attributes from all remaining tags
    URL_ATTRS = {'href','src','action','formaction','data','poster',
                 'dynsrc','lowsrc','background','codebase','classid',
                 'xlink:href','actionurl','srcdoc','ping'}
    
    for tag in soup.find_all(True):
        for attr_name in list(tag.attrs.keys()):
            val = tag.attrs[attr_name]
            if isinstance(val, list):
                val = ' '.join(str(v) for v in val)
            val_str = str(val) if val else ''
            
            if is_event_handler_attr(attr_name):
                del tag[attr_name]
            elif attr_name.lower() in URL_ATTRS:
                if is_javascript_url(val_str) or is_dangerous_data_url(val_str):
                    del tag[attr_name]
    
    # 3. Handle special elements (meta refresh, base, style, etc.)
    # ... (see full implementation)
    
    return str(soup)

def main():
    filepath = sys.argv[1]
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    sanitized = sanitize_html(content)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(sanitized)

if __name__ == '__main__':
    main()
```

## Key Design Decisions

1. **Remove vs. neutralize**: Dangerous tags (script, iframe, etc.) are removed entirely. Dangerous attributes (on*, javascript: hrefs) are removed but the element is kept. This preserves document structure while eliminating execution paths.

2. **SVG animation elements**: Not removed entirely unless dangerous. An animation element (`<set>`, `<animate>`, `<animateTransform>`, `<animateMotion>`, `<animateColor>`) is dangerous if: (a) it has on* event handlers, (b) it has javascript: URLs in its own href/xlink:href, (c) its `attributeName` targets an on* attribute, (d) its `attributeName` targets a URL-bearing attribute AND `to`/`from`/`values` contain javascript:/vbscript:/dangerous data URLs, or (e) its `attributeName` targets `style` AND values contain dangerous CSS. The `values` attribute uses semicolons to separate keyframe values — each must be checked individually. Safe animations like `<animate attributeName="width" from="0" to="100"/>` are preserved.

3. **CSS sanitization**: Uses balanced-parenthesis-aware removal for `expression()` to handle nested calls like `expression(alert('XSS'))`. Property-level removal for `behavior:` and `-moz-binding:`.

4. **Comment handling**: Only removes comments that contain IE conditional syntax or script tags. Regular HTML comments are preserved.

5. **Form handling**: Removes `javascript:` from form `action` and `formaction` attributes but keeps the form element and its other attributes intact.

## Testing Strategy

When verifying the filter:
1. Test each vector category independently
2. Test combinations (e.g., SVG with event handlers AND javascript URLs)
3. Test obfuscation variants (entity encoding, case variation, whitespace injection)
4. Verify safe content preservation (structure, attributes, text, SVG graphics, MathML)
5. Test edge cases: broken nesting, duplicated attributes, empty elements, fragments vs full documents
