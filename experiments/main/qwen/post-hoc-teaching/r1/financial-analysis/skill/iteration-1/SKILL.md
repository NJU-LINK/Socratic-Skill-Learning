---
name: financial-analysis
description: >
  Discover, parse, and compute financial metrics from heterogeneous data sources.
  Handles file discovery among decoys, multiple data formats (CSV, JSON, fixed-width,
  HTML), field-name normalization across locales/schemas, multi-statement joins,
  conditional metric selection, and structured output.
---

# Financial Analysis Skill

## Overview

This skill solves tasks that require:
1. Locating the correct financial data file(s) among potentially many files (including decoys)
2. Parsing financial data from varied formats and schemas
3. Computing a requested financial metric per fiscal year
4. Applying conditional logic (e.g., threshold-based metric switching)
5. Writing results in a specified output format

## General Methodology

### Phase 1: File Discovery

**Goal**: Identify which file(s) contain the target company's relevant financial data.

**Procedure**:
1. List all files in the data directory (e.g., `/app/financials/`)
2. For each file, read its contents and check for:
   - **Company match**: The target company name (e.g., "NVIDIA Corporation") or ticker
   - **Required fields**: Presence of the financial fields needed for the metric (e.g., Revenue, Gross Profit)
   - **Data type**: Annual vs quarterly (prefer annual unless quarterly is specified)
3. Reject decoy files that:
   - Contain data for a different company
   - Are quarterly when annual is needed
   - Contain only metadata/cache/logs without actual financial data tables
   - Have irrelevant product-level data instead of company-level financials

**Key heuristics**:
- A valid financial data file will have structured rows with numeric values
- Look for column headers that map to financial concepts (Revenue, Gross Profit, Net Income, etc.)
- Files named with generic terms like "cache", "backup", "results" may be decoys
- The correct file often has a header/metadata section identifying the company

### Phase 2: Data Parsing

**Goal**: Extract structured (year → financial values) records from the identified file(s).

**Format-specific strategies**:

#### CSV / Comma-Separated
- Find the header row (contains field names separated by commas)
- Parse subsequent rows as data
- Handle: quoted fields, varying delimiters (comma, semicolon, tab, pipe)

#### Fixed-Width / Aligned Text
- Detect column boundaries from header alignment
- Parse each line by character positions
- Handle: variable spacing, separator lines (===, ---)

#### Nested JSON
- Navigate the JSON structure to find the array of records
- Handle: nested objects, arrays within objects, metadata wrappers
- Common patterns: `{"company": "...", "data": {"annual": [...]}}`

#### HTML Tables
- Parse `<table>` elements, handling `<th>` for headers
- Handle: merged headers (`colspan`, `rowspan`), nested tables
- Extract text content from `<td>` cells

**Universal parsing approach**:
1. Scan for lines that look like headers (contain known financial field names)
2. Once header is found, parse subsequent lines as data rows
3. Stop parsing when hitting non-data lines (notes, separators, blank lines)
4. Normalize field names to a canonical mapping (see Field Mapping below)

### Phase 3: Field Mapping

**Goal**: Map whatever field names appear in the data to canonical financial concepts.

**Canonical field mapping table**:

| Canonical Name      | Common Variants |
|---------------------|-----------------|
| `fiscal_year`       | Year, FY, Fiscal Year, Exercise, Jahr, Année, 年度, Exercice |
| `revenue`           | Revenue, Sales, Total Revenue, Net Sales, Net Revenue, Umsätze, Chiffre d'affaires, 売上高 |
| `gross_profit`      | Gross Profit, GP, Gross Income, Profit Bruto, Marge Brute |
| `net_income`        | Net Income, Net Profit, Net Earnings, Profit Net, Ergebnis, Résultat Net |
| `operating_income`  | Operating Income, Operating Profit, EBIT, Operating Earnings |
| `total_equity`      | Total Equity, Shareholders' Equity, Stockholders' Equity, Total Stockholders Equity, Book Value |
| `cost_of_revenue`   | Cost of Revenue, COGS, Cost of Goods Sold, Cost of Sales |

