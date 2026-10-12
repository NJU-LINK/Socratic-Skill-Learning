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
    """
    Find the correct financial data file for the target company.
    Returns list of (filepath, content, parsed_records) tuples.
    """
    candidates = []
    
    for fname in os.listdir(directory):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        
        with open(fpath, 'r', errors='ignore') as f:
            content = f.read()
        
        # Check 1: Company identity
        if company_name.lower() not in content.lower():
            continue
        
        # Check 2: Parse the data
        try:
            records = parse_financial_data(fpath, content)
        except Exception:
            continue
        
        if not records:
            continue
        
        # Check 3: Validate data completeness
        # Must have multiple years (annual data, not quarterly)
        years = [r.get('year', '') for r in records]
        if len(years) < 2:
            continue
        
        # Check for quarterly pattern (Q1, Q2, etc.)
        if any(re.match(r'Q\d', y) for y in years):
            continue
        
        # Check 4: Must have required fields for common metrics
        has_revenue = all('revenue' in r for r in records)
        if not has_revenue:
            continue
        
        # Score by completeness (more fields = better)
        field_count = sum(1 for r in records for k in r.keys() if k != 'year')
        candidates.append((fpath, content, records, field_count))
    
    # Sort by field completeness (descending)
    candidates.sort(key=lambda x: x[3], reverse=True)
    
    # Return top candidates
    return [(fpath, content, records) for fpath, content, records, _ in candidates]

def parse_financial_data(filepath, content):
    """
    Parse financial data from various formats.
    Detects format and extracts structured records.
    Returns list of dicts: [{year, revenue, gross_profit, ...}, ...]
    """
    lines = content.strip().split('\n')
    
    # Detect format
    if content.strip().startswith('{') or content.strip().startswith('['):
        return _parse_json(content)
    elif '<table' in content.lower():
        return _parse_html(content)
    elif _is_csv_like(content):
        return _parse_csv_like(lines)
    elif _is_log_format(content):
        return _parse_log_format(lines)
    else:
        return _parse_fixed_width(lines)

def _is_csv_like(content):
    """Check if content looks like CSV (has comma-separated header with multiple financial columns)."""
    lines = content.strip().split('\n')
    for line in lines:
        if not line.strip() or line.strip().startswith('=') or line.strip().startswith('-'):
            continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 3:  # Need at least 3 columns to be a real data table
            field_matches = sum(1 for p in parts if any(kw in p.lower() for kw in ['year', 'revenue', 'profit', 'income', 'sales', 'equity']))
            if field_matches >= 2:
                return True
    return False

def _is_log_format(content):
    """Check if content uses log-style markers like [INFO], [DATA], [WARN]."""
    return bool(re.search(r'\[(INFO|DATA|WARN|ERROR)\]', content))

def _parse_json(content):
    """Parse JSON format (nested or flat)."""
    import json
    data = json.loads(content)
    records = []
    # Handle various JSON structures
    if isinstance(data, list):
        for item in data:
            record = _extract_fields_from_dict(item)
            if record:
                records.append(record)
    elif isinstance(data, dict):
        # Look for common patterns
        if 'data' in data and isinstance(data['data'], list):
            for item in data['data']:
                record = _extract_fields_from_dict(item)
                if record:
                    records.append(record)
        elif 'financials' in data:
            for item in data['financials']:
                record = _extract_fields_from_dict(item)
                if record:
                    records.append(record)
        else:
            # Single record
            record = _extract_fields_from_dict(data)
            if record:
                records.append(record)
    return records

def _extract_fields_from_dict(d):
    """Extract financial fields from a dictionary, normalizing keys."""
    record = {}
    # Year
    for key in ['year', 'fiscal_year', 'fy', 'period']:
        if key in d:
            record['year'] = str(d[key])
            break
    # Revenue
    for key in ['revenue', 'total_revenue', 'sales']:
        if key in d:
            record['revenue'] = float(d[key])
            break
    # Gross Profit
    for key in ['gross_profit', 'grossprofit', 'gp']:
        if key in d:
            record['gross_profit'] = float(d[key])
            break
    # Operating Income
    for key in ['operating_income', 'operatingincome', 'oi', 'ebit']:
        if key in d:
            record['operating_income'] = float(d[key])
            break
    # Net Income
    for key in ['net_income', 'netincome', 'ni', 'net_profit']:
        if key in d:
            record['net_income'] = float(d[key])
            break
    # Equity
    for key in ['equity', 'shareholders_equity', 'total_equity', 'se']:
        if key in d:
            record['equity'] = float(d[key])
            break
    return record if 'year' in record and 'revenue' in record else None

