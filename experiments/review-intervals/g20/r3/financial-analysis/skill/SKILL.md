---
name: financial-analysis
description: >
  Discover, parse, and compute standard financial metrics from heterogeneous
  corporate financial data sources, handling decoy files, varied formats,
  conditional metric selection, and explicit output contracts.
---

# Financial Analysis Skill

## Overview

This skill handles tasks that require extracting financial data from corporate
filings or summaries, computing standard financial metrics, and producing
structured output. The core challenge is navigating real-world data discovery
and format variation while applying correct financial formulas.

## Core Workflow

### 1. Data Discovery

Financial data may be hidden among decoy files. Use content-based discovery:

- **Scan all files** in the specified directory recursively
- **Identify the target company** by searching for company name, ticker, or exchange
- **Classify each relevant file by statement type** based on which fields it contains:
  - Income statement fields: revenue, gross profit, operating income, net income
  - Balance sheet fields: total assets, total liabilities, shareholders' equity, total equity
  - If a file contains both, it's a combined statement
- **Verify data relevance** by checking for required financial line items
- **Reject decoys**: Files may have misleading names or contain data for wrong
  companies, wrong time periods (quarterly vs annual), or incomplete metrics

**Discovery heuristics:**
- Look for explicit company identifiers (name, ticker symbol)
- Check for fiscal year coverage matching the task requirements
- Verify presence of all required financial line items
- Prefer files with clear financial statement structure over ambiguous formats

### 2. Data Parsing: Format Detection and Dispatch

The family spec lists four source formats: **CSV, nested JSON, fixed-width text,
and HTML tables with merged headers**. Your parsing pipeline must detect the
format and dispatch to the appropriate parser.

#### Format Detection

```python
def detect_and_parse(content):
    """Detect format and dispatch to appropriate parser.
    
    Returns: {year: {canonical_field: value}} dict
    """
    stripped = content.strip()
    
    # JSON: starts with { or [
    if stripped.startswith('{') or stripped.startswith('['):
        return parse_json_financial(content)
    
    # HTML: contains <table tag
    if '<table' in content.lower():
        return parse_html_table(content)
    
    # CSV/delimited detection: scan ALL lines for delimiter patterns
    # (not just the first line — files often have metadata headers)
    lines = stripped.split('\n')
    csv_like = 0
    for line in lines:
        s = line.strip()
        if not s:
            continue
        # Skip decorative lines (====, ----, ****, etc.)
        if all(c in '=-*#|+' for c in s):
            continue
        # Skip metadata/key-value lines (e.g., "Company: NVIDIA")
        if ':' in s and ',' not in s:
            continue
        # Count lines with commas as potential CSV
        if ',' in s:
            csv_like += 1
    
    if csv_like >= 2:  # At least a header + 1 data row with commas
        return parse_csv_style(content)
    
    # Fixed-width: no delimiter, detect column positions from header
    return parse_fixed_width(content)
```

**Principle: Never trust the first line alone for format detection.** Metadata blocks, decorative banners, and preamble text are common in real-world financial files. Scan a representative sample of non-decorative lines and use a count threshold. This is the same robustness mindset as content-based file discovery — don't trust filenames, trust content; don't trust the first line, trust the distribution of lines.

**All parsers produce the same output format:** `{year: {canonical_field: value}}` dict.
This ensures downstream metric calculation works identically regardless of source format.

---

### 2a. CSV/Delimited Text Parser

**Never use positional column indexing.** Column order, labels, and language vary
across the family. Instead, detect the header row and build a mapping from
detected column names to canonical field names.

#### Field Name Normalization

**Critical:** Field names vary widely: `OperatingIncome` (camelCase), `operating_income` (snake_case), `Operating Income` (space-separated), `OPERATING_INCOME` (uppercase). You must normalize before matching.

