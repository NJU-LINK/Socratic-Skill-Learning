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

**Write the complete solve script below to `/tmp/solve.py`, then run
it.** The script is self-contained and requires no modifications for
standard variants. It uses `html.parser` from the standard library
for robust HTML table extraction regardless of CSS class names.

```bash
cat << 'EOF' > /tmp/solve.py
<paste the entire Solve Script here>
EOF

python3 /tmp/solve.py
cat /app/value.txt
```

If the report path or output path differs from defaults, pass them
as arguments: `python3 /tmp/solve.py <html_path> <output_path>`.

## Solve Script

```python
#!/usr/bin/env python3
"""
html-finance-verify solver.
Uses html.parser for robust table extraction (CSS-class agnostic),
then finds the single incorrect KPI by cross-checking every
percentage against all simple pair ratios from the dollar statement.
"""
import re, sys
from html.parser import HTMLParser

html_path = sys.argv[1] if len(sys.argv) > 1 else "/app/q2_earnings_report.html"
out_path  = sys.argv[2] if len(sys.argv) > 2 else "/app/value.txt"

with open(html_path) as f:
    html = f.read()

# ── 1. Robust HTML table parser ───────────────────────────────────
#
# Uses html.parser (stdlib) to extract all <table> contents as
# lists of rows. Works regardless of CSS class names, column
# ordering, or HTML structure variations.

class TableExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._depth = 0
        self._in_table = False
        self._in_tr = False
        self._in_cell = False
        self._table = []
        self._row = []
        self._cell = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._in_table = True
                self._table = []
        elif tag == "tr" and self._in_table:
            self._in_tr = True
            self._row = []
        elif tag in ("td", "th") and self._in_tr:
            self._in_cell = True
            self._cell = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._row.append(self._cell.strip())
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            if self._row:
                self._table.append(self._row)
        elif tag == "table":
            self._depth -= 1
            if self._depth == 0 and self._in_table:
                self._in_table = False
                self.tables.append(self._table)

    def handle_data(self, data):
        if self._in_cell:
            self._cell += data

def parse_num(raw):
    """Parse numeric string; handles $, commas, %, (negative)."""
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

# ── 2. Extract metrics from parsed tables ─────────────────────────
#
# For each table row, identify:
#   - Line number: pure integer cell (1-5 digits)
#   - Value: cell starting with $ or ending with %
#   - Name: remaining text cells (excluding header keywords)
#
# Tables are classified as statement (mostly $) or KPI (mostly %)
# to handle values without explicit $ or % markers.

HEADER_WORDS = {
    'line', 'ref', 'metric', 'item', 'value', 'amount',
    'kpi', 'indicator', 'measure', '',
}

extractor = TableExtractor()
extractor.feed(html)

stmt, kpis = {}, {}   # line_no -> (name, value, raw_str)

for table in extractor.tables:
    # Classify table by majority value type
    dollar_ct = sum(1 for row in table for c in row if c.startswith('$'))
    pct_ct = sum(1 for row in table for c in row if c.endswith('%'))
    is_stmt_table = dollar_ct > pct_ct

    for row in table:
        if len(row) < 2:
            continue

        line_no = None
        name_parts = []
        val = None
        val_raw = None

        for cell in row:
            cell = cell.strip()
            if not cell:
                continue
            # Line number: pure integer, 1-5 digits
            if (line_no is None and cell.isdigit()
                    and 1 <= len(cell) <= 5):
                line_no = int(cell)
                continue
            # Numeric value with $ or % marker
            parsed, cleaned = parse_num(cell)
            if parsed is not None and (cell.startswith('$')
                                       or cell.endswith('%')):
                if val is None:
                    val = parsed
                    val_raw = cleaned
                    continue
            # Name: skip common header keywords
            if cell.lower() in HEADER_WORDS:
                continue
            # Skip cells that look like non-numeric headers
            name_parts.append(cell)

        if line_no is not None and name_parts and val is not None:
            name = ' '.join(name_parts)
            if val_raw and val_raw.startswith('$'):
                stmt[line_no] = (name, val, val_raw)
            elif val_raw and val_raw.endswith('%'):
                kpis[line_no] = (name, val, val_raw)
            else:
                # No explicit marker — use table classification
                if is_stmt_table:
                    stmt[line_no] = (name, val, val_raw or cell)
                else:
                    kpis[line_no] = (name, val, val_raw or cell)

# Regex fallback if html.parser found nothing
if not stmt and not kpis:
    no_tags = re.sub(r'<[^>]+>', ' ', html)
    row_re = re.compile(
        r'<td[^>]*>\s*(\d{1,5})\s*</td>\s*'
        r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
        r'<td[^>]*>\s*([^<]+?)\s*</td>',
        re.IGNORECASE)
    for m in row_re.finditer(html):
        ln = int(m.group(1))
        name = m.group(2).strip()
        v, raw = parse_num(m.group(3))
        if v is None:
            continue
        if raw.startswith('$'):
            stmt[ln] = (name, v, raw)
        else:
            kpis[ln] = (name, v, raw)

print(f"Parsed {len(stmt)} statement metrics, {len(kpis)} KPIs")
for ln in sorted(stmt):
    print(f"  stmt L{ln}: {stmt[ln][0]} = {stmt[ln][1]}")
for ln in sorted(kpis):
    print(f"  kpi  L{ln}: {kpis[ln][0]} = {kpis[ln][1]}")

# ── 3. Dollar cross-checks (sanity) ──────────────────────────────

s = {name: v for _, (name, v, _) in stmt.items()}
print("\nDollar checks:")
rev = (s.get("Revenue") or s.get("Total revenue")
       or s.get("Net revenue"))
cor = (s.get("Cost of revenue") or s.get("Cost of sales")
       or s.get("Cost of goods sold"))
gp  = s.get("Gross profit")
oi  = (s.get("Operating income") or s.get("Operating profit")
       or s.get("EBIT"))
ni  = s.get("Net income") or s.get("Net profit")
oi_net = (s.get("Other income, net") or s.get("Other income")
          or s.get("Other expense, net"))
total_opex = (s.get("Total operating expenses")
              or s.get("Total opex"))

if rev and cor and gp:
    print(f"  GP=Rev-Cost: "
          f"{'OK' if abs(rev-cor-gp)<0.06 else 'FAIL'}")
if gp and oi and total_opex:
    print(f"  OI=GP-OpEx: "
          f"{'OK' if abs(gp-total_opex-oi)<0.06 else 'FAIL'}")
if oi and oi_net is not None and ni:
    print(f"  NI=OI+Other: "
          f"{'OK' if abs(oi+oi_net-ni)<0.06 else 'FAIL'}")

# ── 4. KPI verification (simple pair ratios) ─────────────────────
#
# For each KPI percentage, check whether round(a/b * 100, places)
# matches for ANY ordered pair (a, b) of distinct dollar values.
#
# Why simple pairs only (no sums/differences in primary check):
#   Sum/difference formulas like |R&D - S&M| / G&A can coincidentally
#   produce the same value as an incorrect KPI, creating false
#   matches. Standard financial KPIs (margins, expense ratios, tax
#   rates) are all simple ratios of two statement values.
#
# The extended check (sums/diffs) activates only as a fallback
# when multiple KPIs fail, indicating non-standard formulas.

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
                    if abs(round(num / vals[k] * 100,
                                 places) - kpi_val) < tol:
                        return True
    return False

stmt_vals = list(s.values())
print("\nKPI checks (simple pair ratios):")
wrong = []
for ln in sorted(kpis):
    name, reported, raw = kpis[ln]
    places = decimal_places(raw)
    matched = try_pairs(reported, places, stmt_vals)
    print(f"  L{ln} {name}: {reported} "
          f"[{'OK' if matched else 'WRONG'}]")
    if not matched:
        wrong.append((ln, reported, raw))

# Fallback: if multiple KPIs failed, try extended formulas
if len(wrong) > 1:
    print("\nExtended check (sums/diffs as numerators):")
    still = []
    for ln, reported, raw in wrong:
        places = decimal_places(raw)
        matched = try_extended(reported, places, stmt_vals)
        print(f"  L{ln}: {reported} "
              f"[{'OK' if matched else 'WRONG'}]")
        if not matched:
            still.append((ln, reported, raw))
    wrong = still

# ── 5. Write answer ──────────────────────────────────────────────

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

1. **Robust HTML parsing:** Uses `html.parser.HTMLParser` (stdlib)
   to extract all `<table>` rows as lists of cell text. Does NOT
   depend on specific CSS class names (`class="line"`, `class="num"`).

2. **Content-based row classification:** For each row, identifies
   the line number (pure integer cell), value (cell with `$` or
   `%`), and name (remaining text). Tables are classified as
   statement vs. KPI by majority value type.

3. **Dollar cross-checks:** Verifies standard income statement
   arithmetic as a sanity check.

4. **Simple pair ratio matching:** For each KPI percentage, checks
   if `round(a/b × 100, places)` matches for any pair `(a, b)` of
   dollar values. The single KPI with NO match is the wrong one.
   Sum/diff formulas are NOT used in the primary check to avoid
   coincidental false matches.

5. **Extended fallback:** If multiple KPIs fail (non-standard
   report), also tries `(a+b)/c` and `|a-b|/c` formulas.

6. **Output:** Writes `line_number,displayed_value` with no `%`.

## Decision Rules

1. **Dollar values are correct.** The error is always in a derived
   percentage metric.
2. **Exactly one KPI fails.** If multiple seem wrong, check parsing
   and tolerance.
3. **Report the wrong value as displayed** in the HTML, with `%`
   stripped.
4. **Use report line numbers** (from `<td>` cells containing
   integers), not file line numbers.
5. **Round to match** the report's displayed precision before
   comparing.

## Adaptation Notes

| Variation | How the solver handles it |
|---|---|
| Different CSS class names | `html.parser` ignores classes entirely |
| Different column order | Content-based detection (integer vs $ vs %) |
| Different table structure | Extracts ALL `<table>` elements |
| Different header text | Filters known header keywords dynamically |
| Different metric names | Name-agnostic pair-ratio matching |
| Negative values `(xxx)` | `parse_num` handles parenthetical notation |
| Thousands separators | `parse_num` strips commas |
| Different output path | Configurable via `sys.argv` |
| Different decimal places | Auto-detected from displayed value |

If `html.parser` extraction fails (malformed HTML), a regex
fallback scans the raw HTML. If both fail, inspect the HTML
manually and adjust the parser.

## Verification Checklist

Before submitting:

- [ ] Script parsed all expected metrics (check printed counts).
- [ ] Dollar relationships all show "OK".
- [ ] Exactly one KPI shows "WRONG".
- [ ] Output file has `line_number,value` with no `%` sign.
- [ ] Line number matches the report's embedded number.
