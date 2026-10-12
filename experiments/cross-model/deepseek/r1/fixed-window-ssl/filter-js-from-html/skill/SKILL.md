---
name: filter-js-from-html
description: >-
  Remove executable JavaScript behavior from HTML files in place (scripts,
  event handlers, javascript:/vbscript:/executable data: URLs, active
  containers, SVG/MathML vectors, meta-refresh navigation, CSS
  expressions/imports, form-target attacks) while preserving every benign
  byte. The method is browser-parser span surgery: tokenize with a vendored
  real HTML5 parser to detect danger on decoded values, delete exact source
  spans from the original text (never re-serialize), then re-parse the
  output with the full treebuilder as a safety arbiter and a token-level
  hygiene pass as the substring arbiter. Use when the task family is
  "sanitize untrusted HTML with high preservation fidelity under hostile,
  malformed, or obfuscated input syntax".
---

# filter-js-from-html

## Family definition (what this skill is for)

The task family (jointly defined by `spec.yaml` + `train/v01/task.yaml`):
given an HTML file, remove *one class* of executable behavior (here:
JavaScript) while keeping the document functionally identical otherwise.
The four declared variation axes are the contract:

1. **executable_html_vectors** — every construct that can execute script:
   direct `<script>`, inline `on*` handlers, `javascript:` URLs, `data:`
   URLs that embed HTML, active containers (iframe/object/embed/applet),
   scriptable SVG/MathML, form targets, meta refresh, dangerous attributes
   beyond `on*`, and combinations that only become executable after
   parsing/normalization.
2. **preservation_fidelity** — benign structure, tables, forms, entities,
   images, formatting, dense attribute sets, mixed safe/unsafe attributes.
   Over-sanitizing is a bug.
3. **html_parsing_irregularity** — malformed tags, weird spacing, case
   variation, entity-encoded content, tabs, broken nesting, duplicated
   attributes, browser-tolerated invalid markup, fragments.
4. **payload_obfuscation** — charrefs, percent-encoding, nulls, layered
   encodings, CSS escapes, split/duplicated payloads.

The anchors of this task family are the *semantics* (v01): a CLI script
`filter.py <file>` that modifies the file in place. A family variant changes
the tables in `references/rules.md` (which vectors, which fidelity rules),
never the procedure below.

## Core architecture: span surgery with a real parser as arbiter

The procedure has seven layers. Each layer exists because the layer before
it has a known failure mode; do not skip layers.

### 1. Vendor a real HTML5 tokenizer/parser next to the script

Never rely on a runtime `pip install` persisting at grading time. Ship the
pure-Python dependency into a local directory (e.g. `_vendor/`) with
`pip install --target <dir> html5lib==1.1`, and resolve it from `__file__`:

```python
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_vendor')
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
```

**Pin the version and never use `--no-deps`.** The sanctioned-internals
contract — hardcoded token-type numbers, `HTMLTokenizer`,
`stream.position()`, the rawtext-handoff compensation — is coupled to
html5lib 1.1 exactly; an unpinned install is a future fail-closed mask
(import-time failure politely hidden by the fail-closed path).
`pip install --no-deps html5lib` leaves `six`/`webencodings` missing — the
iteration-1 fresh solver lost real time to exactly that trap. A reference
implementation may also bootstrap its own `_vendor` at import time when
absent (`subprocess` pip with the same pinned command, best effort): that
makes a fresh deployment self-sufficient, while grading-time imports never
trigger it because `_vendor` already exists.

Resolution must be relative to `__file__`, never CWD-relative or
hardcoded: the grader may run from any working directory with an empty
environment (`env -i`). If the parser is missing (and cannot be
bootstrapped), **fail closed**: refuse to sanitize, exit nonzero, do not
modify the file, with one clear stderr line. Emitting unfiltered HTML
while claiming to have filtered it is worse than refusing. (Tested
contract — see `scripts/harness.py`.)

