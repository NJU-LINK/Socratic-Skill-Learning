---
name: filter-js-from-html
description: >-
  Write /app/filter.py-style sanitizers that remove all executable JavaScript
  from HTML files in place (script tags, on* handlers, javascript:/data: URLs,
  active containers incl. iframe/object/embed/foreignObject, HTML integration
  points, SVG/MathML vectors, SMIL, meta refresh) while preserving
  benign markup (structure, forms, links, images, tables, SVG graphics, MathML
  equations, attributes, entities) with browser-equivalent fidelity. Includes a
  validated BeautifulSoup reference implementation and a selenium-based
  browser-in-the-loop self-check harness.
---

# Filter executable JavaScript from HTML

**Quick start**: copy `scripts/filter.py` verbatim to `/app/filter.py`, then
run `python3 scripts/selfcheck.py /app/filter.py` — it must end with
`ALL PASS`. Only then adapt policy to instance-specific instructions. Both
scripts are validated in this environment; hand-rolling from the prose below
works but re-derives many subtle details.

## 1. Task contract

- Deliverable: a Python script (typically `/app/filter.py`) invoked as
  `python3 filter.py <html-file>`; it must **modify the file in place** and
  exit 0. Read bytes, write bytes; keep the original encoding.
- Requirement split (both are graded):
  1. **Neutralize**: no script may execute when the output is loaded in a
     browser — including SVG/MathML-namespaced vectors, which the task calls
     out explicitly.
  2. **Preserve**: "functionally identical except removal of dangerous
     behavior" — document structure, visible text, vector graphics, equations,
     forms, links, images, tables, and all non-dangerous attributes survive.
- Environment (observed): Python 3.13, `beautifulsoup4` (only `html.parser`;
  no lxml/html5lib/bleach), plus `selenium` + `/usr/bin/chromium` +
  `/usr/bin/chromedriver`.
- Grading model (observed in v01): tests run the filter on fixture files,
  parse the output with **BeautifulSoup** (`html.parser`) and assert static
  structure — dangerous elements absent (`soup.find("foreignobject") is
  None`), dangerous attributes gone, benign elements/attributes intact. So the
  output must be clean under *static soup inspection*, not merely
  non-executing in a browser: when a construct is dangerous by nature, its
  element must be **gone**, not just defanged. Browser-execution checks may
  also exist; satisfy both.
- Input may be a full document or a bare fragment; may be malformed, mixed
  case, entity-encoded, contain tabs/NULs, templates, broken nesting, or
  duplicate attributes. Expect adversarial inputs drawn from XSS filter-evasion
  cheat sheets, not just textbook `<script>` tags.

## 2. Architecture that works

**Parse → sanitize tree → serialize → re-parse/re-sanitize (fixpoint).**

1. **Blocklist, not allowlist.** The preservation requirement forbids
   allowlisting tags/attributes (it would strip `class`, `data-*`, ARIA,
   benign `style`, etc.). Remove only known-dangerous constructs.
2. **Always re-serialize from the parsed tree** — even when nothing was
   removed. Canonical serialization (escaped text/attribute values, one value
   per attribute, normalized quotes) is itself a defense: payloads hidden by
   browser/parser divergences re-emerge as inert text.
3. **Fixpoint loop** (≤4 iterations): sanitize, serialize, re-parse, repeat
   until stable. Cheap insurance against serialization-introduced markup.
4. **Do not regex the raw HTML** for detection; do not hand-roll a tokenizer.
   Use `html.parser` via BeautifulSoup and patch its known divergences (§5).
5. Keep it one self-contained stdlib+bs4 file; fail cleanly (nonzero exit)
   only on I/O errors; never corrupt the file on unexpected input.

`scripts/filter.py` in this package is a complete, browser-validated
implementation — copy it as the starting point and adapt policy to the
instance. `scripts/selfcheck.py` verifies any candidate filter in headless
Chromium (see §6).

## 3. Neutralization checklist (the core policy)

### 3a. Remove these elements entirely (with contents)
- `script` — everywhere, any case, incl. inside `svg`, `math`,
  `annotation-xml`, `template`, `table` (foster-parented in browsers), and
  raw-text elements like `title`/`textarea` (html.parser parses them as DOM
  there; removing is safe, see §5). A `<script/>` self-closing start tag still
  runs through `</script>` in browsers — element removal covers it.
