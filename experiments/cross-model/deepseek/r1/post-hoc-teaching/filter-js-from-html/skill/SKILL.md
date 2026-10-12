---
name: filter-js-from-html
description: >
  Remove every script-execution vector from an HTML document in place while
  preserving all benign structure, text, layout and behavior. Covers plain
  <script>, inline event handlers, javascript:/data:/vbscript: URLs in any
  URL-bearing attribute, active containers (iframe/object/embed/frame),
  scriptable SVG and MathML (including xlink:href, SMIL animation and HTML
  integration points), form action/formaction targets, meta-refresh
  navigation, CSS expression()/url(javascript:) constructs, plus obfuscated
  and irregular syntax (entities, percent-encoding, tab/newline/NUL
  obfuscation, mixed case, malformed markup, duplicate attributes, templates,
  noscript and MathML mutation-XSS). Output is functionally identical to the
  input; only dangerous behavior is removed. Reference implementation and a
  headless-Chromium validation harness are included as assets.
---

# filter-js-from-html

Sanitize HTML by removing executable JavaScript behavior, in place, with
browser-grade parsing and maximal preservation of benign content.

## 1. Family definition (joint spec + anchor v01)

- **Interface (v01-grounded invariant):** write a Python program at
  `/app/filter.py`; it takes one HTML file as `argv[1]` and **modifies the
  file in place**. Exit 0 on success; print usage and exit 2 with no args;
  exit 3 (fail-closed) if html5lib is unavailable (input file untouched).
