---
name: financial-analysis
description: >
  Discover, parse, and compute standard financial metrics from company financial
  data in varied representations (CSV, JSON, fixed-width, HTML), with conditional
  computation logic and structured output. Handles decoy files, multi-statement
  joins, diverse locales, and metric-specific formulas.
---

# Financial Analysis Skill

## Overview

This skill solves tasks that require:
1. Finding the correct financial data file(s) among potentially many candidates
2. Parsing financial statements in varied formats and schemas
3. Computing standard financial metrics with correct formulas
4. Applying conditional logic to determine which metric to output
5. Writing results in a specified output format

## Quick Execution Recipe

**CRITICAL: Follow these steps exactly. Do NOT write ad-hoc parsers.**

### Step 1: Discover the correct file
```python
for fname in os.listdir(data_dir):
    content = open(fpath).read()
    if company_name.lower() in content.lower() and has_financial_keywords(content):
        correct_file = fpath
```

### Step 2: Extract data block (DO NOT hardcode header strings)
```python
header_fields, data_rows = extract_data_block(content)
# This function auto-detects delimiter, handles CSV quotes, matches multi-language headers
# NEVER use: if line.startswith('Year,')  ← breaks on "Fiscal Year," or "Jahr,"
```

### Step 3: Parse records with locale detection
```python
records = parse_records(header_fields, data_rows)
# Auto-detects English vs European numeric locale
# NEVER use: val.replace(',', '')  ← breaks European "1.234.567,89"
```

### Step 4: Find fields (use normalized names, no spaces)
```python
rev_field = find_field(records, ['revenue', 'totalrevenue', 'sales', 'umsatz'])
gp_field = find_field(records, ['grossprofit', 'bruttogewinn', 'margebrute'])
ni_field = find_field(records, ['netincome', 'netprofit', 'nettogewinn'])
year_field = find_field(records, ['year', 'fiscalyear', 'jahr', 'año', 'année'])
```

### Step 5: Sort by year, compute metric, apply conditional
```python
records.sort(key=lambda r: int(re.findall(r'\d+', str(r[year_field]))[0]))
most_recent_gm = (records[-1][gp_field] / records[-1][rev_field]) * 100
if round(most_recent_gm, 2) > threshold:
    metric_field = gp_field  # or ni_field, oi_field, etc.
```

### Step 6: Write output with exact column names from spec
```python
with open(output_path, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['fiscal_year', 'gross_margin_pct'])  # or as specified
    for rec in records:
        value = (rec[metric_field] / rec[rev_field]) * 100
        writer.writerow([rec[year_field], round(value, 2)])
```

**Common mistakes that cause failures:**
- Hardcoding `if line.startswith('Year,')` → breaks on variant headers
- Using `val.replace(',', '')` → breaks European locale
- Not using `extract_data_block()` → misses embedded data, breaks on quotes
- Using field names with spaces like `'gross profit'` → keys are normalized to `'grossprofit'`

## Phase 1: Data Discovery

### Strategy
- List all files in the specified data directory
- Examine each file's content to identify the correct one(s)
- The correct file matches the target **company name** and contains **structured financial data** (revenue, profit, income figures)
- Decoy files may include: unrelated companies, product-level sales data, log/cache files, quarterly data when annual is needed

### Identification Heuristics (ordered by reliability)
1. **Company name match**: Look for the exact company name or ticker in headers/metadata
2. **Financial statement structure**: Presence of rows with Revenue, Gross Profit, Net Income, etc.
3. **Annual vs. quarterly**: Check if the task requires annual data; reject quarterly-only files
4. **Data completeness**: The correct file should have all fields needed for the requested metric
5. **File format awareness**: `.dat` files may contain CSV, fixed-width, or formatted text — always inspect content

### Multi-file Scenarios (statement_topology variation)
- If data spans multiple files (e.g., income statement + balance sheet), join them on **fiscal year**
- Ensure consistent year labeling across files before joining
- Watch for fiscal year end conventions (e.g., "FY2026" ending in January 2026)