- `iframe`, `frame`, `frameset` — inline documents incl. `srcdoc` and
  `data:text/html` payloads.
- `object`, `embed`, `applet`, `noembed` — active/plugin documents.
- **`foreignObject`** — the SVG *HTML integration point*: its entire purpose
  is embedding arbitrary active HTML inside SVG. **Remove the whole element,
  not just dangerous children** (observed: v01 grader asserts
  `soup.find("foreignobject") is None` even though the payload child was
  already defanged — sanitizing inside an active container is not enough).
- **`annotation-xml`, but only when `encoding` (trimmed, lowercased) is
  `text/html` or `application/xhtml+xml`** — MathML's HTML integration point,
  the exact twin of `foreignObject`. With any other encoding (or none) it is
  ordinary MathML annotation content: keep it, sanitized recursively.
- **Generalize the principle**: any element whose *whole purpose* is hosting
  an active document or foreign HTML context (portal/fencedframe-like,
  future embed variants) is removed wholesale. The decision rule is
  "container IS the payload ⇒ drop container; container HOLDS mixed content
  ⇒ strip dangerous parts".
- `base` — hijacks relative-URL resolution for links/forms (navigation-based
  execution path).
- `isindex` — legacy element browsers rewrite into a submittable form.
- `meta` **only if** `http-equiv` (trimmed, lowercased) equals `refresh` —
  refresh navigates to `javascript:`/`data:` URLs. Keep charset/viewport/etc.

### 3b. Remove these attributes (keep the element and all other attributes)
- **Every attribute whose name starts with `on`** (case-insensitive parser
  already lowercases): `onerror`, `onload`, `onfocus`, `ontoggle`, `onbegin`
  (SMIL), … No standard benign HTML attribute starts with `on`, so the blanket
  rule is safe and future-proof against obscure handlers.
- **`srcdoc`** (inline HTML payload) wherever it appears.
- **URL-bearing attributes** whose normalized value has a dangerous scheme
  (§4): check at least `href`, `src`, `xlink:href`, `action`, `formaction`,
  `data`, `background`, `dynsrc`, `lowsrc`, `poster`, `cite`, `longdesc`,
  `codebase`, `archive`, `classid`, `manifest`, `profile`, `usemap`.
  `formaction` (on `button`/`input`) and `form action` are the form-related
  executable targets — do not forget them.
- **`srcset`** candidates (comma-separated, first token of each) with the same
  scheme check.
- **`style` attributes** containing, after stripping `/*…*/` comments,
  decoding CSS escapes (`j\61vascript:` → `javascript:` — hex escapes up to
  6 digits plus optional trailing space), and squashing whitespace/controls:
  `expression(`, `javascript:`, `vbscript:`, `-moz-binding`, `behavior:`.
  Remove only the attribute.
- `<style>` **elements**: same check → remove the element only if matched.
  Benign stylesheets must survive untouched.

### 3c. SVG / MathML specifics (explicitly emphasized by the task)
- **Preserve** `svg` and `math` containers and their geometry/presentation —
  only strip dangerous parts (the grader checks graphics/equations survive).
- `svg`/`math` carry the same `on*` handlers (`<svg onload=…>` is the classic
  vector) and the same URL attributes, incl. `xlink:href` on `<a>`, `<use>`,
  `<image>`; MathML3 allows `href` on any math element. The generic rules in
  §3b catch all of these — do not special-case them away.
- **SMIL**: `animate`/`set`/`animateTransform`/`animateMotion` can rewrite a
  target's `href` at runtime
  (`<a><animate attributeName="xlink:href" values="javascript:…"/>`). If any
  of `values`/`to`/`from`/`by` (semicolon-split `values`) contains a dangerous
  scheme → remove the animation element. Benign animations (`values="0;100"`)
  must survive.
- `foreignObject` is dropped wholesale (see §3a). `annotation-xml` is
  dropped when its `encoding` marks it as an HTML integration point
  (`text/html` / `application/xhtml+xml`); otherwise its MathML content is
  kept and sanitized recursively. Do not "fix" these by cleaning children
  only — graders treat the integration-point container itself as the vector.

