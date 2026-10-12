---
name: html-finance-verify
description: Identify a single incorrect metric in an HTML financial report by checking internal consistency across all reported values using two-phase arithmetic verification
---

# HTML Financial Report Verification

This skill identifies a single incorrect metric in an HTML financial report by systematically checking internal consistency across all reported values.

## Core Algorithm: Two-Phase Consistency Check

The verification uses a two-phase approach to avoid false positives:

### Phase 1: Classification
For each metric in the report, attempt to derive it from other metrics using known financial relationship patterns. Classify each metric as:
- **CONFIRMED**: At least one derivation matches the reported value within tolerance
- **CONTRADICTED**: Derivation rules exist but disagree with the reported value
- **UNCHECKED**: No derivation rules apply (independent line items)

### Phase 2: Error Identification
The single CONTRADICTED metric is the error. This approach correctly distinguishes between:
- Metrics that are mathematically consistent (CONFIRMED)
- Metrics with no derivable relationships (UNCHECKED - correctly ignored)
- The one metric that violates consistency (CONTRADICTED - the error)

## Implementation Strategy

### 1. HTML Parsing
Use Python's built-in `html.parser.HTMLParser` to extract structured data from tables:
- Parse all `<table>` elements
- Extract rows with at least 3 cells (line number, metric name, value)
- Skip header rows
- Handle various table structures and layouts

### 2. Numeric Value Parsing
Parse values robustly to handle:
- Dollar amounts: `$842.0`, `$1,234.56`
- Percentages: `60.8%`, `28.5%`
- Negatives: `(123.4)` or `-123.4`
- Thousands separators: `$1,000,000`

### 3. Financial Relationship Patterns
Implement derivation rules for common financial relationships. For each relationship, implement both forward and reverse derivations to maximize cross-checking:

**Income Statement Relationships:**
- Gross profit = Revenue - Cost of revenue (and reverse)
- Cost of revenue = Revenue - Gross profit
- Revenue = Gross profit + Cost of revenue
- Total operating expenses = Sum of individual expenses (R&D + S&M + G&A)
- Individual expense = Total opex - Other expenses (and reverse)
- Operating income = Gross profit - Total operating expenses (and reverse)
- Net income = Operating income + Other income (and reverse)
- Other income = Net income - Operating income

**Margin Ratios (forward and reverse):**
- Gross margin = Gross profit / Revenue × 100
- Gross profit = Gross margin / 100 × Revenue
- Operating margin = Operating income / Revenue × 100
- Operating income = Operating margin / 100 × Revenue
- Net margin = Net income / Revenue × 100
- Net income = Net margin / 100 × Revenue
- Revenue = Gross profit / (Gross margin / 100)

**Per-Share Metrics:**
- EPS = Net income × 1,000,000 / Shares outstanding
- Shares outstanding = Net income × 1,000,000 / EPS

**Key Principle:** For every relationship A = f(B, C), implement:
1. Forward: derive A from B and C
2. Reverse: derive B from A and C (if mathematically possible)
3. Reverse: derive C from A and B (if mathematically possible)

This maximizes the number of metrics that can be cross-checked.

### 4. Tolerance Handling
Use appropriate tolerances for floating-point comparisons:
- **Dollar values**: 0.05 (for values in millions)
- **Percentages**: 0.15 (for rounded-to-one-decimal percentages)

### 5. Pattern Matching
Use case-insensitive partial matching for metric names:
- `'gross profit' in metric_name`
- `'revenue' in metric_name`
- `'operating income' in metric_name`

This handles variations like "Gross Profit", "gross_profit", "GROSS PROFIT".

## Handling Spec Variations

### report_structure_and_metric_relationships
The script handles varying HTML structures by:
- Parsing all tables generically (no hard-coded positions)
- Using pattern matching for metric names
- Supporting different section names and layouts
- Adapting to different line numbering schemes

### error_type_and_discoverability
The two-phase approach handles various error types:
- Wrong percentages (margins, growth rates)
- Wrong dollar amounts (totals, subtotals)
- Wrong per-share values
- Wrong year-over-year changes
- Unit conversion errors

The key is that the error is always discoverable through internal consistency, not external knowledge.

### output_format_constraints
The script writes output as `line_number,value` where:
- `line_number` is the line number shown in the report
- `value` is the incorrect numeric value as displayed (without currency symbols or percent signs)
- Handles decimals, negatives, and various numeric formats

## Robustness Features

1. **Graceful degradation**: If multiple metrics appear contradicted, returns the first one with a warning
2. **Clear diagnostics**: Prints classification status for each metric to stderr
3. **Flexible input**: Accepts custom HTML and output file paths via command-line arguments
4. **No external dependencies**: Uses only Python standard library

## Example Usage

```bash
python3 verify.py /app/q2_earnings_report.html /app/value.txt
```

Or with default paths:
```bash
python3 verify.py
```

## Verification Checklist

When implementing or adapting this skill:

- [ ] HTML parser extracts all metrics correctly
- [ ] Numeric parsing handles all formats (dollars, percentages, negatives)
- [ ] Derivation rules cover all common financial relationships
- [ ] Tolerances are appropriate for the data precision
- [ ] Two-phase logic correctly classifies CONFIRMED/CONTRADICTED/UNCHECKED
- [ ] Output format matches requirements (line_number,value)
- [ ] Script handles edge cases (missing metrics, no errors found)

## Common Pitfalls

1. **Conflating "no derivation" with "derivation disagrees"**: Always distinguish UNCHECKED from CONTRADICTED
2. **Hard-coding metric positions**: Use pattern matching, not index-based lookups
3. **Insufficient tolerance**: Use 0.15 for percentages, 0.05 for dollars
4. **Missing derivation patterns**: Cover both forward (A = B - C) and reverse (B = A + C) relationships
5. **Ignoring individual expense items**: Derive them as Total - Other expenses
6. **Substring collisions**: Use word boundary matching (`\b` + pattern + `\b`) to avoid false matches (e.g., 'sales' in 'net sales')
7. **Leave-one-out closure trap**: When checking if the target satisfies a property, check the target directly — don't search for it in a collection built from `others` (which excludes the target). This is a silent bug that always returns False.

## Testing Strategy

To verify the implementation:
1. Test with the seed v01 report (gross margin error)
2. Create variants with errors in different metric types (dollar amounts, totals, per-share)
3. Test with different HTML structures (nested tables, different layouts)
4. Verify tolerance handling with edge cases (values near rounding boundaries)
5. Confirm output format matches specification exactly
