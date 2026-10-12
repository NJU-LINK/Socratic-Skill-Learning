---
name: html-finance-verify
description: >
  Verify internal consistency of HTML financial reports and identify the single
  incorrect metric. Parses HTML tables containing financial statements and KPIs,
  builds accounting relationships (additive, subtractive, ratio), checks all
  relationships for consistency, and identifies the one metric that violates
  internal consistency. Outputs the line number and reported value of the
  incorrect metric.
---

# HTML Finance Verify

## Quick Start — Run the Bundled Solver

The fastest and most reliable approach is to run the pre-built solver:

```bash
python3 /skill/solve.py [html_file] [output_file]
```

- `html_file`: Path to the HTML report (read from task instruction)
- `output_file`: Path to write the answer (read from task instruction)

The solver handles HTML parsing, metric classification, relationship discovery
(both name-based and structural), consistency checking, and error identification.
It writes the answer in the correct format.

**Only if solve.py fails or produces no answer should you fall back to
implementing the methodology manually using the steps below.**

---

## Task Overview

Given an HTML financial report containing financial statements and/or KPI
sidebars, find the **single incorrect metric** by verifying internal financial
consistency. All metrics except one are internally consistent; the incorrect one
can be identified purely from arithmetic relationships within the report.

## Step 1: Parse the Task Instruction (Critical)

**Before examining the HTML, carefully read the task instruction to determine:**