def _parse_html(content):
    """Parse HTML table format."""
    from html.parser import HTMLParser
    
    class FinancialTableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_table = False
            self.in_row = False
            self.in_cell = False
            self.rows = []
            self.current_row = []
            self.current_cell = ''
        
        def handle_starttag(self, tag, attrs):
            if tag == 'table':
                self.in_table = True
            elif tag == 'tr' and self.in_table:
                self.in_row = True
                self.current_row = []
            elif tag in ['td', 'th'] and self.in_row:
                self.in_cell = True
                self.current_cell = ''
        
        def handle_endtag(self, tag):
            if tag == 'table':
                self.in_table = False
            elif tag == 'tr' and self.in_row:
                self.in_row = False
                if self.current_row:
                    self.rows.append(self.current_row)
            elif tag in ['td', 'th'] and self.in_cell:
                self.in_cell = False
                self.current_row.append(self.current_cell.strip())
        
        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data
    
    parser = FinancialTableParser()
    parser.feed(content)
    
    records = []
    if len(parser.rows) >= 2:
        header = parser.rows[0]
        for row in parser.rows[1:]:
            if len(row) == len(header):
                record = {}
                for i, cell in enumerate(row):
                    header_lower = header[i].lower()
                    if 'year' in header_lower or 'fy' in header_lower:
                        record['year'] = cell
                    elif 'revenue' in header_lower:
                        record['revenue'] = _parse_number(cell)
                    elif 'gross' in header_lower and 'profit' in header_lower:
                        record['gross_profit'] = _parse_number(cell)
                    elif 'operating' in header_lower:
                        record['operating_income'] = _parse_number(cell)
                    elif 'net' in header_lower and 'income' in header_lower:
                        record['net_income'] = _parse_number(cell)
                    elif 'equity' in header_lower:
                        record['equity'] = _parse_number(cell)
                if 'year' in record and 'revenue' in record:
                    records.append(record)
    return records

def _parse_csv_like(lines):
    """Parse CSV-like format with header row."""
    records = []
    header = None
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('//') or line.startswith('='):
            continue
        
        parts = [p.strip() for p in line.split(',')]
        
        # Detect header - must have multiple columns with financial keywords
        if header is None:
            if len(parts) >= 2:  # Must have at least 2 columns
                # Check if multiple parts match financial field names
                field_matches = 0
                for p in parts:
                    p_lower = p.lower()
                    if any(kw in p_lower for kw in ['year', 'revenue', 'profit', 'income', 'sales', 'equity']):
                        field_matches += 1
                
                # If at least 2 parts match financial fields, it's likely a header
                if field_matches >= 2:
                    header = [p.lower() for p in parts]
                    continue
        
        # Parse data row
        if header and len(parts) == len(header):
            record = {}
            for i, value in enumerate(parts):
                col = header[i]
                if 'year' in col or 'fy' in col or 'period' in col:
                    record['year'] = value
                elif 'revenue' in col or 'sales' in col:
                    record['revenue'] = _parse_number(value)
                elif 'gross' in col and 'profit' in col:
                    record['gross_profit'] = _parse_number(value)
                elif 'operating' in col:
                    record['operating_income'] = _parse_number(value)
                elif 'net' in col and 'income' in col:
                    record['net_income'] = _parse_number(value)
                elif 'equity' in col:
                    record['equity'] = _parse_number(value)
            
            if 'year' in record and 'revenue' in record:
                records.append(record)
    
    return records

def _parse_log_format(lines):
    """Parse log-style format with [DATA], [INFO], [WARN] markers."""
    records = {}
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Look for [DATA] lines with financial data
        if '[DATA]' in line:
            # Extract year and values
            # Pattern: [DATA] FY2024: Revenue=$58,000M, GP=$37,800M
            match = re.search(r'FY(\d{4}):\s*(.*)', line)
            if match:
                year = f"FY{match.group(1)}"
                data_part = match.group(2)
                
                record = {'year': year}
                
                # Parse key=value pairs
                for pair in data_part.split(','):
                    pair = pair.strip()
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        key = key.strip().lower()
                        value = _parse_number(value)
                        
                        if 'revenue' in key:
                            record['revenue'] = value
                        elif 'gp' in key or 'gross' in key:
                            record['gross_profit'] = value
                        elif 'ni' in key or 'net' in key:
                            record['net_income'] = value
                        elif 'oi' in key or 'operating' in key:
                            record['operating_income'] = value
                
                if 'year' in record and 'revenue' in record:
                    records[year] = record
    
    return list(records.values())

