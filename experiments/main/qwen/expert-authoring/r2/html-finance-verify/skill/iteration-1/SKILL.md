---
name: html-finance-verify
description: >
  Verify an HTML financial earnings report by extracting line-numbered metrics,
  checking all internal arithmetic and ratio relationships, and identifying the
  single incorrect metric. Writes the result as line_number,value to the
  specified output file.
---

# HTML Financial Report Verification

## Task Overview

You are given an HTML earnings report (e.g. `/app/q2_earnings_report.html`) that
contains an income statement and a KPI sidebar. Every displayed dollar amount is
internally consistent except for **exactly one** reported metric (often a KPI
percentage) that is arithmetically wrong. Your job is to find the incorrect
metric and write its report-line number and displayed value to an output file
(default `/app/value.txt`) as `line_number,value`.

## Variation Dimensions

Reports in this family vary along three axes. The strategy below handles all of
them.

1. **Report structure & metric relationships** – table layout, section names,
   which financial statements appear (income statement, balance sheet, cash flow),
   line-number density, and which arithmetic or ratio relation exposes the error.
2. **Error type** – the wrong value may be a margin percentage, a dollar total or
   subtotal, a per-share figure, a YoY growth rate, a unit conversion, or a
   rounded figure. The error is always discoverable from **internal consistency**
   rather than external knowledge.
3. **Output format** – target file path, numeric precision, comma/whitespace
   handling, and whether the value is a percentage, decimal, negative, or uses
   thousands separators.

## Strategy

### Step 1 – Parse the HTML and extract metrics

Use Python's stdlib `html.parser` (no external dependencies needed).

Run the bundled script:

```bash
python3 skill/html-finance-verify/scripts/verify_report.py [html_file] [output_file]
```

The script:
- Parses all `<table>` elements.
- Identifies rows with a numeric line-number cell (integer 50–9999).
- Extracts the metric name and the displayed value (dollar or percentage).
- Prints every extracted metric for transparency.

### Step 2 – Check every verifiable relationship

The script tests the following standard accounting identities. Each check records
which line numbers are involved so the wrong metric can be isolated later.

**Dollar-amount cross-checks:**
| # | Relationship | Formula |
|---|---|---|
| 1 | Gross Profit | Revenue − Cost of Revenue |
| 2 | Total OpEx | Sum of component expenses (R&D, S&M, G&A, D&A, …) |
| 3 | Operating Income | Gross Profit − Total OpEx |
| 4 | Net Income | Operating Income + Other Income (− Tax) |

**Percentage / ratio checks (all relative to Revenue unless noted):**
| # | KPI | Formula |
|---|---|---|
| 5 | Gross margin | Gross Profit / Revenue × 100 |
| 6 | Operating margin | Operating Income / Revenue × 100 |
| 7 | Net margin | Net Income / Revenue × 100 |
| 8 | EBITDA margin | EBITDA / Revenue × 100 |
| 9 | Other margins | Named dollar metric / Revenue × 100 |
| 10 | EPS | Net Income / Shares Outstanding |
| 11 | YoY growth | (Current − Prior) / Prior × 100 |

Tolerances: **±0.15** for dollar amounts (rounding in millions) and **±0.15 pp**
for percentages.

### Step 3 – Isolate the single incorrect metric

- **One failure** → the `bad_line` field points directly to the wrong metric.
- **Multiple failures** → the wrong metric is the line number that appears in
  *every* failing check's involved-set (intersection). If the intersection is
  empty or ambiguous, the line flagged as `bad_line` most frequently wins.

### Step 4 – Format and write the answer

- Percentages: write the numeric value **without** the `%` sign.
- Dollar amounts: write the numeric value **without** `$`.
- Normalise trailing zeros but keep at least one decimal place (e.g. `60.8`,
  `251.0`).
- Output format: `line_number,value` on a single line, written to the required
  output file.

## Self-Verification Checklist

Before finalising, confirm:

1. **All dollar amounts cross-check.** Manually verify at least two arithmetic
   relationships (e.g. Revenue − COGS = GP, GP − OpEx = OI).
2. **All KPIs recompute.** Recalculate every displayed percentage from the
   dollar values; compare.
3. **Exactly one discrepancy.** If zero or >1 discrepancies appear, re-examine
   the parsing – a metric may have been missed or misclassified.
4. **Output matches format spec.** Check the line number is the one *shown in
   the report* (not the HTML source line). Check the value matches what is
   displayed (no extra rounding, no sign flip, no percent symbol).
5. **File written to correct path.** Verify the output file exists and contains
   exactly one line in `line_number,value` format.

## Worked Example (v01 anchor)

The v01 report has:
- Revenue $842.0M, COGS $321.6M → Gross Profit = $520.4M ✓
- R&D $129.7 + S&M $96.8 + G&A $54.1 = Total OpEx $280.6M ✓
- GP $520.4 − OpEx $280.6 = OI $239.8M ✓
- OI $239.8 + Other $11.2 = NI $251.0M ✓
- Gross margin: 520.4/842.0 × 100 = **61.8%**, but report shows **60.8%** ✗
- Operating margin: 239.8/842.0 × 100 = 28.5% ✓
- Net margin: 251.0/842.0 × 100 = 29.8% ✓

Only one discrepancy → Line 210, value 60.8. Output: `210,60.8`.

## Edge Cases

- **Parenthetical negatives**: `$(12.3)` or `-$5.0` → parsed as −12.3 / −5.0.
- **Thousands separators**: `$1,234.5` → parsed as 1234.5.
- **Missing metrics**: if a relationship cannot be tested (metric absent), the
  check is silently skipped. This is expected for simpler reports.
- **Header rows**: rows with "Line" / "Metric" / "Value" text are skipped
  because they don't contain numeric values.
- **Multiple tables**: the script processes all tables in document order;
  metrics from the income statement and KPI sidebar are merged into one set.
