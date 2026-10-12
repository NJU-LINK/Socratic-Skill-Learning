---
name: financial-analysis
description: >
  Discover, parse, and compute financial metrics from heterogeneous data sources
  containing company financial statements. Handles file discovery among decoys,
  multiple data formats (CSV, JSON, fixed-width, HTML), various financial metrics
  (gross margin, operating margin, net margin, ROE, YoY growth), conditional
  computation logic, and flexible output contracts.
---

# Financial Analysis Skill

## Overview

This skill solves tasks that require extracting financial data from files in a
directory, computing one or more standard financial metrics, and writing results
to a specified output artifact. The task family varies along five axes: source
representation, statement topology, financial metric, schema/locale, and output
contract.

## Generalized Procedure

### Phase 1: Data Discovery

**Goal**: Identify the correct file(s) containing the target company's financial data.

1. **List all files** in the specified data directory (commonly `/app/financials/` or similar).
2. **Read every file** — do not skip files based on extension alone. Decoy files
   may have plausible names (e.g., `backup_records.csv`, `cache_results.txt`,
   `data_2025.dat`).
3. **Filter by company identity**: Look for the target company name or ticker in
   file content. Key signals:
   - Explicit company name (e.g., "NVIDIA Corporation")
   - Ticker symbol (e.g., "NVDA")
   - Reject files for other companies (e.g., "Advanced Micro Devices" / "AMD")
4. **Validate data completeness**: The correct file must contain the financial
   line items needed for the requested metric. Check for:
   - Multiple fiscal years of data (annual, not quarterly-only)
   - Required fields (Revenue, Gross Profit, Net Income, etc.)
5. **Beware of decoy patterns**:
   - Files with partial/quarterly data when annual is needed
   - Files with cached/summary data that lacks full detail
   - Files for a different company entirely
   - Files with product-level revenue (not company-level)

### Phase 2: Data Extraction & Parsing

**Goal**: Extract structured financial data from the identified file.

#### Format-Specific Parsing Strategies

| Format | Detection | Parsing Approach |
|--------|-----------|------------------|
| **CSV** | Has comma-separated header row | Use `csv.DictReader` or `pandas.read_csv` |
| **JSON** | Starts with `{` or `[` | Use `json.load`; navigate nested structure |
| **Fixed-width** | Aligned columns, no delimiters | Identify column positions from header; slice by character positions |
| **HTML table** | Contains `<table>` tags | Use `html.parser` or regex to extract `<td>`/`<th>` content |
| **Mixed/log format** | Contains `[INFO]`, `[DATA]`, `[WARN]` markers | Extract data lines by prefix; parse key-value pairs |

#### Universal Extraction Steps

1. **Skip header/metadata blocks**: Many files have decorative banners, notes,
   or metadata before the data table. Look for the actual data rows.
2. **Identify column mapping**: Map each column/header to its financial meaning:
   - Year/fiscal year identifier
   - Revenue (may be labeled "Revenue", "Total Revenue", "Sales", "Umsatzerlöse", etc.)
   - Gross Profit (may be "Gross Profit", "GP", "Bruttogewinn", etc.)
   - Operating Income (may be "Operating Income", "OI", "EBIT", etc.)
   - Net Income (may be "Net Income", "NI", "Nettoergebnis", etc.)
   - Shareholders' Equity (may be "Equity", "SE", "Eigenkapital", etc.)
3. **Handle numeric formats**:
   - Strip currency symbols ($, €, £)
   - Handle thousands separators (commas in US, periods in EU)
   - Handle unit indicators ("in millions", "M", "mn") — values may need ×1000000
   - Handle negative values in parentheses: `(500)` means `-500`
4. **Extract year labels**: Normalize to consistent format. Years may appear as
   "FY2024", "2024", "Fiscal Year 2024", "2023-2024", "jahr2024", etc.

### Phase 3: Metric Computation

**Goal**: Calculate the requested financial metric(s) with correct formulas.

