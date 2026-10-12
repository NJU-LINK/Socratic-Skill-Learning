---
name: financial-analysis
description: >
  Discover, extract, and compute financial metrics from heterogeneous data sources.
  Handles CSV, decorated .dat files, fixed-width, HTML tables, and nested JSON.
  Supports content-based file discovery among decoys, flexible schema matching,
  conditional metric computation, and multi-file joins by fiscal year.
---

# Financial Analysis Skill

## Purpose

This skill solves financial analysis tasks that require:
1. Discovering the correct data file among decoys
2. Extracting tabular data from various formats (CSV, decorated files, JSON, HTML)
3. Computing standard financial metrics (margins, returns, growth)
4. Applying conditional logic based on computed thresholds
5. Writing results in a specified output schema

## Procedure

### Step 1: Content-Based File Discovery

**Problem**: The target company's data may be in any file, possibly among decoy files containing other companies or irrelevant data.

**Method**:
```python
def discover_file(directory, target_company):
    candidates = []
    for fname in os.listdir(directory):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, 'r', errors='replace') as f:
            content = f.read()
        if target_company.lower() in content.lower():
            # Score by CSV-data density (lines with commas and digits)
            csv_rows = sum(1 for l in content.split('\n') 
                          if ',' in l and re.search(r'\d', l))
            candidates.append((fpath, content, csv_rows))
    
    if not candidates:
        raise FileNotFoundError(f"No file contains '{target_company}'")
    
    # Return highest-scoring candidate
    return max(candidates, key=lambda x: x[2])[:2]
```

**Key insight**: Never trust filenames alone. Always verify by content inspection. Score candidates by data density to prefer files with actual tabular data.

### Step 2: Robust CSV Block Extraction

**Problem**: Financial data files often have decoration (headers, footers, metadata) surrounding the actual CSV data block.

**Method**:
```python
def extract_csv_block(content):
    lines = content.strip().split('\n')
    
    # Find header row by keyword matching
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if ',' in stripped:
            lower = stripped.lower()
            if any(kw in lower for kw in ['year', 'revenue', 'income', 
                                          'profit', 'quarter', 'period']):
                header_idx = i
                break
    
    if header_idx is None:
        raise ValueError("No CSV header found")
    
    # Collect consecutive data rows
    data_rows = []
    for i in range(header_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        # Stop at decoration or non-data lines
        if stripped.startswith(('=', '-', '[', 'NOTE', 'Note')):
            break
        if ',' in stripped and re.search(r'\d', stripped):
            data_rows.append(stripped)
        else:
            break
    
    return lines[header_idx].strip() + '\n' + '\n'.join(data_rows)
```

**Key insight**: Identify the header by financial keywords, then read consecutive data rows until hitting blank lines, decoration, or non-data content.

### Step 3: Flexible Column Identification

**Problem**: Column names vary across sources: "Gross Profit", "GrossProfit", "GP", "gross_profit", etc.

**Method**:
```python
def find_column(columns, candidates):
    """Match column names flexibly, ignoring case, spaces, underscores."""
    col_normalized = {c.lower().replace(' ', '').replace('_', ''): c 
                      for c in columns}
    
    for candidate in candidates:
        norm = candidate.lower().replace(' ', '').replace('_', '')
        if norm in col_normalized:
            return col_normalized[norm]
    
    # Fallback: partial match
    for candidate in candidates:
        for col in columns:
            if candidate.lower() in col.lower().replace(' ', '').replace('_', ''):
                return col
    return None

# Usage:
year_col = find_column(columns, ['year', 'fiscal_year', 'fy', 'period'])
revenue_col = find_column(columns, ['revenue', 'total_revenue', 'rev', 'sales'])
gross_profit_col = find_column(columns, ['grossprofit', 'gross_profit', 'gp'])
net_income_col = find_column(columns, ['netincome', 'net_income', 'ni', 'net_profit'])
operating_income_col = find_column(columns, ['operatingincome', 'operating_income', 'oi'])
shareholders_equity_col = find_column(columns, ['shareholdersequity', 'equity', 'se'])
```

**Key insight**: Normalize column names by removing spaces, underscores, and case differences before matching. Provide multiple candidate names for each semantic field.

