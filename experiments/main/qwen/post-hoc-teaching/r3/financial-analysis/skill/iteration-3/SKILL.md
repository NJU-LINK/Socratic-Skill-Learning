---
name: financial-analysis
description: >
  Discover, parse, and compute financial metrics from company data files in varied
  formats (CSV, JSON, fixed-width, HTML, custom delimited). Handles data discovery
  among decoy files, multi-format parsing, metric computation (gross margin,
  operating margin, net margin, return on equity, year-over-year growth),
  conditional logic on computed values, and structured output generation.
---

# Financial Analysis Skill

## Overview

This skill solves financial data analysis tasks that follow a common pattern:
1. **Discover** the correct data file(s) among potentially many files (including decoys)
2. **Parse** the financial data from varied formats and schemas
3. **Compute** the requested financial metric(s)
4. **Apply** any conditional logic specified in the task
5. **Output** results in the required format

## Step 1: Data Discovery

### Strategy
- List all files in the specified data directory (typically `/app/financials/`)
- Examine each file's content to identify the **target company** mentioned in the task
- Reject decoy files by checking:
  - Company name mismatch (e.g., wrong company, wrong ticker)
  - Data granularity mismatch (e.g., quarterly when annual is needed)
  - Irrelevant data type (e.g., product-level sales instead of company financials)
  - Explicit disclaimers (e.g., "not annual", "cache data", "backup records")

### File Identification Heuristics
- Look for the company name or ticker in file headers/metadata
- Verify the data contains the required financial line items (Revenue, Gross Profit, Net Income, etc.)
- Check that the data coverage matches what's needed (annual vs. quarterly)
- Prefer files with structured financial summaries over transactional or cache data

### Single-File vs Multi-File Scenarios

The `statement_topology` axis determines whether data lives in one file or must be
joined across multiple files (e.g., income statement + balance sheet). **Always
discover ALL relevant files first**, then determine whether a join is needed.

```python
import os
import re

def discover_all_financial_files(directory, target_company):
    """
    Find ALL files containing the target company's financial data.
    Returns list of (filename, filepath, content) for every matching file.
    
    IMPORTANT: Do NOT stop at the first match. In multi-file scenarios
    (e.g., separate income statement and balance sheet files), you need
    all of them.
    
    Detects JSON, HTML, and text-based files by extension and content.
    """
    candidates = []
    financial_exts = {'.json', '.html', '.htm', '.csv', '.tsv', '.txt', '.dat'}
    for fname in sorted(os.listdir(directory)):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, 'r', errors='ignore') as f:
            content = f.read()
        _, ext = os.path.splitext(fname)
        is_known_format = ext.lower() in financial_exts
        has_company = target_company.lower() in content.lower()
        has_financial = bool(re.search(
            r'revenue|sales|turnover|equity|assets|liabilit',
            content, re.IGNORECASE
        ))
        if has_company and (has_financial or is_known_format):
            candidates.append((fname, fpath, content))
    return candidates

def classify_and_merge_files(candidates, required_fields):
    """
    Given multiple candidate files, determine if data must be merged.
    
    Strategy:
    1. Parse each file independently into {fiscal_year: {field: value}} dicts.
    2. Check which required fields each file provides.
    3. If one file has all required fields → single-file mode.
    4. If fields are split across files → merge by fiscal year key.
    
    Args:
        candidates: list of (fname, fpath, content) from discover_all_financial_files
        required_fields: set of canonical field names needed for the metric
    
    Returns:
        dict: {fiscal_year: {field: value, ...}} merged records
    """
    file_records = {}  # fname -> {fiscal_year: {field: value}}
    file_field_coverage = {}  # fname -> set of canonical fields found
    
    for fname, fpath, content in candidates:
        records = extract_financial_data(content, filename=fname)  # returns list of dicts
        if not records:
            continue
        by_year = {}
        fields_found = set()
        for rec in records:
            fy = rec.get('fiscal_year', '')
            by_year[fy] = rec
            fields_found.update(k for k in rec.keys() if k != 'fiscal_year')
        file_records[fname] = by_year
        file_field_coverage[fname] = fields_found
    
    # Check if single file covers everything
    for fname, fields in file_field_coverage.items():
        if required_fields.issubset(fields):
            return file_records[fname]  # Single file is sufficient
    
    # Multi-file merge: combine by fiscal year
    all_years = set()
    for by_year in file_records.values():
        all_years.update(by_year.keys())
    
    merged = {}
    for fy in sorted(all_years):
        merged[fy] = {'fiscal_year': fy}
        for fname, by_year in file_records.items():
            if fy in by_year:
                merged[fy].update(by_year[fy])
    
    return merged
```

**When is a merge needed?** Common patterns:
- **ROE** requires Net Income (from income statement) AND Total Equity (from balance sheet)
- **Debt-to-Equity** requires Total Debt (balance sheet) AND Total Equity (balance sheet)
- Tasks requesting income-statement-only metrics (gross margin, net margin) typically
  have everything in one file

## Step 2: Data Parsing

### Format Detection and Parsing

Support these common formats:

#### CSV / Delimited Text
```python
import csv

def parse_csv(filepath, delimiter=','):
    """Parse CSV or delimited file, auto-detecting header."""
    with open(filepath, 'r') as f:
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)
    # First non-empty row is typically the header
    header = None
    data_rows = []
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = [cell.strip() for cell in row]
        else:
            data_rows.append([cell.strip() for cell in row])
    return header, data_rows
```

#### Fixed-Width / Banner Format
Files with decorative borders (===, ---, etc.) and labeled fields.
**Critical**: These may use commas OR pure whitespace as delimiters.

