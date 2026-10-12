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
incorrect KPI and write its **report line number** and **displayed value**
(no `%` sign) to the output file as `line_number,value`.

## Critical: Host vs Container Filesystem

The skill workspace (`SKILL.md`, `scripts/`) lives on the **host filesystem**.
The `task_shell` tool runs commands inside an **isolated container at `/app/`**.
Scripts from the host are NOT directly executable in the container.

**To use `scripts/solve.py`:**
1. Read it with the `read` tool (host path from SKILL.md metadata)
2. Deploy it into the container: write the content to `/app/solve.py` via
   heredoc in `task_shell`
3. Execute: `python3 /app/solve.py`

**Alternatively**, write a complete verification script inline in `task_shell`
following the procedure below. This avoids the extra `read` call.

## Procedure

### 1. Read the HTML report and extract metrics

Each metric row contains a **line number** (report ID in `td.line`), a
**metric name**, and a **value** (with `$` or `%`). Extract all triples.

```python
import re
pattern = r'<td[^>]*class="[^"]*line[^"]*"[^>]*>(\d+)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*class="[^"]*num[^"]*"[^>]*>(.*?)</td>'
rows = re.findall(pattern, html, re.DOTALL)
```

Clean values: strip `$`, `%`, commas; convert to float; record if `%` present.

### 2. Verify income-statement arithmetic (sanity check)

| Check | Formula |
|-------|---------|
| Gross profit | Revenue − Cost of revenue/COGS |
| Total opex | Sum of R&D + S&M + G&A (+ other opex) |
| Operating income | Gross profit − Total opex |
| Net income | Operating income ± Other income − Tax |

**Name matching must be flexible** — handle plurals (`expense`↔`expenses`),
prefixes (`general and admin`↔`General and Administrative`), and abbreviations
(`G&A`, `R&D`, `S&M`). Check subtract patterns FIRST so "Revenue" inside
"Cost of revenue" doesn't cause double-counting.

### 3. Verify each KPI (the core check)

**Named formulas** (try first):

| KPI name contains | Numerator | Denominator |
|-------------------|-----------|-------------|
| `gross margin` | Gross profit | Revenue |
| `operating margin` | Operating income | Revenue |
| `net margin` | Net income | Revenue |
| `r&d` / `research` | R&D expense | Revenue |
| `ebitda margin` | EBITDA | Revenue |
| `operating ratio` | Total opex | Revenue |

**Brute-force fallback** (if named formula doesn't match or for verification):
Try every dollar metric ÷ every other dollar metric × 100, rounded to report
precision. Correct KPIs will match at least one pair; the wrong KPI will match
**none**.

```python
for kpi_line, kpi_name, kpi_val in kpi_metrics:
    found = False
    for num_val in dollar_values:
        for den_val in dollar_values:
            if den_val == 0: continue
            if abs(round(num_val/den_val*100, dp) - kpi_val) <= tol:
                found = True; break
        if found: break
    if not found:
        answer = (kpi_line, kpi_val)
```

### 4. Decimal precision and tolerance

Read the report's rounding note. If absent, infer from displayed values.
Tolerance = half the last digit + 0.01: (1dp → ±0.06, 2dp → ±0.006).

### 5. Write the output

`line_number,value` — no `%`, no `$`, no commas. Report the **wrong** value.

## Complete Solver Script

Write this into `/app/solve.py` via heredoc and run `python3 /app/solve.py`:

```python
#!/usr/bin/env python3
import re, sys

HTML = "/app/q2_earnings_report.html"
OUT  = "/app/value.txt"

with open(HTML) as f:
    html = f.read()

# Parse metrics: (line_number, name, raw_value)
pat = r'<td[^>]*class="[^"]*line[^"]*"[^>]*>(\d+)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*class="[^"]*num[^"]*"[^>]*>(.*?)</td>'
raw = re.findall(pat, html, re.DOTALL)

metrics = {}
for ln, name, rv in raw:
    ln = int(ln); name = name.strip()
    pct = "%" in rv
    cl = rv.replace("$","").replace("%","").replace(",","").strip()
    if cl.startswith("(") and cl.endswith(")"): cl = "-" + cl[1:-1]
    val = float(cl)
    dp = 0
    if "." in cl:
        d = cl.split(".")[-1].rstrip("0"); dp = len(d) if d else 0
    metrics[name] = dict(line=ln, val=val, pct=pct, dp=dp)

dollars = {k:v for k,v in metrics.items() if not v["pct"]}
kpis    = [v for v in metrics.values() if v["pct"]]

print(f"Found {len(dollars)} dollar metrics, {len(kpis)} KPIs")
for n,m in metrics.items():
    print(f"  Line {m['line']}: {n} = {m['val']}{'%' if m['pct'] else ''}")

# Detect precision from KPI values
dp = max((m["dp"] for m in kpis), default=1)
tol = 0.5 * 10**(-dp) + 0.01

# Brute-force: for each KPI, check if any dollar/dollar pair matches
errors = []
for kpi in kpis:
    found = False
    for nn, nd in dollars.items():
        for dn, dd in dollars.items():
            if nn == dn or dd["val"] == 0: continue
            exp = round(nd["val"] / dd["val"] * 100, dp)
            if abs(exp - kpi["val"]) <= tol:
                found = True; break
        if found: break
    status = "OK" if found else "MISMATCH"
    print(f"  KPI {kpi['line']}: {kpi.get('raw',kpi['val'])} -> {status}")
    if not found:
        errors.append(kpi)

if len(errors) == 1:
    e = errors[0]
    v = f"{e['val']}"
    if "." in v:
        v = v.rstrip("0").rstrip(".")
        if e["dp"] > 0 and "." not in v:
            v = f"{e['val']:.{e['dp']}f}"
    with open(OUT, "w") as f:
        f.write(f"{e['line']},{v}\n")
    print(f"ANSWER: {e['line']},{v}")
else:
    print(f"ERROR: found {len(errors)} mismatches, expected 1")
    sys.exit(1)
```

This brute-force approach works for **any** report structure without needing
to know metric names in advance — it finds which KPI cannot be explained by
any ratio of dollar amounts.

## Common Pitfalls

1. **Report line numbers ≠ file line numbers.** Use the ID from `td.line`.
2. **Strip `%` and `$` from output.** The value is just the number.
3. **Round to report precision** before comparing.
4. **Parse dynamically** — metric names vary across variants.
5. **Host scripts ≠ container.** Read scripts via `read` tool, deploy via
   heredoc into `/app/`, then execute with `python3 /app/solve.py`.