**Matching strategy** (longest-match-wins):
- All variant strings are tested against the lowercased, normalized field name
- Every match is collected as a (length, canonical_name) pair
- The **longest matching variant wins**, ensuring specificity over iteration order
- This prevents collisions: "cost of revenue" (15 chars) beats "revenue" (7 chars)
- Example: a field "Cost of Revenue" matches both "revenue" (7) and "cost of revenue" (15) → correctly maps to `cost_of_revenue`
- Example: "Net Sales Returns" matches "net sales" (9) but also potentially other variants → longest wins

**Numeric normalization**:
- Remove currency symbols ($, €, £, ¥, ₹)
- Handle scale indicators: "M" = millions, "B" = billions, "K" = thousands
- Handle parenthetical negatives: `(1,234)` → `-1234`; also handle leading minus
- **European vs English format detection**: When both `.` and `,` appear, the **last** one is the decimal separator. If only `,` appears: 3 digits after last comma → thousands separator; 1-2 digits → European decimal. If only `.` appears multiple times → European thousands separators.
- Examples: `"1,234.56"` → 1234.56 | `"1.234,56"` → 1234.56 | `"130,50"` → 130.50 | `"1.234.567"` → 1234567

### Phase 4: Metric Computation

**Metric formulas** (all expressed as percentages unless noted):

| Metric | Formula | Notes |
|--------|---------|-------|
| `gross_margin` | `(gross_profit / revenue) × 100` | Profitability of core operations |
| `operating_margin` | `(operating_income / revenue) × 100` | Includes operating expenses |
| `net_margin` | `(net_income / revenue) × 100` | Bottom-line profitability |
| `return_on_equity` | `(net_income / total_equity) × 100` | Return to shareholders |
| `year_over_year_growth` | `((current_revenue - prior_revenue) / prior_revenue) × 100` | Revenue growth rate; first year has no prior |

**Rounding**: Round to 2 decimal places (e.g., 72.72 means 72.72%, not 0.7272).

### Phase 5: Conditional Logic

Many tasks include conditional metric selection. Common patterns:

- **Threshold-based**: "If metric X for the most recent year exceeds Y%, compute X for all years; otherwise compute Z instead"
- **Comparison-based**: "If metric A > metric B, use A; else use B"
- **Trend-based**: "If metric is increasing year-over-year, compute growth rate"

**Procedure**:
1. Compute the primary metric for all years
2. Evaluate the condition using the most recent year's value
3. If condition is met, output the primary metric
4. If condition is NOT met, compute and output the fallback metric instead
5. The output column names should reflect which metric was actually computed

### Phase 6: Output Generation

**Goal**: Write results to the specified output file in the required format.

**Standard output patterns**:
- CSV with header row: `fiscal_year,<metric_name>_pct`
- The metric column name should match the computed metric (e.g., `gross_margin_pct`, `net_margin_pct`)
- Values are percentage numbers (e.g., 72.72), not decimals (0.7272)
- Round to 2 decimal places
- One row per fiscal year, typically in chronological order

**Output column naming convention**:
- `fiscal_year` or `year` for the year column
- `<metric_name>_pct` for the value column (e.g., `gross_margin_pct`, `net_margin_pct`, `operating_margin_pct`, `return_on_equity_pct`, `yoy_growth_pct`)

### Phase 7: Multi-File Joining (when needed)

When financial data spans multiple files (e.g., income statement + balance sheet):

1. Parse each file independently
2. Identify the join key (usually fiscal year)
3. Normalize year labels across files (e.g., "FY2024", "2024", "Year ending 2024" → same key)
4. Join on fiscal year to combine fields from different statements
5. Compute the metric using the combined data

## Implementation Template

