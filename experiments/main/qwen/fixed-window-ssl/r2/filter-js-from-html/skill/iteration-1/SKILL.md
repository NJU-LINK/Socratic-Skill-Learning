---
name: filter-js-from-html
description: Remove executable JavaScript behavior from HTML files while preserving legitimate document structure, SVG graphics, MathML equations, forms, and visible content. Handles SVG/MathML namespace-aware markup, event handlers, dangerous URL schemes, CSS-based execution, and various obfuscation techniques.
---

# Filter JavaScript from HTML

## Purpose

Remove executable JavaScript behavior from HTML files while preserving legitimate document structure, visible content, SVG graphics, MathML equations, forms, links, and non-dangerous attributes. The output should remain functionally identical to the input except for the removal of dangerous executable behavior.

## Core Approach

Use a parse-tree-walk strategy with BeautifulSoup + html5lib:

1. **Parse** HTML with html5lib (handles malformed HTML correctly, preserves SVG/MathML attribute case)
2. **Walk** the DOM tree recursively
3. **Filter** dangerous elements and attributes
4. **Serialize** back to HTML

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(html_content, 'html5lib')
for element in list(soup.find_all(True)):
    sanitize_element(element)
```

## Dangerous Vectors to Neutralize

### 1. Entire Tags (remove with all content)

- `script`, `iframe`, `object`, `embed`, `applet`
- `base` (can change base URL for all relative links)
- `isindex` (obsolete but executable)
- `noscript` (can cause mutation XSS when re-parsed)

### 2. Event Handler Attributes (remove attribute only)

All `on*` attributes on any element:
- `onclick`, `onmouseover`, `onerror`, `onload`, `onfocus`, `onblur`
- `onsubmit`, `onchange`, `oninput`, `onkeydown`, `onkeyup`
- SVG-specific: `onbegin`, `onend`, `onrepeat`, `onresize`, `onzoom`
- Any attribute starting with `on` (case-insensitive)

### 3. URL-Bearing Attributes with Dangerous Schemes

Check these attributes for dangerous URL schemes:
- `href`, `src`, `action`, `formaction`, `data`, `background`
- `dynsrc`, `lowsrc`, `poster`, `srcset`, `xlink:href`
- `cite`, `longdesc`, `codebase`, `classid`, `manifest`, `ping`

**Dangerous schemes:**
- `javascript:`, `vbscript:`, `livescript:`
- `data:text/html` or `data:application/xhtml` (HTML MIME types)

**URL normalization before checking:**
```python
# Strip whitespace, tabs, newlines, null bytes
cleaned = re.sub(r'[\x00-\x20]+', '', url).lower()
# Handle entity-encoded characters
cleaned = re.sub(r'&#x?[0-9a-f]+;?', '', cleaned, flags=re.IGNORECASE)
```

### 4. Style Attributes and Blocks

**Inline `style` attributes:** Remove if containing:
- `expression()` (IE CSS expression)
- `url(javascript:...)` or `url(vbscript:...)`
- `behavior:` (IE behavior)
- `-moz-binding:` (Firefox XBL binding)

**`<style>` blocks:** Remove entire block if text contains any of the above patterns, plus:
- `@import "javascript:..."` or `@import url(javascript:...)`
- `@import "vbscript:..."` or `@import url(vbscript:...)`
- `@import "data:..."` (data URIs in imports)

### 5. SVG-Specific Dangers

- `<script>` inside SVG
- `<animate>`, `<set>`, `<animateTransform>` with `attributeName` targeting event handlers or dangerous attributes
- `<a xlink:href="javascript:...">` inside SVG
- `<foreignObject>` can contain arbitrary HTML (sanitize its contents)
- Event handlers on any SVG element (`onload`, `onerror`, etc.)

**SVG animation check:**
```python
if tag.name.lower() in ('animate', 'set', 'animatemotion', 'animatetransform'):
    attr_name = tag.get('attributeName', '').lower()
    if attr_name.startswith('on') or attr_name in ('href', 'style'):
        # Remove entire element
```

### 6. MathML-Specific Dangers

- `<annotation-xml encoding="text/html">` can embed executable HTML
- Sanitize content inside annotation-xml elements

### 7. Form-Related Execution

- `<form action="javascript:...">`
- `<input type="submit" formaction="javascript:...">`
- `<button formaction="javascript:...">`

### 8. Meta and Link Tags

**Meta tags:** Remove if `http-equiv="refresh"` with URL containing `javascript:`

**Link tags:** Remove if:
- `rel="import"` (HTML imports)
- `rel="preload"` or `rel="prefetch"` with `as="script"`

## Implementation Details

### Fragment vs Full Document Detection

Detect whether input is a fragment (no `<html>`, `<head>`, `<body>` structure):

```python
def is_fragment(html_content):
    return not re.search(r'<(!doctype\s+html|html|head|body)\b', 
                         html_content, re.IGNORECASE)
