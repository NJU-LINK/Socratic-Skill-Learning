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

### Remove Entirely (tags whose primary purpose is execution/loading or can embed arbitrary HTML)
- `<script>`, `<iframe>`, `<object>`, `<embed>`, `<applet>`, `<isindex>`
- `<base>` (combination attack: rewrites all relative URLs to attacker domain)
- **`<foreignObject>`** (can embed arbitrary HTML including scripts — too dangerous to preserve even after sanitizing children)
- **`<meta http-equiv="refresh">` with dangerous URLs** (remove entire tag, not just attributes)

### Sanitize at Attribute Level (tags with legitimate uses)
- **Forms** (`<form>`, `<input>`, `<button>`, `<textarea>`, `<select>`): preserve structure, neutralize `action`/`formaction` only when containing dangerous URLs
- **Links/Images** (`<a>`, `<img>`): preserve structure, neutralize `href`/`src` only when containing dangerous URLs
- **SVG/MathML**: preserve graphics and equations, remove event handlers and dangerous attributes
- **`<link>`, `<meta>`**: preserve safe instances, but remove dangerous meta refresh tags entirely (see Combination Attacks)

## Attack Vectors

### 1. Script Containers
- `<script>` tags (anywhere, including inside SVG/MathML)
- Event handlers: `onclick`, `onload`, `onerror`, `onmouseover`, `onfocus`, etc.

### 2. Dangerous URL Protocols
**REMOVE ENTIRELY** (don't replace with about:blank) from URL-bearing attributes:
- `javascript:` — primary execution vector
- `vbscript:` — VBScript (older IE)
- `livescript:` — old Netscape alias
- `mhtml:` — MIME HTML combination attack

**Attributes to check**: `href`, `src`, `action`, `formaction`, `data`, `xlink:href`, `background`, `poster`, `srcset`, `usemap`, `longdesc`, `cite`, `manifest`, `ping`

**CRITICAL**: Tests expect dangerous URL attributes to be removed entirely, not replaced. For example, `<a href="javascript:alert(1)">` should become `<a>`, not `<a href="about:blank">`.

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
- `<base href="http://evil.com/">` — rewrites all relative URLs (remove entire tag)
- `<meta http-equiv="refresh" content="0;url=javascript:...">` — remove the **ENTIRE meta tag**
  - Handle spaces around `=` in content: `"0; URL = javascript:..."` is valid
  - Don't just remove attributes; remove the whole `<meta>` element

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
2. **Remove dangerous tags**: script, iframe, object, embed, applet, isindex, base, foreignobject
3. **Sanitize attributes** on remaining tags:
   - Remove event handlers (on* attributes)
   - Remove dangerous URL attributes entirely (not replace with about:blank)
   - Sanitize style attributes (remove dangerous CSS)
   - Handle SVG animations (check values/to/from/by and attributeName)
   - Handle meta http-equiv=refresh (remove ENTIRE meta tag if URL is dangerous)
4. **Sanitize `<style>` element text content** using same CSS sanitization
5. **Remove comments** containing `<script`

### URL Checking Logic

For each URL-bearing attribute:
1. Check raw value against dangerous protocol regex
2. Decode entities and percent-encoding, check again
3. Remove all whitespace, check again
4. If dangerous, **REMOVE THE ATTRIBUTE ENTIRELY** (don't replace with about:blank)

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

**"Clean or Remove" Philosophy**: After sanitizing CSS, check if the result has empty/garbage property values. If a property value is empty or contains only punctuation (no alphanumeric content), remove the **entire style attribute**. For example:
- `style="background:url(javascript:alert(1))"` → after sanitization becomes `style="background:)"` → this is garbage, so remove the entire attribute
- `style="color: red; font-weight: bold"` → safe, preserve as-is

Implementation: After calling `sanitize_css_text()`, verify that every CSS property declaration has a non-empty value containing at least one alphanumeric character or `#` (for hex colors).

## Common Pitfalls

1. **Over-sanitization**: Removing entire tags when only attributes are dangerous (e.g., removing `<form>` instead of sanitizing `action`)
2. **Under-sanitization**: Missing SVG/MathML vectors (animations, foreignObject, script inside SVG)
3. **Encoding blind spots**: Only checking raw values without decoding
4. **CSS in `<style>` elements**: Handling `style` attributes but forgetting `<style>` tag text content
5. **Combination attacks**: Not considering `<base>` or meta refresh
6. **Nested parentheses**: Regex failing on `expression(alert(1))` by stopping at first `)`
7. **BeautifulSoup entity decoding**: Writing regex for entity-encoded input when BS4 already decoded it
8. **Replacing instead of removing**: Replacing dangerous URLs with `about:blank` instead of removing the attribute entirely. Tests expect `not tag.has_attr('href')`, not `tag['href'] == 'about:blank'`
9. **Partial CSS sanitization**: Leaving garbage like `background:)` after removing `url(javascript:...)`. Use "clean or remove" philosophy.
10. **Regex typos**: Using `[\s_x00]` (literal underscore) instead of `[\s\x00]` (whitespace + null byte). This breaks protocol matching for livescript: and mhtml:
11. **Meta refresh handling**: Only removing `http-equiv` attribute instead of the entire `<meta>` tag when it contains a dangerous refresh URL
12. **foreignObject handling**: Preserving `<foreignObject>` and only sanitizing its children. Since foreignObject can embed arbitrary HTML (including scripts), it should be removed entirely, not sanitized
13. **Skill drift**: When you fix a bug in the working solution, you must update ALL three artifacts: (1) the working solution itself, (2) the SKILL.md documentation, and (3) the scripts/filter.py reference implementation. If these drift out of sync, future iterations will inherit the bug

## Dependencies

- Python 3.x
- BeautifulSoup4 (`beautifulsoup4`)
- Standard library: `re`, `html`, `urllib.parse`, `sys`
