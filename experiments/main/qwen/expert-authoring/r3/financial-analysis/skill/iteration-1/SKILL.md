---
name: financial-analysis
description: >
  Discover, parse, and analyze financial statement data from heterogeneous
  source files (CSV, fixed-width text, JSON, HTML) to compute standard
  profitability metrics with conditional branching and structured output.
---

# Financial Analysis

## Overview

This skill covers end-to-end financial analysis tasks where you must:
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
| CSV | Consistent comma/tab delimiters, header row with field names |
| Fixed-width / Banner text | Decorative lines (`===`, `---`), but CSV data embedded within |
| JSON | Opens with `{` or `[`, parse with `json.loads()` |
| HTML table | `<table>`, `<tr>`, `<td>` tags; use BeautifulSoup or regex |

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

Each metric below specifies its exact numerator, denominator, and sign/scale
conventions.

| Metric | Formula | Notes |
|--------|---------|-------|
| **Gross Margin** | `Gross Profit / Revenue × 100` | Percentage scale |
| **Operating Margin** | `Operating Income / Revenue × 100` | Percentage scale |
| **Net Margin** | `Net Income / Revenue × 100` | Percentage scale |
| **Return on Equity (ROE)** | `Net Income / Total Equity × 100` | Percentage scale; requires balance-sheet equity |
| **Year-over-Year Growth** | `(Current − Prior) / \|Prior\| × 100` | Percentage scale; undefined for the earliest year |

### Calculation Rules
- **Scale**: All margin/growth metrics are expressed as percentage numbers
  (e.g., 72.72 means 72.72%, not 0.7272) unless the output contract explicitly
  requests decimal form.
- **Rounding**: Round to 2 decimal places using standard round-half-to-even
  (`round()` in Python) unless otherwise specified.
- **Sign**: Preserve natural sign. A negative margin is a valid result.
- **Division by zero**: If denominator is 0, output `N/A` or `null` unless the
  task specifies otherwise.

### Conditional Branching
Many tasks include a threshold condition that determines which metric to compute
or which subset of years to include. Common patterns:

- **Threshold check**: "If the most recent year's metric X exceeds N%, compute
  X for all years; otherwise compute metric Y instead."
- **Selective years**: "Compute only for years where revenue > $X."

**Approach**: Always compute the check value first, evaluate the condition,
then proceed with the full calculation accordingly. Print the branching decision
for traceability.

---

## Phase 4 — Output

### Default Output Format
Unless the task specifies otherwise, write results to `/app/results.csv`:

```
fiscal_year,gross_margin_pct
FY2022,64.93
FY2023,56.93
...
```

### Output Rules
1. **Column names**: Use the exact names specified in the task's output contract.
   If none specified, use `fiscal_year,<metric_name>_pct`.
2. **Row order**: Sort by fiscal year ascending (earliest first) unless told
   otherwise.
3. **Encoding**: UTF-8, no BOM.
4. **Line endings**: Standard newline (`\n`), no trailing blank line.
5. **Verification**: After writing, read back the file and print it to confirm
   correctness.

### Self-Verification Checklist
Before declaring the task complete:
- [ ] Correct source file identified (matches target company/entity)?
- [ ] All required years/periods present in the output?
- [ ] Metric formula applied correctly (numerator / denominator)?
- [ ] Percentage scale correct (not off by 100×)?
- [ ] Rounding applied consistently?
- [ ] Conditional branch evaluated correctly?
- [ ] Output file exists at the specified path with correct schema?
- [ ] Spot-check at least one value manually against the source data?

---

## Common Pitfalls

| Pitfall | Prevention |
|---------|-----------|
| Using a decoy file | Always inspect content, not just filenames |
| Using stale/cached values from log files | Only use primary source data files |
| Off-by-100 error (decimal vs percentage) | Confirm scale: output should be ~50–80 for margins, not 0.5–0.8 |
| Wrong metric computed | Re-read the conditional branch logic carefully |
| Mixing quarterly and annual data | Check period labels; aggregate only if instructed |
| Incorrect rounding | Apply rounding only at the final step, not intermediate |
| Multi-file join on mismatched year keys | Normalize year labels before joining |

---

## Worked Strategy for Single-Company Margin Tasks

```
1. ls -R <data_dir>  → list all candidate files
2. For each file:
     head -30 <file> → check company name + field names
3. Select file where company matches AND required fields present
4. Parse data block:
     - Skip banner/decoration lines
     - Find CSV header row
     - Read rows into list of dicts
5. Identify the most recent fiscal year
6. Compute the check metric for that year
7. Evaluate the threshold condition → decide which metric to compute
8. Compute chosen metric for ALL years
9. Round to 2 decimal places
10. Write to /app/results.csv (or specified path)
11. cat results file to verify
```

This generalizes across all instances in the family regardless of source format,
metric type, or branching condition.
