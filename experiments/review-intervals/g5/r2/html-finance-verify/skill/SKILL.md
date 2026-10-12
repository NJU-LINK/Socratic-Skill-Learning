---
name: html-finance-verify
description: Find the single incorrect metric in an HTML financial report via internal consistency checks.
---

# HTML Financial Verification

Detect and report the single incorrect metric in an HTML earnings report by discovering and checking internal financial relationships.

## Quick Start

The skill package provides a Python script at **`/skill/scripts/verify_finance.py`** (mounted read-only inside the task container).

**Step 1**: Read `task.yaml` (in the host workspace, not `/app`) to determine the HTML file path and output file path.

**Step 2**: Run the script inside the container:
```bash
python3 /skill/scripts/verify_finance.py <html_file> <output_file>
```

For v01-style tasks:
```bash
python3 /skill/scripts/verify_finance.py /app/q2_earnings_report.html /app/value.txt
```

**Step 3**: Verify the output:
```bash
cat /app/value.txt
```

The output format is `line_number,value` (e.g., `210,60.8`).

## Problem Structure

HTML financial reports contain:
- **Income statement** with dollar-denominated line items (revenue, expenses, profits)
- **KPI sidebar** with derived percentages (margins, growth rates, ratios)
- **Line numbers** identifying each metric
- **Exactly one incorrect value** that violates internal consistency

All other values are internally consistent. The task is to find which single metric is wrong.

## Algorithm

### Step 1: Parse HTML → Extract Entries

Use `html.parser.HTMLParser` (stdlib) to extract `(line_number, label, numeric_value)` triples from table rows. Handle formatting:
- Strip `$`, `%`, `,` from numeric values
- Detect percentages via `%` symbol or label keywords (margin, rate, ratio, yield, growth, change)

**Fallback**: If HTMLParser finds no entries, use regex pattern matching.

### Step 2: Discover Financial Relationships

**Additive relationships** (sum and difference):
- **Sum**: `Total = Component1 + Component2 + ...` (e.g., Total OpEx = R&D + S&M + G&A)
- **Difference**: `Result = Positive - Negative` (e.g., Gross Profit = Revenue - COGS)

Discovery: label heuristics ("total", "subtotal", "gross profit", "operating income", "net income") + structure-aware enumeration (prefers line-number proximity) + brute-force fallback (sizes 2–5, limited to nearby lines to avoid spurious matches).

**Ratio relationships** (percentage calculations):
- `Percentage = (Numerator / Denominator) × 100`
- Flexible label matching with precise rules:
  - "X margin" → "X profit/income" / Revenue (e.g., "gross margin" → "gross profit", "operating margin" → "operating income")
  - "X rate" or "X ratio" → X / Revenue
  - "X as % of Y" → X / Y
- Exhaustive fallback for unmatched percentages: try all (numerator, denominator) pairs within ±2% tolerance.

### Step 3: Check Relationships → Satisfied vs Violated

For each discovered relationship, check if it holds within tolerance:
- **Dollar values**: `abs(calculated - reported) < 0.1`
- **Percentages**: `abs(round(calculated, 1) - reported) < 0.05`

### Step 4: Score and Find the Incorrect Value

**Scoring algorithm**: For each entry:
1. If it appears in **any satisfied relationship** → it's correct (skip)
2. If it appears in **every violated relationship** → it's the incorrect value

**Fallback scoring**: If primary algorithm finds no unique candidate, pick the value with highest `(violated_participation - satisfied_participation)` score.

**Why this works**: With exactly one wrong value:
- The incorrect value appears in all violated relationships (its wrong value breaks them)
- The incorrect value appears in NO satisfied relationships (it's wrong, so no correct relationship depends on it)
- Correct values in violated relationships also appear in other satisfied relationships

### Step 5: Output

Write `line_number,value` to the output file. Strip `%` sign. Preserve original numeric formatting.

## Manual Fallback

If the script fails or produces no result, perform manual verification:

1. **Read the HTML** and extract all line items
2. **Check additive relationships**:
   - Revenue - COGS = Gross Profit
   - Sum of operating expense components = Total OpEx
   - Gross Profit - Total OpEx = Operating Income
   - Operating Income + Other Income = Net Income
3. **Check ratio relationships**:
   - Gross Margin = Gross Profit / Revenue × 100
   - Operating Margin = Operating Income / Revenue × 100
   - Net Margin = Net Income / Revenue × 100
4. **Identify the violation**: The value that doesn't match its expected calculation is the incorrect metric
5. **Write** `line_number,displayed_value` to the output file

## Implementation Details

### Relationship Representation

Additive relationships use typed tuples:
```python
('sum', result_line, [component_lines])
('diff', result_line, positive_line, negative_line)
```

Ratio relationships use 3-tuples:
```python
(percentage_line, numerator_line, denominator_line)
```

### Tolerance and Rounding

- Dollar values: ±0.1 tolerance (handles rounding to 1 decimal place)
- Percentages: Round calculated value to 1 decimal, then ±0.05 tolerance
- Use `round(value, 1)` before comparison, not just `abs(a - b) < tol`

### Edge Cases

1. **Percentage is wrong, all dollars correct**: The violated ratio relationship identifies the wrong percentage
2. **Dollar value is wrong, percentages correct**: The violated additive relationship identifies the wrong dollar value
3. **Multiple equivalent relationships**: The scoring algorithm handles ambiguity by requiring the incorrect value to appear in ALL violated relationships

## Variation Handling

**report_structure_and_metric_relationships**:
- Arbitrary table structure (multiple tables, different section names)
- Different metric families (EBITDA, free cash flow, per-share values)
- Various line numbering schemes
- Different arithmetic/ratio relationships

**error_type_and_discoverability**:
- Totals, subtotals, margins, YoY changes, per-share values
- Unit conversions, rounded figures
- Error discoverable via internal consistency (no external knowledge needed)

**output_format_constraints**:
- Different target files (parameterized via command-line argument)
- Various numeric precision (handled by preserving original formatting)
- Comma/whitespace robustness (stripped during parsing)
- Decimals, negatives, percentages, thousands separators (all handled)

## Dependencies

- Python 3 stdlib only: `html.parser`, `re`, `itertools`, `sys`
- No external packages required
- Script is at `/skill/scripts/verify_finance.py` inside the task container