```python
import re

def normalize_field_name(name):
    """Normalize field name to lowercase space-separated for matching.
    
    Handles:
    - camelCase: OperatingIncome -> operating income
    - snake_case: operating_income -> operating income
    - UPPERCASE: OPERATING_INCOME -> operating income
    - Mixed: GrossProfit -> gross profit
    - Annotations: Gross Profit ($M) -> gross profit m
    """
    # Convert camelCase to space-separated
    normalized = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    normalized = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', normalized)
    # Replace underscores and hyphens with spaces
    normalized = re.sub(r'[_-]', ' ', normalized)
    # Strip non-alphanumeric characters (parentheses, currency symbols, %, etc.)
    normalized = re.sub(r'[^a-zA-Z0-9\s]', '', normalized)
    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip().lower()
```

#### Column Alias Registry

**Note:** All aliases are in normalized form (lowercase, space-separated). The `normalize_field_name()` function converts any input format to this form before matching.

```python
COLUMN_ALIASES = {
    'year': [
        'year', 'fiscal year', 'fy', 'period', 'exercise', 'ejercicio',
        'exercice', 'jahr', 'anno', '年度', '财年'
    ],
    'revenue': [
        'revenue', 'total revenue', 'sales', 'turnover', 'net sales',
        'net revenue', 'ventas', 'ingresos', 'chiffre d affaires',
        'umsatz', 'fatturato', '収入', '売上高'
    ],
    'gross_profit': [
        'gross profit', 'gross margin', 'gross margin us',
        'margen bruto', 'marge brute', 'rohertrag', 'margine lordo',
        '粗利益', '総利益'
    ],
    'cost_of_revenue': [
        'cost of revenue', 'cost of goods sold', 'cogs', 'cost of sales',
        'costo de ventas', 'coût des ventes', 'kosten der umsatzerlöse'
    ],
    'operating_income': [
        'operating income', 'operating profit', 'ebit', 'income from operations',
        'resultado de operación', 'résultat d exploitation', 'betriebsergebnis'
    ],
    'net_income': [
        'net income', 'net profit', 'profit after tax', 'net earnings',
        'resultado neto', 'bénéfice net', 'jahresüberschuss', 'utile netto',
        '純利益', '当期純利益'
    ],
    'total_equity': [
        'shareholders equity', 'total equity', 'stockholders equity',
        'net assets', 'total shareholders equity', 'patrimonio neto',
        'capitaux propres', 'eigenkapital', 'patrimonio netto', '株主資本'
    ],
    'total_assets': [
        'total assets', 'assets', 'total asset', 'activo total', 'total de l actif'
    ],
}
```

#### Header Detection and Mapping

```python
def build_column_map(header_row):
    """Map detected column names to canonical field names.
    
    Uses normalize_field_name() to handle camelCase, snake_case, annotations, etc.
    Falls back to substring matching for robustness.
    
    Returns: dict mapping canonical name -> column index
    """
    mapping = {}
    for i, col in enumerate(header_row):
        col_normalized = normalize_field_name(col)  # CRITICAL: normalize before matching
        matched = False
        for canonical, aliases in COLUMN_ALIASES.items():
            # Exact match
            if col_normalized in aliases:
                mapping[canonical] = i
                matched = True
                break
            # Fallback: substring match (handles "gross profit m", "revenue millions", etc.)
            if any(alias in col_normalized or col_normalized in alias for alias in aliases):
                mapping[canonical] = i
                matched = True
                break
        if not matched:
            pass  # Column not recognized; skip it
    return mapping

def parse_data_rows(data_lines, column_map):
    """Parse data rows using column mapping, not positional indices.
    
    Returns: list of dicts with canonical field names as keys
    """
    records = []
    for line in data_lines:
        parts = line.split(',')
        if len(parts) < 2:
            continue
        record = {}
        for canonical, idx in column_map.items():
            if idx < len(parts):
                record[canonical] = parse_number(parts[idx])
        if 'year' in column_map and column_map['year'] < len(parts):
            record['year'] = parts[column_map['year']].strip()
        records.append(record)
    return records

def parse_csv_style(content):
    """Parse CSV/delimited text with metadata headers.
    
    Handles files with decorative banners, metadata lines, and footer notes.
    
    Returns: {year: {canonical_field: value}} dict
    """
    lines = content.strip().split('\n')
    
    # Find header line (first comma-separated line with non-numeric words)
    header_idx = None
    for i, line in enumerate(lines):
        if ',' in line:
            fields = line.split(',')
            # Check if this looks like a header (has non-numeric words)
            if any(not f.replace('.','').replace('-','').replace(' ','').isdigit() for f in fields):
                header_idx = i
                break
    
    if header_idx is None:
        raise ValueError("Could not find header line in CSV")
    
    header = lines[header_idx].split(',')
    column_map = build_column_map(header)
    
    # Parse data rows (skip header and any trailing non-data lines)
    records = {}
    for line in lines[header_idx + 1:]:
        if not line.strip() or ',' not in line:
            continue
        # Skip lines that look like notes/footers
        if line.strip().startswith(('-', '*', '#', 'Note', 'NOTE')):
            continue
        
        parts = line.split(',')
        record = {}
        for canonical, idx in column_map.items():
            if idx < len(parts):
                if canonical == 'year':
                    record['year'] = parts[idx].strip()
                else:
                    try:
                        record[canonical] = parse_number(parts[idx])
                    except ValueError:
                        pass
        
        year = record.get('year')
        if year:
            records[year] = {k: v for k, v in record.items() if k != 'year'}
    
    return records
```