```python
import csv
import json
import re
import os

# === CONFIGURATION (adapt per task) ===
DATA_DIR = "/app/financials"  # or wherever data lives
OUTPUT_FILE = "/app/results.csv"
TARGET_COMPANY = "NVIDIA"  # or as specified
REQUIRED_FIELDS = ["revenue", "gross_profit"]  # depends on metric

# === PHASE 1: File Discovery ===
def discover_file(data_dir, company_name, required_fields):
    """Find the file containing target company's financial data."""
    for fname in os.listdir(data_dir):
        fpath = os.path.join(data_dir, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, 'r', errors='ignore') as f:
            content = f.read()
        # Check company match
        if company_name.upper() not in content.upper():
            continue
        # Check for required financial fields (case-insensitive)
        content_lower = content.lower()
        has_fields = all(
            any(variant in content_lower for variant in FIELD_VARIANTS.get(field, [field]))
            for field in required_fields
        )
        if has_fields:
            # Verify it has actual numeric data rows
            if re.search(r'\d{3,}', content):
                return fpath
    return None

# === PHASE 2: Parsing ===
def parse_financial_data(filepath):
    """Parse financial data from various formats into list of dicts."""
    with open(filepath, 'r', errors='ignore') as f:
        content = f.read()
    
    # Try CSV-like parsing first (most common)
    records = try_csv_parse(content)
    if records:
        return records
    
    # Try JSON parsing
    records = try_json_parse(content)
    if records:
        return records
    
    # Try fixed-width parsing
    records = try_fixed_width_parse(content)
    if records:
        return records
    
    raise ValueError(f"Could not parse financial data from {filepath}")

def try_csv_parse(content):
    """Attempt to parse CSV-like data from content."""
    lines = content.strip().split('\n')
    header = None
    records = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # Skip separator lines
        if all(c in '=-_|+ ' for c in stripped):
            continue
        
        # Detect header: contains known financial field names
        if is_header_line(stripped):
            header = split_header(stripped)
            continue
        
        # Parse data rows after header found
        if header and looks_like_data_row(stripped):
            parts = split_data_row(stripped)
            if len(parts) >= len(header):
                record = {}
                for i, h in enumerate(header):
                    if i < len(parts):
                        record[h] = parts[i]
                records.append(record)
    
    return records if records else None

# === Helper functions for parsing ===
def is_header_line(line):
    """Check if a line looks like a CSV header with financial fields."""
    line_lower = line.lower()
    financial_terms = ['revenue', 'profit', 'income', 'equity', 'sales', 'margin',
                       'year', 'fiscal', 'ebit', 'cogs']
    matches = sum(1 for t in financial_terms if t in line_lower)
    # Must have at least 2 financial terms and a delimiter
    return matches >= 2 and (',' in line or '\t' in line or '|' in line)

def split_header(line):
    """Split a header line into field names."""
    for delim in [',', '\t', '|', ';']:
        if delim in line:
            return [h.strip() for h in line.split(delim)]
    return line.split()

def looks_like_data_row(line):
    """Check if a line looks like a data row (starts with year/FY and has numbers)."""
    # Should start with a year-like token
    first_token = line.split(',')[0].split('\t')[0].strip()
    is_year = bool(re.match(r'(FY)?\d{4}', first_token, re.IGNORECASE))
    has_numbers = bool(re.search(r'\d{3,}', line))
    return is_year and has_numbers

def split_data_row(line):
    """Split a data row into values."""
    for delim in [',', '\t', '|', ';']:
        if delim in line:
            return [v.strip() for v in line.split(delim)]
    return line.split()

# === PHASE 3: Field Mapping ===
FIELD_VARIANTS = {
    "fiscal_year": ["year", "fy", "fiscal year", "fiscal_year", "exercise", "jahr", "année"],
    "revenue": ["revenue", "sales", "total revenue", "net sales", "net revenue", "total sales"],
    "gross_profit": ["gross profit", "gross income", "gp"],
    "net_income": ["net income", "net profit", "net earnings", "profit net"],
    "operating_income": ["operating income", "operating profit", "ebit"],
    "total_equity": ["total equity", "shareholders equity", "stockholders equity", "total stockholders equity"],
    "cost_of_revenue": ["cost of revenue", "cogs", "cost of goods sold", "cost of sales"],
}

def normalize_field_name(name):
    """Map a field name to its canonical form using longest-match-wins.
    
    This prevents collisions where a short variant (e.g., 'revenue') matches
    before a more specific one (e.g., 'cost of revenue'). The longest matching
    variant is almost always the most specific and correct mapping.
    """
    # Normalize: lowercase, replace separators with spaces, split CamelCase
    # Step 1: Split CamelCase on original name (needs original casing)
    # e.g., 'GrossProfit' → 'Gross Profit', 'NetIncome' → 'Net Income'
    camel_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # Step 2: lowercase and replace all separators (underscore, hyphen) with spaces
    name_lower = camel_split.lower().strip()
    name_lower = name_lower.replace('_', ' ').replace('-', ' ')
    # Step 3: collapse multiple spaces
    name_lower = re.sub(r'\s+', ' ', name_lower).strip()
    
    # Collect ALL matching (variant_length, canonical, variant) triples
    candidates = []
    for canonical, variants in FIELD_VARIANTS.items():
        for variant in variants:
            if variant in name_lower:
                candidates.append((len(variant), canonical, variant))
    
    if not candidates:
        return name_lower
    
    # Longest match wins — "cost of revenue" (15) beats "revenue" (7)
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]

def normalize_numeric(value_str):
    """Convert a string to a float, handling various formats.
    
    Handles: currency symbols, scale indicators (M/B/K), thousands separators,
    parenthetical negatives, and European number formats (e.g., '1.234,56').
    """
    s = str(value_str).strip()
    if not s:
        return None
    
    # Handle parentheses as negatives: (1,234) → -1234
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1].strip()
    
    # Handle leading minus sign
    if s.startswith('-'):
        negative = not negative  # flip if already negative from parens
        s = s[1:].strip()
    
    # Remove scale indicators and record scale factor
    scale = 1.0
    s_upper = s.upper().rstrip()
    if s_upper.endswith('B'):
        scale = 1e9
        s = s_upper[:-1].strip()
    elif s_upper.endswith('M'):
        scale = 1e6
        s = s_upper[:-1].strip()
    elif s_upper.endswith('K'):
        scale = 1e3
        s = s_upper[:-1].strip()
    else:
        s = s_upper
    
    # Remove currency symbols
    s = re.sub(r'[$\u20ac\u00a3\u00a5\u20b9]', '', s).strip()  # $ euro pound yen rupee
    
    # Determine decimal separator by analyzing . and , positions
    # Rule: the LAST occurrence of . or , is the decimal separator
    has_dot = '.' in s
    has_comma = ',' in s
    
    if has_dot and has_comma:
        last_dot = s.rfind('.')
        last_comma = s.rfind(',')
        if last_comma > last_dot:
            # European format: 1.234,56 → comma is decimal
            s = s.replace('.', '')   # remove thousands separators (dots)
            s = s.replace(',', '.')  # convert decimal comma to dot
        else:
            # English format: 1,234.56 → dot is decimal
            s = s.replace(',', '')   # remove thousands separators (commas)
    elif has_comma and not has_dot:
        # Could be thousands separator (1,234) or decimal (1,56)
        # Heuristic: if exactly 3 digits after the LAST comma, it's thousands
        # Otherwise, if 1-2 digits after last comma, it's decimal
        parts_after_last_comma = s.split(',')[-1]
        if len(parts_after_last_comma) == 3 and s.count(',') >= 1:
            # Likely thousands separator: 1,234 or 1,234,567
            s = s.replace(',', '')
        else:
            # Likely European decimal: 130,50
            s = s.replace(',', '.')
    elif has_dot and not has_comma:
        # Standard format or European thousands: could be 1.234 (European thousands)
        # or 1234.56 (standard decimal). Heuristic: if multiple dots, they're thousands
        if s.count('.') > 1:
            # Multiple dots = European thousands separators: 1.234.567
            s = s.replace('.', '')
        # else: single dot is standard decimal, leave as-is
    
    s = s.strip()
    try:
        val = float(s) * scale
        return -val if negative else val
    except ValueError:
        return None

# === PHASE 4: Metric Computation ===
def compute_metric(records, metric_name):
    """Compute a financial metric for each year.
    
    For single-year metrics (margins, ROE), each row is computed independently.
    For year_over_year_growth, records must be sorted and a lag is applied.
    """
    # Normalize all records first
    normalized = []
    for rec in records:
        norm = {}
        for k, v in rec.items():
            canon = normalize_field_name(k)
            norm[canon] = v
        normalized.append(norm)
    
    # For YoY growth, we need sorted records with a lag
    if metric_name == 'year_over_year_growth':
        return _compute_yoy_growth(normalized)
    
    # For all other metrics, compute per-row
    results = []
    for rec in normalized:
        year = rec.get('fiscal_year', '')
        value = _compute_single_metric(rec, metric_name)
        if value is not None:
            results.append((year, value))
    
    return results

def _compute_single_metric(rec, metric_name):
    """Compute a single-year metric from a normalized record. Returns None if not computable."""
    if metric_name == 'gross_margin':
        rev = normalize_numeric(rec.get('revenue', 0))
        gp = normalize_numeric(rec.get('gross_profit', 0))
        if rev and rev != 0:
            return (gp / rev) * 100
    elif metric_name == 'operating_margin':
        rev = normalize_numeric(rec.get('revenue', 0))
        oi = normalize_numeric(rec.get('operating_income', 0))
        if rev and rev != 0:
            return (oi / rev) * 100
    elif metric_name == 'net_margin':
        rev = normalize_numeric(rec.get('revenue', 0))
        ni = normalize_numeric(rec.get('net_income', 0))
        if rev and rev != 0:
            return (ni / rev) * 100
    elif metric_name == 'return_on_equity':
        ni = normalize_numeric(rec.get('net_income', 0))
        eq = normalize_numeric(rec.get('total_equity', 0))
        if eq and eq != 0:
            return (ni / eq) * 100
    else:
        raise ValueError(f"Unknown metric: {metric_name}")
    return None

def _compute_yoy_growth(normalized_records):
    """Compute year-over-year revenue growth. First year is skipped (no prior)."""
    # Sort by fiscal year to ensure chronological order
    sorted_recs = sorted(normalized_records, key=lambda r: r.get('fiscal_year', ''))
    
    results = []
    for i, rec in enumerate(sorted_recs):
        if i == 0:
            continue  # first year has no prior year to compare against
        
        current_rev = normalize_numeric(rec.get('revenue', 0))
        prior_rev = normalize_numeric(sorted_recs[i - 1].get('revenue', 0))
        
        if current_rev is not None and prior_rev and prior_rev != 0:
            growth = ((current_rev - prior_rev) / prior_rev) * 100
            results.append((rec.get('fiscal_year', ''), growth))
    
    return results

# === PHASE 6: Output ===
def write_results(filepath, results, metric_name):
    """Write results to CSV."""
    col_name = f"{metric_name}_pct"
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['fiscal_year', col_name])
        for year, value in results:
            writer.writerow([year, f"{value:.2f}"])
```

