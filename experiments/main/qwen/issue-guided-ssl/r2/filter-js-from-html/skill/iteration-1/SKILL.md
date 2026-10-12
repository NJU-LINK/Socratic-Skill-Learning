---
name: filter-js-from-html
description: >
  Whitelist-based HTML sanitization that removes executable JavaScript behavior
  while preserving safe document structure, SVG graphics, MathML equations,
  forms, links, and non-dangerous attributes. Handles SVG/MathML namespaces,
  event handlers, javascript: URLs, data: URLs, CSS-based attacks, obfuscated
  payloads, and malformed HTML.
---

# Filter JavaScript from HTML

## Purpose

Remove executable JavaScript behavior from HTML files while preserving legitimate
document structure, visible content, vector graphics, equations, forms, links,
and non-dangerous attributes. The output must be functionally identical to the
input except for the removal of dangerous executable behavior.

## Architecture

Whitelist-based sanitizer using a three-phase approach:

1. **Parse** — Use lxml-backed BeautifulSoup for browser-like HTML parsing with
   proper SVG/MathML namespace handling. Fall back to html.parser if lxml is
   unavailable.

2. **Sanitize** — Walk the DOM tree and apply these rules:
   - **Remove dangerous elements entirely** (with all children): `script`,
     `iframe`, `frame`, `frameset`, `object`, `embed`, `applet`, `base`,
     `isindex`
   - **Remove dangerous meta refresh** tags that redirect to `javascript:` URLs
   - **Clean `<style>` tag contents** — strip `expression()`, `-moz-binding`,
     `behavior`, `url(javascript:)` constructs
   - **Walk all remaining elements** and for each:
     - Remove ALL `on*` event handler attributes (prefix match)
     - Remove attributes not in the safe whitelist
     - Validate URL-bearing attributes against dangerous schemes
     - Clean `style=""` attribute values
   - **Validate SVG/MathML animation elements** — remove `<animate>`, `<set>`
     etc. that target event handler attributes or contain `javascript:` URLs
   - **Remove IE conditional comments**

3. **Serialize** — Write sanitized HTML back to the file in-place.

## Dangerous Vector Catalog

### Elements that must be removed entirely
- `<script>` (any case, any namespace — including inside SVG/MathML)
- `<iframe>`, `<frame>`, `<frameset>`
- `<object>`, `<embed>`, `<applet>`
- `<base>` (can change base URL for all relative links)
- `<isindex>`
- `<meta http-equiv="refresh">` with `javascript:` URL in content
- `<foreignObject>` — switches parser to HTML mode inside SVG, creating namespace confusion and parser differentials. Remove entirely with all children, even if content appears safe.
- `<style>` inside `<svg>` or `<math>` — CSS `@import` can execute JavaScript in Firefox. Regex-based CSS cleaning is fragile (backslash escapes, comment splitting, entity encoding). Remove SVG/MathML `<style>` entirely; HTML-level `<style>` is kept only if it passes strict validation (no `@import`, `expression()`, `-moz-binding`, `behavior`, `url()`, `javascript:`, `vbscript:`, `data:text/html`).

### Attributes that must be removed
- ALL `on*` event handlers: `onclick`, `onload`, `onerror`, `onmouseover`,
  `onfocus`, `onblur`, etc. (100+ variants — match by `on` prefix)
- Any attribute not in the safe whitelist
- URL attributes (`href`, `src`, `action`, `formaction`, `data`, `poster`,
  `xlink:href`, etc.) containing dangerous schemes
- `<use href>` or `<use xlink:href>` containing non-fragment URLs — only allow `#local-id` references to prevent loading external SVG with embedded scripts. Block `javascript:`, `vbscript:`, `data:`, and external URLs.

### Dangerous URL schemes
- `javascript:` — direct script execution
- `vbscript:` — IE VBScript execution
- `livescript:`, `mocha:` — legacy script schemes
- `data:text/html,...` — HTML embedded in data URLs
- `data:...<script>...` — script content in data URLs

### SVG-specific vectors
- `<script>` inside `<svg>` — browsers execute this
- `on*` handlers on ANY SVG element (`<svg onload=...>`, `<path onclick=...>`)
- `<style>` inside `<svg>` — CSS `@import url("evil.js")` executes in Firefox
- `<foreignObject>` — switches to HTML parser mode, namespace confusion attacks
- `<animate attributeName="onmouseover" to="alert(1)">` — animation XSS
- `<set attributeName="onmouseover" to="alert(1)">` — dynamic attribute injection
- `<use href="javascript:...">` or `<use href="data:...">` — load malicious SVG
- `<use href="https://evil.com/payload.svg">` — external SVG with embedded scripts

