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

You are given an HTML earnings report (typically at
`/app/q2_earnings_report.html`) containing:

1. **An income statement** — line-numbered dollar-denominated metrics
   (revenue, costs, expenses, profits).
2. **A KPI section** — derived percentage metrics (margins, ratios)
   computed from the dollar values.

**Exactly one metric is incorrect.** All dollar values are internally
consistent. The wrong value is a displayed KPI percentage that violates
a cross-check against the statement data.

**Output:** Write `line_number,value` to the output file (typically
`/app/value.txt`). Use the report's embedded line number (not the file
line). Do not include a `%` sign.

## Solve Procedure

**Write the solve script to `/tmp/solve.py`, then run it.** The
script is complete and self-contained — no modifications needed for
standard variants.

```bash
# Write the script (copy from "Solve Script" section below)
cat << 'EOF' > /tmp/solve.py
...
EOF

# Run it
python3 /tmp/solve.py

# Verify
cat /app/value.txt
```

If the report path or output path differs from defaults, pass them
as arguments: `python3 /tmp/solve.py <html_path> <output_path>`.

## Solve Script

```python
#!/usr/bin/env python3
"""
html-finance-verify solver.
Dynamically parses HTML, extracts metrics, and finds the single
incorrect KPI by cross-checking every percentage against all
simple pair ratios from the dollar-denominated statement.
"""
import re, sys

html_path = sys.argv[1] if len(sys.argv) > 1 else "/app/q2_earnings_report.html"
out_path  = sys.argv[2] if len(sys.argv) > 2 else "/app/value.txt"

# ── 1. Parse HTML ─────────────────────────────────────────────────

with open(html_path) as f:
    html = f.read()
no_tags = re.sub(r'<[^>]+>', ' ', html)

def parse_num(raw):
    """Parse a numeric string; handles $, commas, %, (negative)."""
    raw = raw.strip()
    if not raw:
        return None, raw
    sign = 1
    if raw.startswith('(') and raw.endswith(')'):
        sign, raw = -1, raw[1:-1].strip()
    cleaned = raw.replace('$', '').replace('%', '').replace(',', '').strip()
    try:
        return sign * float(cleaned), raw
    except ValueError:
        return None, raw

# Primary parser: structured <td class="line"> regex
row_re = re.compile(
    r'<td[^>]*class="line"[^>]*>\s*(\d+)\s*</td>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*class="num"[^>]*>\s*([^<]+?)\s*</td>',
    re.IGNORECASE)

stmt, kpis = {}, {}   # line_no -> (name, value, raw_str)
for m in row_re.finditer(html):
    ln = int(m.group(1))
    name = m.group(2).strip()
    val, raw = parse_num(m.group(3))
    if val is None:
        continue
    if raw.startswith('$'):
        stmt[ln] = (name, val, raw)
    else:
        kpis[ln] = (name, val, raw)

# Fallback: plain-text scan for unusual HTML structures
if not stmt and not kpis:
    for m in re.finditer(
        r'(\d{2,4})\s+([A-Za-z][\w\s,]+?)\s+([\$\d][\d.,%$()\-]+)',
        no_tags):
        ln, name = int(m.group(1)), m.group(2).strip()
        val, raw = parse_num(m.group(3))
        if val is None:
            continue
        if raw.startswith('$'):
            stmt[ln] = (name, val, raw)
        else:
            kpis[ln] = (name, val, raw)

print(f"Parsed {len(stmt)} statement metrics, {len(kpis)} KPIs")
for ln in sorted(stmt):
    print(f"  stmt L{ln}: {stmt[ln][0]} = {stmt[ln][1]}")
for ln in sorted(kpis):
    print(f"  kpi  L{ln}: {kpis[ln][0]} = {kpis[ln][1]}")

# ── 2. Dollar cross-checks (sanity) ──────────────────────────────

s = {name: val for _, (name, val, _) in stmt.items()}
print("\nDollar checks:")
rev = s.get("Revenue") or s.get("Total revenue") or s.get("Net revenue")
cor = s.get("Cost of revenue") or s.get("Cost of sales") or s.get("Cost of goods sold")
gp  = s.get("Gross profit")
oi  = s.get("Operating income") or s.get("Operating profit") or s.get("EBIT")
ni  = s.get("Net income") or s.get("Net profit")
oi_net = s.get("Other income, net") or s.get("Other income") or s.get("Other expense, net")
total_opex = s.get("Total operating expenses") or s.get("Total opex")

if rev and cor and gp:
    print(f"  GP=Rev-Cost: {'OK' if abs(rev-cor-gp)<0.06 else 'FAIL'}")
if gp and oi and total_opex:
    print(f"  OI=GP-OpEx: {'OK' if abs(gp-total_opex-oi)<0.06 else 'FAIL'}")
if oi and oi_net is not None and ni:
    print(f"  NI=OI+Other: {'OK' if abs(oi+oi_net-ni)<0.06 else 'FAIL'}")

# ── 3. KPI verification (simple pair ratios) ─────────────────────
#
# For each KPI percentage, check whether it matches round(a/b * 100,
# places) for ANY ordered pair (a, b) of distinct dollar values.
#
# Why simple pairs only (no sums/differences in primary check):
#   Sum/difference formulas like |R&D - S&M| / G&A can coincidentally
#   produce the same value as an incorrect KPI, creating false matches.
#   Standard financial KPIs (margins, expense ratios, tax rates) are
#   all simple ratios of two statement values.
#
# The extended check (sums/diffs) is used only as a fallback when
# multiple KPIs fail the simple check, indicating a non-standard
# formula might be in play.

def decimal_places(raw):
    cleaned = raw.replace('%', '').strip()
    return len(cleaned.split('.')[-1]) if '.' in cleaned else 0

def try_pairs(kpi_val, places, vals):
    tol = 0.5 * 10**(-places) + 0.005
    for i, v1 in enumerate(vals):
        for j, v2 in enumerate(vals):
            if i == j or abs(v2) < 1e-9:
                continue
            if abs(round(v1 / v2 * 100, places) - kpi_val) < tol:
                return True
    return False

def try_extended(kpi_val, places, vals):
    """Fallback: also try (a+b)/c and |a-b|/c."""
    tol = 0.5 * 10**(-places) + 0.005
    n = len(vals)
    for i in range(n):
        for j in range(i + 1, n):
            for num in [vals[i] + vals[j], abs(vals[i] - vals[j])]:
                for k in range(n):
                    if abs(vals[k]) < 1e-9:
                        continue
                    if abs(round(num / vals[k] * 100, places) - kpi_val) < tol:
                        return True
    return False

stmt_vals = list(s.values())
print("\nKPI checks (simple pair ratios):")
wrong = []
for ln in sorted(kpis):
    name, reported, raw = kpis[ln]
    places = decimal_places(raw)
    matched = try_pairs(reported, places, stmt_vals)
    print(f"  L{ln} {name}: {reported} [{'OK' if matched else 'WRONG'}]")
    if not matched:
        wrong.append((ln, reported, raw))

# Fallback: if multiple KPIs failed, try extended formulas
if len(wrong) > 1:
    print("\nExtended check (sums/diffs as numerators):")
    still = []
    for ln, reported, raw in wrong:
        places = decimal_places(raw)
        matched = try_extended(reported, places, stmt_vals)
        print(f"  L{ln}: {reported} [{'OK' if matched else 'WRONG'}]")
        if not matched:
            still.append((ln, reported, raw))
    wrong = still

# ── 4. Write answer ──────────────────────────────────────────────

print()
if wrong:
    if len(wrong) > 1:
        print(f"WARNING: {len(wrong)} unmatched KPIs, using first")
    ln, reported, raw = wrong[0]
    value_str = raw.replace('%', '').strip()
    answer = f"{ln},{value_str}"
    print(f"Answer: {answer}")
    with open(out_path, "w") as f:
        f.write(answer + "\n")
    print(f"Written to {out_path}")
else:
    print("ERROR: No incorrect KPI found. Re-examine parsing.")
    sys.exit(1)
```