## Decision Flowchart

```
START
  │
  ├─► Read task instruction carefully
  │     • Which company?
  │     • Which metric(s)?
  │     • Any conditional logic?
  │     • Output format requirements?
  │
  ├─► Phase 1: Discover correct file(s)
  │     • List data directory
  │     • Read each file, check company + fields
  │     • Reject decoys (wrong company, quarterly, non-financial)
  │
  ├─► Phase 2: Parse data
  │     • Detect format (CSV/JSON/fixed-width/HTML)
  │     • Find header row
  │     • Extract data rows
  │
  ├─► Phase 3: Map fields
  │     • Normalize field names to canonical forms
  │     • Normalize numeric values
  │
  ├─► Phase 4: Compute primary metric
  │     • Apply formula per year
  │     • Round to 2 decimal places
  │
  ├─► Phase 5: Evaluate condition (if any)
  │     • Check threshold/comparison using most recent year
  │     • If condition fails → compute fallback metric
  │
  └─► Phase 6: Write output
        • Use specified column names
        • Percentage values (not decimals)
        • CSV format unless otherwise specified
```

## Additional Format Parsers

### JSON Parsing

```python
def try_json_parse(content):
    """Parse financial data from JSON (handles nested structures)."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    
    # Navigate to find the records array
    records = find_records_in_json(data)
    return records if records else None

def find_records_in_json(obj, depth=0):
    """Recursively find an array of record-like dicts in JSON."""
    if depth > 5:
        return None
    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        # Check if items look like financial records
        keys = set(k.lower() for k in obj[0].keys())
        financial_keys = {'revenue', 'sales', 'gross_profit', 'net_income', 'year', 'fiscal_year'}
        if keys & financial_keys:
            return obj
    if isinstance(obj, dict):
        for key, val in obj.items():
            result = find_records_in_json(val, depth + 1)
            if result:
                return result
    return None
```

