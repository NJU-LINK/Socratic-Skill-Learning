---
name: filter-js-from-html
description: Remove executable JavaScript behavior from HTML files while preserving legitimate document structure, visible content, and safe markup. Handles SVG, MathML, forms, links, and various obfuscation techniques.
---

# Filter JavaScript from HTML

## Purpose

Surgically remove executable JavaScript behavior from HTML files while preserving all safe content. This is not a whitelist/blacklist sanitizer — it's a targeted neutralization of dangerous constructs.

## Core Principles

1. **Surgical neutralization, not wholesale removal**: Only remove tags that have no legitimate non-executable purpose. For all other tags, strip dangerous attributes while preserving the element and its safe content.

2. **Preservation fidelity**: Forms, links, meta tags, tables, images, SVG graphics, MathML equations, comments, and all visible content must survive filtering with no functionally meaningful differences.

3. **Namespace-aware handling**: SVG and MathML elements can execute scripts through multiple vectors. Handle namespace-prefixed tags and SVG/MathML-specific dangerous elements.

4. **Obfuscation resistance**: Detect and neutralize JavaScript URLs regardless of encoding (percent, HTML entities, mixed case, whitespace insertion, layered encodings).

## Dangerous Constructs to Remove

### Inherently Dangerous Tags (Remove Entirely)
- `<script>` — Direct JavaScript execution
- `<iframe>` — Can load external executable content
- `<object>`, `<embed>`, `<applet>` — Plugin-based execution

### SVG-Specific Dangerous Elements
- `<script>` — JavaScript in SVG context
- `<set>` — Can set arbitrary attributes to dangerous values (remove entirely)
- `<foreignObject>` — Can embed arbitrary HTML including scripts (remove entirely)
- `<animate>`, `<animateTransform>`, `<animateMotion>` — NOT inherently dangerous; audit their attributes like any other element
- Any SVG element with `on*` event handler attributes

### MathML-Specific Dangerous Elements
- `<script>` — JavaScript in MathML context

### Dangerous Attributes (Strip from Elements)
- **Event handlers**: Any attribute starting with `on` (onclick, onload, onerror, onmouseover, etc.)
  - **Defense-in-depth**: HTML entities in attribute names are decoded before checking (e.g., `&#111;nerror` → `onerror`, `on&#x63;lick` → `onclick`)
  - This handles partially encoded payloads and XHTML/XML contexts where entity decoding occurs
- **URL-bearing attributes** with dangerous protocols:
  - `href`, `src`, `action`, `formaction`, `data`, `poster`
  - `dynsrc`, `lowsrc`, `background`, `codebase`, `classid`
  - `usemap`, `longdesc`, `profile`, `xmlns`
  - SVG-specific: `xlink:href`, `href` (in SVG context)
  - SVG animation: `to`, `from`, `by`, `values` (can contain javascript: URLs)

### Dangerous URL Protocols
- `javascript:` — Direct script execution
- `vbscript:` — VBScript execution (IE)
- `data:text/html` — HTML content that can execute scripts
- `data:application/xhtml+xml` — XHTML content
- `data:image/svg+xml` — SVG content that can contain scripts

### Dangerous CSS Patterns
- `expression(...)` — IE CSS expression (executes JavaScript)
- `-moz-binding: url(...)` — Firefox XBL binding
- `behavior: url(...)` — IE behavior
- `url(javascript:...)` — JavaScript in CSS url()
- `url(data:text/html...)` — HTML in CSS url()

## Implementation Strategy

### 1. Parse with BeautifulSoup
Use `html.parser` for robust handling of malformed HTML. Parse the entire document into a tree structure.

### 2. Recursive Tree Walk
Walk every element in the parsed tree. For each element:
- **Check if inherently dangerous** → Remove the entire element
- **Otherwise, audit every attribute**:
  - Remove event handlers (`on*` attributes)
  - Check URL-bearing attributes for dangerous protocols
  - Sanitize `style` attributes for dangerous CSS
- **Recurse into children**

### 3. URL Decoding and Normalization
Before checking if a URL is dangerous:
- Decode percent-encoding (multiple passes for layered encoding)
- Decode HTML entities (decimal `&#106;`, hex `&#x6A;`, named `&tab;`)
- Remove whitespace, tabs, newlines, control characters
- Convert to lowercase for case-insensitive matching
- Check against dangerous protocol patterns

