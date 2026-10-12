---
name: financial-analysis
description: >
  Discover, parse, compute, and output financial metrics from company data files.
  Handles content-based file discovery among decoys, flexible schema parsing
  (CSV/JSON/fixed-width/HTML), multi-file joins for balance-sheet metrics,
  conditional branching on threshold checks, and locale-aware numeric cleaning.
---

# Financial Analysis Skill

## Overview

This skill solves tasks that ask you to:
1. Find the correct financial data file(s) for a named company among decoys
2. Parse financial line items (Revenue, Gross Profit, Net Income, etc.) across fiscal years
3. Compute a requested financial metric (or conditionally switch metrics based on a threshold)
4. Write results to a specified output file with the required column schema

## Procedure

### Step 1: Extract Task Parameters

Parse the task instruction to identify:
- **Target company**: company name and any ticker symbols mentioned
- **Data directory**: where to look for files (e.g., `/app/financials/`)
- **Required line items**: which financial figures are needed (Revenue, Gross Profit, Net Income, Operating Income, Shareholders' Equity, etc.)
- **Primary metric**: the metric to compute (see Metric Reference below)
- **Conditional threshold**: if present, the condition that determines which metric to output (e.g., "if most recent year's Gross Margin exceeds 70%")
- **Fallback metric**: if the condition is not met, which alternative metric to compute
- **Output path and schema**: file path, column names, rounding, and percentage format

### Step 2: Discover the Data File(s)

List all files in the target directory (recursively if subdirectories exist). For each file, read its content and compute a **relevance score**:

| Signal | Points | Rationale |
|--------|--------|-----------|
| Company name or ticker appears in content | +3 | Identifies the right entity |
| Required line items present (Revenue, Gross Profit, etc.) | +2 | Contains needed financial data |
| Multi-year tabular structure (≥2 rows with year-like identifiers + numeric data) | +2 | Real financial statements span multiple periods; decoys often have single-year or ad-hoc data |
| Clean, consistent column structure across rows | +1 | Structured data vs. log snippets or notes |

**Selection rules:**
- Pick the file with the **highest score**. 
- If tied, prefer the one with more year rows.
- If the task requires line items from both income statement AND balance sheet (e.g., ROE needs Shareholders' Equity), you may need to select **multiple files** and join them by fiscal year.

**Decoy discrimination heuristics:**
- Files with only quarterly data when annual is needed → lower score
- Files for a different company → exclude
- Log/cache files with embedded data snippets → lower score than structured tables
- Product-level sales data (not company financials) → exclude

### Step 3: Parse the Data

**Format detection** (try in order):
1. **CSV/TSV/delimited**: Look for rows with consistent delimiter-separated columns. Find the header row by detecting a row whose cells match known financial terms.
2. **JSON**: Look for arrays/objects containing financial line items. Traverse to find the data structure.
3. **Fixed-width text**: Detect aligned columns by consistent character positions.
4. **HTML tables**: Parse `<table>`, `<tr>`, `<td>` elements; handle merged headers.

**Header identification:**
- Scan all rows for one where multiple cells match financial term synonyms (see Line Item Synonyms below).
- Skip preamble rows (titles, notes, metadata lines before the actual table).

**Numeric cleaning** — apply to every numeric cell:
```
clean_number(s):
  1. Strip whitespace
  2. Remove currency symbols ($, €, £, ¥)
  3. Remove thousands separators (commas in "26,974" or spaces in "26 974")
  4. Handle unit suffixes: M (millions), B (billions), K (thousands) — multiply accordingly
  5. Handle European locale: if comma is decimal separator (e.g., "26.974,50"), swap
  6. Convert to float
  7. Handle parentheses as negative: "(1,234)" → -1234.0
```

**Fiscal year handling — two separate concerns:**
- **For internal logic** (sorting, finding most recent year, joining across files): extract the integer year from formats like `FY2024`, `2024`, `FY 2024`, `Fiscal 2024`, `Year 2024`, `2024-01`.
- **For output**: preserve the original year label exactly as it appears in the source data (e.g., if source says `FY2024`, write `FY2024`; if source says `2024`, write `2024`). Do NOT convert to integer unless the task instruction explicitly requires a different format.

**Line Item Synonyms** (case-insensitive matching):

| Canonical Name | Synonyms |
|---------------|----------|
| Revenue | Total Revenue, Net Sales, Sales, Total Sales, Net Revenue, Turnover |
| Gross Profit | GP, Gross Margin ($), Gross Income |
| Cost of Revenue | COGS, Cost of Goods Sold, Cost of Sales |
| Operating Income | EBIT, Operating Earnings, Operating Profit |
| Net Income | Net Earnings, Net Profit, Profit After Tax, Bottom Line, Earnings |
| Shareholders' Equity | Stockholders' Equity, Total Equity, Common Equity, Book Value, Net Assets, Total Stockholders Equity |

### Step 4: Compute Metrics

Use the metric formulas from the **Metric Reference** section below.

**General computation pattern:**
1. Compute the **primary metric** for ALL available years.
2. Identify the **most recent year** by maximum fiscal year value (don't assume it's the last row).
3. Evaluate the conditional threshold (if present in the task). **Parse the comparison operator carefully**: "exceeds" means `>`, "at least" means `>=`, "below" means `<`, "does not exceed" means `<=`. Strict vs. non-strict inequality matters.
4. If condition is met → output the primary metric.
5. If condition is NOT met → compute and output the **fallback metric** for all years.
6. If no conditional logic → just output the requested metric.

**Rounding and scale:**
- Express as percentage numbers (e.g., 72.72 means 72.72%) unless the task says otherwise.
- Round to the specified decimal places (default: 2).
- For growth rates, the result is already a percentage by construction.

### Step 5: Validate Results

Before writing output, perform sanity checks:
- **Range check**: Margins should typically be between -100% and +100%. Values outside this range indicate a parsing error (e.g., wrong column matched, unit mismatch).
- **Completeness check**: Ensure all years from the source data are represented in the output.
- **Column match verification**: Confirm that the matched columns actually contain the expected data (e.g., Revenue values should be positive and larger than Gross Profit in most cases).
- **Year label format**: Verify that year labels in the output match the source format (FY2024 vs 2024).

### Step 6: Write Output

- Use the exact column names specified in the task instruction.
- Use the exact file path specified.
- Write as CSV unless another format is specified.
- **fiscal_year column**: preserve the original year label format from the source data (e.g., `FY2024` if that's how it appeared in the source file). Only convert to integer if the task instruction explicitly requires it.
- Ensure metric column contains properly rounded percentage numbers.

---

## Metric Reference

| Metric | Formula | Required Line Items | Notes |
|--------|---------|-------------------|-------|
| gross_margin | (Gross Profit / Revenue) × 100 | Revenue, Gross Profit | Most common profitability metric |
| operating_margin | (Operating Income / Revenue) × 100 | Revenue, Operating Income | Measures operating efficiency |
| net_margin | (Net Income / Revenue) × 100 | Revenue, Net Income | Bottom-line profitability |
| return_on_equity | (Net Income / Shareholders' Equity) × 100 | Net Income, Shareholders' Equity | May require joining income statement + balance sheet files |
| year_over_year_growth | ((Current_year_value - Prior_year_value) / Prior_year_value) × 100 | Any metric value across consecutive years | **Meta-metric**: the task instruction specifies which base value (Revenue, Net Income, Gross Profit, etc.) to compute YoY growth on. If years are not consecutive (e.g., FY2022, FY2024 with FY2023 missing), compute YoY only for pairs where the prior year exists. If no consecutive pairs exist, the task likely wouldn't ask for this metric. |

**Scale invariance:** If both numerator and denominator are in the same units (e.g., both in millions), the ratio is correct regardless of scale. Do NOT convert units unless only one side has a unit suffix.

**Sign conventions:**
- Margins can be negative (losses) — preserve the sign.
- Growth rates can be negative (decline) — preserve the sign.

---

## Multi-File Join Pattern

When the task requires metrics that span income statement and balance sheet (e.g., ROE):

1. Discover files separately — one may contain income statement data, another balance sheet data.
2. Parse each file independently using the same parsing logic.
3. Join on fiscal year (integer year match).
4. If a year exists in one file but not the other, note it but only compute metrics for years where all required data is available.

---

## Implementation Template (Python)

```python
import csv
import re
import os
import json

def clean_number(s):
    """Clean a numeric string to float."""
    s = s.strip()
    # Handle parentheses as negative
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    # Remove currency symbols
    s = re.sub(r'[$€£¥]', '', s)
    # Detect European locale
    # Case 1: comma as decimal with thousands separator (e.g., "1.234,56")
    if re.search(r'\d+\.\d{3},\d{1,2}$', s):
        s = s.replace('.', '').replace(',', '.')
    # Case 2: comma as decimal without thousands separator (e.g., "26974,50")
    elif ',' in s and '.' not in s and re.search(r',\d{1,2}$', s):
        s = s.replace(',', '.')
    else:
        # Remove thousands commas/spaces
        s = s.replace(',', '').replace(' ', '')
    # Handle unit suffixes
    multiplier = 1.0
    if s.upper().endswith('B'):
        multiplier = 1e9; s = s[:-1]
    elif s.upper().endswith('M'):
        multiplier = 1e6; s = s[:-1]
    elif s.upper().endswith('K'):
        multiplier = 1e3; s = s[:-1]
    val = float(s) * multiplier
    return -val if negative else val

def extract_year(s):
    """Extract integer year from various formats."""
    m = re.search(r'(\d{4})', s)
    return int(m.group(1)) if m else None

def find_column(headers, synonyms):
    """
    Find column index matching any synonym.
    Uses priority-based matching to avoid false positives:
    1. Exact match (after normalization)
    2. Header ends with synonym + benign qualifier prefix (total, net, gross, adjusted)
    3. Synonym contains header as word-boundary match (for abbreviations like 'gp')
    """
    norm_headers = [(i, re.sub(r'[\s_]', '', h.lower())) for i, h in enumerate(headers)]
    BENIGN_PREFIXES = {'total', 'net', 'gross', 'adjusted'}
    
    for syn in synonyms:
        syn_clean = re.sub(r'[\s_]', '', syn.lower())
        
        # Phase 1: Exact match
        for i, h_clean in norm_headers:
            if syn_clean == h_clean:
                return i
        
        # Phase 2: Header = benign_prefix + synonym (e.g., 'TotalRevenue')
        for i, h_clean in norm_headers:
            if h_clean.endswith(syn_clean) and len(h_clean) > len(syn_clean):
                prefix = h_clean[:-len(syn_clean)]
                if prefix in BENIGN_PREFIXES:
                    return i
        
        # Phase 3: Abbreviation match (e.g., 'gp' in 'grossprofit')
        for i, h_clean in norm_headers:
            if len(h_clean) >= 2 and h_clean in syn_clean:
                idx = syn_clean.index(h_clean)
                before_ok = (idx == 0 or not syn_clean[idx-1].isalpha())
                after_ok = (idx + len(h_clean) >= len(syn_clean) or not syn_clean[idx+len(h_clean)].isalpha())
                if before_ok and after_ok:
                    return i
    
    return None

SYNONYMS = {
    'revenue': ['revenue', 'total revenue', 'net sales', 'sales', 'total sales', 'net revenue', 'turnover'],
    'gross_profit': ['gross profit', 'gross income', 'gp'],
    'operating_income': ['operating income', 'ebit', 'operating earnings', 'operating profit'],
    'net_income': ['net income', 'net earnings', 'net profit', 'profit after tax'],  # Note: 'earnings' alone is too ambiguous (could match RetainedEarnings)
    'shareholders_equity': ["shareholders' equity", "stockholders' equity", 'total equity', 'common equity', 'book value', 'net assets'],
}
```

---

## Common Pitfalls

1. **Picking the first file that mentions the company name** — decoys may also mention the company. Always score and compare.
2. **Assuming the last row is the most recent year** — sort by extracted year integer and use max().
3. **Forgetting the conditional branch** — always compute the primary metric first, check the condition, then decide which metric to output.
4. **Mixing up percentage and decimal** — margins are ratios; multiply by 100 to get percentage numbers.
5. **Not handling multi-line headers** — the actual data table may start several lines into the file after title/metadata blocks.
6. **Ignoring unit suffixes** — "26,974M" means 26,974 million, not 26,974.
7. **Hardcoding column positions** — always detect columns by header name matching, not by index.
8. **Stripping year prefixes in output** — if the source data says `FY2024`, write `FY2024` in the output, not `2024`. Tests may index by the original label. Use integer extraction only for internal sorting/comparison.
9. **Overly generic column synonyms causing false positives** — e.g., "earnings" matching "RetainedEarnings" (a balance sheet item, not Net Income). Use priority-based matching: exact match first, then qualified compounds (Total+Revenue), then abbreviations. Remove standalone generic terms like "earnings" from synonym lists when they could match unrelated compound headers.