### HTML Table Parsing

```python
def try_html_parse(content):
    """Parse financial data from HTML tables."""
    import re
    # Find all tables
    tables = re.findall(r'<table[^>]*>(.*?)</table>', content, re.DOTALL | re.IGNORECASE)
    
    for table_html in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
        if len(rows) < 2:
            continue
        
        # Parse header row
        header_cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', rows[0], re.DOTALL | re.IGNORECASE)
        header = [clean_html_cell(c) for c in header_cells]
        
        if not any(is_financial_field(h) for h in header):
            continue
        
        # Parse data rows
        records = []
        for row_html in rows[1:]:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
            if len(cells) >= len(header):
                record = {}
                for i, h in enumerate(header):
                    if i < len(cells):
                        record[h] = clean_html_cell(cells[i])
                records.append(record)
        
        if records:
            return records
    return None

def clean_html_cell(html):
    """Strip HTML tags and whitespace from a cell."""
    text = re.sub(r'<[^>]+>', '', html)
    return text.strip()

def is_financial_field(name):
    """Check if a field name looks financial."""
    financial_terms = ['revenue', 'profit', 'income', 'equity', 'sales', 'margin', 'year']
    return any(t in name.lower() for t in financial_terms)
```

### Fixed-Width Parsing

```python
def try_fixed_width_parse(content):
    """Parse fixed-width financial data by detecting column alignment."""
    lines = [l.rstrip() for l in content.split('\n') if l.strip()]
    
    # Find the header line
    header_idx = None
    for i, line in enumerate(lines):
        if is_header_line(line):
            header_idx = i
            break
    
    if header_idx is None:
        return None
    
    # Detect column positions from header
    header_line = lines[header_idx]
    # Find word positions
    columns = []
    for match in re.finditer(r'\S+', header_line):
        columns.append((match.start(), match.group()))
    
    # Parse data rows
    records = []
    for line in lines[header_idx + 1:]:
        if not line.strip() or all(c in '=-_|+' for c in line.strip()):
            break
        record = {}
        for col_start, col_name in columns:
            # Find next column start or end of line
            col_idx = columns.index((col_start, col_name))
            if col_idx + 1 < len(columns):
                col_end = columns[col_idx + 1][0]
            else:
                col_end = len(line)
            value = line[col_start:col_end].strip() if col_start < len(line) else ''
            record[col_name] = value
        if any(v for v in record.values()):
            records.append(record)
    
    return records if records else None
```

