---
name: html-finance-verify
description: >-
  Find the single incorrect metric in an HTML financial report (earnings/income
  statement, KPI sidebar, balance sheet, cash-flow statement) whose displayed
  values are meant to be internally consistent, and report it as
  `line_number,value` to the requested answer file (typically /app/value.txt).
  Covers dollar totals/subtotals, margins and ratios, year-over-year changes,
  per-share values, and rounded figures, using only internal consistency (no
  external market data needed).
---

# html-finance-verify

## When to use

A task gives you an **HTML financial report** (single file, usually
`/app/*.html`) containing **line-numbered metric rows**, states that **exactly
one reported metric is incorrect** (or "one value violates a cross-check"), and
asks you to find it and write `line_number,value` to a file. The wrong value is
always discoverable from **internal accounting consistency** — do not fetch
external data.

## Running the helper — do this first

The skill package is mounted **read-only at `/skill`** inside the task
container (`/skill/SKILL.md`, `/skill/scripts/`, `/skill/tests/`). Host paths
(such as `train-solvers/...`) are NOT reachable from `task_shell` — never
search for the script; just run it. **Do not read the script source** (~1400
lines); the commands below are the whole interface.

```bash
ls /app                                  # find the report file
python3 /skill/scripts/find_wrong_metric.py --html /app/<report>.html --out /app/<answer>.txt --verbose
cat /app/<answer>.txt                    # verify: exactly one line 'line_number,value'
```

Pass `--html` and `--out` explicitly from the instruction (the task.yaml lives
on the HOST, not inside `/app` — v01 uses `/app/value.txt` but variants may
change it). Check the script's `[info] report=... output=...` line. Then do a
quick manual spot-check of the arithmetic (recompute the flagged metric from
its inputs). Exit 0 + `[answer]` = correct; exit 2 = the script refuses with
evidence (ambiguous/underdetermined) — read the diagnostics and reason from
the report.

## Step 0 — read the instruction first (never assume paths)

The instruction names three things; extract them before touching any data:

1. **Report path** (usually a backticked `/app/*.html`).
2. **Answer file** (usually a backticked `/app/*.txt` — v01 uses
   `/app/value.txt`, variants may differ: `answer.txt`, `result.txt`, ...).
3. **Output format** (v01: `line_number,value`, value **as shown** without the
   percent sign; confirm decimals/negatives/`$`/`%` handling per instance).

Pass what you found to the helper script **explicitly** (`--html`, `--out`) and
check its `[info] report=... output=...` line. The task.yaml usually lives on
the *host workspace*, NOT inside `/app`, so the script cannot auto-detect from
it in evaluation — this is exactly why `--html`/`--out` must be passed on the
command line. When in doubt, default `/app/value.txt`, then re-read the file
and the instruction before finishing.

## Family invariants vs. what varies (spec.yaml axes + v01)

| Aspect | Family invariant | Expected to vary |
|---|---|---|
| Report | One HTML report; rows carry line numbers next to metric names; exactly **one** displayed metric is wrong; discoverable from internal consistency only | Table structure, section names, metric families, line-number density, which relationship exposes the error |
| Error type | The wrong cell participates in at least one relationship that fails | Totals, subtotals, margins, YoY % or absolute changes, per-share values, unit conversions, rounded figures |
| Output | Deterministic single answer, `line_number,value`, value **as displayed** (formatting stripped) | Target file, numeric precision, decimals/negatives/percent/thousands separators |

## Procedure

### 1. Parse the report (stdlib only)

- Extract every `<table>` (or `<tr>/<td>` if the document has no `<table>`
  tags) into rows of cells with `html.parser.HTMLParser` or regex; `html.unescape`
  each cell. bs4/lxml are NOT guaranteed in the task container.
- Map the header row (Line / Metric / Value / Q2 2025, Q2 2024) to line, label,
  and value columns; use layout heuristics without headers. **Fallback**: if a
  table yields no rows, rows may be single cells like `110 Revenue $842.0` —
  split them with `^(line)\s+(label)\s+(value)$`.
