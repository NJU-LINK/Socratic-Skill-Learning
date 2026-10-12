# Financial Metric Formulas Reference

All metrics expressed as **percentage numbers** (e.g., 72.72 = 72.72%, not 0.7272).
Default rounding: **2 decimal places**.

## Income Statement Metrics

### Gross Margin
```
Gross Margin = (Gross Profit / Revenue) × 100
```
- **Numerator**: Gross Profit (Revenue − Cost of Goods Sold)
- **Denominator**: Revenue (Total Revenue / Net Sales)
- **Source**: Income statement
- **Field aliases**: "Gross Profit", "Gross Margin" (when amount), "Bruttogewinn"

### Operating Margin
```
Operating Margin = (Operating Income / Revenue) × 100
```
- **Numerator**: Operating Income (EBIT / Operating Profit)
- **Denominator**: Revenue
- **Source**: Income statement
- **Field aliases**: "Operating Income", "EBIT", "Operating Profit", "Betriebsergebnis"

### Net Margin
```
Net Margin = (Net Income / Revenue) × 100
```
- **Numerator**: Net Income (Profit After Tax / Net Earnings)
- **Denominator**: Revenue
- **Source**: Income statement
- **Field aliases**: "Net Income", "Net Profit", "Net Earnings", "Nettoergebnis"

## Balance Sheet Metrics

### Return on Equity (ROE)
```
ROE = (Net Income / Average Shareholders' Equity) × 100
```
- **Numerator**: Net Income (from income statement)
- **Denominator**: Average Shareholders' Equity = (Beginning Equity + Ending Equity) / 2
  - If only one year of equity data available, use that year's equity directly
- **Source**: Income statement + Balance sheet (cross-statement join required)
- **Field aliases**: "Shareholders Equity", "Total Equity", "Stockholders Equity", "Eigenkapital"

## Growth Metrics

### Year-over-Year Revenue Growth
```
YoY Growth = ((Revenue[t] − Revenue[t−1]) / Revenue[t−1]) × 100
```
- **Numerator**: Revenue[t] − Revenue[t−1] (change in revenue)
- **Denominator**: Revenue[t−1] (prior period revenue)
- **Source**: Multi-year income statement
- **Note**: First year in the dataset has no prior period; result is undefined/null
- **Field aliases**: Same as Revenue aliases

## Sign Conventions

- Positive margin = profitable
- Negative margin = loss-making
- Revenue and income figures should be used as reported (absolute values for margin computation)
- If Net Income is negative, net margin will be negative

## Scale and Units

- If source data is in millions (M), billions (B), or thousands (K), the scale cancels in ratios
- No unit conversion needed for margin calculations (both numerator and denominator in same units)
- For ROE, ensure Net Income and Equity are in the same currency and scale
