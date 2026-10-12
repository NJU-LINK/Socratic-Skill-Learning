---
name: html-finance-verify
description: >
  Reusable method for verifying HTML financial reports containing line-numbered
  metrics. Parses any HTML table-based financial report, extracts all line-numbered
  values (dollar amounts and percentages), generates and evaluates financial
  relationship checks (ratio via exhaustive pair generation, additive/subtractive
  via subset-sum enumeration), and isolates the single incorrect metric using
  percentage ratio analysis or clustering-based correction consistency for dollar values.
---

# HTML Financial Report Verification

## Task Family

Given an HTML financial report with line-numbered metrics (dollar values and/or
percentages), find the **single incorrect reported metric** using internal
consistency cross-checks. All other values are internally consistent.

## General Approach

```
Parse HTML → Extract line-numbered values → Generate relationship checks
→ Evaluate checks → Isolate the incorrect value → Format output
```

### Stage 1: Parse and Extract

Parse the HTML document using Python's stdlib `html.parser`. Extract all table
rows (`<tr>`) and identify:
- **Line number**: a cell containing a small integer (typically 1-4 digits)
- **Metric name**: a cell with text (non-numeric)
- **Value**: a cell containing a financial number

Key parsing rules:
- Line numbers are integers in range [1, 9999]
- Dollar values may have `$` prefix, comma thousands separators, parentheses for negatives
- Percentages end with `%`
- Strip all formatting to get the raw numeric float

### Stage 2: Generate Relationship Checks

#### Ratio Checks (for percentages)
For **every** percentage entry, generate a check for **every** pair of dollar entries:
```
pct_line = dollar_A / dollar_B * 100
```
No filtering — generate ALL possible triples. A correct percentage will have at
least one matching pair (within evaluation tolerance); an incorrect percentage
will have **none**.

#### Subset-Sum Enumeration (for dollar values)
For each dollar entry, check if any subset of 2-4 OTHER dollar entries sums to
its value:
```
target = sum(subset of 2-4 other dollar entries)
```
This handles:
- **Additive relationships**: Total = A + B + C (components can be anywhere)
- **Subtractive relationships**: A = B - C is discovered as A + C = B
- **Non-contiguous components**: Works even when line items are interspersed

Use a **loose discovery tolerance** (10.0) to capture relationships even when
the target value has a large error. Evaluation uses **tight tolerance** (0.15)
to identify actual errors.

### Stage 3: Evaluate and Isolate

Evaluate all checks with a **tight tolerance** (0.15 for rounding to 1 decimal).

**Isolation strategy:**

1. **For percentages**: A correct percentage has ≥1 passing ratio check. An
   incorrect percentage has **zero** passing ratio checks. If exactly one
   percentage has no passing ratio check, it's the answer.

2. **For dollar values**: Use clustering-based correction consistency:
   - For each candidate line, compute what its value should be according to
     each failing check involving it
   - Find the largest cluster of corrections that are all within 0.3 of each other
   - The candidate with the largest consistent cluster (size ≥ 2) is the answer
   - This approach is robust to spurious relationships discovered by loose tolerance

### Stage 4: Format Output

Write the answer as `line_number,value` where:
- `line_number` is the line number shown in the report
- `value` is the incorrect numeric value as displayed, with formatting stripped
  (no $, commas, or % sign)

## Financial Relationship Catalog

| Type | Formula | Common Examples |
|------|---------|-----------------|
| Additive | A = B + C + ... | Total opex = R&D + S&M + G&A |
| Subtractive | A = B - C | Gross profit = Revenue - COGS; Operating income = Gross profit - Opex |
| Ratio | pct = A / B × 100 | Gross margin = Gross profit / Revenue; Net margin = Net income / Revenue |
| Multiplicative | A = B × C | EPS × Shares = Net income |

## Edge Cases and Robustness

- **Rounding tolerance**: Use 0.15 for evaluation (allows rounding to 1 decimal)
- **Parentheses for negatives**: `(123.4)` means `-123.4`
- **Comma thousands separators**: `$1,234.5` → `1234.5`
- **Percent signs**: Strip `%` before numeric comparison
- **Multiple tables**: Parse all tables in the document
- **Non-standard section names**: Don't hardcode — extract all line-numbered rows
- **Sparse line numbering**: Handle any line number scheme
- **Non-contiguous components**: Subset-sum enumeration finds relationships even when components are interspersed
- **Large errors**: Loose discovery tolerance (10.0) captures relationships with errors up to 10.0
- **Spurious relationships**: Clustering-based isolation filters out coincidental near-matches

## Script Usage

```bash
python3 scripts/verify_finance.py <html_path> <output_path> [--tolerance TOL]
```

The script handles all stages automatically and writes the answer to the output file.