#### Numeric Parsing

```python
import re

def parse_number(s):
    """Convert string to float, handling currency and negative formats."""
    s = s.strip()
    # Remove currency symbols, whitespace, and thousands separators
    s = re.sub(r'[$€£¥₹\s]', '', s)
    # Handle European decimal comma (e.g., "1.234,56" -> "1234.56")
    if ',' in s and '.' in s:
        if s.rindex(',') > s.rindex('.'):
            # European format: dots are thousands, comma is decimal
            s = s.replace('.', '').replace(',', '.')
        else:
            # US format: commas are thousands, dot is decimal
            s = s.replace(',', '')
    elif ',' in s:
        # Could be European decimal or US thousands separator
        # Heuristic: if exactly 3 digits after comma, it's thousands separator
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(',', '')
        else:
            s = s.replace(',', '.')
    # Handle negative numbers in parentheses: (1,234) -> -1234
    if s.startswith('(') and s.endswith(')'):
        return -float(s[1:-1])
    return float(s)
```

### 2b. Nested JSON Parser

JSON data has no header row and may be deeply nested. Navigate to the data array
and flatten nested structures.

```python
import json

def parse_json_financial(content):
    """Parse nested JSON financial data.
    
    Returns: {year: {canonical_field: value}} dict
    """
    data = json.loads(content)
    records = {}
    
    # Navigate to the array — try common keys
    financials = None
    for key in ['financials', 'data', 'statements', 'income_statement', 'results']:
        if key in data and isinstance(data[key], list):
            financials = data[key]
            break
    
    if financials is None:
        # Maybe it's nested deeper
        for key, val in data.items():
            if isinstance(val, dict):
                for subkey, subval in val.items():
                    if isinstance(subval, list):
                        financials = subval
                        break
    
    if financials is None:
        raise ValueError("Could not locate financial data array in JSON")
    
    for entry in financials:
        # Flatten nested dicts into a single {canonical_field: value} dict
        flat = {}
        for k, v in entry.items():
            if isinstance(v, dict):  # nested like {"income_statement": {"revenue": ...}}
                flat.update(v)
            else:
                flat[k] = v
        
        # Extract year using alias matching
        year = None
        for year_key in ['fiscal_year', 'year', 'period', 'fy']:
            if year_key in flat:
                year = str(flat[year_key])
                break
        
        if year:
            # Apply column alias mapping to canonical names
            mapped = {}
            for k, v in flat.items():
                if k in ['fiscal_year', 'year', 'period', 'fy']:
                    continue
                canonical = map_to_canonical(k)
                if canonical:
                    mapped[canonical] = v
            records[year] = mapped
    
    return records

def map_to_canonical(field_name):
    """Map a field name to canonical name using COLUMN_ALIASES.
    
    Uses normalize_field_name() to handle camelCase, snake_case, annotations, etc.
    Falls back to substring matching for robustness.
    """
    field_normalized = normalize_field_name(field_name)  # CRITICAL: normalize before matching
    for canonical, aliases in COLUMN_ALIASES.items():
        # Exact match
        if field_normalized in aliases:
            return canonical
        # Fallback: substring match (handles "gross profit m", "revenue usd", etc.)
        if any(alias in field_normalized or field_normalized in alias for alias in aliases):
            return canonical
    return None
```

