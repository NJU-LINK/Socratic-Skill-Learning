---
name: html-finance-verify
description: >
  Parse an HTML financial earnings report containing an income statement and
  KPI sidebar, identify the single incorrect metric by verifying all internal
  arithmetic and ratio relationships, and write the result to a specified
  output file in `line_number,value` format.
---

# HTML Financial Report Verification

## Task Overview

You are given an HTML quarterly earnings report (typically at
`/app/q2_earnings_report.html`). The report contains:

1. **An income statement** with line-numbered dollar-denominated metrics
   (revenue, cost of revenue, gross profit, operating expenses, operating
   income, other income, net income, etc.).
2. **A KPI sidebar or section** with derived percentage metrics (margins,
   growth rates, per-share figures, etc.) that are computed from the
   dollar-denominated statement values.

**Exactly one metric in the entire document is incorrect.** All dollar
statement values are internally consistent. The single wrong value is a
displayed KPI percentage (or other derived metric) that violates a
cross-check against the statement data.

Your job: find the incorrect metric and report its **line number** and
**displayed value** to the output file (typically `/app/value.txt`).

## General Strategy

### Step 1 — Parse the HTML

Use Python (with `html.parser`, `BeautifulSoup` if available, or regex)
to extract every metric from the report. For each metric, capture:

| Field | Example |
|-------|---------|
| HTML line or report line number | `210` |
| Metric name | `Gross margin` |
| Displayed value | `60.8%` |
| Raw numeric value | `60.8` |
| Unit / section | `KPI` or `Income Statement` |

> **Tip:** The report line numbers are embedded in the HTML (e.g., in a
> `<td class="line">` cell). Use those—not the file line numbers—to
> identify metrics in your answer.

### Step 2 — Map the Income Statement Relationships

Build a directed model of how dollar values relate to each other.
Common relationships found in earnings reports:

| Relationship | Formula |
|---|---|
| Gross profit | Revenue − Cost of revenue |
| Total operating expenses | Sum of R&D + S&M + G&A (+ other OpEx lines if present) |
| Operating income | Gross profit − Total operating expenses |
| Pre-tax income | Operating income + Other income/expense |
| Net income | Pre-tax income − Tax provision (or + Other income if no tax line) |

Verify **every** additive and subtractive relationship among the dollar
values. They should all balance exactly (within floating-point tolerance
of ±0.05 for rounding to one decimal).

> If any dollar relationship fails, that would contradict the task
> guarantee that all dollar values are consistent. In practice, start
> by trusting the dollar amounts and focus suspicion on KPI / percentage
> values.

### Step 3 — Verify Every Derived KPI

For each KPI or percentage metric, recompute the expected value from
the dollar statement and compare:

| KPI Type | Formula |
|---|---|
| Gross margin (%) | Gross profit ÷ Revenue × 100 |
| Operating margin (%) | Operating income ÷ Revenue × 100 |
| Net margin (%) | Net income ÷ Revenue × 100 |
| Year-over-year change (%) | (Current − Prior) ÷ Prior × 100 |
| EPS | Net income ÷ Shares outstanding |
| Operating expense ratio | Total OpEx ÷ Revenue × 100 |
| Tax rate | Tax provision ÷ Pre-tax income × 100 |

**Rounding rule:** Match the report's stated precision (usually one
decimal place). Round the expected value the same way before comparing.

The single KPI whose recomputed value **disagrees** with the reported
value is the incorrect metric.

### Step 4 — Write the Answer

Write to the output file in the required format:

```
line_number,value
```

- `line_number`: the report line number (from the HTML, not the file line).
- `value`: the **incorrect** numeric value **as displayed** in the report.
  - Do **not** include a `%` sign unless the instructions explicitly say so.
  - Use the exact numeric formatting shown (e.g., `60.8`, not `60.80`).

## Verification Checklist

Before writing the final answer, confirm:

- [ ] All dollar-value arithmetic relationships balance.
- [ ] Exactly **one** KPI percentage fails its cross-check.
- [ ] The recomputed correct value for that KPI is consistent with all
      other (correct) KPIs and dollar values.
- [ ] The line number and value in the output file match the HTML report
      line and displayed value exactly.

## Common Pitfalls

| Pitfall | How to avoid |
|---|---|
| Using file line numbers instead of report line numbers | Always extract the line number from the HTML content (e.g., `<td class="line">210</td>`) |
| Including `%` sign in the output value | Strip the `%`; output only the numeric portion |
| Rounding mismatch | Round your expected value to the same decimal places as the report before comparing |
| Assuming a fixed table structure | Parse dynamically; the number of OpEx categories, KPI types, and sections can vary |
| Confusing "which value is wrong" | The task guarantees dollar values are correct; the error is in a derived/KPI metric |

