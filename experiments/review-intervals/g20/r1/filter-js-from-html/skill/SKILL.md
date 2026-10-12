---
name: filter-js-from-html
description: Remove executable JavaScript behavior from HTML files while preserving legitimate document structure, visible content, vector graphics (SVG), equations (MathML), forms, links, and non-dangerous attributes.
---

# Filter JavaScript from HTML

## Task Family Definition

This skill addresses the family of HTML sanitization tasks that remove executable JavaScript behavior while preserving safe content. The family is defined by four variation dimensions:

### 1. Executable HTML Vectors (freeform)
Which HTML constructs can cause script execution and must be neutralized:
- Direct `<script>` tags (with various `type` attributes)
- Inline event handlers (`on*` attributes)
- `javascript:`, `vbscript:`, `livescript:` URLs (including percent-encoded and entity-encoded variants)
- `data:` URLs embedding executable content (HTML, SVG, XHTML)
- Active container tags: `<iframe>`, `<object>`, `<embed>`, `<applet>`
- `<foreignObject>` in SVG (must be removed entirely, not just cleaned)
- Scriptable SVG/MathML elements and SMIL animations
- Form-related executable targets (`action`, `formaction`)
- `<meta http-equiv="refresh">` with dangerous URLs
- `<base>` tags that redirect relative URLs
- `<link>` tags with dangerous hrefs
- `<style>` tags with dangerous CSS (expressions, behaviors, bindings)
- SVG `<handler>` elements

### 2. Preservation Fidelity (freeform)
How much benign HTML structure must remain unchanged:
- Common document structure, tables, forms, semantic HTML
- Entities, images, formatting
- Dense attribute sets on elements
- Mixed safe and unsafe attributes on the same element
- Nested content where only a small fragment is unsafe
- Cases where over-sanitizing would break layout, navigation, or form behavior

### 3. HTML Parsing Irregularity (freeform)
How regular or adversarial the input HTML syntax is:
- Malformed tags, unusual spacing, case variation
- Entity-encoded content (HTML entities in attributes)
- Tab characters, embedded templates
- Fragments wrapped into full documents
- Broken nesting, partially encoded payloads
- Duplicated or conflicting attributes
- Browser-tolerated invalid markup
- Payloads requiring normalization before their danger is clear

### 4. Payload Obfuscation (freeform)
How directly the dangerous behavior is expressed:
- Plain script tags, mixed-case tags
- HTML entities (`&#106;avascript:`)
- Percent-encoding (`%6A%61%76%61%73%63%72%69%70%74%3A`)
- Null-byte-like strings
- Base64-encoded HTML inside URL-bearing attributes
- Layered encodings (entity + percent + whitespace)
- Fragmented payloads split across attributes or nodes
- Executable content hidden in long attribute values or CSS-like constructs
- Payloads requiring decoding or normalization

## Core Implementation Strategy

### Parser Selection
Use BeautifulSoup with `html.parser` backend. This parser:
- Handles malformed HTML gracefully
- Decodes HTML entities in attribute values automatically
- Lowercases all tag and attribute names (requires post-processing for SVG/MathML)
- Preserves document structure and DOCTYPE

### Multi-Phase Filtering Approach

**Phase 1: Remove dangerous container tags**
Remove `<iframe>`, `<object>`, `<embed>`, `<applet>` entirely. These can load external executable content.

**Phase 2: Remove executable `<script>` tags**
Check the `type` attribute. Remove scripts with types: `''`, `'text/javascript'`, `'application/javascript'`, `'text/ecmascript'`, `'application/ecmascript'`, `'text/jscript'`, `'module'`. Preserve non-executable types like `'application/ld+json'`.

**Phase 3: Remove dangerous `<base>` tags**
`<base>` can redirect all relative URLs to a malicious origin.

**Phase 4: Remove dangerous `<meta http-equiv="refresh">`**
Extract the URL from the `content` attribute and check if it's dangerous. Handle spaces around `=` in the URL extraction regex.

**Phase 5: Process all tags for dangerous attributes**
For each tag, check:
- `on*` event handler attributes → remove
- URL-bearing attributes (`href`, `src`, `action`, `formaction`, `xlink:href`, `dynsrc`, `lowsrc`, `data`, `poster`, `background`) → check for dangerous protocols
- `style` attribute → check for dangerous CSS patterns
- `srcdoc` attribute → remove (can contain HTML with scripts)

**Phase 6: Handle SVG-specific vectors**
- **`<foreignObject>` must be removed entirely** (not just cleaned). It can contain arbitrary HTML including `<body onload=...>`, scripts, and other dangerous elements. Even after removing event handlers from children, the foreignObject itself remains a dangerous container.
- SMIL animation elements (`<set>`, `<animate>`, `<animateColor>`, `<animateMotion>`, `<animateTransform>`) → check if `attributeName` targets event handlers or URL-bearing attributes with dangerous values
- **SMIL `values` attribute**: When checking SMIL animations targeting URL attributes, the `values` attribute can contain multiple semicolon-separated values. Split by `;` and check each value individually. A dangerous URL in any position must trigger removal.
- `<handler>` elements → remove

**Phase 7: Handle `<style>` tags with dangerous content**
Check for dangerous CSS patterns: `expression()`, `-moz-binding:`, `behavior:`, `url(javascript:)`, `@import javascript:`

