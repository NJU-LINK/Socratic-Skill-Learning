---
name: filter-js-from-html
description: >
  Build a Python script that removes executable JavaScript behavior from HTML
  files (including SVG and MathML content) while preserving legitimate document
  structure, visible content, vector graphics, equations, forms, links, and
  non-dangerous attributes. The script reads an HTML file path from argv[1]
  and modifies it in-place.
---

# Filter JavaScript from HTML

## Task Summary

Create `/app/filter.py` that:
1. Takes an HTML file path as `sys.argv[1]`
2. Reads the file, removes all executable JavaScript vectors
3. Writes the sanitized HTML back to the **same path** (in-place)

The output must be **functionally identical** to the input except that no
JavaScript can execute when the result is rendered by a browser.

## Environment

- **Python 3.13+** with `beautifulsoup4` (html.parser backend only)
- No `lxml`, no `html5lib`, no regex-based HTML libraries
- Chromium and selenium are available (tests may load filtered HTML in a
  real browser to verify JS does not execute and safe content is preserved)

## Architecture: Parse → Sanitize → Serialize

```
raw HTML
  │
  ├─ preprocess  (strip null bytes, normalize control chars)
  │
  ├─ parse       (BeautifulSoup + html.parser)
  │
  ├─ phase 1: remove dangerous elements
  ├─ phase 2: conditional element removal
  ├─ phase 3: attribute-level sanitization
  ├─ phase 4: CSS sanitization (inline + <style>)
  │
  └─ serialize   (str(soup) → write back)
```

## Phase 1 — Remove Dangerous Elements

Remove these elements **entirely** (tag + all descendants) with
`element.decompose()`:

| Element      | Why                                         |
|--------------|---------------------------------------------|
| `script`     | Direct JS execution                         |
| `iframe`     | Embeds external HTML; can run JS            |
| `object`     | Plugin / external resource loading          |
| `embed`      | Plugin / external resource loading          |
| `applet`     | Java applets                                |
| `base`       | Rewrites URL base for all relative links    |
| `frame`      | Legacy frame element                        |
| `frameset`   | Legacy frameset element                     |
| `handler`    | SVG 1.2 inline script container             |
| `listener`   | SVG 1.2 event binding element               |

**Loop until stable** — nested dangerous elements may be revealed as outer
ones are removed.

> `find_all('script')` catches scripts in **every** context: inside `<svg>`,
> `<math>`, `<title>`, `<template>`, `<noscript>`, `<noembed>`, `<iframe>`
> fallback, etc.  html.parser treats them all as real elements.

## Phase 2 — Conditional Element Removal

### `<meta http-equiv="refresh">`
Remove **any** `<meta>` whose `http-equiv` equals `refresh` (case-insensitive).
Meta refresh can redirect to `javascript:` URLs.

### `<link rel="import">`
Remove `<link>` elements whose `rel` attribute contains `import`.
HTML imports load and execute external HTML documents.

### `<foreignObject>` (SVG)
Remove all `<foreignObject>` elements. They embed arbitrary HTML inside SVG
and can contain scripts that execute in the page context.

### SVG Animation Elements (`<animate>`, `<animateTransform>`,
`<animateMotion>`, `<set>`)

Remove **only if dangerous**; preserve safe animations.

An animation is dangerous when any of these hold:
1. `attributeName` (lowercased) starts with `on` → targets an event handler
2. `attributeName` is a URL attribute (`href`, `xlink:href`, `src`, `action`,
   `formaction`, `data`, `poster`, `background`) **and** the `to`, `from`, or
   any semicolon-separated value in `values` is a dangerous URL
3. `attributeName` is `style` **and** `to`/`from`/`values` contains dangerous CSS
4. The element itself has an `href` or `xlink:href` with a dangerous URL
   (e.g., `<mpath xlink:href="javascript:...">`)

> **Important**: `values` is semicolon-separated — split and check each part
> individually. A list like `"safe;javascript:alert(1)"` contains a dangerous
> URL even though the whole string doesn't start with `javascript:`.

## Phase 3 — Attribute-Level Sanitization

Walk every remaining element and inspect each attribute:

### Event handlers (`on*`)
Remove **any** attribute whose lowercased name starts with `on`.
This covers `onclick`, `onerror`, `onload`, `onmouseover`, `onfocus`,
`ontoggle`, `onanimationend`, and hundreds more.

### URL attributes with dangerous values
Check these attributes for dangerous URLs:
`href`, `src`, `action`, `formaction`, `data`, `poster`, `background`,
`dynsrc`, `lowsrc`, `xlink:href`, `srcdoc`, `codebase`, `classid`,
and any attribute ending with `:href`.

Remove the attribute (not the element) if its value is dangerous.

### `srcdoc`
Remove from any element (embeds raw HTML like an inline iframe).

### Dangerous URL detection

A URL is dangerous if, after normalization, it matches:

```
Normalization steps:
  1. Decode HTML entities (html.unescape)
  2. Strip control characters: \x00-\x08, \x0b, \x0c, \x0e-\x1f, \t, \n, \r
  3. Strip leading/trailing whitespace

Dangerous patterns (case-insensitive):
  javascript\s*:
  vbscript\s*:
  data\s*:\s*text/html
  data\s*:\s*image/svg\+xml
  data\s*:\s*application/xhtml\+xml
```

Key considerations:
- Entity-encoded schemes (`&#106;avascript:`) are decoded by `unescape`
- Mixed case (`JaVaScRiPt:`) is caught by case-insensitive match
- Whitespace/control chars inside scheme (`java\nscript:`) are stripped
- `data:text/html;base64,...` is caught by the `data:text/html` prefix match
- `data:image/svg+xml` is dangerous in `object`/`embed` contexts (but those
  elements are already removed); flag it in URL attributes to be safe