#### Metric Formulas (all expressed as percentages unless noted)

#### Point-in-Time Ratio Metrics

These are computed independently for each row — no cross-row dependencies.

| Metric | Formula | Notes |
|--------|---------|-------|
| **Gross Margin** | `(Gross Profit / Revenue) × 100` | Measures production efficiency |
| **Operating Margin** | `(Operating Income / Revenue) × 100` | Measures operational efficiency |
| **Net Margin** | `(Net Income / Revenue) × 100` | Measures overall profitability |
| **Return on Equity** | `(Net Income / Shareholders' Equity) × 100` | Measures equity returns |

#### Sequential Metric: Year-over-Year (YoY) Growth

YoY growth is structurally different from the ratio metrics above. It is a
**relational/sequential** computation that requires cross-row dependencies.

**Key properties:**
1. **Applies to any line item** the task specifies — revenue, gross profit, net
   income, operating income, equity, etc. Do not assume it always targets revenue.
2. **Requires chronological sorting** before computation.
3. **Prior-year lookup**: For year t, compute `(value[t] - value[t-1]) / |value[t-1]| × 100`.
4. **First year has no prior** — it must be **excluded from output** (unless the
   task explicitly says otherwise).
5. **Absolute value in denominator**: Use `|prior|` not `prior`. When the prior
   year's value is negative (e.g., a net loss), omitting the absolute value
   produces a sign-flipped or meaningless percentage.
6. **Zero prior**: If the prior year's value is exactly 0, growth is undefined —
   skip that year or flag it per task instructions.

```python
def compute_yoy_growth(records, field):
    """
    Compute YoY growth for any specified field across sorted records.
    
    Args:
        records: list of dicts with at least 'year' and the target field
        field: the financial line item to compute growth for
                 (e.g., 'revenue', 'gross_profit', 'net_income')
    
    Returns:
        list of dicts with 'year' and 'value' (growth percentage)
    """
    records_sorted = sorted(records, key=lambda r: r['year'])
    results = []
    for i in range(1, len(records_sorted)):
        current = records_sorted[i][field]
        prior = records_sorted[i - 1][field]
        if prior == 0:
            continue  # undefined growth; skip
        growth = ((current - prior) / abs(prior)) * 100
        results.append({
            'year': records_sorted[i]['year'],
            'value': round(growth, 2)
        })
    return results
```

