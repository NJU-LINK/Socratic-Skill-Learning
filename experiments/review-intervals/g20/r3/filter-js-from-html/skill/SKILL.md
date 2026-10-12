---
name: filter-js-from-html
description: >
  Remove executable JavaScript behavior from HTML files while preserving
  legitimate document structure, visible content, vector graphics, equations,
  forms, links, and non-dangerous attributes. Handles direct script tags,
  inline event handlers, javascript:/vbscript: URLs, dangerous data: URLs,
  SVG/MathML executable vectors, meta refresh, base tag abuse, template
  content, and various obfuscation techniques including entity encoding,
  whitespace injection, case variation, and null bytes.
---

# Filter JavaScript from HTML

## Overview

This skill removes executable JavaScript behavior from HTML while preserving
all safe content. The approach uses BeautifulSoup with `html.parser` to parse
HTML, identify dangerous constructs, and remove them while keeping legitimate
structure intact.

## Architecture

The sanitizer operates in phases:

1. **Parse** the HTML with BS4 `html.parser` (handles entity decoding, case
   normalization, null byte stripping automatically)
2. **Remove dangerous elements** entirely (script, noscript, iframe, object,
   embed, applet, frame, frameset)
3. **Strip event handler attributes** (any `on*` attribute from any element)
4. **Handle special elements** (meta refresh, base tag, SVG animation
   [selective], SVG use)
5. **Clean URL-bearing attributes** (remove javascript:/vbscript:/dangerous
   data: URLs from href, src, action, etc.)
6. **Serialize** with ordered formatter to preserve attribute order

## Key Implementation Details

### Parser Choice

Use `html.parser` (not `lxml` or `html5lib`). Key behaviors:
- Decodes HTML entities in attribute values (`&#106;` → `j`)
- Lowercases ALL tag names and attribute names (including camelCase SVG attrs)
- Strips null bytes from values
- Parses inside `<template>` elements
- Treats SVG `<script>` as regular script (which is what you want)

**Critical gotcha**: BS4 lowercases `attributeName` → `attributename`,
`httpEquiv` → `httpequiv`, etc. Always use lowercase keys when accessing
BS4 attributes.

### Dangerous Elements (Remove Entirely)

```python
REMOVE_ELEMENTS = frozenset([
    'script', 'noscript',
    'iframe', 'frame', 'frameset',
    'object', 'embed', 'applet',
    'foreignobject',  # Can embed arbitrary HTML with own execution context
])
```

`<noscript>` is counter-intuitively dangerous: if scripts are stripped but
noscript content remains, the noscript content renders and any markup with
event handlers inside it will execute.

`<foreignObject>` can embed arbitrary HTML (including `<body>`, `<html>`, etc.)
with its own execution context. Even after stripping event handlers from inner
elements, the foreignObject itself should be removed entirely.

### Event Handler Detection

Strip any attribute whose lowercase name starts with `on`:
```python
for attr_name in list(tag.attrs.keys()):
    if attr_name.lower().startswith('on'):
        del tag.attrs[attr_name]
```

This catches onclick, onerror, onload, onmouseover, onfocus, onblur,
onsubmit, onanimationend, ontransitionend, ontoggle, etc.

### URL Safety Detection

For URL-bearing attributes, normalize then check. The normalization chain
must handle multiple encoding layers:

```python
from urllib.parse import unquote

def normalize_url_value(value):
    if not value:
        return ''
    # 1. Decode percent-encoding (multi-pass for layered encoding)
    cleaned = value
    for _ in range(3):  # up to 3 layers
        decoded = unquote(cleaned)
        if decoded == cleaned:
            break
        cleaned = decoded
    # 2. Strip whitespace, null bytes, control characters
    cleaned = re.sub(r'[\s\x00-\x1f]+', '', cleaned)
    # 3. Lowercase
    return cleaned.lower()

def is_dangerous_url(value):
    normalized = normalize_url_value(value)
    # Check dangerous schemes
    if normalized.startswith(('javascript:', 'vbscript:', 'livescript:')):
        return True
    # Check dangerous data: MIME types
    if normalized.startswith('data:'):
        mime_match = re.match(r'data:([^;,]+)', normalized)
        if mime_match:
            mime = mime_match.group(1).strip()
            if mime in DANGEROUS_DATA_MIMES:
                return True
    return False
```

**Critical: Percent-encoding handling**

BS4 decodes HTML entities (`&#106;` → `j`) but does NOT decode URL
percent-encoding (`%6a` stays as `%6a`). The browser, however, decodes
percent-encoding in URL attributes. So `%6a%61%76%61%73%63%72%69%70%74%3a`
is `javascript:` after browser decoding.

The normalization chain must:
1. Apply `urllib.parse.unquote()` in a loop (up to 3 passes) to handle
   layered encoding: `%256a` → `%6a` → `j`
2. Strip whitespace/control chars (handles `java\tscript:`)
3. Lowercase (handles `JavaScript:`)

This single normalization function is shared by all URL checks:
- `is_dangerous_url()` for URL-bearing attributes
- `is_meta_refresh_dangerous()` for meta refresh content
- `is_svg_use_dangerous()` for SVG `<use>` href detection

**URL-bearing attributes** to check:
- `href` (a, area, link, base)
- `src` (img, iframe, script, input, audio, video, source, track, embed)
- `action` (form), `formaction` (button, input[type=submit])
- `data` (object), `poster` (video)
- `dynsrc`, `lowsrc`, `background` (legacy)
- `ping` (a, area), `usemap`
- `xlink:href` (SVG use)

