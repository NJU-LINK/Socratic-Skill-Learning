---
name: financial-analysis
description: >
  Reusable agent skill for discovering, parsing, and computing standard
  financial metrics (gross margin, operating margin, net margin, return on
  equity, year-over-year growth) from heterogeneous financial data sources.
  Handles content-based file discovery among decoys, multi-format parsing
  (CSV, JSON, fixed-width, HTML), single- and cross-statement topologies,
  conditional computation branching, and output contract matching.
---

# Financial Analysis Skill

## Overview

This skill solves tasks that require:
1. Finding the correct financial data file(s) in a directory that may contain decoys
2. Parsing financial statements from varied formats and locales
3. Computing one or more standard financial metrics
4. Applying conditional logic (e.g., threshold-based branching between metrics)
5. Writing results in a specified output format

---

## Quick-Start Template

Copy and adapt this template for standard single-statement tasks. Only the **CONFIGURATION** section needs changing per task variant.

```python
import csv, json, os, re
from pathlib import Path

# === CONFIGURATION (change these for each task) ===
DATA_DIR = "/app/financials"          # from task instruction
TARGET_COMPANY = "NVIDIA Corporation" # from task instruction  
METRIC = "gross_margin"               # gross_margin|operating_margin|net_margin|return_on_equity|year_over_year_growth
THRESHOLD = 70.0                      # from conditional logic in task (None if no condition)
FALLBACK_METRIC = "net_margin"        # metric to use if threshold not met
OUTPUT_PATH = "/app/results.csv"      # from task instruction
OUTPUT_COLUMNS = ["fiscal_year", "gross_margin_pct"]  # from task instruction

# === STEP 1: DISCOVER FILE ===
# Score each file: +10 company match, +2 per financial keyword, +5 year labels
# -15 log prefixes, -20 product data, -30 wrong company, -10 quarterly-only
best_file, best_score = None, -999
for entry in os.listdir(DATA_DIR):
    fp = os.path.join(DATA_DIR, entry)
    if not os.path.isfile(fp):
        continue
    content = open(fp, 'r', errors='ignore').read(5000)
    cl = content.lower()
    score = 0
    if TARGET_COMPANY.lower() in cl:
        score += 10
    for kw in ['revenue','gross profit','net income','operating income','total equity','shareholders equity']:
        if kw in cl:
            score += 2
    if re.search(r'FY\d{4}|FY\s*\d{4}|\b(19|20)\d{2}\b', content):
        score += 5
    if any(p in content for p in ['[INFO]','[WARN]','[ERROR]','[DATA]']):
        score -= 15
    if sum(1 for k in ['product','units','sku'] if k in cl) >= 2:
        score -= 20
    if score > best_score:
        best_file, best_score = fp, score

# === STEP 2: PARSE (auto-detect CSV/JSON/fixed-width) ===
def normalize_numeric(v):
    s = str(v).strip()
    if not s or s in ('-','—','N/A','n/a','null','None',''):
        return None
    s = re.sub(r'[$€£¥₹]', '', s)
    neg = s.startswith('(') and s.endswith(')')
    if neg:
        s = s[1:-1]
    mult = 1.0
    su = s.upper().strip()
    if su.endswith('M') or 'MILLION' in su:
        mult, s = 1e6, re.sub(r'[Mm]\s*$|[Mm]illion','',s,flags=re.I).strip()
    elif su.endswith('B') or 'BILLION' in su:
        mult, s = 1e9, re.sub(r'[Bb]\s*$|[Bb]illion','',s,flags=re.I).strip()
    elif su.endswith('K') or 'THOUSAND' in su:
        mult, s = 1e3, re.sub(r'[Kk]\s*$|[Tt]housand','',s,flags=re.I).strip()
    # CRITICAL: European format BEFORE removing commas
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.','').replace(',','.')
        else:
            s = s.replace(',','')
    elif ',' in s and '.' not in s:
        parts = s.split(',')
        if len(parts)==2 and len(parts[1])<=2:
            s = s.replace(',','.')
        else:
            s = s.replace(',','')
    s = s.replace(' ','')
    try:
        r = float(s)*mult
        return -r if neg else r
    except ValueError:
        return None

with open(best_file,'r',errors='ignore') as f:
    raw = f.read()
lines = raw.strip().split('\n')
# Find header row: contains 'year'/'fy' AND a financial term
hdr_idx = next(i for i,l in enumerate(lines) 
    if re.search(r'\b(year|fiscal|fy)\b',l.lower()) 
    and any(k in l.lower() for k in ['revenue','profit','income','equity']))
hdr = lines[hdr_idx].strip()
# Detect delimiter
if ',' in hdr:
    sep = ','
elif '\t' in hdr:
    sep = '\t'
else:
    sep = None
headers = [h.strip() for h in (hdr.split(sep) if sep else re.split(r'\s{2,}',hdr))]
# Parse data rows
records = []
for line in lines[hdr_idx+1:]:
    ls = line.strip()
    if not ls or re.match(r'^[=\-]+$',ls) or ls.startswith('NOTE') or ls.startswith('#'):
        continue
    vals = [v.strip() for v in (ls.split(sep) if sep else re.split(r'\s{2,}',ls))]
    if len(vals) >= 2:
        records.append(dict(zip(headers,vals)))

# === STEP 3: NORMALIZE FIELDS ===
ALIASES = {
    'revenue':['revenue','total revenue','net sales','sales','turnover'],
    'gross_profit':['gross profit','grossprofit','bruttogewinn'],
    'operating_income':['operating income','operatingincome','ebit','operating profit'],
    'net_income':['net income','netincome','net profit','net earnings'],
    'shareholders_equity':['shareholders equity','total equity','stockholders equity','book value'],
}
def camel_split(n):
    return re.sub(r'([a-z])([A-Z])',r'\1 \2',re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1 \2',n)).lower().strip()
def map_field(name):
    for canon,als in ALIASES.items():
        for a in als:
            if name.lower().strip()==a or camel_split(name)==a or name.lower().replace('_',' ')==a:
                return canon
            if name.lower().replace(' ','')==a.replace(' ',''):
                return canon
    if re.search(r'\b(year|fiscal|fy)\b',name.lower()):
        return 'fiscal_year'
    return None

norm = []
for r in records:
    nr = {}
    for k,v in r.items():
        c = map_field(k)
        if c=='fiscal_year':
            nr[c] = str(v).strip()
        elif c:
            n = normalize_numeric(v)
            if n is not None:
                nr[c] = n
        else:
            nr[k] = v
    norm.append(nr)

# === STEP 4: COMPUTE METRIC ===
def compute(records, metric):
    results = []
    for i,r in enumerate(records):
        yr = r.get('fiscal_year','unknown')
        rev = r.get('revenue',0)
        if metric=='gross_margin' and 'gross_profit' in r and rev:
            results.append((yr, round(r['gross_profit']/rev*100,2)))
        elif metric=='operating_margin' and 'operating_income' in r and rev:
            results.append((yr, round(r['operating_income']/rev*100,2)))
        elif metric=='net_margin' and 'net_income' in r and rev:
            results.append((yr, round(r['net_income']/rev*100,2)))
        elif metric=='return_on_equity' and 'net_income' in r and 'shareholders_equity' in r:
            eq = r['shareholders_equity']
            avg = (eq+records[i-1]['shareholders_equity'])/2 if i>0 and 'shareholders_equity' in records[i-1] else eq
            if avg:
                results.append((yr, round(r['net_income']/avg*100,2)))
        elif metric=='year_over_year_growth' and 'revenue' in r:
            if i==0 or 'revenue' not in records[i-1] or records[i-1]['revenue']==0:
                results.append((yr, None))
            else:
                results.append((yr, round((r['revenue']-records[i-1]['revenue'])/records[i-1]['revenue']*100,2)))
    return results

results = compute(norm, METRIC)

# === STEP 5: CONDITIONAL BRANCHING ===
if THRESHOLD is not None and FALLBACK_METRIC:
    latest = results[-1][1] if results else None
    if latest is not None and latest > THRESHOLD:
        pass  # keep primary results
    else:
        METRIC = FALLBACK_METRIC
        results = compute(norm, METRIC)
        # Update output columns for fallback metric
        OUTPUT_COLUMNS = [OUTPUT_COLUMNS[0], METRIC + '_pct']

# === STEP 6: WRITE OUTPUT ===
with open(OUTPUT_PATH, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(OUTPUT_COLUMNS)
    for yr, val in results:
        w.writerow([yr, val if val is not None else ''])
```

