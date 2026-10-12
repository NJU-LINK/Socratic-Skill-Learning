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

## Task Overview

Given an HTML financial report containing financial statements and/or KPI
sidebars, find the **single incorrect metric** by verifying internal financial
consistency. All metrics except one are internally consistent; the incorrect one
can be identified purely from arithmetic relationships within the report.

## Methodology

### Step 1: Read the Task Instruction

Determine:
- **HTML file path** (e.g., `/app/q2_earnings_report.html`)
- **Output file path** (e.g., `/app/value.txt`)
- **Output format** (e.g., `line_number,value`)
- **Value formatting rules** (no percent sign, decimal precision, etc.)

### Step 2: Parse the HTML

Extract all tables from the HTML document. For each table row, identify:
- **Line number**: An integer displayed next to the metric
- **Metric name**: Text describing the financial item
- **Value**: Numeric value (may include `$`, `%`, commas, parentheses for negatives)

Use Python's `html.parser.HTMLParser` (standard library) to parse tables. Handle
both `<thead>` and `<tbody>` rows.

### Step 3: Classify Metrics (Name-Based Fast Path)

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
- **Other**: YoY changes, growth rates

### Step 4: Build Financial Relationships (Two Layers)

#### Layer 1: Name-Based Relationships (Fast Path)

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

#### Layer 2: Structural Discovery (Robust Backbone)

When name-based classification fails or returns 'unknown', use **sequential
structure and numerical cross-checks** to discover relationships:

1. **Contiguous block additive**: For each dollar metric at position i, check if
   it equals the sum of a contiguous block of preceding dollar metrics. This
   catches "total" lines even when the name doesn't contain "total".

2. **Sequential subtractive**: For each dollar metric at position i, check if it
   equals `dollar[j] - sum(dollar[j+1:i])` for some j < i. This catches profit
   lines (e.g., Gross Profit = Revenue - COGS) based on position alone.

3. **Ratio discovery**: For each percentage metric, try all pairs of dollar
   metrics to find `numerator / denominator × 100 ≈ percentage`.

This structural layer works **independently of naming conventions** and catches
relationships that name-based classification misses.

### Step 5: Merge and Deduplicate

Merge relationships from both layers, deduplicating by relationship type and
line set. Structural relationships supplement (not replace) name-based ones.

### Step 6: Check All Relationships

For each relationship, compute the expected value and compare with the reported
value. Use appropriate tolerance:
- **Dollar amounts**: ±0.15 (accounts for rounding to 1 decimal)
- **Percentages**: ±0.05 at the reported precision level

Record which relationships fail and which metrics are involved.

### Step 7: Identify the Error

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

### Step 8: Write Output

Format the output according to the task instruction:
- Extract the **reported** (incorrect) value as shown in the HTML
- Remove formatting characters (%, $, commas) as specified
- Write `line_number,value` to the output file

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

## Edge Cases

- **Comma-separated thousands**: `$1,200.0` → 1200.0
- **Parenthetical negatives**: `(50.0)` → -50.0
- **Rounding**: Margins rounded to 1 decimal place
- **Multiple tables**: Income statement and KPI sidebar may be separate tables
- **Non-standard names**: "Cost of goods sold" = COGS, "Selling" = S&M
- **Unknown metric names**: Structural discovery catches relationships even when
  name-based classification returns 'unknown'
- **Error in dollar value**: Not always a percentage — could be a total, subtotal,
  or any line item
- **Duplicate line numbers**: Handled via list-based lookup
- **Balance sheet / cash flow reports**: Patterns included for common items
- **Generic totals**: Subset-sum discovery for unmatched "total" lines

## Implementation Notes

- Use only Python standard library (`html.parser`, `re`, `itertools`)
- No external dependencies (bs4, lxml, etc.) may not be available
- Parse HTML with `HTMLParser` subclass for table extraction
- Use regex for numeric extraction and metric name classification
- Two-layer relationship discovery: name-based (fast) + structural (robust)
- Correction-based error identification with exhaustive fallback
- The solver should be self-contained in a single Python script
