---
name: financial-analysis
description: >
  Discover, parse, and analyze financial data from heterogeneous sources to
  compute standard profitability metrics with conditional logic and produce
  a validated CSV result artifact.
---

# Financial Analysis Skill

## Critical Environment Constraints

> **pandas and numpy are NOT available.** All code must use Python stdlib only:
> `csv`, `json`, `re`, `io`, `os`, `decimal`. Never `import pandas` or
> `import numpy`. Every code snippet below uses stdlib exclusively.
>
> **The scripts/ directory is NOT available inside /app.** Do not try to run
> external scripts. All validation must be done inline in your solution script.

---

## Phase 1 — Data Discovery

### 1.1 Read every file and classify by content

```bash
for f in $(find /app -type f 2>/dev/null); do
  echo "=== $f ==="; cat "$f"; echo; echo
done
```

Then classify each file:

| Clue in content | Likely role |
|---|---|
| Company name / ticker matching the task target | **Primary data file** |
| Different company or ticker | Decoy — skip |
| Log lines (`[INFO]`, `[WARN]`, `[DATA]`) with pre-computed numbers | Stale cache — skip |
| Product-level rows without financial-statement fields | Decoy — skip |

**Rules:**
- File extensions are unreliable — read content, not names.
- A file is relevant only if it contains **both** the target entity
  **and** the financial fields needed for the requested metric.
- **Never trust cached/log values**; always recompute from the primary source.

### 1.2 Handle multiple relevant files (statement topology)

If revenue and profit figures live in separate files (e.g., income statement
and balance sheet), parse each independently, then join on the fiscal-year key:

```python
# Join two parsed datasets by year
merged = {}
for row in income_rows:
    yr = extract_year(row)
    merged[yr] = {**normalize(row)}
for row in balance_rows:
    yr = extract_year(row)
    if yr in merged:
        merged[yr].update(normalize(row))
    else:
        merged[yr] = {**normalize(row)}
```

---

## Phase 2 — Parsing & Schema Normalization (stdlib only)

### 2.1 Extract CSV block from a mixed-format file

Many files wrap a CSV data block inside human-readable headers/footers.
This function handles that pattern:

```python
import re, csv, io

def extract_csv_block(filepath):
    """Extract a CSV data block from a mixed-format file."""
    with open(filepath) as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if ',' in stripped and not stripped.startswith('='):
            fields = [f.strip() for f in stripped.split(',')]
            name_like = sum(1 for f in fields if re.match(r'^[A-Za-z_ ]+$', f))
            if name_like >= 2:
                header_idx = i
                break

    if header_idx is None:
        raise ValueError(f"No CSV header found in {filepath}")

    data_lines = [lines[header_idx].strip()]
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('=') or stripped.startswith('-'):
            break
        if stripped.startswith('NOTE') or stripped.startswith('Note'):
            break
        if ',' in stripped:
            data_lines.append(stripped)

    reader = csv.DictReader(io.StringIO('\n'.join(data_lines)))
    return list(reader)
```

### 2.2 Parse JSON financial data

```python
import json

def parse_json_file(filepath):
    """Parse a JSON financial data file. Handles both objects and arrays."""
    with open(filepath) as f:
        data = json.load(f)
    # If top-level is a dict, look for a list-valued key containing the data
    if isinstance(data, dict):
        for key in data:
            if isinstance(data[key], list) and len(data[key]) > 0:
                return data[key]
        return [data]  # single record
    return data  # already a list
```

### 2.3 Schema normalization

Map encountered field names to canonical concepts (case-insensitive):

```python
FIELD_MAP = {
    'revenue': ['revenue', 'sales', 'net sales', 'totalsales', 'totalrevenue',
                'total revenue', 'net revenue'],
    'gross_profit': ['gross profit', 'grossprofit', 'gross margin'],
    'operating_income': ['operating income', 'operatingincome', 'ebit',
                         'operating profit', 'income from operations'],
    'net_income': ['net income', 'netincome', 'net earnings',
                   'profit after tax', 'net profit', 'profit'],
    'equity': ['equity', 'stockholders', 'shareholders',
               'total equity', 'owners equity'],
    'year': ['year', 'fiscalyear', 'fy', 'period', 'fiscal year', 'date'],
}

def normalize_fieldname(raw_name):
    lower = raw_name.strip().lower()
    for canonical, aliases in FIELD_MAP.items():
        for alias in aliases:
            if alias in lower:
                return canonical
    return None

def normalize_row(row):
    """Normalize all keys in a dict row."""
    nrow = {}
    for raw_key, val in row.items():
        canon = normalize_fieldname(raw_key)
        nrow[canon or raw_key.strip().lower()] = val
    return nrow
```

