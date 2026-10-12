---
name: html-finance-verify
description: Find the single incorrect metric in a line-numbered HTML financial report by reconstructing its internal accounting relations. Parse every (line token, metric label, shown value) triple, recompute each derived metric (margins/ratios, subtotals, income-statement identities, per-share, YoY growth, unit conversions) from the base quantities its label names, assert exactly one displayed value violates a relation within display precision, and report that line token with the wrong value exactly as displayed.
---

# HTML Finance Verify

## When to use

A task gives an HTML financial report (earnings snapshot, income statement,
KPI sidebar, etc.) whose metrics carry **line numbers**, and states that
exactly one reported metric is wrong while the rest are internally consistent.
The deliverable is the wrong metric's `line_number,value` pair. Variants may
differ in table structure, section names, metric families, line-numbering
density, which arithmetic/ratio relation exposes the error, and the output
file/format — but the mechanism is always: *enumerate internal relations,
recompute, find the one violated value*.

## Quick runbook (fresh execution environment)

In this task runtime the skill package is mounted **read-only at `/skill`**,
with the family files at its root: `/skill/checker.py`, `/skill/SKILL.md`,
`/skill/references/...`. Run `ls /skill` first; if the package is not there,
locate the mount from the task runtime's metadata rather than scanning host
paths. Do not reimplement the checker from scratch as an ad-hoc script: its
safety rails (display-precision tolerance, exactly-one violation assertion,
root-cause resolver, duplicate-base refusal, verbatim output rules) are
load-bearing for correctness and are easy to lose in a hand-written
reimplementation. You normally do not need to read `checker.py`'s source; the
procedure below explains what it does. (Copying the checker and *adding* a
builder is a separate, sanctioned workflow — see "Extending to unseen
relation families".)

1. `task_shell`: read the variant instruction (report path, output path,
   which tokens the answer must exclude). Read the HTML only if you want to
   eyeball the structure.
2. `task_shell`, run the checker end to end:
   `python3 /skill/checker.py /app/q2_earnings_report.html --out /app/value.txt`
   — replace report/out with the paths from the instruction. **Do not pass
   `--expect` using the instruction's example output**: the example
   illustrates *format* (in v01 it happens to equal the seed's answer), not
   the variant's answer, and on mismatch the checker exits 3 with nothing
   written. `--expect` is a development-time regression pin for a value you
   already derived yourself (`references/selftest.sh` uses it exactly that
   way).
3. Interpret the exit code:
   - `0` — unique diagnosis: `ANSWER: <line>,<value>` printed and the output
     file written.
   - `2` — refused (0 or ≥2 violations, no unique root, or duplicate-base
     ambiguity); nothing written. Read the diagnostics and the
     `[note] unchecked metrics` (see cheat sheet).
   - `3` — `REGRESSION MISMATCH`: only possible when you passed `--expect`
     with a wrong pin. The printed `ANSWER:` line is still the checker's
     diagnosis, so simply re-run **without** `--expect` to write the file.
   - `1` — usage/parse error (usually a path or quoting mistake): fix the
     command; never diagnose data from an exit-1 run.
4. `task_shell`: `cat` the written file and confirm the content matches the
   instruction's format.
Optional pre-flight: `bash /skill/references/selftest.sh /skill/checker.py`
verifies the checker works in this container (all PASS).

## Core invariant (family definition)

1. Every displayed **derived** metric is a function of base quantities named by
   its own label (margins ← profit & revenue lines; subtotals ← child lines;
   growth ← the same metric in two periods; EPS ← net income / shares).
2. Base values are internally consistent; **exactly one** displayed value
   violates a relation. The wrong value is discoverable from internal
   consistency alone — never from external knowledge or by eyeballing.
3. The answer quotes the **wrong displayed value** (as shown, minus tokens the
   instruction forbids, e.g. `%`), not the corrected value, and the **line
   token** printed next to it in the report (which is NOT the HTML source line
   number, `grep -n` index, or enumerate counter).

## Procedure

### Step 0 — read the variant instruction first
Extract from the task text: report path, output path (e.g. `/app/value.txt`
but it varies), the answer format (`line_number,value`), which tokens must be
stripped (`%`, `$`, commas?), and precision expectations. Never hard-code the
seed's path/conventions in your reasoning; the checker takes `--out` as an
argument for this reason. Operationally, run the checker from `/skill` as
shown in the Quick runbook above — do not hand-write a bespoke verification
script for the report.

### Step 1 — parse every metric triple
Walk all `<table>` elements (CSS-class and section-name independent). For each
row produce `(line_token, label, shown_value)`:

- **line token**: the cell next to the metric (opaque string, echo verbatim —
  density and labeling style vary).
- **value**: parse `$`, `€`, `(`, `-`, commas, and trailing `%`; keep (a) the
  exact display string, (b) the numeric value, (c) displayed decimals, (d) the
  percent flag. Use `Decimal` for all arithmetic; strip commas for math only.
- Header-driven column roles (Line / Metric / Value / period columns) when a
  header row exists; positional fallback otherwise (first int-like cell = line,
  first text = label, numeric cells = values).
- Multi-period tables: each numeric column becomes a metric instance carrying
  its period column name (order periods chronologically via year/quarter
  tokens when present, else document order).

`checker.py` implements this as `extract_metrics()`.

### Step 2 — build relation checks from label semantics
Never from section names or CSS classes. Trigger each check by the label's
meaning (thesaurus in parentheses is the axis-1 robustness):

| Relation | Label trigger | Formula (Decimal) |
|---|---|---|
| Margin/ratio | `X margin`, `X ratio`, `X % of Y` | `100 * profit_line / revenue_line` (kind ← gross/operating/net/ebitda keywords) |
| Subtotal | `Total …` | sum of the contiguous child block above, bounded by the nearest computed line (`profit`/`income`/`margin`/`total`/…) |
| Statement identity | `Gross profit`, `Operating income`, `Net income` | `rev − cost`; `gross − total opex`; `op income ± other income/expense` (only when the referenced labels exist) |
| Per-share | `per share`, `EPS`, `Earnings per share` | `net income / shares outstanding` |
| YoY/growth | `growth`, `YoY`, `% change`, `vs`, `increase`, `decrease`, `trend`, `delta` | `100*(cur − prev)/prev`, pairing the metric's period column against the chronologically previous column of the base row (strip growth words from the label to find the base: `revenue growth` → `Revenue`); same-row adjacent-column difference as fallback |
| Unit conversion | label unit words (`(in $000s)`, `in millions`, `$M`, `thousands`…) | annotated metric = plain partner × declared factor; asymmetric (the unit-free metric is the base); partner = same semantic label, unit-free, exactly one; annotated metrics are excluded from all other base searches (`is_plain` guard) so a conversion row never reads as a duplicate base |

### Step 3 — recompute and diff with display precision
For each check: `expected = round_half_up(computed, displayed_decimals)`;
consistent iff `abs(shown − expected) <= 0.5 display_unit` (one decimal ⇒
0.05). A shown value one display step off (e.g. `60.8` vs `61.8`) is a
violation; normal display rounding is not.

### Step 4 — assert exactly one violation; never guess
- `0` violations ⇒ the relation set missed the real relation — extend the
  taxonomy (print all unchecked metrics to see what is unverifiable).
- `1` violation ⇒ the shown metric is the planted error (a wrong derivable
  root always violates its *own* check too, so roots fan to ≥2; see below).
  Write it directly — but only after the duplicate-base gate (below) passes.
- `≥2` violations ⇒ **run the root-cause resolver** (`resolve_root`): every
  violated check records the base metrics it was derived from; the true root
  is the unique base — *restricted to bases that are themselves derivable*,
  i.e. the dependent metric of some check — whose correction (override its
  numeric value with its own derived value, re-run the full check set at the
  same tolerance) makes every other check consistent again. Its own displayed
  mismatch is the answer. Emit `line,shown-wrong-value` **only when exactly
  one candidate zeroes the fan**; print `shown vs computed` for every
  candidate so the agent can adapt.
  - *Warrant:* the family guarantees exactly one planted error. Any other
    hypothesis (fixing a victim or a non-root base) leaves the true root's
    own chain violated — so the zeroing candidate is unique when the model
    and the family guarantee both hold.
  - *No unique root:* two independent errors, or a root that is an
    independent base (Revenue, Other income, a single expense line — no
    self-relation exists), yield no zeroing candidate → explicit abort
    (exit 2, nothing written). **Bounded blind spot:** a planted error in an
    independent base referenced by only one derived check can surface as a
    single violation at that derived metric (e.g. a wrong expense line shows
    up only in the subtotal check). The checker cannot auto-resolve this; the
    true root appears among the `[note] unchecked metrics` — inspect them
    when the solver's answer line is a subtotal/total.
- *Duplicate-base pairing gate:* when a label matches multiple base metrics
  (e.g. `Revenue` in a highlights table AND in the statement), `find_metric`
  records the ambiguity; the write path **refuses** to emit for any winning
  check (direct or resolved) that relied on such a base, printing
  `[warn] duplicate base candidates`. A lucky mis-pairing must never become a
  confident wrong answer. **The gate targets genuinely distinct metrics that
  share a semantic label — not scale-duplicates.** Unit-annotated rows
  (`Revenue (in $000s)`) are excluded from every non-conversion base search
  by construction (`is_plain` guard on `is_revenue`/`is_cost_of_revenue`/
  `is_gross_profit`/`is_operating_income`/`is_net_income`, margin-numerator
  and opex/other predicates): they are the *same quantity at another scale*
  and participate only in the unit-conversion relation, so their presence can
  never flip an otherwise unique diagnosis into a refusal. Per-share
  denominators search plain share counts first and fall back to annotated
  ones (`Shares (in millions)` alongside plain net income is the EPS
  convention).

Write the answer **only** after one of the emit paths above succeeds;
`checker.py` exits 2 (writes nothing) on every refusal.

### Step 5 — write the answer
`<line_token>,<shown_wrong_value>` with the wrong value **exactly as
displayed**, preserving precision (`60.8` not `60.80`; `42` not `42.0`),
stripping only the tokens the instruction forbids (typically `%`; `$` is also
stripped by the checker's `clean_value`, adjust per instruction). Example:
`210,60.8`.

## Diagnostics cheat sheet (when the checker aborts)

- `no metric rows parsed` → header/role mapping wrong; check period-column
  headers (they must be recognized as value columns, not labels).
- `found 0` violations → relation set missed the planted relation (or the
  report really is consistent). Inspect `[note] unchecked metrics` and extend
  the relation taxonomy.
- `found 0` with a unit-annotated metric in the unchecked note (e.g.
  `Revenue (in $000s)`) → the conversion check needs exactly one unit-free
  partner with the same semantic label; if both sides are annotated, or the
  unit is declared only in a subtitle (`Dollars in millions` outside the
  labels), the mechanism cannot fire — that is the documented boundary.
  Copy-and-extend or hand-verify.
- period headers that are bare years or `FY xxxx` are value columns; if a
  growth metric is reported as unchecked in a multi-period table, check the
  header row (a stray caption row can push the table into positional
  fallback, which pairs columns by document order).
- `no unique root` → the resolver could not find a zeroing base. Either the
  report carries two independent errors, or the root is an independent base
  with no self-relation (Revenue, Other income, an expense line). Inspect the
  fan and the unchecked metrics; hand-resolve if needed.
- `duplicate base candidates` → a base label matched several metrics; the
  pairing is untrustworthy. Disambiguate by label/table position or accept
  the abort. Note: unit-annotated rows never trigger this — scale-duplicates
  are excluded from base searches by construction (see Step 4).
- violation on a margin **and** its upstream identity (e.g. gross margin +
  gross profit) → the *dollar* line is the planted error, not the margin;
  the resolver emits the root's line automatically.
- violation on a subtotal → the wrong metric is one of its children or the
  subtotal itself; the resolver handles the subtotal-as-root case, while a
  wrong child is the independent-base blind spot (see Step 4).

## Extending to unseen relation families

When exit 2 reports `found 0` and the `[note] unchecked metrics` clearly
reference an uncoded relation (e.g. a subtitle-declared unit scale, or a
mixed-unit subtotal), do not hand-solve the arithmetic and do not rewrite the
checker from scratch: copy-and-extend. The mount is read-only, so
`cp /skill/checker.py /tmp/checker.py`, add one builder in `build_checks()`
(match the label semantic, locate base quantities by label predicate, compute
in `Decimal`, `add(metric, computed, formula, bases=[...])`), and run the
copy. Copying preserves every safety rail (tolerance, exactly-one assertion,
resolver, duplicate-base gate, verbatim output); starting from scratch loses
them. The exactly-one-violation assertion then protects against mis-pairing:
a wrong formula fires on correct data and the checker refuses to emit.

## Evidence and scope

- **Directly verified (v01, bundled fixtures, and synthetic variants, this
  package):** margin error in a two-table statement+KPI report (`210,60.8`,
  live v01 and `v01_minimal`); wrong subtotal with dollar-value output
  (`70,250.7`); wrong YoY growth in a two-period table (`340,10.1`); wrong
  EPS (`3,4.80`); headerless table positional fallback (`70,19.5`);
  all-consistent and two-error reports abort with exit 2 and write nothing;
  **resolver**: a single planted gross-profit dollar error (all margins
  consistent) is root-resolved to `130,521.4`; two independent errors abort
  with `no unique root`; duplicated `Revenue` labels trigger the
  duplicate-base write refusal. **unit conversion**: `Revenue (in $000s)`
  `$2,310` vs plain `Revenue` `$2.3` → `20,2,310` (shown-value verbatim,
  comma preserved); **period-header robustness**: bare-year (`2025`) and
  `FY 2025` headers parse as value columns → wrong YoY growth detected
  (`340,10.1`); **conversion composition**: a report combining v01's
  statement+KPI plus a correct `Revenue (in $000s)` row still emits the
  planted margin error `210,60.8` with no duplicate-base refusal, and the
  same report with the margin corrected and the annotated row wrong emits
  the conversion violation `215,862,000` verbatim. All pinned in
  `references/selftest.sh`.
- **Fresh-solver evaluation (iteration 1, independent session, frozen
  package):** 3/3 hidden tests passed on v01 in a single attempt, running
  `/skill/checker.py` directly; the trajectory's package-location detour and
  its near-miss plan to hand-reimplement the checker motivated the Quick
  runbook above — preserving the safety rails is what keeps the answer
  correct, not re-deriving the numbers ad hoc.
- **Exit-3 discriminating check (`--expect` is a dev pin, not a runtime
  aid):** on `subtotal_error.html` (a variant), the seed's example answer
  differs from the true answer. `python3 checker.py subtotal_error.html
  --out /tmp/x --expect 210,60.8` → exit 3, `REGRESSION MISMATCH`, no file
  written (the `ANSWER: 70,250.7` line is still printed); re-running without
  `--expect` writes `70,250.7` with exit 0. Pinned in `references/selftest.sh`
  as the `expect_exit3` rail.
- **Teacher-taught:** the cross-check-reconstruction invariant, relation
  taxonomy from spec axis 2, line-token-vs-source-line distinction, verbatim
  display output, exactly-one self-check.
- **Reasoned extrapolation (not locally exercised):** subtitle-declared
  units (`Dollars in millions` outside labels) and mixed-unit subtotals need
  a subtitle-aware builder; an error planted on the unit-free base of a
  conversion pair cannot be caught by the asymmetric conversion check (it
  surfaces as `found 0` with the annotated line consistent); headerless
  multi-period tables pair columns by document order (chronology is only
  derivable from period tokens in headers, so report them prior-first or add
  a period map); outputs whose instruction allows commas/`$` in the value
  should keep them (checker strips `%`/currency by default — read the
  instruction per run).

## Files (mounted at `/skill` in the task container)

- `checker.py` — runnable cross-check reconstructor (parse → relations →
  recompute → exactly-one/root-resolver → write).
  `python3 checker.py REPORT.html --out OUT [--expect LINE,VALUE]
  [--tol-frac 0.5]`.
- `references/v01-workthrough.md` — worked v01 solution used as the regression
  anchor (`--expect 210,60.8`).
- `references/selftest.sh` + `references/fixtures/` — hermetic regression
  harness (answers and abort rails, incl. root-resolver and duplicate-base
  cases); run after any checker change: `bash references/selftest.sh`.