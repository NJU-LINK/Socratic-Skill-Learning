---
name: financial-analysis
description: >
  Discover, parse, and analyze financial data from heterogeneous sources to
  compute standard profitability metrics with conditional logic and produce
  a validated CSV result artifact.
---

# Financial Analysis Skill

## Critical Environment Note

> **pandas and numpy are NOT available.** All code must use Python stdlib only:
> `csv`, `json`, `re`, `io`, `os`, `decimal`. Never `import pandas` or
> `import numpy`. Every code snippet in this skill uses stdlib exclusively.

---

## Phase 1 — Data Discovery

### 1.1 Broad file search

The data directory is not always `/app/financials/`. Search broadly first:

```bash
find /app -type f 2>/dev/null
```

If files are found in a subdirectory (e.g. `/app/financials/`, `/app/data/`),
focus there. If files are directly in `/app/`, work with those.

### 1.2 Read every file and classify by content

For each discovered file, print its full contents:

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
| Product-level or departmental rows without financial-statement fields | Decoy — skip |

**Rules:**

- File extensions (`.dat`, `.csv`, `.txt`, `.json`, `.html`) are unreliable.
  Read content, not names.
- A file is relevant only if it contains **both** the target entity
  **and** the financial fields needed for the requested metric.
- **Never trust cached/log values**; always recompute from the primary source.

### 1.3 Handle multiple relevant files (statement topology)

If revenue and profit figures live in separate files (e.g., income statement
and balance sheet), join them on the fiscal-year key. Ensure consistent
year labels before merging.

---

## Phase 2 — Format Detection & Parsing (stdlib only)

### 2.1 Identify the data block within a mixed-format file

Many files wrap a structured data block inside human-readable headers/footers.
Use this approach to extract the data block:

1. Read all lines of the file.
2. Find the **header line** — the first line that looks like comma-separated
   field names (e.g., contains "Year" or "Revenue" or has multiple commas).
3. Collect subsequent lines that match the data pattern (contain commas,
   start with a year-like token, contain numbers).
4. Stop at footer lines (blank, borders like `===`, or notes like `NOTES:`).

### 2.2 Robust CSV-block extraction from mixed files

```python
import re, csv, io

def extract_csv_block(filepath):
    """Extract a CSV data block from a mixed-format file."""
    with open(filepath) as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Detect header: contains commas and field-name-like words
        if ',' in stripped and not stripped.startswith('='):
            fields = [f.strip() for f in stripped.split(',')]
            # Check if it looks like a financial header
            name_like = sum(1 for f in fields if re.match(r'^[A-Za-z_ ]+$', f))
            if name_like >= 2:
                header_idx = i
                break

    if header_idx is None:
        raise ValueError(f"No CSV header found in {filepath}")

    header_line = lines[header_idx].strip()
    data_lines = [header_line]

    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('=') or stripped.startswith('-'):
            break
        if stripped.startswith('NOTE') or stripped.startswith('Note'):
            break
        # Check if line looks like data (has commas and numbers)
        if ',' in stripped:
            data_lines.append(stripped)

    text = '\n'.join(data_lines)
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return rows
```

### 2.3 Format-specific parsers (all stdlib)

| Format | Detection | Parsing |
|---|---|---|
| CSV / TSV | Comma/tab delimiters, header row | `csv.DictReader` (snippet above) |
| Fixed-width | Aligned columns, no delimiters | Parse by column positions using `re` or slicing |
| JSON | Starts with `{` or `[` | `json.load(f)` then flatten nested objects |
| HTML table | Contains `<table>` | Use `re` to extract `<tr>/<td>` content; see snippet below |
| Mixed | Text header + CSV body | `extract_csv_block` function above |

**HTML table extraction (stdlib):**

```python
import re

def parse_html_table(filepath):
    """Extract rows from an HTML table file."""
    with open(filepath) as f:
        html = f.read()
    # Find all rows
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    result = []
    headers = None
    for row in rows:
        cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if not cells:
            continue
        if headers is None:
            headers = cells
        else:
            result.append(dict(zip(headers, cells)))
    return result
```

