---
name: filter-js-from-html
description: Remove executable JavaScript from HTML while preserving document structure and safe content
---

# Filter JavaScript from HTML

## Overview

This skill removes executable JavaScript behaviors from HTML documents while preserving safe content, document structure, and legitimate visible elements. It uses capability-based neutralization rather than element blacklisting.

## Policy: Drop vs Strip vs Keep

### Drop Subtree Entirely (Remove Element + Content)

These elements are pure execution/embedding vectors with no benign visible payload:

| Element | Reason |
|---------|--------|
| `<script>` | Executes JavaScript (HTML and SVG namespaces) |
| `<iframe>` | Embeds arbitrary content |
| `<frame>`, `<frameset>` | Legacy frame embedding |
| `<handler>`, `<listener>` | SVG Tiny execution vectors |
| Dangerous SMIL (`<animate>`, `<set>`) | Animating `href` or `on*` attributes |
| Dangerous `<meta refresh>` | JavaScript or data: URLs in refresh |

### Keep Element, Strip Dangerous Attributes

These elements have legitimate visible content or safe use cases:

| Element | Action | Rationale |
|---------|--------|-----------|
| `<form>` | Strip dangerous `action` | Form structure is safe; only URL matters |
| `<button>`, `<input>` | Strip dangerous `formaction` | Same as form action |
| `<a>`, `<area>`, `<base>` | Strip dangerous `href` | Links are safe; only URL matters |
| `<object>` | Strip `data`/`codebase`/`classid` | Keep fallback content visible |
| `<embed>` | Strip `src` | Void element, no fallback |
| `<img>`, `<image>`, `<video>`, `<audio>` | Sanitize `src` | Resource context allows data:image |
| `<svg>`, `<math>` | Sanitize attributes | Keep graphics/equations; remove `onload` etc. |
| `<noscript>` | Sanitize children | Container element, sanitize contents |

### Safe Attributes (Always Keep)