```python
import re

def detect_delimiter(header_line, sample_data_lines):
    """
    Detect whether a data section uses tab, comma, or whitespace delimiters.
    
    Strategy:
    - If the header contains tabs → tab-delimited (handles multi-word headers)
    - If the header contains commas → comma-delimited
    - If header has multiple whitespace-separated tokens → whitespace-delimited
    - Fall back to comma if any data line contains commas
    """
    if '\t' in header_line:
        return '\t'
    if ',' in header_line:
        return ','
    # Check if whitespace splitting gives multiple columns
    if len(header_line.split()) >= 2:
        # Verify data lines also split into same number of columns
        header_cols = len(header_line.split())
        for line in sample_data_lines[:3]:
            if len(line.split()) != header_cols:
                return ','  # Mismatch → fall back to comma
        return 'whitespace'
    return ','

def parse_banner_or_fixedwidth(content):
    """
    Parse fixed-width or banner-style financial data.
    Handles BOTH comma-separated and whitespace-separated formats.
    
    Example comma-in-banner:
        ======================================================================
        Company:  NVIDIA Corporation
        ======================================================================
        Year,Revenue,GrossProfit,NetIncome
        FY2024,60922,44301,29760
    
    Example true fixed-width (no commas):
        ======================================================================
        Company:  NVIDIA Corporation
        ======================================================================
        Year    Revenue    Gross Profit    Net Income
        FY2024   60922       44301          29760
        FY2025  130497       97858          72880
    """
    lines = content.strip().split('\n')
    
    # Phase 1: Filter out non-data lines (banners, metadata, notes, bullet points)
    data_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip decorative lines (all same character repeated)
        if re.match(r'^[=\-\*\#\~]+$', stripped):
            continue
        # Skip bullet-point lines (starting with - or *)
        if re.match(r'^[\-\*]\s', stripped):
            continue
        # Skip metadata lines (Key: Value pattern, no commas, not starting with digit/FY)
        if ':' in stripped and ',' not in stripped:
            first_word = stripped.split()[0].rstrip(':')
            if not re.match(r'^\d|FY', first_word, re.IGNORECASE):
                continue
        # Skip NOTE/DATA COVERAGE lines
        if stripped.upper().startswith(('NOTE', 'DATA COVERAGE')):
            continue
        data_lines.append(stripped)
    
    if not data_lines:
        return None, []
    
    # Phase 2: Find the header line and detect delimiter
    # A valid header must: (a) have multiple columns, (b) be mostly alphabetic,
    # AND (c) contain at least one recognized financial field name
    financial_keywords = {
        'revenue', 'sales', 'turnover', 'income', 'profit', 'loss',
        'equity', 'assets', 'liabilities', 'expense', 'earnings',
        'year', 'period', 'fy', 'operating', 'gross', 'net',
        'operatingincome', 'netincome', 'grossprofit', 'total',
    }
    header = None
    header_idx = None
    for idx, line in enumerate(data_lines):
        # Detect delimiter early: tab > comma > whitespace
        if '\t' in line:
            parts = [p.strip() for p in line.split('\t')]
        elif ',' in line:
            parts = [p.strip() for p in line.split(',')]
        else:
            parts = line.split()
        
        if len(parts) >= 2:
            alpha_count = sum(1 for p in parts if re.match(r'^[A-Za-z_ /]+$', p))
            if alpha_count >= len(parts) * 0.6:
                # Check for at least one recognized financial keyword
                lower_parts = [p.lower().replace(' ', '') for p in parts]
                has_financial = any(
                    any(kw in lp for kw in financial_keywords)
                    for lp in lower_parts
                )
                if has_financial:
                    header = parts
                    header_idx = idx
                    break
    
    if header is None:
        return None, []
    
    # Phase 3: Determine delimiter from header
    delimiter = detect_delimiter(
        ','.join(header) if ',' in data_lines[header_idx] else ' '.join(header),
        data_lines[header_idx + 1:]
    )
    
    # Phase 3.5: Check for multi-word header mismatch
    # If header has more tokens than data rows, use position-based parsing
    first_data_line = data_lines[header_idx + 1] if header_idx + 1 < len(data_lines) else None
    if first_data_line:
        # Use the same delimiter for both header and data token counting
        if delimiter == '\t':
            header_token_count = len([p.strip() for p in data_lines[header_idx].split('\t')])
            data_token_count = len([p.strip() for p in first_data_line.split('\t')])
        elif delimiter == ',':
            header_token_count = len([p.strip() for p in data_lines[header_idx].split(',')])
            data_token_count = len([p.strip() for p in first_data_line.split(',')])
        else:
            header_token_count = len(data_lines[header_idx].split())
            data_token_count = len(first_data_line.split())
        if header_token_count > data_token_count:
            # Multi-word headers detected: use position-based parsing
            header, data_rows = parse_fixedwidth_multiword(
                data_lines[header_idx],
                data_lines[header_idx + 1:]
            )
            return header, data_rows
    
    # Phase 4: Parse data rows using detected delimiter
    data_rows = []
    for line in data_lines[header_idx + 1:]:
        if delimiter == '\t':
            parts = [p.strip() for p in line.split('\t')]
        elif delimiter == 'whitespace':
            parts = line.split()
        else:
            parts = [p.strip() for p in line.split(',')]
        
        if len(parts) >= 2:
            data_rows.append(parts)
    
    return header, data_rows

def parse_fixedwidth_multiword(header_line, data_lines):
    """
    Parse fixed-width files where header has multi-word column names
    (e.g., "Gross Profit" as two words) but data values are single tokens.
    
    Strategy: Use data token POSITIONS to determine column boundaries,
    then slice the header at those same positions.
    
    This works because in properly aligned fixed-width files, data values
    and header names share the same column boundaries.
    
    Example:
        Year    Revenue    Gross Profit    Net Income
        FY2024  60922      44301           29760
        
    Data tokens start at positions [0, 8, 19, 34]
    Header sliced at those positions: ['Year', 'Revenue', 'Gross Profit', 'Net Income']
    """
    if not data_lines:
        return [], []
    
    first_data = data_lines[0]
    
    # Find token boundaries (start and end positions) in first data line
    token_boundaries = []  # List of (start, end) tuples
    i = 0
    while i < len(first_data):
        if first_data[i] != ' ':
            start = i
            while i < len(first_data) and first_data[i] != ' ':
                i += 1
            end = i
            token_boundaries.append((start, end))
        else:
            i += 1
    
    if not token_boundaries:
        return [], []
    
    # Extract header names by slicing at data token boundaries
    # Each column spans from the start of one token to the start of the next (or end of line)
    header_cols = []
    for idx, (start, end) in enumerate(token_boundaries):
        # Column extends from this token's start to the next token's start (or end of header)
        if idx + 1 < len(token_boundaries):
            col_end = token_boundaries[idx + 1][0]
        else:
            col_end = len(header_line)
        col_text = header_line[start:col_end].strip()
        header_cols.append(col_text)
    
    # Extract all data rows using same column boundaries
    all_rows = []
    for line in data_lines:
        row = []
        for idx, (start, end) in enumerate(token_boundaries):
            if idx + 1 < len(token_boundaries):
                col_end = token_boundaries[idx + 1][0]
            else:
                col_end = len(line)
            if start < len(line):
                val = line[start:min(col_end, len(line))].strip()
                row.append(val)
            else:
                row.append('')
        all_rows.append(row)
    
    return header_cols, all_rows

def is_year_field(value):
    """
    Check if a string looks like a fiscal year label.
    Handles: FY2024, 2024, FY24, FY 2024, Year 2024, '24, etc.
    """
    s = value.strip().strip("'")
    # Pure 4-digit year
    if re.match(r'^\d{4}$', s):
        return True
    # FY prefix: FY2024, FY24, FY 2024, FY 24
    if re.match(r'^FY\s*\d{2,4}$', s, re.IGNORECASE):
        return True
    # "Year" prefix: Year 2024, Year2024
    if re.match(r'^Year\s*\d{2,4}$', s, re.IGNORECASE):
        return True
    return False

def normalize_year(value):
    """
    Normalize a year string to a consistent format.
    FY24 → FY2024, '24 → 2024, Year 2024 → FY2024, etc.
    """
    s = value.strip().strip("'")
    # Extract the numeric part
    m = re.search(r'(\d{2,4})', s)
    if not m:
        return value
    year_num = m.group(1)
    # Expand 2-digit years
    if len(year_num) == 2:
        year_num = '20' + year_num if int(year_num) < 50 else '19' + year_num
    return f'FY{year_num}'
```

