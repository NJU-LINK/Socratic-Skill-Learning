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

Financial data uses varied numeric formats. Normalize all values:

```
function normalize_numeric(value_string):
    s = value_string.strip()
    s = s.replace('$', '').replace('€', '').replace('£', '').replace('¥', '')
    s = s.replace(',', '')           # thousands separator
    s = s.replace(' ', '')           # space thousands separator
    
    # Handle scale suffixes
    multiplier = 1
    if s.upper().endswith('M') or 'million' in s.lower():
        multiplier = 1_000_000
        s = s.rstrip('Mm').strip()
    elif s.upper().endswith('B') or 'billion' in s.lower():
        multiplier = 1_000_000_000
        s = s.rstrip('Bb').strip()
    elif s.upper().endswith('K') or 'thousand' in s.lower():
        multiplier = 1_000
        s = s.rstrip('Kk').strip()
    
    # Handle European decimal comma (e.g., "1.234,56" -> 1234.56)
    # Only if there's exactly one comma and it's after a period
    if ',' in s and '.' in s and s.rfind(',') > s.rfind('.'):
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s and '.' not in s:
        # Could be European decimal: "1234,56" -> 1234.56
        # Or thousands: "1,234" -> 1234
        # Heuristic: if digits after comma <= 2, treat as decimal
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    
    return float(s) * multiplier
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
