---
name: financial-analysis
description: >
  Discover, parse, and analyze financial data from heterogeneous sources to
  compute standard profitability metrics with conditional logic and produce
  a validated CSV result artifact.
---

# Financial Analysis Skill

## Overview

This skill solves tasks that require finding financial statement data hidden
among decoy files, parsing varied formats, computing a requested profitability
metric per fiscal year, applying conditional branching rules, and writing a
clean CSV result.

---

## Phase 1 — Data Discovery

### 1.1 Enumerate candidate files

```bash
find /app/financials/ -type f 2>/dev/null
# Also check /app/data/ or the root /app/ if nothing is found there.
```

### 1.2 Classify each file by content (not extension)

| Clue in first ~20 lines | Likely role |
|---|---|
| Company name matching the task target | **Primary data file** |
| Different company / ticker | Decoy — skip |
| Log lines (`[INFO]`, `[WARN]`, `[DATA]`) | Stale cache / misleading log — skip |
| Product-level or departmental rows without financial-statement fields | Decoy — skip |

**Rules:**

- Read every file. Extensions (`.dat`, `.csv`, `.txt`, `.json`, `.html`) are
  unreliable indicators of actual format or relevance.
- A file is relevant only if it contains **both** the target entity (company
  name, ticker, or subsidiary) **and** the financial fields needed for the
  requested metric.
- Log/cache files may contain plausible-looking numbers from prior runs.
  **Never trust cached values**; always recompute from the primary source.

### 1.3 Handle multiple relevant files (statement topology)

If revenue and profit figures live in separate files (e.g., `income_statement`
and `balance_sheet`), join them on the fiscal-year key. Ensure consistent
year labels before merging.

---

## Phase 2 — Format Detection & Parsing

### 2.1 Identify the data block within the file

Many files wrap a structured data section inside human-readable headers/footers.
Strategy:

1. Scan for the **first line** that looks like a header row
   (comma/tab-separated field names, or a table border).
2. Scan for the **last data line** before a footer, blank block, or border.
3. Extract only the data block.

### 2.2 Format-specific parsers

| Format | Detection | Parsing approach |
|---|---|---|
| CSV / TSV | Comma or tab delimiters, header row | `pandas.read_csv` or `csv.DictReader` |
| Fixed-width text | Aligned columns, no delimiters | `pandas.read_fwf` or manual `split()` on column positions |
| JSON | `{` or `[` at start | `json.loads`; handle nested objects by flattening |
| HTML table | `<table>` tags | `pandas.read_html` — watch for merged header rows (`header=[0,1]`) |
| Mixed | Text header + CSV body | Strip header/footer, then parse the CSV block |

### 2.3 Schema normalization

Financial field names vary widely. Map encountered names to canonical concepts:

| Canonical concept | Common aliases |
|---|---|
| Revenue | `Revenue`, `Total Revenue`, `Sales`, `Net Revenue`, `Net Sales`, `Total Sales`, `TotalRevenues` |
| Gross Profit | `GrossProfit`, `Gross Profit`, `Gross Margin $`, `Total Gross Profit` |
| Operating Income | `OperatingIncome`, `Operating Income`, `EBIT`, `Operating Profit`, `Income from Operations` |
| Net Income | `NetIncome`, `Net Income`, `Net Earnings`, `Profit After Tax`, `Net profit` |
| Shareholders' Equity | `Total Equity`, `Shareholders' Equity`, `Stockholders' Equity`, `Total Stockholders Equity` |
| Fiscal Year | `Year`, `FiscalYear`, `FY`, `Period`, `fiscal_year` |

**Locale notes:**

- European numbers: `.` as thousands separator, `,` as decimal → replace before casting.
- Parenthesised negatives: `(1,234)` → `-1234`.
- Units: confirm whether values are in millions, billions, or raw. Ratios are
  unit-independent as long as numerator and denominator share the same unit.

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
| **Year-over-Year Growth** | `(Current − Prior) / |Prior| × 100` (applied to Revenue or another specified field) |

### 3.2 Rounding