#### JSON
```python
import json

def parse_json(filepath):
    """Parse JSON financial data (may be nested)."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    # Handle various JSON structures
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        # Look for common keys containing the data array
        for key in ['data', 'financials', 'statements', 'results', 'records']:
            if key in data and isinstance(data[key], list):
                return data[key]
        # Single record
        return [data]
```

#### HTML Tables
```python
from html.parser import HTMLParser

class TableParser(HTMLParser):
    """Extract tables from HTML content."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_cell = ''
        self.in_table = False
        self.in_row = False
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
            self.current_table = []
        elif tag == 'tr' and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ('td', 'th') and self.in_row:
            self.in_cell = True
            self.current_cell = ''

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.in_cell:
            self.in_cell = False
            self.current_row.append(self.current_cell.strip())
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            self.current_table.append(self.current_row)
        elif tag == 'table' and self.in_table:
            self.in_table = False
            self.tables.append(self.current_table)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data

def parse_html_tables(filepath):
    """Parse HTML file and extract tables."""
    with open(filepath, 'r') as f:
        content = f.read()
    parser = TableParser()
    parser.feed(content)
    return parser.tables
```

### Numeric Value Cleaning

Financial data often uses locale-specific formatting:
```python
import re

def clean_numeric(value_str):
    """Convert various numeric formats to float.
    
    Handles: $1,234.56, 1.234,56 (European), (123) for negatives,
    values with M/B/T suffixes, etc.
    """
    s = str(value_str).strip()
    # Remove currency symbols and whitespace
    s = re.sub(r'[$€£¥\s]', '', s)
    # Handle parentheses as negative: (123) -> -123
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    # Remove thousands separators (commas in English, dots in European)
    # Heuristic: if both . and , exist, the last one is the decimal separator
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            # European: 1.234,56
            s = s.replace('.', '').replace(',', '.')
        else:
            # English: 1,234.56
            s = s.replace(',', '')
    elif ',' in s:
        # Could be thousands separator or decimal
        # If pattern is like "1,234" treat as thousands; "1,5" as decimal
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    
    # Handle magnitude suffixes
    s = s.strip()
    multiplier = 1
    if s.upper().endswith('M'):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.upper().endswith('B'):
        multiplier = 1_000_000_000
        s = s[:-1]
    elif s.upper().endswith('T'):
        multiplier = 1_000_000_000_000
        s = s[:-1]
    elif s.upper().endswith('K'):
        multiplier = 1_000
        s = s[:-1]
    
    return float(s) * multiplier
```

### Field Name Normalization