## Phase 2: Data Parsing

### Format Detection
Examine the file to determine its structure:

| Format | Indicators | Parsing Approach |
|--------|-----------|-----------------|
| CSV | Comma-separated, header row | `csv.DictReader` or `csv.reader` |
| Semicolon CSV | Semicolon-separated (common in European locales where comma is decimal) | `csv.reader(f, delimiter=';')` |
| Fixed-width | Aligned columns, no delimiters | Detect column positions from header, use `pandas.read_fwf` |
| Nested JSON | `{` `}` structure, nested keys | `json.load()`, navigate to data arrays |
| HTML table | `<table>`, `<tr>`, `<td>` tags | `pandas.read_html()` or regex extraction |
| Embedded data | Headers/footers around data block | Use `extract_data_block()` then parse the data portion |

**Delimiter detection**: The `detect_delimiter()` function auto-detects comma, semicolon, tab, or pipe by checking which character appears most consistently across lines. European CSV files often use semicolons because commas are decimal separators.

### Schema Normalization
Field labels vary across locales and conventions. Build a mapping from observed labels to canonical names:

| Canonical Field | Common Labels / Variants |
|----------------|------------------------|
| fiscal_year | Year, FY, Fiscal Year, Année, Jahr, 年度, "FY2024", "2024" |
| revenue | Revenue, Total Revenue, Sales, Net Sales, Umsatz, 売上高 |
| gross_profit | Gross Profit, GP, Bruttogewinn, 粗利益 |
| operating_income | Operating Income, OI, EBIT, Operating Profit, Betriebsergebnis |
| net_income | Net Income, NI, Net Profit, Profit After Tax, Nettogewinn |
| shareholders_equity | Shareholders' Equity, Total Equity, Stockholders' Equity, Book Value, Eigenkapital |
| cost_of_revenue | Cost of Revenue, COGS, Cost of Goods Sold, Cost of Sales |

### Numeric Parsing
- **CRITICAL: Detect locale convention BEFORE parsing.** Never blindly strip commas.
  - English: `1,234,567.89` (comma = thousands, dot = decimal)
  - European: `1.234.567,89` (dot = thousands, comma = decimal)
  - Detection heuristic: if the LAST separator character in a value is a comma → European; if dot → English
  - Apply the detected locale consistently to all numeric fields
- Strip currency symbols (`$`, `€`, `¥`, etc.)
- Handle suffixes: `M` = millions, `B` = billions, `K` = thousands
- Convert all values to a consistent unit before computing ratios
- If values are already in millions, ratios are unaffected by the unit (both numerator and denominator scale equally)

### Year Extraction
- Normalize year labels: "FY2024" → keep as-is for output, but understand it means fiscal year 2024
- Sort years chronologically for determining "most recent"
- Watch for non-standard fiscal year naming (e.g., "2023-24" or "FY ended Jan 2024")

## Phase 3: Financial Metric Computation

### Metric Formulas

All metrics are expressed as **percentages** (multiply ratio by 100), rounded to the specified decimal places.

