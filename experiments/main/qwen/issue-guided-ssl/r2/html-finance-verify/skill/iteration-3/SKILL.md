---
name: html-finance-verify
description: >
  Reusable method for verifying HTML financial reports containing line-numbered
  metrics. Parses any HTML financial report (table-based or non-table structures
  like divs/spans), extracts all line-numbered values (dollar amounts and
  percentages, including unit suffixes K/M/B), generates and evaluates comprehensive
  financial relationship checks (margin-style ratios, YoY growth rates,
  additive/subtractive subset-sums, per-share divisions, and multiplicative
  relationships), and isolates the single incorrect metric using percentage analysis
  or clustering-based correction consistency for dollar values.
---

# HTML Financial Report Verification

## Task Family

Given an HTML financial report with line-numbered metrics (dollar values and/or
percentages), find the **single incorrect reported metric** using internal
consistency cross-checks. All other values are internally consistent.

## Operational Instructions for Solver

**IMPORTANT**: All file operations in `/app` must use `task_shell`, NOT workspace tools.
- ✅ Use `task_shell` to: read files in /app, run the verification script, write output
- ❌ Do NOT use `read`, `ls`, `find`, or `write` tools for `/app` paths (will get WORKSPACE_BOUNDARY errors)

Example workflow:
```bash
# Read the HTML file
task_shell: cat /app/q2_earnings_report.html

# Run the verification script
task_shell: python3 /skill/scripts/verify_finance.py /app/q2_earnings_report.html /app/value.txt

# Check the output
task_shell: cat /app/value.txt
```

## General Approach

```
Parse HTML → Extract line-numbered values → Generate relationship checks
→ Evaluate checks → Isolate the incorrect value → Format output
```

### Stage 1: Parse and Extract

The parser uses a **two-tier approach** for maximum robustness:

1. **Table-based extraction** (primary): Parses `<table>/<tr>/<td>/<th>` structures
2. **Generic extraction** (fallback): If no table entries found, extracts text nodes
   and looks for patterns of (line_number, metric_name, value) in consecutive elements

This handles both traditional table-based reports and modern div/span-based layouts.

Key parsing rules:
- Line numbers are integers in range [1, 9999]
- Dollar values may have `$` prefix, comma thousands separators, parentheses for negatives
- Percentages end with `%`
- Unit suffixes: `K` (thousands), `M` (millions), `B` (billions) are multiplied appropriately
- Strip all formatting to get the raw numeric float

### Stage 2: Generate Relationship Checks

#### Ratio Checks (margin-style percentages)
For **every** percentage entry, generate a check for **every** pair of dollar entries:
```
pct_line = dollar_A / dollar_B * 100
```
This handles margin-style percentages like gross margin, operating margin, net margin.

#### Growth Checks (YoY-style percentages)
For **every** percentage entry, generate a check for **every** pair of dollar entries:
```
pct_line = (dollar_A - dollar_B) / dollar_B * 100
```
This handles year-over-year growth rates, period-over-period changes.

#### Subset-Sum Enumeration (additive/subtractive for dollar values)
For each dollar entry, check if any subset of 2-4 OTHER dollar entries sums to
its value:
```
target = sum(subset of 2-4 other dollar entries)
```
This handles:
- **Additive relationships**: Total = A + B + C (components can be anywhere)
- **Subtractive relationships**: A = B - C is discovered as A + C = B
- **Non-contiguous components**: Works even when line items are interspersed

#### Division Checks (per-share-style for dollar values)
For each dollar entry, check if it equals any pair of other dollar entries divided:
```
value = dollar_A / dollar_B
```
This handles per-share calculations like EPS = Net Income / Shares Outstanding.

#### Multiplicative Checks (for dollar values)
For each dollar entry, check if it equals any pair of other dollar entries multiplied:
```
target = dollar_A * dollar_B
```
This handles unit conversions and other multiplicative relationships.

**Discovery tolerance**: Use a loose tolerance (10.0) for subset-sum, division, and
multiplicative checks to capture relationships even when the target value has a large
error. Evaluation uses **tight tolerance** (0.15) to identify actual errors.

### Stage 3: Evaluate and Isolate

Evaluate all checks with a **tight tolerance** (0.15 for rounding to 1 decimal).

**Isolation strategy (3-tier fallback):**

1. **For percentages**: A correct percentage has ≥1 passing check of any applicable
   type (ratio or growth). An incorrect percentage has **zero** passing checks of
   either type. If exactly one percentage has no passing checks, it's the answer.

2. **For dollar values**: Use clustering-based correction consistency:
   - For each candidate line, compute what its value should be according to
     each failing check involving it (any applicable type: additive, division, multiplicative)
   - Find the largest cluster of corrections that are all within 0.3 of each other
   - **Critical filter**: The cluster mean must be significantly different from the
     actual value (>0.5 difference). This filters out spurious relationships where
     the candidate is actually correct.
   - The candidate with the largest valid cluster (size ≥ 2) is the answer

3. **Fallback**: If approaches 1-2 fail, pick the line that appears in the most
   failing checks across all types.

### Stage 4: Format Output

Write the answer as `line_number,value` where:
- `line_number` is the line number shown in the report
- `value` is the incorrect numeric value as displayed, with formatting stripped
  (no $, commas, %, or unit suffixes)

## Financial Relationship Catalog

| Type | Formula | Common Examples |
|------|---------|-----------------|
| Ratio (margin) | pct = A / B × 100 | Gross margin = Gross profit / Revenue |
| Growth (YoY) | pct = (A - B) / B × 100 | Revenue growth = (Current - Prior) / Prior × 100 |
| Additive | A = B + C + ... | Total opex = R&D + S&M + G&A |
| Subtractive | A = B - C | Gross profit = Revenue - COGS |
| Division (per-share) | value = A / B | EPS = Net Income / Shares Outstanding |
| Multiplicative | A = B × C | Revenue in thousands = Revenue in millions × 1000 |

## Edge Cases and Robustness

- **HTML structure flexibility**: Handles both table-based and div/span-based layouts
- **Rounding tolerance**: Use 0.15 for evaluation (allows rounding to 1 decimal)
- **Parentheses for negatives**: `(123.4)` means `-123.4`
- **Comma thousands separators**: `$1,234.5` → `1234.5`
- **Percent signs**: Strip `%` before numeric comparison
- **Unit suffixes**: `1.5K` → `1500.0`, `2.3M` → `2300000.0`, `1.1B` → `1100000000.0`
- **Multiple tables**: Parse all tables in the document
- **Nested tables**: Handles nested table structures correctly
- **Non-standard section names**: Don't hardcode — extract all line-numbered rows
- **Sparse line numbering**: Handle any line number scheme
- **Non-contiguous components**: Subset-sum enumeration finds relationships even when components are interspersed
- **Large errors**: Loose discovery tolerance (10.0) captures relationships with errors up to 10.0
- **Spurious relationships**: Clustering-based isolation with mean-difference filter removes coincidental near-matches
- **No percentages**: Works correctly with only dollar values
- **Single percentage**: Works correctly with only one percentage entry

## Script Usage

```bash
python3 scripts/verify_finance.py <html_path> <output_path> [--tolerance TOL]
```

The script handles all stages automatically and writes the answer to the output file.