Map varied field labels to canonical names:
```python
FIELD_ALIASES = {
    # Revenue
    'revenue': ['revenue', 'totalrevenue', 'netrevenue', 'sales',
                'totalsales', 'netsales', 'turnover', 'umsatz',
                'chiffredaffaires', 'ingresos'],
    # Gross Profit
    'gross_profit': ['grossprofit', 'grossincome', 'gp',
                     'profitbrut', 'bruttogewinn', 'beneficiobruto'],
    # Operating Income
    'operating_income': ['operatingincome', 'operatingprofit', 'oi',
                         'operatingearnings', 'ebit', 'betriebsergebnis'],
    # Net Income
    'net_income': ['netincome', 'netprofit', 'netearnings',
                   'profitnet', 'nettoergebnis', 'beneficioneto',
                   'bottomline'],
    # Total Equity
    'total_equity': ['totalequity', 'shareholdersequity',
                     'stockholdersequity', 'equity', 'netassets',
                     'totalshareholdersequity'],
    # Year
    'fiscal_year': ['year', 'fiscalyear', 'fy', 'period', 'exercise',
                    'geschäftsjahr', 'exercice'],
}

def normalize_field_name(name):
    """Map a field name to its canonical form."""
    name_lower = name.strip().lower().replace(' ', '')
    for canonical, aliases in FIELD_ALIASES.items():
        if name_lower in aliases:
            return canonical
    return name_lower
```

## Step 3: Financial Metric Computation

### Metric Formulas

All metrics are expressed as **percentage numbers** (e.g., 72.72 means 72.72%, not 0.7272) unless otherwise specified.

| Metric | Formula | Numerator | Denominator |
|--------|---------|-----------|-------------|
| **Gross Margin** | Gross Profit / Revenue × 100 | Gross Profit | Revenue |
| **Operating Margin** | Operating Income / Revenue × 100 | Operating Income | Revenue |
| **Net Margin** | Net Income / Revenue × 100 | Net Income | Revenue |
| **Return on Equity** | Net Income / Total Equity × 100 | Net Income | Total Shareholders' Equity |
| **Year-over-Year Growth** | (Current - Prior) / |Prior| × 100 | Current Year Value − Prior Year Value | Prior Year Value (absolute) |

```python
def compute_metric(metric_name, row_data, prior_row_data=None):
    """
    Compute a financial metric from parsed row data.
    
    Args:
        metric_name: One of 'gross_margin', 'operating_margin', 'net_margin',
                     'return_on_equity', 'year_over_year_growth'
        row_data: dict with canonical field names -> numeric values
        prior_row_data: dict for prior year (needed for YoY growth)
    
    Returns:
        float: metric value as percentage (e.g., 72.72 for 72.72%)
    """
    if metric_name == 'gross_margin':
        return (row_data['gross_profit'] / row_data['revenue']) * 100
    elif metric_name == 'operating_margin':
        return (row_data['operating_income'] / row_data['revenue']) * 100
    elif metric_name == 'net_margin':
        return (row_data['net_income'] / row_data['revenue']) * 100
    elif metric_name == 'return_on_equity':
        return (row_data['net_income'] / row_data['total_equity']) * 100
    elif metric_name == 'year_over_year_growth':
        if prior_row_data is None:
            return None  # Cannot compute for first year
        current = row_data['revenue']  # or whichever value is being tracked
        prior = prior_row_data['revenue']
        if prior == 0:
            return None
        return ((current - prior) / abs(prior)) * 100
    else:
        raise ValueError(f"Unknown metric: {metric_name}")
```

### Rounding

Always round to the specified number of decimal places (default: 2):
```python
def round_pct(value, decimals=2):
    """Round a percentage value to the specified decimal places."""
    return round(value, decimals)
```

## Step 4: Conditional Logic

Tasks may include conditional computation rules. Common patterns:

### Threshold-Based Metric Selection
```python
def apply_threshold_logic(metric_values, threshold, primary_metric, fallback_metric, 
                          row_data_list, condition='most_recent_exceeds'):
    """
    Apply conditional metric selection based on threshold.
    
    Args:
        metric_values: computed values for the primary metric
        threshold: numeric threshold value
        primary_metric: metric to use if condition is met
        fallback_metric: metric to use if condition is not met
        row_data_list: list of row data dicts for recomputation
        condition: 'most_recent_exceeds' | 'most_recent_below' | 'any_exceeds'
    """
    if condition == 'most_recent_exceeds':
        trigger_value = metric_values[-1]  # most recent year
        use_primary = trigger_value > threshold
    elif condition == 'most_recent_below':
        trigger_value = metric_values[-1]
        use_primary = trigger_value < threshold
    elif condition == 'any_exceeds':
        use_primary = any(v > threshold for v in metric_values)
    else:
        use_primary = True
    
    if use_primary:
        return primary_metric, metric_values
    else:
        # Recompute with fallback metric
        fallback_values = []
        for i, row in enumerate(row_data_list):
            prior = row_data_list[i-1] if i > 0 else None
            val = compute_metric(fallback_metric, row, prior)
            if val is not None:
                fallback_values.append(val)
        return fallback_metric, fallback_values
```

## Step 5: Output Generation

### CSV Output (most common)

**IMPORTANT**: Use `\n` line endings, NOT `\r\n`. The `csv.writer` module produces
`\r\n` by default (even with `newline=''`), which can cause silent test failures
when tests do byte-level or string comparison. For simple financial data (no
embedded commas or quotes), write manually:

```python
def write_csv_output(filepath, data, column_names):
    """
    Write results to CSV with \n line endings.
    
    Args:
        filepath: output file path (e.g., '/app/results.csv')
        data: list of rows (each row is a list of values)
        column_names: list of column header names
    """
    with open(filepath, 'w') as f:
        f.write(','.join(str(c) for c in column_names) + '\n')
        for row in data:
            f.write(','.join(str(v) for v in row) + '\n')
```

**When to use csv.writer instead**: If output values might contain commas, quotes,
or newlines (rare for financial metrics but possible for company names in some
schemas), use `csv.writer` but be aware of the `\r\n` terminator issue. In that
case, open with `newline=''` and accept `\r\n`, or write to a StringIO and
post-process.

### Output Column Naming
The output column names are specified by the task. Common patterns:
- `fiscal_year, gross_margin_pct` — for margin metrics
- `year, value` — generic
- `fiscal_year, metric_name` — dynamic based on metric

Always use the exact column names specified in the task instruction.

## Complete Workflow Template