**Phase 8: Restore SVG and MathML attribute case**
BS4's `html.parser` lowercases all attributes. Restore camelCase for SVG attributes (`viewBox`, `attributeName`, `preserveAspectRatio`, etc.) and MathML attributes (`definitionURL`).

### URL Checking Logic

**Clean URLs before checking (iteratively until stable):**
1. Strip whitespace, control characters, null bytes
2. Decode HTML entities (BS4 does this, but apply again for double-encoding)
3. Decode percent-encoding (`%XX` sequences)
4. Repeat until no more changes occur
5. Final strip of whitespace/control characters

**Check for dangerous protocols:**
- `javascript:`, `vbscript:`, `livescript:` (case-insensitive)
- `data:text/html` (always dangerous, including base64 variants)
- `data:image/svg+xml`, `data:application/xhtml+xml` (dangerous in navigation-capable attributes like `href`, `action`, `formaction`)

**Important:** `data:image/svg+xml` in `<img src>` is safe because SVG in `<img>` is sandboxed (scripts don't execute). Only check for SVG data URLs in navigation-capable attributes.

### CSS Checking Logic

Check for dangerous patterns in CSS (in `style` attributes and `<style>` tags):
- `expression()` (IE CSS expressions)
- `-moz-binding:` (Firefox XBL bindings)
- `behavior:` (IE HTC behaviors)
- `url(javascript:)` or `url(vbscript:)` in CSS
- `@import javascript:` or `@import data:text/html`

Remove CSS comments before checking to prevent bypass via `/* */`.

### SVG Animation Checking

For SMIL animation elements, check if `attributeName` targets:
1. Event handler attributes (starts with `on`) → remove animation
2. URL-bearing attributes (`href`, `xlink:href`, `src`, `action`, `formaction`, `data`, `dynsrc`, `lowsrc`, `background`, `poster`):
   - Check `to` attribute for dangerous URL
   - **Split `values` attribute by `;` and check each value individually** for dangerous URLs
   - Remove animation if any value is dangerous
3. `style` attribute → check if `to` or `values` contains dangerous CSS → remove if dangerous

## Critical Implementation Details

### BeautifulSoup Serialization Quirks

When calling `str(soup)` to serialize:
- Self-closing tags become open/close: `<circle r="50"/>` → `<circle r="50"></circle>`
- Attribute order is alphabetical (BS4 sorts attributes)
- Entity normalization: `&` in text becomes `&amp;`, `<` in attributes becomes `&lt;`
- Void elements: `<br>`, `<img>`, `<input>`, `<meta>`, `<link>` serialize as `<br/>` (self-closing)
- DOCTYPE preserved but may get extra newline

These changes are functionally equivalent and browsers handle them correctly.

### SVG Attribute Case Restoration

BS4 lowercases all attributes. For SVG, restore camelCase using a mapping:
```python
SVG_CAMEL_ATTRS = {
    'viewbox': 'viewBox',
    'attributename': 'attributeName',
    'preserveaspectratio': 'preserveAspectRatio',
    # ... (full list in implementation)
}
```

Apply this mapping to the SVG tag itself AND all descendant tags.

### MathML Attribute Case Restoration

Similarly restore `definitionurl` → `definitionURL` for MathML elements.

### In-Place File Modification

The script takes a file path as `argv[1]`, reads the file, filters it, and writes back to the same file. Use `errors='replace'` when reading to handle encoding issues.

## Testing Strategy

Test these categories:
1. **Basic removal**: script tags, event handlers, javascript: URLs
2. **SVG/MathML**: scripts in SVG, event handlers on SVG elements, animation targeting dangerous attributes, foreignObject removal
3. **Preservation**: safe styles, safe URLs, forms, tables, semantic HTML
4. **Obfuscation**: mixed case, entity encoding, percent-encoding, whitespace in URLs, null bytes
5. **Edge cases**: data:image/svg+xml in href vs src, non-executable script types, malformed HTML, SMIL animations with multiple values
6. **Attribute case**: viewBox, attributeName, definitionURL restoration

## Common Pitfalls

1. **foreignObject must be removed entirely**: Don't just clean its children. `<foreignObject>` can contain arbitrary HTML with event handlers on any element. Even after removing visible handlers, the container itself is dangerous.
2. **Forgetting to check the SVG tag itself**: When restoring attribute case, process the SVG tag's own attributes, not just descendants.
3. **Over-sanitizing data:image/svg+xml**: Only check for dangerous SVG data URLs in navigation-capable attributes (`href`, `action`, `formaction`), not in `src` attributes where SVG is sandboxed.
4. **Missing xlink:href**: This attribute is in the `xlink:` namespace but BS4 treats it as a regular attribute. Include it in URL checks.
5. **Not handling SMIL animations**: `<set>` and `<animate>` can dynamically set dangerous attributes at runtime.
6. **SMIL values attribute**: The `values` attribute can contain multiple semicolon-separated values. Use `re.search` (not `re.match`) or split by `;` and check each value. A dangerous URL anywhere in the list must trigger removal.
7. **CSS comment bypass**: Attackers can hide dangerous patterns in CSS comments. Strip comments before checking.
8. **Entity double-encoding**: Apply entity decoding iteratively until no more changes occur.
9. **Percent-encoding bypass**: `javascript:` can be encoded as `%6A%61%76%61%73%63%72%69%70%74%3A`. Must decode percent-encoding in URL checking.
10. **Meta refresh URL extraction**: The content attribute can have spaces around `=` like `0; URL = javascript:...`. Handle this in the regex.