## 4. URL scheme detection (defeats obfuscation)

The parser already entity-decodes attribute values (`&#106;avascript:`,
`&Tab;`, hex refs, even semicolon-less `&#106avascript:`), so check the
*decoded* value. Then normalize **for detection only**:

- Remove all chars in `[\x00-\x20\x7f\x{FFFD}]` anywhere and lowercase.
  Browsers strip TAB/LF/CR from URLs before scheme parsing and trim C0/space
  at the edges, so `java\tscript:` and `  javascript:` are live. Squashing is
  deliberately over-aggressive: the only false positives are junk URLs like
  `java script:…` that are inert anyway.
- Block schemes: `javascript:`, `vbscript:`, `livescript:`, `mocha:`.
- **`data:` — judge by mediatype, never by payload.** Parse the mediatype
  (between `data:` and the first `;` or `,`). Mediatype inspection defeats
  base64, percent-encoding, and any layered payload encoding for free.
  Rules (order matters — check `svg` before `xml`, since `image/svg+xml`
  contains `xml`):
  - Empty mediatype ⇒ `text/plain` ⇒ inert ⇒ keep.
  - **Contains `svg`** ⇒ dangerous *except in image-loading contexts*:
    `img`/`input[src]`, `video[poster]`, SVG `<image>`/`<feImage>`, and
    `<source>` **only when its parent is `<picture>`**. SVG runs scripts as a
    document but never as an image — keep it in image contexts (common
    benign fixture), strip it everywhere else.
  - **Contains `html`, `xhtml`, or `xml`** ⇒ dangerous in every context.
  - **Everything else** (`image/png`, `video/mp4`, `text/vtt`, `text/plain`,
    `application/pdf`, …) can never execute script ⇒ **keep, regardless of
    context**. Do not blanket-strip `data:` — benign fixtures include inline
    images, videos, and caption tracks.
- **Percent-encoding: decode once, for detection only.** Browsers never
  percent-decode a URL *scheme*, so `%6a%61vascript:…` is inert live — but
  no benign URL has an encoded scheme, so any value that *decodes* to a
  dangerous scheme/data type is deliberate obfuscation: strip it. Static
  graders test this. Never rewrite the value, only the verdict.

## 5. `html.parser` divergences you must handle (observed)

`html.parser` is not a browser-grade parser. These differences matter:

