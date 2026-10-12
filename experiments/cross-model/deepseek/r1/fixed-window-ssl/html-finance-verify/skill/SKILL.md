---
name: html-finance-verify
description: >
  Find the single incorrect metric in a line-numbered HTML financial report
  (earnings statements, KPI sidebars, balance-sheet/cash-flow variants) by
  checking internal consistency — sums/totals, subtotals, differences,
  margins and ratios, year-over-year changes, per-share values, unit
  conversions — then report its line label and displayed value as
  `line,value` in the task's answer file. No external financial knowledge is
  needed; the data is self-verifying. Handles stdlib-only offline containers,
  dollars/percent/thousands/parenthesized-negative formatting, and the
  rounding-precision traps that hide planted errors.
---

# html-finance-verify

## Task family (joint definition: spec.yaml + anchor v01)

- **Input**: an HTML financial report with line-numbered metrics (v01:
  `/app/q2_earnings_report.html`, income statement + KPI sidebar).
- **Guarantees (family invariants, from v01 and task determinism)**:
  1. Exactly **one** reported metric is incorrect.
  2. The wrong metric is discoverable from **internal consistency** — no
     external knowledge (no need to know the company, sector, or typical
     margins).
  3. Every *consistent* cross-check holds exactly at the report's display
     precision (otherwise the single-answer check would be ill-posed).
  4. The answer is a deterministic `line_number,value` pair.
- **Variation axes (spec.yaml — expected to change across variants)**:
  - *Report structure & metric relationships*: table layout, section names,
    metric families, line-numbering density, and which arithmetic/ratio
    relation exposes the error (totals, subtotals, differences, margins, YoY
    changes, per-share values, unit conversions, rounded figures).
  - *Error type & discoverability*: the wrong value may be a dollar total, a
    margin, a growth %, a per-share amount, etc.; always one value that
    violates a cross-check.
  - *Output format*: answer target file, numeric precision accepted,
    comma/whitespace tolerance, presence of decimals/negatives/percent
    signs/thousands separators — always a deterministic single-answer check.

## Non-negotiables learned from v01

1. **Report line label ≠ file line.** The `line_number` you emit is the
   number **printed inside the HTML** next to the metric (v01: labels
   110–230), never the `cat -n` offset (the file had only 188 lines). Parse
   the document, do not count lines.
2. **Environment is stdlib-only.** The task container is Python 3.12 with
   **no bs4 / lxml / pandas** and is likely offline. Parse with `re` +
   `html.unescape` (see `scripts/verify_report.py`); never assume bs4.
3. **Instruction examples are format decoration, not evidence.** v01's
   instruction literally showed `210,60.8` — which happened to be the true
   answer. Variants will reuse similar text over different data. The example
   documents the *format* only; every number must come from the actual
   report.
4. **The family invariant validates the checker — never the reverse.** The
   family guarantees exactly one wrong metric exists, so:
   - **Exactly 1 BAD row** at the voted precision → spot-check the expected
     value by hand (one arithmetic step), then emit.
   - **0 BAD rows** → no template matched the wrong row's actual relation.
     The task guarantees the relation exists. Look at the rows printed as
     `no template relation (uncovered)` and hand-derive each one's relation
     from its name and neighbors (e.g., a "SG&A % of revenue" row, an
     "EBITDA" row, a unit-conversion row); re-run with a corrected/added
     template. Do not just widen tolerances.
   - **≥2 BAD rows** → a template or the convention vote is wrong (bad name
     key, invented relation, mixed precisions). Fix the checker. Never emit
     a multi-row answer.

## Workflow

### 0. Gate: run the regression selftest first

```
python3 scripts/verify_report.py --selftest report.html
```

The selftest derives its scenarios from the report itself (no hardcoded
numbers — works on any in-family variant) and asserts the family invariants:

- **A** — original report: exactly 1 inconsistent row, with no precision
  AMBIGUITY and no CONFLICT on the flagged row;
- **B** — corrected copy (flagged row set to `round(expected, family_d*)`):
  0 issues. **B is the false-positive tripwire**: a row misflagged for the
  wrong reason (wrong layout, wrong precision) survives "correction" and
  fails B;
