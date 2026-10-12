---
name: financial-analysis
description: >
  Reusable procedure for extracting financial data from heterogeneous sources
  (CSV, JSON, fixed-width, HTML), computing standard financial metrics
  (gross margin, operating margin, net margin, ROE, YoY growth), applying
  task-specific conditional logic, and producing output in the required
  contract. Handles content-based file discovery among decoys, multi-format
  parsing with locale-aware numeric handling, cross-statement joins by fiscal
  year, and flexible output serialization.
---

# Financial Analysis Skill

## Overview

This skill enables an agent to perform financial metric computation tasks
across a wide variation space: different source formats, statement topologies,
metric types, schema/locale conventions, and output contracts.

## Procedure

### Step 1: Parse the Task Instruction

Extract the following from the task instruction:
- **Target company**: The company name to search for (e.g., "NVIDIA Corporation")
- **Required fields**: Which financial line items are needed (Revenue, Gross Profit, etc.)
- **Target metric**: Which metric to compute (gross_margin, operating_margin, net_margin, return_on_equity, year_over_year_growth)
- **Conditional logic**: The task-specific condition that determines which metric to report (e.g., "if most recent year's gross margin exceeds 70%")
- **Output contract**: Required file path, column names, serialization format, rounding rules

### Step 2: Content-Based File Discovery

**Never trust filenames.** Use content-based scoring to find the correct file(s).

For each file in the target directory:
1. Read its content (try UTF-8, fall back to latin-1)
2. Check if it contains the target company name (case-insensitive substring match)
3. Check if it contains parseable numeric financial data (look for known field labels)
4. **Check temporal granularity**: If the task requires annual data, reject files that contain only quarterly/interim data (look for "quarterly", "Q1", "Q2", "interim", "trimestre", etc.)
5. Score = company_match (boolean) + field_coverage (count of matched financial fields) - temporal_mismatch_penalty
6. Select the highest-scoring file

If the task requires data from multiple statements (e.g., income statement + balance sheet for ROE), select the top-scoring file for each required statement type.

Use `scripts/discover_file.py` as a reference implementation.

### Step 3: Parse Financial Data

Handle multiple source formats:

| Format | Detection | Parsing Strategy |
|--------|-----------|-----------------|
| CSV | Has comma-separated header row | Use csv.DictReader or pandas |
| JSON | Starts with `{` or `[` | Navigate nested structure, flatten to records |
| Fixed-width | Aligned columns, no delimiters | Detect column positions from header alignment |
| HTML | Contains `<table>` tags | Parse table rows, handle merged headers (rowspan/colspan) |
| Log/mixed | Contains data lines mixed with metadata | Extract data lines by pattern matching |

**Schema and Locale Handling:**
- Build a synonym map for each financial concept (see `references/metrics.md`)
- Match field labels against synonym sets (case-insensitive, strip whitespace)
- Parse numbers by: stripping currency symbols ($, €, £), removing thousands separators (commas, spaces, dots depending on locale), handling parentheses for negatives `(1,234)` → `-1234`
- **Year labels: dual tracking.** Normalize year labels to integers **for internal use** (sorting, joining, computing). But **always preserve the original label string** from the source data for output purposes. For example, if the source says `FY2022`, store both `int_year=2022` (for computation) and `original_label="FY2022"` (for output). The parser returns both: `(data, year_labels)` where `data` is keyed by int and `year_labels` maps int→original string.

Use `scripts/parse_financials.py` as a reference implementation.

### Step 4: Join Across Statements (if needed)

When `statement_topology` requires data from multiple files:
1. Parse each file independently
2. Identify the join key (usually fiscal year)
3. Normalize year labels across files to a common format
4. Join on fiscal year, keeping only years present in all required statements

### Step 5: Compute the Metric

Use the metric registry (see `scripts/compute_metrics.py` and `references/metrics.md`):

| Metric | Formula | Scale |
|--------|---------|-------|
| gross_margin | Gross Profit / Revenue | ×100, round to 2dp |
| operating_margin | Operating Income / Revenue | ×100, round to 2dp |
| net_margin | Net Income / Revenue | ×100, round to 2dp |
| return_on_equity | Net Income / Shareholders' Equity | ×100, round to 2dp |
| year_over_year_growth | (Revenue_t - Revenue_{t-1}) / Revenue_{t-1} | ×100, round to 2dp |

All metrics are expressed as **percentage numbers** (e.g., 72.72 means 72.72%, not 0.7272).

### Step 6: Apply Conditional Logic

The task instruction specifies a condition that determines which metric to report.
Common patterns:
- "If [metric] for [year] exceeds [threshold], compute [metric_A]; else compute [metric_B]"
- "If [condition], report [X]; otherwise report [Y]"

Extract and evaluate the condition at runtime. Do NOT hardcode the conditional.

**Critical: The conditional determines the output schema, not just the metric.** When the condition branches between metrics, the output column name typically changes to match the selected metric. For example:
- True branch → compute gross_margin → output column: `gross_margin_pct`
- False branch → compute net_margin → output column: `net_margin_pct`

Always extract the output column names from the task instruction for **both branches** of the conditional. The column name is part of the output contract, not an afterthought.

### Step 7: Write Output

Match the output contract exactly:
- File path as specified
- Column names as specified (e.g., `fiscal_year,gross_margin_pct`)
- **The `fiscal_year` column must contain the original year label exactly as it appeared in the source data** (e.g., `FY2022`, not `2022`). If the source uses `FY2022`, write `FY2022`. If it uses `2022`, write `2022`. If it uses `Year Ended Jan 2025`, write that. Never strip prefixes or normalize labels in the output.
- One row per fiscal year, in chronological order (sorted by integer year)
- Percentages as numbers rounded to 2 decimal places
- Include a header row with the exact column names specified

## Key Principles

1. **Content over filenames**: Always verify file contents, never assume from names
2. **Synonym matching**: Financial concepts appear under many labels; use synonym sets
3. **Locale-aware parsing**: Numbers may use different thousands/decimal separators
4. **Metric registry**: Each metric has a precise formula; do not invent formulas
5. **Runtime conditionals**: Extract logic from the task, never hardcode
6. **Exact output contract**: Match column names, format, and path precisely
7. **Preserve source labels in output**: Internal computation uses normalized integers for years, but the output must use the original label strings from the source data (e.g., `FY2022` not `2022`). Never destroy source information that the output contract may reference.
8. **Conditional output schema**: When a conditional branches between metrics, the output column name changes with the branch. Extract both column names from the task instruction.
9. **Use scripts for complex parsing**: For simple CSV files with clear headers, manual extraction may suffice. For mixed-format files, HTML tables, nested JSON, fixed-width data, or files with decoy content, use `scripts/parse_financials.py` and `scripts/discover_file.py` to avoid errors.