---

### 2c. HTML Table Parser with Merged Headers

HTML tables may have `colspan` and `rowspan` attributes, meaning a simple header
row doesn't exist. Flatten the multi-row header into a single row, then apply
column mapping.

```python
from html.parser import HTMLParser

class TableParser(HTMLParser):
    """Parse HTML table, handling colspan/rowspan."""
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = ''
        self.in_cell = False
        self.cell_colspan = 1
        self.cell_rowspan = 1
    
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ('td', 'th'):
            self.in_cell = True
            self.current_cell = ''
            self.cell_colspan = int(attrs_dict.get('colspan', 1))
            self.cell_rowspan = int(attrs_dict.get('rowspan', 1))
        elif tag == 'tr':
            self.current_row = []
    
    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data.strip()
    
    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.in_cell = False
            # Repeat cell for colspan
            for _ in range(self.cell_colspan):
                self.current_row.append(self.current_cell)
        elif tag == 'tr' and self.current_row:
            self.rows.append(self.current_row)

def parse_html_table(content):
    """Parse HTML table with merged headers.
    
    Returns: {year: {canonical_field: value}} dict
    """
    parser = TableParser()
    parser.feed(content)
    
    if not parser.rows:
        raise ValueError("No table rows found in HTML")
    
    # Identify header rows (typically first 1-2 rows)
    # Heuristic: header rows contain non-numeric text
    header_rows = []
    data_rows = []
    for row in parser.rows:
        # Check if row looks like a header (mostly non-numeric)
        numeric_count = sum(1 for cell in row if cell.replace(',', '').replace('.', '').replace('-', '').isdigit())
        if numeric_count < len(row) / 2:
            header_rows.append(row)
        else:
            data_rows.append(row)
    
    if not header_rows:
        raise ValueError("Could not identify header row in HTML table")
    
    # Flatten multi-row header (handle rowspan by repeating cells)
    # For simplicity, use the last header row as the column names
    # (This works for most cases; complex rowspan may need more logic)
    header = header_rows[-1]
    
    # Build column map from header
    column_map = build_column_map(header)
    
    # Parse data rows
    records = {}
    for row in data_rows:
        if len(row) < len(header):
            continue
        
        record = {}
        for canonical, idx in column_map.items():
            if idx < len(row):
                if canonical == 'year':
                    record['year'] = row[idx]
                else:
                    record[canonical] = parse_number(row[idx])
        
        year = record.get('year')
        if year:
            records[year] = {k: v for k, v in record.items() if k != 'year'}
    
    return records
```

---

### 2d. Fixed-Width Text Parser

Fixed-width text has no delimiter. Detect column boundaries from the header
line's word positions.

```python
import re

def parse_fixed_width(content):
    """Parse fixed-width text by detecting column positions from header.
    
    Returns: {year: {canonical_field: value}} dict
    """
    lines = content.strip().split('\n')
    
    # Find header line (first line with multiple words)
    header_line = None
    data_start_idx = 0
    for i, line in enumerate(lines):
        words = line.split()
        if len(words) >= 2:
            # Check if this looks like a header (non-numeric words)
            if not all(w.replace(',', '').replace('.', '').isdigit() for w in words):
                header_line = line
                data_start_idx = i + 1
                break
    
    if header_line is None:
        raise ValueError("Could not find header line in fixed-width text")
    
    # Detect column positions from header
    positions = [(m.start(), m.group()) for m in re.finditer(r'\S+', header_line)]
    col_names = [name for _, name in positions]
    col_starts = [pos for pos, _ in positions]
    col_ends = col_starts[1:] + [len(header_line)]
    
    # Build column map
    column_map = build_column_map(col_names)
    
    # Parse data lines
    records = {}
    for line in lines[data_start_idx:]:
        if not line.strip():
            continue
        
        # Extract values by column position
        values = [line[start:end].strip() for start, end in zip(col_starts, col_ends)]
        
        record = {}
        for canonical, idx in column_map.items():
            if idx < len(values):
                if canonical == 'year':
                    record['year'] = values[idx]
                else:
                    record[canonical] = parse_number(values[idx])
        
        year = record.get('year')
        if year:
            records[year] = {k: v for k, v in record.items() if k != 'year'}
    
    return records
```