### Why This Template Matters

1. **The eval agent writes ad-hoc code every time** — your pipeline script is never imported. This template IS the pipeline, inline, so the agent gets tested code without needing to import.
2. **Only 5 CONFIGURATION lines need changing** per task variant — the agent doesn't re-implement algorithms, it just configures.
3. **European format handling is baked in** — the most common bug (comma handling order) is already correct.
4. **camelCase splitting is included** — the `camel_split` function handles `GrossProfit` → `gross profit`.

### Alternative: CLI Invocation

For agents that prefer shell commands, the pipeline script supports argparse:

```bash
python3 scripts/financial_pipeline.py \
    --data-dir /app/financials \
    --company "NVIDIA Corporation" \
    --metric gross_margin \
    --threshold 70 \
    --fallback-metric net_margin \
    --output /app/results.csv \
    --columns fiscal_year gross_margin_pct
```

---

## 1. Content-Based File Discovery

When given a directory of files and asked to find financial data for a specific company:

### Algorithm

```
function discover_financial_file(directory, target_company):
    candidates = []
    for each file in directory:
        content = read_preview(file, max_lines=50)
        
        # Score each file on relevance
        score = 0
        
        # (a) Company match: does the file mention the target company name or ticker?
        if target_company.name in content OR target_company.ticker in content:
            score += 10
        
        # (b) Financial field presence: does it contain needed financial terms?
        financial_keywords = [Revenue, Gross Profit, Net Income, Operating Income,
                             Total Assets, Shareholders Equity, Total Equity]
        matched_keywords = count_matches(content, financial_keywords)
        score += matched_keywords * 2
        
        # (c) Annual structure: does it have year-labeled rows (FY20XX, 20XX, etc.)?
        if contains_year_labels(content):
            score += 5
        
        # (d) Reject known decoy patterns
        if is_product_level_data(content):    # e.g., product SKUs, unit counts
            score -= 20
        if is_cache_or_log_file(content):     # e.g., [INFO], [WARN], cache headers
            score -= 15
        if is_different_company(content):     # mentions another company prominently
            score -= 30
        if is_quarterly_only(content):        # only quarterly, not annual data
            score -= 10  # unless task asks for quarterly
        
        candidates.append((file, score))
    
    return sorted(candidates, key=score, reverse=True)[0]
```