### 4. CSS Sanitization
For `<style>` tags and `style` attributes:
- Parse CSS into individual rules (for `<style>`) or properties (for `style` attributes)
- Check each rule/property for dangerous patterns
- Remove only dangerous rules/properties, preserve safe ones
- If all rules/properties are dangerous, remove the entire tag/attribute

### 5. Special Cases

#### Meta Refresh
Format: `<meta http-equiv="refresh" content="5;url=javascript:alert(1)">`
- Extract URL portion after `;url=` (case-insensitive)
- Check if extracted URL is dangerous
- If dangerous: remove entire `<meta>` tag
- If safe: leave tag completely untouched (preserve both `http-equiv` and `content`)

#### Namespace-Prefixed Tags
Handle tags like `<svg:script>`, `<math:script>`:
- Strip namespace prefix before checking against dangerous tag lists
- `svg:script` → `script` → remove
- `svg:circle` → `circle` → keep

## Preservation Guidelines

### What to Preserve
- All safe HTML structure (div, p, span, h1-h6, etc.)
- Forms with safe `action` attributes
- Links with safe URLs (http, https, relative, anchor)
- Images with safe `src` attributes
- Tables, lists, semantic HTML
- Meta tags (charset, viewport, description, etc.)
- Link tags (stylesheets, icons)
- SVG graphics with safe elements
- MathML equations
- HTML comments
- `<noscript>` content (unless security policy requires removal)
- All text content

### What to Remove
- Only the dangerous parts, not entire safe elements
- Example: `<form action="javascript:alert(1)">` → `<form>` (remove `action` attribute, keep form)
- Example: `<a href="javascript:alert(1)" class="link">` → `<a class="link">` (remove `href`, keep class and content)

## Testing Checklist

### Security Tests
- [ ] Direct `<script>` tags removed
- [ ] Inline event handlers removed
- [ ] `javascript:` URLs removed (all encodings)
- [ ] `data:text/html` URLs removed
- [ ] SVG dangerous elements removed
- [ ] MathML script tags removed
- [ ] `<iframe>`, `<object>`, `<embed>` removed
- [ ] Dangerous CSS in `<style>` tags removed
- [ ] Dangerous CSS in `style` attributes removed
- [ ] Meta refresh with dangerous URLs removed
- [ ] Namespace-prefixed dangerous tags removed

### Obfuscation Tests
- [ ] Tab/newline insertion in `javascript:` URLs
- [ ] Mixed case (`JaVaScRiPt:`)
- [ ] HTML entity encoding (decimal, hex, named)
- [ ] Percent encoding
- [ ] Double/multiple encoding
- [ ] Layered encoding (percent + entities)
- [ ] Null byte insertion (`java&#x0;script:`) — BeautifulSoup converts `&#x0;` to U+FFFD, not `\x00`

### Preservation Tests
- [ ] Forms with safe actions preserved
- [ ] Links with safe URLs preserved
- [ ] Meta tags preserved (charset, viewport)
- [ ] Link tags preserved (stylesheets)
- [ ] Tables, lists, semantic HTML preserved
- [ ] SVG graphics preserved
- [ ] MathML equations preserved
- [ ] Comments preserved
- [ ] All text content preserved
- [ ] Mixed safe/dangerous CSS (safe rules preserved)

## Edge Cases

### Malformed HTML
BeautifulSoup handles broken nesting, unclosed tags, and invalid markup gracefully.

### Mixed Safe and Dangerous Content
- Same element with safe and dangerous attributes: remove only dangerous attributes
- Same CSS with safe and dangerous rules: remove only dangerous rules
- Nested dangerous content: remove dangerous elements, preserve structure

### Browser-Specific Behaviors
- `expression()` — IE only, but still tested
- `-moz-binding` — Firefox only, but still tested
- `behavior` — IE only, but still tested
- These are removed for defense-in-depth even if not universally exploitable

## Performance Considerations

- Multi-pass URL decoding (up to 5 iterations) handles layered encoding
- CSS rule-level parsing is more expensive than all-or-nothing but provides better preservation
- Recursive tree walk is O(n) where n is number of elements
- BeautifulSoup parsing is the main bottleneck for large documents

## Limitations

- CSS parsing is regex-based, not a full CSS parser — may miss edge cases in complex CSS
- Does not handle JavaScript in `<script type="module">` differently (all scripts removed)
- Does not validate URLs beyond protocol checking (e.g., doesn't check for XSS in query parameters)
- Namespace handling depends on BeautifulSoup's parser behavior

## References

- OWASP XSS Prevention Cheat Sheet
- HTML5 specification on script execution
- SVG specification on scriptable content
- CSS specification on expression() and url()
