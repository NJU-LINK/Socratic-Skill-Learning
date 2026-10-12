---
name: html-finance-verify
description: >
  Find the single internally inconsistent metric in a line-numbered HTML financial
  report (income statement, KPI sidebar, balance sheet, multi-period table) by
  recomputing accounting/ratio relations from the displayed values, then write the
  displayed line label and the displayed (wrong) value to the required output file
  in the exact "line_number,value" format. Covers totals/subtotals, margins, YoY
  changes, per-share values, unit conversions, and rounding tolerances.
---

# HTML Finance Verify

An HTML financial report in `/app` shows metrics with **displayed line labels**.
**Exactly one** displayed value violates internal consistency; everything else is
coherent. You must locate it and write `line_number,value` to the output file the
instruction names.

> **Environment access:** everything under `/app` is reachable **only through
> `task_shell`** (`cat`, `python3`, `grep`, ...). The `read`/`write` host tools are
> workspace-bound and fail on `/app/...` paths with `WORKSPACE_BOUNDARY` — do not
> waste calls on them.

## Invariants vs. what varies

Invariant: one wrong metric; discoverable from *internal* consistency only (no
external knowledge); the report states its units/rounding conventions; a
deterministic single-answer checker reads your output file.

Variable across variants: report filename, table layout/section names, line-label
density and format, which relation exposes the error (sum, subtotal, margin, YoY,
per-share, unit conversion, rounded figure), output file path, required precision,
and symbol-stripping rules. **Never assume the seed's paths, format, or answer.**

## Step 1 — Extract the contract from the instruction

Write down, verbatim, before computing anything:

- report file path (e.g. `/app/q2_earnings_report.html`)
- output file path (e.g. `/app/value.txt`) and exact template (e.g. `line_number,value`)
- stripping rules: which symbols to remove from `value` (e.g. "no percent sign"),
  and whether `$`/`,`/decimals/negatives stay
- **what `value` means**: in this family it is the *incorrect value as displayed*,
  NOT the corrected value. The line number is the *label printed in the report*,
  NOT the HTML source-file line number.
- the example output is illustrative formatting only. Compute independently even
  if the example looks plausible.

## Step 2 — Parse the report into (line, metric, values)

Environment has Python 3 but **no bs4/lxml** — use stdlib. Default path is the
bundled tool (synced into the task container at `/skill/scripts/`):

```
python3 /skill/scripts/report_check.py auto  <report.html>   # infer + check standard relations
python3 /skill/scripts/report_check.py parse <report.html>   # show all rows / notes / value columns
```

`auto` parses the HTML itself and checks inferred standard relations (subtotal
sums, gross-profit / operating-income / net-income identities, name-matched
margins, growth rows) — **no transcription, no authoring**. `parse` prints the
raw material: non-table notes (units like "in millions/thousands", rounding notes
that define your tolerances) and one row per metric with displayed line label,
name, and value columns. **Never retype displayed values into Python by hand —
parsing the file eliminates transcription slips, which look exactly like planted
errors.**

Numbers are normalized for `$`, `€`, commas, `%`, `(parens)` negatives, unicode
minus; `—`/`-` are treated as missing. If `/skill/scripts/` is not mounted, copy
the script from the skill package's `scripts/` directory or fall back to a
`python3` heredoc using `html.parser`.

Sanity-check the parse: row count and a couple of spot values against
`grep -n '<td' <report.html>`. If parsing looks off (nested tables, odd markup),
read the `<table>` blocks directly; report line labels are usually in a dedicated
cell (e.g. `<td class="line">` or a row-leading `<th>`), never the HTML file's own
line numbers.

## Step 3 — Enumerate every applicable relation

Build the check list from the metric names actually present. Common identities:

| Relation | Formula |
|---|---|
| Gross profit | Revenue − Cost of revenue |
| Total / subtotal rows | sum of the item rows since the previous subtotal in that section |
| Operating income | Gross profit − Total operating expenses |
| Pretax income | Operating income + Other income, net (or − interest) |
| Net income | Pretax − Tax (check Tax = Pretax × effective rate if a rate is shown) |
| Margins (gross/operating/net) | corresponding profit ÷ Revenue × 100 |
| YoY / growth % | (current − prior) ÷ prior × 100 (use the prior-period column) |
| Per-share (EPS, book value/share) | numerator ÷ share count — watch **unit conversion**: statement in millions vs per-share in dollars |
| Balance sheet | Assets = Liabilities + Equity; section totals = component sums |
| Segment/geography tables | segments sum to consolidated total |

Rules:
- Every "Total/Subtotal/Net/Gross/ margin / growth / per share / change" row is a
  derived value → it has a checkable relation.