### Decoy Rejection Heuristics

| Decoy Pattern | Detection |
|---------------|-----------|
| Product-level data | Contains SKU/product names, unit counts, per-product rows |
| Cache/log files | Contains `[INFO]`, `[WARN]`, `[DATA]` log prefixes |
| Different company | Company name/ticker doesn't match target |
| Quarterly-only data | Only Q1/Q2/Q3/Q4 labels, no annual totals |
| Aggregated summaries | Contains computed ratios but not raw statement data |

---

## 2. Format Detection and Parsing

### Format Detection

Detect the file format from extension and content:

| Indicator | Format | Parser |
|-----------|--------|--------|
| `.csv` extension or comma-delimited header row | CSV | `csv.DictReader` or `pandas.read_csv` |
| `.json` extension or starts with `{`/`[` | JSON | `json.load`, walk keys for statement arrays |
| `.dat`/`.txt` with aligned columns, `=====` borders | Fixed-width text | Split on 2+ spaces after finding header row |
| `.html` or contains `<table` | HTML | `pandas.read_html` or BeautifulSoup |

### Parsing Pipeline

```
function parse_financial_file(filepath):
    format = detect_format(filepath)
    
    if format == CSV:
        rows = parse_csv(filepath)
    elif format == JSON:
        rows = parse_json_financial(filepath)
    elif format == FIXED_WIDTH:
        rows = parse_fixed_width(filepath)
    elif format == HTML:
        rows = parse_html_tables(filepath)
    
    # Normalize the parsed data
    return normalize_financial_data(rows)
```

### Numeric Normalization

Financial data uses varied numeric formats. **Critical: handle European format BEFORE removing commas**, otherwise "1.234,56" becomes 1.23456 instead of 1234.56.