- **Goal:** remove executable JS behavior; special attention to SVG and
  MathML namespace-aware content ("scripts in SVG/MathML are the seed's
  emphasized vector"). Do not alter safe content any more than necessary.
  Output stays *functionally identical* (structure, visible content, forms,
  links, vector graphics, equations survive).
- **Four declared variation axes (spec.yaml)** — the skill must cover every
  member of this closure:
  1. `executable_html_vectors` — every construct that can execute script.
  2. `preservation_fidelity` — benign structure/attributes/text survive,
     including mixed safe+unsafe attributes on one element and small unsafe
     fragments inside large safe documents.
  3. `html_parsing_irregularity` — malformed/browser-tolerated markup,
     case/spacing/tab variation, entities, templates, fragments wrapped into
     full documents, duplicated/conflicting attributes, payloads whose danger
     appears only after normalization.
  4. `payload_obfuscation` — entities, percent-encoding, layered encodings,
     NUL/control characters, base64 HTML in URL attributes, fragmented
     payloads, long attribute values, CSS-like constructs.

## 2. Danger model — exhaustive vector catalog

Remove/render inert **every** item below. Do not remove anything else.

| Class | Constructs |
|---|---|
| Script elements | `<script>` in HTML, SVG or MathML namespace (inline or `src`) |
| Event handlers | any attribute whose (lowercased, prefix-stripped) name matches `^on\w+$`, on any element, any namespace (onclick, onload, onerror, onbegin, onrepeat, onpageshow, ontoggle, ...) |
| URL attributes, dangerous scheme | `href`, `src`, `action`, `formaction`, `poster`, `background`, `dynsrc`, `lowsrc`, `data` (object), `code`, `codebase`, plus foreign `xlink:href`/`{xlink}href` (matched by local name). Drop the attribute when its value has an executable scheme (below). Elements stay; attribute is removed |
| Executable schemes | `javascript:`, `vbscript:`, `mhtml:`; `data:` unless the media type is a raster image (`image/*` excluding `svg+xml`) |
| Active containers | `iframe` (dangerous `src`, dangerous `srcdoc`), `frame`, `object` (`data`), `embed` (`src`), `applet` (`code`/`codebase`) — neutralize the attribute, keep the element |
| `srcdoc` | recursively sanitize the value as HTML (it is a whole document context; entity-decoded by the parser, so entity-obfuscated `<script>` inside is caught) |
| Forms | `<form action>`, `<button formaction>`, `<input formaction>`, `<isindex action>` with executable URL |
| Meta refresh | `<meta http-equiv=refresh content="...url=...">` — REMOVE THE WHOLE `<meta>` ELEMENT when the url is executable (v01 test-verified semantics: `soup.find("meta") is None`); benign refresh metas (no url / safe url) stay untouched |
| CSS | `expression(...)`, `url(javascript:...)`, `url(vbscript:...)`, dangerous `@import "javascript:..."` in `style` attributes and `<style>` elements (comments/tabs/percent-encoding tolerated). REMOVE the whole `style` attribute and the whole `<style>` element when dangerous (v01 test-verified: `not div.has_attr("style")`); safe style attributes/elements are preserved exactly |
| Frameset family | `<frameset>` / `<frame>` (fragment context!): `frame src=javascript:` executes in Chromium (verified `top.f0`), `frameset onload=` fires on load (verified `top`). Frameset-containing fragments MUST be parsed in the frameset fragment context — a div context drops those tokens and the no-change path would return the raw executable bytes (§3) |
| SVG/MathML | `xlink:href`/`href` on `<a>`, `<image>`, `<use>`, `<feImage>`; SMIL `<animate>/<set>/<animateTransform>/<animateMotion>` with `attributeName` targeting `on*` or `href` — REMOVE THE WHOLE SMIL ELEMENT (test-verified: `find("set") is None`); benign SMIL (`attributeName=fill` etc.) is preserved exactly; `<foreignObject>` whose RAW inner HTML is dangerous (e.g. `<body onload=...>` inside) — REMOVE THE WHOLE ELEMENT (test-verified: `find("foreignobject") is None`; Chromium-verified: that vector FIRES — see §3); benign foreignObject content survives; `<annotation-xml encoding="text/html">` descendants; `<style>` inside svg/math |
| srcset | drop the whole `srcset` attribute if a candidate URL is `javascript:`/`vbscript:`/`data:text/` after normalization |
| Mutation XSS (mXSS) | `math/mtext/mglyph/style` combos and `noscript` region tricks; handled by fixpoint re-parse/re-sanitize + noscript hardening (§3) |

**Preservation rules (equally important):**
- Only the attributes/elements above are touched. `data-*`, `aria-*`,
  `id`, `class`, `title` (ordinary values), `cite`, `ping`, `manifest`,
  `xmlns*`, `alt`, `width`, `height`, `value`, etc. pass through untouched.
- `data:` raster images (`image/png`, `image/gif`, `image/jpeg`,
  `image/webp`, ...) in `img src`/`href` contexts are **kept** (verified
  inert). `data:image/svg+xml` is dropped (conservative: SVG-as-document
  can carry script; SVG-in-`<img>` is passive in Chromium but static tests
  may flag it).
- Remove dangerous URL attributes, *not* whole elements — with exceptions
  where the ELEMENT itself is the danger carrier (v01 test-verified
  semantics): `<script>`; `<meta http-equiv=refresh>` with an executable
  URL; `<style>` whose text contains executable CSS; SMIL `<set>/<animate>`
  with `attributeName` targeting `on*`/`href`; `<foreignObject>` whose raw
  inner HTML is dangerous. Everything else keeps its (neutralized) element.
- Safe structures — tables, forms, semantic HTML, entities, unicode text,
  links, images, `srcdoc` frames with benign content — survive intact.
- `data:`-on-`<a>` links to HTML/SVG documents are dropped (clicking them
  opens an executable document).
- Percent-encoded *https* URLs are kept (they are relative URLs to the
  browser; `https%3A%2F%2F...` does not navigate). Percent-encoded
  `javascript:` is still dropped (single-encoded; double-encoded
  `java%2573cript:` is not executable in any current engine and left alone —
  verify with `location.href='javascript:...'` if unsure).

## 3. Algorithm

1. **Bootstrap (fresh eval environments have NO html5lib).** `pip install
   --target=vendor html5lib` next to filter.py (filter.py inserts that dir
   into `sys.path` from `__file__`). Then verify `python3 filter.py` works
   from any CWD. If html5lib cannot be loaded the filter must fail closed
   (exit 3, file untouched) — never emit best-effort output from a weaker
   parser.
2. **Detect document vs fragment.** If the text contains `<!doctype`,
   `<html`, `<head` or `<body` (start tags) → full document (parse with
   `parse()`); otherwise fragment (parse with `parseFragment(container='div')`
   and serialize children only). This keeps fragments fragments and preserves
   full documents (including their doctype).
3. **Frameset fragments need a frameset context.** If a fragment contains a
   `<frameset` or `<frame` start tag, parse it with
   `parseFragment(container="frameset")` instead of `div`. A div context
   DROPS frameset/frame tokens, the walk then reports "no change", and the
   fixpoint keeps the raw bytes — which execute as a page (`frame
   src=javascript:` and `frameset onload=` both fire in Chromium; verified).
   The frameset context preserves structure; the walk removes the dangerous
   attributes from the surviving elements.
4. **Parse with html5lib** (HTML5 tree-construction = browser-grade error
   recovery, namespace-aware SVG/MathML, duplicate attributes resolved
   first-wins, entity decoding in values, raw-text elements handled). The
   etree builder keeps `<template>` children in the tree, so templates are
   sanitized too. html5lib parses `<noscript>` with scripting disabled, so
   its content is real markup we can sanitize.
5. **Integration-point raw-danger pass (before parsing) — with a
   TOKENIZER-FAITHFUL extent scanner.** The TREE parse can structurally lose
   dangers that the BROWSER executes: html5lib drops the inner `<body>` of
   `<foreignObject><body onload=...>` (in-body rules) but Chromium merges
   its attributes onto the real body and fires the handler (verified:
   `__xss` fires) — same for `<math><annotation-xml>...</annotation-xml>`
   with ANY encoding (verified). Therefore, on the RAW input text, find
   every `<foreignobject>`/`<annotation-xml>` block with a scanner whose
   extent rules copy the tokenizer: quoted attribute values and `<!-- -->`
   comments are OPAQUE (an end tag inside them never closes the block), a
   self-closing `/>` is honored (Chromium does self-close foreignObject;
   benign siblings after it must survive), an unclosed block extends to its
   parent terminator (`</svg>`/`</math>`) or EOF. For each span, re-parse
   the inner content as a FULL DOCUMENT and run the sanitizer walk; if it
   would change anything (danger found), remove the whole block; an
   ambiguous extent must still end in a removal decision (never silently
   skip). Benign content (text, `<p>`, MathML, clean markup) survives
   byte-for-byte. A regex block finder would be a SECOND, disagreeing
   parser — it must never be used for extent. Also mask the (benign) spans
   before the full-doc/fragment decision so `<body` appearing only inside
   them does not flip fragment inputs into full-document mode.
6. **Walk the tree, apply §2 rules:**
   - local name = tag after `}` (namespace) → `script` → remove element.
   - attribute local name = attr after `}` *and* after any `xml:`-style
     prefix (`{http://www.w3.org/1999/xlink}href` and `xlink:href` both →
     `href`); then apply on*/URL/style/srcset/attributename/srcdoc rules.
   - `meta http-equiv=refresh` with executable url → the walk returns
     "REMOVE" for the element (parent removes it).
   - `style` attribute with any dangerous CSS → remove the whole attribute;
     `<style>` element with dangerous text → remove the whole element;
     safe styles stay byte-for-byte.
   - SMIL `<set>/<animate>/<animateTransform>/<animateMotion>` with
     `attributeName` targeting `on*` or `href` → REMOVE the whole element;
     benign SMIL (`attributeName="fill"`) is preserved exactly.
6. **Serialize** with `html5lib.serializer.HTMLSerializer(omit_optional_tags=False)`.
   Full docs: serialize the `html` root. Fragments: serialize each root child.
7. **Fixpoint loop** (≤4 iterations, stop when output stops changing):
   re-parse the serialized output and re-sanitize. This is *required*, not
   optional: html5lib serializes `{xlink}href` as plain `href`, and mXSS /
   mutation-class payloads only become dangerous (or only expose their
   dangerous attributes) *after* serialization + re-parsing. The ONLY
   legitimate "no change" is a completed walk that changed nothing
   (`changed_out is None` from `_sanitize_tree`) or the idempotent
   `changed_out == cur`. **Never catch an exception into the "no change"
   sentinel**: an exception must propagate (input file untouched, non-zero
   exit) — a tool that returns the unsanitized input with exit 0 is worse
   than a crash. The tree walk is ITERATIVE (explicit stack), so deep
   nesting (1500+ levels, verified) cannot RecursionError into the
   pass-through path; `sys.setrecursionlimit(10000)` is a belt-and-braces
   budget for the remaining srcdoc recursion.
8. **srcdoc recursion is depth-capped** (`SRCDOC_MAX_DEPTH = 64`): deeper
   chains are handled conservatively by removing the srcdoc attribute
   (iframe becomes inert about:blank) instead of recursing until the stack
   dies. A 30-level chain's leaf `javascript:` anchor executes in Chromium
   (verified: fires 30 frames deep on click) and the filtered output is
   inert; a 400-level chain parses, sanitizes and caps cleanly (exit 0).
9. **Noscript hardening:** after serialization, for each `<noscript>`
   region, if its inner text contains an early `</noscript>` (before the real
   closing tag), replace every `<` in the inner region with `&lt;` (leave the real closing tag). A
   scripting-enabled browser reads noscript content as raw text and would end
   it at the first `</noscript>` — promoting attribute-value text to markup.
   Verified: the classic
   `<noscript><p title="</noscript><img src=x onerror=...>">` payload executes
   in Chromium unmodified and is inert after this hardening.
10. **Doctype + BOM preservation:** html5lib's serializer drops
   `<!DOCTYPE ...>` and the BOM; capture them before parsing and re-insert.
11. **Encoding:** read bytes; try utf-8 → cp1252 → latin-1; write utf-8.
12. **Fail closed on EVERY abort.** A parser weaker than the browser's can
   certify content the browser will execute (mXSS relies on exactly that
   gap), so a "best-effort + regex net" fallback is a security bug. If
   html5lib cannot be imported (vendored `./vendor` first, then
   site-packages), the CLI exits **3** with an actionable message. ANY other
   unexpected failure also aborts: exceptions propagate before any write
   (input file byte-untouched) and `main()` exits **4** with a clean
   message. The file is never modified on any abort.

## 4. URL normalization (obfuscation axis)

**The invariant that makes this section safe:** *the URL normalizer may
strip MORE than the browser's URL parser does — every divergence must only
add drops — but it must never strip LESS. When in doubt, simulate the exact
pipeline the attacker's runtime runs: HTML tokenizer entity-decoding → URL
parser C0/space preprocessing → scheme scan on the raw (pre-percent-decode)
string.* Violating "never strip less" is a real bypass: `&#01;javascript:...`
executes in Chromium (verified) because the URL parser trims leading C0
controls that `str.lstrip()` keeps.

`_dangerous_url_value(value)` must mirror browser URL handling before the
scheme check:

1. remove ASCII tab `\t`, LF `\n`, CR `\r`, NUL `\x00` **and** U+FFFD
   (html5lib already replaces NUL with U+FFFD per spec — without stripping
   U+FFFD, `java&#0;script:` survives! Verified bug). Superset-safe: the
   browser only removes tab/newline anywhere; removing more can only add
   drops.
2. trim **leading and trailing C0 controls (U+0000–U+001F) and ASCII space**
   with `re.compile(r"^[\x00-\x20]+|[\x00-\x20]+$")` — the URL parser's
   exact preprocessing. `str.lstrip()` is NOT equivalent: it uses
   `isspace()` and misses U+0001–U+0008 and U+000E–U+001B, which browsers
   trim (verified: every leading `&#N;javascript:` for N in 0x00–0x20
   executes in Chromium via href; the filter must drop them all).
3. percent-decode once (`urllib.parse.unquote`): catches `java%73cript:`,
   `%6A%61va...`, `javascript%3A...` — stricter than the browser (safe
   direction; the browser's scheme scan runs on the raw string, so
   percent-encoded schemes are relative URLs it will not execute — we drop
   them anyway).
4. trim leading/trailing C0/space **again** (percent-decoding can introduce
   them).
5. match `^([A-Za-z][A-Za-z0-9+.\-]*):` — case-insensitive scheme.
6. `javascript:` / `vbscript:` / `mhtml:` → dangerous.
7. `data:` → parse `[mediatype][;base64],` head; safe **only** if media type
   starts with `image/` and does not contain `svg`; everything else
   (text/html, text/plain, application/xml, svg, empty) → dangerous.

HTML-entity obfuscation needs no extra work: the parser decodes character
references in attribute *values* (`jav&#x61;script:`, `javascript&colon;`,
`&#106;avascript:`). Verified in Chromium: entity-colon and entity-scheme
hrefs execute and are stripped. Entities in attribute *names*
(`on&#101;rror=`) are NOT decoded by any current engine and are inert;
leaving them matches browser behavior.

## 5. Evidence & confidence

All statements below were verified by direct experiment in the anchor
environment (html5lib 1.1, stdlib etree, Chromium 150 headless via
Selenium) unless marked **(extrapolation)**.

- **Verified safe via 47 browser-probed cases (iteration 1) + 19 live-vector
  cases (iteration 2 corpus):** direct script tags (HTML, SVG, in-fragment,
  in-template, in-foreignObject, in annotation-xml), on* handlers (mixed
  case, newlines in value), javascript: hrefs (plain, leading-space, tab,
  mixed-case, entity-scheme, entity-colon, NUL), form action/formaction,
  iframe data:text/html (raw and base64), iframe srcdoc (incl. nested srcdoc
  and parent-access payloads), object/embed data:, frame src, svg
  onload/script, xlink:href javascript:, svg animate attributeName=href,
  body onpageshow, frameset+frame src=javascript: (fires `top.f0`),
  frameset onload (fires `top`), and both classic mXSS payloads
  (`math/mtext/mglyph/style`, `noscript` title trick). Each executable
  original fires `window.__xss` in Chromium; each filtered output is inert —
  also after `body.innerHTML` round-trip re-parses (mutation probe), link
  clicks, and form submits, with `__xss` scanned across all frames.
- **Static scans:** re-parsing every filtered output with html5lib finds zero
  `script` elements, zero `on*` attributes, zero executable-scheme URL
  attributes (with the same normalization).
- **Preservation verified:** visible text (`innerText`) and DOM element
  counts are identical original-vs-filtered for safe documents (tables,
  forms, entities, unicode, SVG, MathML, malformed markup).
- **Idempotent:** filtering the output again changes nothing.
- **Anchor-v01 eval feedback drove three semantic corrections (iteration 1
  score 2/4 → iteration 2 score 3/4 → fixed):** the v01 pytest suite
  asserted (1) `soup.find("meta") is None` for a refresh meta with an
  executable URL — whole element removed, not just its `content`
  attribute; (2) `not div.has_attr("style")` for a style attribute
  containing `url(javascript:...)` — whole attribute removed, not a
  partial scrub; and (3, iteration 2) `soup.find("foreignobject") is None`
  for `<foreignObject><body onload=...>` — the WHOLE foreignObject element
  removed. (3) turned out to be a REAL BROWSER VECTOR, not just seed
  semantics: Chromium creates the inner `<body>` (html5lib drops it per
  the tree-construction spec) and fires `onload` (verified: `__xss` fires
  for the original, filtered output inert). Fix: a RAW-input pass removes
  foreignObject blocks whose inner content is dangerous when re-parsed as
  an HTML document; benign foreignObject (`<p>caption</p>`) survives with
  its visible text (browser-verified). SMIL `<set>/<animate>` with
  dangerous `attributeName` are likewise removed wholesale; benign
  `animate attributeName="fill"` is preserved exactly (all re-verified
  against replicas of the failing tests).
- **URL-boundary matrix (added after a Teacher-taught bypass):** the first
  version of this skill used `str.lstrip()` before the scheme check, and the
  corpus+checker shared that model — so `&#01;javascript:` on an `<a href>`
  passed 47 browser-verified "green" cases and still executed in Chromium.
  The fix: `^[\x00-\x20]+|[\x00-\x20]+$` trim (the URL parser's exact
  preprocessing). Re-validated by enumerating every character U+0000–U+001F
  plus U+0020 as a leading prefix of `javascript:` in href, meta refresh,
  form action, srcdoc, and xlink:href contexts (33 cases × contexts via
  `assets/url_boundary_probe.py`): every href original fires in Chromium,
  every filtered output is inert; meta-refresh originals do not fire in
  Chromium 150 but are still neutralized (other engines/static tests).
- **Browser facts learned (Chromium 150):** MathML `<script>` and MathML
  event handlers do *not* execute (still remove them — other engines/static
  tests may differ); `javascript:` in meta refresh does not execute (still
  stripped); `javascript:` in `video poster`, `audio src`, `input
  type=image src`, `table background`, `base href`, `srcset` does not
  execute (still stripped); SMIL `animate values=javascript:` does not
  execute (still stripped); percent-encoded schemes are relative URLs
  (still stripped when single-encoded).
- **(extrapolation)** `vbscript:`/`mhtml:` are IE-era; stripped by the same
  rule without browser verification here. mXSS variants beyond
  math/mtext/mglyph and noscript are covered structurally (fixpoint +
  conservative per-attribute rules) but each new payload class should be
  re-verified with the harness in §7.
- **Deep-nesting / deep-srcdoc (Teacher-taught hole #2, verified then
  fixed):** 1500 nested `<div>`s with a `<script>` leaf previously returned
  the ORIGINAL bytes with exit 0 (the fixpoint loop aliased the walk's
  RecursionError with "no change"). Same for 400 nested `srcdoc` chains
  with a javascript: leaf. Fixed: iterative tree walk (no recursion),
  `sys.setrecursionlimit(10000)`, srcdoc depth cap of 64 (deeper chains
  drop the srcdoc attribute conservatively), exceptions PROPAGATE before
  any write, CLI exits 4 on any abort with the file byte-untouched
  (verified with an induced RuntimeError). A 30-level srcdoc chain's leaf
  `javascript:` anchor fires in Chromium 30 frames deep on click (original)
  and the filtered output is inert; the 1500-div case sanitizes with exit 0
  and preserves the nesting.
- **Parser divergence drove the foreignObject fix (iteration-3 eval):**
  html5lib and Chromium disagree on `<body>` inside foreignObject — the
  spec-correct tree parse discards it, the browser creates it and fires its
  handler. Lesson generalized: when the tree loses information the browser
  acts on (integration points, raw text, foster parenting), the check must
  run on RAW input, not only on the parsed tree. Corpus now includes
  47_foreignobject_danger (live in Chromium), 48_foreignobject_benign
  (preserved), 49_smil_danger (set removed / animate kept),
  50_fo_js_link (removed), 51_fo_comment (comment mentioning foreignObject
  untouched).
- **Extent boundary matrix (Teacher-taught hole #4 — the pre-pass is a
  second parser):** the first version of the integration-point pass located
  blocks with a regex `(.*?)</foreignobject\s*>` whose extent rules
  disagree with the tokenizer (quotes, comments, self-closing, unclosed
  blocks). The regex OVER-REMOVED benign siblings after
  `<foreignObject/>` (Chromium honors the self-closing flag) and its
  extent was wrong wherever the closer appeared inside quoted attributes or
  comments. Fixed with a tokenizer-faithful scanner
  (`_ip_extents`/`_integration_point_danger_pass`) and validated with a
  9-case boundary matrix (cases 52–60): closers in double/single-quoted
  attrs, `>` inside quoted attrs, unclosed blocks (with and without
  `</svg>`), self-closing + benign sibling preservation, closers inside
  comments, annotation-xml with application/xml / no encoding (Chromium
  fires body-onload inside annotation-xml for ANY encoding), benign
  MathML/XML preservation. All 9 originals fire in Chromium where live and
  every filtered output is inert; the benign `<circle>` after
  `<foreignObject/>` survives byte-for-byte.
- **Harness calibration (Teacher-taught hole #3):** two all-INERT-BOTH runs
  in this family's history were setup bugs (relative file paths; pairs
  built by filtering originals in place) — errors aliased as "no fire".
  The harness now fails loud: an oracle control pair
  (`zzz_control.html`, plain `<script>__xss=1</script>`) must fire or the
  run aborts (`FATAL: harness broken`); probe failures return an error
  sentinel and label cases ERROR (never INERT-BOTH); pairs are built by
  copy-then-filter so the original is never mutated; the click phase
  recurses into all frames (so deep-srcdoc and frameset vectors are
  exercised). After calibration: 40-case corpus, 21 OK / 18 INERT-BOTH /
  0 LEAK / 0 ERROR, VALID.
- **Method lessons:** (1) the corpus and the checker must not share the
  filter's mental model — enumerate the steps of the *browser's*
  parsing/normalization pipeline and emit one probe per boundary of each
  step; only the browser is authoritative about what executes. (2) Fresh
  eval environments have NO html5lib and an empty /app: the filter must
  bootstrap (`pip install --target=vendor html5lib`) or fail closed.
  (3) The v01 seed semantics remove danger carriers wholesale (meta element,
  style attribute/element) rather than partially scrubbing — follow
  test-verified removal semantics where evidence exists, and preserve
  everything else exactly. (4) Unifying invariant: **no failure mode may be
  represented by the same output as success** — exception→exit-0-with-
  original-bytes, harness-error→INERT-BOTH, and weaker-parser→best-effort
  output are all instances of the same bug.

## 6. Implementation checklist (for a new in-family task)

1. Bootstrap the environment: `pip install --target=vendor html5lib` next
   to filter.py (fresh eval containers have neither html5lib nor /app
   files); verify the script runs from any CWD.
2. Verify the interface from the task text (`argv[1]`, in-place, exit codes)
   — anchor v01 uses exactly this; changes are unlikely but check.
3. Ensure html5lib is available — it is REQUIRED, the script must fail
   closed (exit 3, file untouched) without it; vendor it next to the script.
4. Implement: full-doc/fragment detection → frameset-context for
   frameset/frame fragments → parse → tree walk (rules §2, incl. whole
   meta-element removal for dangerous refresh and whole style
   attribute/element removal; ITERATIVE walk so deep nesting cannot
   RecursionError) → serialize → fixpoint ≥2 iterations (exceptions
   propagate; never alias them with "no change") → srcdoc depth cap (~64,
   drop the attribute beyond it) → noscript hardening → doctype/BOM
   restore → in-place write.
5. Self-check with a ≥25-case corpus spanning all four spec axes (script
   tags, handlers, URL attrs, containers, SVG, MathML, meta refresh, CSS,
   preservation doc, mixed attrs, malformed, case/tabs, entities, template,
   duplicate attrs, noscript, mXSS, broken nesting, fragment, percent,
   NUL/tab, layered, data URLs, fragmented, srcset, long attrs, frameset
   fragment, frameset onload, lone frame, style element mixed, meta benign,
   DEEP NESTING (1500 divs + script leaf), DEEP SRCDOC chain, foreignObject
   dangerous (live in Chromium) + benign, SMIL dangerous + benign,
   foreignObject-in-comment, INTEGRATION-POINT EXTENT MATRIX (closers in
   quoted attrs, `>` in attrs, unclosed blocks, self-closing + benign
   sibling, closers in comments, annotation-xml any-encoding + benign),
   oracle
   control). Use `assets/make_corpus.py`; it enforces copy-then-filter
   pairing and includes the control pair.
6. Run a **URL-boundary matrix** (`assets/url_boundary_probe.py`): every
   character U+0000–U+001F + U+0020 as a leading/trailing prefix of
   `javascript:` in every URL-bearing context; every original that fires in
   the anchor browser must have an inert filtered twin.
7. If a browser is available, run the `assets/deep_check.py` harness:
   rewrite payloads to set `window.__xss`, then require
   *original fires / filtered inert* (including innerHTML round-trip, clicks,
   submits, all frames). The control pair must fire or the run ABORTS;
   probe errors label cases ERROR. Never ship a filter whose filtered
   output executes anything in the anchor browser.
8. Check preservation: `innerText` and key DOM counts identical for a safe
   document; idempotence (filter twice → same bytes).
9. Verify fail-closed really fails: hide html5lib (move the vendor dir and
   run with `python3 -S`), confirm exit 3 and that the input file is
   byte-untouched; ALSO induce a runtime failure and confirm exit 4 with
   the file byte-untouched (exceptions must never return original bytes
   with exit 0).

## 7. Validation harness (asset)

- `assets/filter.py` — the reference implementation (the file validated in
  this family: 54-case corpus (31 live-vector browser cases + 22
  inert-but-sanitized + oracle control) including the integration-point
  EXTENT matrix, a 33-character URL-boundary matrix, deep-nesting/srcdoc
  probes and static scans; requires html5lib, **fails closed with exit 3 if
  it is missing**, aborts with exit 4 on any other failure (file
  untouched); copy it to /app/filter.py, then `pip
  install --target=vendor html5lib` next to it for hermetic execution).
- `assets/make_corpus.py` — regenerates the static corpus (tests/in,
  tests/out) and the browser corpus (bcorpus + filtered twins), including
  the `zzz_control.html` oracle pair and deep-nesting / deep-srcdoc cases.
  Enforces the pairing discipline: write original → copy to the filtered
  twin → filter the COPY (a mutated original would read as trivially
  INERT).
- `assets/url_boundary_probe.py` — generates the URL-layer boundary matrix
  (C0 controls + space as prefixes of executable URLs in every URL-bearing
  context). Run it, filter each generated case, and require every original
  that fires in the browser to have an inert filtered twin.
- `assets/deep_check.py` — headless-Chromium verifier. Usage:
  `python3 deep_check.py <dir>` where the dir contains `x.html` (original)
  and `x.filtered.html` (filtered output). Payloads set a global
  `window.__xss`. FAILS LOUD: the oracle control must fire or the run
  aborts (`FATAL: harness broken`); probe errors label cases ERROR (never
  INERT-BOTH); the click phase recurses into every frame (deep-srcdoc and
  frameset vectors included). Expect `OK` (orig fires, filtered inert) for
  live vectors, `INERT-BOTH` for constructs Chromium does not execute
  (still sanitized — acceptable), and treat any LEAK/ERROR as a failed
  run.

## 8. Pitfalls (each cost real debugging time)

- **NO failure mode may be represented by the same output as success.**
  Three instances of this one bug, all fixed here: (a) an exception in the
  fixpoint loop was aliased with "no change" — the filter returned the
  fully dangerous input with exit 0 (deep nesting / deep srcdoc chains
  trigger it via RecursionError); exceptions must propagate, the walk must
  be iterative, srcdoc recursion must be depth-capped, and the CLI must
  exit non-zero with the file untouched. (b) a harness probe error was
  aliased with "no fire" — every case read INERT-BOTH; use an error
  sentinel + oracle-control abort. (c) a weaker parser emitted best-effort
  output that could execute — fail closed instead.
- **Frameset fragments are dropped by div-context parsing:** a `<frameset>`
  / `<frame>` fragment parsed with a div container yields an empty tree, the
  walk reports no change, and the raw bytes survive — but they execute as a
  page (`frame src=javascript:` fires in Chromium, `frameset onload=`
  fires). Always parse frameset-family fragments with
  `parseFragment(container="frameset")`.
- **Deep nesting / deep srcdoc must be probed, not assumed:** 1500 nested
  divs + script and 400-level srcdoc chains previously passed through
  untouched with exit 0. After the iterative-walk + depth-cap fix, a
  30-level srcdoc chain's leaf javascript: anchor still fires in Chromium
  when clicked (original) but is inert filtered — so the corpus must
  include both depths.
- **Seed/tests remove danger carriers wholesale:** refresh metas with
  executable URLs → whole `<meta>` element removed; style attribute with any
  executable CSS → whole attribute removed; `<style>` element with
  executable text → whole element removed. Partial scrubbing (keeping
  `style="background:"`) fails v01-style assertions (`find("meta") is
  None`, `not has_attr("style")`). Safe styles and benign refresh metas
  stay exactly as-is.
- **URL preprocessing must never strip LESS than the browser:** Python
  `str.lstrip()` misses U+0001–U+0008 / U+000E–U+001B that the WHATWG URL
  parser trims — `&#01;javascript:` executes. Use
  `^[\x00-\x20]+|[\x00-\x20]+$`. Every other divergence must only add
  drops (superset-safe), never lose them.
- **The corpus and the checker must not share the filter's model:** a blank
  in the normalization model reproduces as a blank in the evidence. Enumerate
  parser/URL-pipeline boundaries (see `assets/url_boundary_probe.py`) and
  probe each with a real browser.
- html5lib **drops the doctype** on serialization → restore it.
- html5lib **replaces NUL with U+FFFD** in attribute values → strip U+FFFD
  in URL checks or `java&#0;script:` survives.
- html5lib serializes `{xlink}href` as plain `href` → without the fixpoint
  loop, an SVG javascript: link survives the first pass as `href=`.
- Attribute matching must use **local names** (`}`- and `:`-stripped).
- `<noscript>` content parses as markup (html5lib scripting-off) but a
  scripting-enabled browser reads it as raw text → the title-attribute
  `</noscript>` trick is a real Chromium XSS; harden after serialization.
- mXSS payloads only materialize dangerous markup after re-serialization →
  **always** re-parse/sanitize to a fixpoint; keep the rules
  content-based (strip on* wherever they end up) rather than position-based.
- Document fragments vs full docs: `<script>` fragments must stay fragments;
  full docs must keep `<!DOCTYPE html>` (rendering mode!). Detect, don't
  guess.
- Static scanners see attribute values: after html5lib re-serialization the
  classic mXSS payload leaves a `title` value containing an embedded
  `<img src=1 onerror=...>` string. It is inert in Chromium (verified);
  decide per test family whether to also scrub such values.
- **Every raw-text pre-pass is a NEW PARSER — give it its own boundary
  matrix before any green run counts:** a regex that finds
  `<foreignobject>...` extents disagrees with the HTML tokenizer about
  quotes (an end tag inside a quoted attribute value is data), comments
  (opaque), self-closing `/>` (honored by Chromium; the old regex
  over-removed benign siblings after `<foreignObject/>`), and unclosed
  blocks (extend to the parent terminator or EOF — an unclosed block the
  regex silently skipped let `<body onload>` fire). The extent scanner
  must copy the tokenizer's rules exactly; semantics stay in the tree walk
  (parse the span as a document, remove the block iff the walk would
  change it). Probe every extent rule in the corpus (see cases 52–60).
- **annotation-xml is a second integration-point vector:** `<body onload>`
  inside `<math><annotation-xml>...` fires in Chromium for ANY encoding
  value (verified) — treat all annotation-xml blocks as candidates; benign
  MathML/XML content passes the content-based danger check and survives.
- **The tree can lose what the browser executes:** `<foreignObject>` with
  `<body onload>` — html5lib's spec-correct parse discards the inner body,
  Chromium merges its attributes onto the real body and fires (verified).
  Any construct where the parse discards information (integration points,
  raw text, foster parenting) needs a RAW-input check, not only a tree
  walk.
- **SMIL elements are scriptable SVG:** `<set>/<animate>` with
  `attributeName` targeting `on*`/`href` are removed wholesale (matching
  the seed's remove-the-carrier semantics); benign animations
  (`attributeName="fill"`) are preserved exactly.
- **Never ship a "best-effort" fallback parser:** a parser weaker than the
  browser's can certify content the browser executes (a `<script>` embedded
  in an mXSS attribute value survives bs4+regex nets). If the authoritative
  parser is unavailable, fail closed (exit 3, file untouched) — silent
  best-effort output that can execute script is the failure mode a security
  skill must not encode.
- **The validator needs calibration, not vibes:** build pairs by
  copy-then-filter (never filter the original in place); always include a
  control pair that must fire; use absolute paths for `file://` loads;
  label probe errors ERROR, and treat any ERROR/LEAK as an invalid run —
  two historically "all-green" runs of this family were harness setup bugs
  (relative paths, in-place mutation), which is exactly what the oracle
  exists to catch.
- When browser-verifying clicks: clicking safe links navigates the page and
  wipes the flag; only click dangerous-URL links, and re-check the flag
  *after* a short delay (javascript: URL evaluation is asynchronous).
- Fresh eval containers start with an empty /app and no html5lib: budget
  time for `pip install --target=vendor html5lib` (or equivalent) before
  anything else; the fail-closed exit-3 path must never be the production
  outcome during evaluation.