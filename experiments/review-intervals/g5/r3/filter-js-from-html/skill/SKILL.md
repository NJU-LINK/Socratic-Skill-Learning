---
name: filter-js-from-html
description: Remove executable JavaScript behavior from HTML files while preserving safe content, handling SVG/MathML, malformed markup, and obfuscated payloads
---

# Filter JavaScript from HTML

Remove executable JavaScript behavior from HTML documents while preserving legitimate structure, visible content, and safe functionality.

## Core Architecture

Use a real HTML parser (BeautifulSoup4 with html.parser backend, or lxml/html5lib if available). Never use regex for HTML sanitization — browsers use permissive parsers that will "fix" broken markup and still execute scripts.

```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(content, 'html.parser')
# Walk tree, remove dangerous nodes/attributes
output = str(soup)
```

## Threat Model: Executable HTML Vectors

### Script Elements
Remove entirely (including all children):
- `<script>`, `<script src="...">`, mixed-case variants
- Namespaced variants in SVG/MathML contexts

### Inline Event Handlers
Strip ALL attributes starting with `on` from ALL elements:
- Common: `onclick`, `onload`, `onerror`, `onfocus`, `onmouseover`
- Less common: `ontoggle`, `onanimationend`, `onpointerenter`, `onwheel`, `ondrag`, `oncopy`, `onpaste`
- There are 100+ event handler attributes — match by prefix `on*`

### JavaScript URLs
Check URL-bearing attributes after full normalization:
- Attributes: `href`, `src`, `action`, `formaction`, `data`, `poster`, `background`, `dynsrc`, `lowsrc`, `xlink:href`, `srcdoc`
- Dangerous schemes: `javascript:`, `vbscript:`, `livescript:`
- Dangerous data URLs: `data:text/html`, `data:text/html;base64`

**Normalization before checking:**
1. Decode HTML entities (`&#106;` → `j`, `&Tab;` → tab)
2. URL-decode (multiple rounds for layered encoding)
3. Strip whitespace and control characters (`\t`, `\n`, `\r`, `\0`)
4. Case-insensitive comparison

```python
import html
from urllib.parse import unquote
import re

def normalize_url(value):
    decoded = html.unescape(value)
    for _ in range(5):  # Multiple rounds
        prev = decoded
        decoded = unquote(decoded)
        if decoded == prev:
            break
    # Strip whitespace, control chars, AND replacement character (U+FFFD)
    cleaned = re.sub(r'[\s\x00-\x1f\x7f\ufffd]', '', decoded)
    return cleaned.lower()
```

### Dangerous Elements
Remove entirely:
- `<iframe>`, `<frame>`, `<frameset>` — embed external content
- `<object>`, `<embed>`, `<applet>` — plugin content
- `<base>` — rewrites all relative URLs

Conditional removal:
- `<meta http-equiv="refresh">` — only remove if content contains dangerous URL (e.g., `javascript:`). Keep safe meta tags like `<meta charset="utf-8">` and `<meta name="viewport">`. **Important**: extract the URL using regex `url\s*=\s*(.*)` to handle spaces around `=` (e.g., `URL = javascript:alert(1)`).
- `<link>` — apply normal URL attribute filtering. Remove only if `href` is dangerous. Keep safe links like `<link rel="stylesheet">` and `<link rel="icon">`.

### SVG-Specific Vectors
- `<animate>`, `<set>`, `<animateMotion>` — can set attributes on other elements, including `on*` handlers
  - **Conditional removal**: Only remove if they set dangerous attributes
  - Check `attributeName`: if it's an `on*` event handler (e.g., `onload`, `onclick`), remove the element
  - Check `to` attribute: if it's a dangerous URL (`javascript:`, `vbscript:`), remove the element
  - Check `xlink:href` being set to dangerous URLs
  - **Safe animations preserved**: `<animate attributeName="fill" values="red;blue">` is safe and should be kept
- `<foreignObject>` — embeds full HTML inside SVG, always remove
- `<use xlink:href="data:...">` — can load dangerous content, check href
- Event handlers on any SVG element: `<svg onload="...">`, `<g onload="...">` — strip `on*` attributes

### MathML-Specific Vectors
- `<maction actiontype="statusline">` — clicking triggers URL from text content
- `<script>` inside `<math>`
- Event handlers on `<math>` or child elements

### Form-Related
- `<form action="javascript:...">`
- `<button formaction="javascript:...">`
- `<input formaction="javascript:...">`

### Style/CSS Vectors
Sanitize `style` attributes and `<style>` element content:
- `expression(...)` — IE CSS expression
- `behavior:` — IE behavior
- `-moz-binding:` — Firefox XBL binding
- `url(javascript:...)` — CSS url() with dangerous scheme
- `url(data:text/html...)` — CSS url() with data URI containing HTML
- `@import` with dangerous URLs (javascript:, vbscript:, data:text/html)
- `-o-link:` — Opera link