## How It Works

1. **Dynamic HTML parsing:** Regex extracts every row with a line
   number, metric name, and numeric value. Classifies by `$` / `%`
   prefix/suffix. Plain-text fallback handles unusual layouts.

2. **Dollar relationship verification:** Checks standard income
   statement arithmetic as a sanity check. These should all balance.

3. **Simple pair ratio matching:** For each KPI percentage, checks
   whether `round(a/b × 100, places)` matches for any ordered pair
   `(a, b)` of distinct dollar values. Standard financial KPIs
   (margins, expense ratios, tax rates) are all simple ratios.
   The single KPI that NO pair matches is the wrong one.

4. **Extended fallback:** If multiple KPIs fail (non-standard report),
   also tries `(a+b)/c` and `|a-b|/c` formulas.

5. **Output:** Writes `line_number,displayed_value` with no `%` sign.

## Decision Rules

1. **Dollar values are correct.** The error is always in a derived
   percentage metric.
2. **Exactly one KPI fails.** If multiple seem wrong, check parsing
   and tolerance.
3. **Report the wrong value as displayed** in the HTML, with `%`
   stripped.
4. **Use report line numbers** (from `<td class="line">` cells), not
   file line numbers.
5. **Round to match** the report's displayed precision before
   comparing.

## Adaptation Notes

| Variation | How the solver handles it |
|---|---|
| Different table structure / CSS | Regex + plain-text fallback |
| Different metric names | Name-agnostic pair-ratio matching |
| Different KPI types | All-pairs enumeration covers margins, ratios, rates |
| Negative values `(xxx)` | `parse_num` handles parenthetical notation |
| Different output file / path | Configurable via `sys.argv` |
| Different decimal precision | Auto-detected from displayed value |

If the HTML uses a radically different structure (no `<td
class="line">` cells), the plain-text fallback activates. If that
also fails, inspect the HTML and adjust the regex.

If a KPI uses a formula not covered by simple ratios (CAGR, EPS
with share counts, multi-period averages), the extended fallback
may catch it. Otherwise, add custom formulas to the script.

## Verification Checklist

Before submitting:

- [ ] Script parsed all expected metrics (check printed counts).
- [ ] Dollar relationships all show "OK".
- [ ] Exactly one KPI shows "WRONG".
- [ ] Output file has `line_number,value` with no `%` sign.
- [ ] Line number matches the report's embedded number.