### MathML-specific vectors
- `<script>` inside `<math>` — browsers execute this
- `on*` handlers on MathML elements
- Nested namespace confusion: `<math><mtext><table><mglyph><svg>...`

### CSS-based vectors (in style attributes and `<style>` tags)
- `expression(...)` — IE CSS expression
- `url(javascript:...)` — JavaScript in CSS url()
- `url(data:...)` — data URLs in CSS
- `-moz-binding:` — Firefox XBL binding
- `behavior:` — IE behavior
- `@import url(...)` — CSS import can load external JavaScript (Firefox)
- CSS backslash escapes: `@\i\m\p\o\r\t` bypasses simple regex
- CSS comment splitting: `@im/**/port` bypasses keyword matching
- HTML entities in CSS text decoded by HTML parser before CSS parser sees them

### Form & navigation vectors
- `<form action="javascript:...">`
- `<input type="image" src="javascript:...">`
- `<button formaction="javascript:...">`
- `<meta http-equiv="refresh" content="0;url=javascript:...">`

## Key Implementation Details

### URL validation
- Strip whitespace, tabs, newlines, and control characters before checking
- Decode HTML entities (multiple rounds for double-encoding)
- Case-insensitive scheme matching
- Allow only: `http`, `https`, `mailto`, `tel`, `sms`, and scheme-relative URLs
- Block: `javascript:`, `vbscript:`, `livescript:`, `mocha:`, `data:text/html`
- For `<use>` elements: only allow fragment-only URLs (`#id`), block all others

### CSS sanitization
- For `<style>` inside SVG/MathML: remove entirely (regex cleaning is fragile)
- For HTML `<style>`: remove entirely if contains `@import`, `expression`, `-moz-binding`, `behavior`, `url()`, `javascript:`, `vbscript:`, `data:text/html`
- For `style=""` attributes: validate each property, remove properties with dangerous constructs
- CSS regex is inherently fragile — prefer removal over surgical cleaning

### Case insensitivity
- All tag names and attribute names must be lowercased before checking
- `<SCRIPT>`, `<Script>`, `<sCrIpT>` are all dangerous
- `<ONCLICK>`, `<OnClick>` are all event handlers

### Null byte handling
- Strip null bytes from raw input before parsing
- Browsers may ignore null bytes in tag names/attributes

### Parser choice
- **lxml** is strongly preferred: handles SVG/MathML namespaces correctly,
  browser-like parsing of malformed HTML
- Fall back to `html.parser` if lxml unavailable (with caveats about namespace
  handling)
- If lxml is not pre-installed, the script should attempt `pip install lxml` or work with html.parser fallback

### Preservation rules
- Keep safe HTML structure: headings, paragraphs, lists, tables, forms
- Keep safe SVG: shapes, paths, gradients, text, filters
- Keep safe MathML: equations, symbols, layout
- Keep safe attributes: class, id, style (cleaned), href (validated), etc.
- Keep data-* and aria-* attributes
- Keep text content unchanged
- Keep safe comments (remove IE conditional comments)

## Interface

```
python filter.py <html_file>
```

- Takes HTML file path as `argv[1]`
- Modifies the file in-place
- No stdout output on success
- Exit code 0 on success, 1 on error

## Dependencies

- Python 3.x
- beautifulsoup4
- lxml (preferred) or html.parser fallback

## Variation Dimensions (from spec)

This skill must handle variation across:

1. **Executable HTML vectors** — script tags, inline handlers, javascript: URLs,
   data URLs, iframe/object/embed, SVG/MathML script elements, form-related
   targets, refresh/navigation paths, dangerous attributes, combinations

2. **Preservation fidelity** — common document structure, tables, forms,
   semantic HTML, entities, images, formatting, dense attributes, mixed
   safe/unsafe on same element, nested content with small unsafe fragments

3. **HTML parsing irregularity** — malformed tags, unusual spacing, case
   variation, entity-encoded content, tabs, embedded templates, fragments
   wrapped into full documents, broken nesting, duplicated attributes,
   browser-tolerated invalid markup

4. **Payload obfuscation** — plain script tags, mixed case, HTML entities,
   null-byte strings, base64 in URLs, percent-encoding, layered encodings,
   fragmented payloads, executable content in long attributes or CSS,
   payloads requiring decoding/normalization
