---
name: financial-analysis
description: >
  Discover, parse, and analyze financial statement data from heterogeneous
  source files (CSV, fixed-width text, JSON, HTML) to compute standard
  profitability metrics with conditional branching and structured output.
---

# Financial Analysis

## Overview

End-to-end workflow: **Discover → Parse → Compute → Branch → Output**.

1. **Discover** the correct data source among distractor/decoy files
2. **Parse** financial data from varied formats and layouts
3. **Compute** a requested financial metric using correct formulae
4. **Branch** conditionally based on threshold checks
5. **Output** results in a specified structured format

---

## Phase 1 — Data Discovery

### Strategy
- List **all** files in the data directory recursively.
- Do **not** trust file extensions or names alone — decoys are expected.
- Read the **content** of each file to identify the correct one.

### Identification Heuristics
- Match by **company name** mentioned in the task (e.g., "NVIDIA Corporation").
- Match by **required fields**: the correct file must contain the columns/values
  needed for the requested metric (e.g., Revenue and Gross Profit for gross margin).
- Reject files that:
  - Reference a different company or entity.
  - Contain only product-level, quarterly-only, or cached/stale data when annual is required.
  - Contain log lines, cache entries, or analysis summaries rather than primary source data.
- If the task specifies a fiscal-year range, prefer the file whose data coverage
  best matches that range.

### Verification
After selecting a file, print its path and a sample of its contents to confirm
it is the authoritative source before proceeding.

---

## Phase 2 — Data Parsing

### Format Detection
Inspect the first ~20 lines of the chosen file to determine format:

| Format | Detection Signals |
|--------|-------------------|
| CSV-in-text | Banner/decoration lines (`===`, `---`) wrapping a CSV data block |
| Pure CSV | Consistent comma/tab delimiters, header row with field names |
| JSON | Opens with `{` or `[`, parse with `json.loads()` |
| HTML table | `<table>`, `<tr>`, `<td>` tags |

### Parsing Rules
1. **Strip decoration**: Ignore banner lines, comment lines (`#`, `Note:`), and
   separator lines. Extract only the tabular data block.
2. **Locate the header row**: Find the row that contains the known field names
   (e.g., "Revenue", "Year", "GrossProfit"). This anchors the data block.
3. **Normalize field names**: Strip whitespace, convert to lowercase, and map
   common aliases:

   | Canonical Name | Aliases |
   |---------------|---------|
   | `fiscal_year` | `year`, `fy`, `period`, `fiscal year` |
   | `revenue` | `sales`, `net_revenue`, `total_revenue`, `net sales` |
   | `gross_profit` | `gross margin $`, `gp`, `gross profit` |
   | `operating_income` | `operating profit`, `op income`, `ebit` |
   | `net_income` | `net profit`, `net earnings`, `ni`, `profit after tax` |
   | `total_equity` | `shareholders_equity`, `stockholders_equity`, `equity`, `net assets` |

4. **Numeric cleaning**: Remove `$`, commas, whitespace, and surrounding
   parentheses (which indicate negatives). Convert to `float`.
5. **Year normalization**: Accept `FY2024`, `2024`, `FY 2024`, `Year 2024`, etc.
   Preserve the original label for output.

### Robustness
- If a file has multiple data sections, use the one whose header row contains
  the fields needed for the target metric.
- If multi-file joining is required, match records by fiscal year across files.

---

## Phase 3 — Metric Calculation

### Formula Reference

| Metric | Numerator | Denominator | Notes |
|--------|-----------|-------------|-------|
| **Gross Margin** | Gross Profit | Revenue | × 100 → percentage |
| **Operating Margin** | Operating Income | Revenue | × 100 → percentage |
| **Net Margin** | Net Income | Revenue | × 100 → percentage |
| **ROE** | Net Income | Total Equity | × 100 → percentage; requires balance-sheet data |
| **YoY Growth** | Current − Prior | \|Prior\| | × 100 → percentage; undefined for earliest year |

### Calculation Rules
- **Scale**: All metrics are percentage numbers (72.72 = 72.72%, NOT 0.7272).
- **Rounding**: Round to 2 decimal places at the **final step only** using
  Python's `round(val, 2)`.