**Dangerous data: MIME types**:
- `text/html`, `application/xhtml+xml`
- `image/svg+xml` (SVG can contain scripts)
- `text/xml`, `application/xml`

**Safe data: MIME types**: `image/png`, `image/jpeg`, `image/gif`,
`text/css`, `application/json`, etc.

### Style Attribute Handling

CSS `style` attributes can contain embedded JavaScript through several
mechanisms. Check for and remove `style` attributes containing:

- `url(javascript:...)` or `url(vbscript:...)` — CSS url() with dangerous schemes
- `expression(...)` — IE-specific CSS expression that executes JavaScript
- `-moz-binding:url(...)` — Firefox XBL binding that can load external content
- `behavior:url(...)` — IE CSS behavior that can load external content

```python
def is_style_dangerous(style_value):
    if not style_value:
        return False
    normalized = normalize_url_value(style_value)
    # Check for url() with dangerous schemes
    if re.search(r'url\s*\(\s*["\']?(?:javascript|vbscript|livescript):', normalized):
        return True
    # Check for expression() (IE-specific)
    if 'expression(' in normalized:
        return True
    # Check for -moz-binding or behavior
    if re.search(r'(-moz-binding|behavior)\s*:', normalized):
        return True
    return False
```

Safe styles like `color: red; font-weight: bold` are preserved.

### Meta Refresh Handling

`<meta http-equiv="refresh" content="0;url=javascript:...">` — the dangerous
value is inside the `content` attribute. Parse the content string for `url=`
followed by a dangerous scheme. Remove the entire meta element if dangerous.

### Base Tag Handling

`<base href="javascript:...">` changes URL resolution for the entire page.
Remove the entire base element if its href is dangerous. **Important**: check
base href BEFORE the general URL attribute stripping, otherwise the href gets
removed but the empty base tag survives.

### SVG-Specific Vectors

1. **Animation elements** (`<set>`, `<animate>`, `<animateTransform>`,
   `<animateMotion>`, `<animateColor>`): These are **selectively** removed.
   An animation element is dangerous and should be removed if:
   - `attributeName` starts with `on` (e.g., `attributeName="onload"` sets event handlers)
   - `to`, `from`, or `values` contains a dangerous URL (javascript:, vbscript:, etc.)
   
   Safe animations (e.g., `<animate attributeName="fill" values="red;blue">`)
   are **preserved** — they only change visual properties and pose no security risk.
   
   **Critical gotcha**: BS4 lowercases `attributeName` → `attributename`.
   Always check `tag.get('attributename')` (lowercase).

2. **`<use>` elements**: Do NOT remove the element entirely. Instead, treat
   `href`/`xlink:href` as URL-bearing attributes and strip them if they contain
   dangerous URLs (javascript:, vbscript:, etc.). The `<use>` element itself
   should survive with its dangerous href removed.

3. **`<foreignObject>`**: Remove entirely. Can embed arbitrary HTML (including
   `<body>`, `<html>`, etc.) with its own execution context. Even after
   stripping event handlers from inner elements, the foreignObject itself
   remains a security risk.

4. **Event handlers on SVG elements**: `<svg onload="...">` — handled by
   the general `on*` stripping.

### Template Content

BS4 `html.parser` parses inside `<template>`, so `find_all('script')` catches
scripts inside templates. This is correct behavior since template content
could be activated by remaining JS.

### Attribute Order Preservation

BS4 sorts attributes alphabetically by default. Use a custom formatter:
```python
class OrderedFormatter(HTMLFormatter):
    def attributes(self, tag):
        for k, v in tag.attrs.items():
            yield k, v
```

### Known Normalization Differences

BS4 output differs from input in these acceptable ways:
- Entity-decoded attribute values (`&#106;` → `j`)
- Self-closing slash on void elements (`<br>` → `<br/>`)
- Boolean attributes get `=""` (`required` → `required=""`)
- Attribute values use double quotes consistently
- Tag names lowercased (`<DIV>` → `<div>`)

These don't change browser-visible behavior and are acceptable per the
spec's "Do not alter safe content any more than necessary" requirement.

## Testing Checklist

When verifying a sanitizer implementation, test:

- [ ] `<script>` removal (all cases, mixed case)
- [ ] `<noscript>` removal
- [ ] `<iframe>`, `<object>`, `<embed>`, `<applet>` removal
- [ ] `<foreignObject>` removal (entire element, not just inner content)
- [ ] `on*` event handler stripping from all element types
- [ ] `javascript:` URL detection (plain, spaced, tabbed, entity-encoded, percent-encoded)
- [ ] `vbscript:` and `livescript:` URL detection
- [ ] `data:text/html` and `data:image/svg+xml` URL removal
- [ ] Safe `data:image/png` URLs preserved
- [ ] `<meta http-equiv="refresh">` with javascript: URL removed
- [ ] `<base href="javascript:...">` removed entirely
- [ ] SVG `<set>` with dangerous `attributeName` (starts with `on`) removed
- [ ] SVG `<animate>` with dangerous `to`/`from`/`values` URL removed
- [ ] SVG `<animate>` with safe attributes (e.g., `attributeName="fill"`) preserved
- [ ] SVG `<use>` with dangerous href: href stripped, element preserved
- [ ] SVG `<use>` with safe `#id` href: preserved as-is
- [ ] `style="...url(javascript:...)"` attribute removed
- [ ] `style="color: red"` safe styles preserved
- [ ] `<template>` inner scripts removed
- [ ] Safe HTML structure preserved (tables, forms, semantic elements)
- [ ] Safe links and images preserved
- [ ] Attribute order preserved
- [ ] Comments preserved
