---
name: html-finance-verify
description: >
  Verify an HTML financial report for internal consistency. Parse line-numbered
  metrics from an income statement and KPI sidebar, cross-check all arithmetic
  relationships (subtotals, margins, ratios), identify the single incorrect
  metric, and write the result to a file.
---

# HTML Finance Verify

## Task Summary

An HTML earnings report contains dollar-denominated statement values (all
internally consistent) and KPI percentages (exactly one is wrong). Find the
incorrect KPI and write its report line number and displayed value to the
output file.

## Procedure

### 1. Read the HTML report and extract metrics

Parse the HTML file specified in the task. Each metric row contains:
- **Line number** (the report's own ID, e.g. in `td.line`) — NOT the file line number
- **Metric name** (e.g. "Revenue", "Gross margin")
- **Value** (numeric, may have `$` prefix or `%` suffix)

Extract all `(line_number, name, raw_value)` triples. A regex works for simple
table structures; fall back to `html.parser` or BeautifulSoup for complex HTML.

```python
import re
pattern = r'<td[^>]*class="[^"]*line[^"]*"[^>]*>(\d+)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*class="[^"]*num[^"]*"[^>]*>(.*?)</td>'
rows = re.findall(pattern, html, re.DOTALL)
```

Clean each value: strip `$`, `%`, commas, whitespace; convert to float; record
whether `%` was present.

### 2. Verify income-statement arithmetic (sanity check)

Dollar amounts should satisfy standard identities. **Important**: check
subtract patterns FIRST to prevent "Revenue" from matching "Cost of revenue":

| Check | Formula |
|-------|---------|
| Gross profit | Revenue − Cost of revenue/COGS |
| Total opex | Sum of R&D + S&M + G&A + other opex items |
| Operating income | Gross profit − Total opex |
| Net income | Operating income ± Other income − Tax |

Use tolerance ≤ 0.05. These should all pass (task guarantees dollar amounts
are consistent). This step builds confidence that your extracted values are
correct.

**Name matching must be flexible** — use prefix, suffix, and plural handling:
- Prefix: "general and admin" matches "General and administrative"
- Suffix: "operating expense" matches "Total operating expenses"
- Plural: "expense" matches "expenses" (append optional `s?` to patterns)

### 3. Verify each KPI (the core check)

For every percentage metric, compute the expected value from dollar amounts.

**Step 3a — Try named formulas first:**

| KPI name contains | Numerator | Denominator |
|-------------------|-----------|-------------|
| `gross margin` | Gross profit | Revenue |
| `operating margin` | Operating income | Revenue |
| `net margin` | Net income | Revenue |
| `r&d` / `research` | R&D expense | Revenue |
| `ebitda margin` | EBITDA | Revenue |
| `operating ratio` | Total opex | Revenue |
| `tax rate` | Income tax | Pre-tax income |

**Step 3b — Brute-force fallback:** If no named formula matches, try every
dollar metric as numerator divided by every other dollar metric as denominator.
Check if the result (× 100, rounded to the report's stated precision) matches
the reported KPI value. A correct KPI will have at least one matching pair;
the incorrect one will have **no matching pair at all**.

```python
for kpi_name, kpi_line, kpi_val in kpi_metrics:
    found_match = False
    for num_name, num_val in dollar_metrics:
        for den_name, den_val in dollar_metrics:
            if den_val == 0 or num_name == den_name:
                continue
            expected = round(num_val / den_val * 100, decimal_places)
            if abs(expected - kpi_val) <= tolerance:
                found_match = True
                break
        if found_match:
            break
    if not found_match:
        answer = (kpi_line, kpi_val)  # This KPI is the error
```

### 4. Handle the decimal precision

Read the report's note about rounding (e.g. "rounded to one decimal place").
If no note, infer precision from the reported values. Round your expected
values to the same number of decimal places before comparing.

Tolerance = half the last displayed digit + 0.01 float buffer:
- 1 decimal place: ±0.06
- 2 decimal places: ±0.006
- Integer: ±0.6

### 5. Write the output

Format: `line_number,value` (no `%`, no `$`, no commas).
- `line_number` = the report's embedded line number
- `value` = the **incorrect value as displayed** (do NOT correct it)

### 6. Run the provided solver

**Prefer running `scripts/solve.py` directly** — it handles parsing,
name matching, verification, and output in one step:

```bash
python3 <skill_dir>/scripts/solve.py [--html /app/q2_earnings_report.html] [--output /app/value.txt]
```

It prints all extracted metrics, all verification checks, and writes the
answer. Inspect its output to confirm exactly one error was found.

## Common Pitfalls

1. **Report line numbers ≠ file line numbers.** Use the ID from `td.line`.
2. **Strip formatting from output.** Remove `%`, `$`, commas from the value.
3. **Round expected values to report precision** before comparing.
4. **Don't hard-code metric names.** Parse dynamically; variants use different names.
5. **Don't hard-code the answer.** The wrong metric and its value change per variant.
6. **Check subtract patterns before add patterns.** "Revenue" appears inside
   "Cost of revenue" — subtract-first prevents double-counting.
7. **Handle plurals and abbreviations.** "expense" vs "expenses",
   "G&A" vs "General and Administrative", "R&D" vs "Research and Development".
8. **Brute-force as fallback.** If named formulas don't match, try all
   numerator/denominator pairs — the correct KPIs will match, the wrong one won't.
