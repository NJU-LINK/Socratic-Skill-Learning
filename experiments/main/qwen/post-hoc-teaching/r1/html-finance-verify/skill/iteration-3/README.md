# HTML Finance Verify Skill Package

## Overview

This skill package solves HTML financial verification tasks: given an HTML report with line-numbered financial metrics, find the single incorrect metric by verifying internal consistency.

## Package Contents

- **SKILL.md**: Comprehensive skill documentation with methodology, algorithms, and code examples
- **solve.py**: Complete Python implementation that can be executed directly
- **README.md**: This file

## How to Use

### Quick Start

```bash
# Copy solve.py to the task environment
cp /skill/solve.py /app/solve.py

# Run the solver
cd /app && python3 solve.py

# Check the result
cat /app/value.txt
```

### What It Does

1. **Parses HTML**: Extracts all metrics with line numbers, names, and values
2. **Discovers relationships**: Identifies additive (sums) and ratio (percentages) relationships
3. **Verifies consistency**: Checks all relationships for internal consistency
4. **Finds the error**: Identifies the single metric that violates consistency
5. **Outputs result**: Writes `line_number,value` to `/app/value.txt`

## Supported Relationship Types

### Additive Relationships
- Gross profit = Revenue − Cost of revenue
- Total operating expenses = Sum of OpEx components
- Operating income = Gross profit − Total operating expenses
- Net income = Operating income + Other income − Taxes

### Ratio Relationships
- Gross margin = Gross profit / Revenue × 100
- Operating margin = Operating income / Revenue × 100
- Net margin = Net income / Revenue × 100
- Other percentage-based KPIs

## Variation Handling

The skill handles variations in:

1. **Report structure**: Different table layouts, section names, metric organizations
2. **Error types**: Errors in totals, subtotals, margins, growth rates, per-share values
3. **Output formats**: Different target files, numeric precision, formatting requirements

## Algorithm Details

### Parsing Strategy
- Regex-based extraction of table rows with line numbers
- Flexible numeric parsing (handles $, %, commas, negatives, unit suffixes)
- Works with various HTML structures (tables, divs, spans)

### Relationship Discovery
- **Name-based**: Recognizes standard financial metric names and their relationships
- **Value-based**: Detects additive patterns by checking if A + B ≈ C
- **Ratio-based**: Matches percentages to numerator/denominator pairs

### Error Identification
- Checks all discovered relationships
- Uses majority voting when multiple relationships are violated
- Prioritizes percentage errors when dollar values are consistent
- Falls back to exhaustive search if standard patterns fail

## Tolerance and Rounding

- Dollar values: ±0.15 tolerance (accounts for rounding in chained calculations)
- Percentages: ±0.15 percentage points tolerance
- Handles values rounded to 0 or 1 decimal place

## Example

**Input HTML** (simplified):
```html
<table>
  <tr><td class="line">110</td><td>Revenue</td><td class="num">$842.0</td></tr>
  <tr><td class="line">120</td><td>Cost of revenue</td><td class="num">$321.6</td></tr>
  <tr><td class="line">130</td><td>Gross profit</td><td class="num">$520.4</td></tr>
  ...
  <tr><td class="line">210</td><td>Gross margin</td><td class="num">60.8%</td></tr>
</table>
```

**Output** (`/app/value.txt`):
```
210,60.8
```

**Explanation**: Gross margin should be 520.4/842.0 × 100 = 61.8%, but the report shows 60.8%.

## Testing

Tested on v01 seed task:
- ✓ Correctly identifies line 210 (Gross margin) as incorrect
- ✓ Outputs value 60.8 (the incorrect reported value)
- ✓ Handles HTML parsing, relationship discovery, and error identification

## Extensibility

The skill can be extended to handle:
- Balance sheet relationships (Assets = Liabilities + Equity)
- Cash flow statement relationships
- Multi-period comparisons (YoY, QoQ growth)
- Per-share calculations (EPS, book value per share)
- Segment reporting consistency

## Key Principles

1. **Internal consistency only**: All errors are discoverable from relationships within the report
2. **Exactly one error**: The task always has a single incorrect metric
3. **Cross-check everything**: Verify all possible relationships
4. **Report the wrong value**: Output the value as displayed, not the corrected value
5. **Respect formatting**: Follow exact output format specifications

## Common Pitfalls Avoided

- Confusing which metric is wrong when multiple participate in a failed check
- Forgetting rounding tolerance when comparing computed vs. reported values
- Missing relationships when component names vary
- Including formatting characters in output
- Not handling different HTML structures

## References

- Task specification: `spec.yaml`
- Seed task: `train/v01/task.yaml`
- Skill documentation: `SKILL.md`