## Multi-File Joining

When data spans multiple files (e.g., income statement + balance sheet):

```python
def join_statements(files, join_key='fiscal_year'):
    """Join records from multiple files on a common key."""
    all_records = {}
    
    for fpath in files:
        records = parse_financial_data(fpath)
        for rec in records:
            # Normalize the record
            norm = {normalize_field_name(k): v for k, v in rec.items()}
            key = normalize_year(norm.get(join_key, ''))
            if key not in all_records:
                all_records[key] = {}
            all_records[key].update(norm)
    
    # Convert back to list
    result = []
    for key in sorted(all_records.keys()):
        rec = all_records[key]
        rec[join_key] = key  # ensure join key is present
        result.append(rec)
    return result

def normalize_year(year_str):
    """Normalize year labels to a canonical form for joining."""
    s = str(year_str).strip()
    # Extract 4-digit year
    match = re.search(r'(\d{4})', s)
    if match:
        return f"FY{match.group(1)}"
    return s
```

## Common Pitfalls

1. **Decoy files**: Files with financial-sounding names but wrong company or quarterly data
2. **Scale confusion**: Values in millions vs absolute; ensure consistent units
3. **Year format**: "FY2024" vs "2024" vs "Year ending Jan 2024" — normalize for comparison
4. **Percentage vs decimal**: Output should be 72.72 (meaning 72.72%), not 0.7272
5. **Conditional logic**: Always check the condition BEFORE deciding which metric to output
6. **Most recent year**: Determine this from the data (last row or highest year number), not assumptions
7. **Field ambiguity**: "Income" alone is ambiguous — check context for gross/net/operating
8. **Multi-file joins**: Ensure year labels match across files before joining
9. **Field mapping collisions**: When variant sets overlap (e.g., "revenue" is a substring of "cost of revenue"), first-match-wins with arbitrary iteration order is a **correctness hazard**. Always use longest-match-wins or explicit exclusion rules. This is a universal principle for any heterogeneous-input → canonical-category mapping.
10. **European number formats**: A value like `"130.497,00"` stripped of commas becomes `130.497` (wrong by 1000×). Always detect which of `.` or `,` is the decimal separator by position (the last one is typically decimal).