Also hardcode the small frozen constants (html5lib 1.1 token types:
`Doctype 0, Characters 1, SpaceCharacters 2, StartTag 3, EndTag 4,
EmptyTag 5, Comment 6, ParseError 7`) so the module imports even when the
parser is absent and the fail-closed branch is reachable.

### 2. Capture exact token spans (ParseError elision)

Drive the vendored tokenizer yourself. The invariant that makes every
span-based decision sound:

> **An interval between two real-token yields is exactly that token's
> consumption.**

The tokenizer queues some parse errors and real tokens in the same state
pass; a ParseError yield consumes zero input. So capture the stream
position before the first token and after every yield, **skip ParseError
records without recording or advancing**, and append a trailing sentinel
covering any remainder (EOF-in-tag bookkeeping never drains). Verification
of the span layer (run once, keep in the harness):

> Concatenating all captured spans must reproduce the input exactly.

Positions are `(line, col)`; convert with a line-start table. The stream
normalizes `\r\n`/`\r` to `\n`, so spans are computed in normalized
coordinates and mapped back to raw bytes with a per-character index map.
When a normalized span ends right before a CRLF-derived LF, the leading
`\r` sits in the mapping gap: subtract one from the raw end so the pair is
never half-eaten.

### 3. Masked walk: restore rawtext/RCDATA semantics

The bare tokenizer lies inside rawtext/RCDATA content — in html5lib 1.1
the *treebuilder* switches the tokenizer into script/style/textarea/title
states, so a bare token stream yields real StartTag tokens for bytes that
are text. Never trust token types inside such content; compute inert
content extents yourself and mask them (skip all tokens whose span starts
inside a mask) before any classification.

- **HTML content**: `script, style, xmp, iframe, noembed, noframes,
  noscript` are rawtext; `title, textarea` are RCDATA; `plaintext` runs to
  EOF. Their content is inert text — never delete inside it (it is visible
  content), except when the whole element is deleted.
- **Foreign content** (inside an open `svg`/`math` element that has not
  hit an HTML integration point): `script`/`style` remain rawtext; every
  other rawtext/RCDATA name is an ordinary element whose children are real
  tokens (`<svg><title><b onbegin=...>` is exactly the "scriptable SVG"
  axis — the attribute must be seen and deleted). Integration points reset
  to HTML: `foreignObject`, MathML text integration points
  (`mi,mo,mn,ms,mtext`), and `<annotation-xml encoding="text/html">`.
  When in doubt, do not mask (masking is silence; silence must be earned
  by certainty of inertness).
- The close of rawtext/RCDATA content is the first `</name`
  (ASCII-case-insensitive) immediately followed by a boundary char in
  `[\t\n\f\r />]`; `</scriptx>` does not close, `</script x>` does. Track
  a small `svg`/`math` depth counter (with the integration-point resets)
  to decide the foreign context; keep it in a stack of element
  `{name, fc}` entries.
- **Script has escape states**: `<!--` switches to escaped, `<script`+
  boundary inside escaped switches to double-escaped, and inside
  double-escaped a `</script`+boundary is *text* (it does not close).
  Model the three states to find the true close. This is exactly the
  case that leaves a stray `</script>` behind; the hygiene pass (layer 6)
  removes it — do not extend the deletion greedily to the last
  `</script>`, or you delete visible text.
- Self-closing `/` is ignored for rawtext elements in HTML content
  (`<script/>alert(1)</script>` has content `alert(1)`); in foreign
  content `<script/>` genuinely self-closes and the following text is
  inert SVG text that must be preserved. Track these two decisions
  separately: "is this a foreign element" vs "does this token's `/` take
  effect".

### 4. Classify on decoded values, delete per raw occurrence

The threat classifier runs on *parsed-decoded* values (charrefs decoded,
names case-folded, nulls handled by the tokenizer) — source-level regexes
cannot see `href="java&#115;cript:..."`. Rules (see `references/rules.md`
for the full tables):