### 2.4 Schema normalization

Financial field names vary. Map encountered names to canonical concepts
(case-insensitive matching):

| Canonical concept | Match if field contains any of |
|---|---|
| Revenue | `revenue`, `sales`, `net sales` |
| Gross Profit | `gross profit`, `grossprofit`, `gross margin` (when $-valued) |
| Operating Income | `operating income`, `operatingincome`, `ebit`, `operating profit` |
| Net Income | `net income`, `netincome`, `net earnings`, `profit after tax` |
| Shareholders' Equity | `equity`, `stockholders`, `shareholders` |
| Fiscal Year | `year`, `fiscalyear`, `fy`, `period` |

```python
import re

FIELD_MAP = {
    'revenue': ['revenue', 'sales', 'net sales', 'totalsales', 'totalrevenue'],
    'gross_profit': ['gross profit', 'grossprofit', 'gross margin'],
    'operating_income': ['operating income', 'operatingincome', 'ebit', 'operating profit'],
    'net_income': ['net income', 'netincome', 'net earnings', 'profit after tax', 'net profit'],
    'equity': ['equity', 'stockholders', 'shareholders'],
    'year': ['year', 'fiscalyear', 'fy', 'period', 'fiscal year'],
}

def normalize_fieldname(raw_name):
    """Map a raw field name to a canonical concept, or None."""
    lower = raw_name.strip().lower()
    for canonical, aliases in FIELD_MAP.items():
        for alias in aliases:
            if alias in lower:
                return canonical
    return None
```

### 2.5 Locale and number cleaning

```python
def clean_number(raw):
    """Parse a financial number string, handling common locale formats."""
    s = raw.strip()
    # Handle parenthesised negatives: (1,234) → -1234
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    # Remove currency symbols and whitespace
    s = re.sub(r'[$€£¥\s]', '', s)
    # Detect European format: 1.234,56 (dot=thousands, comma=decimal)
    # vs standard: 1,234.56 (comma=thousands, dot=decimal)
    if ',' in s and '.' in s:
        if s.rindex(',') > s.rindex('.'):
            # European: dots are thousands, comma is decimal
            s = s.replace('.', '').replace(',', '.')
        else:
            # Standard: commas are thousands, dot is decimal
            s = s.replace(',', '')
    elif ',' in s:
        # Could be thousands separator or decimal
        # If only one comma and 1-2 digits after, it's decimal (European)
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    val = float(s)
    return -val if negative else val
```

---

## Phase 3 — Metric Calculation

### 3.1 Formula reference

All metrics are expressed as **percentage numbers** (e.g., 72.72 means 72.72%).

| Metric | Formula |
|---|---|
| **Gross Margin** | `Gross Profit / Revenue × 100` |
| **Operating Margin** | `Operating Income / Revenue × 100` |
| **Net Margin** | `Net Income / Revenue × 100` |
| **Return on Equity** | `Net Income / Average Shareholders' Equity × 100` (or year-end equity if only one value) |
| **Year-over-Year Growth** | `(Current − Prior) / abs(Prior) × 100` (applied to Revenue or another specified field) |

### 3.2 Rounding

