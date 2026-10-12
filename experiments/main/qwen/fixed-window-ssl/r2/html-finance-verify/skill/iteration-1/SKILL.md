---
name: html-finance-verify
description: >
  Verify internal consistency of an HTML financial report, identify the single
  incorrect metric, and write its line number and reported value to the
  specified output file. Handles arbitrary table structures, metric families,
  line numbering, and relationship types (subtotals, margins, year-over-year
  changes, per-share figures) by parsing all labeled numeric values,
  reconstructing verifiable accounting identities via both named-pattern and
  generic detection, and using an intersection algorithm to isolate the one
  wrong value.
---

# HTML Finance Verify

## Task Family

Given an HTML financial report, find the single incorrect metric and output its
line number and reported value. The report contains financial data that is
internally consistent except for exactly one wrong value.

## Architecture Overview

The solution has four stages:

1. **Parse** — Extract all labeled numeric values with line numbers from HTML
2. **Detect relationships** — Build verifiable accounting identities
3. **Cross-check** — Compare expected vs. reported for each identity
4. **Isolate** — Use intersection algorithm to find the single wrong value

## Stage 1: HTML Parsing

Use Python's stdlib `html.parser.HTMLParser`. Track table boundaries so you
know which rows belong to which table. For each row, extract:
- **Line number** (from cells with `class="line"` or cells containing only digits)
- **Metric name** (the text label)
- **Raw value** (the displayed number with $ or % symbols)
- **Value type** (dollar, percentage, or plain number)

```python
from html.parser import HTMLParser

class FinancialTableParser(HTMLParser):
    # Track: tables > rows > cells
    # For each cell: text content + CSS class
    # When </tr>: try to extract (line_num, metric_name, raw_value)
    # When </table>: finalize the table
```

Parse numeric values by stripping `$`, `%`, commas, whitespace. Handle
parenthetical negatives: `(123.4)` → `-123.4`.

## Stage 2: Relationship Detection

Use **two layers** of detection:

### Layer A: Named-pattern checks (fast, precise when they match)

Check for well-known metric names and their standard relationships:

| Relationship | Formula |
|---|---|
| Gross profit | Revenue − Cost of revenue |
| Total opex | Sum of R&D + S&M + G&A (and similar leaf expenses) |
| Operating income | Gross profit − Total operating expenses |
| Net income | Operating income + Other income/expenses |
| Gross margin | (Gross profit / Revenue) × 100 |
| Operating margin | (Operating income / Revenue) × 100 |
| Net margin | (Net income / Revenue) × 100 |

Match metric names case-insensitively with flexible keywords:
- "revenue" / "sales" / "total revenue"
- "cost of revenue" / "cost of sales" / "COGS"
- "gross profit" / "gross earnings"
- "total operating expenses" / "total opex"
- "operating income" / "operating earnings" / "EBIT"
- "net income" / "net earnings"
- "gross margin" / "gross profit margin"
- etc.

### Layer B: Generic detection (catches variants with unfamiliar names)

**Generic additive detection:**
For any row whose name contains "total" (case-insensitive), sum all
preceding "leaf expense" rows in the same table. A leaf expense is a
dollar row whose name does NOT contain: total, sum, profit, income,
margin, revenue, gross, operating, net, earnings, other.

**Generic subtraction detection:**
For the specific pattern "operating income = gross profit − total opex",
look for these three metrics by keyword matching.

**Generic ratio detection:**
For each percentage value, try all pairs of dollar values as
(numerator, denominator) and find the best match. To avoid spurious
matches, prefer the largest dollar value as denominator (likely revenue)
by trying only the top 3 largest values as denominators.

**Important:** Record ALL generated checks, not just the ones that pass.
The cross-check in Stage 3 needs to see both passing and failing checks.

## Stage 3: Cross-Check

For each relationship check:
1. Compute the expected value from the other reported values
2. Round to the report's stated decimal precision (detect from the data)
3. Compare: `abs(expected - reported) <= tolerance`

**Tolerance:** Half the unit of the last displayed digit.
- 1 decimal place → tolerance = 0.05
- 2 decimal places → tolerance = 0.005
- General: `0.5 × 10^(-decimals)`

**Rounding:** Use `Decimal` with `ROUND_HALF_UP` to match typical financial
reporting (Python's built-in `round()` uses banker's rounding).

## Stage 4: Isolate the Wrong Value

Use the **intersection algorithm with passing-check filtering**:

1. Collect the set of line numbers involved in each **failing** check
2. Compute the **intersection** of all failing-check sets
3. **Eliminate** any candidate that appears in a **passing** check
   (if it were wrong, those passing checks would also fail)
4. If exactly one candidate remains → that's the answer
5. If multiple remain → pick the one appearing in the most failing checks

**Why this works:** With exactly one wrong value, every failing check must
involve that value. Every passing check proves its participants are correct.
The intersection + filtering uniquely identifies the wrong value in practice.

## Output Format

**Critical: Parse the task instruction for output requirements before writing the answer.**

The output format is NOT invariant across the family. The task instruction specifies:

1. **Target file** — Usually `/app/value.txt`, but may vary
2. **Format pattern** — Usually `line_number,value`, but check for variations
3. **Symbol handling** — Does it say "Do not include a percent sign"? "Do not include a dollar sign"? Or does it say "Include the dollar sign"?
4. **Numeric format** — Should the value be "as shown" in the report, or in a specific format?
5. **Precision** — Does it require a specific number of decimal places?
6. **Negative values** — If the wrong value is negative, should it be `-45.2` or `(45.2)`?
7. **Commas** — Should thousands separators be preserved or removed?

**Common patterns:**
- Percentages: strip `%` sign, output numeric value (e.g., `60.8` not `60.8%`)
- Dollars: usually strip `$` sign, output numeric value (e.g., `842.0` not `$842.0`)
- Preserve the precision as displayed in the report
- Handle parenthetical negatives: convert `(45.2)` to `-45.2` unless instruction says otherwise

**Implementation:**
```python
def format_output(wrong_row, task_instruction):
    """Format the wrong value for output based on task requirements."""
    raw = wrong_row["raw"].strip()
    
    # Parse task instruction for specific requirements
    # (This is a placeholder — adapt based on actual instruction text)
    
    # Default: strip common symbols
    value = raw.replace("%", "").replace("$", "").replace(",", "").strip()
    
    # Handle parenthetical negatives
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    
    return value
```

**Before writing the answer, re-read the task instruction and verify:**
- ✓ Target file path
- ✓ Format pattern (e.g., `line_number,value`)
- ✓ Symbol handling (strip or keep `$`, `%`)
- ✓ Numeric format (as shown vs. specific format)
- ✓ Precision requirements
- ✓ Negative value format

## Detecting Decimal Precision

Scan percentage values first (they usually state precision in a note),
then fall back to dollar values. Count digits after the decimal point.

## Adaptation Guide for Variants

### Report structure changes
- Different table layouts → parser handles any number of columns
- Multiple sections → parse all tables
- Different line numbering → don't assume a pattern

### Error type changes
- Wrong dollar value (subtotal/total) → additive checks catch it
- Wrong percentage (margin) → ratio checks catch it
- Wrong YoY change → add `(current - prior) / prior × 100` check
- Wrong per-share value → add `net_income / shares` check
- Wrong unit conversion → check if values are in millions vs actual

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
