---
name: html-finance-verify
description: >
  Verify an HTML financial report for internal consistency. Parse line-numbered
  metrics from an income statement and KPI sidebar, cross-check all arithmetic
  relationships (subtotals, margins, ratios), identify the single incorrect
  reported metric, and write the result to a file.
---

# HTML Finance Verify

## Task Overview

You are given an HTML earnings report containing an income statement and derived
KPI metrics. Exactly **one** reported metric is incorrect. All dollar-denominated
statement values are internally consistent with each other; the error is in a
single displayed KPI (percentage, ratio, or derived value) that does not match
the statement data.

Your job: find the incorrect metric and report its **line number** and
**displayed value** to the output file.

## Step 1 — Locate and Parse the Report

The HTML file path is given in the task (e.g. `/app/q2_earnings_report.html`).
Read it and extract every metric row. Each row typically contains:

| Field | Where to find it |
|-------|-----------------|
| **Line number** | A cell with class `line` (or similar) — this is the report's own identifier, NOT the file line number |
| **Metric name** | A text cell (e.g. "Revenue", "Gross margin") |
| **Value** | A numeric cell, possibly prefixed with `$` and/or suffixed with `%` |

Use a regex or HTML parser to extract all `(line_number, metric_name, raw_value)`
triples. Example Python:

```python
import re

with open("/app/q2_earnings_report.html") as f:
    html = f.read()

pattern = r'<td class="line">(\d+)</td>\s*<td>(.*?)</td>\s*<td class="num">(.*?)</td>'
rows = re.findall(pattern, html, re.DOTALL)
```

Adapt the regex if the HTML structure differs (different class names, extra
columns, nested spans, etc.). If the regex approach misses rows, fall back to
an HTML parser like `html.parser` or `BeautifulSoup`.

### Clean numeric values

- Strip `$`, `%`, commas, and whitespace.
- Convert to `float`.
- Track which values are percentages (had `%`) vs dollar amounts.

## Step 2 — Identify Metric Relationships

### Income statement (dollar amounts)

Look for standard accounting identities among the dollar-denominated metrics.
Common patterns (adapt names to what you actually find):

| Relationship | Formula |
|-------------|---------|
| Gross profit | Revenue − Cost of revenue |
| Total operating expenses | Sum of R&D + S&M + G&A (and any other listed opex line items) |
| Operating income | Gross profit − Total operating expenses |
| Net income | Operating income + Other income (net) − Tax expense |

Not every report will have all of these. **Determine the actual relationships
from the metric names present.** If a metric name contains "total" or "subtotal",
it is likely the sum or difference of adjacent line items.

### KPI section (percentages / ratios)

KPIs are derived from the dollar amounts. Common patterns:

| KPI name pattern | Formula |
|-----------------|---------|
| *Gross margin* | Gross profit ÷ Revenue × 100 |
| *Operating margin* | Operating income ÷ Revenue × 100 |
| *Net margin* | Net income ÷ Revenue × 100 |
| *R&D as % of revenue* | R&D ÷ Revenue × 100 |
| *YoY growth* | (Current − Prior) ÷ Prior × 100 |
| *EPS* | Net income ÷ Shares outstanding |
| *Operating ratio* | Operating expenses ÷ Revenue × 100 |