- Default: round to **2 decimal places** unless the task specifies otherwise.
- Use `round(value, 2)` (Python banker's rounding).
- If the task expects standard half-up rounding, use:

```python
from decimal import Decimal, ROUND_HALF_UP

def round_half_up(value, places=2):
    q = Decimal(10) ** -places
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))
```

### 3.3 Sign convention

- Margins and ROE: positive = profit, negative = loss.
- YoY growth: positive = increase, negative = decrease.
- **Never** output raw decimals (0.7272) when the contract asks for percentages (72.72).

---

## Phase 4 — Conditional Logic

Tasks often include branching rules. Common pattern:

> "If condition on the most recent year's metric holds, compute metric A for
> all years; otherwise compute metric B for all years."

### Execution checklist

1. **Identify the condition**: which metric, which year, what threshold,
   what comparison (>, <, >=, <=, ==).
2. **Determine "most recent year"**: extract numeric year from labels
   (e.g., `FY2026` → 2026, `Jan-2025` → 2025), then pick the maximum.
3. **Evaluate the condition** on that year's data.
4. **Compute the chosen metric** for *all* available years — not just the latest.
5. **Column naming** in the output must match the *actual* metric computed,
   unless the task prescribes a fixed column name.

### Robust year sorting

```python
import re

def year_sort_key(label):
    """Extract the numeric year from labels like FY2026, 2026, Jan-2025."""
    m = re.search(r'(\d{4})', str(label))
    return int(m.group(1)) if m else 0

sorted_years = sorted(results.keys(), key=year_sort_key)
```

---

## Phase 5 — Output Generation

### 5.1 Default output contract

Unless the task specifies otherwise:

- **Path**: `/app/results.csv`
- **Encoding**: UTF-8, no BOM
- **Column order**: `fiscal_year,<metric>_pct`
- **Row order**: ascending by fiscal year (use `year_sort_key` above)
- **No index column**

### 5.2 Task-specified contracts

**The task's explicit output contract overrides all defaults.** Always re-read
the output section of the task instruction. Variations include:

- Different column names (e.g., `year` instead of `fiscal_year`)
- Different metric column suffix (e.g., `net_margin_pct`)
- Additional columns required
- JSON or TSV output instead of CSV
- Specific row ordering

### 5.3 Writing CSV (stdlib)

```python
import csv

def write_results(filepath, columns, rows):
    """Write results to CSV. rows is a list of dicts."""
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
```

---

## Phase 6 — Self-Verification

### 6.1 Before writing: data integrity checklist

Print and verify intermediate results **before** writing the file:

```python
# Print all computed values for manual inspection
for year in sorted_years:
    print(f"  {year}: {numerator}/{denominator} = {metric_value}%")
print(f"Most recent year: {latest_year}, value: {latest_value}")
print(f"Condition met? {condition_result}")
print(f"Selected metric: {metric_name}")
```

Check:
- [ ] Used the correct company's data (not a decoy)?
- [ ] Numerators and denominators match the requested metric's formula?
- [ ] Most recent year identified correctly (by numeric year, not string sort)?
- [ ] Condition evaluated correctly?
- [ ] All available years included in output?

### 6.2 After writing: validate the CSV

```python
import csv

def validate_output(filepath, expected_columns=None):
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    print(f"Columns: {fieldnames}")
    print(f"Row count: {len(rows)}")

    if expected_columns and fieldnames != expected_columns:
        print(f"FAIL: Expected columns {expected_columns}")
        return False
    if len(rows) == 0:
        print("FAIL: No data rows")
        return False

    # Check for empty values
    for i, row in enumerate(rows):
        for col in fieldnames:
            if not row.get(col, '').strip():
                print(f"FAIL: Empty value at row {i+1}, col '{col}'")
                return False

    # Check metric values are percentages, not decimals
    year_kw = {'year', 'fy', 'period', 'fiscal_year'}
    for col in fieldnames:
        if any(k in col.lower() for k in year_kw):
            continue
        vals = [float(row[col]) for row in rows]
        if max(abs(v) for v in vals) < 1.0:
            print(f"WARN: '{col}' values look like decimals, not percentages")

    print("PASS: All checks passed")
    for row in rows:
        print(f"  {row}")
    return True

validate_output('/app/results.csv', ['fiscal_year', 'gross_margin_pct'])
```

### 6.3 Also run the bundled verification script

The skill package includes `scripts/verify_output.py` (stdlib-only, no pandas).
Run it after generating the output:

```bash
python3 <skill_base_dir>/scripts/verify_output.py /app/results.csv \
  --expected-columns fiscal_year,gross_margin_pct
```

Replace `--expected-columns` with whatever the task's output contract requires.

---

## Complete End-to-End Template

Use this as a starting skeleton. Adapt to the specific task:

```python
import csv, json, re, io, os
from decimal import Decimal, ROUND_HALF_UP

# ---- Config (read from task instruction) ----
TARGET_COMPANY = "NVIDIA Corporation"   # from task
METRIC_A = "gross_margin"               # if condition is true
METRIC_B = "net_margin"                 # if condition is false
CONDITION_THRESHOLD = 70                # percentage
CONDITION_OP = ">"                      # comparison
OUTPUT_PATH = "/app/results.csv"
OUTPUT_COLUMNS = ["fiscal_year", "gross_margin_pct"]  # from task

# ---- Discovery ----
all_files = []
for root, dirs, files in os.walk("/app"):
    for fn in files:
        all_files.append(os.path.join(root, fn))

# ---- Read and classify each file ----
primary_file = None
for fp in all_files:
    with open(fp) as f:
        content = f.read()
    if TARGET_COMPANY.lower() in content.lower():
        primary_file = fp
        print(f"Found target company in: {fp}")
        break

assert primary_file, f"No file found containing '{TARGET_COMPANY}'"

# ---- Parse the data block ----
rows = extract_csv_block(primary_file)  # use function from Phase 2
print(f"Parsed {len(rows)} data rows")

# ---- Normalize field names ----
normalized = []
for row in rows:
    nrow = {}
    for raw_key, val in row.items():
        canon = normalize_fieldname(raw_key)
        if canon:
            nrow[canon] = val
        else:
            nrow[raw_key.strip()] = val
    normalized.append(nrow)

# ---- Compute metrics ----
def year_sort_key(label):
    m = re.search(r'(\d{4})', str(label))
    return int(m.group(1)) if m else 0

results = {}
for row in normalized:
    year_label = row.get('year', '')
    revenue = clean_number(row['revenue'])
    # ... compute the relevant metric per the task formula ...
    # gm = clean_number(row['gross_profit']) / revenue * 100
    # results[year_label] = round(gm, 2)

# ---- Conditional logic ----
sorted_years = sorted(results.keys(), key=year_sort_key)
latest_year = sorted_years[-1]
latest_value = results[latest_year]
condition_met = latest_value > CONDITION_THRESHOLD  # adjust op as needed

print(f"Latest year: {latest_year} = {latest_value}%")
print(f"Condition ({CONDITION_OP} {CONDITION_THRESHOLD}): {condition_met}")

# ---- Write output ----
with open(OUTPUT_PATH, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(OUTPUT_COLUMNS)
    for yr in sorted_years:
        writer.writerow([yr, results[yr]])

print(f"Wrote {len(sorted_years)} rows to {OUTPUT_PATH}")

# ---- Validate ----
# (use validate_output function from Phase 6)
```

---

## Common Pitfalls

| Pitfall | How to avoid |
|---|---|
| `import pandas` crashes | **Never use pandas** — stdlib only (`csv`, `json`, `re`) |
| Trusting cache/log files | Always recompute from the primary data file |
| Using the wrong company's data | Verify company name/ticker in file content |
| Confusing decimals with percentages | Multiply by 100: 0.7272 → 72.72 |
| Wrong "most recent" year | Extract numeric year with `re.search(r'\d{4}', label)` |
| Alphabetical year sort fails | Use `year_sort_key` to sort by numeric year |
| Applying metric to only one year | Compute the chosen metric for **all** years |
| Locale numbers (`1.234,56`) | Use `clean_number()` from Phase 2 |
| Hard-coding data from cat output | Parse programmatically with `extract_csv_block` |
| Wrong column names in output | Re-read the task's output contract each time |
| Missing data rows in output | Assert `len(rows) >= expected_count` before writing |
