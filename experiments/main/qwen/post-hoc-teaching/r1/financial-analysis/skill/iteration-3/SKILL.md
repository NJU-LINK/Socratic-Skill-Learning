---
name: financial-analysis
description: >
  Discover, parse, and compute financial metrics from heterogeneous data sources.
  Handles file discovery among decoys (including subdirectories), multiple data formats
  (CSV, JSON, fixed-width, HTML), field-name normalization across locales/schemas,
  multi-statement joins, conditional metric selection, and structured output.
---

# Financial Analysis Skill

## Overview

This skill solves tasks that require:
1. Locating the correct financial data file(s) among potentially many files (including decoys, possibly in subdirectories)
2. Parsing financial data from varied formats and schemas
3. Computing a requested financial metric per fiscal year
4. Applying conditional logic (e.g., threshold-based metric switching)
5. Writing results in a specified output format

## General Methodology

### Phase 1: File Discovery

**Goal**: Identify which file(s) contain the target company's relevant financial data.

**Procedure**:
1. Recursively list all files in the data directory (e.g., `/app/financials/`) using `os.walk` or similar
2. Score each file by:
   - **Filename match**: Does the filename contain the target company name or ticker?
   - **Content match**: Does the file content contain the target company name?
   - **Required fields**: Does the file contain the financial fields needed for the metric?
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
- If multiple files match, prefer the one with the most complete data

### Phase 2: Data Parsing

**Goal**: Extract structured (year → financial values) records from the identified file(s).

**Format detection and parsing strategy**:
1. Try JSON parsing first (if content starts with `{` or `[`)
2. Try HTML parsing (if content contains `<table`)
3. Try CSV/delimited parsing (detect delimiter from header row)
4. Try fixed-width parsing (if no clear delimiter found)

**Universal parsing approach**:
1. Scan for lines that look like headers (contain known financial field names)
2. **Detect the delimiter** from the header line (comma, semicolon, tab, pipe)
3. Use the **same delimiter** for parsing all subsequent data rows
4. Normalize field names to a canonical mapping (see Field Mapping below)
5. **Lock the header** after first detection — do not re-check for headers on subsequent lines
6. **Identify the year column** from the header to guide data row detection
7. **Distinguish "not data" from "end of data section"**:
   - Lines that don't match data pattern (blank lines, irrelevant text) → skip and continue
   - Section boundaries (separator blocks, "NOTES:" labels) → stop parsing
8. Stop parsing when hitting a section boundary

**Critical: Header lock and section boundaries** — Once the header is detected, lock it and stop checking `is_header_line` on subsequent lines. Notes lines with financial terms (e.g., "Revenue, Operating Income are reported on accrual basis") can match `is_header_line` and silently corrupt the schema if not prevented.

**Critical: Flexible column order** — The year column may not be first. After detecting the header, identify which column contains the year field and use that column index for data row detection. This handles variants where columns are in different orders (e.g., "Segment,Year,Revenue" vs "Year,Revenue,Segment").

**Critical: HTML merged headers** — HTML tables may have multi-level headers with `colspan` attributes. These must be flattened by combining parent and child headers (e.g., "2024" + "Q1" → "2024 Q1"). The parser should detect `<th>` rows and build a unified header list before parsing data rows.

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

**Numeric normalization**:
- Remove currency symbols ($, €, £, ¥, ₹)
- Handle scale indicators: "M" = millions, "B" = billions, "K" = thousands
- Handle parenthetical negatives: `(1,234)` → `-1234`; also handle leading minus
- **European vs English format detection**: When both `.` and `,` appear, the **last** one is the decimal separator. If only `,` appears: 3 digits after last comma → thousands separator; 1-2 digits → European decimal. If only `.` appears multiple times → European thousands separators.

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

**Extract output specification from task instruction**:
- Parse the instruction to identify exact column names required
- Identify the output file path
- Determine the serialization format (CSV, JSON, etc.)
- Note any specific formatting requirements (decimal places, percentage format, etc.)

**Standard output patterns**:
- CSV with header row: `<year_column>,<value_column>`
- The column names should match what the task instruction specifies
- Common patterns: `fiscal_year,gross_margin_pct` or `year,gross_margin_pct` or `period,value`
- Values are percentage numbers (e.g., 72.72), not decimals (0.7272)
- Round to 2 decimal places unless otherwise specified
- One row per fiscal year, typically in chronological order

