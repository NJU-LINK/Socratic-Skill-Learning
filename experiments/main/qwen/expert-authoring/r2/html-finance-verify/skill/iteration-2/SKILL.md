---
name: html-finance-verify
description: >
  Verify an HTML financial earnings report by extracting line-numbered metrics,
  checking all internal arithmetic and ratio relationships, and identifying the
  single incorrect metric. Writes the result as line_number,value to the
  specified output file.
---

# HTML Financial Report Verification

## Task Summary

An HTML earnings report contains line-numbered financial metrics (dollar amounts
and percentage KPIs). Exactly **one** metric is arithmetically wrong. Your job:
find it and write `line_number,value` to the output file.

## Execution Plan

1. Read `task.yaml` for the HTML file path, output file path, and format rules.
2. Read the HTML report file.
3. **Write the verifier script** to `/tmp/verify.py` using a heredoc.
4. Run `python3 /tmp/verify.py <html_file> <output_file>`.
5. Verify the output file.

> **IMPORTANT**: Skill resource files under `scripts/` are readable via the
> `read` tool but are **NOT directly executable** from `task_shell`. You must
> create the script in `/tmp/` as shown in Step 3.

## Creating the Verifier Script

### Option A: Read and copy from skill resource

Read `scripts/verify_report.py` with the `read` tool, then write its full
content to `/tmp/verify.py` using `task_shell`:

```bash
cat > /tmp/verify.py << 'PYEOF'
... paste the script content here ...
PYEOF
python3 /tmp/verify.py /app/<report>.html /app/value.txt
```

### Option B: Manual calculation (for simple reports)

If the report has fewer than ~15 metrics, you can verify manually:
1. Extract all metrics (line numbers, names, values).
2. Check every arithmetic relationship (see table below).
3. Recompute every percentage from the dollar values.
4. Find the single discrepancy.

## Verification Relationships

The script checks these identities. Each check records all line numbers
involved (including upstream dollar values for percentage KPIs).

**Dollar cross-checks:**

| # | Check | Formula |
|---|-------|---------|
| 1 | Gross Profit | Revenue − COGS |
| 2 | Total OpEx | Σ components (R&D, S&M, G&A, D&A…) |
| 3 | Operating Income | Gross Profit − Total OpEx |
| 4 | Net Income | OI + Other Income (− Tax) |

**Percentage/ratio checks (denominator = Revenue unless noted):**

| # | KPI | Formula | Upstream deps |
|---|-----|---------|---------------|
| 5 | Gross margin | GP / Rev × 100 | GP, Rev |
| 6 | Operating margin | OI / Rev × 100 | OI, Rev |
| 7 | Net margin | NI / Rev × 100 | NI, Rev |
| 8 | EBITDA margin | EBITDA / Rev × 100 | EBITDA, Rev |
| 9 | Other margins | X_dollar / Rev × 100 | X, Rev |
| 10 | EPS | NI / Shares | NI, Shares |
| 11 | YoY growth | (Cur − Prior) / Prior × 100 | Cur, Prior |

**Tolerances**: ±0.15 for dollars, ±0.15 pp for percentages.

## Error Isolation Logic

1. **One failure** → the `bad_line` directly identifies the wrong metric.
2. **Multiple failures** → the wrong line is in the **intersection** of all
   failures' involved-line sets (the line that touches every failure).
   - When a KPI percentage is wrong, its check's inv set includes the KPI
     line AND its upstream dollar-value lines, so the intersection correctly
     identifies the KPI when it's the root cause.
   - When a dollar amount is wrong, it may cascade: e.g. wrong OI makes the
     OI check fail, but downstream checks (NI = OI + Other) may pass because
     they use the *reported* (wrong) OI. Typically only one check fails.
3. **Ambiguous intersection** → prefer the candidate with the **fewest
   passing-check participations** (least independent evidence of correctness).

## Output Format Rules

Read task.yaml carefully for these variant-sensitive details:

- **line_number**: the integer shown *in the report* next to the metric (the
  "Line" column value), NOT the HTML source line number.
- **value**: the incorrect numeric value *as displayed* in the report.
  - Percentages → numeric only, **no `%` sign**.
  - Dollar amounts → numeric only, **no `$` sign**.
  - Preserve the precision shown (e.g. `60.8` not `60.80`).
  - Normalise trailing zeros but keep ≥1 decimal (e.g. `251.0`).
- **Target file**: default `/app/value.txt`, but task.yaml may differ.

## Self-Verification Checklist

Before finishing, confirm:

1. ✅ Every dollar cross-check was tested (at least Rev−COGS=GP and GP−OpEx=OI).
2. ✅ Every displayed percentage was recomputed from the dollar values.
3. ✅ Exactly **one** discrepancy was found.
4. ✅ The output value matches what the report *displays* (raw, not corrected).
5. ✅ The output file exists at the correct path and contains one line.

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Parenthetical negatives `$(12.3)` | Parsed as −12.3 |
| Thousands separators `$1,234.5` | Commas stripped → 1234.5 |
| Non-standard HTML file name | Script auto-detects `.html` in `/app/` |
| Missing metrics | Skipped — only available checks run |
| Header rows | Skipped automatically (no numeric values) |
| Multiple tables / sections | All merged into one metric set |
| Error in dollar amount | Dollar cross-checks catch it; downstream checks may pass vacuously |
| YoY / growth rate errors | Compared against available prior-period values |
| Component vs total ambiguity | Task guarantees discoverability; additional cross-checks disambiguate |
