---
name: financial-analysis
description: >
  General method for extracting financial data from heterogeneous sources,
  computing standard financial metrics (gross_margin, operating_margin,
  net_margin, return_on_equity, year_over_year_growth), and producing
  task-specified output. Handles multi-file joins, schema/locale variation,
  and task-driven conditional logic.
---

# Financial Analysis Skill

## Task Family Overview

This skill addresses tasks requiring:
1. **Data discovery** - Find correct financial data among decoys
2. **Parsing & normalization** - Extract structured data from varied formats
3. **Metric computation** - Calculate specified financial metrics
4. **Conditional logic** - Execute task-specified branching rules
5. **Output generation** - Produce results in requested format

The task instruction specifies which metric(s) to compute and any conditional logic. Do not assume specific patterns; parse the instruction carefully.

## Step 1: Data Discovery

### Content-Based File Classification

Never rely on filenames alone. Scan all candidate files and classify by content:

**For each file:**
1. Read the entire content
2. Identify the company name (look for explicit labels like "Company: NVIDIA Corporation")
3. Identify statement type:
   - **Income statement**: Revenue, Cost of Revenue, Gross Profit, Operating Income, Net Income
   - **Balance sheet**: Assets, Liabilities, Shareholders' Equity
   - **Mixed**: Contains both income and balance sheet items
4. Identify time coverage: fiscal years, quarters, or date ranges
5. Identify data format: CSV, fixed-width, nested JSON, HTML table

**Selection criteria:**
- Match the company name specified in the task
- Ensure all required fields for the requested metric are present
- Prefer annual data unless task specifies quarterly
- If multiple files match, check if they need to be joined (e.g., income statement + balance sheet for ROE)

### Handling Decoys

Decoy files may:
- Contain data for a different company
- Have quarterly data when annual is needed
- Be missing required fields
- Have misleading filenames

Always verify content, not just names.

## Step 2: Parsing & Normalization

### Format Detection

**CSV/TSV:**
- Detect delimiter (comma, tab, semicolon, pipe)
- Handle quoted fields with embedded delimiters
- Skip header rows and metadata lines

**Fixed-width text:**
- Look for aligned columns with consistent spacing
- Identify column boundaries from header alignment
- Extract by position

**Nested JSON:**
- Traverse to find financial data arrays/objects
- Map nested paths to flat field names
- Handle arrays of yearly/quarterly records

**HTML tables:**
- Parse table structure (may have merged headers)
- Extract row/column data
- Handle multi-level headers

### Locale & Schema Normalization

**Numeric formats:**
- US: `1,234.56` (comma thousands, period decimal)
- European: `1.234,56` (period thousands, comma decimal)
- Detect by examining sample values; if ambiguous, assume US

**Field name variation:**
Map common synonyms to canonical names:

| Canonical | Synonyms |
|-----------|----------|
| Revenue | Sales, Total Revenue, Net Sales, Turnover, Chiffre d'affaires |
| Gross Profit | Gross Margin (dollars), Gross Income |
| Operating Income | Operating Profit, EBIT, Operating Earnings |
| Net Income | Net Earnings, Net Profit, Profit After Tax, Bottom Line, Résultat net |
| Shareholders' Equity | Stockholders' Equity, Total Equity, Book Value, Capitaux propres |

**Year labels:**
- Normalize `FY2024`, `2024`, `Fiscal Year 2024`, `Year ending 2024` → `2024`
- Handle fiscal year end dates (e.g., "FY ending Jan 2025" → fiscal year 2025)

**Units:**
- Detect if values are in millions, billions, or absolute
- Note the unit but do not convert unless task requires it
- Maintain consistency within a dataset

### Canonical Data Structure

After parsing, produce a normalized table:

```python
[
    {
        'year': 2024,  # integer
        'revenue': 60922.0,  # float, in stated units
        'gross_profit': 44301.0,
        'operating_income': 32972.0,
        'net_income': 29760.0,
        'shareholders_equity': None  # if not present
    },
    ...
]
```

Sort by year ascending.

## Step 3: Multi-File Joins (When Required)