- **Sign**: Preserve natural sign. A negative margin is valid.
- **Division by zero**: If denominator is 0, output `N/A` or `null`.

### Conditional Branching
Common pattern: "If the most recent year's metric X exceeds N%, compute X for
all years; otherwise compute metric Y instead."

**Approach**: Compute the check value for the most recent year first, evaluate
the condition, then proceed with the full calculation. Print the branching
decision for traceability.

---

## Phase 4 — Output

### Output Rules
1. **Column names**: Use the exact names from the task's output contract.
   Default: `fiscal_year,<metric_name>_pct`.
2. **Row order**: Fiscal year ascending (earliest first).
3. **Encoding**: UTF-8, no BOM.
4. **Line endings**: Use `\n` only — **NOT** `\r\n`.
5. **No trailing blank line** after the last data row.

### CRITICAL: Preventing `\r\n` Line Endings

Python's `csv.writer` produces `\r\n` on some platforms even with `newline=""`.
**Do NOT use `csv.writer`**. Instead, build CSV strings manually and write with
`open(path, "w")` (no `newline` parameter needed when writing plain strings):

```python
# CORRECT — guaranteed \n line endings
lines = ["fiscal_year,gross_margin_pct"]
for fy, val in results:
    lines.append(f"{fy},{val}")
with open("/app/results.csv", "w") as f:
    f.write("\n".join(lines) + "\n")
```

```python
# WRONG — csv.writer may produce \r\n
import csv
with open("/app/results.csv", "w", newline="") as f:
    writer = csv.writer(f)   # ← risk of \r\n
    writer.writerow(...)
```

### Self-Verification Checklist
- [ ] Correct source file (matches target company)?
- [ ] All years present in output?
- [ ] Formula correct (right numerator / denominator)?
- [ ] Percentage scale (not off by 100×)?
- [ ] Rounding applied at final step only?
- [ ] Conditional branch evaluated correctly?
- [ ] Output file has `\n` line endings (not `\r\n`)?
- [ ] No trailing blank line?

---

## Tool Friction Warnings

| Avoid | Use Instead |
|-------|------------|
| `xxd file` | `python3 -c "print(repr(open('file','rb').read()))"` |
| f-string with `\n` inside `{}` | Assign to variable first: `nl = chr(10); print(f'...{nl}...')` |
| `sed -i` on CSV | Rewrite with Python for full control |
| Heredoc with complex Python | Write to a `.py` file, then `python3 file.py` |

---

## Executable Template

**This is the recommended approach.** Copy this template into a Python heredoc
or `.py` file and adapt the configuration section to match the task. It handles
dynamic parsing (no hardcoded values), correct rounding, correct line endings,
and conditional branching.

