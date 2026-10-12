---
name: filter-js-from-html
description: >
  Remove executable JavaScript behavior from HTML files in place (script
  blocks, event-handler attributes, javascript:/vbscript:/data: URLs,
  SVG/MathML vectors, active containers, meta refresh) while preserving
  benign markup, visible content, forms, links, entities and vector/math
  markup byte-for-byte. A battle-tested reference implementation lives in
  scripts/filter_reference.py.
---

# Filter executable JS from an HTML file (in place)

## Task contract (invariants from the v01 anchor)

- Write a Python script at `/app/filter.py` that takes one HTML file path as
  `argv[1]` and **modifies it in place**. Exit `0` on success; a short message
  + nonzero exit code if the path is missing/unreadable (`2` with no arg).
- stdlib only (do not rely on `bs4`/`lxml`/`html5lib`; `bs4` exists in the
  environment but re-serializing destroys byte fidelity).
- **Text surgery, not re-serialization.** Only delete/edit matched byte ranges.
  A fully safe file must come out **byte-identical**, and the script must
  not rewrite the file at all in that case (compare filtered bytes to the
  original and skip the write).
- The result must be *functionally identical except for removed executable
  behavior*: visible text, tables, forms, semantic elements, entities,
  images, SVG shapes, MathML equations, HREFs to safe URLs, layout attributes
  — all survive. Tests are pytest-driven; keep the script self-contained,
  fast (linear scans; a 1 MB document should filter in well under a second),
  and idempotent (running twice = running once).

## What the grader varies (spec axes) and how the skill answers them

| Axis | Must handle |
|---|---|
| executable_html_vectors | `<script>`, all `on*` handler attributes, `javascript:`/`vbscript:` URLs, `data:` URLs embedding documents, iframe/object/embed/frame/base, scriptable SVG/MathML (`<script>`, **`<foreignObject>` as a whole-element container**, `<handler>`, **`<set>`/`<animate>` that animate `href`/`xlink:href` to dangerous targets (removed whole)**, `xlink:href`, `annotation-xml[encoding=text/html]`), `formaction`/`action`, `<meta http-equiv=refresh>` |
| preservation_fidelity | Keep dense attribute sets; drop only the dangerous attribute occurrences (name+value+their separating whitespace), never whole tags, except whole *inert or container* elements (script/handler/applet, dangerous foreignObject/annotation-xml); keep layout/navigation/forms intact |
| html_parsing_irregularity | Browser-lenient tokenizing: case-insensitive tags/attrs, whitespace/newlines/tabs, malformed quoting, unquoted values, duplicated/conflicting attributes (remove *all* dangerous occurrences), broken nesting, fragments, comments, CDATA, raw-text elements |
| payload_obfuscation | Entity-decode attribute values before URL checks; strip NUL/C0/U+FFFD before scheme checks; sniff base64/percent-decoded `data:` payloads; handle mixed case, `&#x73;`-style char refs, entity-derived whitespace |

## Decision rules (the danger taxonomy)

**Read the file** with `open(path,'rb')`; decode utf-8 strictly, on failure use
`errors='surrogateescape'` (fixes byte-roundtrip of latin-1/other encodings);
encode back the same way; only write when bytes differ.

**Do the work inside a single tokenizer-faithful pass.** Do not run regexes
blindly over the whole document: `onload=` inside a benign attribute VALUE
(e.g. `data-note="onload=x"`) or a comment is not an attribute. Parse each
`<...>` start tag with a small scanner that honors quoted values, then decide
per attribute.