- **C** — two-bad copy (perturb a second *checked* row): ≥2 issues, so the
  emit-gate ABORTs; skipped gracefully if <2 checked rows exist;
- **D** — precision trap (expected value shown at `family_d*+1` decimals,
  e.g. `61.81` vs convention `61.8`): the same row must still be flagged;
  skipped for sum-type rows where the trap is not exerciseable.

Verdicts: **PASS** → proceed. **FAIL (A/B/C)** → the checker regressed; do
not proceed — fix the checker. **D COLLAPSED** → the family vote cannot pin
the row's convention on this report: apply the fallback oracle (report
prose like "rounded to one decimal place", or the modal decimal count of
siblings) and hand-check before emitting. The selftest also fails on
AMBIGUOUS singleton rows and prose/vote CONFLICTs — both require a human
decision from the report's own words.

**What the selftest does NOT prove:** every scenario ranks against the
checker's own computed expectation, so a template with a wrong denominator
gives a "corrected" copy consistent with a wrong model. The hand-verification
step below remains separate and non-optional.

### 1. Read the task instruction first
- Identify the **answer file** (v01: `/app/value.txt`; variants may use
  another target) and the exact format required (typically `line,value`).
- Follow the instruction's own value rules (e.g., v01: "Do not include a
  percent sign in `value`").

### 2. Extract the data (stdlib)
- Split the HTML into `<table>` blocks; within each, take `<tr>` rows with
  ≥3 cells where cell 0 is a bare integer (the line label).
- Keep `(line, name, value)` plus the **raw displayed cell text** — you need
  both the numeric value and the exact displayed digits for the answer.
- Normalize numbers: strip `$`, `,`, `%`, whitespace; `(x)` → negative;
  `—`, `n/m`, `N/A` → placeholder (skip). **Strip symbols before the
  parenthesis check**: `$(1,234.5)` is `-1234.5`. **Normalize the
  typographic minus U+2212 (`−`, also `&minus;` / `&#8722;`, which
  `html.unescape` turns into U+2212) to ASCII `-` before anything else** —
  otherwise `float('−3.2')` raises, the row becomes *invisible* (dropped,
  not even listed as uncovered). If parens carry the sign, drop a redundant
  inner `-`/`+` (`(-3.2)` and `(&minus;3.2)` are `-3.2`, not a double
  negation).
- **Encoding habit**: the output axis lists semantic features (negatives,
  percentages, thousands separators, placeholders) — for each feature
  enumerate its *encodings* and test one of each: ASCII `-`, U+2212 `−`,
  `&minus;`/`&#8722;`, `(x)`, `$(x)`, parens plus inner sign `(-x)`. The
  paren-order bug and the U+2212 bug were both found this way.
- Rows lacking a line number (line-numbering density varies) are kept as
  relation INPUTS with a synthetic negative line key (e.g. `L-10001`), so
  totals runs never silently lose components. Negative keys are parser-
  internal only: they never appear on the answer, and when a BAD row
  carries one the checker deliberately ABORTs ("no line label") — map the
  row back to the report and supply the real label by hand.

### 3. Verify every row that a name-template can explain
Compute expected values from *other* rows only:
- **Totals/subtotals**: "Total X" = sum of the contiguous run of non-total
  rows ending before it (same table). Test every possible run; the correct
  grouping is the one whose sum matches at the convention precision. If two
  runs match, the grouping is **AMBIGUOUS** — never auto-emit; hand-decide.
  **Multi-column tables (Current vs Prior)**: every numeric column of the
  resolved run is verified against the total's corresponding cell (issue
  diagnostics carry `[col1]`, the answer uses that cell's displayed
  digits). Component errors propagate — a bad component also flags its
  dependents (≥2 issues → ABORT); the ABORT prints a root-cause hint: the
  culprit is the row whose inputs are ALL consistent.
- **Difference chains** (income statement): gross profit = revenue − cost of
  revenue; operating income = gross profit − total operating expenses; net
  income = pretax − tax, or = operating income ± other income, net. Same
  per-column verification applies in multi-column tables.
- **Margins**: `<prefix> margin` = `<prefix> profit/income` ÷ revenue × 100
  (gross, operating, net, pretax, EBITDA, EBIT). In two-column KPI
  sidebars every margin cell is checked against its own column's
  profit/revenue (verified: prior gross margin error → `210,60.0`).