- Default: round to **2 decimal places** unless the task specifies otherwise.
- Use Python's `round(value, 2)` which implements banker's rounding.
- Verify edge cases: `round(72.725, 2)` → `72.72` in Python (banker's rounding).
  If the task expects standard rounding (half-up), use:
  ```python
  from decimal import Decimal, ROUND_HALF_UP
  result = float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
  ```

### 3.3 Sign convention

- Margins and ROE: positive values indicate profit / positive equity.
- YoY growth: positive means increase, negative means decrease.
- Never output raw decimals (0.7272) when the contract asks for percentage numbers (72.72).

---

## Phase 4 — Conditional Logic

Tasks often include branching rules. Common pattern:

> "If condition on the most recent year's metric holds, compute metric A for
> all years; otherwise compute metric B for all years."

### Execution checklist

1. **Identify the condition variable** — which metric, which year, what threshold.
2. **Determine "most recent year"** — sort years descending; pick the latest.
   Watch out: year labels may be `FY2026`, `2026`, `Jan-2026`, etc.
3. **Evaluate the condition** on that year's data.
4. **Compute the chosen metric** for *all* available years — not just the latest.
5. **Column naming** in the output must match the *actual* metric computed
   (e.g., if the branch selects Net Margin, the column should reflect that,
   unless the task prescribes a fixed column name).

---

## Phase 5 — Output Generation

### 5.1 Default output contract

Unless the task specifies otherwise:

- **Path**: `/app/results.csv`
- **Encoding**: UTF-8, no BOM
- **Line endings**: `\n`
- **Column order**: `fiscal_year,<metric>_pct`
- **Row order**: ascending by fiscal year
- **No index column**

```csv
fiscal_year,gross_margin_pct
FY2022,64.93
FY2023,56.93
FY2024,72.72
FY2025,74.99
FY2026,71.07
```

### 5.2 Task-specified contracts

Always re-read the task's output section. Variations include:

- Different column names (e.g., `year` instead of `fiscal_year`)
- Different metric column suffix (e.g., `net_margin_pct`)
- Additional columns required (e.g., `revenue` alongside margin)
- JSON or TSV output instead of CSV
- Specific row ordering

**The task's explicit output contract overrides all defaults.**

### 5.3 Writing the file

```python
import csv

with open('/app/results.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['fiscal_year', 'gross_margin_pct'])
    for year in sorted(results.keys()):
        writer.writerow([year, results[year]])
```

---

## Phase 6 — Self-Verification

Before declaring the task complete, run through this checklist:

### 6.1 Data integrity

- [ ] Used the correct company's data (not a decoy)?
- [ ] Used the most recent year for the condition check?
- [ ] Numerators and denominators match the requested metric's formula?
- [ ] All available years are included in the output?

### 6.2 Arithmetic spot-check

Recompute at least one year manually:

```python
# Quick sanity check
revenue = <value from data>
profit = <value from data>
expected = round(profit / revenue * 100, 2)
print(f"Manual check: {profit}/{revenue} = {expected}%")
```

### 6.3 Output format

```bash
cat /app/results.csv
```

Verify:
- [ ] Header row matches the task's required column names exactly
- [ ] Values are percentage numbers (not decimals)
- [ ] Rounding is correct (2 decimal places unless otherwise specified)
- [ ] No trailing commas, no extra blank lines
- [ ] File is valid CSV parseable by `pandas.read_csv`

### 6.4 Final validation script

```python
import pandas as pd

df = pd.read_csv('/app/results.csv')
print(df.to_string())
print(f"\nShape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(f"Dtypes:\n{df.dtypes}")
assert df.shape[0] >= 1, "No data rows"
assert df.shape[1] >= 2, "Missing columns"
# Check no nulls
assert df.isnull().sum().sum() == 0, "Unexpected nulls"
# Check percentage range (margins typically -100 to 100+)
metric_col = [c for c in df.columns if c != 'fiscal_year'][0]
assert df[metric_col].between(-200, 200).all(), "Values outside expected range"
print("✓ All checks passed")
```

---

## Common Pitfalls

| Pitfall | How to avoid |
|---|---|
| Trusting cache/log files with pre-computed values | Always recompute from the primary data file |
| Using the wrong company's data | Verify company name/ticker in the file content |
| Confusing decimals with percentages | If formula gives 0.7272, multiply by 100 → 72.72 |
| Wrong year for the condition check | Sort years descending, pick the maximum/latest |
| Applying the condition metric to only one year | Compute the chosen metric for **all** years |
| Locale-formatted numbers (`1.234,56`) | Detect and strip thousands separators before casting |
| Hard-coding column names from one instance | Read the task's output contract each time |
| Off-by-one in header row detection | Print the parsed DataFrame to confirm headers are correct |

---

## Worked Strategy (abstract — not a specific answer)

```
1. find /app/financials/ -type f  → list all files
2. For each file, read contents → identify target company + financial fields
3. Parse the data block → DataFrame with [year, revenue, profit, ...]
4. Identify the requested metric and condition from the task
5. Evaluate condition on the most recent year
6. Compute the chosen metric for all years → round to 2dp
7. Write /app/results.csv with the required columns
8. cat + validate the output
```