## Reference Implementation Skeleton

```python
#!/usr/bin/env python3
"""
General skeleton for html-finance-verify tasks.
Adapt the parsing and relationship maps to the specific report.
"""
import re
from html.parser import HTMLParser

# ── 1. Read the HTML ──────────────────────────────────────────────
html_path = "/app/q2_earnings_report.html"
with open(html_path) as f:
    html_text = f.read()

# ── 2. Extract metrics ───────────────────────────────────────────
# Adapt these regexes to the actual HTML structure.
# Pattern: find <td class="line">NNN</td> followed by metric name and value.
metric_pattern = re.compile(
    r'<td class="line">(\d+)</td>\s*'
    r'<td>([^<]+)</td>\s*'
    r'<td class="num">([^<]+)</td>'
)

income_stmt = {}  # line_no -> (name, value_dollars)
kpis = {}          # line_no -> (name, value_pct)

for m in metric_pattern.finditer(html_text):
    line_no = int(m.group(1))
    name = m.group(2).strip()
    raw_val = m.group(3).strip()

    if raw_val.startswith("$"):
        # Dollar value from income statement
        dollars = float(raw_val.replace("$", "").replace(",", ""))
        income_stmt[line_no] = (name, dollars)
    elif raw_val.endswith("%"):
        # Percentage KPI
        pct = float(raw_val.replace("%", ""))
        kpis[line_no] = (name, pct)
    else:
        # Other numeric (e.g., per-share, shares outstanding)
        val = float(raw_val.replace(",", ""))
        kpis[line_no] = (name, val)

# ── 3. Build income statement model ──────────────────────────────
# Map metric names to values for easy lookup.
stmt = {name: val for _, (name, val) in income_stmt.items()}

# ── 4. Verify dollar relationships ──────────────────────────────
# (Adapt relationship names to the actual report.)
def check(label, expected, actual, tol=0.05):
    diff = abs(expected - actual)
    status = "OK" if diff < tol else f"FAIL (diff={diff:.2f})"
    print(f"  {label}: expected {expected:.1f}, got {actual:.1f} -> {status}")
    return diff < tol

print("Income statement checks:")
# These checks use generic names; adapt to the report's actual labels.
# check("Gross profit", stmt["Revenue"] - stmt["Cost of revenue"], stmt["Gross profit"])
# check("Total OpEx", stmt["R&D"] + stmt["S&M"] + stmt["G&A"], stmt["Total operating expenses"])
# check("Operating income", stmt["Gross profit"] - stmt["Total operating expenses"], stmt["Operating income"])
# check("Net income", stmt["Operating income"] + stmt["Other income, net"], stmt["Net income"])

# ── 5. Verify KPI cross-checks ──────────────────────────────────
print("\nKPI checks:")
revenue = stmt.get("Revenue", 0)
wrong_line = None
wrong_value = None

for line_no, (name, reported_pct) in kpis.items():
    # Determine expected value based on KPI name
    # Adapt these conditions to the report's KPI labels.
    if "gross margin" in name.lower():
        expected = stmt["Gross profit"] / revenue * 100
    elif "operating margin" in name.lower():
        expected = stmt["Operating income"] / revenue * 100
    elif "net margin" in name.lower():
        expected = stmt["Net income"] / revenue * 100
    else:
        print(f"  {name} (line {line_no}): no rule — skipping")
        continue

    expected_rounded = round(expected, 1)
    match = abs(expected_rounded - reported_pct) < 0.05
    status = "OK" if match else f"WRONG (expected {expected_rounded})"
    print(f"  {name} (line {line_no}): reported {reported_pct}, expected {expected_rounded} -> {status}")

    if not match:
        wrong_line = line_no
        wrong_value = reported_pct

# ── 6. Write the answer ─────────────────────────────────────────
if wrong_line is not None:
    answer = f"{wrong_line},{wrong_value}"
    print(f"\nAnswer: {answer}")
    with open("/app/value.txt", "w") as f:
        f.write(answer + "\n")
else:
    print("\nERROR: No incorrect metric found. Re-examine relationships.")
```

## Decision Rules Summary

1. **Dollar values are assumed correct.** The single error is always in a
   derived / percentage metric.
2. **Exactly one KPI will fail.** If multiple seem wrong, recheck your
   formula mapping and rounding.
3. **Report the wrong value as-is.** Do not correct it; output what the
   report displays.
4. **Use report line numbers**, not file line numbers.
5. **No `%` sign** in the output value.