- **YoY/change rows** (CHECK-CREATION LAW): a check exists only when the
  layout is positively confirmed — ≥3 numeric cells `[current, prior,
  growth%]` AND a `%`-suffixed final cell; the final cell is then checked
  against `(current − prior)/|prior|×100`. Two-cell (Current/Prior columns)
  and one-cell layouts get NO check (they stay in the uncovered list), and
  a growth formula is never compared against the current-period cell.
  A template that can emit a confident BAD on a fully consistent report is
  worse than no template: the emit gate only counts 0 vs ≥2, it cannot
  catch "one wrong for the wrong reason".
- **Per-share**: EPS = net income ÷ shares outstanding; dividend/share,
  book value/share = related total ÷ shares. If the shares row's name
  contains "thousand"/"000s", its value is scaled ×1000 (verified unit
  conversion: `205,400` thousands → 205.4 M). Per-column checks apply in
  two-column layouts (verified: prior EPS error → `240,1.12`).
- **Unit conversions across tables** (not yet verified — hand-derive):
  when two tables use different units (e.g. revenues in millions vs a
  per-unit KPI in thousands), read the section footnote (v01: "Dollars in
  millions except percentages"), derive the ×/÷ factor, and check the row
  that displays the converted unit. A row no template explains must still
  participate in *some* relation (family guarantee): derive it from its
  name and neighbors and check it by hand at display precision.
- **Any row no template explains** must still participate in *some* relation
  (family guarantee): derive it from the row's name and its neighbors and
  check it by hand at display precision before concluding.

### 4. Precision convention — the critical anti-trap rule
**Never test a row at its own displayed precision.** The wrong row's
displayed form may itself be the lie: if the convention is 1 decimal and
the true gross margin is 61.805… (display 61.8), a variant can inject
`61.81`; rounding the expected value to the row's own 2 decimals would
validate it. Instead the script votes **per metric family**: 'money'
(totals/differences), 'pct' (margins/YoY ratios), 'ps' (per-share
amounts).

- **Per-family vote**: for each family, the precision `family_d*` is the
decimal count (0–6) at which the most *rows of that family* are consistent.
  Sum rows stay consistent at many precisions (money ties break to the
  modal displayed dp of the family); ratio rows pin the precision
  (v01 pct family: margins 220/230 are consistent at 1 dp only → 1 dp).
- **Prose-note oracle (advisory)**: the script parses report prose like
  "rounded to one decimal place" (context-tagged per family) to resolve
  singleton families and vote ties. A regex miss is neutral (fall back to
  the modal displayed dp), never an error. If a parsed note *disagrees with
  a unique family vote*, the run ABORTs with a CONFLICT message — a
  silently wrong precision is a false-positive generator (see T2), so the
  human decides.
- **Singleton families** (e.g. a lone per-share row): the note decides;
  without a note the modal displayed dp of all rows is used. A singleton
  that fails at `family_d*` yet matches its own displayed precision is
  **AMBIGUOUS** → the run ABORTs (exit 1) with guidance and writes nothing.
  Never treat the candidate's own dp as the pass criterion.
- A row is BAD iff `round(expected, family_d*)` ≠ its value — **digits
  compared exactly** (epsilon ~1e-7 relative only absorbs binary noise;
  round the expected side only — the reported side stays unrounded; that
  asymmetry is intentional).
- A row whose own decimal count differs from its family's is a **red flag**
  (`REDFLAG(dp!=conv)`) but never itself the pass/fail criterion.
- If the selftest reports **D COLLAPSED**, the family vote cannot pin this
  row's convention: apply the fallback oracle (prose note / modal sibling
  precision), re-check by hand, then emit.

### 5. Isolate and emit
- Exactly one BAD row at its family precision, with its inputs all
  consistent → that is the answer, provided the row is not AMBIGUOUS and
  no note/vote CONFLICT was raised (both ABORT with exit 1 and write
  nothing).