## Phase 4 — CSS Sanitization

### Inline `style` attributes — Remove vs. Sanitize decision

When an inline `style` attribute contains dangerous CSS:
1. **Sanitize** the CSS value (replace dangerous constructs with safe placeholders)
2. **Check** if the sanitized value still has any **meaningful** declarations
   (i.e., property declarations whose value is not `none` and not empty)
3. **If meaningful declarations remain** → keep the attribute with the sanitized value
4. **If only `none` placeholders remain** → **remove the attribute entirely**

This is critical. A `style` like `"background:url(javascript:alert(1))"` has
only one dangerous declaration. After sanitization it becomes `"background:none"`.
This is useless CSS residue — the attribute should be **removed**, not left
as `style="background:none"`.

In contrast, `"color:red; background:url(javascript:alert(1))"` sanitizes to
`"color:red; background:none"`. The `color:red` declaration is meaningful, so
the attribute is **kept** with the sanitized value.

> **Implementation**: Split sanitized CSS by `;`, parse each `property: value`
> pair. A declaration is "meaningful" if its value is non-empty and not `none`.
> If no meaningful declarations exist, remove the attribute.

### `<style>` element contents
Apply the same sanitization to the text content of `<style>` elements.
**Do not remove** `<style>` elements — only sanitize their contents.
Handle CDATA-wrapped content in SVG `<style>` (strip markers, sanitize, restore).

### Dangerous CSS patterns and their replacements

| Pattern                          | Replacement |
|----------------------------------|-------------|
| `expression(...)`                | `none`      |
| `url(javascript:...)`            | `none`      |
| `url(vbscript:...)`              | `none`      |
| `url(data:text/html...)`         | `none`      |
| `-moz-binding: ...`              | (remove)    |
| `behavior: ...`                  | (remove)    |
| `binding: ...`                   | (remove)    |
| `@import 'javascript:...'`       | (remove)    |

> **CSS `url()` with nested parentheses**: Use a regex that matches balanced
> parens to one level: `url\s*\([^()]*(?:\([^()]*\)[^()]*)*\)`.
> This ensures `url(javascript:alert(1))` is fully consumed, not leaving
> a stray `)` that breaks subsequent CSS properties.

## Preprocessing: Null Bytes

**Before parsing**, strip `\x00` from the raw HTML. Browsers silently ignore
null bytes, but `html.parser` may fail to recognize tags containing them
(e.g., `<scr\x00ipt>` is not parsed as `<script>`). Stripping nulls first
ensures the parser sees the same tag names the browser would.

## Preservation Rules

These must survive filtering with no functionally meaningful changes:
- Document structure (doctype, html/head/body, sections, nav, article, etc.)
- Text content and HTML entities (`&amp;`, `&lt;`, `&gt;`, `&quot;`)
- Tables, lists, forms (with safe actions), links (with safe URLs)
- Images (with safe `src`), video/audio (with safe `src`, minus event handlers)
- SVG graphics: shapes, paths, text, gradients, transforms, safe animations
- MathML equations: `mi`, `mo`, `mn`, `mfrac`, `msup`, etc.
- Semantic attributes: `class`, `id`, `data-*`, `role`, `aria-*`, `tabindex`
- Safe CSS in `<style>` and inline `style` attributes

## Self-Verification Checklist

Before submitting, verify the script handles:

- [ ] `<script>` in HTML, SVG, MathML, `<title>`, `<template>`, `<noscript>`
- [ ] Mixed-case tags (`<ScRiPt>`)
- [ ] Entity-encoded attacks (`j&#x61;vascript:`)
- [ ] Null bytes in tag names (`<scr\x00ipt>`)
- [ ] Tabs in tag names (`<script\t>`)
- [ ] All `on*` event handlers on any element (HTML, SVG, MathML)
- [ ] `javascript:`, `vbscript:`, `data:text/html` URLs in href/src/action
- [ ] `<svg>` `<set>`/`<animate>` targeting event handlers or URL attributes
- [ ] SVG `<foreignObject>`, `<handler>`, `<listener>` removal
- [ ] `<meta http-equiv="refresh">` removal
- [ ] `<link rel="import">` removal
- [ ] CSS `expression()`, `url(javascript:...)`, `-moz-binding` in both
      inline style and `<style>` elements
- [ ] CSS `url()` with nested parentheses (e.g. `url(javascript:alert(1))`)
      fully consumed without leaving stray `)` in output
- [ ] Inline `style` attribute **removed entirely** when all declarations
      were dangerous (leaving only `none` placeholders) — e.g.
      `style="background:url(javascript:...)"` → attribute removed,
      not left as `style="background:none"`
- [ ] Inline `style` attribute **kept with sanitized value** when mixed
      safe/dangerous — e.g. `style="color:red; background:url(javascript:...)"`
      → `style="color: red; background: none"`
- [ ] SVG `<style>` with CDATA sections
- [ ] Semicolon-separated `values` in SVG animations
- [ ] `xlink:href` on SVG elements (`<use>`, `<a>`, `<image>`, `<mpath>`)
- [ ] `formaction` on `<button>` and `<input>`
- [ ] Safe content (tables, forms, SVG graphics, MathML) is preserved
- [ ] Doctype and basic document structure survive

## Reference Implementation

See `scripts/filter.py` for a complete working implementation using this
strategy. It can be copied directly to `/app/filter.py`.
