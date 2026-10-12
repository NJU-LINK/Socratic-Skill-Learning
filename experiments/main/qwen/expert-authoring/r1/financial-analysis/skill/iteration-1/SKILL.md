---
name: financial-analysis
description: >
  Discover, parse, and analyze financial data files to compute standard
  financial metrics (gross margin, operating margin, net margin, ROE,
  year-over-year growth) with conditional logic, handling varied source
  formats, schemas, and output contracts.
---

# Financial Analysis Skill

## Overview

This skill solves financial-data extraction and computation tasks. Every
instance shares the same core workflow but differs in source format, metric,
schema, statement topology, and output contract. The agent must **discover**
the right data, **parse** it robustly, **compute** the requested metric(s)
correctly, and **write** a CSV result that matches the specified schema.

---

## Phase 1 — Data Discovery

### Goal
Locate the file(s) containing the target company's financial statements among
potential decoys in the data directory (commonly `/app/financials/`).

### Strategy
1. **List all files** recursively in the data directory.
2. **Classify each file** by reading its first ~30 lines:
   - Is it structured data (CSV, JSON, HTML, fixed-width) or a log/cache file?
   - Does it mention the **target company** by name or ticker?
   - Does it contain financial-statement fields (Revenue, Gross Profit,
     Operating Income, Net Income, Shareholders' Equity, etc.)?
3. **Reject decoys**:
   - Log / cache / info files that contain pre-computed values but are not
     authoritative source data.
   - Files for a different company or ticker.
   - Files with product-level or quarterly data when annual statement data is
     needed (unless no annual file exists).
4. **Retain** the file(s) that match the target company AND contain
   financial-statement line items.

> **Key invariant**: The correct file is identified by *content*, not by
> filename. Always verify company identity and data semantics inside the file.

### Handling Multiple Statement Files
If income-statement and balance-sheet data live in separate files:
- Match them by **fiscal year** key.
- Perform an inner join on the year column before computing metrics.

---

## Phase 2 — Parsing

### Supported Formats

| Format         | Detection heuristic                                   | Parse method                          |
|----------------|-------------------------------------------------------|---------------------------------------|
| CSV            | Comma-separated, header row, `.csv` extension         | `csv.DictReader` or `pandas.read_csv` |
| JSON           | Starts with `{` or `[`, `.json` extension             | `json.load` then walk structure       |
| Fixed-width    | Aligned columns, `===` borders, `.dat`/`.txt`         | Regex or manual column splitting      |
| HTML table     | `<table>` tags, `.html` extension                     | `pandas.read_html` or BeautifulSoup   |

### Robust Parsing Rules
- **Skip decoration lines**: lines that are all `=`, `-`, `*`, or whitespace.
- **Skip metadata blocks**: Company name, ticker, notes, etc. — extract them
  for verification but don't treat them as data rows.
- **Detect the header row**: look for a row with ≥2 comma-separated
  alphabetic tokens **where the next content line contains numeric data**.
  Do NOT pick the first alphabetic line — decorated files often have title
  lines (e.g., "FINANCIAL DATA SUMMARY") that look like headers but are not.
- **Normalize field names**: lowercase, strip whitespace, replace spaces /
  underscores / hyphens with a canonical form:
  - `revenue`, `gross_profit`, `operating_income`, `net_income`,
    `shareholders_equity`, `total_equity`, `year`, `fiscal_year`.
- **Normalize numeric values**:
  - Remove currency symbols (`$`, `€`, `¥`), commas, `M`/`B`/`K` suffixes.
  - Handle locale-specific decimal separators (`,` → `.` in some locales).
  - Convert to `float`.
- **Normalize year labels**: keep the raw label (e.g., `FY2024`, `2024`,
  `Jan-2024`) as-is for output, but maintain ordering.
- **Ignore irrelevant rows**: subtotal rows, segment breakdowns, empty rows.

---

## Phase 3 — Metric Computation

### Metric Definitions

| Metric               | Numerator            | Denominator            | Formula                           |
|----------------------|----------------------|------------------------|-----------------------------------|
| `gross_margin`       | Gross Profit         | Revenue                | GP / Rev × 100                    |
| `operating_margin`   | Operating Income     | Revenue                | OI / Rev × 100                    |
| `net_margin`         | Net Income           | Revenue                | NI / Rev × 100                    |
| `return_on_equity`   | Net Income           | Shareholders' Equity   | NI / SE × 100                     |
| `year_over_year_growth` | Δ Value (e.g. Revenue) | Prior Year Value   | (V_t − V_{t−1}) / V_{t−1} × 100 |

### Sign Convention
- All margins and ROE are expressed as **positive percentage numbers**
  (e.g., `72.72` means 72.72%), rounded to 2 decimal places unless the task
  specifies otherwise.
- YoY growth can be negative; preserve the sign.
- If the task says "percentage numbers, not decimals", output `72.72`,
  **not** `0.7272`.

### Conditional Logic
Many tasks include a **threshold gate**:
1. Compute the primary metric for the **most recent** fiscal year.
2. Compare against the stated threshold (e.g., "> 70%").
3. If the condition is **met**: compute the primary metric for **all** years.
4. If the condition is **not met**: compute the **alternate** metric for all
   years instead.

> Always re-read the task instruction carefully for the exact condition, the
> primary metric, the alternate metric, and the threshold value. These are
> **not fixed** across the family.

### Edge Cases
- **Zero denominator**: if Revenue or Equity is 0, output `0.00` or skip —
  follow task instructions; default to `0.00`.
- **Missing field**: if a required field is absent from the data, note it
  and check if the file was parsed correctly before reporting failure.
- **Year ordering**: sort chronologically before computing YoY growth.

---

## Phase 4 — Output

### Default Contract
- Write to `/app/results.csv` (or as specified).
- Header row with column names matching the task spec (e.g.,
  `fiscal_year,gross_margin_pct`).
- One row per fiscal year, sorted chronologically.
- Values rounded to 2 decimal places.
- No index column, no extra whitespace.

### Verification Before Writing
1. Re-compute a sample row manually to confirm arithmetic.
2. Check that the number of output rows matches the number of fiscal years
   in the source data.
3. Confirm column names exactly match the task specification.
4. Ensure values are in percentage-number form, not decimal form.

---

## Execution Plan (Agent Checklist)

```
[ ] 1. Read the task instruction carefully; identify:
       - target company
       - requested metric(s)
       - conditional threshold and alternate metric
       - output file path and column names
       - rounding / scale requirements
[ ] 2. List files in the data directory
[ ] 3. Read each file's content; classify as target / decoy
[ ] 4. Parse the target file(s) into structured rows
[ ] 5. Normalize field names and numeric values
[ ] 6. Compute the primary metric for the most recent year
[ ] 7. Evaluate the threshold condition
[ ] 8. Compute the appropriate metric for ALL years
[ ] 9. Round and format values
[ ] 10. Write results.csv with correct schema
[ ] 11. Verify output: spot-check arithmetic and row count
```

---

## Using the Solver Script

A general-purpose Python solver is available at `scripts/solve.py`. It can
be invoked as:

```bash
python3 scripts/solve.py \
    --data-dir /app/financials \
    --company "NVIDIA Corporation" \
    --metric gross_margin \
    --threshold 70 \
    --threshold-operator gt \
    --alternate-metric net_margin \
    --output /app/results.csv \
    --columns "fiscal_year,gross_margin_pct"
```

### Arguments

| Argument | Description |
|----------|-------------|
| `--data-dir` | Directory containing financial data files |
| `--company` | Target company name or ticker to search for |
| `--metric` | Primary metric: `gross_margin`, `operating_margin`, `net_margin`, `return_on_equity`, `year_over_year_growth` |
| `--threshold` | Threshold value for conditional gate (e.g., `70`) |
| `--threshold-operator` | Comparison: `gt`, `gte`, `lt`, `lte`, `eq` |
| `--threshold-metric` | Metric to check threshold against (defaults to `--metric`) |
| `--alternate-metric` | Metric if threshold is NOT met |
| `--no-condition` | Skip threshold gate; always compute primary metric |
| `--output` | Output CSV file path |
| `--columns` | Column names: `year_col,value_col` |
| `--yoy-field` | Field for YoY growth (default: `revenue`) |

> **Tip**: The script is a starting point. If the data format is unusual
> (nested JSON, HTML with merged headers, multi-file joins), adapt the
> parsing logic inline or write a custom script following the same workflow.

---

## Common Pitfalls

| Pitfall | Mitigation |
|---------|-----------|
| Using a decoy/cache file as source | Always verify company name and data structure inside the file |
| Treating pre-computed values in logs as authoritative | Parse the raw statement data, compute from scratch |
| Wrong company (e.g., AMD instead of NVIDIA) | Match company name or ticker explicitly |
| Decimal vs percentage confusion | If task says "72.72 means 72.72%", multiply ratio by 100 |
| Incorrect rounding | Use Python `round(value, 2)` and format with `f"{val:.2f}"` |
| Ignoring the conditional gate | Always check the threshold condition on the most recent year first |
| Mixing fiscal years from different files | Join on year key and verify alignment |
| Locale-specific number formatting | Strip commas/dots used as thousands separators before parsing |