- Output format: `line,value` where `value` = the **displayed digits minus
  symbols** (`%`, `$`, commas, spaces removed; decimals and sign kept
  exactly as shown; no re-rounding, no padding). v01: shown `60.8%` → emit
  `60.8`. Negative shown `(3.2)` → `-3.2`. Percentages stay unrounded;
  YoY rows report the growth cell, per-share rows the per-share cell.
- Hand-verify the arithmetic of the flagged row once before writing.

## Environment & tooling facts (verified in v01 container)

- Python 3.12; `html.parser` present; `bs4`, `lxml`, `pandas` absent.
- Files inside `/app` are read with `task_shell` (`cat`, `sed`, …); the
  host `read` tool cannot see them (WORKSPACE_BOUNDARY) — do not waste a
  call trying.
- **The skill package is mounted read-only at `/skill` in task containers**
  (`/skill/SKILL.md`, `/skill/scripts/verify_report.py`). Run straight from
  the mount — no copy needed:
  `python3 /skill/scripts/verify_report.py --selftest /app/report.html`.
  Host workspace paths are NOT visible inside `/app` (do not try to `cp`
  from them). Only if `/skill` is absent should the script be written into
  `/app` (e.g. heredoc from the package copy); never edit the mount; delete
  stale `/app` copies after use so later runs never execute outdated code.
- `scripts/verify_report.py` implements steps 0–5 (stdlib-only):
  `python3 verify_report.py report.html answer.txt` for the task;
  `python3 verify_report.py --selftest report.html` for the step-0 gate.
  - Prints every check with expected value at its family precision
    (`@1dp[money]`, `@2dp[ps]`, …) plus the per-family vote summary.
  - Prints `REDFLAG(dp!=conv)`, `AMBIGUOUS-GROUPING`, `AMBIGUOUS: [lines]`
    (singleton precision) and `CONFLICTS: [...]` (note vs vote) diagnostics.
  - ABORTs (exit 1) unless exactly one un-ambiguous, conflict-free issue —
    treat any other verdict as a checker bug, per invariant rule 4 above.
  - `replace_raw` (used by the selftest) replaces a displayed cell only
    when the raw string occurs exactly once, else localizes by the
    line-label context — a KPI value numerically equal to a dollar figure
    elsewhere is never patched in the wrong place.
- **Package is the single source of truth**: in the authoring workspace the
  container's `/skill` mirrors the *live* host package (edits propagate
  immediately, read-only). In frozen task runs `/skill` is the packaged
  snapshot. Either way: patch the host package, then re-run from `/skill`
  (re-copy to `/app` only if you copied earlier); never end a session with
  a `/app` copy or mental model ahead of the package.

## v01 worked trace (direct evidence)

Report: Ridgeway Robotics, Q2 2025 — income statement (L110–L200) + KPI
sidebar (L210–L230), dollars in millions, margins "% of revenue, rounded to
one decimal place".

| Line | Metric | Shown | Expected | Verdict |
|------|--------|-------|----------|---------|
| 130 | Gross profit | $520.4 | 842.0 − 321.6 = 520.4 | OK |
| 170 | Total operating expenses | $280.6 | 129.7 + 96.8 + 54.1 = 280.6 | OK |
| 180 | Operating income | $239.8 | 520.4 − 280.6 = 239.8 | OK |
| 200 | Net income | $251.0 | 239.8 + 11.2 = 251.0 | OK |
| 210 | Gross margin | **60.8%** | 520.4/842.0×100 = **61.8** | **BAD** |
| 220 | Operating margin | 28.5% | 239.8/842.0×100 = 28.5 | OK |
| 230 | Net margin | 29.8% | 251.0/842.0×100 = 29.8 | OK |

Per-family vote (live v01 output): money family votes flat `{1..6 dp: 4}`
→ tie-break modal displayed dp = 1; pct family `{1 dp: 2, else 0}` → 1 dp;
prose note confirms pct = 1 dp; no conflict. Only L210 fails at 1 dp. Answer
written: `210,60.8`.

## Evidence ledger (what is proven vs extrapolated)

General staleness guard: every concrete claim in this file (vote counts,
verdict messages, exit codes, protocol steps) is an assertion about
`scripts/verify_report.py`'s actual output; after any mechanism rewrite,
re-run the battery and re-check the worked trace and this ledger — they
are the sections that read like facts but become memories fastest.