- Delete any element whose (case-folded) name is deny-listed:
  `script, iframe, frame, object, embed, applet, noscript, noembed,
  noframes, foreignobject` (script-family by rawtext extent;
  `object/applet/frame/foreignObject` by explicit end-tag pairing with a
  name stack and HTML5 in-scope list; `embed` is void → tag only;
  foreign `/*` self-closing honored; `noscript` deleted wholesale under
  scripting-on rawtext semantics).
- Delete every attribute occurrence whose local name is `on*` (any
  element, including SVG `onbegin/onend/onrepeat/onload/onactivate/
  onfocusin/onfocusout`), `srcdoc`, `style` with executable CSS, `srcset`
  containing a dangerous URL, or a URL attribute resolving to an
  executable scheme.
- **Per raw occurrence, not per DOM attribute**: the tokenizer de-dupes
  attributes first-wins (mirroring the DOM), but the raw text still holds
  both copies. Scan the start-tag span yourself, classify every
  occurrence by its own value (first occurrence from the tokenizer-decoded
  dict, later ones via `html.unescape`), and delete each dangerous one.
- Special elements: `meta http-equiv=refresh` with a dangerous `content`
  URL; SVG animation elements (`animate, set, animateTransform,
  animateMotion`) whose `attributeName` targets `on*`/`href` or whose
  `from/to/by/values` carry dangerous URLs.

Deletion spans are exactly:
- elements: `[start-tag start, computed close-tag end]` — no whitespace
  nudging outside those boundaries;
- attributes: `[separator before the name, end of value incl. quote]` —
  the only sanctioned whitespace consumption, and it lives inside a tag.

### 5. DOM re-parse as the safety arbiter

Re-parse the edited document with the full treebuilder (not the bare
tokenizer) and re-run the same classifier on the DOM. This is the
guarantee that matters: **the output is provably clean under the parser
the tests are built against** — not under every user agent ever shipped.
State that boundary in any claims.

### 6. Token-level hygiene (the substring arbiter) + escalation

Hygiene is a *second pass over tokens of the output*, never a raw-regex
scan — a raw regex doesn't know quotes and will delete a `<script>` that
sits inside a `title="..."` value or a comment. Run the same masked walk
and classifier on the output (so masks and decode cannot disagree with
the main pass), plus: any deny-listed StartTag or **EndTag** token
(`</script>` leftovers from double-escape closes). CSS fragments are
excised only from style element content and style attribute occurrences.

Escalation loop, bounded rounds, each round re-normalizing the *current*
text (offsets shift):
1. DOM dangers → targeted regex (attribute/tag occurrence), then
   line-spanning deletion of that danger's marker.
2. Hygiene spans → apply directly.
3. No progress → per-danger line sweep; then element-name line sweep.
4. Still dirty → **print a loud WARNING to stderr and return best
   effort** — a sanitizer's correct failure mode is to refuse/record,
   never to emit silently.

An evidence-only *tripwire* scan may report suspicious raw substrings
(schemes with `[\t\n\r\x0b\x0c]`/`%xx` tolerance) to stderr. **stderr
output is evidence, not error**: it also fires on preserved benign cases
like a kept `title="javascript: in docs"` value. Document this contract
so a grader asserting stderr quietness is not misled.

### 7. Byte round-trip and fail-closed

- Decode bytes losslessly (UTF-8 BOM / UTF-16 BOM / UTF-32 BOM / UTF-8,
  fallback Latin-1 which round-trips every byte), edit the string, encode
  with the same codec. CRLF, tabs, entities, and every character outside
  the deleted spans survive byte-for-byte.
- Missing parser → exit 1, no modification, one stderr line.

## Fresh-solver deployment drill (evidence: iterations 1-2 trajectories)

In the solve container the frozen package is mounted read-only at `/skill`
(2/2 iterations observed), and network is available during the solve
session. The successful deployment sequence:

```bash
cp /skill/scripts/filter.py /app/filter.py
cp /skill/scripts/harness.py /app/harness.py
pip install --quiet --target /app/_vendor 'html5lib==1.1'   # WITH deps
python3 /app/harness.py          # expect: HARNESS FAILURES: 0
cd / && env -i python3 /app/filter.py /tmp/smoke.html      # empty-env smoke
cmp /app/filter.py /skill/scripts/filter.py                # byte-identity
```

The reference implementation also self-vendors: importing filter.py without
an `_vendor` directory runs the same pinned pip install (best effort,
timeout 120s); if that fails (no network) the tool FAILS CLOSED. The
manual install is the deterministic path; the bootstrap is the safety net.
Verify before finishing: harness 0 failures, byte-identity, empty-env
smoke, idempotence.

## Definition of done (run `scripts/harness.py`)

1. **Paired-verdict agreement**: for every hostile sample, the token-layer
   deletions and the html5lib DOM classifier agree on what is dangerous;
   the final output has zero DOM dangers and zero hygiene spans.
2. **Byte identity on clean inputs**: sanitizing a document with no
   dangerous constructs must return it unchanged.
3. **Preservation probes**: benign substrings (entities, tables, forms,
   style attrs, dense attribute sets, CRLF, UTF-8) survive exactly.
4. **Idempotence**: `filter(filter(x)) == filter(x)`.
5. **CLI round-trip**: in-place edit, CRLF + BOM + entities, missing-file
   and no-arg exit codes.
6. **Fail-closed contract**: parser absent → exit nonzero, file untouched,
   message on stderr.
7. **Fresh-environment smoke**: `cd / && env -i python3 filter.py f.html`
   (empty environment, foreign CWD) cleans in place. Test this at the
   very end — it is the one failure mode a harness cannot see.
8. **Span invariant**: concatenating token spans reproduces the input.
9. **Positive-firing rule for detectors**: every report-only instrument
   shipped in the solution (tripwire, diagnostics) gets a test asserting it
   FIRES on a known input and stays silent on a clean one — a detector that
   never fires is indistinguishable from a dead one (the tripwire was
   silent-by-construction for a full cycle: its separator class lacked the
   `*` quantifier, making it a match-nothing pattern; only a boundary probe
   that demanded the ear speak exposed it). Positive tests convert silence
   from background noise into a detectable signal; stderr evidence lines
   during harness runs are the documented contract working (see the
   fire/silent set in rules.md ledger), not failures to be "cleaned up".

Every defensive branch must be exercised by a test; untested fallback
code is a lie the next invocation catches for you.

## Decisions of record (made under uncertainty — revisit only with evidence)

1. `noscript` is deleted wholesale (scripting-on rawtext semantics), not
   sanitized in place: script-disabled consumers render its children as
   live markup, and html5lib parses it scripting-off. Choose consciously
   per variant.
2. `template` children are sanitized like normal HTML (tests may
   instantiate their semantics), even though they are inert at page load.
3. CSS danger in `style` content is excised as fragments (at-rule span
   `@` → first `;` outside quotes; `expression(...)`; dangerous
   `url(...)`; the rest preserved) — fall back to whole-element deletion
   only when the danger cannot be localized.
4. `java script:alert(1)` (interior ordinary space) is preserved: browsers
   only strip tab/LF/CR/FF/VT anywhere and C0+space at the ends when
   reading a scheme; an interior space makes it a relative URL. The
   classifier and the hygiene patterns must encode exactly this table.
5. **Fail-closed**: html5lib absent → exit nonzero, input untouched. This
   is a *tested* behavior; resist any future "simplification" that turns
   it into a silent best-effort pass.