- Keep the **raw displayed text** of every value (needed for output).
- Read units/format notes: "Dollars in millions except percentages",
  "rounded to one decimal place", per-share/cents, "% of revenue".

### 2. Normalize numbers, canonicalize labels, resolve units

- Numbers: strip `$`, `%` (flag percentages), thousands `,`, spaces,
  parentheses → negative, unicode `−` → `-`; attached `K/M/B/T`,
  `million/...`, `x` suffixes → scale the displayed value.
- **Labels (morphological matching)**: lowercase → `&`→`and` → punctuation to
  spaces → collapse whitespace → **singularize the final token**
  (`ies`→`y`; trailing `s` not in ss/us/is, len>3). Apply the same canonical
  form to your alias list, so `Total revenues` ~ `revenue`, `Costs of Sales` ~
  `cost of sales`, `share count` ~ `shares`. Never rely on spellings you
  happened to list.
- **Unit scales (axis 2: unit conversions).** Every cell gets an effective
  value = displayed value × scale, where scale comes from ONE of four carriers
  in precedence order (they annotate the same figure; never multiply):
  1. attached suffix (already applied inside the value → scale 1);
  2. a label phrase (`Net income (in thousands)`, `(000s)`, `in millions`);
  3. a column header (`Amount ($ in thousands)`) — per-column, so `Q2 2025
     ($M)` vs `Q2 2024 ($ thousands)` both work;
  4. a prose note (`Dollars in millions except percentages`).
  Header and prose scales apply ONLY to dollar-like rows: no `%` in the raw
  value and the label not per-share/eps/ratio/margin/cent — a `Gross margin
  40.0%` row under an `($M)` header stays scale 1, and a `Diluted EPS` row is
  never scaled. The same eligibility gates the LABEL branch: an annotated
  unit phrase never scales a percentage row. Share counts FOLLOW the document
  unit (`Diluted shares 400,000` with an "in thousands" note scales like the
  statement).
  All identities are computed on **effective values**; tolerances and
  back-solved implied values convert back to displayed units for output.
  **Alias tie-break** (priority order): 1) rows with NO explicit re-annotation
  win; 2) among the rest, rows whose scale equals the document (prose) scale;
  3) rows sharing a table with the already-resolved base rows (rev, opinc,
  ...); 4) document order. This makes base-role resolution order-independent
  for unannotated-vs-annotated AND annotated-vs-annotated duplicates (`Net
  income (in millions)` statement vs `Net income (in thousands)` KPI card,
  in either table order). **Multi-row families**: EVERY matching row gets its
  own check — with `Basic EPS` and `Diluted EPS` both present, both are
  verified against net income/shares (likewise multiple EBITDA rows) — never
  only the first match.

### 3. Build the constraints (what each value should equal)

**Label-driven accounting identities** (phrase variants handled by the
canonicalization above):
- Gross profit = Revenue − Cost of revenue/COGS/cost of sales.
- Total operating expenses = Σ expense lines; Operating income = GP − OpEx
  (= Rev − COGS − OpEx).
- No tax lines: Net income = OpInc +/− Other. With tax structure:
  **Pretax = OpInc +/− Other and Net income = Pretax − Tax** (never use the
  no-tax shortcut when taxes exist).
- EBITDA = OpInc + D&A; EPS = Net income / diluted shares (×100 if cents).
- Margins = profit line / Revenue × 100 (also accept plain fractions < ~5
  without `%`); expense ratios ("S&M as % of revenue") = expense/Revenue.
- Derived KPIs: **Effective tax rate** = tax/pretax ×100; **Working capital** =
  Current assets − Current liabilities; **Book value per share** = equity/shares;
  **Revenue per share** = revenue/shares; **Debt-to-equity** = total debt/equity;
  **Current ratio** = CA/CL; **Quick ratio** = (CA − Inventory)/CL;
  Return on equity/assets = net income/equity/assets.
