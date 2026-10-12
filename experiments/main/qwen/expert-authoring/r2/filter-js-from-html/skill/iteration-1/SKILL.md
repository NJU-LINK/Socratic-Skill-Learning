---
name: filter-js-from-html
description: >
  Build a Python CLI script that removes executable JavaScript behavior from
  HTML files while preserving legitimate document structure, visible content,
  vector graphics, equations, forms, links, and non-dangerous attributes.
  Handles SVG, MathML, entity-encoded payloads, obfuscated schemes, and
  malformed markup using BeautifulSoup4 with the stdlib html.parser.
---

# Filter JS from HTML

## Task summary

Create `/app/filter.py` — a Python CLI script that:

1. Reads an HTML file path from `sys.argv[1]`.
2. Modifies the file **in-place** to strip executable JS behavior.
3. Preserves safe structure, text, layout, and navigation.

The only required dependency is `beautifulsoup4` (installed as `bs4`) using the
stdlib `html.parser` backend — `lxml` and `html5lib` are **not** available.

## Architecture

```
filter.py
├── decode helpers      # multi-pass decode: HTML entities → strip control chars → URL-decode
├── detection helpers   # is_dangerous_url, is_event_handler, is_dangerous_style, …
├── sanitize(soup)      # 9-step in-place pipeline on a BeautifulSoup tree
└── main()              # read → parse → sanitize → write
```

Copy the reference implementation from `scripts/filter.py` into `/app/filter.py`.

## Decision rules

### Tags to remove entirely (with all children)

Use **normalized** tag names (HTML-entity-decoded, control-char-stripped, lowered)
so that `<scr&#105;pt>` and `<SCRIPT>` are caught the same as `<script>`.

| Normalized name | Rationale |
|---|---|
| `script` | Direct JS execution |
| `iframe` | Navigation + script host |
| `object`, `embed`, `applet` | Plugin execution |
| `noembed` | Fallback for embed |
| `frameset`, `frame` | Frame-based navigation |
| `base` | Rewrites all relative URLs |

### Tags to remove only inside SVG / MathML

Walk up the parent chain; if an ancestor is `<svg>` or `<math>` the tag is
in a namespace-aware context where browsers execute scripts.

| Tag | Rationale |
|---|---|
| `script` | SVG/MathML script execution |
| `handler` | XBL-like event binding |
| `foreignobject` | Can embed full HTML (including scripts) |

### Attributes to remove

| Category | Attributes / Pattern | Check |
|---|---|---|
| Event handlers | Any `on*` (`onclick`, `onerror`, `onload`, …) | Always remove |
| URL attributes | `href`, `src`, `action`, `formaction`, `data`, `poster`, `dynsrc`, `lowsrc`, `background`, `srcdoc`, `xlink:href`, `usemap`, `longdesc`, `code`, `codebase`, `archive`, `movie`, `pluginspage`, `classid` | Remove if URL is dangerous |
| `srcset` | Comma-separated URL+descriptor list | Remove if any URL is dangerous |
| `srcdoc` | Always | Always remove |
| `style` (attribute) | Any value | Remove if contains dangerous CSS |

### Dangerous URL detection

Apply multi-pass decoding **before** checking:

1. HTML-entity decode (`html.unescape`)
2. Strip control characters: `\x00–\x08`, `\x0b`, `\x0c`, `\x0e–\x1f`, `\x7f`, `\ufffd`
3. URL-decode (`urllib.parse.unquote`)
4. Repeat up to 5× for layered encoding
5. Collapse whitespace (`re.sub(r'\s+', '', …)`) and lowercase

Then check the collapsed value:

- Starts with `javascript:`, `vbscript:`, or `livescript:` → **dangerous**
- Starts with `data:` containing `text/html` or `application/xhtml+xml` → **dangerous**
- Starts with `data:` with `base64` flag → decode and scan for `<script`, `<iframe`, etc.

### Dangerous CSS detection

For `style=""` attributes, flag if decoded/collapsed value contains:

- `expression(` — IE expression
- `-moz-binding:` — XBL binding
- `behavior:` — IE HTC
- `javascript:` or `vbscript:` — scheme in CSS

For `<style>` tag **content**, additionally sanitize:

- Replace `expression(…)` with `none`
- Remove `-moz-binding: …` declarations
- Remove `behavior: …` declarations
- Remove `@import …;` rules
- Replace `url(javascript:…)` and `url(vbscript:…)` with `none`

