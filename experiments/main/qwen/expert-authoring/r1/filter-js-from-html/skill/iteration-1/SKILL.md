---
name: filter-js-from-html
description: >
  Sanitize HTML files by removing all executable JavaScript behavior while
  preserving legitimate document structure, visible content, vector graphics,
  equations, forms, links, and non-dangerous attributes. Covers script tags,
  inline event handlers, dangerous URL protocols, data URLs, SVG/MathML
  execution vectors, CSS-based attacks, and encoding-based evasion techniques.
---

# HTML JavaScript Sanitizer

## Task Overview

Create a Python script (`/app/filter.py`) that takes an HTML file path as
`argv[1]`, removes all executable JavaScript behavior, and writes the
sanitized result back to the same file (in-place modification).

The sanitizer must be **comprehensive** (block all known JS execution vectors)
and **conservative** (preserve all safe content and functionality).

## Environment

- Python 3.13+ with `beautifulsoup4` (html.parser backend) and `soupsieve`
- No lxml or html5lib available — use `html.parser` as the BS4 parser
- pytest for testing; selenium/chromium may be used for browser-based verification

## Implementation Strategy

### 1. Parser Choice and Behavior

Use **BeautifulSoup with `html.parser`** — the only parser available without
additional installs. Key behaviors to account for:

| Behavior | Implication |
|---|---|
| Lowercases tag names | `<ScRiPt>` → `<script>` — good for matching |
| Lowercases attribute names | `ONCLICK` → `onclick` — good for matching |
| Decodes HTML entities in attrs | `&#106;avascript:` → `javascript:` — good |
| Does NOT parse tags inside `<style>` | `<script>` in `<style>` is text — must handle separately |
| Does NOT add wrapper tags to fragments | Fragments stay as fragments — good |
| Tolerant of broken nesting | Auto-corrects — may change structure slightly |
| Does NOT strip null bytes | `<scr\x00ipt>` becomes text — must preprocess |

### 2. Preprocessing (Before Parsing)

Strip null bytes and control characters (0x00–0x08, 0x0B, 0x0C, 0x0E–0x1F,
0x7F) from the raw HTML. Browsers ignore these characters but html.parser
may treat them as significant, causing tags like `<scr\x00ipt>` to be
misinterpreted as text rather than parsed as a `<script>` tag.

### 3. Sanitization Phases

Apply sanitization in this order to avoid ordering-dependent bypasses:

#### Phase 1: Remove Inherently Dangerous Tags (decompose entire subtree)

- `script` — direct JS execution
- `iframe` — loads external content, `srcdoc` attribute
- `object` — plugin execution
- `embed` — plugin execution
- `applet` — Java execution
- `frame`, `frameset` — frame-based attacks

#### Phase 2: SVG-Specific Dangers

- **`foreignObject`** — can embed arbitrary HTML (including scripts) inside SVG
- **SVG animation elements** (`animate`, `set`, `animateTransform`,
  `animateMotion`, `animateColor`) — dangerous when `attributeName` targets:
  - Event handler attributes (`onmouseover`, `onclick`, etc.)
  - URL-bearing attributes (`href`, `xlink:href`) with javascript: values
  - `style` attribute with dangerous CSS values
- Safe SVG animations (e.g., `attributeName="x"`, `attributeName="fill"`)
  should be **preserved**

#### Phase 3: Meta Refresh

Remove `<meta http-equiv="refresh">` when the `content` attribute contains
a `javascript:` URL (check the portion after `;url=`).

#### Phase 4: Base Tag

Remove `<base>` elements whose `href` uses a dangerous protocol. Keep safe
base tags with regular http/https URLs.

#### Phase 5: Link Tags

Remove `<link>` elements whose `href` uses a dangerous protocol. Keep safe
stylesheet links, icon links, etc.

#### Phase 6: Style Tag Content

Clean `<style>` block text content:
1. Remove embedded HTML tags and their content (e.g., `<script>` inside `<style>`
   in SVG context — BS4 treats this as text, not as a parsed tag)
2. Remove dangerous CSS: `expression()`, `javascript:` URLs, `vbscript:` URLs,
   `-moz-binding`, `behavior`, dangerous `url()` values
3. Remove `@import` with dangerous URLs

#### Phase 7: Attribute Sanitization (all remaining elements)

Walk every element and:

1. **Remove event handler attributes** — any attribute matching `^on[a-z]`
   (case-insensitive). Covers `onclick`, `onload`, `onerror`, `onmouseover`,
   `onfocus`, etc.

2. **Sanitize URL-bearing attributes** — check these attributes for dangerous
   protocols: `href`, `src`, `action`, `formaction`, `data`, `poster`,
   `background`, `dynsrc`, `lowsrc`, `srcdoc`, `xlink:href`, `ping`, `cite`,
   `usemap`, `longdesc`.

3. **Sanitize `style` attributes** — check for dangerous CSS patterns
   (same patterns as Phase 6).

#### Phase 8: Dangerous Comments

Remove IE conditional comments (`<!--[if ...]>`, `<![endif]-->`) which can
execute code in older IE versions. Preserve regular HTML comments.

### 4. URL Protocol Checking

This is the most critical security function. Before checking any URL attribute
value, **normalize** it:

1. Decode HTML entities: `html.unescape(value)`
2. Strip null bytes and control characters
3. Collapse all whitespace (tabs, newlines, spaces) to nothing
4. Check against dangerous protocols (case-insensitive)

**Dangerous protocols:**
- `javascript:` — direct JS execution
- `vbscript:` — VBScript execution (IE)
- `livescript:` — LiveScript execution (legacy)