```
function normalize_numeric(value_string):
    s = value_string.strip()
    s = remove_currency_symbols(s)  # $, €, £, ¥, ₹
    
    # Handle negative in parentheses: (1,234) -> -1234
    is_negative = False
    if s.startswith('(') and s.endswith(')'):
        is_negative = True
        s = s[1:-1]
    
    # Handle scale suffixes BEFORE removing separators
    multiplier = 1
    if s.upper().endswith('M') or 'million' in s.lower():
        multiplier = 1_000_000
        s = remove_suffix(s, 'M/million')
    elif s.upper().endswith('B') or 'billion' in s.lower():
        multiplier = 1_000_000_000
        s = remove_suffix(s, 'B/billion')
    elif s.upper().endswith('K') or 'thousand' in s.lower():
        multiplier = 1_000
        s = remove_suffix(s, 'K/thousand')
    
    # CRITICAL: Handle European decimal format BEFORE removing commas
    # European: "1.234,56" -> 1234.56 (period=thousands, comma=decimal)
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):  # European format
            s = s.replace('.', '').replace(',', '.')
        else:  # Standard format
            s = s.replace(',', '')
    elif ',' in s and '.' not in s:
        # Ambiguous: "1234,56" (European decimal) or "1,234" (thousands)
        # Heuristic: if digits after comma <= 2, treat as decimal
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    
    # Remove any remaining space thousands separators
    s = s.replace(' ', '')
    
    result = float(s) * multiplier
    return -result if is_negative else result
```

### Fixed-Width Text Parsing

For files with `=====` borders and aligned columns:

```
function parse_fixed_width(filepath):
    lines = read_lines(filepath)
    
    # Find the header row: look for a line containing column names
    # like "Year,Revenue,..." or "Year  Revenue  ..."
    header_idx = None
    for i, line in enumerate(lines):
        if contains_financial_headers(line):  # "Year" AND at least one financial field
            header_idx = i
            break
    
    if header_idx is None:
        raise ValueError("Cannot find data header")
    
    header_line = lines[header_idx]
    # Detect delimiter: comma, 2+ spaces, or tab
    if ',' in header_line:
        delimiter = ','
    elif '\t' in header_line:
        delimiter = '\t'
    else:
        delimiter = r'\s{2,}'  # 2+ spaces
    
    headers = split(header_line, delimiter)
    
    # Parse data rows after header (skip separator lines)
    data = []
    for line in lines[header_idx+1:]:
        if is_separator(line) or is_note(line) or line.strip() == '':
            continue
        values = split(line, delimiter)
        if len(values) >= len(headers):
            row = dict(zip(headers, values))
            data.append(row)
    
    return data
```

### JSON Parsing

For nested JSON financial data:

```
function parse_json_financial(filepath):
    data = json.load(open(filepath))
    
    # Walk the structure to find financial statement arrays
    # Common patterns:
    # - {"company": "X", "financials": {"income_statement": [...]}}
    # - {"data": [{"year": 2024, "revenue": ...}]}
    # - [{"fiscal_year": "FY2024", "Revenue": ...}]
    
    records = find_financial_arrays(data)
    return flatten_to_records(records)
```

### HTML Table Parsing

```
function parse_html_tables(filepath):
    tables = pandas.read_html(filepath)
    # Select the table with financial data (most columns, contains year labels)
    best_table = max(tables, key=lambda t: score_financial_table(t))
    # Flatten multi-row headers if present
    return flatten_headers(best_table)
```

### Multi-Row Header Detection and Flattening

Financial tables often have **multi-row headers** where column names span multiple rows with merged cells. This is explicitly mentioned in the spec ("HTML table with merged headers", "header depth varies").

**Detection**: A table has multi-row headers if:
- The first N rows contain only text (no numeric data)
- Those rows contain financial terms (Revenue, Profit, etc.) or year labels
- Row N+1 onwards contains numeric data

**Flattening Algorithm**:

```
function flatten_multirow_headers(table):
    # Step 1: Identify header rows (rows with no numeric data)
    header_rows = []
    data_start = 0
    for i, row in enumerate(table):
        if all_cells_are_text(row):
            header_rows.append(row)
        else:
            data_start = i
            break
    
    # Step 2: Build column names by concatenating header rows
    # For merged cells, propagate the value down/right
    num_cols = max(len(row) for row in header_rows)
    column_names = []
    for col_idx in range(num_cols):
        parts = []
        for row in header_rows:
            if col_idx < len(row):
                cell = row[col_idx].strip()
                if cell and cell not in parts:
                    parts.append(cell)
        column_names.append(' '.join(parts))
    
    # Step 3: Extract data rows
    data_rows = table[data_start:]
    
    # Step 4: Create records with flattened column names
    records = []
    for row in data_rows:
        record = {}
        for i, col_name in enumerate(column_names):
            if i < len(row):
                record[col_name] = row[i]
        records.append(record)
    
    return records
```

**Example**: A table with this structure:

```
                    |    FY2024    |    FY2025    |
    Metric          |  Amount  (%) |  Amount  (%) |
  Revenue           |   60,922     |   130,497    |
  Gross Profit      |   44,301     |    97,858    |
```