### SVG-specific attribute checks

| Element | Dangerous pattern |
|---|---|
| `<set>`, `<animate>`, `<animatetransform>` | `attributename` targets an `on*` handler |
| `<use>` | `href` or `xlink:href` is a dangerous URL |

### Dangerous comments

- Contains the word `script` → remove (may hide scripts)
- Contains `if` AND (`ie` OR `mso`) → remove (IE conditional comments)

### `<meta>` tags

- `http-equiv="refresh"` → remove (can redirect to javascript:)
- Preserve `charset`, `viewport`, `description`, `content-security-policy`, etc.

### `<link>` tags

- Remove if `href` is a dangerous URL
- Preserve safe stylesheet links, icons, etc.

### `<form>` tags

- Remove `action` attribute if its URL is dangerous
- Preserve the form element, its children, method, and other attributes

## Preservation rules (what NOT to touch)

- All text content (including entities like `&amp;`, `&copy;`)
- Safe elements: `<p>`, `<div>`, `<table>`, `<ul>`, `<ol>`, `<dl>`, `<h1>`–`<h6>`,
  `<img>` (with safe src), `<a>` (with safe href), `<form>` (with safe action), etc.
- SVG graphics: `<circle>`, `<rect>`, `<path>`, `<text>`, `<defs>`, `<linearGradient>`, etc.
- MathML equations: `<mrow>`, `<mi>`, `<mn>`, `<mo>`, `<mfrac>`, `<msup>`, etc.
- Attributes: `id`, `class`, `data-*`, `aria-*`, `role`, `style` (when safe),
  `title`, `alt`, `width`, `height`, `colspan`, `rowspan`, etc.
- `<noscript>`, `<template>`, `<details>`, `<summary>`, `<marquee>` (not dangerous)
- Boolean attributes (`checked`, `disabled`, `required`, etc.)

## Sanitization pipeline (execution order)

1. Remove dangerous comments
2. Remove dangerous tags (normalized name match) — decompose with children
3. Remove dangerous SVG/MathML elements — decompose with children
4. Sanitize `<style>` tag text content in-place
5. Clean attributes on every remaining tag
6. Remove `<meta http-equiv="refresh">`
7. Remove `<link>` with dangerous `href`
8. Strip dangerous `action` from `<form>`
9. Final sweep: remove any remaining dangerous tags (catches edge cases)

Steps 2–3 use normalized tag names to handle entity-encoded tag names.
Step 9 is a safety net for tags that may have been missed in earlier passes
due to parser quirks.

## Verification checklist

After writing the script, run it against these scenarios and inspect output:

| # | Input | Expected behavior |
|---|---|---|
| 1 | `<script>alert(1)</script>` | Removed entirely |
| 2 | `<SCRIPT>`, `<Script>`, `<scr&#105;pt>` | All removed (case/entity insensitive) |
| 3 | `<p onclick="…">text</p>` | `onclick` removed, `text` kept |
| 4 | `<a href="javascript:…">` | `href` removed, text kept |
| 5 | `<a href="&#106;avascript:…">` | Caught after entity decode |
| 6 | `<a href="%6A%61…%3A…">` | Caught after URL decode |
| 7 | `<a href="java\nscript:…">` | Caught after whitespace collapse |
| 8 | `<a href="j&#0;avas&#0;cript:…">` | Caught (U+FFFD stripped) |
| 9 | `<iframe>`, `<object>`, `<embed>` | Removed entirely |
| 10 | `<svg><script>…</script></svg>` | Script removed, SVG kept |
| 11 | `<circle onclick="…"/>` | `onclick` removed, circle kept |
| 12 | `<set attributeName="onmouseover" to="…"/>` | `attributename` removed |
| 13 | `<style>body{background:expression(alert(1))}</style>` | `expression(…)` → `none` |
| 14 | `<p style="-moz-binding:url(…)">` | `style` removed |
| 15 | `<base href="javascript:…">` | Removed entirely |
| 16 | `<meta http-equiv="refresh" content="0;url=javascript:…">` | Removed |
| 17 | `<form action="javascript:…">` | `action` removed, form kept |
| 18 | `<img srcset="javascript:… 320w">` | `srcset` removed |
| 19 | `<a href="data:text/html,<script>…">` | `href` removed |
| 20 | `<table>`, `<div>`, `<noscript>`, safe `<style>` | All preserved unchanged |
