---
name: html-finance-verify
description: Identify a single incorrect metric in an HTML financial report by checking internal consistency across all reported values
---

# HTML Financial Report Verification

Find the single incorrect metric in an HTML financial report by verifying internal consistency.

## Quick Start

**For simple reports (standard metric names, <15 metrics):**
1. Extract all metrics from HTML tables (line number, name, value)
2. Verify dollar relationships: subtotals = sum of components
3. Verify percentage relationships: margin = component / revenue × 100
4. The metric that fails verification is the error
5. Write `line_number,value` to output file

**For complex reports (renamed metrics, unusual structure, >15 metrics):**
Use the provided `verify.py` script:
```bash
python3 verify.py /app/report.html /app/value.txt
```

## Core Algorithm: Two-Phase Classification

For each metric, attempt to derive it from other metrics:
- **CONFIRMED**: Derivation matches reported value (within tolerance)
- **CONTRADICTED**: Derivation exists but disagrees → **THIS IS THE ERROR**
- **UNCHECKED**: No derivation applies (independent line items, correctly ignored)

**Critical:** Distinguish UNCHECKED from CONTRADICTED. A metric with no derivation rules is not an error — it's just independent.

## Financial Relationships

### Income Statement
- Gross profit = Revenue - Cost of revenue
- Total operating expenses = Sum of individual expenses (R&D + S&M + G&A)
- Operating income = Gross profit - Total operating expenses
- Net income = Operating income + Other income

### Margin Ratios
- Gross margin = Gross profit / Revenue × 100
- Operating margin = Operating income / Revenue × 100
- Net margin = Net income / Revenue × 100

### Per-Share Metrics
- EPS = Net income / Shares outstanding

**For each relationship, implement forward AND reverse derivations** to maximize cross-checking coverage.

## Tolerance Handling

- **Dollar values**: 0.05 (for values in millions)
- **Percentages**: 0.15 (for rounded-to-one-decimal percentages)

## Common Pitfalls

1. **Conflating UNCHECKED with CONTRADICTED**: Only CONTRADICTED metrics are errors
2. **Substring collisions**: Use word boundary matching (`\b` + pattern + `\b`) to avoid false matches (e.g., 'sales' in 'net sales')
3. **Leave-one-out closure trap**: When checking if target satisfies a property, check target directly — don't search for it in a collection built from `others` (which excludes target)
4. **Missing reverse derivations**: For A = B - C, also implement B = A + C and C = B - A

## Output Format

Write `line_number,value` where:
- `line_number`: Line number shown in report
- `value`: Incorrect numeric value as displayed (no currency symbols or percent signs)

## When to Use Each Approach

**Manual verification** (for simple cases):
- Standard metric names (Revenue, Gross profit, etc.)
- <15 metrics
- Clear income statement + KPI structure
- You can verify all relationships by hand

**verify.py script** (for complex cases):
- Renamed metrics (e.g., "Net sales" instead of "Revenue")
- Unusual structure or many tables
- >15 metrics
- Need automated verification
