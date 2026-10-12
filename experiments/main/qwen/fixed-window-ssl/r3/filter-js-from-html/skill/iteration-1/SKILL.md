---
name: filter-js-from-html
description: >
  Remove executable JavaScript behavior from HTML files while preserving safe document structure,
  visible content, forms, links, images, SVG graphics, MathML equations, and non-dangerous attributes.
  Handles direct script tags, inline event handlers, javascript:/vbscript:/livescript:/mhtml: URLs,
  data:text/html URLs, dangerous CSS expressions, SVG/MathML-specific execution vectors, and
  combination attacks. Neutralizes obfuscated payloads using HTML entities, percent-encoding, and
  whitespace insertion.
---

# Filter JavaScript from HTML

## Decision Framework: Remove vs. Sanitize

### Remove Entirely (tags whose primary purpose is execution/loading)
- `<script>`, `<iframe>`, `<object>`, `<embed>`, `<applet>`, `<isindex>`
- `<base>` (combination attack: rewrites all relative URLs to attacker domain)

### Sanitize at Attribute Level (tags with legitimate uses)
- **Forms** (`<form>`, `<input>`, `<button>`, `<textarea>`, `<select>`): preserve structure, neutralize `action`/`formaction` only when containing dangerous URLs
- **Links/Images** (`<a>`, `<img>`): preserve structure, neutralize `href`/`src` only when containing dangerous URLs
- **SVG/MathML**: preserve graphics and equations, remove event handlers and dangerous attributes
- **`<link>`, `<meta>`**: preserve, neutralize specific dangerous patterns (http-equiv=refresh with javascript: URL)
- **`<foreignObject>`**: preserve container, remove dangerous children/attributes

## Attack Vectors

### 1. Script Containers
- `<script>` tags (anywhere, including inside SVG/MathML)
- Event handlers: `onclick`, `onload`, `onerror`, `onmouseover`, `onfocus`, etc.

### 2. Dangerous URL Protocols
Neutralize to `about:blank` in URL-bearing attributes:
- `javascript:` — primary execution vector
- `vbscript:` — VBScript (older IE)
- `livescript:` — old Netscape alias
- `mhtml:` — MIME HTML combination attack

**Attributes to check**: `href`, `src`, `action`, `formaction`, `data`, `xlink:href`, `background`, `poster`, `srcset`, `usemap`, `longdesc`, `cite`, `manifest`, `ping`

### 3. Data URLs Embedding HTML
- `data:text/html,...` and `data:application/xhtml,...` — can embed executable HTML

### 4. Dangerous CSS
In `style` attributes and `<style>` element text:
- `expression(...)` — IE CSS expression (executes JavaScript)
- `-moz-binding: url(...)` — Firefox XBL binding
- `behavior: url(...)` — IE behavior
- `url(javascript:...)` — JavaScript in CSS url()
- `@import url("javascript:...")` — JavaScript in @import

### 5. SVG/MathML-Specific
- `<svg onload="...">` — event handler on SVG root
- `<animate attributeName="onload" to="alert(1)">` — animation targeting event handler
- `<animate attributeName="xlink:href" values="javascript:...">` — animation setting dangerous URL
- `<set attributeName="onclick" to="alert(1)">` — set element targeting event handler
- `<script>` inside SVG/MathML — remove entirely

### 6. Combination Attacks
- `<base href="http://evil.com/">` — rewrites all relative URLs
- `<meta http-equiv="refresh" content="0;url=javascript:...">` — remove both http-equiv and content

## Obfuscation Handling

### Encoding Tricks
Payloads use encodings to bypass filters:
- **HTML entities**: `&#106;avascript:` (decimal), `&#x6a;avascript:` (hex)
- **Percent-encoding**: `java%73cript:` (%73 = 's')
- **Whitespace**: `java\tscript:`, `java\nscript:`
- **Null bytes**: `java\x00script:`
- **Mixed case**: `JaVaScRiPt:`

### Normalization Strategy
**Before checking for dangerous patterns, normalize:**
1. Decode HTML entities (decimal and hex)
2. Decode percent-encoding
3. Remove null bytes
4. Collapse whitespace
5. Apply pattern matching on normalized form

**Note**: BeautifulSoup with `html.parser` automatically decodes HTML entities in attribute values, so regex patterns should handle the *decoded* form.

## Implementation

### Parser: BeautifulSoup + html.parser
- Handles malformed HTML
- Preserves tag names (SVG/MathML as plain strings)
- Auto-decodes HTML entities in attributes
- No namespace awareness needed (we match tags as lowercase strings)

### Processing Pipeline

1. **Parse HTML** with BeautifulSoup
2. **Remove dangerous tags**: script, iframe, object, embed, applet, isindex, base
3. **Sanitize attributes** on remaining tags:
   - Remove event handlers (on* attributes)
   - Neutralize dangerous URLs → `about:blank`
   - Sanitize style attributes (remove dangerous CSS)
   - Handle SVG animations (check values/to/from/by and attributeName)
   - Handle meta http-equiv=refresh (remove http-equiv and content if dangerous)
4. **Sanitize `<style>` element text content** using same CSS sanitization
5. **Remove comments** containing `<script`

### URL Checking Logic

For each URL-bearing attribute:
1. Check raw value against dangerous protocol regex
2. Decode entities and percent-encoding, check again
3. Remove all whitespace, check again
4. If dangerous, replace with `about:blank`

**Dangerous protocol regex** (handles whitespace between characters):
```python
r'^[\s\x00]*(?:'
r'j[\s\x00]*a[\s\x00]*v[\s\x00]*a[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
r'|v[\s\x00]*b[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
r'|l[\s\x00]*i[\s\x00]*v[\s\x00]*e[\s\x00]*s[\s\x00]*c[\s\x00]*r[\s\x00]*i[\s\x00]*p[\s\x00]*t'
r'|m[\s\x00]*h[\s\x00]*t[\s\x00]*m[\s\x00]*l'
r')[\s\x00]*:'
```

### CSS Sanitization

For `style` attributes and `<style>` text:
1. Remove `expression(...)` with nested parentheses: `expression\s*\([^()]*(?:\([^()]*\)[^()]*)*\)`
2. Remove `@import` with dangerous URLs: match entire statement up to semicolon
3. Remove `url(javascript:...)` patterns
4. Remove `-moz-binding: ...` declarations
5. Remove `behavior: ...` declarations
6. Preserve safe CSS

## Common Pitfalls

1. **Over-sanitization**: Removing entire tags when only attributes are dangerous (e.g., removing `<form>` instead of sanitizing `action`)
2. **Under-sanitization**: Missing SVG/MathML vectors (animations, foreignObject, script inside SVG)
3. **Encoding blind spots**: Only checking raw values without decoding
4. **CSS in `<style>` elements**: Handling `style` attributes but forgetting `<style>` tag text content
5. **Combination attacks**: Not considering `<base>` or meta refresh
6. **Nested parentheses**: Regex failing on `expression(alert(1))` by stopping at first `)`
7. **BeautifulSoup entity decoding**: Writing regex for entity-encoded input when BS4 already decoded it

## Dependencies

- Python 3.x
- BeautifulSoup4 (`beautifulsoup4`)
- Standard library: `re`, `html`, `urllib.parse`, `sys`