```

For fragments, extract content from both `<head>` and `<body>` after sanitization:

```python
if fragment:
    output_parts = []
    
    # Collect head children (style, link, meta, etc.)
    head = soup.head
    if head:
        for child in head.children:
            if isinstance(child, str) and not child.strip():
                continue
            output_parts.append(str(child))
    
    # Collect body children
    body = soup.body
    if body:
        for child in body.children:
            if isinstance(child, str) and not child.strip():
                continue
            output_parts.append(str(child))
    
    return '\n'.join(output_parts)
```

This ensures `<style>` and `<link>` elements in fragments are preserved (they belong in `<head>` but should still appear in fragment output).

### Case Preservation

html5lib preserves SVG/MathML attribute case (e.g., `viewBox`, `preserveAspectRatio`), but BeautifulSoup with html.parser lowercases them. Use html5lib backend.

### Attribute Case-Insensitive Lookup

BS4 stores attributes with original case, so use case-insensitive lookup:

```python
def get_attr_case_insensitive(element, attr_name):
    attr_lower = attr_name.lower()
    for key, value in element.attrs.items():
        if key.lower() == attr_lower:
            return value
    return None
```

### srcset Handling

`srcset` contains multiple URLs with descriptors. Check each URL:

```python
parts = srcset_value.split(',')
for part in parts:
    tokens = part.strip().split()
    if tokens and is_dangerous_url(tokens[0]):
        # Skip this source
```

## Edge Cases and Obfuscation

### Encoding Tricks

- Entity-encoded URLs: `&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;`
- Mixed case: `JaVaScRiPt:`
- Whitespace/null bytes: `java\tscript:`, `java\x00script:`
- HTML entities in attributes: `&Tab;`, `&NewLine;`

**Solution:** Normalize URLs before checking by stripping whitespace and decoding entities.

### Malformed HTML

- Unclosed tags
- Mismatched nesting
- Missing quotes on attributes
- Duplicate attributes

**Solution:** html5lib handles these correctly per HTML5 spec.

### Conditional Comments

IE conditional comments can contain executable content:
```html
<!--[if IE]><script>alert(1)</script><![endif]-->
```

**Solution:** Remove comments matching `/\[if\s/i`.

## Preservation Requirements

**Preserve:**
- Document structure (DOCTYPE, html, head, body)
- Visible text content
- Safe HTML elements and attributes
- SVG graphics (with case-sensitive attributes)
- MathML equations
- Forms (with safe actions)
- Links (with safe URLs)
- Images, videos, audio (with safe sources)
- Tables, lists, semantic HTML
- Comments (except conditional comments)
- Entities (`&amp;`, `&lt;`, etc.)

**Do not alter safe content more than necessary.** Attribute ordering may change (html5lib sorts alphabetically), but this is functionally equivalent.

## Testing Checklist

- [ ] Script tags removed
- [ ] Event handlers removed from all elements
- [ ] javascript: URLs removed from href, src, action, etc.
- [ ] data:text/html URLs removed
- [ ] SVG with onload, onerror removed
- [ ] SVG animate/set with dangerous attributeName removed
- [ ] MathML annotation-xml content sanitized
- [ ] Style attributes with expression/behavior/-moz-binding removed
- [ ] Style blocks with dangerous CSS removed (including @import with dangerous schemes)
- [ ] iframe, object, embed, applet removed
- [ ] base tag removed
- [ ] meta refresh with javascript: removed
- [ ] link rel="import" removed
- [ ] Fragments not wrapped in html/head/body
- [ ] Full documents preserve structure
- [ ] SVG viewBox, preserveAspectRatio case preserved
- [ ] Entities preserved
- [ ] Safe content unchanged

## Dependencies

The solution requires `beautifulsoup4` and `html5lib`. Auto-install them at the top of the script:

```python
import subprocess, sys

try:
    import html5lib
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'html5lib', '-q'])
    import html5lib

try:
    from bs4 import BeautifulSoup
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'beautifulsoup4', '-q'])
    from bs4 import BeautifulSoup
```

## Common Mistakes

1. **Using regex for sanitization** — easily bypassed by case variation, encoding, whitespace
2. **Lowercasing SVG attributes** — breaks `viewBox`, `preserveAspectRatio`, etc.
3. **Forgetting noscript** — can cause mutation XSS
4. **Not normalizing URLs** — misses obfuscated javascript: URLs
5. **Wrapping fragments** — adds unwanted html/head/body structure
6. **Removing entire style blocks** — loses legitimate CSS (check content first)
7. **Forgetting xlink:href** — SVG links use this attribute
8. **Not checking formaction** — separate from action attribute
9. **Forgetting @import in style blocks** — can load javascript: URLs
10. **Fragment extraction only from body** — misses style/link in head