### 2.4 Number cleaning

```python
def clean_number(raw):
    """Parse a financial number string, handling locale formats."""
    s = raw.strip() if isinstance(raw, str) else str(raw)
    negative = s.startswith('(') and s.endswith(')')
    if negative:
        s = s[1:-1]
    s = re.sub(r'[$€£¥\s]', '', s)
    if ',' in s and '.' in s:
        if s.rindex(',') > s.rindex('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    val = float(s)
    return -val if negative else val
```

---

## Phase 3 — Metric Computation Functions

All metrics return **percentage numbers** (e.g., 72.72 means 72.72%).
Copy the functions you need based on the task's requested metric.

### Gross Margin

```python
def gross_margin(row):
    gp = clean_number(row['gross_profit'])
    rev = clean_number(row['revenue'])
    return gp / rev * 100
```

### Operating Margin

```python
def operating_margin(row):
    oi = clean_number(row['operating_income'])
    rev = clean_number(row['revenue'])
    return oi / rev * 100
```

### Net Margin

```python
def net_margin(row):
    ni = clean_number(row['net_income'])
    rev = clean_number(row['revenue'])
    return ni / rev * 100
```

### Return on Equity

```python
def return_on_equity(rows_sorted):
    """Compute ROE for each year. Uses average equity when two consecutive
    years are available; falls back to year-end equity for the first year."""
    results = {}
    for i, row in enumerate(rows_sorted):
        ni = clean_number(row['net_income'])
        eq = clean_number(row['equity'])
        if i == 0:
            avg_eq = eq
        else:
            prev_eq = clean_number(rows_sorted[i - 1]['equity'])
            avg_eq = (prev_eq + eq) / 2
        results[row['_year_label']] = ni / avg_eq * 100 if avg_eq != 0 else 0
    return results
```

### Year-over-Year Growth

```python
def yoy_growth(rows_sorted, field='revenue'):
    """Compute YoY growth for a given field across sorted years."""
    results = {}
    for i, row in enumerate(rows_sorted):
        current = clean_number(row[field])
        if i == 0:
            continue  # no prior year for first entry
        prior = clean_number(rows_sorted[i - 1][field])
        growth = (current - prior) / abs(prior) * 100 if prior != 0 else 0
        results[row['_year_label']] = growth
    return results
```

### Rounding

Use `round(value, 2)` by default. If the task expects standard half-up
rounding (check carefully):

```python
from decimal import Decimal, ROUND_HALF_UP

def round_half_up(value, places=2):
    q = Decimal(10) ** -places
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))
```

---

## Phase 4 — Year Sorting and Conditional Logic

### Robust year sorting

```python
def year_sort_key(label):
    """Extract numeric year from labels like FY2026, 2026, Jan-2025."""
    m = re.search(r'(\d{4})', str(label))
    return int(m.group(1)) if m else 0

sorted_years = sorted(results.keys(), key=year_sort_key)
```

### Conditional branching pattern

Tasks often include: "If condition on the most recent year holds, compute
metric A; otherwise compute metric B."

```python
latest_year = sorted_years[-1]
latest_value = results[latest_year]

if latest_value > THRESHOLD:     # adjust comparison as needed
    chosen_metric = metric_a_fn  # function reference
    metric_col = "metric_a_pct"
else:
    chosen_metric = metric_b_fn
    metric_col = "metric_b_pct"
```

Compute the chosen metric for **all** available years — not just the latest.

---

## Phase 5 — Output Generation

### Output contract

**The task's explicit output contract overrides all defaults.** Always re-read
the task's output section. Defaults:

- **Path**: `/app/results.csv`
- **Encoding**: UTF-8, no BOM
- **Column order**: `fiscal_year,<metric>_pct`
- **Row order**: ascending by fiscal year
- **No index column**

```python
import csv

with open('/app/results.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['fiscal_year', metric_col])
    for yr in sorted_years:
        writer.writerow([yr, round(results[yr], 2)])
```

---

## Phase 6 — Self-Verification (inline, no external scripts)

After writing results.csv, always validate it **within the same script**:

```python
# ---- Inline validation (append to your solution script) ----
with open('/app/results.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    out_rows = list(reader)
    cols = reader.fieldnames or []

print(f"Output columns: {cols}")
print(f"Output rows: {len(out_rows)}")
for row in out_rows:
    print(f"  {row}")

assert len(out_rows) > 0, "No data rows"
assert len(cols) >= 2, "Too few columns"

# Check no empty values
for i, row in enumerate(out_rows):
    for col in cols:
        assert row.get(col, '').strip(), f"Empty value at row {i}, col {col}"

# Check metric values are percentages, not raw decimals
year_kw = {'year', 'fy', 'period', 'fiscal'}
for col in cols:
    if any(k in col.lower() for k in year_kw):
        continue
    vals = [float(row[col]) for row in out_rows]
    assert max(abs(v) for v in vals) >= 1.0, f"'{col}' looks like decimals"
    assert max(abs(v) for v in vals) <= 500, f"'{col}' exceeds 500%"

print("Validation passed!")
```

---

## Complete End-to-End Template

Copy this skeleton and adapt to the specific task:

```python
import csv, json, re, io, os

# ========== CONFIG (from task instruction) ==========
TARGET_COMPANY = "Company Name Here"
OUTPUT_PATH = "/app/results.csv"
OUTPUT_COLUMNS = ["fiscal_year", "gross_margin_pct"]  # from task
CONDITION_THRESHOLD = 70   # percentage, from task
CONDITION_METRIC = "gross_margin"  # metric to check condition on
CONDITION_OP = ">"         # >, <, >=, <=, ==

# ========== HELPER FUNCTIONS ==========
# (paste extract_csv_block, parse_json_file, normalize_row, clean_number,
#  year_sort_key, and the metric functions you need from above)

def extract_csv_block(filepath):
    with open(filepath) as f:
        lines = f.readlines()
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if ',' in stripped and not stripped.startswith('='):
            fields = [f.strip() for f in stripped.split(',')]
            if sum(1 for f in fields if re.match(r'^[A-Za-z_ ]+$', f)) >= 2:
                header_idx = i
                break
    if header_idx is None:
        raise ValueError(f"No CSV header in {filepath}")
    data_lines = [lines[header_idx].strip()]
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('=') or stripped.startswith('-'):
            break
        if stripped.startswith('NOTE') or stripped.startswith('Note'):
            break
        if ',' in stripped:
            data_lines.append(stripped)
    reader = csv.DictReader(io.StringIO('\n'.join(data_lines)))
    return list(reader)

FIELD_MAP = {
    'revenue': ['revenue', 'sales', 'net sales', 'totalrevenue', 'total revenue'],
    'gross_profit': ['gross profit', 'grossprofit', 'gross margin'],
    'operating_income': ['operating income', 'operatingincome', 'ebit',
                         'operating profit', 'income from operations'],
    'net_income': ['net income', 'netincome', 'net earnings',
                   'profit after tax', 'net profit'],
    'equity': ['equity', 'stockholders', 'shareholders', 'total equity'],
    'year': ['year', 'fiscalyear', 'fy', 'period', 'fiscal year'],
}

def normalize_row(row):
    nrow = {}
    for k, v in row.items():
        canon = None
        lower = k.strip().lower()
        for c, aliases in FIELD_MAP.items():
            if any(a in lower for a in aliases):
                canon = c
                break
        nrow[canon or lower] = v
    return nrow

def parse_json_file(filepath):
    with open(filepath) as f:
        data = json.load(f)
    if isinstance(data, dict):
        for key in data:
            if isinstance(data[key], list) and len(data[key]) > 0:
                return data[key]
        return [data]
    return data

def clean_number(raw):
    s = raw.strip() if isinstance(raw, str) else str(raw)
    negative = s.startswith('(') and s.endswith(')')
    if negative:
        s = s[1:-1]
    s = re.sub(r'[$€£¥\s]', '', s)
    if ',' in s and '.' in s:
        if s.rindex(',') > s.rindex('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    return -float(s) if negative else float(s)

def year_sort_key(label):
    m = re.search(r'(\d{4})', str(label))
    return int(m.group(1)) if m else 0

# Metric functions — use the one(s) the task requires
def gross_margin(row):
    return clean_number(row['gross_profit']) / clean_number(row['revenue']) * 100

def operating_margin(row):
    return clean_number(row['operating_income']) / clean_number(row['revenue']) * 100

def net_margin(row):
    return clean_number(row['net_income']) / clean_number(row['revenue']) * 100

# ========== DISCOVERY ==========
# IMPORTANT: Only search in data directories, not the entire /app tree.
# This avoids picking up solve.py or results.csv.
data_dirs = []
for d in ['/app/financials', '/app/data', '/app/files', '/app/input']:
    if os.path.isdir(d):
        data_dirs.append(d)
if not data_dirs:
    data_dirs = ['/app']

all_files = []
for d in data_dirs:
    for root, dirs, files in os.walk(d):
        for fn in files:
            all_files.append(os.path.join(root, fn))

# Find the primary data file
primary_file = None
for fp in all_files:
    with open(fp) as f:
        content = f.read()
    if TARGET_COMPANY.lower() in content.lower():
        # Skip log/cache files
        if '[INFO]' in content and '[WARN]' in content:
            continue
        primary_file = fp
        print(f"Found: {fp}")
        break

assert primary_file, f"No file with '{TARGET_COMPANY}'"

# ========== PARSE ==========
# Detect format and parse
with open(primary_file) as f:
    first_char = f.read(1).strip()

if first_char in ('{', '['):
    raw_rows = parse_json_file(primary_file)
else:
    raw_rows = extract_csv_block(primary_file)

print(f"Parsed {len(raw_rows)} rows")

# Normalize field names
rows = [normalize_row(r) for r in raw_rows]

# Tag each row with its original year label for output
for r in rows:
    r['_year_label'] = r.get('year', '')

# Sort by numeric year
rows.sort(key=lambda r: year_sort_key(r['_year_label']))

# ========== COMPUTE METRIC ==========
# First pass: compute the condition-check metric for the latest year
# to determine which branch to take

# Example: compute gross margin for condition check
gm_by_year = {}
for r in rows:
    gm_by_year[r['_year_label']] = gross_margin(r)

sorted_years = sorted(gm_by_year.keys(), key=year_sort_key)
latest = sorted_years[-1]
latest_val = gm_by_year[latest]
print(f"Latest year: {latest}, GM={latest_val:.2f}%")

# Conditional branch
if latest_val > CONDITION_THRESHOLD:
    # Use gross margin for all years
    metric_col = "gross_margin_pct"
    final = {yr: round(gm_by_year[yr], 2) for yr in sorted_years}
    print(f"Condition met (>{CONDITION_THRESHOLD}%) → Gross Margin")
else:
    # Compute net margin for all years instead
    nm_by_year = {}
    for r in rows:
        nm_by_year[r['_year_label']] = net_margin(r)
    metric_col = "net_margin_pct"
    final = {yr: round(nm_by_year[yr], 2) for yr in sorted_years}
    print(f"Condition NOT met → Net Margin")

# ========== WRITE OUTPUT ==========
# Use columns from the task instruction (not hardcoded defaults!)
OUTPUT_COLUMNS = ["fiscal_year", metric_col]  # adjust if task differs

with open(OUTPUT_PATH, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(OUTPUT_COLUMNS)
    for yr in sorted_years:
        writer.writerow([yr, final[yr]])

print(f"Wrote {len(sorted_years)} rows to {OUTPUT_PATH}")

# ========== VALIDATE ==========
with open(OUTPUT_PATH, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    out_rows = list(reader)
    cols = reader.fieldnames or []

print(f"Columns: {cols}, Rows: {len(out_rows)}")
for row in out_rows:
    print(f"  {row}")

assert len(out_rows) > 0, "No data rows"
for col in cols:
    if any(k in col.lower() for k in ['year', 'fy', 'period', 'fiscal']):
        continue
    vals = [float(row[col]) for row in out_rows]
    assert max(abs(v) for v in vals) >= 1.0, f"'{col}' looks like decimals"

print("Done! Validation passed.")
```

---

## Common Pitfalls

| Pitfall | How to avoid |
|---|---|
| `import pandas` crashes | **Never use pandas** — stdlib only |
| `os.walk('/app')` picks up solve.py | Search specific data dirs only (see template) |
| Trusting cache/log files | Always recompute from primary data |
| Wrong company's data | Verify company name in file content |
| Decimals vs percentages | Multiply by 100: 0.7272 → 72.72 |
| Wrong "most recent" year | Use `year_sort_key`, not string sort |
| Metric for only one year | Compute for **all** years |
| Locale numbers (`1.234,56`) | Use `clean_number()` |
| Hard-coding from cat output | Parse programmatically |
| Wrong column names | Re-read the task's output contract each time |
| Looking for scripts/ in /app | All validation must be inline |
| Leaving solve.py behind | Remove it at end: `os.remove('/app/solve.py')` |