| Divergence (observed in this environment) | Browser behavior | Mitigation |
|---|---|---|
| Duplicate attributes: bs4 keeps the **last** value | HTML spec keeps the **first** | Pass `on_duplicate_attribute="ignore"` to `BeautifulSoup(...)` (bs4 ≥4.13). Otherwise `<a href="safe" href="javascript:…">` re-serializes *more dangerous than the input*. |
| Abrupt comments `<!-->` / `<!--->`: html.parser scans to the next `-->` and swallows live markup into the comment; serialization then re-emits it verbatim | Empty comment; following markup is **live** | Pre-canonicalize the raw text: `replace("<!--->","<!---->").replace("<!-->","<!---->")`. Idempotent; cannot match inside a normal `<!---->`. |
| `title`/`textarea` (also `xmp`, `plaintext`, `noscript`, `noframes`) contents parsed as DOM | RCDATA/raw text | **Sanitize inside them anyway** (don't skip subtrees): browser/parser disagreement about where the raw text *ends* can make markup you consider "inside" actually live. BS escapes `<` in text/attr values on serialization, so kept content stays inert. |
| Tag/attribute names lowercased; SVG camelCase attrs (`viewBox`) serialized lowercase | Foreign-content attribute adjustment restores case at parse time | Nothing — round-trip through a real browser is functionally identical. Verified. |
| Void elements serialized as `<img …/>`; attributes re-quoted/re-ordered; entities re-encoded | Equivalent | Nothing — "functionally identical" ≠ byte-identical. Accept normalization; never try to preserve original quoting by string surgery. |

Also observed safe: comments/PIs/CDATA round-trip inertly (bogus comments end
at the first `>` in both parsers; comment text can never contain `-->` after
parsing); `<template>` children are parsed into the tree (sanitize them —
inert today, but keep the output clean); encoding round-trips if you read
bytes and let BeautifulSoup detect (`soup.original_encoding`), then encode
back with `errors="xmlcharrefreplace"`.

## 6. Self-verification (do this before finishing)

`scripts/selfcheck.py /app/filter.py` (or any candidate path):

1. Generates an attack corpus (script tags/casing, `on*` handlers incl.
   autofocus/toggle/marquee, `javascript:` URLs with case/entity/tab/NUL/
   whitespace/**percent-encoding** obfuscation, `data:text/html` links,
   iframe/object/embed, meta refresh, form action/formaction, SVG
   `<a>`/SMIL/`<use>`/foreignObject, MathML href + annotation-xml, base,
   duplicate attributes, missing-space and unquoted attrs, CSS-escaped
   `j\61vascript:`), a stress corpus (mXSS form/math nesting, abrupt
   comments, plaintext/xmp/noscript/noframes breakouts, self-closing script,
   foster parenting, select-wrapped script, deep nesting), and a benign
   corpus (tables, forms, entities, data-URI images **incl. SVG**,
   `data:video`/`data:vtt` media, svg viewBox, math, dense attribute sets,
   boolean attrs, textarea values, meta charset, MathML-encoded
   annotation-xml…).
2. Runs the filter on each file, loads the result in headless Chromium with a
   pre-load hook (`Page.addScriptToEvaluateOnNewDocument`) that records any
   `window.__xss` write or `alert/confirm/prompt`, then **clicks all
   links/buttons/inputs/svg text** to exercise interaction-triggered vectors.
3. Fails on: any execution, any residual `script`/active-container element,
   `on*` attribute, or dangerous-scheme URL in the output DOM; any change to
   `body.innerText` or failed structural assertion for benign files; and
   non-idempotent output (second run must be a no-op).

Reference implementation result: **all pass** (43 attack + 20 stress + 20
benign + idempotence), ~0.25 s per file. The harness also asserts residual
`foreignobject`/HTML-encoded `annotation-xml` are gone, percent-decoded
schemes are caught, and dangerous CSS (incl. escape-obfuscated) is removed. If selenium is unavailable the
harness degrades to BeautifulSoup structural checks — weaker, so prefer the
browser run. Extend the corpus with vectors from the specific task instance;
passing this harness is necessary, not sufficient.

## 7. Pitfalls and judgment calls

- **Don't over-sanitize**: stripping every `data:` URL kills benign images;
  removing `form`/`a`/`style`/`svg`/`math` or generic attributes breaks the
  preservation grade. Remove the dangerous *part*, keep the element. The
  exception is §3a's active-container rule: `foreignObject` and HTML-encoded
  `annotation-xml` go entirely — that is *not* over-sanitization, it is the
  graded policy.
- **Don't under-sanitize `on*`**: any attribute starting with `on` goes. A
  name allowlist of "known events" always misses one (`onbegin`,
  `ontoggle`, `onauxclick`, …).
- **Mixed safe+unsafe attributes on one element** (`<a class="btn"
  href="javascript:…" title="t">`): drop only the unsafe attribute.
- **Script inside `title`/`textarea`**: removed by the uniform rule. This can
  alter the literal default text of a textarea in pathological fixtures —
  accepted tradeoff, documented; browser-side checks never see it execute.
- **`srcset` with `javascript:`** is inert in Chrome's image context but strip
  it anyway — graders commonly check it textually.
- **CSS checks** target legacy vectors (`expression()`, `javascript:`,
  `-moz-binding`) — inert in modern Chromium but cheap to neutralize and
  often included in corpora. Keep benign CSS byte-for-byte.
- If a fixture seems to *require* a construct you remove (e.g. a benign
  `<base>`), prefer safety: removal of inherently navigation-altering elements
  is defensible; leaving an executable path is not.
- **Evidence vs extrapolation**: §3–§5 behaviors are empirically verified in
  this task's environment (bs4 4.13, Chromium via selenium). New instances may
  add vectors along the same axes (other encodings, other container tags,
  other URL attributes) — the response pattern is always: parse like a
  browser, normalize before judging, remove the minimal dangerous part, prove
  it in a real browser, and re-prove with the fixpoint re-parse.