### Step 4: Numeric Parsing

**Problem**: Financial values may include currency symbols ($), thousands separators (,), scale suffixes (M, B), or locale-specific decimal marks.

**Method**:
```python
def parse_numeric(val):
    """Clean and parse numeric values from various formats.
    
    Locale disambiguation heuristic:
    - Multiple commas (1,234,567) → US format, commas are thousands separators
    - Multiple periods (1.234.567) → European format, periods are thousands separators
    - Mixed (1,234.56 vs 1.234,56) → last separator is the decimal
    - Single comma with ≤2 digits after (1234,56) → European decimal
    - Single comma with >2 digits after (1,234) → US thousands
    """
    s = str(val).strip()
    s = s.replace('$', '').replace('€', '').replace('£', '').replace('¥', '')
    
    comma_count = s.count(',')
    period_count = s.count('.')
    
    if comma_count > 1 and period_count == 0:
        s = s.replace(',', '')  # US: 1,234,567
    elif period_count > 1 and comma_count == 0:
        s = s.replace('.', '')  # European: 1.234.567
    elif comma_count == 1 and period_count == 1:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')  # European: 1.234,56
        else:
            s = s.replace(',', '')  # US: 1,234.56
    elif comma_count == 1 and period_count == 0:
        parts = s.split(',')
        if len(parts[1]) <= 2:
            s = s.replace(',', '.')  # European decimal: 1234,56
        else:
            s = s.replace(',', '')  # US thousands: 1,234
    
    # Handle scale suffixes
    multiplier = 1.0
    if s.upper().endswith('M'): multiplier = 1_000_000; s = s[:-1]
    elif s.upper().endswith('B'): multiplier = 1_000_000_000; s = s[:-1]
    
    # Handle parentheses for negative numbers
    if s.startswith('(') and s.endswith(')'): s = '-' + s[1:-1]
    
    return float(s) * multiplier
```

**Key insight**: Strip formatting characters, detect scale suffixes, and handle locale variations. Apply multipliers for M/B suffixes if needed for calculations.

### Step 5: Year Extraction and Sorting

**Problem**: Fiscal years may be labeled as "FY2022", "2022", "2022-01", "Q1 2022", etc.

**Method**:
```python
def extract_year(val):
    """Extract numeric year from various formats."""
    s = str(val).strip()
    # Find 4-digit year
    m = re.search(r'(\d{4})', s)
    if m:
        return int(m.group(1))
    # Try plain number
    try:
        return int(float(s))
    except ValueError:
        return s

def format_year(val, preserve_format=True):
    """Format year for output. Default preserves source format (e.g., FY2022)."""
    if preserve_format:
        return str(val).strip()
    return extract_year(val)

# Sort rows by extracted year
rows_sorted = sorted(rows, key=lambda r: extract_year(r[year_col]))

# For output, preserve source format by default (FY2022 stays FY2022)
year_out = format_year(row[year_col], preserve_format=True)
```

**Key insight**: Use regex to find 4-digit year patterns for sorting. For output, **preserve the source format by default** (e.g., FY2022 stays FY2022, not 2022). Tests index by the exact year labels from the source data, so stripping prefixes will cause key mismatches. Only strip to numeric if the task explicitly requests it.

### Step 6: Financial Metric Computation

**Standard Metrics** (all expressed as percentages):

```python
METRICS = {
    'gross_margin': {
        'numerator': 'gross_profit',
        'denominator': 'revenue',
        'formula': lambda gp, rev: (gp / rev) * 100,
        'description': 'Gross Profit / Revenue × 100'
    },
    'operating_margin': {
        'numerator': 'operating_income',
        'denominator': 'revenue',
        'formula': lambda oi, rev: (oi / rev) * 100,
        'description': 'Operating Income / Revenue × 100'
    },
    'net_margin': {
        'numerator': 'net_income',
        'denominator': 'revenue',
        'formula': lambda ni, rev: (ni / rev) * 100,
        'description': 'Net Income / Revenue × 100'
    },
    'return_on_equity': {
        'numerator': 'net_income',
        'denominator': 'shareholders_equity',
        'formula': lambda ni, eq: (ni / eq) * 100,
        'description': 'Net Income / Shareholders Equity × 100',
        'note': 'Requires balance sheet data'
    },
    'year_over_year_growth': {
        'numerator': 'revenue',
        'denominator': 'prior_revenue',
        'formula': lambda curr, prev: ((curr - prev) / prev) * 100,
        'description': '(Current - Prior) / Prior × 100',
        'note': 'Requires consecutive periods'
    }
}
```