## Adversarial Input Testing

Before deploying the field mapper, test it against inputs that expose collision bugs:

```python
# These MUST all map correctly:
test_cases = [
    ("Revenue", "revenue"),
    ("Cost of Revenue", "cost_of_revenue"),  # NOT "revenue"
    ("Net Sales", "revenue"),
    ("Gross Profit", "gross_profit"),
    ("GP", "gross_profit"),
    ("Net Income", "net_income"),
    ("Operating Income", "operating_income"),
    ("Total Stockholders Equity", "total_equity"),
    ("COGS", "cost_of_revenue"),
]
for field_name, expected in test_cases:
    result = normalize_field_name(field_name)
    assert result == expected, f"FAIL: '{field_name}' → '{result}', expected '{expected}'"
```

For numeric normalization, test:
```python
numeric_tests = [
    ("1,234.56", 1234.56),     # English
    ("1.234,56", 1234.56),     # European
    ("130,50", 130.50),        # European decimal
    ("1,234,567", 1234567),    # English thousands
    ("(500)", -500.0),         # Parenthetical negative
    ("$1,234M", 1234000000),   # Scale + currency
    ("1.234.567", 1234567),    # European thousands (multiple dots)
]
```

## Variations Expected per Spec

| Dimension | What Varies | How to Handle |
|-----------|-------------|---------------|
| source_representation | File format, naming | Try multiple parsers; content-based discovery |
| statement_topology | Single vs multi-file | Join on fiscal year when needed |
| financial_metric | Which metric to compute | Use correct formula; handle conditional switching |
| schema_and_locale | Field names, number formats | Flexible field mapping; numeric normalization |
| output_contract | Column names, serialization | Follow task-specified output format exactly |
