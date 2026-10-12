# Decision tables for filter-js-from-html

These tables are the *family variation* of the skill: the procedure in
`SKILL.md` is fixed; a task variant changes rows here. Every row must have
at least one harness case.

## 0. Iteration ledger (evidence, not vibes)

| Iteration | Graded result | Change made | Calibration |
|---|---|---|---|
| 1 | 3/4 — foreignObject kept (sanitize-in-place) | none (baseline) | reference deletes foreignObject wholesale: `soup.find("foreignobject") is None` (assertion quoted verbatim from feedback) |
| 2 | 4/4 | foreignObject → ELEMENT_DELETE (wholesale, self-closing honored); vendor pin html5lib==1.1 + auto-bootstrap | other rows NOT churned: evidence flows only from the arbiter and concrete feedback; the three passing tests are the weight against excess deletion |
| 3 | expected 4/4 — PENDING EVALUATION (no grader feedback this cycle; actual local evidence sits in the calibration column: byte-identical artifact against the proven bytes, emulated suite 4/4, 90-case output-equivalence with the named premise) | documentation/taxonomy + TRIPWIRE REPAIR: `_C0_OR_PCT` gained the missing `*` (the evidence ear was silent-by-construction; stderr-only). Output-equivalence proof over all 90 battery cases (EQUIV FAILURES: 0). **Premise of the no-deletion claim, named**: it rests on the confirmed single-consumer scope of `_SCHEME_PATTERNS` (consumed only by `raw_tripwire`, a print-only path — true by reading) PLUS the battery run; scope, not the run, carries the induction to unseen inputs. Detector-firing tests added (run_bias_units) so a dead ear is a red harness, not a ghost. Observed fire/silent set: FIRES on title-js-mention, long-value-inert-scheme, pct-c0-in-scheme; SILENT on clean tags and scheme text outside tags. | behavior unchanged; biases + ear pinned under test |

Named biases under calibration (NOT browser facts — see section 2):
unquote-before-scheme-check (percent in scheme), FF/VT-anywhere strip,
U+FFFD strip, `.strip()`'s Unicode-whitespace trim, C0 strip beyond
tab/LF/CR. Same status as the `java script:` preservation decision: a
bias you can name is policy; a bias you cannot name is a bug.

## 1. Executable vector classes → rules → spec axes