- Also check the base rows against *each other* when names imply it (Revenue −
  COGS = Gross profit checks all three at once).
- Use the report's stated units. If sections use different units ("dollars in
  millions", "per share in dollars"), convert before comparing.
- `auto` already covers subtotal sums, the gross-profit / operating-income /
  net-income chain, name-matched margins, and growth rows. You own the rest:
  per-share, unit conversions, balance-sheet identities, segment sums, and any
  variant-specific relation implied by the metric names.

## Step 4 — Pinpoint the single wrong metric (voting, not first-failure)

**Never finalize a verdict on mental arithmetic or hand-transcribed numbers.**
Run the relations against the parsed file:

1. First pass — `auto` (already run in Step 2): audit its printed inferred
   relations. One failing relation cluster with a unique intersection line is a
   strong candidate.
2. Confirm — re-express the decisive relations (plus any auto missed: per-share,
   unit conversions, cross-table identities) as explicit `check` expressions:

```
python3 /skill/scripts/report_check.py check <report.html> \
  "@130 = @110 - @120" \
  "@170 = @140 + @150 + @160" \
  "@210 = round(@130 / @110 * 100, 1)" ...
```

Tolerances are automatic (default tol = half a unit of the smallest displayed
decimal place, matching the report's rounding note).

`@N` = value of the row with displayed label N (first value column); `@N#k` =
value column k for multi-period tables; `round(x, 1)` mirrors the stated rounding.

Decision rules:

1. **The culprit is the line that appears in failing relations and whose
   co-members pass their other relations.** A failed relation `@170 = @140+@150+@160`
   alone cannot tell which of the four is wrong. Confirm by checking the other
   relations each member participates in: the wrong value fails (nearly) all of
   its relations; correct values pass theirs elsewhere. The wrong row can be a
   dollar statement row (then several derived rows/KPIs disagree with it) or a
   derived KPI/percentage — the voting rule is identical either way.
2. With exactly one planted error, properly enumerated relations yield a unique
   answer: exactly one line with FAILs whose removal makes every relation pass.
   The tool's summary ("in N FAIL / M PASS relations", intersection of failing
   relations) computes this for you.
3. If several lines tie (each in only one failing relation), your relation set is
   too sparse — add more relations involving those lines (other totals, margins,
   prior-period columns, cross-section identities) until the vote is unique. The
   family guarantees the error is discoverable, so a unique answer exists once
   every applicable relation is checked.
4. A FAIL within rounding tolerance is a PASS. A FAIL far beyond tolerance
   (digit transposition like 58.3 vs 53.8, wrong sign, swapped rows, off-by-1000×
   unit error) is the planted error — but you still report the **displayed** value.
5. Cross-check the verdict by recomputing what the value *should* be; a plausible
   financial figure (vs. an absurd one) confirms the location.

## Step 5 — Write and verify the output

```bash
# inside task_shell — example shape only, use YOUR flagged line/value:
printf '%s\n' "LINE,VALUE" > <output_file>   # e.g. printf '345,12.34\n' > /app/value.txt
cat <output_file>                             # verify exact bytes
```

- `VALUE` = the incorrect number **exactly as displayed**, minus only the symbols
  the instruction says to strip (e.g. if told to drop `%`, write `60.8` for a
  displayed `60.8%` — not the recomputed value, not re-padded digits). Preserve
  decimals, sign, and digit count as shown.
- `LINE` = the displayed label string, exactly (no padding/spaces).
- Single line, no extra words, no trailing spaces. Verify with `cat` (and
  `od -c | head` if the checker is strict).
- Final sanity: the file exists at the exact path from the instruction, and the
  line/value pair you wrote is the one your relation analysis flagged.

## Pitfalls

- Writing the *corrected* value instead of the displayed wrong one.
- Using the HTML source line number instead of the report's printed line label.
- Treating the instruction's example output as the answer.
- Flagging the first failing relation's left-hand side without leave-one-out
  voting — the wrong value can be on either side of a failed identity.
- Finalizing on mental arithmetic; always re-run the decisive relations in Python.
- Hand-transcribing displayed values into a script — parse the HTML instead; one
  transcription typo creates a phantom error or hides the real one.
- Trying to `read` `/app/...` with host file tools — use `task_shell` for `/app`.
- Ignoring the rounding note: compare ratios with `round(..., d)` or half-ULP
  tolerance, never exact equality on floats.
- Mixing units (millions vs thousands vs per-share dollars) — read the notes first.
- Letting `(1,234)` stay positive, or keeping `%`/`,` in the output when the
  instruction says strip them.
- Assuming seed paths/format: re-read the instruction's paths and template for
  every variant.