def _parse_fixed_width(lines):
    """Parse fixed-width format by detecting column positions."""
    records = []
    header = None
    
    for line in lines:
        line = line.rstrip()
        if not line or line.startswith('=') or line.startswith('-'):
            continue
        
        # Detect header by looking for financial keywords
        if header is None and any(kw in line.lower() for kw in ['year', 'revenue', 'profit']):
            # Try to identify column positions
            header = line
            continue
        
        # Parse data rows
        if header:
            # Simple approach: split by multiple spaces
            parts = line.split()
            if len(parts) >= 2:
                record = {}
                for part in parts:
                    if re.match(r'FY\d{4}|\d{4}', part):
                        record['year'] = part
                    else:
                        # Try to parse as number
                        num = _parse_number(part)
                        if num is not None:
                            # Assign to fields in order
                            if 'revenue' not in record:
                                record['revenue'] = num
                            elif 'gross_profit' not in record:
                                record['gross_profit'] = num
                            elif 'net_income' not in record:
                                record['net_income'] = num
                
                if 'year' in record and 'revenue' in record:
                    records.append(record)
    
    return records

def _parse_number(s):
    """
    Parse a numeric string, handling various formats:
    - Currency symbols: $, €, £
    - Thousands separators: commas (US), periods (EU)
    - Unit indicators: M, mn, million, B, bn, billion
    - Negative in parentheses: (500) means -500
    - Percentage signs
    """
    if not s or not isinstance(s, str):
        return None
    
    s = s.strip()
    
    # Handle parentheses (negative)
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    
    # Remove currency symbols
    s = re.sub(r'[\$€£¥]', '', s)
    
    # Remove percentage sign
    s = s.replace('%', '')
    
    # Handle unit multipliers - extract BEFORE removing separators
    multiplier = 1
    unit_match = re.search(r'\s*(M|mn|million|B|bn|billion|K|k|thousand)\b', s, re.IGNORECASE)
    if unit_match:
        unit = unit_match.group(1).upper()
        if unit in ['M', 'MN', 'MILLION']:
            multiplier = 1_000_000
        elif unit in ['B', 'BN', 'BILLION']:
            multiplier = 1_000_000_000
        elif unit in ['K', 'THOUSAND']:
            multiplier = 1_000
        s = s[:unit_match.start()] + s[unit_match.end():]
    
    # Now handle thousands separators
    s = s.strip()
    
    # Determine format by analyzing comma and period positions
    has_comma = ',' in s
    has_period = '.' in s
    
    if has_comma and has_period:
        # Both present - determine which is decimal
        last_comma = s.rfind(',')
        last_period = s.rfind('.')
        
        if last_comma > last_period:
            # Comma is decimal separator (EU format): 1.234.567,89
            s = s.replace('.', '').replace(',', '.')
        else:
            # Period is decimal separator (US format): 1,234,567.89
            s = s.replace(',', '')
    elif has_comma:
        # Only commas present
        # Count commas and check pattern
        comma_count = s.count(',')
        
        if comma_count > 1:
            # Multiple commas = thousands separators (US): 1,234,567
            s = s.replace(',', '')
        else:
            # Single comma - check if it's thousands or decimal
            # If followed by exactly 3 digits at end, it's thousands (US): 1,234
            # If followed by 1-2 digits, it's decimal (EU): 1,23
            parts = s.split(',')
            if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
                # Thousands separator
                s = s.replace(',', '')
            else:
                # Decimal separator (EU format)
                s = s.replace(',', '.')
    elif has_period:
        # Only periods present
        period_count = s.count('.')
        
        if period_count > 1:
            # Multiple periods = thousands separators (EU): 1.234.567
            s = s.replace('.', '')
        # else: single period is decimal, leave as is
    
    # Try to parse
    try:
        value = float(s)
        if negative:
            value = -value
        return value * multiplier
    except ValueError:
        return None

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