---

### 3. Multi-File Join Procedure

When required values live in separate files (e.g., income statement and balance
sheet), join them by fiscal year.

#### Step-by-Step Procedure

1. **Classify files by statement type** during discovery:
   ```python
   def classify_file(content):
       """Determine if file contains income statement or balance sheet data."""
       income_keywords = ['revenue', 'gross profit', 'operating income', 'net income']
       balance_keywords = ['total assets', 'total liabilities', 'equity', 'net assets']
       
       content_lower = content.lower()
       has_income = any(kw in content_lower for kw in income_keywords)
       has_balance = any(kw in content_lower for kw in balance_keywords)
       
       if has_income and has_balance:
           return 'combined'
       elif has_income:
           return 'income'
       elif has_balance:
           return 'balance'
       else:
           return 'unknown'
   ```

2. **Parse each file independently** into `{year: {field: value}}` dicts:
   ```python
   def parse_to_year_dict(filepath):
       """Parse financial file into {year: {canonical_field: value}} dict."""
       # ... (use header detection and column mapping from above)
       result = {}
       for record in records:
           year = record.get('year')
           if year:
               result[year] = {k: v for k, v in record.items() if k != 'year'}
       return result
   ```

3. **Join on fiscal year**:
   ```python
   def join_financial_data(file_dicts):
       """Merge multiple year-keyed dicts into single merged dict.
       
       Args: list of {year: {field: value}} dicts
       Returns: {year: {field: value}} with all fields merged
       """
       merged = {}
       for data_dict in file_dicts:
           for year, fields in data_dict.items():
               if year not in merged:
                   merged[year] = {}
               merged[year].update(fields)
       return merged
   ```

4. **Calculate metrics** from the merged record using canonical field names.

### 4. Financial Metric Calculation

Standard metrics with exact formulas. Use canonical field names from column mapping.

```python
def calculate_metric(merged_data, metric_type):
    """Calculate the specified financial metric for all years.
    
    Args:
        merged_data: {year: {canonical_field: value}} dict
        metric_type: one of 'gross_margin', 'operating_margin', 'net_margin',
                     'return_on_equity', 'year_over_year_growth'
    
    Returns: list of {year: str, value: float} dicts, sorted chronologically
    """
    results = []
    
    # Sort years chronologically (not alphabetically) to handle varied year labels
    for year in sort_years_chronologically(merged_data.keys()):
        fields = merged_data[year]
        
        if metric_type == 'gross_margin':
            # Gross Margin = Gross Profit / Revenue
            numerator = fields.get('gross_profit')
            denominator = fields.get('revenue')
            if numerator is None or denominator is None:
                # Fallback: calculate from revenue - cost_of_revenue
                revenue = fields.get('revenue')
                cogs = fields.get('cost_of_revenue')
                if revenue is not None and cogs is not None:
                    numerator = revenue - cogs
                    denominator = revenue
            
        elif metric_type == 'operating_margin':
            # Operating Margin = Operating Income / Revenue
            numerator = fields.get('operating_income')
            denominator = fields.get('revenue')
            
        elif metric_type == 'net_margin':
            # Net Margin = Net Income / Revenue
            numerator = fields.get('net_income')
            denominator = fields.get('revenue')
            
        elif metric_type == 'return_on_equity':
            # ROE = Net Income / Shareholders' Equity
            numerator = fields.get('net_income')
            denominator = fields.get('total_equity')
            
        elif metric_type == 'year_over_year_growth':
            # YoY Growth requires prior year data
            # Determine which metric to grow (task-specific)
            # Default to revenue growth if not specified
            growth_field = 'revenue'  # Adjust based on task
            current = fields.get(growth_field)
            # Find prior year
            years = sorted(merged_data.keys())
            year_idx = years.index(year)
            if year_idx > 0:
                prior_year = years[year_idx - 1]
                prior = merged_data[prior_year].get(growth_field)
                if current is not None and prior is not None:
                    numerator = current - prior
                    denominator = prior
                else:
                    continue
            else:
                continue  # No prior year for first year
        
        if numerator is not None and denominator is not None and denominator != 0:
            value = (numerator / denominator) * 100
            results.append({'year': year, 'value': value})
    
    return results
```