#### Rounding
- Round to the number of decimal places specified in the task (commonly 2).
- Use standard rounding (Python's `round()` or explicit formatting).
- Express as percentage numbers (e.g., 72.72 means 72.72%, not 0.7272).

#### Conditional Logic
Tasks may include conditional branches. Common patterns:
- "If metric X exceeds threshold T, compute metric Y; otherwise compute metric Z"
- "If the most recent year's value > threshold, compute for all years"
- Always evaluate the condition using the computed value BEFORE rounding for the
  threshold check, then round for output.

### Phase 4: Statement Topology (Multi-file Joining)

When data spans multiple files:
1. Identify which file contains which line items (e.g., income statement vs.
   balance sheet).
2. Join on fiscal year to combine values needed for the metric.
3. Example: ROE needs Net Income (from income statement) and Shareholders'
   Equity (from balance sheet) — join by year.

### Phase 5: Output Generation

**Goal**: Write results in the exact format specified.

1. **Column names**: Use exactly what the task specifies (e.g., `fiscal_year,gross_margin_pct`).
2. **File location**: Write to the specified path (e.g., `/app/results.csv`).
3. **Row ordering**: Typically chronological (earliest year first).
4. **Format**: Usually CSV, but may be JSON or other formats.
5. **Values**: Percentage numbers rounded as specified.

## Implementation Pattern (Python)

```python
import csv
import json
import os
import re

def discover_file(directory, company_name):
    """Find the correct financial data file for the target company."""
    candidates = []
    for fname in os.listdir(directory):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, 'r', errors='ignore') as f:
            content = f.read()
        if company_name.lower() in content.lower():
            candidates.append((fpath, content))
    # Filter: prefer files with multi-year annual data
    # Reject files that only have quarterly data or are for other companies
    return candidates

def parse_financial_data(filepath, content):
    """Parse financial data from various formats."""
    # Detect format and parse accordingly
    # Return list of dicts: [{year, revenue, gross_profit, ...}, ...]
    pass

def compute_ratio_metric(records, metric_name):
    """Compute a point-in-time ratio metric (all except YoY growth)."""
    formulas = {
        'gross_margin': lambda r: (r['gross_profit'] / r['revenue']) * 100,
        'operating_margin': lambda r: (r['operating_income'] / r['revenue']) * 100,
        'net_margin': lambda r: (r['net_income'] / r['revenue']) * 100,
        'return_on_equity': lambda r: (r['net_income'] / r['equity']) * 100,
    }
    results = []
    for r in records:
        value = formulas[metric_name](r)
        results.append({'year': r['year'], 'value': round(value, 2)})
    return results

def compute_yoy_growth(records, field):
    """
    Compute YoY growth for any specified financial line item.
    Requires chronological sort; first year excluded (no prior).
    Uses abs(prior) in denominator to handle negative prior values.
    """
    records_sorted = sorted(records, key=lambda r: r['year'])
    results = []
    for i in range(1, len(records_sorted)):
        current = records_sorted[i][field]
        prior = records_sorted[i - 1][field]
        if prior == 0:
            continue  # undefined growth
        growth = ((current - prior) / abs(prior)) * 100
        results.append({
            'year': records_sorted[i]['year'],
            'value': round(growth, 2)
        })
    return results

def write_results(results, output_path, column_names):
    """Write results to the specified output file."""
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(column_names)
        for row in results:
            writer.writerow([row['year'], row['value']])
```

## Key Pitfalls & Checks

1. **Decoy files**: Always read ALL files. Do not assume the first file or the
   file with the most "financial-looking" name is correct.
2. **Quarterly vs Annual**: If the task asks for fiscal year data, reject files
   that only contain quarterly data.
3. **Unit consistency**: Ensure all values are in the same units before computing
   ratios. If Revenue is in millions but Gross Profit is in actual dollars,
   convert first.
4. **Sign conventions**: Some statements show expenses as negative numbers.
   Gross Profit = Revenue - COGS; if COGS is shown as a negative, then
   Gross Profit = Revenue + COGS (since COGS is already negative).
5. **Threshold comparison**: Use unrounded values for threshold comparisons;
   round only for output.
6. **Fiscal year labeling**: "FY2024" and "2024" may refer to the same year.
   Normalize year labels for consistent output.
7. **Missing data**: If a required field is missing for a year, that year cannot
   be included in the output.

## Worked Example (v01 — NVIDIA Gross Margin)

**Scenario**: Find NVIDIA data in `/app/financials/`, compute Gross Margin.

**Discovery**:
- `backup_records.csv` → Product-level sales data (RTX 5090, 5080). Not company financials. REJECT.
- `cache_results.txt` → Contains some margin data but incomplete, no clear company identifier. REJECT.
- `data_2025.dat` → AMD quarterly data. Wrong company. REJECT.
- `financial_summary.dat` → "NVIDIA Corporation", "NVDA", FY2022-FY2026 with Revenue, GrossProfit, etc. CORRECT.

**Extraction**:
```
Year     Revenue   GrossProfit
FY2022   26914     17475
FY2023   26974     15356
FY2024   60922     44301
FY2025   130497    97858
FY2026   215938    153463
```

**Conditional check**: Most recent year (FY2026) Gross Margin = 153463/215938 × 100 = 71.07% > 70% → compute Gross Margin for all years.

**Output** (`/app/results.csv`):
```csv
fiscal_year,gross_margin_pct
FY2022,64.93
FY2023,56.93
FY2024,72.72
FY2025,74.99
FY2026,71.07
```
