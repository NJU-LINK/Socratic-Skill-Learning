# Financial Metric Formulas — Quick Reference

## Margin Metrics (all expressed as percentage × 100)

### Gross Margin
```
Gross Margin (%) = (Gross Profit / Revenue) × 100
```
- Gross Profit = Revenue − Cost of Goods Sold (COGS)
- Also called "Gross Profit Margin"

### Operating Margin
```
Operating Margin (%) = (Operating Income / Revenue) × 100
```
- Operating Income = Gross Profit − Operating Expenses
- Also called "Operating Profit Margin" or "EBIT Margin"

### Net Margin
```
Net Margin (%) = (Net Income / Revenue) × 100
```
- Net Income = Operating Income + Other Income − Taxes
- Also called "Net Profit Margin"

## Return Metrics

### Return on Equity (ROE)
```
ROE (%) = (Net Income / Shareholders' Equity) × 100
```
- Requires balance-sheet data (Shareholders' Equity)
- May need joining income statement and balance sheet files

## Growth Metrics

### Year-over-Year (YoY) Growth
```
YoY Growth (%) = ((Value_t − Value_{t−1}) / Value_{t−1}) × 100
```
- Can apply to Revenue, Net Income, or any metric
- Requires at least two consecutive periods
- Result can be negative (decline)
- No YoY value for the first period

## Rounding Convention
- Default: round to 2 decimal places
- Output as percentage number: 72.72 (not 0.7272)
- Use Python: `round(value, 2)` or `f"{value:.2f}"`