Becomes:

```
[
  {"Metric": "Revenue", "FY2024 Amount": "60,922", "FY2025 Amount": "130,497"},
  {"Metric": "Gross Profit", "FY2024 Amount": "44,301", "FY2025 Amount": "97,858"}
]
```

**Handling Merged Cells in HTML**: When using `pandas.read_html`, merged cells (colspan/rowspan) are automatically handled by pandas, which propagates values across the merged range. For BeautifulSoup, you need to manually track colspan/rowspan attributes and fill in the grid accordingly.

---

## 3. Financial Metric Formulas

All metrics are expressed as **percentage numbers** (e.g., 72.72 means 72.72%, not 0.7272).
Default rounding: **2 decimal places**.

| Metric | Numerator | Denominator | Formula | Data Requirements |
|--------|-----------|-------------|---------|-------------------|
| **gross_margin** | Gross Profit | Revenue | `(Gross Profit / Revenue) × 100` | Income statement |
| **operating_margin** | Operating Income | Revenue | `(Operating Income / Revenue) × 100` | Income statement |
| **net_margin** | Net Income | Revenue | `(Net Income / Revenue) × 100` | Income statement |
| **return_on_equity** | Net Income | Shareholders' Equity | `(Net Income / Avg Equity) × 100` where `Avg Equity = (beginning_equity + ending_equity) / 2` | Income statement + Balance sheet |
| **year_over_year_growth** | Revenue[t] − Revenue[t−1] | Revenue[t−1] | `((Revenue_current − Revenue_prior) / Revenue_prior) × 100` | Multi-year income statement; first year is undefined/null |

### Field Name Matching

Financial field names vary by locale and convention. **Normalize before matching**:

1. **Convert to lowercase**
2. **Split camelCase/PascalCase**: `GrossProfit` → `gross profit`, `NetIncome` → `net income`
3. **Replace underscores/hyphens with spaces**: `gross_profit` → `gross profit`
4. **Match against canonical aliases** (case-insensitive, space-insensitive)

| Canonical Field | Common Aliases |
|----------------|----------------|
| Revenue | "Revenue", "Total Revenue", "Sales", "Net Sales", "Turnover", "Umsatz" (DE), "Chiffre d'affaires" (FR), "Ingresos" (ES) |
| Gross Profit | "Gross Profit", "GrossProfit", "Gross Margin" (when used as amount), "Bruttogewinn" (DE) |
| Operating Income | "Operating Income", "OperatingIncome", "EBIT", "Operating Profit", "Betriebsergebnis" (DE) |
| Net Income | "Net Income", "NetIncome", "Net Profit", "Net Earnings", "Profit After Tax", "Nettoergebnis" (DE) |
| Shareholders' Equity | "Shareholders Equity", "Total Equity", "Stockholders Equity", "Book Value", "Eigenkapital" (DE) |
| Fiscal Year | "Year", "Fiscal Year", "FY", "fiscal_year", "Geschäftsjahr" (DE) |

---

## 4. Statement Topology Handling

### Single-Statement Topology

All required fields are in one file. Simply parse and extract.

### Cross-Statement Topology

