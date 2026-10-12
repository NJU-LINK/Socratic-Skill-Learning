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

## ⚠️ Deployment: how to get the script into /app

The `read` tool can access the host workspace (including `scripts/filter.py`),
but `task_shell` runs inside an **isolated** `/app` container that **cannot**
see host workspace paths.  You **cannot** use `cp` to copy the file.

**Correct approach**: Use `read` to load `scripts/filter.py`, then use
`task_shell` with a heredoc to write it into `/app/filter.py`:

```
task_shell: cat > /app/filter.py << 'ENDOFFILE'
<entire file content from read>
ENDOFFILE
```

Do NOT attempt `cp`, `cat`, or any filesystem operation on host workspace
paths from `task_shell` — they will fail with "No such file or directory".

## Architecture

```
filter.py
├── decode helpers      # multi-pass decode: HTML entities → strip control chars → URL-decode
├── detection helpers   # is_dangerous_url, is_event_handler, is_dangerous_style, …
├── sanitize(soup)      # 10-step in-place pipeline on a BeautifulSoup tree
└── main()              # read → parse → sanitize → write
```

Read the reference implementation from `scripts/filter.py` and deploy it to
`/app/filter.py` using the heredoc method described above.

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

### SVG animation elements: whole-element removal

`<set>`, `<animate>`, and `<animatetransform>` set or animate attribute values
on other SVG elements.  They must be removed **entirely** (not just have
attributes stripped) when dangerous.  This requires a **whole-element check**
before the per-attribute cleaning loop.

An SVG animation element is dangerous when:

1. **Target is an event handler** — `attributename` value starts with `on`
   (e.g. `<set attributeName="onmouseover" to="alert(1)">`)
2. **Any attribute value is a dangerous URL** — check every attribute on the
   element (`to`, `from`, `values`, `by`, `xlink:href`, etc.) through the
   standard `_is_dangerous_url` decoder.  This catches cases like
   `<set attributeName="xlink:href" to="javascript:alert(1)">` where the
   target is a URL-bearing attribute and the injected value is executable.

**Safe example** (preserve): `<animate attributeName="fill" values="red;blue">` —
`values` is `"red;blue"` which is not a dangerous URL.

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
- Replace `url(javascript:…)`, `url(vbscript:…)`, and `url(data:text/html…)` with `none`

### SVG-specific per-attribute checks (non-animation elements)

| Element | Dangerous pattern |
|---|---|
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
- SVG animations with safe values: `<animate attributeName="fill" values="red;blue">`
- MathML equations: `<mrow>`, `<mi>`, `<mn>`, `<mo>`, `<mfrac>`, `<msup>`, etc.
- Attributes: `id`, `class`, `data-*`, `aria-*`, `role`, `style` (when safe),
  `title`, `alt`, `width`, `height`, `colspan`, `rowspan`, etc.
- `<noscript>`, `<template>`, `<details>`, `<summary>`, `<marquee>` (not dangerous)
- Boolean attributes (`checked`, `disabled`, `required`, etc.)

## Sanitization pipeline (execution order)

1. Remove dangerous comments
2. Remove dangerous tags (normalized name match) — decompose with children
3. Remove dangerous SVG/MathML elements — decompose with children
4. **Remove dangerous SVG animation elements** — whole-element decompose for
   `<set>`/`<animate>`/`<animatetransform>` that target event handlers or
   contain dangerous URLs in any attribute
5. Sanitize `<style>` tag text content in-place
6. Clean attributes on every remaining tag
7. Remove `<meta http-equiv="refresh">`
8. Remove `<link>` with dangerous `href`
9. Strip dangerous `action` from `<form>`
10. Final sweep: remove any remaining dangerous tags (catches edge cases)

Steps 2–4 use normalized tag names to handle entity-encoded tag names.
Step 4 must run before step 6 (attribute cleaning) because it removes entire
elements rather than individual attributes.
Step 10 is a safety net for tags missed in earlier passes due to parser quirks.

## Verification checklist

After deploying the script to `/app/filter.py`, run it against these scenarios
and inspect output:

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
| 12 | `<set attributeName="onmouseover" to="…"/>` | **Element** removed (targets on*) |
| 13 | `<set attributeName="xlink:href" to="javascript:…"/>` | **Element** removed (dangerous URL in `to`) |
| 14 | `<animate attributeName="fill" values="red;blue">` | Preserved (safe values) |
| 15 | `<style>body{background:expression(alert(1))}</style>` | `expression(…)` → `none` |
| 16 | `<p style="-moz-binding:url(…)">` | `style` removed |
| 17 | `<base href="javascript:…">` | Removed entirely |
| 18 | `<meta http-equiv="refresh" content="0;url=javascript:…">` | Removed |
| 19 | `<form action="javascript:…">` | `action` removed, form kept |
| 20 | `<img srcset="javascript:… 320w">` | `srcset` removed |
| 21 | `<a href="data:text/html,<script>…">` | `href` removed |
| 22 | `<foreignObject>…</foreignObject>` in SVG | Removed entirely |
| 23 | `<table>`, `<div>`, `<noscript>`, safe `<style>` | All preserved unchanged |