6. **Container-classification default (iteration-2 evidence)**: the
   family's "active container tags *such as* iframe, object, embed" is an
   OPEN cohort. For invisible structural elements that can host arbitrary
   HTML, default to WHOLESALE DELETION, not in-place sanitization: a
   deleted invisible container costs no visible content; a preserved one
   risks the whole container class. `foreignObject` was the canonical next
   member (hosts `<body onload>`; classic mXSS container). Iteration 1
   sanitized its children in place — browser-semantically right and
   policy-wrong: 1/4 hidden tests failed (`soup.find("foreignobject")`
   expected None). Iteration 2 deletes it wholesale; the verbatim failing
   test is a harness case. Do NOT churn the other deny-list rows "for
   safety": tests 1–3 passed under the previous policy; evidence flows
   only from the arbiter and from concrete grader feedback.
7. **Vendor pin**: html5lib==1.1 only, WITH dependencies (never
   `--no-deps`). The hardcoded token types / tokenizer internals contract
   is 1.1-coupled; an unpinned install is a future silent fail-closed
   mask. (Both traps cost the iteration-1 fresh solver real time.)
8. **Disagreement-resolution rule**: when a self-authored test expectation
   fails, the arbiter (the treebuilder's parse of the input) adjudicates
   which side is wrong — never the author's first guess. Example from
   iteration 2: `<svg><foreignObject>x</svg>y` deletes `y` — `</svg>`
   inside an open foreignObject is a scope-stop parse error, so the
   container legitimately swallows to EOF; the expectation (keep `y`),
   not the implementation, was wrong. Re-derived expectations get a
   comment on the harness case so iteration-3's solver does not "fix"
   browser-correct behavior.
9. **URL normalization rows are NAMED biases, not browser facts
   (iteration-3 taxonomy)**: per the WHATWG URL parser, only ASCII
   tab/LF/CR strip anywhere before scheme recognition (scheme alphabet
   `[A-Za-z][A-Za-z0-9+.-]*`); FF/VT anywhere and percent-in-scheme
   (`java%73cript:`) make a conformant browser see a RELATIVE, INERT URL;
   NUL never reaches the classifier (tokenizer → U+FFFD, the live
   mechanism); `str.strip()` trims Unicode whitespace beyond C0+space.
   The implementation deliberately over-deletes on all of these —
   unquote-before-check, FF/VT strip, U+FFFD strip — as safe-side bias
   for legacy engines and data: media-header variance. The html5lib
   arbiter only adjudicates parse semantics; URL normalization lies
   outside its scope, so no absence-grader ever detects over-deletion.
   The biases are enforced under test (`run_bias_units`) and recorded in
   rules.md section 2 — same status as the `java script:` preservation
   decision.

## Transferability rules (family variants)

- A variant task changes `references/rules.md`, not the procedure: which
  elements are deny-listed, which attributes are URL-bearing, which CSS
  constructs count as executable, what counts as "executable data:" —
  add/remove rows in the tables and re-run the harness with one case per
  row.
- Resolve all vendored dependencies from `__file__`; assume an empty
  environment and any CWD.
- Keep the span-capture invariant test and the paired-verdict harness in
  the package; they are the definition of done for every variant.
- The arbiter claim is bounded: output is clean under the parser the
  tests use (html5lib), which subsumes the HTML5 tokenizer/treebuilder
  semantics the seed demands — not a guarantee against every historical
  user-agent quirk (IE `expression()`, conditional comments) beyond what
  the vector tables explicitly cover.

## Handling grader feedback (standing procedure)

Each feedback event follows the same cycle that produced the iteration-2
fix: (1) read feedback/iteration-N.json; (2) reconstruct the failing test
verbatim from the failure output and run it locally with pytest exactly as
the grader does; (3) let the failure identify the policy row — change the
row in references/rules.md, the implementation, and the harness case
TOGETHER; (4) calibrate: the quoted assertion from the failure output is
evidence, your reconstruction of the other tests is a guess — log which
is which; (5) re-run everything and re-verify byte-identity of
scripts/filter.py against the graded artifact; (6) freeze.

## Reference implementation

`scripts/filter.py` is the working v01 solver that passed the full
harness; `scripts/harness.py` is the paired-verdict harness with unit
tests and the decisions record. `references/rules.md` is the decision
tables that encode the current family variation.