When the task requires fields from both income statement and balance sheet (e.g., return_on_equity needs Net Income from income statement and Shareholders' Equity from balance sheet):

```
function handle_cross_statement(income_file, balance_file):
    income_data = parse_financial_file(income_file)
    balance_data = parse_financial_file(balance_file)
    
    # Join by fiscal year
    merged = {}
    for year in income_data:
        merged[year] = {**income_data[year]}
    for year in balance_data:
        if year in merged:
            merged[year].update(balance_data[year])
        else:
            merged[year] = balance_data[year]
    
    return merged
```

### Discovery for Cross-Statement

When multiple files are needed, the discovery algorithm should find:
- The file containing income statement fields (Revenue, Gross Profit, Operating Income, Net Income)
- The file containing balance sheet fields (Total Assets, Total Liabilities, Shareholders' Equity)
- Join them by matching fiscal year labels

**Algorithm for distinguishing statement types**:

```
function classify_financial_files(directory, target_company):
    income_files = []
    balance_files = []
    
    for file in directory:
        content = read_preview(file)
        score = score_file(file, target_company)
        
        if score <= 0:
            continue  # Skip decoys
        
        # Classify by field presence
        income_keywords = ['revenue', 'gross profit', 'operating income', 
                          'net income', 'ebit', 'sales']
        balance_keywords = ['total assets', 'total liabilities', 
                           'shareholders equity', 'total equity', 
                           'stockholders equity', 'retained earnings']
        
        income_score = count_matches(content.lower(), income_keywords)
        balance_score = count_matches(content.lower(), balance_keywords)
        
        if income_score > balance_score and income_score > 0:
            income_files.append((file, score))
        elif balance_score > income_score and balance_score > 0:
            balance_files.append((file, score))
        elif income_score > 0 and balance_score > 0:
            # File contains both - likely a combined statement
            # Treat as income statement (primary) and check for equity fields
            if balance_score >= 2:  # Has significant balance sheet data
                balance_files.append((file, score))
            income_files.append((file, score))
    
    # Return best match for each type
    income_file = max(income_files, key=lambda x: x[1])[0] if income_files else None
    balance_file = max(balance_files, key=lambda x: x[1])[0] if balance_files else None
    
    return income_file, balance_file
```

**Joining by fiscal year**: After parsing both files, merge records by matching the fiscal year field. If year labels differ (e.g., "FY2024" vs "2024"), normalize them before joining:

```
function normalize_year_label(year_str):
    # Extract 4-digit year from various formats (FY2024, Fiscal 2024, etc.)
    match = re.search(r'(19|20)\d{2}', year_str)
    if match:
        return match.group(0)
    return year_str  # Return as-is if no year found
```

---

## 5. Conditional Computation Pattern

Many tasks include threshold-based branching:

```
function conditional_computation(data, primary_metric, condition, fallback_metric):
    # Step 1: Compute primary metric for all periods
    primary_values = compute_metric(data, primary_metric)
    
    # Step 2: Evaluate condition on the specified period (usually most recent)
    comparison_value = primary_values[most_recent_period]
    
    if evaluate_condition(comparison_value, condition):
        # Condition met: use primary metric results
        return primary_values
    else:
        # Condition not met: compute fallback metric for all periods
        fallback_values = compute_metric(data, fallback_metric)
        return fallback_values
```

### Condition Parsing

Common condition patterns in task instructions:
- "If X exceeds N%" → `value > threshold`
- "If X is above N%" → `value > threshold`
- "If X is below N%" → `value < threshold`
- "If X does NOT exceed N%" → `value <= threshold`

Always identify: (1) which metric to check, (2) which period to check it in, (3) the threshold, (4) the comparison operator, (5) what to compute if true vs. false.

---

## 6. Output Contract Matching

### Output Schema

Read the task instruction for the exact output schema. Common patterns:

| Required Columns | CSV Header |
|-----------------|------------|
| Fiscal year + gross margin | `fiscal_year,gross_margin_pct` |
| Fiscal year + net margin | `fiscal_year,net_margin_pct` |
| Fiscal year + operating margin | `fiscal_year,operating_margin_pct` |
| Fiscal year + ROE | `fiscal_year,return_on_equity_pct` |
| Fiscal year + YoY growth | `fiscal_year,yoy_growth_pct` |
| Year + generic margin | `year,margin` |

### Serialization

```
function write_output(results, output_path, column_names):
    # Always write as CSV unless task specifies otherwise
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(column_names)  # e.g., ['fiscal_year', 'gross_margin_pct']
        for row in results:
            writer.writerow(row)
```

### Key Rules
- Percentages are **numbers**, not strings with `%` signs (e.g., `72.72` not `"72.72%"`)
- Round to specified decimal places (default: 2)
- Preserve the fiscal year label format from the source data (e.g., "FY2024", "2024", "2023-2024")
- Output file path is always specified in the task instruction

---

## Execution Workflow

Complete end-to-end workflow for any task in this family:

```
1. READ task instruction → extract:
   - target company name/ticker
   - data directory path
   - requested metric(s)
   - conditional logic (if any)
   - output path and schema

2. DISCOVER data file(s):
   - List directory contents
   - Score each file using content-based discovery algorithm
   - Select best match; verify it contains needed fields

3. PARSE data:
   - Detect format (CSV/JSON/fixed-width/HTML)
   - Extract header row and data rows
   - Normalize numeric values
   - Map field names to canonical names

4. COMPUTE metric(s):
   - Look up formula for requested metric
   - Handle single vs. cross-statement topology
   - Apply conditional logic if present
   - Round to specified precision

5. WRITE output:
   - Match exact output schema from task instruction
   - Serialize to specified format (usually CSV)
   - Verify output file exists and has correct structure
```