- **HTML file path** — where to find the report (e.g., `/app/q2_earnings_report.html`)
- **Output file path** — where to write the answer (e.g., `/app/value.txt`)
- **Output format** — the exact format required (e.g., `line_number,value`)
- **Value formatting rules** — how to format the value:
  - Should percent signs be included or excluded?
  - How many decimal places? (detect from the report's own precision)
  - Should thousands separators be included or removed?
  - How should negative values be formatted? (minus sign vs parentheses)
- **What counts as the "incorrect" metric** — is it always a percentage KPI, or could it be a dollar amount?

**Example parsing:**
```
Task says: "write your answer to `/app/value.txt` as: `line_number,value`"
         + "Do not include a percent sign in `value`"
         + "Example output: `210,60.8`"

→ Output file: /app/value.txt
→ Format: {line_number},{value}
→ Value rules: no % sign, preserve decimal places as shown
```

## Step 2: Parse the HTML

Extract all tables from the HTML document. For each table row, identify:
- **Line number**: An integer displayed next to the metric
- **Metric name**: Text describing the financial item
- **Value**: Numeric value (may include `$`, `%`, commas, parentheses for negatives)

Use Python's `html.parser.HTMLParser` (standard library) to parse tables. Handle
both `<thead>` and `<tbody>` rows.

**Important:** Preserve the raw string representation of each value (e.g., `"60.8%"`, `"$1,234.5"`) — you'll need it for output formatting.

## Step 3: Detect Precision and Units

Before checking relationships, analyze the report to determine:

1. **Decimal precision**: Count decimal places in reported values. If margins show 1 decimal (e.g., `60.8%`), use 1 decimal for comparison. If EPS shows 2 decimals (e.g., `$1.23`), use 2.

2. **Unit consistency**: Check if all values use the same unit (millions, thousands, etc.). Look for notes like "Dollars in millions" or "Amounts in thousands". If units differ across tables, normalize before comparison.

3. **Rounding convention**: Determine how percentages are rounded. Common patterns:
   - Standard rounding: `round(value, decimals)`
   - Banker's rounding: round half to even
   - Truncation: floor to specified decimals

## Step 4: Classify Metrics (Name-Based Fast Path)

Categorize each metric by financial type using name-based pattern matching.
**Priority matters** — check specific patterns before general ones to avoid
false matches (e.g., "Sales and marketing" should NOT match "revenue/sales").

Key categories:
- **Income statement**: Revenue, COGS, Gross profit, OpEx items (R&D, S&M, G&A,
  D&A), Total OpEx, Operating income, EBITDA, Interest, Other income/expense,
  Pretax income, Income tax, Net income, EPS, Shares
- **Margins**: Gross, operating, net, EBITDA, FCF
- **Balance sheet**: Total assets, current assets, total liabilities, current
  liabilities, shareholders' equity, long-term debt, cash, receivables,
  inventory, payables, retained earnings
- **Cash flow**: Operating CF, investing CF, financing CF, net change in cash,
  CapEx, free cash flow
- **Growth metrics**: YoY change, QoQ change, growth rate
- **Other**: Per-share values, unit conversions

## Step 5: Build Financial Relationships (Two Layers)

### Layer 1: Name-Based Relationships (Fast Path)

Use categorized metrics to build relationships from known accounting identities:

**Income Statement:**
- Revenue − COGS = Gross Profit
- Σ OpEx items = Total OpEx
- Gross Profit − Total OpEx = Operating Income
- Operating Income + Other Income − Interest − Tax = Net Income
- Pretax Income − Tax = Net Income
- Operating Income + D&A = EBITDA

**Balance Sheet:**
- Total Assets = Total Liabilities + Shareholders' Equity
- Current Assets ≈ Cash + Receivables + Inventory

**Cash Flow:**
- Operating CF + Investing CF + Financing CF = Net Change in Cash
- Operating CF − CapEx = Free Cash Flow

**Ratios:**
- Profit / Revenue = Margin %
- Net Income / Shares = EPS

**Generic Discovery:**
- For any "total" metric not yet matched, try subsets of preceding dollar metrics
- For any percentage metric not yet matched, try all dollar-metric pairs

### Layer 2: Structural Discovery (Robust Backbone)

When name-based classification fails or returns 'unknown', use **sequential
structure and numerical cross-checks** to discover relationships:

1. **Contiguous block additive**: For each dollar metric at position i, check if
   it equals the sum of a contiguous block of preceding dollar metrics. This
   catches "total" lines even when the name doesn't contain "total".

2. **Sequential subtractive**: For each dollar metric at position i, check if it
   equals `dollar[j] - sum(dollar[j+1:i])` for some j < i. This catches profit
   lines (e.g., Gross Profit = Revenue - COGS) based on position alone.

4. **Ratio discovery**: For each percentage metric, try all pairs of dollar
   metrics to find `numerator / denominator × 100 ≈ percentage`.

This structural layer works **independently of naming conventions** and catches
relationships that name-based classification misses.

### Merge and Deduplicate

Merge relationships from both layers, deduplicating by relationship type and
line set. Structural relationships supplement (not replace) name-based ones.

## Step 6: Check All Relationships

For each relationship, compute the expected value and compare with the reported
value. Use **precision-aware tolerance**:

- **Dollar amounts**: Tolerance = 0.5 × 10^(−decimals), where decimals is the
  number of decimal places in the reported value. E.g., if value is `$1,234.56`,
  tolerance = 0.005. If value is `$842.0`, tolerance = 0.05.

- **Percentages**: Tolerance = 0.5 × 10^(−decimals), where decimals is the
  number of decimal places in the reported percentage. E.g., if value is `60.8%`,
  tolerance = 0.05. If value is `60.81%`, tolerance = 0.005.

- **Rounding check**: When comparing, round the expected value to the same
  precision as the reported value before comparison.

Record which relationships fail and which metrics are involved.

## Step 7: Identify the Error

**Primary strategy: Correction-based elimination**

For each metric involved in a failing relationship:
1. Compute what value it should have to fix each failing relationship it's in
2. If all required corrections agree on a single value, test whether correcting
   that metric makes ALL relationships pass
3. The metric whose correction resolves all failures is the answer

This correctly handles cascading failures (e.g., a wrong total causing both a
summation check and a downstream subtraction to fail).

**Fallback: Exhaustive single-metric elimination**

If correction-based elimination fails:
- For each metric, try replacing its value with every computable alternative
- Check if any replacement makes all relationships pass
- This catches edge cases where the correction value isn't directly computable



## Step 8: Format and Write Output

**Use the exact format specified in the task instruction.** Common patterns:

| Task says | Output format |
|-----------|---------------|
| `line_number,value` | `{line},{value}` |
| `line: value` | `{line}: {value}` |
| "write the line number and value" | Determine from context |

**Value formatting rules:**
- If task says "do not include a percent sign", strip `%` from the value
- Preserve the decimal precision as shown in the report
- Remove thousands separators (commas) unless explicitly required
- For negative values, use the format shown in the report (minus sign or parentheses)

**Example:**
```
Report shows: Line 210, Gross margin, 60.8%
Task says: "line_number,value" with "do not include a percent sign"
Output: 210,60.8
```

## Key Financial Accounting Identities

```
=== Income Statement ===
Revenue − COGS = Gross Profit
Σ OpEx items = Total OpEx
Gross Profit − Total OpEx = Operating Income
Operating Income + Other Income − Interest − Tax = Net Income
Pretax Income − Tax = Net Income
Operating Income + D&A = EBITDA

=== Balance Sheet ===
Total Assets = Total Liabilities + Shareholders' Equity
Current Assets = Cash + Receivables + Inventory + ...

=== Cash Flow ===
Operating CF + Investing CF + Financing CF = Net Change in Cash
Operating CF − CapEx = Free Cash Flow

=== Ratios ===
Profit / Revenue = Margin %
Net Income / Shares = EPS

```

## Edge Cases and Robustness

### Numeric Formatting
- **Comma-separated thousands**: `$1,200.0` → 1200.0
- **Parenthetical negatives**: `(50.0)` → -50.0
- **Mixed precision**: Some values may have 0 decimals, others 2 — handle each independently
- **Percentage vs decimal**: `60.8%` vs `0.608` — detect from context

### Structural Variation
- **Multiple tables**: Income statement and KPI sidebar may be separate tables
- **Non-standard names**: "Cost of goods sold" = COGS, "Selling" = S&M
- **Unknown metric names**: Structural discovery catches relationships even when
  name-based classification returns 'unknown'
- **Non-contiguous sums**: A total may sum non-adjacent line items
- **Duplicate line numbers**: Handled via list-based lookup

### Error Types
- **Error in dollar value**: Not always a percentage — could be a total, subtotal,
  or any line item
- **Error in percentage**: Margin, growth rate, or per-share percentage
- **Rounding error**: Value is off by rounding convention (rare but possible)
- **Unit conversion error**: Value is in wrong units (e.g., thousands vs millions)

### Output Format Variation
- **Different file paths**: May not always be `/app/value.txt`
- **Different delimiters**: May use `:` or `=` instead of `,`
- **Additional fields**: May require metric name or other metadata
- **Precision requirements**: May specify exact decimal places

## Implementation Notes

- Use only Python standard library (`html.parser`, `re`, `itertools`)
- No external dependencies (bs4, lxml, etc.) may not be available
- Parse HTML with `HTMLParser` subclass for table extraction
- Use regex for numeric extraction and metric name classification
- Two-layer relationship discovery: name-based (fast) + structural (robust)
- Correction-based error identification with exhaustive fallback
- **Dynamically parse task instruction for output format** — do not hardcode
- **Detect precision from reported values** — do not assume fixed tolerance
- The solver should be self-contained in a single Python script
