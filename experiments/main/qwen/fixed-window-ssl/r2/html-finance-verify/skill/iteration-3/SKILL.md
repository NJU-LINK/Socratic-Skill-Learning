---
name: html-finance-verify
description: >
  Verify internal consistency of an HTML financial report, identify the single
  incorrect metric, and write its line number and reported value to the
  specified output file. Uses a four-stage algorithm: parse HTML tables, build
  verifiable accounting identities, cross-check expected vs. reported values,
  and isolate the wrong value using intersection with passing-check filtering.
---

# HTML Finance Verify

## Task Family

Given an HTML financial report, find the single incorrect metric and output its
line number and reported value. The report contains financial data that is
internally consistent except for exactly one wrong value.

## Core Algorithm (4 Stages)

### Stage 1: Parse HTML

Use Python's stdlib `html.parser.HTMLParser`. Track table boundaries. For each
row with 3+ cells, extract:
- **Line number** (from cells with `class="line"` or cells containing only digits)
- **Metric name** (text label)
- **Raw value** (displayed number with $ or % symbols)
- **Value type** (dollar, percentage, or plain number)

Parse numeric values by stripping `$`, `%`, commas. Handle parenthetical
negatives: `(123.4)` → `-123.4`. Use `Decimal` throughout for precision.

### Stage 2: Build Relationship Checks

Create checks that verify accounting identities. Each check has:
- A description
- The set of line numbers involved
- The expected value (computed from other reported values)
- The reported value (what the document shows)

**Named-pattern checks** (use when metric names match known patterns):

| Relationship | Formula |
|---|---|
| Gross profit | Revenue − Cost of revenue |
| Total opex | Sum of leaf expense items (R&D, S&M, G&A, etc.) |
| Operating income | Gross profit − Total operating expenses |
| Net income | Operating income + Other income/expenses |
| X margin | (X / Revenue) × 100 |

Match metric names case-insensitively with flexible keywords. For example:
- "revenue" / "sales" / "total revenue"
- "cost of revenue" / "cost of sales" / "COGS"
- "gross profit" / "gross earnings"
- "operating income" / "operating earnings" / "EBIT"
- "net income" / "net earnings"

**CRITICAL: Avoid keyword collision.** Simple substring matching can cause false positives. For example:
- "Sales and marketing" contains "sales" but is NOT revenue (it's an operating expense)
- "Cost of revenue" contains "revenue" but is NOT revenue (it's COGS)

**Solution:** Use specific matching functions with exclusion logic:
```python
def is_revenue(name):
    n = name.lower()
    # Exclude "cost of revenue" and "sales and marketing"
    if "cost" in n and ("revenue" in n or "sales" in n):
        return False
    if "marketing" in n:
        return False
    # Match "revenue" or standalone "sales"
    if "revenue" in n:
        return True
    if "sales" in n and "marketing" not in n and "cost" not in n:
        return True
    return False
```

Always check for common false positives before matching. Print identified metrics to verify correctness.

**Generic additive checks** (for unfamiliar metric names):
For any row whose name contains "total", sum all preceding "leaf" dollar rows
in the same table. A leaf row is one whose name does NOT contain: total, sum,
profit, income, margin, revenue, gross, operating, net, earnings, other.

**Generic ratio checks** (for unfamiliar percentage names):
For each percentage not already checked by a named pattern, try all pairs of
dollar values as (numerator, denominator). Keep only the best match (smallest
difference). Prefer the largest dollar value as denominator (likely revenue).

### Stage 3: Cross-Check

For each check:
1. Compute expected value from the other reported values
2. Round to the report's stated decimal precision
3. Compare: `abs(expected - reported) <= tolerance`

**Tolerance:** Half the unit of the last displayed digit.
- 1 decimal place → 0.05
- 2 decimal places → 0.005
- General: `0.5 × 10^(-decimals)`

**Rounding:** Use `Decimal` with `ROUND_HALF_UP` to match typical financial
reporting. Python's `round()` uses banker's rounding which may differ.

### Stage 4: Isolate the Wrong Value

Use the **intersection algorithm with passing-check filtering**:

1. Collect the set of line numbers involved in each **failing** check
2. Compute the **intersection** of all failing-check sets
3. **Eliminate** any candidate that appears in a **passing** check
   (if it were wrong, those passing checks would also fail)
4. If exactly one candidate remains → that's the answer
5. If multiple remain → pick the one appearing in the most failing checks

**Why this works:** With exactly one wrong value, every failing check must
involve that value. Every passing check proves its participants are correct.

## Output Format

**Read the task instruction carefully** for output requirements:

1. **Target file** — usually `/app/value.txt`
2. **Format** — usually `line_number,value`
3. **Symbol handling** — strip `%` and `$` unless instruction says otherwise
4. **Precision** — match the report's displayed precision
5. **Negatives** — convert `(45.2)` to `-45.2` unless instruction says otherwise

## Detecting Decimal Precision

Scan percentage values first (they usually state precision in a note), then
fall back to dollar values. Count digits after the decimal point.

## Adaptation Guide

### Report structure changes
- Different table layouts → parser handles any number of columns
- Multiple sections → parse all tables
- Different line numbering → don't assume a pattern

### Error type changes
- Wrong dollar value (subtotal/total) → additive checks catch it
- Wrong percentage (margin) → ratio checks catch it
- Wrong YoY change → add `(current - prior) / prior × 100` check
- Wrong per-share value → add `net_income / shares` check

### Output format changes
- Different target file → read instruction
- Different precision → match report's stated precision
- Commas/separators → preserve as displayed

## Verification Checklist

Before writing the answer:
1. ✓ All checks ran without errors
2. ✓ Exactly one value is identified as wrong
3. ✓ The wrong value appears in failing checks but not passing checks
4. ✓ Output format matches instruction exactly
5. ✓ Value is reported as displayed (not recomputed)