**Sign conventions:**
- Positive margins indicate profitability
- Negative margins indicate losses
- Growth can be negative (contraction)

### 5. Rounding

**Critical distinction:** Python's built-in `round()` uses **banker's rounding**
(round half to even), not "round half up".

- `round(72.725, 2)` → `72.72` (rounds to even)
- `round(72.735, 2)` → `72.74` (rounds to even)

If the task specifies "round half up" (standard arithmetic rounding):

```python
from decimal import Decimal, ROUND_HALF_UP

def round_half_up(value, decimals=2):
    """Round using 'round half up' rule (standard arithmetic rounding)."""
    d = Decimal(str(value))
    rounded = d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(rounded)
```

**Decision procedure:**
1. Check task specification for rounding instruction
2. If "round half up" or "standard rounding" → use `round_half_up()`
3. If "round" without qualification → use Python's `round()` (banker's rounding)
4. If "round to N decimal places" → adjust quantize target accordingly

**Rounding timing:**
- Round only the final output value, not intermediate calculations
- Use unrounded values for conditional comparisons (e.g., "if margin > 70%")

### 6. Conditional Logic

Tasks may include conditional metric selection:

**Common patterns:**
- "If metric X exceeds threshold T, compute metric A; otherwise compute metric B"
- "If company's metric > industry benchmark, use formula 1; else use formula 2"

**Implementation procedure:**
1. Calculate the condition metric for the specified year (often most recent)
2. Compare against threshold using **unrounded** value
3. Branch to appropriate calculation path
4. Apply the selected metric to ALL required years (not just the condition year)

```python
def apply_conditional_logic(merged_data, condition_spec):
    """
    Args:
        merged_data: {year: {field: value}} dict
        condition_spec: dict with keys:
            - 'condition_metric': metric to evaluate (e.g., 'gross_margin')
            - 'condition_year': year to evaluate (e.g., 'most_recent' or specific year)
            - 'threshold': numeric threshold
            - 'operator': comparison operator ('>', '<', '>=', '<=', '==', '!=')
            - 'if_true': metric to calculate if condition is true
            - 'if_false': metric to calculate if condition is false
    
    Returns: (metric_type, results) tuple
    """
    # Determine condition year
    years = sorted(merged_data.keys())
    if condition_spec['condition_year'] == 'most_recent':
        cond_year = years[-1]
    else:
        cond_year = condition_spec['condition_year']
    
    # Calculate condition metric (unrounded)
    cond_results = calculate_metric(
        {cond_year: merged_data[cond_year]},
        condition_spec['condition_metric']
    )
    cond_value = cond_results[0]['value']
    
    # Evaluate condition
    threshold = condition_spec['threshold']
    op = condition_spec['operator']
    
    if op == '>' and cond_value > threshold:
        selected_metric = condition_spec['if_true']
    elif op == '<' and cond_value < threshold:
        selected_metric = condition_spec['if_true']
    elif op == '>=' and cond_value >= threshold:
        selected_metric = condition_spec['if_true']
    elif op == '<=' and cond_value <= threshold:
        selected_metric = condition_spec['if_true']
    elif op == '==' and cond_value == threshold:
        selected_metric = condition_spec['if_true']
    elif op == '!=' and cond_value != threshold:
        selected_metric = condition_spec['if_true']
    else:
        selected_metric = condition_spec['if_false']
    
    # Calculate selected metric for ALL years
    results = calculate_metric(merged_data, selected_metric)
    
    return selected_metric, results
```

