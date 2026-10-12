---
name: financial-analysis
description: >
  Discover, parse, and compute standard financial metrics from company financial
  data in varied formats (CSV, JSON, fixed-width, HTML), with conditional
  computation logic and structured output. Handles data discovery among decoys,
  multi-format parsing, cross-statement joins, and locale/schema variations.
---

# Financial Analysis Skill

## Overview

This skill handles tasks that require:
1. Discovering the correct financial data file(s) for a target company among potentially many files
2. Parsing financial data from varied formats (CSV, JSON, fixed-width text, HTML tables)
3. Extracting specific financial line items (Revenue, Gross Profit, Net Income, Operating Income, Shareholders' Equity, etc.)
4. Computing standard financial metrics with conditional logic
5. Writing results in a specified output format

## Financial Metric Definitions

All metrics are expressed as **percentage numbers** (e.g., 72.72 means 72.72%, NOT 0.7272).

| Metric | Formula | Notes |
|--------|---------|-------|
| `gross_margin` | Gross Profit / Revenue × 100 | Also called gross profit margin |
| `operating_margin` | Operating Income / Revenue × 100 | Also called operating profit margin, EBIT margin |
| `net_margin` | Net Income / Revenue × 100 | Also called net profit margin, profit margin |
| `return_on_equity` | Net Income / Shareholders' Equity × 100 | Also called ROE; equity = total equity / stockholders' equity |
| `year_over_year_growth` | (Current_Value - Previous_Value) / Previous_Value × 100 | Applied to any base metric (revenue, net income, etc.); produces one fewer data point than input years |

Rounding: Always round to 2 decimal places unless the task specifies otherwise.

## Step-by-Step Method

### Step 1: Data Discovery — Source Hierarchy & Decoy Rejection

Explore the data directory to find the correct file(s) for the target company.
This is the most error-prone step: directories often contain **decoy files** that
look plausible but contain wrong, stale, or pre-computed data.

#### Data Source Priority Hierarchy (highest to lowest)

| Priority | File Type | Signals | Action |
|----------|-----------|---------|--------|
| **1 — USE** | Primary/raw data | Company name + raw line items (Revenue, Gross Profit, etc.) as structured numbers in CSV/JSON/table format | **Primary source** |
| **2 — REJECT** | Pre-computed summary / cache / log | Log markers (`[INFO]`, `[WARN]`, `[DATA]`), pre-computed percentages, narrative text, different units ($M vs raw) | **REJECT** — numbers may differ from raw data due to rounding, restatements, unit conversion, or stale snapshots |
| **3 — REJECT** | Other company | Different company name/ticker in header | **REJECT** |
| **4 — REJECT** | Wrong granularity | Quarterly when annual needed, or vice versa | **REJECT** |

**CRITICAL RULE:** When multiple files contain overlapping financial figures for the same company/year, ALWAYS use the file with the most granular raw line items. Pre-computed values in cache/log files are NOT authoritative — they may use different units, different time periods, or be stale.

**Concrete trap example:** A cache file might say `FY2024: Revenue=$58,000M, GP=$37,800M` (Gross Margin = 65.24%) while the raw data file says `FY2024: Revenue=60922, GrossProfit=44301` (Gross Margin = 72.72%). These are wildly different. Always trust the raw structured data.

#### Exploration Procedure

```
1. List all files in the data directory (and subdirectories if present)
2. For each file, inspect its contents (first ~20 lines) and CLASSIFY it:
   a. Does it contain the target company name/ticker? If NO → REJECT (type 3)
   b. Does it contain raw structured line items (numbers in rows/columns)?
      - YES → CANDIDATE primary source (type 1)
      - NO, but has pre-computed percentages or log markers → REJECT (type 2)
   c. Does it have the right time granularity (annual vs quarterly)?
      - NO → REJECT (type 4)
3. If multiple candidates remain, prefer the one with:
   - More structured data (CSV/JSON over formatted text)
   - More complete field coverage (has all fields needed for the metric)
   - More years of data
4. If data spans multiple files (e.g., separate income statement and balance sheet),
   identify all required files and note the join key (typically fiscal year)
```

### Step 2: Format Parsing

Handle each format type appropriately:

**CSV files:**
```python
import csv
# Standard csv.reader or csv.DictReader
# Watch for: header rows that don't start at line 1, comment lines, blank lines
```

**Fixed-width / formatted text files:**
```python
# Look for section headers (lines of '=' or '-' characters)
# Data often follows a header block
# Fields may be comma-separated within a formatted text block
# Extract the CSV-like data section by finding lines that match "Year,..." or similar patterns
```

**Nested JSON:**
```python
import json
# Navigate nested structure to find financial data arrays/objects
# Common patterns: {"company": {"financials": {"income_statement": [...]}}}
# Or: {"data": [{"year": 2024, "revenue": ..., "gross_profit": ...}]}
```

**HTML tables:**
```python
# Parse <table> elements, handle merged headers (rowspan/colspan)
# May need to flatten multi-row headers into single column names
```

**General parsing strategy:**
1. Read the file content
2. Identify the data section (skip headers, metadata, notes)
3. Determine column mapping (which columns contain needed values)
4. Handle numeric formatting:
   - Commas as thousands separators: "1,234,567" → 1234567
   - European notation: "1.234.567,89" → 1234567.89
   - Currency symbols: "$1,234M" → 1234 (note the M for millions)
   - Parentheses for negatives: "(500)" → -500
5. Extract a canonical integer year for SORTING ONLY — do NOT use it in output:
   - "FY2024" → sort key 2024, but OUTPUT "FY2024"
   - "2024" → sort key 2024, OUTPUT "2024"
   - "Fiscal Year 2024" → sort key 2024, OUTPUT "Fiscal Year 2024"
   - "Year ended Dec 31, 2024" → sort key 2024, OUTPUT "Year ended Dec 31, 2024"
   - "FY25" → sort key 2025, OUTPUT "FY25"
   Use regex extraction: `re.search(r'(20\d{2})', label)` to find the 4-digit year.
   This ensures consistent sorting regardless of label format.

   **CRITICAL: Preserve the original year label from the source data for output.**
   The fiscal_year column in the output must contain the EXACT label as it appears
   in the source data (e.g., "FY2022", not "2022"). Integer extraction is ONLY
   for determining chronological order and identifying the most recent year.

### Step 3: Field Mapping

Map discovered field names to canonical financial concepts. Field names vary by locale and convention:

| Canonical | Common Variants |
|-----------|----------------|
| Revenue | "Revenue", "Total Revenue", "Sales", "Net Sales", "Turnover", "Umsätze" (DE), "Chiffre d'affaires" (FR), "Ingresos" (ES) |
| Gross Profit | "Gross Profit", "Gross Income", "GP", "Bruttogewinn" (DE) |
| Operating Income | "Operating Income", "Operating Profit", "EBIT", "Operating Earnings", "Betriebsergebnis" (DE) |
| Net Income | "Net Income", "Net Profit", "Net Earnings", "Profit After Tax", "PAT", "Nettoergebnis" (DE) |
| Shareholders' Equity | "Shareholders' Equity", "Stockholders' Equity", "Total Equity", "Book Value", "Eigenkapital" (DE) |
| Cost of Revenue | "Cost of Revenue", "Cost of Goods Sold", "COGS", "Cost of Sales" |

**Matching strategy:** Use case-insensitive substring matching. For example, if a column contains "gross" and "profit" (or "income"), it maps to Gross Profit.

### Step 4: Metric Computation with Conditional Logic

The typical pattern involves:

```
1. Compute the PRIMARY metric for the MOST RECENT year
2. Compare against a THRESHOLD
3. IF condition is met:
     → Compute PRIMARY metric for ALL years
   ELSE:
     → Compute ALTERNATIVE metric for ALL years
4. Write results with specified column names
```

**Implementation template:**
```python
import re

def extract_year_int(label):
    """Extract canonical year integer from various label formats.
    Handles 'FY2024', 'FY25', '2024', 'Year ended Jan 2024', etc.
    """
    m = re.search(r'(20\d{2})', str(label))
    return int(m.group(1)) if m else int(label)

# Parse all data into records: [{year_label, year_int, revenue, gross_profit, net_income, ...}, ...]
records = parse_financial_data(filepath)
for r in records:
    r['year_int'] = extract_year_int(r['year_label'])
records.sort(key=lambda r: r['year_int'])

most_recent = records[-1]

# Compute primary metric for most recent year
primary_value = compute_metric(most_recent, primary_metric)

# THRESHOLD SEMANTICS: "exceeds" means STRICTLY GREATER THAN (>).
# If the value equals the threshold exactly, the condition is NOT met → go to ELSE branch.
if primary_value > threshold:  # strictly greater than
    # Compute primary metric for all years
    # IMPORTANT: use r['year_label'] (original label like "FY2022"), NOT r['year_int']
    results = [(r['year_label'], compute_metric(r, primary_metric)) for r in records]
    output_columns = primary_output_columns
else:
    # Compute alternative metric for all years
    results = [(r['year_label'], compute_metric(r, alternative_metric)) for r in records]
    output_columns = alternative_output_columns

# Write output
write_results(results, output_path, output_columns)
```

### Step 5: Output Generation

Write results to the specified output file. **Read the task instruction carefully to determine the output format** (CSV, JSON, etc.) — the format is always specified.

**CSV output** (most common):
```python
import csv

with open(output_path, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(output_columns)  # e.g., ['fiscal_year', 'gross_margin_pct']
    for year, value in results:
        writer.writerow([year, round(value, 2)])
```

**JSON output** (if specified):
```python
import json

# Format 1: Array of objects
output_data = [
    {output_columns[0]: year, output_columns[1]: value}
    for year, value in results
]
with open(output_path, 'w') as f:
    json.dump(output_data, f, indent=2)

# Format 2: Object with year keys
output_data = {year: value for year, value in results}
with open(output_path, 'w') as f:
    json.dump(output_data, f, indent=2)
```

**Output conventions:**
- Percentages as numbers (72.72 not 0.7272)
- Round to 2 decimal places unless specified otherwise
- Column names as specified in the task (e.g., `fiscal_year`, `gross_margin_pct`)
- **Fiscal year labels: preserve the EXACT format from the source data** (e.g., if source has "FY2022", output "FY2022" — do NOT strip the "FY" prefix or convert to bare integer). The test harness indexes results by the original label.

## Multi-File / Cross-Statement Joins

When data spans multiple files (e.g., income statement + balance sheet), you must join them by fiscal year before computing metrics.

**Common scenario**: ROE requires Net Income (from income statement) and Shareholders' Equity (from balance sheet), which may be in separate files.

**Implementation pattern**:
```python
# 1. Parse each file independently into year-keyed dictionaries
income_data = {}  # {year_label: {net_income: value, ...}}
for record in parse_file('income_statement.csv'):
    income_data[record['year_label']] = record

balance_data = {}  # {year_label: {equity: value, ...}}
for record in parse_file('balance_sheet.csv'):
    balance_data[record['year_label']] = record

# 2. Join by fiscal year (preserve original year labels)
merged_records = []
for year_label in income_data:
    if year_label in balance_data:
        merged = {
            'year_label': year_label,
            'year_int': extract_year_int(year_label),
            'net_income': income_data[year_label]['net_income'],
            'equity': balance_data[year_label]['equity']
        }
        merged_records.append(merged)

# 3. Sort by year_int and compute metric
merged_records.sort(key=lambda r: r['year_int'])
roe_results = []
for r in merged_records:
    roe = r['net_income'] / r['equity'] * 100
    roe_results.append((r['year_label'], round(roe, 2)))
```

**Key points**:
- Always preserve original year labels when joining
- Use year_int for sorting only
- Handle missing years gracefully (skip or report N/A)
- Verify both files cover the same company and time periods

## Year-over-Year Growth Special Handling

```python
# YoY growth requires at least 2 years of data
# Produces N-1 data points from N years
# Records must already be sorted by year_int (canonical integer year)
records.sort(key=lambda r: r['year_int'])
growth_results = []
for i in range(1, len(records)):
    prev_val = compute_base_metric(records[i-1], base_metric)
    curr_val = compute_base_metric(records[i], base_metric)
    yoy = (curr_val - prev_val) / abs(prev_val) * 100 if prev_val != 0 else None
    growth_results.append((records[i]['year_label'], round(yoy, 2) if yoy is not None else None))
```

## Error Handling & Edge Cases

- **Missing data**: If a required field is missing for a year, skip that year or report N/A
- **Zero denominators**: Guard against division by zero in margin calculations
- **Negative values**: Some metrics can be negative (e.g., negative net income → negative margin)
- **Currency/unit normalization**: All values in a file should be in the same units; watch for "in millions" notes
- **Fiscal year conventions**: Some companies have fiscal years ending in different months; "FY2024" may end in Jan 2024, Mar 2024, etc.
- **Decoy data**: Files may contain plausible but incorrect data for other companies or time periods

## Complete Workflow Summary

```
1. READ the task instruction carefully to identify:
   - Target company
   - Data directory location
   - Required metric(s)
   - Conditional logic (threshold, primary vs. alternative)
   - Output file path and column names
   - Rounding/formatting requirements

2. DISCOVER the correct data file(s):
   - List directory contents
   - Inspect each file's content
   - Match company name/ticker
   - Verify required fields are present

3. PARSE the data:
   - Detect format (CSV, JSON, fixed-width, HTML)
   - Extract header/data sections
   - Map field names to canonical concepts
   - Normalize numeric values

4. COMPUTE:
   - Implement the metric formula
   - Apply conditional logic
   - Round to specified precision

5. OUTPUT:
   - Write to specified file path
   - Use specified column names
   - Format values correctly (percentages as numbers)
```