```python
#!/usr/bin/env python3
"""
General financial analysis workflow.
Adapt this template for each specific task variant.
"""
import os
import re

# === CONFIGURATION (from task instruction) ===
DATA_DIR = '/app/financials/'        # Where to find data files
OUTPUT_FILE = '/app/results.csv'     # Where to write results
TARGET_COMPANY = 'NVIDIA'            # Company to look for
PRIMARY_METRIC = 'gross_margin'      # First metric to compute
FALLBACK_METRIC = 'net_margin'       # Fallback if condition not met
THRESHOLD = 70.0                     # Conditional threshold
CONDITION = 'most_recent_exceeds'    # Condition type
ROUND_DECIMALS = 2                   # Decimal places for rounding
OUTPUT_COLUMNS = ['fiscal_year', 'gross_margin_pct']  # Output schema
# Fields needed for the requested metrics (used for multi-file merge decisions)
REQUIRED_FIELDS = {'revenue', 'gross_profit', 'net_income'}

# === STEP 1: DISCOVER ALL RELEVANT FILES ===
def discover_all_financial_files(data_dir, target_company):
    """
    Find ALL files containing the target company's financial data.
    Does NOT stop at first match — multi-file scenarios need all of them.
    Detects JSON, HTML, and text-based files by extension and content.
    """
    candidates = []
    financial_exts = {'.json', '.html', '.htm', '.csv', '.tsv', '.txt', '.dat'}
    for fname in sorted(os.listdir(data_dir)):
        fpath = os.path.join(data_dir, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, 'r', errors='ignore') as f:
            content = f.read()
        # Check file extension for known financial data formats
        _, ext = os.path.splitext(fname)
        is_known_format = ext.lower() in financial_exts
        # Check content for target company and financial keywords
        has_company = target_company.lower() in content.lower()
        has_financial = bool(re.search(
            r'revenue|sales|turnover|equity|assets|liabilit',
            content, re.IGNORECASE
        ))
        if has_company and (has_financial or is_known_format):
            candidates.append((fname, fpath, content))
    return candidates

# === STEP 2: PARSE (handles comma-separated, whitespace/fixed-width, JSON, HTML) ===
def detect_delimiter(header_line, sample_data_lines):
    """Detect whether data uses tab, comma, or whitespace delimiters."""
    if '\t' in header_line:
        return '\t'
    if ',' in header_line:
        return ','
    if len(header_line.split()) >= 2:
        header_cols = len(header_line.split())
        for line in sample_data_lines[:3]:
            if len(line.split()) != header_cols:
                return ','
        return 'whitespace'
    return ','

def parse_fixedwidth_multiword(header_line, data_lines):
    """
    Parse fixed-width files where header has multi-word column names
    (e.g., 'Gross Profit') but data values are single tokens.
    Uses data token positions to determine column boundaries.
    """
    if not data_lines:
        return [], []
    
    # Find token boundaries (start and end positions) in first data line
    first_data = data_lines[0]
    token_boundaries = []  # List of (start, end) tuples
    i = 0
    while i < len(first_data):
        if first_data[i] != ' ':
            start = i
            while i < len(first_data) and first_data[i] != ' ':
                i += 1
            end = i
            token_boundaries.append((start, end))
        else:
            i += 1
    
    if not token_boundaries:
        return [], []
    
    # Extract header names by slicing at data token boundaries
    # Each column spans from the start of one token to the start of the next (or end of line)
    header_cols = []
    for idx, (start, end) in enumerate(token_boundaries):
        # Column extends from this token's start to the next token's start (or end of header)
        if idx + 1 < len(token_boundaries):
            col_end = token_boundaries[idx + 1][0]
        else:
            col_end = len(header_line)
        col_text = header_line[start:col_end].strip()
        header_cols.append(col_text)
    
    # Extract all data rows using same column boundaries
    all_rows = []
    for line in data_lines:
        row = []
        for idx, (start, end) in enumerate(token_boundaries):
            if idx + 1 < len(token_boundaries):
                col_end = token_boundaries[idx + 1][0]
            else:
                col_end = len(line)
            if start < len(line):
                val = line[start:min(col_end, len(line))].strip()
                row.append(val)
            else:
                row.append('')
        all_rows.append(row)
    
    return header_cols, all_rows

def is_year_field(value):
    """Check if a string looks like a fiscal year label (FY2024, 2024, FY24, etc.)."""
    s = value.strip().strip("'")
    if re.match(r'^\d{4}$', s):
        return True
    if re.match(r'^FY\s*\d{2,4}$', s, re.IGNORECASE):
        return True
    if re.match(r'^Year\s*\d{2,4}$', s, re.IGNORECASE):
        return True
    return False

def normalize_year(value):
    """Normalize year string: FY24→FY2024, '24→2024, etc."""
    s = value.strip().strip("'")
    m = re.search(r'(\d{2,4})', s)
    if not m:
        return value
    year_num = m.group(1)
    if len(year_num) == 2:
        year_num = '20' + year_num if int(year_num) < 50 else '19' + year_num
    return f'FY{year_num}'

def extract_financial_data(content, filename=None):
    """
    Extract structured financial data from file content.
    Handles: JSON, HTML, comma-separated, whitespace/fixed-width, banner formats.
    Returns list of dicts with keys: fiscal_year, revenue, gross_profit, etc.
    
    Args:
        content: file content as string
        filename: optional filename for format detection (e.g., 'data.json')
    """
    # Phase 0: Detect format and route to appropriate parser
    content_stripped = content.strip()
    
    # Check for JSON format
    if filename and filename.lower().endswith('.json'):
        return _parse_json_content(content_stripped)
    if content_stripped.startswith('{') or content_stripped.startswith('['):
        try:
            return _parse_json_content(content_stripped)
        except:
            pass  # Not valid JSON, fall through to text parsing
    
    # Check for HTML format
    if filename and filename.lower().endswith(('.html', '.htm')):
        return _parse_html_content(content_stripped)
    if '<html' in content_stripped.lower() or '<table' in content_stripped.lower():
        return _parse_html_content(content_stripped)
    
    # Default: text-based parsing (CSV, TSV, fixed-width)
    return _parse_text_content(content_stripped)

def _parse_json_content(content):
    """Parse JSON financial data and return list of record dicts."""
    import json
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    
    # Handle various JSON structures
    records_raw = None
    if isinstance(data, list):
        records_raw = data
    elif isinstance(data, dict):
        # Look for common keys containing the data array
        for key in ['data', 'financials', 'statements', 'results', 'records', 'items']:
            if key in data and isinstance(data[key], list):
                records_raw = data[key]
                break
        if records_raw is None:
            # Single record
            records_raw = [data]
    
    if not records_raw:
        return []
    
    # Normalize field names and extract records
    records = []
    for item in records_raw:
        if not isinstance(item, dict):
            continue
        record = {}
        for key, value in item.items():
            norm_key = normalize_field(key)
            if norm_key == 'fiscal_year':
                record['fiscal_year'] = normalize_year(str(value))
            else:
                try:
                    record[norm_key] = float(value)
                except (ValueError, TypeError):
                    record[norm_key] = value
        if 'fiscal_year' in record:
            records.append(record)
    
    return records

def _parse_html_content(content):
    """Parse HTML tables and return list of record dicts."""
    from html.parser import HTMLParser
    
    class FinancialTableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables = []
            self.current_table = []
            self.current_row = []
            self.current_cell = ''
            self.in_table = False
            self.in_row = False
            self.in_cell = False
        
        def handle_starttag(self, tag, attrs):
            if tag == 'table':
                self.in_table = True
                self.current_table = []
            elif tag == 'tr' and self.in_table:
                self.in_row = True
                self.current_row = []
            elif tag in ('td', 'th') and self.in_row:
                self.in_cell = True
                self.current_cell = ''
        
        def handle_endtag(self, tag):
            if tag in ('td', 'th') and self.in_cell:
                self.in_cell = False
                self.current_row.append(self.current_cell.strip())
            elif tag == 'tr' and self.in_row:
                self.in_row = False
                if self.current_row:
                    self.current_table.append(self.current_row)
            elif tag == 'table' and self.in_table:
                self.in_table = False
                if self.current_table:
                    self.tables.append(self.current_table)
        
        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data
    
    parser = FinancialTableParser()
    parser.feed(content)
    
    if not parser.tables:
        return []
    
    # Find the table with financial data (contains financial keywords)
    financial_keywords = {
        'revenue', 'sales', 'income', 'profit', 'equity', 'assets',
        'year', 'period', 'fy', 'operating', 'gross', 'net',
    }
    
    best_table = None
    best_score = 0
    
    for table in parser.tables:
        if not table:
            continue
        # Check header row for financial keywords
        header_row = table[0]
        score = sum(1 for cell in header_row 
                   if any(kw in cell.lower().replace(' ', '') for kw in financial_keywords))
        if score > best_score:
            best_score = score
            best_table = table
    
    if not best_table or len(best_table) < 2:
        return []
    
    # Parse the best table
    header = best_table[0]
    records = []
    norm_header = [normalize_field(h) for h in header]
    
    for row in best_table[1:]:
        if len(row) != len(header):
            continue
        record = {}
        for i, h in enumerate(norm_header):
            if h == 'fiscal_year':
                record['fiscal_year'] = normalize_year(row[i])
            else:
                try:
                    record[h] = clean_numeric(row[i])
                except (ValueError, TypeError):
                    record[h] = row[i]
        if 'fiscal_year' in record:
            records.append(record)
    
    return records

def _parse_text_content(content):
    """Parse text-based financial data (CSV, TSV, fixed-width)."""
    lines = content.strip().split('\n')
    
    # Phase 1: Filter out non-data lines
    data_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r'^[=\-\*\#\~]+$', stripped):
            continue
        # Skip bullet-point lines (starting with - or *)
        if re.match(r'^[\-\*]\s', stripped):
            continue
        if ':' in stripped and ',' not in stripped:
            first_word = stripped.split()[0].rstrip(':')
            if not re.match(r'^\d|FY', first_word, re.IGNORECASE):
                continue
        if stripped.upper().startswith(('NOTE', 'DATA COVERAGE')):
            continue
        data_lines.append(stripped)
    
    if not data_lines:
        return []
    
    # Phase 2: Find header line (must contain at least one financial keyword)
    financial_keywords = {
        'revenue', 'sales', 'turnover', 'income', 'profit', 'loss',
        'equity', 'assets', 'liabilities', 'expense', 'earnings',
        'year', 'period', 'fy', 'operating', 'gross', 'net',
        'operatingincome', 'netincome', 'grossprofit', 'total',
    }
    header = None
    header_idx = None
    for idx, line in enumerate(data_lines):
        # Detect delimiter early: tab > comma > whitespace
        if '\t' in line:
            parts = [p.strip() for p in line.split('\t')]
        elif ',' in line:
            parts = [p.strip() for p in line.split(',')]
        else:
            parts = line.split()
        if len(parts) >= 2:
            alpha_count = sum(1 for p in parts if re.match(r'^[A-Za-z_ /]+$', p))
            if alpha_count >= len(parts) * 0.6:
                lower_parts = [p.lower().replace(' ', '') for p in parts]
                has_financial = any(
                    any(kw in lp for kw in financial_keywords)
                    for lp in lower_parts
                )
                if has_financial:
                    header = parts
                    header_idx = idx
                    break
    
    if header is None:
        return []
    
    # Phase 3: Detect delimiter
    delimiter = detect_delimiter(
        ','.join(header) if ',' in data_lines[header_idx] else ' '.join(header),
        data_lines[header_idx + 1:]
    )
    
    # Phase 3.5: Check for multi-word header mismatch
    # If header has more tokens than data rows, use position-based parsing
    first_data_line = data_lines[header_idx + 1] if header_idx + 1 < len(data_lines) else None
    if first_data_line:
        # Use the same delimiter for both header and data token counting
        if delimiter == '\t':
            header_token_count = len([p.strip() for p in data_lines[header_idx].split('\t')])
            data_token_count = len([p.strip() for p in first_data_line.split('\t')])
        elif delimiter == ',':
            header_token_count = len([p.strip() for p in data_lines[header_idx].split(',')])
            data_token_count = len([p.strip() for p in first_data_line.split(',')])
        else:
            header_token_count = len(data_lines[header_idx].split())
            data_token_count = len(first_data_line.split())
        if header_token_count > data_token_count:
            # Multi-word headers detected: use position-based parsing
            header, data_rows = parse_fixedwidth_multiword(
                data_lines[header_idx],
                data_lines[header_idx + 1:]
            )
            # Skip normal delimiter-based parsing, go directly to record mapping
            records = []
            norm_header = [normalize_field(h) for h in header]
            for row in data_rows:
                record = {}
                for i, h in enumerate(norm_header):
                    if i < len(row):
                        if h == 'fiscal_year':
                            # Use header to identify year field, not the value
                            record['fiscal_year'] = normalize_year(row[i])
                        else:
                            try:
                                record[h] = clean_numeric(row[i])
                            except (ValueError, TypeError):
                                record[h] = row[i]
                if 'fiscal_year' in record:
                    records.append(record)
            
            return records
    
    # Phase 4: Parse data rows
    data_rows = []
    for line in data_lines[header_idx + 1:]:
        if delimiter == '\t':
            parts = [p.strip() for p in line.split('\t')]
        elif delimiter == 'whitespace':
            parts = line.split()
        else:
            parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2:
            data_rows.append(parts)
    
    # Phase 5: Map to structured records
    records = []
    norm_header = [normalize_field(h) for h in header]
    for row in data_rows:
        record = {}
        for i, h in enumerate(norm_header):
            if i < len(row):
                if h == 'fiscal_year':
                    # Use header to identify year field, not the value
                    record['fiscal_year'] = normalize_year(row[i])
                else:
                    try:
                        record[h] = clean_numeric(row[i])
                    except (ValueError, TypeError):
                        record[h] = row[i]
        if 'fiscal_year' in record:
            records.append(record)
    
    return records

def normalize_field(name):
    """Normalize a field name to canonical form."""
    name_lower = name.strip().lower().replace(' ', '')
    aliases = {
        'revenue': ['revenue', 'totalrevenue', 'netrevenue', 'sales',
                    'totalsales', 'netsales', 'turnover'],
        'gross_profit': ['grossprofit', 'grossincome', 'gp'],
        'operating_income': ['operatingincome', 'operatingprofit', 'oi', 'ebit'],
        'net_income': ['netincome', 'netprofit', 'netearnings'],
        'total_equity': ['totalequity', 'shareholdersequity',
                         'stockholdersequity', 'equity', 'netassets'],
        'fiscal_year': ['year', 'fiscalyear', 'fy', 'period'],
    }
    for canonical, alias_list in aliases.items():
        if name_lower in alias_list:
            return canonical
    return name_lower

def clean_numeric(s):
    """Convert string to float, handling various formats."""
    s = str(s).strip()
    s = re.sub(r'[$\u20ac\u00a3\u00a5\s]', '', s)
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    for suffix, mult in [('T', 1e12), ('B', 1e9), ('M', 1e6), ('K', 1e3)]:
        if s.upper().endswith(suffix):
            return float(s[:-1]) * mult
    return float(s)

# === STEP 2b: MULTI-FILE MERGE (when needed) ===
def merge_multi_file(candidates, required_fields):
    """
    Parse all candidate files and merge by fiscal year if needed.
    Returns list of merged record dicts sorted by year.
    """
    file_records = {}  # fname -> {fiscal_year: record_dict}
    file_field_coverage = {}  # fname -> set of fields
    
    for fname, fpath, content in candidates:
        records = extract_financial_data(content, filename=fname)
        if not records:
            continue
        by_year = {}
        fields_found = set()
        for rec in records:
            fy = rec.get('fiscal_year', '')
            by_year[fy] = rec
            fields_found.update(k for k in rec.keys() if k != 'fiscal_year')
        file_records[fname] = by_year
        file_field_coverage[fname] = fields_found
    
    # Check if single file covers everything
    for fname, fields in file_field_coverage.items():
        if required_fields.issubset(fields):
            return list(file_records[fname].values())
    
    # Multi-file merge
    all_years = set()
    for by_year in file_records.values():
        all_years.update(by_year.keys())
    
    merged = []
    for fy in sorted(all_years):
        rec = {'fiscal_year': fy}
        for fname, by_year in file_records.items():
            if fy in by_year:
                rec.update(by_year[fy])
        merged.append(rec)
    return merged

# === STEP 3: COMPUTE ===
def compute_all_metrics(records, metric_name):
    """Compute metric for all records, sorted by fiscal year."""
    # Sort records by fiscal year to ensure chronological order
    # Extract numeric year for sorting: FY2024 -> 2024, 2024 -> 2024
    def extract_year_num(fy):
        m = re.search(r'(\d{4})', str(fy))
        return int(m.group(1)) if m else 0
    
    sorted_records = sorted(records, key=lambda r: extract_year_num(r.get('fiscal_year', '')))
    
    values = []
    for i, rec in enumerate(sorted_records):
        if metric_name == 'gross_margin':
            val = (rec['gross_profit'] / rec['revenue']) * 100
        elif metric_name == 'operating_margin':
            val = (rec['operating_income'] / rec['revenue']) * 100
        elif metric_name == 'net_margin':
            val = (rec['net_income'] / rec['revenue']) * 100
        elif metric_name == 'return_on_equity':
            val = (rec['net_income'] / rec['total_equity']) * 100
        elif metric_name == 'year_over_year_growth':
            if i == 0:
                continue
            current = rec['revenue']
            prior = sorted_records[i-1]['revenue']
            val = ((current - prior) / abs(prior)) * 100
        else:
            raise ValueError(f"Unknown metric: {metric_name}")
        values.append((rec.get('fiscal_year', f'Year{i}'), round(val, ROUND_DECIMALS)))
    return values

# === STEP 4: CONDITIONAL LOGIC ===
def check_condition(values, threshold, condition_type):
    """Check if conditional threshold is met."""
    if condition_type == 'most_recent_exceeds':
        return values[-1][1] > threshold
    elif condition_type == 'most_recent_below':
        return values[-1][1] < threshold
    return True

# === STEP 5: OUTPUT (\n line endings, not \r\n) ===
def write_results(filepath, values, columns):
    """Write results to CSV with \n line endings."""
    with open(filepath, 'w') as f:
        f.write(','.join(str(c) for c in columns) + '\n')
        for row in values:
            f.write(','.join(str(v) for v in row) + '\n')

# === MAIN EXECUTION ===
def main():
    # Discover ALL relevant files (not just the first)
    candidates = discover_all_financial_files(DATA_DIR, TARGET_COMPANY)
    if not candidates:
        raise RuntimeError(f"No files found for {TARGET_COMPANY} in {DATA_DIR}")
    
    # Parse and optionally merge multi-file data
    records = merge_multi_file(candidates, REQUIRED_FIELDS)
    if not records:
        raise RuntimeError("No financial records extracted")
    
    # Compute primary metric
    values = compute_all_metrics(records, PRIMARY_METRIC)
    
    # Apply conditional logic
    if not check_condition(values, THRESHOLD, CONDITION):
        values = compute_all_metrics(records, FALLBACK_METRIC)
        OUTPUT_COLUMNS[1] = 'net_margin_pct'
    
    # Write output
    write_results(OUTPUT_FILE, values, OUTPUT_COLUMNS)
    print(f"Results written to {OUTPUT_FILE}")
    for year, val in values:
        print(f"  {year}: {val}%")

if __name__ == '__main__':
    main()
```