### 7. Output Generation

**Critical:** The `output_contract` axis specifies that column names vary across variants. You must extract the required column names from the task specification, not hardcode them.

#### Extracting Output Column Names from Task

Parse the task instruction to find the required output columns. Look for patterns like:
- "write the results to /app/results.csv with columns: fiscal_year,gross_margin_pct"
- "output columns: year,gm"
- "CSV with headers: fiscal_year,net_margin_pct"

```python
import re

def extract_output_columns(task_instruction):
    """Extract output column names from task instruction.
    
    Returns: list of column names (e.g., ['fiscal_year', 'gross_margin_pct'])
    """
    # Pattern 1: "columns: col1,col2" or "columns: col1, col2"
    match = re.search(r'columns?:\s*([^\n]+)', task_instruction, re.IGNORECASE)
    if match:
        cols_str = match.group(1).strip()
        # Split by comma and clean up
        cols = [c.strip() for c in cols_str.split(',')]
        return cols
    
    # Pattern 2: "with headers: col1,col2"
    match = re.search(r'headers?:\s*([^\n]+)', task_instruction, re.IGNORECASE)
    if match:
        cols_str = match.group(1).strip()
        cols = [c.strip() for c in cols_str.split(',')]
        return cols
    
    # Fallback: use default based on metric (should rarely be needed)
    return None
```

**If column names are not explicitly specified in the task**, use sensible defaults:
- Year column: 'fiscal_year' or 'year'
- Metric column: '{metric_name}_pct' (e.g., 'gross_margin_pct', 'net_margin_pct')

#### Year Normalization for Chronological Sorting

The `schema_and_locale` axis specifies that "year labels" vary. You must normalize years for correct chronological sorting.

```python
def normalize_year(year_str):
    """Normalize year string to a sortable format.
    
    Handles:
    - "FY2022" -> 2022
    - "2022" -> 2022
    - "FY22" -> 2022 (assume 2000s)
    - "Fiscal Year 2022" -> 2022
    - "2022/2023" -> 2022 (use start year)
    
    Returns: int year for sorting
    """
    year_str = str(year_str).strip()
    
    # Extract 4-digit year (don't require word boundaries)
    match = re.search(r'(\d{4})', year_str)
    if match:
        return int(match.group(1))
    
    # Extract 2-digit year and assume 2000s
    match = re.search(r'(\d{2})', year_str)
    if match:
        return 2000 + int(match.group(1))
    
    # Fallback: try to parse as integer
    try:
        return int(year_str)
    except ValueError:
        return 0  # Unknown format, sort first

def sort_years_chronologically(years):
    """Sort year strings in chronological order."""
    return sorted(years, key=normalize_year)
```

**Usage in metric calculation:**
```python
# Instead of: for year in sorted(merged_data.keys()):
for year in sort_years_chronologically(merged_data.keys()):
    # ... calculate metric
```

#### CSV Output

```python
def write_csv_output(results, output_path, column_names, rounding_func=None):
    """Write results to CSV with specified column names.
    
    Args:
        results: list of {year: str, value: float} dicts (already sorted chronologically)
        output_path: file path for output
        column_names: list of column names (extracted from task or defaults)
        rounding_func: optional rounding function (default: no rounding)
    """
    import csv
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(column_names)
        
        for result in results:
            year = result['year']
            value = result['value']
            
            if rounding_func:
                value = rounding_func(value)
            
            # Write as percentage number (72.72), not decimal (0.7272)
            writer.writerow([year, value])
```