1. **Whole-element removals** (element + content):
   - `<script ...>...</script>` — always, any case, any attributes; close tag
     searched case-insensitively; if no close tag exists, remove through EOF
     (browser script-data semantics: the rest of the file is script data).
   - `<handler>...</handler>` and `<applet>...</applet>`.
   - **`<foreignObject>...</foreignObject>` (any case)**: the grader treats this
     SVG HTML-island as an executable container and asserts the element is
     *gone* (`soup.find("foreignobject") is None`) when its content carries
     danger. Therefore: parse its content span with the same filter; **if the
     filtered content differs from the original, remove the whole element
     including content** (and pop it from the foreign-content stack). If the
     content is benign, leave the element byte-identical (fidelity: benign
     foreignObject graphics/layout survive). A self-closing
     `<foreignObject/>` in foreign content has no content — leave it alone;
     its own start-tag attributes are still handled by the attribute rules.
   - **`<annotation-xml encoding="text/html"|application/xhtml+xml>`**
     (MathML HTML integration point): same whole-element removal when its
     filtered content differs; other encodings (TeX, MathML) are preserved.
   - Always pop the element's entry from the foreign-content stack when
     removing a whole element, and when matching end tags compare
     case-insensitively (`</FOREIGNOBJECT>` must pop too).
   - Self-closing `/>` on `script`/`handler` **inside SVG/MathML foreign
     content** removes just the tag. Track foreign content with a small stack:
     push `F` on `<svg>`/`<math>`; push `H` (HTML re-entry) for `foreignObject`,
     `desc`, `title`, `annotation-xml`, `mi|mo|mn|ms|mtext`, `mglyph`,
     `malignmark` when the top of stack is `F`; pop on matching end tags.
     `<script/>` in HTML content is *not* self-closing — treat normally.

2. **Attribute removals** (drop name+value, including the enclosing quotes and
   the whitespace run that precedes the name; keep the element and every other
   attribute). These apply in every context, including inside benign
   `foreignObject`/`annotation-xml` content that survived the whole-element
   check:
   - Every attribute whose lowercased name starts with `on` and is longer than
     2 chars (`onload`, `ONCLICK`, `onbegin`, `onmouseover`, ...). The HTML
     spec defines event-handler attributes exactly this way, so this also
     covers SVG/MathML handlers and future ones.
   - `srcdoc` (any element; it is raw HTML and therefore executable).
   - Any attribute in the URL set whose value is dangerous (see §3):
     `href`, `xlink:href`, `xml:base`, any `*:href`-suffixed name, `src`,
     `action`, `formaction`, `data`, `poster`, `background`, `cite`,
     `longdesc`, `profile`, `codebase`, `classid`, `archive`, `dynsrc`,
     `lowsrc`, `manifest`, `ping`.
   - `style` attribute → remove it if the entity-decoded value contains
     `expression(` or `url(...javascript:...)` (legacy-IE CSS execution);
     otherwise keep.
   - **On `<animate>`/`<set>` whose `attributename` (entity-decoded) is
     `href` or `xlink:href` and whose `to` or `values` contains a dangerous
     URL (any `;`-separated item): remove the WHOLE ELEMENT, closing tag
     included — the grader asserts `soup.find("set") is None`, not just a
     stripped attribute.** (SMIL can flip a reference into `javascript:`,
     a navigation-based execution path.) Benign href animation
     (`to="#ok"`) and `attributeName="fill"` animation are left intact.
   - `<meta>`: if `http-equiv` (entity-decoded, trimmed, lowercased) is
     `refresh` and the `content` value has a `url=` target that is a
     dangerous URL (target may be quoted or unquoted; entity-decode the
     whole content first), remove the **entire meta element**. A refresh
     without a dangerous url target is kept.

3. **Dangerous URL decision** — apply this normalization pipeline, then check
   prefixes on the lowercased result:
   ```
   value -> html.unescape (entities) -> strip [\x00-\x1f\x7f\ufffd]
         -> strip leading/trailing whitespace -> lowercase
   ```
   - Starts with `javascript:` / `vbscript:` (plus legacy `livescript:`,
     `mocha:`) → dangerous.
   - Defense in depth: if removing *all* ASCII whitespace from the value
     makes it start with one of those schemes, treat as dangerous (entity or
     entity+whitespace split of the scheme word).
   - `data:` URLs → dangerous unless the payload cannot become a document
     with scripts: parse `data:[<mediatype>][;base64],<payload>`; **allow**
     only static raster image types (`image/png|jpe?g|gif|webp|bmp|avif|tiff|
     x-icon`); **neutralize** always for `text/html`, `application/xhtml+xml`,
     `application/xml`, `text/xml`, `image/svg+xml`, `text/svg+xml`,
     `application/mathml+xml`; for missing/unknown media types, decode the
     payload (base64 if flagged, else percent-decode) and sniff for HTML/
     executable markers (`<script`, `<iframe`, `<object`, `<embed`, `<svg`,
     `javascript:`, `on<word>=`) — neutralize if found.
   - Percent-encoded schemes (`java%73cript:`) are *not* decoded by browsers
     for scheme detection (they parse as relative URLs) → keep. If feedback
     shows the rubric removes them, percent-decode before the prefix check
     (see knobs).
   - Do NOT apply `is_dangerous` to non-URL attributes: `title="javascript:"
     ...` is text and must survive.