## Key Principles

1. **Always verify the target company**: Don't assume the first file is correct. Check company name, ticker, and data relevance.
2. **Discover ALL files, not just the first**: Multi-file scenarios (income statement + balance sheet) require finding and merging all relevant files. Never stop discovery at the first match.
3. **Detect format by extension AND content**: Check file extensions (.json, .html, .csv, .tsv, .dat) to route to the correct parser. Fall back to content-based detection if extension is ambiguous.
4. **Handle format diversity**: Financial data comes in many formats — CSV, TSV, fixed-width (whitespace-separated), banner with commas, JSON, HTML. Each format has its own parser, and all are wired into the main `extract_financial_data` function.
5. **Handle multi-word headers in fixed-width files**: When header has more whitespace-tokens than data rows, use data token POSITIONS to determine column boundaries, then slice the header at those positions.
6. **Normalize field names**: Different files use different labels for the same concept. Map to canonical names before computation.
7. **Clean numeric values**: Handle currency symbols, thousands separators, magnitude suffixes (M/B/T/K), and locale-specific decimal separators.
8. **Express percentages correctly**: Output as percentage numbers (72.72) not decimals (0.7272) unless explicitly told otherwise.
9. **Sort by year before computing metrics**: Ensure records are in chronological order before determining "most recent year" for conditional logic.
10. **Use `\n` line endings in CSV output**: Avoid `csv.writer`'s default `\r\n` which can cause silent test failures. Write manually for simple data.
11. **Respect the output contract**: Use exact column names and file paths specified in the task.
12. **Handle edge cases**: Missing data, zero denominators, first-year YoY growth (no prior year), and negative values.

