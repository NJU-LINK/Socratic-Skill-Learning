# Common Financial Relationships for Cross-Checking

This document catalogs the standard financial ratio relationships used to
verify HTML financial reports. The verifier tries all possible ordered pairs
of dollar values, but understanding these relationships helps interpret results.

## Income Statement Relationships (Additive)

### Gross Profit
```
Gross profit = Revenue − Cost of revenue
```

### Total Operating Expenses
```
Total operating expenses = R&D + S&M + G&A
```
(May also include D&A, restructuring, or other line items)

### Operating Income (EBIT)
```
Operating income = Gross profit − Total operating expenses
```

### Net Income (Earnings)
```
Net income = Operating income + Other income, net − Income tax expense
```
(Other income may be net of interest expense, gains/losses, etc.)

### EBITDA
```
EBITDA = Operating income + Depreciation + Amortization
```

## Margin Ratios (Percentage of Revenue)

All margins are computed as `(component / Revenue) × 100`:

### Gross Margin
```
Gross margin = (Gross profit / Revenue) × 100
```

### Operating Margin
```
Operating margin = (Operating income / Revenue) × 100
```

### Net Margin (Profit Margin)
```
Net margin = (Net income / Revenue) × 100
```

### R&D Margin
```
R&D margin = (R&D expense / Revenue) × 100
```

### S&M Margin
```
S&M margin = (Sales & marketing / Revenue) × 100
```

## Per-Share Metrics

### Earnings Per Share (EPS)
```
Basic EPS = Net income / Weighted average shares outstanding
Diluted EPS = Net income / Diluted weighted average shares outstanding
```

### Revenue Per Share
```
Revenue per share = Revenue / Shares outstanding
```

## Growth Rates (Year-over-Year)

```
Revenue growth = ((Current revenue − Prior revenue) / Prior revenue) × 100
Earnings growth = ((Current EPS − Prior EPS) / |Prior EPS|) × 100
```

## Balance Sheet Relationships

### Current Ratio
```
Current ratio = Current assets / Current liabilities
```

### Working Capital
```
Working capital = Current assets − Current liabilities
```

### Book Value Per Share
```
BVPS = Total shareholders' equity / Shares outstanding
```

## Key Verification Principles

1. **All dollar values are internally consistent** — they satisfy the additive relationships above
2. **Exactly one percentage is wrong** — it fails to match any valid ratio
3. **Rounding**: Percentages are typically rounded to 1 decimal place
4. **Tolerance**: Use ~0.15 tolerance when comparing computed vs. reported percentages
5. **The incorrect value is the one that matches NO valid ratio** while all others match at least one

## Variant Considerations

Different report variants may include:
- Different metric families (e.g., SaaS metrics like ARR growth, rule of 40)
- Different sections (balance sheet, cash flow, segment data)
- Different line numbering schemes (110/120/130 vs. 10/20/30 vs. arbitrary)
- Different value formats (thousands separators, magnitude suffixes, parenthesized negatives)
- Different precision (0 vs. 1 vs. 2 decimal places)

The verifier handles all of these through regex-based extraction and exhaustive ratio checking.