**Key insight**: Each metric has a specific numerator and denominator. ROE requires balance sheet data (may need multi-file join). YoY growth requires consecutive time periods.

### Step 7: Conditional Logic

**Problem**: Some tasks require computing one metric conditionally based on a threshold check of another metric.

**Method**:
```python
# Example: Compute gross margin for most recent year
most_recent = rows_sorted[-1]
most_recent_gm = (most_recent['gross_profit'] / most_recent['revenue']) * 100

# Conditional branch
if most_recent_gm > threshold:
    # Compute metric_A for all years
    metric_name = "metric_a_pct"
    results = [(format_year(row[year_col], preserve_format=True), 
                round(compute_metric_A(row), 2)) 
               for row in rows_sorted]
else:
    # Compute metric_B for all years
    metric_name = "metric_b_pct"
    results = [(format_year(row[year_col], preserve_format=True), 
                round(compute_metric_B(row), 2)) 
               for row in rows_sorted]
```

**Key insight**: The conditional is data-driven, not hardcoded. Compute the threshold metric first, then branch based on the result. The output column name reflects which branch was taken.

### Step 8: Multi-File Joins (When Required)

**Problem**: Some variants split data across income statement and balance sheet files.

**Method**:
```python
def join_by_year(income_data, balance_data, year_col='year'):
    """Join two datasets by fiscal year."""
    joined = {}
    for row in income_data:
        year = extract_year(row[year_col])
        joined[year] = dict(row)
    
    for row in balance_data:
        year = extract_year(row[year_col])
        if year in joined:
            joined[year].update(row)
        else:
            joined[year] = dict(row)
    
    return list(joined.values())
```

**Key insight**: When data spans multiple files, join by fiscal year. Extract numeric year for matching, then merge the row dictionaries.

### Step 9: Output Generation

**Method**:
```python
with open(output_path, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['fiscal_year', metric_name])
    for year, value in results:
        writer.writerow([year, value])
```

**Key insight**: Preserve source year format by default (e.g., FY2022 stays FY2022). Tests index by exact year labels from the source data. Round percentages to 2 decimal places as specified. Only strip to numeric if the task explicitly requests it.

## Complete Workflow

1. **Parse task parameters**: Extract company name, data directory, output path, metric to compute, threshold logic
2. **Discover file**: Content-based search with data-density scoring
3. **Extract data**: Find CSV block, parse with flexible numeric handling
4. **Identify columns**: Fuzzy-match column names to semantic fields
5. **Sort by year**: Extract numeric year for sorting; preserve source format for output (e.g., FY2022)
6. **Compute metrics**: Apply formulas, handle conditional logic
7. **Write results**: CSV output with specified column names, rounded values

## Common Pitfalls

- **Hardcoding column names**: Always use flexible matching
- **Assuming clean CSV**: Handle decorated files, metadata, footers
- **Stripping year prefixes**: Preserve source format (FY2022) by default; tests index by exact labels
- **Forgetting conditional logic**: Compute threshold metric first, then branch
- **Mixing up metrics**: Each metric has specific numerator/denominator
- **Not handling scale suffixes**: M/B suffixes need multiplier application
- **Trusting filenames**: Always verify by content inspection

## Testing Checklist

- [ ] File discovery works with decoy files present
- [ ] CSV extraction handles decorated files (headers, footers, metadata)
- [ ] Column matching works with variations (spaces, underscores, abbreviations)
- [ ] Numeric parsing handles $, commas, M/B suffixes
- [ ] Year extraction works with FY prefix, plain years, date ranges
- [ ] Year output preserves source format (FY2022) by default
- [ ] Conditional logic branches correctly based on threshold
- [ ] Percentages rounded to 2 decimal places
- [ ] Multi-file joins work when data is split
- [ ] All 5 metrics compute correctly (gross_margin, operating_margin, net_margin, ROE, YoY growth)