**Key requirements:**
- **Extract column names from task specification** (don't hardcode)
- Include ALL requested years, sorted chronologically (use `sort_years_chronologically()`)
- Numeric values without currency symbols or commas
- Percentage values as numbers (72.72), not strings ("72.72%")

## Complete Execution Template

```python
import csv
import re
import os
from decimal import Decimal, ROUND_HALF_UP

# Column alias registry (see Section 2)
COLUMN_ALIASES = { ... }

def main():
    # 1. Discover and classify files
    data_dir = '/app/financials/'
    target_company = 'NVIDIA Corporation'
    
    relevant_files = []
    for filename in os.listdir(data_dir):
        filepath = os.path.join(data_dir, filename)
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            if target_company.lower() in content.lower():
                stmt_type = classify_file(content)
                relevant_files.append((filepath, stmt_type, content))
    
    # 2. Parse each file
    file_dicts = []
    for filepath, stmt_type, content in relevant_files:
        data_dict = parse_to_year_dict(filepath, content)
        file_dicts.append(data_dict)
    
    # 3. Join if multiple files
    if len(file_dicts) == 1:
        merged_data = file_dicts[0]
    else:
        merged_data = join_financial_data(file_dicts)
    
    # 4. Apply conditional logic (if specified)
    # Example: "If most recent year's Gross Margin > 70%, calculate Gross Margin;
    #           otherwise calculate Net Margin"
    condition_spec = {
        'condition_metric': 'gross_margin',
        'condition_year': 'most_recent',
        'threshold': 70,
        'operator': '>',
        'if_true': 'gross_margin',
        'if_false': 'net_margin'
    }
    
    selected_metric, results = apply_conditional_logic(merged_data, condition_spec)
    
    # 5. Extract output column names from task specification
    # (Don't hardcode — output_contract varies across variants)
    output_columns = extract_output_columns(task_instruction)
    if output_columns is None:
        # Fallback defaults
        if selected_metric == 'gross_margin':
            output_columns = ['fiscal_year', 'gross_margin_pct']
        elif selected_metric == 'net_margin':
            output_columns = ['fiscal_year', 'net_margin_pct']
        # ... etc for other metrics
    
    # 6. Write output with appropriate rounding
    output_path = '/app/results.csv'
    
    # Use round_half_up if task requires "round half up"
    # Use Python's round() if task just says "round"
    write_csv_output(results, output_path, output_columns, rounding_func=round_half_up)

if __name__ == '__main__':
    main()
```

## Verification Checklist

Before submitting results:

- [ ] Correct file(s) identified (right company, complete data, correct statement types)
- [ ] Header-based column mapping built (no positional indexing)
- [ ] All required years extracted
- [ ] Multi-file join performed if needed (ROE, etc.)
- [ ] Metric formula applied correctly (numerator/denominator from canonical fields)
- [ ] Conditional logic evaluated on unrounded values
- [ ] Output rounded with correct method (banker's vs round-half-up per task spec)
- [ ] Values expressed as percentages (×100), not decimals
- [ ] Column names match specification exactly
- [ ] File written to correct path
- [ ] All years included in output (not just condition year)

## Example: v01 Task

**Task**: Calculate Gross Margin for NVIDIA Corporation if most recent year > 70%

**Solution steps**:
1. Discovered `financial_summary.dat` contains NVIDIA data (rejected decoys)
2. Detected header row: `Year,Revenue,OperatingIncome,NetIncome,GrossProfit`
3. Built column map: `{year: 0, revenue: 1, operating_income: 2, net_income: 3, gross_profit: 4}`
4. Extracted 5 years of data: FY2022-FY2026
5. Calculated Gross Margin using canonical field names:
   - FY2022: `gross_profit` / `revenue` = 17475/26914 = 64.93%
   - FY2023: 15356/26974 = 56.93%
   - FY2024: 44301/60922 = 72.72%
   - FY2025: 97858/130497 = 74.99%
   - FY2026: 153463/215938 = 71.07%
6. Most recent year (FY2026) = 71.07% > 70% threshold (unrounded comparison)
7. Wrote Gross Margin for ALL years to `/app/results.csv` with `round_half_up()`

**Key learning**: Data was embedded in formatted text with headers/footers. Required content-based file discovery, header detection, and column mapping — not positional indexing.
