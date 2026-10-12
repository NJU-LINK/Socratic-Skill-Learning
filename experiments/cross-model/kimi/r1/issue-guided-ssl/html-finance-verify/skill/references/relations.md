# Financial Relations Reference

## Label Synonyms (for variant compatibility)

When matching financial statement lines across variants with renamed sections:

| Concept | Synonyms |
|---------|----------|
| Revenue | `revenue`, `total revenue`, `net sales`, `total net sales`, `sales` |
| Cost of Revenue | `cost of revenue`, `cost of sales`, `cogs`, `cost of goods sold` |
| Gross Profit | `gross profit`, `gross income`, `gross margin dollars`, `gross earnings` |
| Total OpEx | `total operating expenses`, `total opex`, `operating expenses`, `total operating costs` |
| Operating Income | `operating income`, `operating profit`, `income from operations` |
| Net Income | `net income`, `net profit`, `bottom line` |
| Other Income | `other income`, `other income net`, `other expenses` |

## Additive Relations (Dollar Values)

### Income Statement Structure
```
Gross Profit = Revenue - Cost of Revenue

Total Operating Expenses = Σ Operating Expense Lines
Operating Income = Gross Profit - Total Operating Expenses

Net Income = Operating Income + Other Income
```

### Expense Line Detection
Operating expenses contain: `research`, `development`, `marketing`, `general`, `administrative`, `r&d`, `sg&a`, `overhead`

Excluded from expenses: `cost of revenue`, `cost of sales`, `cogs`, `cost of goods sold`, `total`

## Ratio Relations (Percentages)

### Margin Formulas
```
Gross Margin = Gross Profit / Revenue × 100
Operating Margin = Operating Income / Revenue × 100
Net Margin = Net Income / Revenue × 100
```

### Growth Rates
```
YoY Growth = (Current - Prior) / Prior × 100
QoQ Growth = (Current - Prior) / Prior × 100
```

## Unit Conversions

| Suffix | Multiplier | Example |
|--------|-----------|---------|
| K | × 1,000 | $500K = $500,000 |
| M | × 1,000,000 | $842.0M = $842,000,000 |
| B | × 1,000,000,000 | $2.5B = $2,500,000,000 |

## Rounding Rules

- Use `ROUND_HALF_UP` (not Python's default banker's rounding)
- Tolerance: `|reported - expected| ≤ 0.5 × 10^-d`
- Where `d` = decimals displayed in the raw value
- Material errors (>0.5 point for 1-decimal percents) separate from rounding noise

## Cascading Failure Detection

When a single wrong value causes multiple checks to fail:

1. **Track involvement**: Each check records which line numbers it involves
2. **Find root cause**: The line that participates in ALL failed checks
3. **Fallback heuristic**: If no line covers all failures, use most frequent participant

Example: Corrupting Total OpEx affects:
- Total OpEx check itself
- Operating Income check (derived from OpEx)
But NOT Gross Margin check (derived from Gross Profit/Revenue)

Root cause selection prioritizes the line involved in the most failed checks.

## Detection Strategy

**Label-guided first**: Map keywords to formulas using synonym matching.

**Brute-force fallback**: For each percentage p with d decimals, search all ordered pairs (a, b) of dollar values for `round_half_up(a/b*100, d) == p`. The metric with zero explaining pairs while siblings have one is the outlier.