**Data URL handling:**
- **Block** `data:image/svg+xml` — SVG can contain scripts
- **Block** `data:text/html` and other executable MIME types
- **Block** all `data:` URLs not explicitly safe-listed
- **Allow** `data:image/{png,jpeg,jpg,gif,webp,bmp,x-icon};base64,...`

### 5. Encoding Evasion Techniques

The sanitizer must defeat these common evasion methods:

| Technique | Example | Defense |
|---|---|---|
| Case variation | `<ScRiPt>` | BS4 lowercases; regex `re.IGNORECASE` |
| HTML entities (decimal) | `&#106;avascript:` | `html.unescape()` before checking |
| HTML entities (hex) | `&#x6a;avascript:` | `html.unescape()` handles both |
| Double encoding | `&amp;#106;avascript:` | `html.unescape()` twice if needed |
| Null bytes | `<scr\x00ipt>` | Strip before parsing |
| Whitespace injection | `java\tscript:` | Collapse whitespace before check |
| Newline injection | `java\nscript:` | Collapse whitespace before check |
| Mixed case protocol | `JaVaScRiPt:` | Case-insensitive regex |

### 6. Preservation Rules

**Must be preserved unchanged:**
- Document structure: `<html>`, `<head>`, `<body>`, `<!DOCTYPE>`
- Semantic HTML: `<article>`, `<section>`, `<header>`, `<footer>`, `<nav>`, etc.
- Tables: `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>`
- Forms: `<form>` with safe `action`, `<input>`, `<select>`, `<textarea>`, `<button>`
- Links: `<a>` with safe `href` (http, https, mailto, fragment, relative)
- Images: `<img>` with safe `src` (http, https, safe data: URLs)
- SVG graphics: `<svg>`, `<circle>`, `<rect>`, `<path>`, `<line>`, `<text>`,
  `<defs>`, `<linearGradient>`, `<radialGradient>`, `<clipPath>`, etc.
- MathML: `<math>`, `<mrow>`, `<mi>`, `<mo>`, `<mn>`, `<mtext>`, `<mfrac>`, etc.
- Safe attributes: `class`, `id`, `name`, `type`, `value`, `placeholder`, `title`,
  `alt`, `width`, `height`, `viewBox`, `xmlns`, `fill`, `stroke`, `d`, etc.
- Text content, entity references (`&amp;`, `&lt;`, `&gt;`), and formatting
- Safe comments (non-conditional)
- `<style>` blocks with safe CSS
- `<meta charset>`, safe `<meta>` tags
- `<base href="https://...">` with safe URLs
- `<link rel="stylesheet" href="safe.css">` with safe URLs

**Must be removed or neutralized:**
- Only the dangerous parts (tags, attributes, or attribute values)
- Never remove more than necessary

### 7. Output Format

- BS4's `str(soup)` produces the sanitized HTML
- Fragments remain fragments (html.parser does not add wrapper tags)
- Full documents preserve `<!DOCTYPE>`, `<html>`, `<head>`, `<body>`
- Self-closing tags may be expanded (`<circle/>` → `<circle></circle>`)
  — this is functionally equivalent and acceptable

## Verification Checklist

After implementation, verify each of these scenarios:

- [ ] `<script>alert(1)</script>` removed (including mixed case, with attrs)
- [ ] `onclick`, `onerror`, `onload`, etc. removed from all elements
- [ ] `javascript:` URLs blocked in `href`, `src`, `action`, `formaction`, etc.
- [ ] Entity-encoded `&#106;avascript:` URLs decoded and blocked
- [ ] Whitespace-obfuscated `java\tscript:` URLs normalized and blocked
- [ ] `data:text/html,...` URLs blocked; `data:image/png;base64,...` preserved
- [ ] `<iframe>`, `<object>`, `<embed>`, `<applet>` fully removed
- [ ] SVG `<foreignObject>` removed
- [ ] SVG `<animate attributeName="onmouseover">` removed; safe animations kept
- [ ] `<meta http-equiv="refresh" content="...;url=javascript:...">` removed
- [ ] `<base href="javascript:...">` removed
- [ ] `<style>` with `expression()`, `url(javascript:...)`, `-moz-binding` cleaned
- [ ] `<style>` containing `<script>` tags has them stripped
- [ ] Null-byte-obfuscated tags handled after preprocessing
- [ ] Safe HTML structure, forms, links, images, SVG, MathML preserved
- [ ] Template tags containing scripts sanitized
- [ ] IE conditional comments removed; safe comments preserved
- [ ] File modified in-place via argv[1]

## Common Pitfalls

1. **Forgetting to preprocess null bytes** — html.parser won't parse
   `<scr\x00ipt>` as a script tag, leaving the payload as visible text.

2. **Not checking `xlink:href`** — SVG `<use>` and `<a>` elements use
   `xlink:href` which can carry `javascript:` URLs.

3. **Missing `formaction`** — `<button>` and `<input>` can override form
   action with `formaction="javascript:..."`.

4. **Ignoring `<style>` tag text content** — In SVG, `<style>` can contain
   `<script>` that BS4 treats as text (raw text element), but browsers in
   SVG/XML mode may parse it as an actual element.

5. **Over-sanitizing SVG animations** — Only remove animation elements whose
   `attributeName` targets dangerous attributes. Animations targeting `x`, `y`,
   `fill`, `opacity`, etc. are safe and should be preserved.

6. **Not normalizing before protocol check** — Whitespace, tabs, newlines,
   and null bytes in protocol names bypass simple string matching.

7. **Blocking all `data:` URLs** — Base64-encoded raster images
   (`data:image/png;base64,...`) are safe and commonly used.

8. **Not handling BS4 attribute value types** — BS4 may return attribute
   values as lists (for multi-valued attrs like `class`). Always check
   `isinstance(value, list)` and join before checking.