If the requested metric requires data from multiple statements (e.g., ROE needs Net Income from income statement and Shareholders' Equity from balance sheet):

1. Parse each file independently into canonical structure
2. Classify each file by statement type
3. Join on fiscal year:
   ```python
   merged = {}
   for record in income_data:
       year = record['year']
       merged[year] = record.copy()
   
   for record in balance_sheet_data:
       year = record['year']
       if year in merged:
           merged[year].update(record)
       else:
           # Handle mismatched coverage
           merged[year] = record
   ```
4. Handle missing fields gracefully:
   - If a required field is missing for a year, either skip that year or flag as incomplete
   - Document which years have complete data

## Step 4: Metric Computation

### Metric Definitions

All metrics are computed per fiscal year unless task specifies aggregation.

**1. Gross Margin**
```
gross_margin = (gross_profit / revenue) * 100
```
- Express as percentage (e.g., 72.72 means 72.72%)
- Round to 2 decimal places
- Edge case: revenue = 0 → undefined, skip or flag

**2. Operating Margin**
```
operating_margin = (operating_income / revenue) * 100
```
- Same rounding and edge cases as gross margin

**3. Net Margin**
```
net_margin = (net_income / revenue) * 100
```
- Same rounding and edge cases as gross margin

**4. Return on Equity (ROE)**
```
roe = (net_income / shareholders_equity) * 100
```
- Cross-statement metric (requires income statement + balance sheet)
- Edge cases:
  - shareholders_equity = 0 → undefined, skip or flag
  - shareholders_equity < 0 → negative ROE is valid (company has negative book value)
  - Report as percentage, rounded to 2dp

**5. Year-over-Year Growth**
```
yoy_growth = ((value_t - value_{t-1}) / abs(value_{t-1})) * 100
```
- Requires sorting by year
- Compute for each year except the first (no prior year)
- Use absolute value in denominator to handle sign flips
- The "value" is whatever field the task specifies (e.g., "Revenue growth" uses revenue)
- Round to 2dp

### Rounding

Always round to 2 decimal places using **ROUND_HALF_UP** (standard financial rounding):

**Important:** Python's built-in `round()` uses banker's rounding (round half to even), which can produce incorrect results for financial analysis. For example, `round(0.125, 2)` returns `0.12` instead of `0.13`.

**Correct approach using Decimal:**
```python
from decimal import Decimal, ROUND_HALF_UP

def round_financial(value, decimals=2):
    """Round using ROUND_HALF_UP (standard financial rounding)"""
    d = Decimal(str(value))
    quantize_str = '0.' + '0' * decimals
    return float(d.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP))

# Example
rounded_value = round_financial(72.725, 2)  # Returns 72.73, not 72.72
```

**Alternative using arithmetic:**
```python
import math

def round_financial_arithmetic(value, decimals=2):
    """Round using arithmetic (round half up)"""
    multiplier = 10 ** decimals
    return math.floor(value * multiplier + 0.5) / multiplier
```

Use the Decimal approach as it's more explicit and handles edge cases better.

## Step 5: Conditional Logic

The task instruction may specify conditional computation. Parse the instruction carefully to identify:

1. **Condition**: What triggers the branch (e.g., "if most recent year's GM > 70%")
2. **True branch**: What to compute if condition is met
3. **False branch**: What to compute otherwise

**Execution pattern:**
```python
# Evaluate condition
condition_met = evaluate_condition(data, task_instruction)

if condition_met:
    results = compute_metric(data, true_branch_metric)
else:
    results = compute_metric(data, false_branch_metric)
```

**Do not hard-code specific conditional patterns.** Each task may have different conditions and branches.

## Step 6: Output Generation

### Output Format

The task instruction specifies the output format. Common patterns:

**CSV:**
```csv
fiscal_year,gross_margin_pct
2024,72.72
2025,74.99
```

**Column naming:**
- Use exact column names from task instruction
- Common patterns: `fiscal_year` or `year`, `gross_margin_pct` or `gross_margin`

**Serialization:**
- Write to specified file path (e.g., `/app/results.csv`)
- Use proper CSV formatting with headers
- Ensure numeric values are not quoted

### Validation

Before finalizing output:
1. Verify all requested years are present
2. Check that values are in correct units (percentages, not decimals)
3. Ensure rounding is applied consistently
4. Confirm column names match task specification

## Implementation Checklist

When solving a financial analysis task:

- [ ] Read task instruction carefully; identify requested metric(s) and any conditional logic
- [ ] Discover all candidate files in the data directory
- [ ] Parse each file; classify by company, statement type, time coverage
- [ ] Select file(s) matching the target company and containing required fields
- [ ] Normalize data to canonical {year, field, value} structure
- [ ] If multi-file join needed, merge on fiscal year
- [ ] Compute requested metric(s) using correct formula
- [ ] Apply any conditional logic specified in the task
- [ ] Round to 2 decimal places
- [ ] Write output in specified format with correct column names
- [ ] Validate output completeness and correctness

## Edge Cases & Error Handling

**Missing data:**
- If a required field is missing for a year, skip that year or flag as incomplete
- Document which years have complete data

**Division by zero:**
- If denominator is zero, the metric is undefined
- Either skip that year or report as "N/A" per task requirements

**Negative values:**
- Negative margins are valid (company is losing money)
- Negative ROE is valid (negative shareholders' equity)
- Use absolute value in YoY growth denominator to handle sign flips

**Mismatched year coverage:**
- If joining files with different year ranges, only compute for years with complete data
- Document the coverage gap

**Ambiguous data:**
- If a file contains both annual and quarterly data, prefer annual unless task specifies quarterly
- If company name is ambiguous, look for ticker symbols or other identifiers