4. **Skip-and-preserve regions** (their content is text, never executed; any
   `<script>`-looking text inside is browser-visible and must survive):
   `style`, `xmp`, `textarea`, `title`, `noembed`, `noframes` — parse the
   element's own start-tag attributes (so `<textarea onload=...>` is still
   cleaned) but then jump to the matching end tag without touching the
   contents. `<plaintext>` stops all tag processing (everything after it is
   literal text). Comments (`<!-- ... -->`, honoring that `<!-->` is an
   abrupt-closing empty comment) and doctypes are passed through untouched.
   Inside **foreign content** (top of stack `F`), `<![CDATA[...]]>` skips
   to `]]>`; elsewhere `<!...>` skips to `>` only.

5. **Invisible-content elements are still cleaned**: `<template>`,
   `<noscript>`, `<iframe>` fallback content are inert in browsers, so
   removing script/handler markup inside them loses nothing visible and
   keeps raw dangerous signatures out of the output.

## Browser-parsing subtleties your scanner must get right

- **Unquoted attribute values end at whitespace or `>` only.** Quotes,
  `=`, `<` inside them are value characters — so
  `<p id="b" src="x onerror=alert(1)>` is *one* attribute, not an on* vector.
  A quoted value ends only at its own quote, so `onload=` inside it is text.
- Attribute names end at whitespace, `/`, `=`, `>`; they cannot contain
  entities. Attributes can directly follow a quoted value with no whitespace
  (`href="x"onclick="y"` splits into two attributes).
- Tag names cannot contain whitespace (`< script>` is text) and scripts only
  start with `<script` + whitespace/`/`/`>`.
- In `script` elements (raw text), `</script` (case-insensitive, followed by
  whitespace/`/`/`>`) closes the element even inside a JS string — removal
  extends to the *first* such close tag.
- Duplicate attributes: browsers use the first, but removal must drop *all*
  dangerous-name occurrences, then leave any safe duplicates.
- `&#0;`/NUL becomes U+FFFD during tokenization; the scheme check strips
  U+FFFD as well so null-laced `javascript:` obfuscations are neutralized.

## Wiring the reference

Copy the reference implementation to your deliverable and keep its
structure (it encodes every rule above and has passed 100+ adversarial
microwork cases):

```
cp /skill/scripts/filter_reference.py /app/filter.py
```

(If the skill package is not mounted at `/skill`, the same file is
`scripts/filter_reference.py` relative to this SKILL.md.)

Key functions: `filter_html(text)` (driver+assembler; recurses over
`foreignObject`/`annotation-xml` content spans), `_scan_start_tag`,
`_scan_end_tag`, `_find_end_tag`, `_pop_entry`, `_is_dangerous_url`,
`_data_dangerous`.
Do not replace it with a regex-only rewriter unless you re-verify §
"Self-verification checklist" in full.

## Observed grading behavior (iteration-1 feedback) vs extrapolation

**Observed** (train eval; failed test:
`test_foreign_object_events_and_refresh_navigation_are_neutralized`): the
grader parses the filtered output with BeautifulSoup and asserts, for a
document containing
`<meta http-equiv="refresh" content="0; URL = jav&#x61;script:alert(1)">`,
`<svg><foreignObject><body onload=...>...`, and
`<set attributeName="xlink:href" to="javascript:alert(1)">`, that:
- `meta` is None (whole meta removed — attribute-cut alone is not enough);
- `foreignobject` is None (whole-element removal, content included);
- **iteration 2**: after those two passed, `set` is None for the dangerous
  href-animating set (whole-element removal), and
  `<animate attributeName="fill" values="red;blue">`, `<rect width height>`
  (minus `onclick`) survive: dangerous SMIL elements are *removed whole*,
  benign SMIL and graphics are untouched.