- Balance sheet: TA = TL + TE (and the two rearrangements).
- Cash flow: ΔCash = CFO + CFI + CFF; Ending = Beginning + ΔCash.

**Block discovery (numeric subtotal detection — axis "subtotals")** — do NOT
key only on labels starting with "total". For rows whose canonical label
suggests a summary (`total`, `subtotal`, `current`, `non-current`, `net` —
excluding net income/earnings/profit/loss/margin/sales/revenue):
- Walk up to the maximal contiguous strip of rows above (stopping at headline
  labels: Revenue, Gross profit, Operating income, Net income, other totals,
  cash-flow lines, shares...).
- **Collapse to confirmed summaries**: once a row is verified as a summary
  (its own window matched), strips below it collapse to start at the topmost
  confirmed summary — this keeps nested subtotals (Total assets = Current
  assets + PP&E) while preventing a `Total current liabilities` row placed
  under an asset block from being "matched" to Cash+AR+Inventory+Current
  assets.
- Try every contiguous window, longest first; the longest window that sums to
  the row within tolerance becomes a sum-constraint. If none matches, the
  longest strip is emitted as a *candidate* constraint **only when every row
  in it is primitive** (a confirmed summary, or a row bound by no other check
  and carrying no summary label) — this is how a wrong `Current assets`
  subtotal fails its own block check, while catch-all windows like
  `[CA, TCL, Working capital, LTD]` are pruned because they would block the
  real answer in every rebuild.
- **Matching windows are frozen from the first build**: restoration rebuilds
  keep the same verified windows for rows that matched originally (recomputing
  expectations from hypothesis values), so a wrong hypothesis cannot make a
  verified block check disappear; rows with no matching window follow the
  dynamic candidate path each rebuild (a corrected subtotal thus re-finds its
  window).

