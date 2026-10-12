---
name: html-finance-verify
description: Identify incorrect financial metrics in HTML earnings reports by cross-checking internal consistency using three-valued logic and (a)+(b)+(c) culprit identification.
---

# html-finance-verify

## Quick Start (Use This First)

**From any working directory**, use the absolute path where skills are mounted:
```bash
python3 /skill/scripts/verify_report.py <input_html> <output_file>
```

**Or, if running from the skill directory:**
```bash
python3 scripts/verify_report.py <input_html> <output_file>
```

**Example:**
```bash
python3 /skill/scripts/verify_report.py /app/q2_earnings_report.html /app/value.txt
```

**Expected output on stdout:**
- Relationship check showing exactly one `[FAIL]` line
- "CANDIDATE" on exactly one metric
- "CULPRIT: Line X, Value 'Y'"
- Exit code 0

**Success indicators:**
- Single `[FAIL]` in relationship list ✓
- Single `CANDIDATE` in analysis ✓
- Exit code 0 ✓

**Failure modes (fall back to manual method):**
- Exit non-zero → check "ERROR" message
- "underdetermined" → multiple candidates, need more relationships or task hint
- Zero candidates → tolerance too strict or relationships incomplete

**Audit trail:** The script's stdout shows all calculations - verify the `[FAIL]` line matches the task's hint about which category is wrong (e.g., "only one KPI percentage is wrong").

---

## Purpose

Analyze HTML financial reports to find the single incorrectly reported metric. The error is discoverable through internal arithmetic relationships - sums, differences, and ratios between related values.

## Core Method

### Three-Valued Logic

Relationship checking produces three outcomes:
- **PASS**: Relationship holds within tolerance
- **FAIL**: Relationship violated (indicates inconsistency)
- **UNTESTABLE**: Missing operands (provides no information)

### (a)+(b)+(c) Culprit Identification Rule

A metric M is the incorrect one if and only if all three conditions hold:

- **(a)** Every relationship NOT involving M PASSES
- **(b)** Every TESTABLE relationship involving M FAILS
- **(c)** M participates in at least one TESTABLE relationship

This rule uses the FULL metric set; involvement is determined by filtering, not by removal. The key insight: co-operands of a single failing equation are indistinguishable without additional independent relationships pinning them.

### Identifiability Principle

Unique blame requires every candidate to be pinned by at least one independent relationship. When multiple candidates satisfy (a)+(b)+(c), the error is underdetermined - look for:
- Additional relationships in the document (subtotals, ratios, YoY changes)
- Instruction text that constrains which category is wrong (e.g., "only one KPI percentage is wrong")

## Implementation Steps

### 1. Parse HTML Report

Extract (line, name, value) triples from tables:
- Detect columns from header row first (look for "Line", "Metric", "Value")
- Fallback: detect line-number column by content shape (all bare integers)
- Preserve original value display format for output

### 2. Normalize Metric Names

Convert to canonical forms for relationship matching:
```
revenue: revenue, total revenue, net sales, sales
cost_of_revenue: cost of revenue, COGS, cost of sales
gross_profit: gross profit, gross income
total_op_expenses: total operating expenses
operating_income: operating income, operating profit
net_income: net income, net profit, earnings
# ... etc
```

Order matters: check exact matches first, then substring matches, with more specific patterns before general ones.

### 3. Define Relationships

Enumerate all checkable internal relationships:
- **Sums**: total_op_expenses = R&D + sales + G&A
- **Differences**: gross_profit = revenue - cost_of_revenue
- **Ratios**: gross_margin = (gross_profit / revenue) × 100
- **Cascading**: operating_income = gross_profit - total_op_expenses

### 4. Apply (a)+(b)+(c) Rule

For each metric M:
1. Check (c): Does M participate in any TESTABLE relationship?
2. Check (a): Do all relationships NOT involving M PASS?
3. Check (b): Do all TESTABLE relationships involving M FAIL?

If exactly one metric satisfies all three, that's the culprit.

### 5. Format Output

Extract the value as displayed, stripping only unit symbols:
- Remove: $, €, £, %, whitespace
- Preserve: digits, decimal points, negative signs, thousands separators
- Format: `line_number,value` (no extra text)

## Tolerance Guidelines

- Dollar values: ±0.01 absolute, or relative tolerance 0.1%
- Percentages rounded to 1 decimal: ±0.06 (accounts for display rounding)
- Ratios: depends on precision of inputs

## Family Invariants

1. **Single Error**: Exactly one metric is incorrect
2. **Internal Consistency**: The incorrect value can be discovered from relationships within the document
3. **Line Numbering**: The incorrect metric has a visible line number
4. **Deterministic Answer**: Given complete relationships, answer is unique

## Expected Variations

### Report Structure
- Table layouts: column reordering, different section names
- Line numbering: different starting points, densities
- HTML structure: different class names, element nesting

### Error Types
- Dollar amounts: totals, subtotals, components
- Percentages: margins, growth rates, per-share values
- Calculated values: any derived metric

## Coverage Boundaries

### Multi-Period Tables (REFUSE)
Tables with multiple value columns (e.g., "Q2 2025", "Q1 2025") without an explicit "Value" header will raise:
```
ValueError: Ambiguous value columns detected: N columns contain numeric/financial data...
```
**Action**: Extend parser to treat each period column as distinct metric keyed `name (period)`, then add `GrowthRelationship` and `PerShareRelationship` templates.

### Supported
- Single-period reports with explicit "Value" column
- Single-period reports with single value-like column (inferred)

### Output Constraints
- Target file path
- Numeric precision requirements
- Handling of: decimals, negatives, thousands separators

## Acceptance Test (Mutant Suite)

| Input | Expected Result |
|-------|----------------|
| v01 (original) | `210,60.8` |
| err230 (net margin wrong) | `230,27.3` |
| err_total (total opex wrong) | `170,285.6` |
| err_rd (R&D component wrong) | REFUSE with candidates {140,150,160} |
| err_reorder (columns swapped) | `210,60.8` |
| err_4col (multi-period) | REFUSE with "Ambiguous value columns" |

The R&D case demonstrates correct underdetermination. The 4-column case demonstrates parser coverage boundary - multi-period tables require extension.

## Common Pitfalls

1. **Using external data**: Never check against "real" market data
2. **Wrong tolerance**: ±0.1 for percentages rounded to 1 decimal is too loose; use ±0.06
3. **Float round-trip**: Don't convert output through float; strip symbols only
4. **Removal vs filtering**: (a)+(b)+(c) filters on full data; removal causes false candidates
5. **Missing operands**: UNTESTABLE must not count as PASS or FAIL

## Tool Dependencies

- `html.parser.HTMLParser` (stdlib) for robust HTML parsing
- `re` for name normalization and value cleaning
- No external dependencies required