For `<style>` elements: if any dangerous pattern is found, remove the entire style content. CSS with embedded HTML/script content is inherently dangerous and surgical removal is error-prone.

For `style` attributes: parse declarations carefully to handle url() content with special characters (like data URIs containing semicolons). Remove only the dangerous declarations while preserving safe ones.

## Preservation Fidelity

Keep safe content intact:
- Document structure (`<html>`, `<head>`, `<body>`, semantic elements)
- Tables, forms, lists, semantic HTML
- Safe SVG graphics (`<path>`, `<circle>`, `<rect>`, `<text>`, `<g>`)
- Safe MathML elements (`<mi>`, `<mo>`, `<mn>`, `<mrow>`)
- Images, links (with safe URLs), formatting
- Text content and entities
- Safe attributes (class, id, style with safe values, etc.)

For style attributes: if only some declarations are dangerous, remove just those; keep safe declarations.

## HTML Parsing Irregularity

Handle malformed input gracefully:
- Broken nesting: `<b><i></b></i>`
- Missing end tags
- Unusual spacing and case variation
- Entity-encoded content
- Browser-tolerated invalid markup

BeautifulSoup's tree model handles these automatically. For token-stream approaches, be careful with nested dangerous elements: `<script><script>alert(1)</script></script>` — the inner `</script>` is just text.

## Payload Obfuscation

Detect obfuscated payloads through normalization:
- Entity encoding: `&#106;avascript:` → `javascript:`
- Hex entities: `&#x6A;avascript:` → `javascript:`
- Mixed case: `JaVaScRiPt:` → `javascript:`
- Whitespace/control chars: `java\tscript:` → `javascript:`
- URL encoding: `%6A%61%76%61%73%63%72%69%70%74%3A` → `javascript:`
- Layered encoding: multiple rounds of URL decoding
- Fragmented payloads across attributes or nodes

Always normalize before checking for dangerous patterns.

## Implementation Algorithm

1. **Parse** with BeautifulSoup (or equivalent real parser)
2. **Remove dangerous elements**:
   - Unconditionally remove: script, iframe, object, embed, applet, base, foreignObject, maction
   - Conditionally remove `<animate>`, `<set>`, `<animateMotion>`: only if they set dangerous attributes (check `attributeName` for `on*` handlers, check `to` for dangerous URLs)
   - For `<meta>`: only remove `http-equiv="refresh"` with dangerous URL
   - For `<link>`: apply normal URL attribute filtering
3. **Filter attributes** on all remaining elements:
   - Remove all `on*` event handlers
   - Remove `srcdoc` attribute
   - Check URL attributes: normalize and remove if dangerous
   - Sanitize `style` attributes: remove dangerous declarations
4. **Sanitize `<style>` element content**: remove dangerous CSS patterns
5. **Serialize** back to HTML string
6. **Write** to file (in-place modification)

## Fragment vs Full Document Handling

Detect if input is a fragment (no `<!DOCTYPE>` or `<html>` tag). For fragments, extract just the body content after parsing to avoid BeautifulSoup adding wrapper tags.

```python
is_fragment = not (content.strip().lower().startswith('<!doctype') or 
                   '<html' in content[:200].lower())

if is_fragment:
    body = soup.body
    if body:
        output = ''.join(str(c) for c in body.contents)
    else:
        output = str(soup)
else:
    output = str(soup)
```

## Key Pitfalls

1. **Don't unconditionally remove `<meta>` or `<link>`** — only remove when they contain dangerous URLs
2. **Don't unconditionally remove `<animate>` or `<set>`** — only remove when they set dangerous attributes (on* handlers, javascript: URLs)
3. **Meta refresh URL extraction** — use regex `url\s*=\s*(.*)` to handle `URL = javascript:...` with spaces
4. **Null bytes and replacement chars** — strip `\ufffd` (U+FFFD) in URL normalization, not just `\x00`
5. **Style sanitization** — check for `url(javascript:)` pattern, not just bare `javascript:`
6. **Fragment detection** — check for `<html` in first 500 chars, not just at start
7. **data:text/html in CSS** — check for `url(data:text/html...)` in both style attributes and style elements
8. **SVG animation href attributes** — check both `xlink:href` and `href` for dangerous URLs
9. **Style attribute parsing** — when splitting by semicolons, be aware that data URIs can contain semicolons (e.g., `data:text/html;base64,...`). Parse url() content carefully to avoid breaking declarations.

## Reference Implementation

See `scripts/filter.py` for a complete working implementation using BeautifulSoup4.

## Testing Strategy

Test against:
- Basic vectors: script tags, event handlers, javascript: URLs
- Obfuscation: entity encoding, mixed case, whitespace, URL encoding
- SVG/MathML: animate, set, foreignObject, maction
- Preservation: safe links, images, forms, tables, styles
- Edge cases: malformed HTML, nested dangerous elements, fragments
- Style sanitization: url(javascript:), expression(), behavior

Verify both removal of dangerous content AND preservation of safe content.