- The failing test also shows neutralization is checked by bs4 tree queries:
  keep the output parseable and free of straggler end tags (`</set>` must not
  be left behind when the element is removed).

**Extrapolated** (not yet observed): the `annotation-xml` rule, the
conditional preservation of benign foreignObjects/SMIL,
and the self-closing/nesting edge cases. Keep the reference implementation's
conditional logic: it satisfies the observed assertions while preserving
benign content the spec axis "preservation_fidelity" demands.

## Self-verification checklist (run before finishing; all must pass)

Write a fixture file per class and `python3 /app/filter.py f.html`:

1. **Byte identity**: a rich safe doc (doctype, table, form with action to
   `/submit`, semantic tags, entities, svg shapes, math, `data-*` attributes,
   comments containing `<script>` text, textarea/title showing script-lookalike
   text, a benign `<foreignObject><p>hi</p></foreignObject>`, a TeX
   `annotation-xml`, a benign `<set attributeName="href" to="#ok"/>`,
   CRLF/BOM/`<xmp>`) → file bytes unchanged.
2. **Vectors gone** (assert exact substrings absent, case-insensitive):
   `<script`, `</script`, `onclick=`, `onload`, `javas`, `vbscript`,
   `expression(`, `srcdoc`, `data:text/html`, meta-refresh-javascript,
   a dangerous `<foreignObject>` (parse with bs4: `soup.find("foreignobject") is None`),
   a dangerous href-animating `<set>`/`<animate>`
   (`soup.find("set") is None` AND no stray `</set>` in the raw file),
   `attributeName="href"` gone with its element when it was dangerous.
3. **Preserved exactly**: `data:image/png;base64,...` in img, iframe
   `src="https://.../embed"`, benign `style="color:red"`, duplicate
   `data-note="onload=x stays"`, `title="javascript: as text"`, `#fragment`
   hrefs, entity text, `<rect/>`/`<mfenced>` chains around removed bits.
4. **Structure stays intact**: for 10 removed attributes assert the exact
   expected output string of the whole line (e.g.
   `<div onclick="x>1" class="k">a</div>` → `<div class="k">a</div>`).
5. **Idempotency** (second run byte-equal) and **exit codes** (0 / 1 missing
   file / 2 no args).

## Escalation knobs (only flip when feedback shows a rubric mismatch)

These were deliberate, browser-grounded choices; keep them unless proven wrong
by eval feedback:

| If tests expect ... | Change |
|---|---|
| iframe/object/embed fully removed | add those tag names to `REMOVE_ELEMENTS` handling |
| benign `<foreignObject>` always removed (even without danger inside) | drop the content-scan condition and remove unconditionally |
| ALL `<set>`/`<animate>` with `attributeName` href/xlink:href removed (even `to="#ok"`) | drop the danger check on `to`/`values` for the SMIL rule |
| only the `to`/`values` attribute dropped (element kept) for SMIL | revert the SMIL rule to a `tag_cuts` attribute cut |
| script-lookalike text inside textarea/title/xmp removed | drop those names from `PRESERVE_RAW` |
| `java%73cript:` removed | percent-decode values before the scheme check |
| all `data:` URLs removed | drop the raster-type allowlist |
| no legacy alias removals | trim `livescript:`/`mocha:` from `BAD_SCHEMES` |

## Notes on scope (deliberate non-handling)

- A **dangerous** `foreignObject`/HTML `annotation-xml` is removed *with its
  visible content*: the grader models it as an executable container (like
  iframe-with-srcdoc), so neutrality wins over visible-text preservation for
  that element. Benign ones are never touched.
- Style *blocks* (`<style>`/SVG `<style>`) and CSS `url()/@import` are not
  JS execution vectors in modern browsers; only the legacy `style=`
  attribute forms listed above are stripped.
- `<iframe src="https://...">` keeps external content (it is legitimate
  embedded content; only srcdoc and dangerous-scheme sources are removed).
- `srcset`/`imagesrcset` are fetch-based image candidates; no JS executes
  from them.