**Growth / change rows** (two-column current/prior tables):
- Percent rows: `(cur − prior)/prior × 100`. Rows **without** `%` may equally
  match the absolute difference `cur − prior` ("Revenue increase (YoY)
  $150").
- If the label names a base metric ("Revenue growth (YoY)"), only pairs from
  rows sharing a token with that label are accepted; unnamed rows fall back to
  any two-column row. Percent tolerances use only the RELATIVE error of the
  base (an absolute dollar half-unit is never added to a percent comparison).

**Duplicate metrics — same name OR different scale:** any two rows with
IDENTICAL canonical labels must agree in effective value ("Net income" in the
statement and in a summary card) — the family invariant makes this equality
safe: a consistent document cannot show two different values under the same
name, so the check never fires spuriously; only the planted error fails it.
Same-family rows additionally match when their scales differ (unit
conversions, t13). Different-name same-family same-scale pairs (`basic eps`
vs `diluted eps`, `net income` vs `net income attributable to common`) can
differ legitimately and are intentionally NOT cross-checked — those have their
own identity checks instead. Every pair's columns are scanned, so a
multi-column table with per-column scales is fully covered.

**Alias collisions:** containment matching must exclude modifier words —
`operating income` must NOT match `Other operating income`, `operating
activities` must NOT match `Other operating activities` (exclude
`other`/`non operating` in those lookups); a row that is only an input is never
allowed to be silently promoted into a base role.

### 4. Rounding-aware tolerance

One `half = 0.5 × 10^-(displayed decimals)`. Sums:
`tol = Σ half(inputs) + half(target)` (≈0.15 for two 1-decimal values, ≈1.0
for integers). Ratios: `tol ≈ half(target) + |expected| × (half(num)/num +
half(den)/den)` — **always the absolute value of the expected**: for loss
quarters with NEGATIVE margins/growth the tolerance must stay positive
(≈0.06–0.08 pp). A value is consistent if it matches **at least one**
applicable relationship within tolerance. The planted wrong value is far
outside tolerance (seed: 60.8 vs 61.8); mismatches of ~1–2× tolerance warrant
re-reading the rounding note.

### 5. Selection: uniform restoration + provenance-governed second pass

The family invariant: the wrong cell is the unique cell whose correction makes
**every** constraint pass. Do not gate candidates by "is the row a target" or
"fails every check it appears in".

1. Evaluate all checks on all columns; collect the **failed** (check, column)
   pairs.
2. Every failed check contributes **implied values** (in displayed units) to
   every cell it touches:
   - the **target**: the check's expected variants ÷ the target's scale (×100
     for %, plain ×1, EPS cents);
   - each **additive input** `i`: back-solve from the **target's displayed
     (effective) value**, `implied_eff = (target_eff − Σ other_inputs·coeff)
     / coeff_i`, then divide by the input's scale. Never solve from the
     check's expected value (it already contains the wrong input — circular);
   - the **numerator and denominator of ratio checks**: per scale `s`,
     `implied_num = target·den/s`, `implied_den = num·s/target` (this finds a
     wrong Revenue when margins are the only relations).
3. **Restoration test**: a cell is accepted iff some implied value, when
   substituted and all checks **rebuilt with the same frozen window set**
   (matching block windows are recorded only by the initial structure build;
   restorations and the strict pass never mutate them), yields zero failures.
4. **Provenance discipline.** Every check is tagged `verified` (numerically
   grounded: label identities, matched ratios/growth, block windows that
   matched) or `candidate` (a block window that NEVER matched the original
   document — emitted only from the wrong-subtotal mechanism). Whenever a
   failed check is candidate-class, run a **strict second pass** with
   candidate block checks disabled:
   - both passes accept the same unique cell → answer;
   - full pass's ONLY failures are candidate-class AND the strict pass finds
     no failed checks (subtotal-only document, e.g. wrong `Current assets` in
     a pure block layout) → accept with re-confirmation, and log the
     provenance on the answer line;
   - otherwise (strict finds the true metric while the full pass is blocked,
     or vice versa, or they disagree) → **exit 2 with both passes' accepted
     sets printed** — never answer on the strength of an unverified
     candidate check alone.
5. Exactly one accepted **row** → answer. Zero accepted → consistent (out of
   family) or a missed relationship — re-check parsing, labels, blocks,
   coverage. Several accepted → genuinely underdetermined (one equation,
   unbound components): report ambiguity with `(line, label, col, displayed,
   implied-set)` — do not guess.

**Known limitation (bounded, visible):** same-metric rows with DIFFERENT
canonical names at the SAME unit scale are not cross-checked — that is
deliberate, since those can be legitimately different figures (basic vs
diluted EPS, net income vs net income attributable to common shareholders).
The equality check is scoped to identical canonical labels and to
different-scale pairs, the two preconditions under which the family invariant
makes the relation safe. If a wrong value hides in a same-name row, the
coverage line and the verbose per-row `checks=0` markers surface it.

### 6. Write the answer

- `line_number,value` on one line (seed example `210,60.8`). Line number as
  shown next to the metric (digits only, sparse numbering preserved).
- `value` = the **incorrect displayed value** with formatting stripped: no
  `%`, `$`, commas, spaces, trailing `x`; `(x)` → `-x`; displayed decimals
  kept exactly.
- Write only that one line to the instruction's path, then re-read the file
  AND the instruction to confirm path and value.

## Helper script and tests

`scripts/find_wrong_metric.py` implements steps 1–6 with stdlib only.

```bash
python3 /skill/scripts/find_wrong_metric.py --html /app/q2_earnings_report.html --out /app/value.txt
python3 /skill/scripts/find_wrong_metric.py --html r.html --out /app/answer.txt --verbose
```

- `--task /path/task.yaml` helps only when task.yaml is readable by the
  container; always prefer explicit `--html`/`--out` from the instruction.
  The script prints `[info] report=... output=...` before solving.
- Exit 0 = answer written; exit 2 = not found / ambiguous, with per-cell
  diagnostics `(line, label, col, displayed, implied-set)` plus a coverage
  line ("cells bound by ≥1 check / total cells"). **Low coverage** with an
  empty candidate set means the relationship library missed a label shape —
  re-check canonicalization/coverage, not the instance.
- `--verbose` prints parsed rows with bound-check counts, every check
  expected-vs-displayed (PASS/FAIL), and the implied-value hypotheses.
- Regression suite: `tests/run_tests.py` (22 fixtures): wrong KPI margin (t0),
  wrong subtotal inside a block (t1), ratio-only wrong denominator (t2),
  pluralized/renamed labels (t3), wrong prior-year column (t4), wrong Total
  assets with bound components (t8), wrong effective tax rate (t9), wrong
  Working capital (t10), wrong absolute YoY dollar change (t11), single-cell
  table layout (t12), unit-scale duplicate KPI in thousand-display (t13 and
  t13b, both table orders), interrupted-subtotal layout where a correct block
  is masked and the solver must REFUSE (`t14`, exit 2, never writes),
  per-column header units with wrong YoY growth (t15), share counts following
  the document unit with wrong basic/diluted EPS (t16), negative
  margins/growth in a loss quarter (t17), IDENTICAL-NAME same-scale duplicate
  with the wrong value (t18 and t18b, both table orders), annotated-vs-
  annotated duplicate resolved by the doc-scale tie-break (t19), consistent
  control (t5), graceful ambiguity for underdetermined EPS/cash-flow shapes
  (t6/t7). Run after any change: `python3 tests/run_tests.py`.
- If the script fails on an unusual variant, run the manual procedure with its
  printed evidence: the implied sets make the ambiguity (or the missing
  relationship) visible.

## Worked seed example (v01, verified)

`Ridgeway Robotics Q2`: income statement (110–200) + KPI sidebar (210–230;
margins "as a percentage of revenue", 1 decimal). Recomputed: GP = 520.4 ✓;
OpEx = 129.7+96.8+54.1 = 280.6 ✓; OpInc = 239.8 ✓; NI = 239.8+11.2 = 251.0 ✓;
Oper. margin 28.5 ✓; Net margin 29.8 ✓; **Gross margin 520.4/842.0 = 61.8 vs
displayed 60.8 ✗** (line 210). Restoration: 61.8 fixes everything; fixing
Gross profit or Revenue leaves other checks failing. Answer: `210,60.8`.
Verified end-to-end in the iteration-1 evaluation: 3/3 tests passed, 1
attempt, using the skill's SKILL.md + scripts.

## Evidence & provenance

- **Directly verified on v01**: parsing, identities, tolerance (~0.06 pp),
  restoration, `210,60.8` output; plus the iteration-1 evaluation run (3/3).
- **Domain knowledge (accounting)**: the identity library (income statement,
  margins, ratios, balance sheet, cash flow, EPS, tax rate, working capital)
  and the conditional "NI = OpInc + Other only when no tax structure exists".
- **Reasoned extrapolation, exercised on adversarial synthetic fixtures**:
  uniform restoration selection; block discovery with confirmed-summary
  collapse and frozen matching windows (locked to the initial structure build
  per `solve()` call — no process-global leakage); candidate-window pruning;
  morphological label canonicalization; unit scales from suffix/label/header/
  prose with dollar-like-row gating, share-count doc-unit semantics, doc-scale
  and table-sharing base-role tie-breaks, and duplicate-metric checks for
  identical canonical names at any scale plus same-family different-scale
  pairs (t13/t13b/t15/t16/t18/t18b/t19); provenance-tagged checks with a
  strict second pass that refuses candidate-only answers (t14, pa_wrong_ca-
  type exception with re-confirmation); per-row EPS/EBITDA checking
  (basic+diluted); negative margins and change rows with sign-safe tolerances
  (t17); prior-year-column handling; absolute-change rows; single-cell
  layouts; coverage diagnostics; ambiguity reporting. These fixtures are the
  evidence for those claims; official non-v01 instances may still differ, in
  which case re-derive the mechanism from the document's own notes and
  re-verify with the restoration test.