| Metric | Formula | Notes |
|--------|---------|-------|
| **Gross Margin** | (Gross Profit / Revenue) × 100 | Also: 1 - (COGS / Revenue) |
| **Operating Margin** | (Operating Income / Revenue) × 100 | Uses EBIT / Operating Profit |
| **Net Margin** | (Net Income / Revenue) × 100 | Bottom-line profitability |
| **Return on Equity** | (Net Income / Shareholders' Equity) × 100 | Uses average equity if multiple points available |
| **Year-over-Year Growth** | ((Current - Previous) / |Previous|) × 100 | Applied to any base metric; sign matters |

### Rounding
- Round to the specified number of decimal places (default: 2)
- Use standard rounding (Python `round()` or equivalent)
- Output as percentage numbers (e.g., 72.72 means 72.72%, NOT 0.7272)

### Sign Conventions
- Positive margin = profitable
- Negative margin = loss
- Growth can be negative (decline)
- Maintain sign in output; do not take absolute values of the final result

## Phase 4: Conditional Logic

Tasks may include conditional branches. Common patterns:

1. **Threshold-based metric selection**: "If metric X > threshold, compute X for all years; otherwise compute Y"
   - Compute the specified metric for the most recent year first
   - Compare against threshold
   - Branch to compute the appropriate metric for all years

2. **Data-dependent output**: "If data exists for metric X, use it; otherwise fall back to Y"

### Implementation Pattern
```python
# 1. Parse all data
# 2. Compute the primary metric for the most recent year
most_recent_value = compute_metric(most_recent_year_data, primary_metric)

# 3. Apply conditional
if most_recent_value > threshold:
    metric_to_compute = primary_metric
else:
    metric_to_compute = fallback_metric

# 4. Compute for all years and write output
results = []
for year in all_years:
    value = compute_metric(year_data, metric_to_compute)
    results.append((year, round(value, decimal_places)))
write_output(results)
```

## Phase 5: Output Generation

### Output Format
- Read the task specification carefully for required column names and file path
- Common output: CSV with columns like `fiscal_year,gross_margin_pct`
- Ensure the file is written to the exact specified path

### Output Validation
- Verify all required years are present
- Verify values are percentages (not decimals)
- Verify rounding is correct
- Verify column names match specification exactly

## Complete Algorithm (Pseudocode)

```
1. DISCOVER: List files in data directory → identify correct file(s) by company name + financial structure
2. PARSE: Read file → detect format → extract rows → normalize field names → parse numeric values
3. IDENTIFY: Determine fiscal years, sort chronologically
4. COMPUTE PRIMARY: Calculate the primary metric for the most recent year
5. CONDITION: Check threshold/condition → determine which metric to output
6. COMPUTE ALL: Calculate the chosen metric for all years
7. OUTPUT: Write results to specified file in required format with correct column names
```

## Python Implementation Template

```python
import csv
import io
import json
import os
import re

def discover_financial_file(directory, company_name):
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
    # Filter: must contain financial keywords (multi-language)
    financial_keywords = [
        # English
        'revenue', 'gross profit', 'net income', 'operating income',
        'grossprofit', 'netincome', 'operatingincome',
        # German
        'umsatz', 'bruttogewinn', 'nettogewinn', 'betriebsergebnis',
        # French
        'chiffre daffaires', 'résultat net', 'marge brute',
        # Spanish
        'ingresos', 'beneficio neto',
    ]
    for fpath, content in candidates:
        lower_content = content.lower()
        if any(kw in lower_content for kw in financial_keywords):
            return fpath, content
    return None, content

def detect_delimiter(content):
    """Detect the field delimiter: comma, semicolon, tab, or pipe."""
    lines = [l.strip() for l in content.split('\n') 
             if l.strip() and not l.strip().startswith('=')]
    candidates = [',', ';', '\t', '|']
    best_delim = ','
    best_score = 0
    for delim in candidates:
        counts = {}
        for line in lines[:20]:
            n = line.count(delim)
            if n > 0:
                counts[n] = counts.get(n, 0) + 1
        if counts:
            max_count_freq = max(counts.values())
            if max_count_freq > best_score:
                best_score = max_count_freq
                best_delim = delim
    return best_delim

def extract_data_block(content):
    """
    CRITICAL: Robustly find and extract the tabular data block from mixed-format text.
    
    Two-tier header detection:
    1. Vocabulary matching (multi-language financial terms)
    2. Structural fallback (language-agnostic CSV pattern detection)
    
    Uses csv.reader for proper quote handling (European values like "89.000,5"
    contain commas inside quotes that must not be treated as field separators).
    
    Files often mix metadata/decorations with actual data. Do NOT assume:
    - Data starts at line 0 (there may be headers/footers)
    - Year labels start with digits ("FY2022" starts with 'F')
    - Header has a specific string ("Year" vs "Fiscal Year" vs "Année" vs "Jahr")
    - Values are unquoted (European CSV often quotes numbers with decimal commas)
    """
    delimiter = detect_delimiter(content)
    lines = content.split('\n')
    
    # Multi-language financial vocabulary (normalized, no spaces)
    financial_tokens = {
        # English
        'year', 'revenue', 'grossprofit', 'gross profit', 'netincome', 'net income',
        'operatingincome', 'operating income', 'totalrevenue', 'total revenue',
        'sales', 'fiscalyear', 'fiscal year', 'costofrevenue', 'cost of revenue',
        'operatingprofit', 'operating profit', 'shareholdersequity',
        'shareholders equity', 'totalequity', 'total equity',
        'stockholdersequity', 'stockholders equity', 'netprofit', 'net profit',
        # German
        'jahr', 'umsatz', 'bruttogewinn', 'nettogewinn', 'betriebsergebnis',
        'eigenkapital', 'gewinn', 'erlöse', 'jahresüberschuss',
        # French
        'année', 'chiffredaffaires', 'résultatnet', 'margebrute',
        # Spanish
        'año', 'ingresos', 'beneficioneto', 'patrimonio',
    }
    
    def try_extract_from_header(header_line_idx, header_fields_raw):
        """Given a header at a specific line, extract data rows using csv.reader."""
        header_fields = [f.strip().lower() for f in header_fields_raw]
        n_fields = len(header_fields)
        data_rows = []
        remaining_text = '\n'.join(lines[header_line_idx + 1:])
        reader = csv.reader(io.StringIO(remaining_text), delimiter=delimiter)
        for parsed_row in reader:
            parsed_row = [f.strip() for f in parsed_row]
            if not parsed_row or all(f == '' for f in parsed_row):
                continue
            first = parsed_row[0] if parsed_row else ''
            if first.startswith('=') or first.startswith('-') or first.upper().startswith('NOTE'):
                break
            if len(parsed_row) == n_fields:
                data_rows.append(parsed_row)
            else:
                if data_rows:
                    break
                continue
        return header_fields, data_rows if data_rows else None
    
    # Tier 1: Vocabulary matching
    for i, line in enumerate(lines):
        stripped = line.strip()
        if delimiter not in stripped:
            continue
        parsed = next(csv.reader(io.StringIO(stripped), delimiter=delimiter))
        tokens_norm = [t.strip().lower().replace(' ', '') for t in parsed]
        matches = sum(1 for t in tokens_norm if t in financial_tokens)
        if matches >= 2:
            result = try_extract_from_header(i, parsed)
            if result[1]:
                return result
    
    # Tier 2: Structural fallback (language-agnostic)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if delimiter not in stripped:
            continue
        parsed = next(csv.reader(io.StringIO(stripped), delimiter=delimiter), None)
        if parsed is None or len(parsed) < 2:
            continue
        # Header: mostly alphabetic tokens (not numbers)
        alpha_count = sum(1 for t in parsed if t and not re.match(r'^[\d.,;$€£¥"\'\t| ]+$', t))
        if alpha_count < len(parsed) * 0.5:
            continue
        result = try_extract_from_header(i, parsed)
        if result[1]:
            return result
    
    return None, None

def detect_numeric_locale(sample_values):
    """
    Determine whether values use English or European numeric convention.
    
    English:  1,234,567.89  (comma = thousands, dot = decimal)
    European: 1.234.567,89  (dot = thousands, comma = decimal)
    
    Heuristic: if the LAST separator in a value is a comma, it's the decimal mark (European).
    If the last separator is a dot, it's the decimal mark (English).
    """
    for val in sample_values:
        val = str(val).strip()
        last_comma = val.rfind(',')
        last_dot = val.rfind('.')
        if last_comma > last_dot and last_comma >= 0:
            return 'european'  # comma is decimal separator
        elif last_dot > last_comma and last_dot >= 0:
            return 'english'
    return 'english'  # default when no separators found

def parse_numeric_locale_aware(value_str, locale='english'):
    """
    Parse a numeric string respecting the detected locale convention.
    Handles currency symbols, thousands separators, and M/B/K suffixes.
    """
    s = str(value_str).strip()
    s = re.sub(r'[$€£¥]', '', s)
    
    # Handle suffixes (M, B, K) — strip before locale processing
    multiplier = 1
    if s and s[-1].upper() in ('M', 'B', 'K'):
        suffix = s[-1].upper()
        s = s[:-1].strip()
        multiplier = {'M': 1_000_000, 'B': 1_000_000_000, 'K': 1_000}[suffix]
    
    if locale == 'european':
        s = s.replace('.', '')      # dots are thousands separators
        s = s.replace(',', '.')     # comma is decimal mark
    else:
        s = s.replace(',', '')      # commas are thousands separators
    
    return float(s) * multiplier

def parse_records(header_fields, data_rows, locale=None):
    """
    Convert raw header + data rows into list of dicts with numeric conversion.
    Handles field name variations by normalizing to lowercase no-space keys.
    
    If locale is None, auto-detect from numeric values in the data.
    """
    # Normalize header field names for matching
    normalized_headers = [h.strip().lower().replace(' ', '') for h in header_fields]
    
    # Auto-detect locale if not specified
    if locale is None:
        # Sample values from all columns (skip first column which is typically year)
        sample_vals = []
        for row in data_rows:
            for val in row[1:]:  # skip year column
                v = val.strip()
                if v and any(c in v for c in ',.$€£¥'):
                    sample_vals.append(v)
        locale = detect_numeric_locale(sample_vals) if sample_vals else 'english'
    
    records = []
    for row in data_rows:
        rec = {}
        for norm_h, raw_h, val in zip(normalized_headers, header_fields, row):
            val = val.strip()
            # Try numeric conversion with locale awareness
            try:
                rec[norm_h] = parse_numeric_locale_aware(val, locale)
            except (ValueError, IndexError):
                rec[norm_h] = val  # Keep as string (e.g., year label)
        records.append(rec)
    return records

def find_field(records, candidates):
    """
    Find which normalized field name is used in the data.
    IMPORTANT: candidates must be in normalized form (lowercase, no spaces)
    because record keys are normalized by parse_records().
    Example: use 'grossprofit' not 'gross profit'.
    """
    if not records:
        return None
    keys = set(records[0].keys())
    for c in candidates:
        if c in keys:
            return c
    return None

def compute_metric(numerator, denominator):
    """Compute a margin/return metric as a percentage."""
    if denominator == 0:
        return 0.0
    return (numerator / denominator) * 100

def write_csv_output(filepath, results, column_names):
    """Write results to CSV."""
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(column_names)
        for row in results:
            writer.writerow(row)

# ============================================================
# Complete pipeline usage:
# ============================================================
# 1. DISCOVER
#    fpath, content = discover_financial_file(data_dir, company_name)
#
# 2. PARSE (robust embedded-data extraction + locale detection)
#    header_fields, data_rows = extract_data_block(content)
#    records = parse_records(header_fields, data_rows)  # auto-detects locale
#    # Or explicitly: records = parse_records(header_fields, data_rows, locale='european')
#
# 3. IDENTIFY FIELDS (use normalized names without spaces)
#    rev_field = find_field(records, ['revenue', 'totalrevenue', 'sales', 'umsatz'])
#    gp_field  = find_field(records, ['grossprofit', 'bruttogewinn', 'margebrute'])
#    ni_field  = find_field(records, ['netincome', 'netprofit', 'nettogewinn'])
#    oi_field  = find_field(records, ['operatingincome', 'operatingprofit', 'betriebsergebnis'])
#    eq_field  = find_field(records, ['shareholdersequity', 'totalequity', 'eigenkapital'])
#    year_field = find_field(records, ['year', 'fiscalyear', 'jahr', 'año', 'année'])
#
# 4. SORT BY YEAR
#    records.sort(key=lambda r: int(re.findall(r'\d+', str(r[year_field]))[0]))
#
# 5. COMPUTE + CONDITIONAL
#    most_recent_gm = compute_metric(records[-1][gp_field], records[-1][rev_field])
#    if round(most_recent_gm, 2) > threshold:
#        metric = 'gross_margin'
#    else:
#        metric = 'net_margin'
#
# 6. OUTPUT
#    results = [(r[year_field], round(compute_metric(r[num_field], r[den_field]), 2)) for r in records]
#    write_csv_output(output_path, results, output_columns)
```

## Key Pitfalls to Avoid

1. **Decoy files**: Always verify company name AND financial data structure. Files may look financial (contain revenue numbers) but be for the wrong company, or be quarterly when annual is needed.
2. **Embedded data extraction**: Files often mix metadata, decorative separators (=== lines), and footers with the actual data table. Use vocabulary-based header detection + field-count validation for data rows. Do NOT assume data starts at line 0 or that year labels start with digits ("FY2022" starts with 'F', not a digit — a `line[0].isdigit()` check will silently skip all rows).
3. **Header detection by content, not exact string**: The header might say "Year", "Fiscal Year", "Année", "Jahr", or "年度". Match by checking if ≥2 tokens match a financial vocabulary set.
4. **Data row validation by field count**: A valid data row has the same number of comma-separated fields as the header. This is more robust than checking if the first character is a digit.
5. **Unit inconsistency**: If some values are in millions and others in absolute, normalize first. (Ratios are unaffected if both numerator and denominator share the same unit.)
6. **Fiscal year ordering**: "Most recent" means chronologically latest. Extract the numeric year from labels like "FY2026" for proper sorting.
7. **Percentage vs decimal**: Output 72.72, not 0.7272. The task explicitly says "percentage numbers."
8. **Rounding timing**: Round only at the final output step, not intermediate calculations. The threshold comparison should use the rounded value.
9. **Column name matching**: Output column names must match specification exactly (e.g., `fiscal_year,gross_margin_pct`).
10. **Missing data**: Handle cases where a field might be absent for some years.
11. **Compound field names without spaces**: Headers like "GrossProfit" (no space) vs "Gross Profit" (with space) — normalize by removing spaces before matching.
12. **European numeric locale**: `1.234.567,89` means 1,234,567.89 in European convention. Never blindly strip commas — detect the convention first by checking whether the last separator is a comma (European decimal) or dot (English decimal). A wrong locale assumption can produce values off by a factor of 1,000,000. The `detect_numeric_locale()` function examines sample values to determine the convention before any parsing occurs.
13. **CSV quoting with European decimals**: European CSV files often quote values containing decimal commas: `"89.000,5"`. A naive `split(',')` will break these into multiple fields. Always use `csv.reader` to parse data rows, which correctly handles quoted fields.
14. **Multi-language headers**: Field labels may be in German (Jahr, Umsatz, Bruttogewinn), French (Année, Chiffre d'affaires), Spanish (Año, Ingresos), etc. The vocabulary set should include common financial terms in multiple languages. As a fallback, use structural detection: a header line is mostly alphabetic tokens followed by data rows with matching field counts.
15. **Delimiter auto-detection**: Files may use comma, semicolon, tab, or pipe as field delimiters. European CSV files often use semicolons because commas are decimal separators. The `detect_delimiter()` function auto-detects the delimiter by checking which character appears most consistently across lines. Never hardcode a delimiter assumption.