## Common Pitfalls

- **Decoy files**: Files may mention the target company but contain wrong data (quarterly vs annual, different company, product-level data)
- **Header detection**: In banner-format files, the header row may be preceded by metadata lines. Always require at least one financial keyword in the header.
- **Tab-separated files**: Don't assume all delimited files use commas. Check for tabs FIRST. TSV files can have multi-word headers like "Gross Profit" which would break whitespace splitting.
- **Fixed-width with multi-word headers**: When header has more whitespace-tokens than data rows (e.g., "Gross Profit" splits into 2 tokens but data has 1 value), use data token positions to determine column boundaries, then slice the header.
- **JSON/HTML files not detected**: If a file has .json or .html extension, route to the appropriate parser. Don't try to parse JSON as text.
- **Year extraction**: Fiscal years may be labeled as "FY2024", "2024", "Year 2024", "FY24", "'24", "FY 2024" — use permissive regex
- **Year sorting**: Data may not be in chronological order. Always sort by fiscal year before determining "most recent year" for conditional logic.
- **Magnitude units**: Values may be in millions (M), billions (B), or absolute — check the file's stated units
- **Conditional column names**: The output column name may change based on which metric is selected (e.g., `gross_margin_pct` vs `net_margin_pct`)
- **Multi-file join for ROE**: Return on Equity needs both Net Income (income statement) and Total Equity (balance sheet). If these are in separate files, you must merge by fiscal year
- **CSV `\r\n` vs `\n`**: `csv.writer` produces `\r\n` by default. Tests doing string comparison will fail. Use manual write with `\n` for simple financial data
- **Stopping discovery too early**: If a task needs ROE, there may be separate income statement and balance sheet files. Finding only the income statement and stopping means you'll fail on missing equity data