The report usually states the denominator in a note (e.g. "Margins are
presented as a percentage of revenue"). **Read that note** to confirm the
formula. If no note exists, infer the denominator from the KPI name and
magnitude.

## Step 3 — Verify Everything

### 3a. Verify income-statement arithmetic

For each subtotal/total metric, compute the expected value from its constituent
line items and compare to the reported value. Use tolerance ≤ 0.05 for
rounding in the source data.

```python
def check(reported, expected, label, tol=0.05):
    diff = abs(reported - expected)
    status = "OK" if diff <= tol else f"MISMATCH (diff={diff:.4f})"
    print(f"  {label}: expected={expected}, reported={reported} → {status}")
    return diff > tol
```

If any dollar amount is wrong, note it — but per the task spec, dollar amounts
are internally consistent. The error is in a KPI.

### 3b. Verify each KPI

For every KPI metric:

1. Identify which dollar amounts it is derived from.
2. Compute the expected KPI value.
3. Round to the same precision as the report (usually 1 decimal place for
   percentages — check the report's note).
4. Compare to the reported KPI value.

```python
def verify_kpi(name, numerator, denominator, reported_pct, dp=1):
    expected = round(numerator / denominator * 100, dp)
    mismatch = abs(expected - reported_pct) > 10 ** (-dp) / 2 + 0.01
    return expected, mismatch
```

### Tolerance guide

| Report precision | Tolerance |
|-----------------|-----------|
| 1 decimal place | ±0.06 |
| 2 decimal places | ±0.006 |
| Integer | ±0.6 |

The tolerance accounts for the rounding window (±half the last digit) plus a
small floating-point buffer.

## Step 4 — Identify the Single Error

Exactly one KPI will fail verification. Collect all mismatches:

- If **exactly one** KPI mismatches → that is the answer.
- If **zero** KPIs mismatch → re-examine your assumed formulas (maybe the
  denominator is not Revenue, or the KPI uses a different numerator).
- If **multiple** KPIs mismatch → re-check your extracted values and
  relationships; the task guarantees exactly one error.

## Step 5 — Write the Output

Write to the file specified in the task (e.g. `/app/value.txt`):

```
line_number,value
```

Rules:
- `line_number` — the report's embedded line number (from `td.line`), NOT the
  file line number.
- `value` — the incorrect numeric value **as displayed** in the report.
- **Do NOT include** `%`, `$`, commas, or other formatting symbols.
- **Do NOT correct** the value; report the wrong value that appears in the
  document.

Example: if line 210 shows `60.8%` and that is the incorrect metric, write:
```
210,60.8
```

## Quick Verification Script

When possible, write and run a self-contained Python script to automate the
check. Template:

```python
import re, sys

# --- Config ---
HTML_PATH = "/app/q2_earnings_report.html"
OUTPUT_PATH = "/app/value.txt"

# --- Parse ---
with open(HTML_PATH) as f:
    html = f.read()

pattern = r'<td class="line">(\d+)</td>\s*<td>(.*?)</td>\s*<td class="num">(.*?)</td>'
rows = re.findall(pattern, html, re.DOTALL)

metrics = {}
for line_str, name, raw in rows:
    line_num = int(line_str)
    clean = raw.replace("$", "").replace("%", "").replace(",", "").strip()
    is_pct = "%" in raw
    metrics[name] = {"line": line_num, "value": float(clean), "pct": is_pct, "raw": raw}

# --- Identify dollar amounts and KPIs ---
dollar_metrics = {k: v for k, v in metrics.items() if not v["pct"]}
kpi_metrics = {k: v for k, v in metrics.items() if v["pct"]}

# --- Verify income statement relationships ---
# Adapt these to the actual metric names found
rev = dollar_metrics.get("Revenue", {}).get("value", 0)
cor = dollar_metrics.get("Cost of revenue", {}).get("value", 0)
gp  = dollar_metrics.get("Gross profit", {}).get("value", 0)
# ... extract all dollar values, then check:
#   gp ≈ rev - cor
#   operating_income ≈ gp - total_opex
#   net_income ≈ operating_income + other_income

# --- Verify KPIs ---
errors = []
for name, m in kpi_metrics.items():
    # Determine expected value based on metric name
    # Example for margin metrics:
    if "gross" in name.lower():
        expected = round(gp / rev * 100, 1)
    elif "operating" in name.lower():
        oi = dollar_metrics.get("Operating income", {}).get("value", 0)
        expected = round(oi / rev * 100, 1)
    elif "net" in name.lower():
        ni = dollar_metrics.get("Net income", {}).get("value", 0)
        expected = round(ni / rev * 100, 1)
    else:
        continue  # handle other KPI types as needed

    if abs(expected - m["value"]) > 0.06:
        errors.append((m["line"], m["value"], name, expected))

# --- Report ---
if len(errors) == 1:
    line, val, name, exp = errors[0]
    print(f"Error found: {name} at line {line}: reported {val}, expected {exp}")
    with open(OUTPUT_PATH, "w") as f:
        f.write(f"{line},{val}\n")
elif len(errors) == 0:
    print("WARNING: No mismatches found. Re-check formulas and precision.")
    sys.exit(1)
else:
    print(f"WARNING: {len(errors)} mismatches found. Re-check extraction.")
    for e in errors:
        print(f"  Line {e[0]}: {e[2]} reported={e[1]} expected={e[3]}")
    sys.exit(1)
```

**Adapt this template** to the actual report structure. Do not run it blindly;
inspect the extracted metrics first to confirm names and relationships.

## Common Pitfalls

1. **Confusing report line numbers with file line numbers.** The task wants
   the report's embedded line number (inside `td.line`), not the line number
   in the HTML source file.
2. **Including formatting symbols.** Strip `%` and `$` from the output value.
3. **Using the wrong denominator.** Always check the report's note about how
   margins/KPIs are calculated.
4. **Ignoring rounding.** The report rounds to a specific decimal place.
   Your expected value must be rounded the same way before comparison.
5. **Hard-coding a specific company's numbers.** The report content varies
   across instances. Parse dynamically.
