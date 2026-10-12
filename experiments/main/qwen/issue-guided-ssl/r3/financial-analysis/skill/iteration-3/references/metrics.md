# Financial Metrics Reference

## Metric Formulas

### Gross Margin
- **Formula**: Gross Profit / Revenue × 100
- **Numerator**: Gross Profit (= Revenue − Cost of Revenue)
- **Denominator**: Revenue
- **Synonyms for numerator**: Gross Profit, Gross Margin (as absolute $), Gross Income
- **Synonyms for denominator**: Revenue, Total Revenue, Net Sales, Sales, Net Revenue, Turnover
- **Typical range**: 20%–80% for tech companies; <20% for retail

### Operating Margin
- **Formula**: Operating Income / Revenue × 100
- **Numerator**: Operating Income (= Gross Profit − Operating Expenses)
- **Denominator**: Revenue
- **Synonyms for numerator**: Operating Income, Operating Profit, EBIT, Income from Operations
- **Synonyms for denominator**: Same as Revenue above
- **Notes**: EBIT may differ slightly from Operating Income in some accounting frameworks

### Net Margin
- **Formula**: Net Income / Revenue × 100
- **Numerator**: Net Income (= Operating Income + Other Income − Taxes − Interest)
- **Denominator**: Revenue
- **Synonyms for numerator**: Net Income, Net Earnings, Net Profit, Profit After Tax, Profit for the Year
- **Synonyms for denominator**: Same as Revenue above

### Return on Equity (ROE)
- **Formula**: Net Income / Shareholders' Equity × 100
- **Numerator**: Net Income (from income statement)
- **Denominator**: Shareholders' Equity (from balance sheet)
- **Synonyms for denominator**: Shareholders' Equity, Stockholders' Equity, Total Equity, Book Value, Net Assets
- **Notes**: Requires data from both income statement and balance sheet. May need average equity (beginning + ending) / 2 for more accurate calculation.

### Year-over-Year Revenue Growth
- **Formula**: (Revenue_t − Revenue_{t−1}) / Revenue_{t−1} × 100
- **Numerator**: Revenue in current year minus Revenue in previous year
- **Denominator**: Revenue in previous year
- **Notes**: Requires consecutive fiscal years. If years are not consecutive (e.g., 2022 and 2024), the growth rate cannot be computed for the gap year.

## Scale and Rounding

All metrics are expressed as **percentage numbers**:
- 72.72 means 72.72%, NOT 0.7272
- Round to 2 decimal places: `round(value, 2)`
- Example: if Gross Profit = 97858 and Revenue = 130497, then Gross Margin = 97858/130497 × 100 = 74.99%

## Field Label Synonyms by Language

### English
| Concept | Common Labels |
|---------|--------------|
| Revenue | Revenue, Total Revenue, Net Sales, Sales, Net Revenue, Turnover |
| Gross Profit | Gross Profit, Gross Income, Gross Margin ($) |
| Operating Income | Operating Income, Operating Profit, EBIT, Operating Earnings |
| Net Income | Net Income, Net Earnings, Net Profit, Profit After Tax |
| Shareholders' Equity | Shareholders' Equity, Stockholders' Equity, Total Equity, Book Value |

### French
| Concept | Common Labels |
|---------|--------------|
| Revenue | Chiffre d'affaires, Produits des activités |
| Gross Profit | Marge brute, Résultat brut |
| Net Income | Résultat net, Bénéfice net |

### German
| Concept | Common Labels |
|---------|--------------|
| Revenue | Umsatz, Erlöse |
| Gross Profit | Rohergebnis, Bruttogewinn |
| Net Income | Nettoergebnis, Jahresüberschuss |

### Spanish
| Concept | Common Labels |
|---------|--------------|
| Revenue | Ingresos, Ingresos totales |
| Net Income | Resultado neto, Beneficio neto |

## Numeric Format Handling

| Format | Example | Interpretation |
|--------|---------|---------------|
| US | 1,234.56 | 1234.56 |
| EU | 1.234,56 | 1234.56 |
| Space | 1 234.56 | 1234.56 |
| Parenthetical | (1,234) | −1234 |
| Currency | $1,234.56 | 1234.56 |
| Suffix M | 1,234M | 1,234,000,000 |
| Suffix B | 1.2B | 1,200,000,000 |
| Suffix K | 500K | 500,000 |

## Year Label Formats

| Format | Example | Normalized |
|--------|---------|------------|
| Plain | 2025 | 2025 |
| FY prefix | FY2025 | 2025 |
| Short FY | FY25 | 2025 |
| Date range | 2024-2025 | 2025 |
| Verbose | Year Ended Jan 2025 | 2025 |
| Calendar | Calendar Year 2025 | 2025 |

## Conditional Logic Patterns

Common conditional patterns in task instructions:
1. **Threshold**: "If [metric] exceeds [X]%, compute [metric_A]; else [metric_B]"
2. **Sign**: "If [metric] is positive for all years, report it; else report [alternative]"
3. **Trend**: "If [metric] increased year-over-year, report [X]; else [Y]"
4. **Comparison**: "If [metric_A] > [metric_B], report [metric_A]; else [metric_B]"

Always extract the condition from the task instruction at runtime. Never hardcode.