| Vector class | Rule | Spec axis |
|---|---|---|
| Direct script execution | Delete elements: `script, iframe, frame, object, embed, applet, noscript, noembed, noframes` (case-folded; any namespace incl. SVG/MathML) | executable_html_vectors |
| Inline event handlers | Delete every attribute whose **local** name is `on*` (strip namespace prefix first: `xlink:onload` → `onload`). Never score by "commonness": `<input autofocus onfocus>` executes at load with zero interaction | executable_html_vectors |
| `javascript:` / `vbscript:` URLs | Scheme check on decoded value (table §2), applied to URL-bearing attributes (§3) on every element, any namespace | executable_html_vectors, payload_obfuscation |
| `data:` URLs that embed HTML | Media type in `{text/html, application/xhtml+xml, image/svg+xml}`; or payload (percent/base64-decoded) starts with `<` | executable_html_vectors, payload_obfuscation |
| Active containers (OPEN cohort) | Element deletion covers iframe/object/embed/applet/frame/foreignObject; `srcdoc` attribute always deleted. **Container-classification default (decision of record #6): the family's "active container tags *such as* iframe, object, embed" is an open cohort — for any invisible structural element that can host arbitrary HTML, default to WHOLESALE DELETION, not in-place sanitization. A deleted invisible container costs no visible content; a preserved one risks the whole container class. foreignObject was the canonical next member (svg>foreignObject can host `<body onload>`; a classic mXSS host) and iteration-1 grading evidence confirms the v01 reference deletes it (`soup.find("foreignobject") is None`).** | executable_html_vectors, preservation_fidelity |
| Scriptable SVG/MathML | Same element/attribute rules apply inside foreign content; `script`/`style` stay rawtext there; `title`/`textarea`/`xmp` do NOT (children are real tokens — `<svg><title><b onbegin>` must be caught) | executable_html_vectors, preservation_fidelity |
| SVG animation attacks | `animate, animateColor, animateMotion, animateTransform, set`: delete element if `attributeName` (local part) is `on*`/`href`/`xlink:href`, or any of `from/to/by/values` is a dangerous URL | executable_html_vectors |
| Form-related executable targets | `action` on form, `formaction` on button/input — delete the attribute only (form behavior survives) | executable_html_vectors, preservation_fidelity |
| Refresh / navigation execution | `meta http-equiv=refresh` whose `content` URL (after `url=` / quotes stripped) is dangerous → delete the meta element; safe refresh kept | executable_html_vectors |
| Dangerous attributes beyond `on*` | `srcdoc`, `style` (executable CSS, §4), URL attrs (§3): `href src srcset action formaction poster background cite longdesc lowsrc dynsrc data icon manifest ping codebase` (+ namespace-local forms like `xlink:href`) | executable_html_vectors, payload_obfuscation |
| CSS-like constructs | `expression(`, `javascript:`/`vbscript:` (also inside `url(...)`), `-moz-binding`, `behavior`, `@import` | executable_html_vectors, payload_obfuscation |
| Combinations executable only after parsing | `annotation-xml encoding="text/html"` children parse as HTML (sanitize in place); duplicated attributes (browser keeps the **first**) — classify per raw occurrence | executable_html_vectors, html_parsing_irregularity |
| HTML entities / nulls / case | Tokenizer decodes charrefs, case-folds names, replaces nulls; classify on the decoded DOM-level value, delete raw spans | payload_obfuscation, html_parsing_irregularity |

## 2. URL normalization table (classifier + hygiene must agree)

Browsers read a scheme after this normalization; anything a browser would
treat as `javascript:` must be flagged, anything it would read as a
relative URL must be preserved:

| Input byte class | Treated as | Action |
|---|---|---|
| ASCII tab / LF / CR | stripped **anywhere** (SPEC: the WHATWG URL parser strips these before scheme recognition) | remove before scheme check |
| FF / VT (`\x0b\x0c`) anywhere | NOT stripped by the standard → `java\x0bscript:` is a relative, inert URL in conformant engines | removed anyway as **NAMED SAFE-SIDE BIAS** (legacy tolerance) |
| NUL (`\x00`) | dead at the classifier layer: the tokenizer already replaced it with U+FFFD in the markup pipeline | the live NUL mechanism is the U+FFFD row below |
| C0 controls + ASCII space, ends | trimmed at the **ends** only (SPEC) | `str.strip()`, which also trims Unicode whitespace (NBSP, line separators) — **NAMED BIAS** beyond the spec |
| interior ordinary space (`java script:`) | NOT stripped → relative URL, inert | preserve |
| HTML charrefs (`&#115;`) | decoded in the **markup** pipeline before the URL parser sees the value → `java&#115;cript:` DOES execute | classify decoded value (this is why the tokenizer-decode classifier is right) |
| percent-encoding in the scheme (`%73`, `%09`) | NOT decoded before scheme recognition: `%` is not in the scheme alphabet `[A-Za-z][A-Za-z0-9+.-]*`, so `java%73cript:` is a relative, inert URL in conformant browsers | `urllib.parse.unquote` before the scheme check as **NAMED SAFE-SIDE BIAS** (legacy engines; see data-header row) |
| percent-encoded `data:` media header (`data:%74ext/html`) | legacy engine variance: some decode the header before MIME classification, some do not | unquote-first makes the executable media set still match — safe-side bias |
| U+FFFD (the tokenizer's NUL replacement; `\x00` never reaches this layer) | replacement char produced by the markup pipeline | strip — named safety bias |
| case (`JAVASCRIPT:`) | case-folded | lowercase scheme compare |
| `data:` payload | media type before `;`/`,`; payload after first `,` | media in executable set, or decoded payload starts with `<`, or base64-decoded payload starts with `<` → dangerous |

Everything extra stripped beyond the spec is a *safety-side bias*: keep it
deliberate and named (a constant/comment), not emergent. The bias rows in
this table are enforced under test in the harness (`run_bias_units`), so a
later reader cannot "simplify" them into browser facts or delete them
silently. The html5lib arbiter adjudicates PARSE semantics only: URL
normalization is outside its scope — no DOM walk or absence-assertion
grader will ever tell you a browser-inert URL was over-deleted. That is
why these rows are named, not implicit.

## 3. Rawtext / RCDATA element sets by context

| Context | rawtext (inert text; close = first `</name` + boundary) | RCDATA (text; charrefs decoded) | not masked (children are tokens) |
|---|---|---|---|
| HTML content | `script style xmp iframe noembed noframes noscript` | `title textarea` | — |
| Foreign content (inside svg/math, before an integration point) | `script style` | — | `title textarea xmp iframe noembed noframes noscript` |
| HTML integration points (children parse as HTML): MathML text integration points `mi mo mn ms mtext`, `annotation-xml` with `encoding=text/html` or `application/xhtml+xml`. **`foreignObject` is NOT a sanitize-in-place integration point: it is a deleted container (deny list). Its integration-point row is kept only for context modeling and is UNREACHABLE BY CONSTRUCTION — foreignobject is deleted wholesale before any child token is processed. Do not re-derive a sanitize-in-place policy from this table (that was the iteration-1 bug: 1/4 hidden tests failed).** | as HTML content | as HTML content | — |
| `plaintext` | element start → rest of document is text, no close tag | — | — |

Close-tag boundary predicate (rawtext and RCDATA, case-insensitive):

```
</name(?=[\t\n\f\r />])
```

`</scriptx>` does NOT close; `</script x>` (space) does; `x("</script>")`
does not (quote is not a boundary). Script additionally has
escaped/double-escaped states: after `<!--`, a `<script`+boundary enters
double-escaped, where `</script`+boundary is **text**.

Self-closing: honored only for non-HTML-named elements (foreign) and for
`<script/>` in foreign content. Ignored in HTML content for all rawtext
elements (`<script/>alert(1)</script>` has content `alert(1)`).

## 4. CSS facts

- CSS comments are removed **without becoming token boundaries**:
  `@im/**/port` is the identifier `@import`.
- CSS escapes decode: `\70` → `p`; a trailing space after a hex escape is
  consumed as part of the escape: `\70 ort` → `port`.
- `expression(...)` is flagged even with whitespace between name and `(`
  (old-IE tolerated it).
- `@import` and `-moz-binding` must be contiguous (at-keyword/property
  name) — only C0/controls tolerance.
- An unquoted `url(...)` cannot legally contain `;`: an executable
  `@import`/declaration spans from `@`/name to the first `;` outside
  quotes. Excise that span and preserve the rest of the stylesheet;
  delete the whole element only when the danger cannot be localized or
  the remainder is still dangerous.

## 5. Spec-axis checklist (every clause needs a harness case)

- executable_html_vectors: elements, on*, schemes, data:, containers (incl. foreignObject: closed, self-closing, HTML-context, unclosed-to-EOF), SVG/MathML, forms, refresh, CSS, attr-bombs — one case each.
- hygiene claims: every NAME_DENY member has a stray-close case where applicable (e.g. `keep</foreignobject>more` → stray close gone, text kept).
- preservation_fidelity: entities, tables, forms, images, formatting,
  style `color:red`, dense attrs, safe href/src/action, CRLF, UTF-8,
  BOM, comments, doctype, `<template>`, nested small-fragment deletion.
- html_parsing_irregularity: case mix, tabs, `<` in text, `< img` (space
  after `<` is text), unterminated tag at EOF, unterminated quote,
  duplicated (conflicting) attributes in both orders, `<script>` inside a
  `title="..."` value, comment/CDATA containing script-looking text,
  textarea/title/xmp content, misnesting.
- payload_obfuscation: charrefs in names and values, percent-encoding,
  C0 inside scheme, null bytes, `java script:` (preserve), CSS escapes in
  style, double-escape script close, base64 `data:text/html`, layered
  `href="java&#115;cript:"`, `ON...=` case, encoded `on&#x63;lick=`.

## 6. Hygiene rules (token-level, on the output)

- Deny-listed **StartTag or EndTag** tokens (EndTag: the stray
  `</script>` from double-escape closes) → delete span.
- Per-occurrence attribute scan inside surviving StartTag spans (same
  classifier).
- CSS fragments in style element content / style attribute occurrences.
- Token-level only: a raw regex hygiene pass cannot know quotes and will
  delete `<script>` inside a `title="..."` value or comment.
- Tripwire (evidence only, stderr): scheme patterns with
  `[\t\n\r\x0b\x0c\x00]` and `%xx` tolerance between letters; never
  deletes.

## 7. Environment and failure contract

- Vendored dependency resolved from `__file__`; empty-env + foreign-CWD
  smoke test is part of done.
- Parser absent → exit nonzero, no file modification, one stderr line.
- stderr output is evidence, not error (tripwire fires on preserved
  benign values by design).