- Standard structural: `id`, `class`, `style` (CSS can't execute JS)
- Layout: `width`, `height`, `colspan`, `rowspan`
- Content: `alt`, `title`, `lang`, `dir`
- Form: `name`, `value`, `type`, `method`, `enctype` (without dangerous URL)

## Browser-Accurate Mechanics

### Event Handler Detection

**Rule:** Any attribute starting with `on` (case-insensitive) is an event handler.

```python
def is_event_handler_attr(name):
    return name.lower().startswith('on') and len(name) > 2
```

This catches:
- Standard: `onclick`, `onload`, `onerror`
- SVG/SMIL: `onbegin`, `onend`, `onrepeat`
- Future/Vendor: `ontoggle`, `onsecuritypolicyviolation`

**Do not enumerate event names** - browsers bind any `on*` attribute.

### URL Normalization

Browsers normalize URLs by:
1. Entity-decoding (parser already does this)
2. Removing TAB (0x09), LF (0x0A), CR (0x0D), and NUL (0x00) anywhere in URL
3. Lowercasing the scheme

```python
import re
WS_CHARS = re.compile(r'[\x00\x09\x0a\x0d]')

def normalize_url(value):
    return WS_CHARS.sub('', value).lstrip().lower()
```

This means `jav\tascript:alert(1)` and `javascript:alert(1)` are equivalent.

### URL Scheme Danger Assessment

```python
def is_dangerous_url(url, is_navigation):
    normalized = normalize_url(url)
    scheme = normalized.split(':', 1)[0]
    
    if scheme in ('javascript', 'vbscript'):
        return True
    
    if scheme == 'data':
        if is_navigation:
            return True  # Never allow data: in navigation
        # Only allow passive images in resource contexts
        if not re.match(r'data:image/(png|gif|jpe?g|webp|avif|bmp|x-icon|svg\+xml)', normalized):
            return True
    
    return False
```

**Navigation contexts** (`is_navigation=True`): `href`, `xlink:href`, `action`, `formaction`
- These navigate the browser to the URL
- Block: `javascript:`, `vbscript:`, `data:` (always)

**Resource contexts** (`is_navigation=False`): `src`, `data`, `poster`, `background`
- These load as subresources
- Block: `javascript:`, `vbscript:`, `data:text/html`, `data:image/svg+xml` (executable)
- Allow: `data:image/png`, `data:image/jpeg`, etc. (passive images)

### Duplicate Attributes

**Rule:** Keep the first occurrence; browsers use first-wins semantics.

```python
def remove_duplicate_attrs(attrs):
    seen = set()
    result = []
    for name, value in attrs:
        name_lower = name.lower()
        if name_lower not in seen:
            seen.add(name_lower)
            result.append((name, value))
    return result
```

Attack: `<a href="javascript:evil()" href="https://safe.com">` - keep `href="javascript:evil()"`, evaluate danger, remove attribute.

### Safe Re-emission

**Critical:** Text and attributes must be escaped on output to prevent entity resurrection.

```python
from html import escape

# Text content: preserve entities by using convert_charrefs=False
# Attribute values: escape quotes
escaped_value = escape(value, quote=True)
```

With `convert_charrefs=False`, the parser preserves entities:
- Input: `&lt;script&gt;`
- Parser receives: `&lt;script&gt;` (not `<script>`)
- Output: `&lt;script&gt;` (safe)

With `convert_charrefs=True` (default), the parser decodes entities:
- Input: `&lt;script&gt;`
- Parser receives: `<script>` (literal)
- Output without escaping: `<script>` (dangerous - resurrects tag!)

## Vector Taxonomy

### HTML Vectors

| Vector | Location | Mitigation |
|--------|----------|------------|
| `<script>...</script>` | Anywhere | Drop subtree |
| `<script src="...">` | src attribute | Drop subtree |
| `<tag on*=...>` | Any element | Strip on* attribute |
| `<a href="javascript:...">` | href | Strip href |
| `<form action="javascript:...">` | action | Strip action |
| `<input formaction="javascript:...">` | formaction | Strip formaction |
| `<meta http-equiv="refresh" content="...;url=javascript:...">` | content | Drop meta |
| `<iframe src="...">` | src | Drop subtree |
| `<iframe srcdoc="<script>...">` | srcdoc | Drop subtree |
| `<object data="javascript:...">` | data | Strip data |
| `<embed src="javascript:...">` | src | Strip src |
| `<base href="javascript:...">` | href | Strip href |

### SVG Vectors

| Vector | Location | Mitigation |
|--------|----------|------------|
| `<svg onload="...">` | Any SVG element | Strip on* attribute |
| `<svg><script>...</script>` | script in SVG namespace | Drop subtree |
| `<a xlink:href="javascript:...">` | xlink:href | Strip attribute |
| `<set attributeName="onload" to="...">` | SMIL animation | Drop SMIL |
| `<animate attributeName="href" values="...">` | Animating href | Drop SMIL |
| `<animate attributeName="xlink:href">` | Animating xlink:href | Drop SMIL |
| `<foreignObject>` | HTML integration point | Sanitize children |
| `<handler>`, `<listener>` | SVG Tiny | Drop subtree |

### MathML Vectors

| Vector | Location | Mitigation |
|--------|----------|------------|
| `<math href="javascript:...">` | href | Strip href |
| `<annotation-xml encoding="text/html">` | HTML content | Sanitize children |

### Obfuscation Vectors

| Technique | Example | Mitigation |
|-----------|---------|------------|
| Tab/LF/CR in URL | `href="jav\tascript:..."` | Strip WS_CHARS before scheme check |
| Mixed case | `<ScRiPt>` | Lowercase for comparison |
| HTML entities | `href="jav&#97;script:..."` | Parser decodes before filtering |
| Duplicate attrs | `href="evil" href="safe"` | Evaluate first occurrence |
| data:text/html | `href="data:text/html,<script>..."` | Block data: in navigation |
| Base64 data: | `href="data:text/html;base64,..."` | Block in navigation context |

## Verification Protocol

### 1. Benign Round-Trip

A file with legitimate content should pass through unchanged:

- DOCTYPE declaration
- Document structure (`html`, `head`, `body`)
- Forms with safe actions
- Tables, lists, paragraphs
- `data:image/*` URLs in `src` or `href`
- SVG graphics and MathML equations
- Object with fallback content
- noscript blocks
- HTML entities in text

### 2. Attack Neutralization

Each vector should be neutralized:

| Test File | Expected Result |
|-----------|-----------------|
| `svg_onload.html` | SVG kept, onload removed |
| `xlink_javascript.html` | SVG kept, xlink:href removed |
| `tab_obfuscated.html` | Link kept, href removed (obfuscated JS detected) |
| `data_text_html.html` | Link kept, href removed (data:text/html blocked) |
| `duplicate_attr.html` | Link kept, href removed (first value was evil) |
| `form_javascript_action.html` | Form kept, action removed |
| `object_javascript.html` | Object kept, data removed, fallback preserved |
| `meta_refresh_js.html` | Meta removed entirely |
| `mixed_case_script.html` | Script dropped (case-insensitive) |
| `iframe_any.html` | Iframe dropped (entire subtree) |
| `svg_smil_href.html` | Dangerous SMIL dropped |

### 3. Idempotence Check

Running the filter twice should produce the same output:

```bash
filter input.html > pass1.html
filter pass1.html > pass2.html
diff pass1.html pass2.html  # Should be empty
```

Idempotence failures indicate escaping bugs.

## Implementation Notes

### Parser Choice

Uses `html.parser.HTMLParser` (stdlib) with `convert_charrefs=False`:
- Preserves entity references in output
- Handles malformed HTML (browser-tolerant)
- No external dependencies

Alternative: `html5lib` provides more browser-accurate parsing but requires installation.

### Known Limitations

1. **No CSS parsing**: `<style>` content is passed through. Modern browsers don't execute JS from CSS, but `@import` with JavaScript URLs is theoretically possible in some legacy browsers.

2. **Namespace unaware**: `html.parser` doesn't track XML namespaces. SVG elements are handled by tag name matching, which works for inline SVG in HTML5.

3. **No URL validation**: Only checks scheme, not full URL structure. A malformed URL might slip through if scheme check passes.

4. **No script detection in data URLs**: If `data:text/html` somehow passes, embedded scripts would execute. The mitigation is blocking all `data:text/html` in navigation contexts.

## Usage

```python
from scripts.sanitize_html import filter_html

html_content = open('input.html').read()
safe_html = filter_html(html_content)
```

Or as a script:

```bash
python scripts/sanitize_html.py input.html
# Modifies file in-place
```