- **Directly verified on v01**: stdlib-only env; regex table/row extraction;
  symbol-stripping incl. `$`, `%`, commas, `(x)` negatives after the paren
  fix, U+2212/`&minus;`/`&#8722;` normalization, and redundant-inner-sign
  handling (`(-3.2)`, `(&minus;3.2%)` → `-3.2`); totals/difference/margin
  templates; **per-family precision vote** (money 4-flat→1 dp tie-break;
  pct 2→1 dp); prose-note oracle (pct=1, no conflict); exact digit
  comparison; BAD isolation; `line,value` output; ABORT on 0 and ≥2
  issues; the 61.81-at-2dp precision trap (still flagged); **`--selftest`
  on v01: A/B/C pass, D PASS (`61.81%` still flagged L210 at convention
  1 dp)**; T5: note-vote CONFLICT ABORTs with a human-decision message.
- **Verified on synthetic variants this iteration (two-phase protocol:
  clean → main must ABORT-0; planted → `--selftest` must PASS, watch B/D)**
  — this discipline found and killed two answer-emitting bugs:
  - YoY rows `[current, prior, growth%]` (T1): clean → 0 issues; planted
    `14.6%` → answer `240,14.6`; selftest PASS, D at family 1 dp. The old
    two-cell template had emitted `240,842.0` on a fully consistent report;
  - per-share at 2 dp with a per-share prose note (T2/T4): clean → 0
    issues (ps family votes 2 dp, no false positive); planted `1.30` →
    answer `240,1.30`; selftest PASS, D at family 2 dp. The global-vote
    checker had emitted `240,1.22` on a consistent report;
  - shares-in-thousands unit conversion (T4): `205,400` (thousands) scales
    ×1000 → EPS `1.22` checks out; planted error still isolated;
  - singleton without note (T3): fail-closed — summary prints
    `AMBIGUOUS: [240]`, main ABORTs (exit 1, no output file), selftest
    fails with "apply the oracle by hand" guidance.
- **Verified on synthetic variants this iteration (two-phase protocol)**:
  - two-column Current/Prior statements (T6): every column of totals and
    difference chains checked — clean → ABORT-0; planted prior-period net
    income (a leaf) → answer `200,213.3`, selftest PASS; planted
    prior-period opex (a component) propagates → ABORT with `L170 [col1]`
    + `L180 [col1]` and the root-cause hint, no file written;
  - two-column margin sidebar (T6m): clean → ABORT-0; planted prior gross
    margin `60.0%` → answer `210,60.0`, selftest PASS, D exerciseable at
    the ratio cell (trap `60.97%`, family 1 dp);
  - two-column per-share (T8): clean → ABORT-0; planted prior EPS `$1.12`
    → answer `240,1.12`, selftest PASS, D at family 2 dp (trap `1.023`);
  - unlabeled rows (T7): with only some statement rows labeled, clean →
    ABORT-0 (totals not spuriously flagged — the false-positive tripwire);
    planted labeled margin error → still `210,60.8` with correct dollar
    expectations; the BAD row itself unlabeled → main ABORTs "no line
    label" (synthetic key `L-20000`), selftest FAILs with the synthetic-
    key message, no output file.
- **Teacher-taught domain mechanics**: per-row precision is circular (the
  wrong row's display can be the lie); convention must come from trusted
  siblings; a template that can emit a confident BAD on a consistent report
  is worse than no template (check-creation law); the family invariant
  validates the checker (0/≥2 verdicts = checker bug); prose notes are an
  advisory oracle, not a new point of truth (conflict → human); dropped
  input rows are silent false-positive generators — keep them as synthetic
  keys or exclude them explicitly.
- **Reasoned extrapolation (not locally exercised — verify on a future
  variant)**: cross-table unit conversions (millions↔thousands across
  separate tables, per-thousand vs per-unit KPIs) — derive ×/÷ from the
  section footnote and hand-check; YoY rows in two-cell Current/Prior
  column layouts stay uncovered by design (layout not positively
  confirmed); prior-period tables as YoY inputs. Verification procedure:
  the two-phase protocol above — build a synthetic, confirm clean → main
  ABORT-0 (no false positive), planted → `--selftest` PASS with correct
  isolated answer.