```python
import os, re, json, sys

# ══════════════════════════════════════════════════════════════
# CONFIGURATION — adapt these to the specific task
# ══════════════════════════════════════════════════════════════
DATA_DIR     = "/app/financials"          # directory to search
COMPANY      = "NVIDIA Corporation"        # target company name from task
OUTPUT_PATH  = "/app/results.csv"          # required output path

# Metric definitions: name -> (numerator_alias, denominator_alias)
# For YoY growth, use the special key with a single field.
METRIC_DEFS = {
    "gross_margin":         ("gross_profit", "revenue"),
    "operating_margin":     ("operating_income", "revenue"),
    "net_margin":           ("net_income", "revenue"),
    "return_on_equity":     ("net_income", "total_equity"),
}
# YoY growth is special: it compares consecutive years of a single field
YOY_GROWTH_FIELD = "revenue"  # field to compute YoY growth on

# Which metric to compute first (for threshold check)
PRIMARY_METRIC   = "gross_margin"
# Threshold: if most-recent year's value > THRESHOLD, use PRIMARY; else use ALT
THRESHOLD        = 70.0
ALT_METRIC       = "net_margin"

# Output column names per metric
METRIC_COL_NAMES = {
    "gross_margin":      "gross_margin_pct",
    "operating_margin":  "operating_margin_pct",
    "net_margin":        "net_margin_pct",
    "return_on_equity":  "roe_pct",
    "year_over_year_growth": "yoy_growth_pct",
}

# ══════════════════════════════════════════════════════════════
# FIELD-NAME ALIASES — maps lowercase variants to canonical names
# ══════════════════════════════════════════════════════════════
ALIASES = {
    "year": "fiscal_year", "fy": "fiscal_year", "period": "fiscal_year",
    "fiscal year": "fiscal_year", "fiscal_year": "fiscal_year",
    "revenue": "revenue", "sales": "revenue", "net revenue": "revenue",
    "total revenue": "revenue", "net sales": "revenue", "net_sales": "revenue",
    "grossprofit": "gross_profit", "gross profit": "gross_profit",
    "gross_profit": "gross_profit", "gp": "gross_profit",
    "operatingincome": "operating_income", "operating income": "operating_income",
    "operating_income": "operating_income", "operating profit": "operating_income",
    "op income": "operating_income", "ebit": "operating_income",
    "netincome": "net_income", "net income": "net_income",
    "net_income": "net_income", "net profit": "net_income",
    "net earnings": "net_income", "net_earnings": "net_income",
    "ni": "net_income", "profit after tax": "net_income",
    "totalequity": "total_equity", "total equity": "total_equity",
    "total_equity": "total_equity", "shareholders equity": "total_equity",
    "shareholders_equity": "total_equity", "stockholders_equity": "total_equity",
    "stockholders equity": "total_equity", "equity": "total_equity",
    "net assets": "total_equity", "net_assets": "total_equity",
}

CANONICAL_FIELDS = set(ALIASES.values())

def normalize(name):
    key = name.strip().lower().replace("_", " ")
    return ALIASES.get(key, key.replace(" ", "_"))

def clean_num(val):
    s = val.strip().replace("$","").replace(",","").replace(" ","")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if not s or s.lower() in ("n/a","na","null","-",""):
        return None
    return float(s)

# ══════════════════════════════════════════════════════════════
# PHASE 1 — DISCOVER
# ══════════════════════════════════════════════════════════════
def discover():
    files = []
    for root, dirs, fnames in os.walk(DATA_DIR):
        for fn in sorted(fnames):
            files.append(os.path.join(root, fn))
    for fpath in files:
        try:
            content = open(fpath, "r", errors="replace").read()
        except Exception:
            continue
        if COMPANY.lower() not in content.lower():
            continue
        # Check that required metric fields appear somewhere in content
        norm = content.lower().replace("_"," ")
        needed = set()
        for m in (PRIMARY_METRIC, ALT_METRIC):
            if m in METRIC_DEFS:
                needed.update(METRIC_DEFS[m])
            elif m == "year_over_year_growth":
                needed.add(YOY_GROWTH_FIELD)
        if all(any(a in norm for a, c in ALIASES.items() if c == f) or f in norm
               for f in needed):
            print(f"[SELECT] {fpath}", file=sys.stderr)
            return fpath, content
    raise FileNotFoundError("No matching data file found")

# ══════════════════════════════════════════════════════════════
# PHASE 2 — PARSE
# ══════════════════════════════════════════════════════════════
def parse(content):
    # Try JSON
    stripped = content.strip()
    if stripped.startswith(("{","[")):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return [{normalize(k): v for k, v in r.items()} for r in data]
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return [{normalize(k): val for k, val in r.items()} for r in v]
        except json.JSONDecodeError:
            pass

    # CSV-in-text: find header row
    lines = content.splitlines()
    header_idx = None
    header = None
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or set(s) <= {"=","-","*"," ","#"}:
            continue
        if s.startswith("#") or s.lower().startswith("note"):
            continue
        for sep in [",", "\t"]:
            parts = [p.strip() for p in s.split(sep)]
            if len(parts) < 2:
                continue
            normed = [normalize(p) for p in parts]
            if sum(1 for n in normed if n in CANONICAL_FIELDS) >= 2:
                header_idx = i
                header = normed
                found_sep = sep
                break
        if header_idx is not None:
            break

    if header_idx is None:
        raise ValueError("No CSV header found")

    records = []
    for line in lines[header_idx+1:]:
        s = line.strip()
        if not s or set(s) <= {"=","-","*"," ","#"}:
            continue
        if s.startswith("#") or s.lower().startswith("note"):
            continue
        parts = [p.strip() for p in s.split(found_sep)]
        if len(parts) != len(header):
            continue
        row = dict(zip(header, parts))
        fy = row.get("fiscal_year", "")
        if not re.search(r"\d{4}", fy):
            break
        records.append(row)
    return records

# ══════════════════════════════════════════════════════════════
# PHASE 3 — COMPUTE
# ══════════════════════════════════════════════════════════════
def compute(records, metric_name):
    if metric_name == "year_over_year_growth":
        # Special: compare consecutive years of a single field
        results = []
        prev = None
        for r in records:
            fy = r.get("fiscal_year", "")
            cur = clean_num(r.get(YOY_GROWTH_FIELD, ""))
            if prev is not None and prev != 0 and cur is not None:
                val = round(((cur - prev) / abs(prev)) * 100, 2)
            else:
                val = None
            results.append((fy, val))
            prev = cur
        return results
    num_f, den_f = METRIC_DEFS[metric_name]
    results = []
    for r in records:
        num = clean_num(r.get(num_f, ""))
        den = clean_num(r.get(den_f, ""))
        fy = r.get("fiscal_year", "")
        if num is not None and den is not None and den != 0:
            val = round((num / den) * 100, 2)
        else:
            val = None
        results.append((fy, val))
    return results

# ══════════════════════════════════════════════════════════════
# PHASE 4 — BRANCH + OUTPUT
# ══════════════════════════════════════════════════════════════
def main():
    fpath, content = discover()
    records = parse(content)
    print(f"[PARSED] {len(records)} records", file=sys.stderr)

    # Check threshold on most recent year
    check = compute(records, PRIMARY_METRIC)
    last_val = check[-1][1]
    exceeds = last_val is not None and last_val > THRESHOLD
    print(f"[CHECK] {PRIMARY_METRIC} latest = {last_val} > {THRESHOLD}? {exceeds}",
          file=sys.stderr)

    if exceeds or not ALT_METRIC:
        results = check
        metric = PRIMARY_METRIC
    else:
        results = compute(records, ALT_METRIC)
        metric = ALT_METRIC
    col = METRIC_COL_NAMES.get(metric, f"{metric}_pct")

    # Write with guaranteed \n line endings (NO csv.writer!)
    rows = ["fiscal_year," + col]
    for fy, val in results:
        rows.append(f"{fy},{val}")
    with open(OUTPUT_PATH, "w") as f:
        f.write("\n".join(rows) + "\n")

    print(f"[OUTPUT] {OUTPUT_PATH}", file=sys.stderr)
    print(open(OUTPUT_PATH).read())

if __name__ == "__main__":
    main()
```

### Adapting the Template

For each new task, change only the **CONFIGURATION** section:
- `COMPANY` → the target entity name from the task instruction
- `PRIMARY_METRIC` / `ALT_METRIC` → which metrics the task requests
- `THRESHOLD` → the branch condition value
- `METRIC_COL_NAMES` → exact output column names from the task
- `OUTPUT_PATH` → the required output file path

Everything else (discovery, parsing, numeric cleaning, line endings) is handled
automatically. This avoids the fragile pattern of hardcoding data values.

---

## Common Pitfalls

| Pitfall | Prevention |
|---------|-----------|
| Hardcoding data values | Always parse the file dynamically; data changes across instances |
| Using a decoy file | Inspect content, not just filenames |
| Using stale cached values | Only use primary source data files |
| Off-by-100 error | Output should be ~50–80 for margins, not 0.5–0.8 |
| Wrong metric computed | Re-read the conditional branch logic carefully |
| Mixing quarterly and annual | Check period labels; aggregate only if instructed |
| `\r\n` line endings | Use `"\n".join(rows)` + `f.write()`, never `csv.writer` |
| Rounding too early | Apply `round()` only at the final step |