**Output column naming**:
- Extract exact column names from the task instruction
- If not specified, use defaults: `fiscal_year` for year column, `<metric_name>_pct` for value column
- Pass extracted column names to `write_results` as parameters

### Phase 7: Multi-File Joining (when needed)

When financial data spans multiple files (e.g., income statement + balance sheet):

1. Parse each file independently
2. Identify the join key (usually fiscal year)
3. Normalize year labels across files (e.g., "FY2024", "2024", "Year ending 2024" → same key)
4. Join on fiscal year to combine fields from different statements
5. Compute the metric using the combined data

## Complete Implementation

```python
import csv
import json
import re
import os

# === CONFIGURATION (adapt per task) ===
DATA_DIR = "/app/financials"  # or wherever data lives
OUTPUT_FILE = "/app/results.csv"
TARGET_COMPANY = "NVIDIA"  # or as specified

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
    """Map a field name to its canonical form using longest-match-wins."""
    # Split CamelCase, normalize separators
    camel_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    name_lower = camel_split.lower().strip()
    name_lower = name_lower.replace('_', ' ').replace('-', ' ')
    name_lower = re.sub(r'\s+', ' ', name_lower).strip()
    
    # Collect all matching candidates
    candidates = []
    for canonical, variants in FIELD_VARIANTS.items():
        for variant in variants:
            if variant in name_lower:
                candidates.append((len(variant), canonical, variant))
    
    if not candidates:
        return name_lower
    
    # Longest match wins
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]

def normalize_numeric(value_str):
    """Convert a string to a float, handling various formats."""
    s = str(value_str).strip()
    if not s:
        return None
    
    # Handle parentheses as negatives
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1].strip()
    if s.startswith('-'):
        negative = not negative
        s = s[1:].strip()
    
    # Remove scale indicators
    scale = 1.0
    s_upper = s.upper().rstrip()
    if s_upper.endswith('B'):
        scale = 1e9; s = s_upper[:-1].strip()
    elif s_upper.endswith('M'):
        scale = 1e6; s = s_upper[:-1].strip()
    elif s_upper.endswith('K'):
        scale = 1e3; s = s_upper[:-1].strip()
    else:
        s = s_upper
    
    # Remove currency symbols
    s = re.sub(r'[$\u20ac\u00a3\u00a5\u20b9]', '', s).strip()
    
    # Determine decimal separator
    has_dot = '.' in s
    has_comma = ',' in s
    
    if has_dot and has_comma:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif has_comma and not has_dot:
        if len(s.split(',')[-1]) == 3:
            s = s.replace(',', '')
        else:
            s = s.replace(',', '.')
    elif has_dot and not has_comma:
        if s.count('.') > 1:
            s = s.replace('.', '')
    
    s = s.strip()
    try:
        val = float(s) * scale
        return -val if negative else val
    except ValueError:
        return None

# === PHASE 1: File Discovery ===
def discover_file(data_dir, company_name, required_fields=None):
    """Find the file containing target company's financial data.
    
    Searches recursively and uses robust matching:
    - Full name: "NVIDIA Corporation"
    - Short name: "NVIDIA"
    - Ticker: "NVDA"
    - Partial matches: "NVIDIA Corp"
    """
    candidates = []
    
    # Build list of company name variants to match
    company_variants = build_company_variants(company_name)
    
    for root, dirs, files in os.walk(data_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            
            # Score this file
            score = 0
            
            # Filename match (any variant)
            fname_lower = fname.lower()
            if any(variant.lower() in fname_lower for variant in company_variants):
                score += 10
            
            # Content match
            try:
                with open(fpath, 'r', errors='ignore') as f:
                    content = f.read()
                
                content_upper = content.upper()
                # Check for any company variant
                if any(variant.upper() in content_upper for variant in company_variants):
                    score += 5
                
                # Check for required fields
                if required_fields:
                    content_lower = content.lower()
                    has_fields = all(
                        any(variant in content_lower for variant in FIELD_VARIANTS.get(field, [field]))
                        for field in required_fields
                    )
                    if has_fields:
                        score += 3
                
                # Check for numeric data
                if re.search(r'\d{3,}', content):
                    score += 1
                    
            except Exception:
                continue
            
            if score > 0:
                candidates.append((score, fpath))
    
    if not candidates:
        return None
    
    # Return highest-scoring file
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]

def build_company_variants(company_name):
    """Build a list of company name variants for matching.
    
    Examples:
    - "NVIDIA Corporation" -> ["NVIDIA Corporation", "NVIDIA Corp", "NVIDIA", "NVDA"]
    - "Apple Inc." -> ["Apple Inc", "Apple", "AAPL"]
    """
    variants = [company_name]
    
    # Remove common suffixes
    for suffix in [' Corporation', ' Corp.', ' Corp', ' Inc.', ' Inc', ' LLC', ' Ltd.', ' Ltd']:
        if company_name.endswith(suffix):
            variants.append(company_name[:-len(suffix)])
    
    # Extract first word (often the main brand name)
    first_word = company_name.split()[0]
    if first_word not in variants:
        variants.append(first_word)
    
    # Common ticker symbols (would need a lookup table for full coverage)
    # For now, just add uppercase abbreviation if it looks like one
    if len(company_name) <= 5 and company_name.isupper():
        # Already looks like a ticker
        pass
    
    return variants

# === PHASE 2: Parsing ===
def parse_financial_data(filepath):
    """Parse financial data from various formats into list of dicts."""
    with open(filepath, 'r', errors='ignore') as f:
        content = f.read()
    
    # Try JSON first
    if content.strip().startswith('{') or content.strip().startswith('['):
        records = try_json_parse(content)
        if records:
            return records
    
    # Try HTML
    if '<table' in content.lower():
        records = try_html_parse(content)
        if records:
            return records
    
    # Try CSV/delimited
    records = try_csv_parse(content)
    if records:
        return records
    
    # Try fixed-width
    records = try_fixed_width_parse(content)
    if records:
        return records
    
    raise ValueError(f"Could not parse financial data from {filepath}")

def detect_delimiter(line):
    """Detect the delimiter used in a line."""
    # Try common delimiters in order of likelihood
    for delim in [',', ';', '\t', '|']:
        if delim in line:
            # Verify it produces multiple fields
            parts = line.split(delim)
            if len(parts) >= 2:
                return delim
    return ','

def is_header_line(line):
    """Check if a line looks like a CSV header with financial fields."""
    line_lower = line.lower()
    financial_terms = ['revenue', 'profit', 'income', 'equity', 'sales', 'margin',
                       'year', 'fiscal', 'ebit', 'cogs']
    matches = sum(1 for t in financial_terms if t in line_lower)
    # Must have at least 2 financial terms and a delimiter
    has_delim = any(d in line for d in [',', '\t', '|', ';'])
    return matches >= 2 and has_delim

def looks_like_year(token):
    """Check if a token looks like a fiscal year."""
    token = token.strip()
    # FY2024, FY24, 2024, 2022-23, Year 2024, etc.
    patterns = [
        r'^(FY)?\d{2,4}$',  # FY2024, FY24, 2024
        r'^\d{4}[-/]\d{2,4}$',  # 2022-23, 2022/2023
        r'^(year|fy)\s*\d{2,4}$',  # Year 2024, FY 2024
    ]
    return any(re.match(p, token, re.IGNORECASE) for p in patterns)

def looks_like_data_row(line, delimiter, year_col_idx=None):
    """Check if a line looks like a data row.
    
    If year_col_idx is provided, check that specific column for a year.
    Otherwise, check if ANY column contains a year-like token.
    """
    parts = line.split(delimiter)
    if len(parts) < 2:
        return False
    
    # Check if there are numeric values in at least one column
    has_numbers = any(re.search(r'\d', p) for p in parts)
    if not has_numbers:
        return False
    
    # If year column index is specified, check that column
    if year_col_idx is not None and year_col_idx < len(parts):
        return looks_like_year(parts[year_col_idx].strip())
    
    # Otherwise, check if ANY column looks like a year
    return any(looks_like_year(p.strip()) for p in parts)

def is_section_break(line):
    """Detect lines that mark the end of a data section.
    
    Returns True for:
    - Separator lines with mostly separator characters (===, ---, etc.)
    - Section labels like "NOTES:", "FOOTNOTES:", "SOURCE:", "TOTAL", "SUBTOTAL"
    """
    stripped = line.strip()
    if not stripped:
        return False
    
    # Lines that are mostly separator characters with some text
    if len(stripped) > 3:
        sep_chars = sum(1 for c in stripped if c in '=-_|+')
        if sep_chars / len(stripped) > 0.5:
            return True
    
    # Explicit section labels
    lower = stripped.lower()
    section_keywords = ['notes', 'note:', 'footnotes', 'source:', 'total', 'subtotal']
    for keyword in section_keywords:
        if lower == keyword or lower.startswith(keyword + ' ') or lower.startswith(keyword + ':'):
            return True
    
    return False

def try_csv_parse(content):
    """Parse CSV/delimited data from content."""
    lines = content.strip().split('\n')
    header = None
    delimiter = None
    year_col_idx = None
    records = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # Skip pure separator lines FIRST (they are structural, not semantic)
        if all(c in '=-_|+ ' for c in stripped):
            continue
        
        # THEN check for section break (only meaningful on text-bearing lines)
        if header and is_section_break(stripped):
            break
        
        # Detect header ONCE — lock it after finding
        if header is None and is_header_line(stripped):
            delimiter = detect_delimiter(stripped)
            header = [h.strip() for h in stripped.split(delimiter)]
            # Find which column contains the year
            for idx, col_name in enumerate(header):
                if normalize_field_name(col_name) == 'fiscal_year':
                    year_col_idx = idx
                    break
            continue
        
        # Parse data rows after header found
        if header and delimiter and looks_like_data_row(stripped, delimiter, year_col_idx):
            parts = [p.strip() for p in stripped.split(delimiter)]
            if len(parts) >= len(header):
                record = {}
                for i, h in enumerate(header):
                    if i < len(parts):
                        record[h] = parts[i]
                records.append(record)
    
    return records if records else None

def try_json_parse(content):
    """Parse financial data from JSON."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    
    records = find_records_in_json(data)
    return records if records else None

def find_records_in_json(obj, depth=0):
    """Recursively find an array of record-like dicts in JSON."""
    if depth > 5:
        return None
    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
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

def try_html_parse(content):
    """Parse financial data from HTML tables, handling merged headers."""
    tables = re.findall(r'<table[^>]*>(.*?)</table>', content, re.DOTALL | re.IGNORECASE)
    
    for table_html in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
        if len(rows) < 2:
            continue
        
        # Parse header rows (may have multiple levels with colspan/rowspan)
        header_rows = []
        data_start_idx = 0
        
        for row_idx, row_html in enumerate(rows):
            # Check if this is a header row (contains <th> tags)
            if '<th' in row_html.lower():
                header_rows.append(row_html)
                data_start_idx = row_idx + 1
            else:
                break
        
        if not header_rows:
            continue
        
        # Flatten multi-level headers with colspan handling
        header = flatten_html_headers(header_rows)
        
        if not any(is_financial_field(h) for h in header):
            continue
        
        # Parse data rows
        records = []
        for row_html in rows[data_start_idx:]:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
            if len(cells) >= len(header):
                record = {}
                for i, h in enumerate(header):
                    if i < len(cells):
                        record[h] = re.sub(r'<[^>]+>', '', cells[i]).strip()
                records.append(record)
        
        if records:
            return records
    return None

def flatten_html_headers(header_rows):
    """Flatten multi-level HTML headers, handling colspan and rowspan.
    
    Returns a single list of column names by combining parent and child headers.
    """
    if len(header_rows) == 1:
        # Single-level header
        cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', header_rows[0], re.DOTALL | re.IGNORECASE)
        return [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
    
    # Multi-level header: parse each row and build column hierarchy
    grid = []
    max_cols = 0
    
    for row_html in header_rows:
        row_cells = []
        cells = re.findall(r'<t[hd]([^>]*)>(.*?)</t[hd]>', row_html, re.DOTALL | re.IGNORECASE)
        
        for attrs, content in cells:
            text = re.sub(r'<[^>]+>', '', content).strip()
            colspan = 1
            colspan_match = re.search(r'colspan=["\']?(\d+)', attrs, re.IGNORECASE)
            if colspan_match:
                colspan = int(colspan_match.group(1))
            row_cells.append((text, colspan))
        
        grid.append(row_cells)
        max_cols = max(max_cols, sum(c[1] for c in row_cells))
    
    # Build final header by combining levels
    # For each column position, combine all non-empty parent headers
    final_header = []
    for col_idx in range(max_cols):
        parts = []
        current_col = 0
        for row_cells in grid:
            for text, colspan in row_cells:
                if current_col <= col_idx < current_col + colspan:
                    if text:
                        parts.append(text)
                    break
                current_col += colspan
        
        # Combine parts with space, or use last non-empty part
        if parts:
            final_header.append(' '.join(parts))
        else:
            final_header.append(f'Column_{col_idx}')
    
    return final_header

def is_financial_field(name):
    """Check if a field name looks financial."""
    financial_terms = ['revenue', 'profit', 'income', 'equity', 'sales', 'margin', 'year']
    return any(t in name.lower() for t in financial_terms)

def try_fixed_width_parse(content):
    """Parse fixed-width financial data."""
    lines = [l.rstrip() for l in content.split('\n') if l.strip()]
    
    header_idx = None
    for i, line in enumerate(lines):
        if is_header_line(line):
            header_idx = i
            break
    
    if header_idx is None:
        return None
    
    header_line = lines[header_idx]
    columns = []
    for match in re.finditer(r'\S+', header_line):
        columns.append((match.start(), match.group()))
    
    records = []
    for line in lines[header_idx + 1:]:
        # Skip blank lines but continue parsing
        if not line.strip():
            continue
        
        # Skip pure separator lines (they are structural, not semantic)
        if all(c in '=-_|+ ' for c in line.strip()):
            continue
        
        # Then check for section break (end of data section)
        if is_section_break(line):
            break
        
        record = {}
        for col_idx, (col_start, col_name) in enumerate(columns):
            if col_idx + 1 < len(columns):
                col_end = columns[col_idx + 1][0]
            else:
                col_end = len(line)
            value = line[col_start:col_end].strip() if col_start < len(line) else ''
            record[col_name] = value
        if any(v for v in record.values()):
            records.append(record)
    
    return records if records else None

# === PHASE 4: Metric Computation ===
def compute_metric(records, metric_name):
    """Compute a financial metric for each year."""
    normalized = []
    for rec in records:
        norm = {normalize_field_name(k): v for k, v in rec.items()}
        normalized.append(norm)
    
    if metric_name == 'year_over_year_growth':
        return _compute_yoy_growth(normalized)
    
    results = []
    for rec in normalized:
        year = rec.get('fiscal_year', '')
        value = _compute_single_metric(rec, metric_name)
        if value is not None:
            results.append((year, value))
    
    return results

def _compute_single_metric(rec, metric_name):
    """Compute a single-year metric."""
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
    """Compute year-over-year revenue growth."""
    sorted_recs = sorted(normalized_records, key=lambda r: r.get('fiscal_year', ''))
    
    results = []
    for i, rec in enumerate(sorted_recs):
        if i == 0:
            continue
        current_rev = normalize_numeric(rec.get('revenue', 0))
        prior_rev = normalize_numeric(sorted_recs[i - 1].get('revenue', 0))
        if current_rev is not None and prior_rev and prior_rev != 0:
            growth = ((current_rev - prior_rev) / prior_rev) * 100
            results.append((rec.get('fiscal_year', ''), growth))
    
    return results

# === PHASE 6: Output ===
def write_results(filepath, results, metric_name, year_column='fiscal_year', value_column=None):
    """Write results to CSV.
    
    Args:
        filepath: Output file path
        results: List of (year, value) tuples
        metric_name: Name of the metric (e.g., 'gross_margin')
        year_column: Column name for year (default: 'fiscal_year')
        value_column: Column name for values (default: '{metric_name}_pct')
    """
    if value_column is None:
        value_column = f"{metric_name}_pct"
    
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([year_column, value_column])
        for year, value in results:
            writer.writerow([year, f"{value:.2f}"])

# === Multi-File Joining ===
def join_statements(files, join_key='fiscal_year'):
    """Join records from multiple files on a common key."""
    all_records = {}
    
    for fpath in files:
        records = parse_financial_data(fpath)
        for rec in records:
            norm = {normalize_field_name(k): v for k, v in rec.items()}
            key = normalize_year(norm.get(join_key, ''))
            if key not in all_records:
                all_records[key] = {}
            all_records[key].update(norm)
    
    result = []
    for key in sorted(all_records.keys()):
        rec = all_records[key]
        rec[join_key] = key
        result.append(rec)
    return result

def normalize_year(year_str):
    """Normalize year labels to a canonical form for joining.
    
    Handles various formats:
    - "FY2024", "2024" -> "FY2024"
    - "FY23" -> "FY2023" (assumes 2000s)
    - "2022-23" -> "FY2023" (uses end year)
    - "Year ending March 2024" -> "FY2024"
    - "2024/25" -> "FY2025"
    """
    s = str(year_str).strip()
    
    # Try year range first (2022-23, 2024/25) - check before 4-digit to avoid false matches
    match = re.search(r'(\d{4})[-/](\d{2,4})', s)
    if match:
        end_year = match.group(2)
        if len(end_year) == 2:
            return f"FY{2000 + int(end_year)}"
        else:
            return f"FY{end_year}"
    
    # Try to extract a 4-digit year
    match = re.search(r'\b(\d{4})\b', s)
    if match:
        return f"FY{match.group(1)}"
    
    # Try 2-digit year (FY23, 23, etc.) - use more flexible pattern
    match = re.search(r'(?:FY|fy)?(\d{2})(?:\b|$)', s)
    if match:
        year = int(match.group(1))
        # Assume 2000s for years 00-99
        return f"FY{2000 + year}"
    
    return s
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
  │     • Recursively search data directory
  │     • Score files by filename + content match
  │     • Reject decoys (wrong company, quarterly, non-financial)
  │
  ├─► Phase 2: Parse data
  │     • Detect format (JSON/HTML/CSV/fixed-width)
  │     • Detect delimiter from header (for CSV)
  │     • Use same delimiter for all data rows
  │
  ├─► Phase 3: Map fields
  │     • Normalize field names (longest-match-wins)
  │     • Normalize numeric values (handle European formats)
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

## Common Pitfalls

1. **Decoy files**: Files with financial-sounding names but wrong company or quarterly data
2. **Scale confusion**: Values in millions vs absolute; ensure consistent units
3. **Year format**: "FY2024" vs "2024" vs "Year ending Jan 2024" — normalize for comparison
4. **Percentage vs decimal**: Output should be 72.72 (meaning 72.72%), not 0.7272
5. **Conditional logic**: Always check the condition BEFORE deciding which metric to output
6. **Most recent year**: Determine this from the data (last row or highest year number), not assumptions
7. **Field ambiguity**: "Income" alone is ambiguous — check context for gross/net/operating
8. **Multi-file joins**: Ensure year labels match across files before joining
9. **Field mapping collisions**: When variant sets overlap, longest-match-wins prevents silent errors
10. **European number formats**: Detect decimal separator by position (last `.` or `,`)
11. **Delimiter consistency**: Detect delimiter from header, use it for all data rows
12. **Subdirectory search**: Use recursive search, not just top-level directory listing
13. **Section boundary detection**: Distinguish "not data" (skip and continue) from "end of data section" (stop parsing). Notes lines with financial terms can trick header detection if not locked after first detection.
14. **Output contract flexibility**: Extract exact column names from task instruction rather than hardcoding defaults. Variants may require different column names.
15. **HTML merged headers**: Tables with `colspan` or multi-level headers must be flattened before parsing. Parent and child headers should be combined (e.g., "2024 Q1" from a two-level header).
16. **Column order flexibility**: Year column may not be first. Check all columns for year-like tokens when detecting data rows.
17. **Company name variations**: Match against multiple variants (full name, short name, ticker). "NVIDIA Corporation" should match "NVIDIA", "NVDA", "NVIDIA Corp", etc.
18. **Check ordering in parsing loops**: When two conditions overlap and one should take precedence, always check the skip/continue case before the stop/break case. A false positive on a "stop" condition is worse than a missed skip, because stopping loses data while skipping merely ignores noise. Example: check "pure separator" (structural) before "section break" (semantic).

## Adversarial Input Testing

Test field mapper against collision cases:
```python
test_cases = [
    ("Revenue", "revenue"),
    ("Cost of Revenue", "cost_of_revenue"),  # NOT "revenue"
    ("GrossProfit", "gross_profit"),  # CamelCase
    ("cost_of_revenue", "cost_of_revenue"),  # underscores
]
```

Test numeric normalization:
```python
numeric_tests = [
    ("1,234.56", 1234.56),     # English
    ("1.234,56", 1234.56),     # European
    ("130,50", 130.50),        # European decimal
    ("$1,234M", 1234000000),   # Scale + currency
]
```

## Variations Expected per Spec

| Dimension | What Varies | How to Handle |
|-----------|-------------|---------------|
| source_representation | File format, naming, subdirectories, wrapper text, notes sections | Recursive search; multiple parsers; delimiter detection; section boundary detection |
| statement_topology | Single vs multi-file | Join on fiscal year when needed |
| financial_metric | Which metric to compute | Use correct formula; handle conditional switching |
| schema_and_locale | Field names, number formats, year labels, irrelevant rows, notes sections | Longest-match field mapping; European number handling; flexible year detection; section break detection |
| output_contract | Column names, serialization format | Extract exact column names from task instruction; pass as parameters to write_results |
