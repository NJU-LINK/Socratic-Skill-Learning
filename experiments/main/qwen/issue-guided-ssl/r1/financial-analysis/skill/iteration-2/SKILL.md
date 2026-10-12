---
name: financial-analysis
description: >
  Reusable 5-stage pipeline for financial data analysis tasks: discover the
  correct data file among decoys, parse heterogeneous formats (CSV, JSON,
  fixed-width, decorated text, HTML), canonicalize schemas via synonym mapping,
  compute standard financial metrics with conditional branching, and serialize
  results per the output contract.
---

# Financial Analysis Skill

## ⚡ Quick Start — EXECUTE THE PIPELINE SCRIPT

**Do NOT manually extract data or write inline code.** The pipeline script handles everything.

```bash
python3 /skill/scripts/pipeline.py \
    --source-dir <DATA_DIRECTORY> \
    --company "<COMPANY_NAME>" \
    --ticker <TICKER> \
    --metric <METRIC_NAME> \
    --conditional "<CONDITIONAL_RULE>" \
    --output-path <OUTPUT_PATH> \
    --output-columns <COLUMN_NAMES> \
    --round <DECIMAL_PLACES>
```

**Extract parameters from the task instruction:**
- `--source-dir`: The directory mentioned in the task (e.g., `/app/financials`)
- `--company`: The target company name from the task
- `--ticker`: The company ticker if mentioned (optional)
- `--metric`: The primary metric to compute (e.g., `gross_margin`, `net_margin`)
- `--conditional`: If the task says "if X > Y then A else B", format as: `"if latest <metric> > <threshold> then <metric_a> else <metric_b>"`
- `--output-path`: The output file path from the task (e.g., `/app/results.csv`)
- `--output-columns`: The column names from the task (e.g., `fiscal_year,gross_margin_pct`)
- `--round`: Decimal places for rounding (default: 2)

**Example for v01 task:**
```bash
python3 /skill/scripts/pipeline.py \
    --source-dir /app/financials \
    --company "NVIDIA Corporation" \
    --ticker NVDA \
    --metric gross_margin \
    --conditional "if latest gross_margin > 70 then gross_margin else net_margin" \
    --output-path /app/results.csv \
    --output-columns fiscal_year,gross_margin_pct \
    --round 2
```

## Overview

This skill implements a **5-stage pipeline** for extracting, analyzing, and
reporting financial metrics from heterogeneous data sources. It handles the
full variation space defined by the spec: different source representations,
statement topologies, metric types, schema variations, and output contracts.

**The pipeline script (`scripts/pipeline.py`) is the primary execution tool.** It automates all 5 stages and handles format detection, decoy filtering, schema normalization, metric computation, and output serialization.

## Pipeline Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  1. DISCOVER │───▶│   2. PARSE   │───▶│ 2.5 JOIN     │───▶│  3. CANONICAL│───▶│  4. COMPUTE  │
│  Find all    │    │  Read format │    │  Merge multi │    │  Map to std  │    │  Metric +    │
│  matching    │    │  dynamically │    │  file data   │    │  schema      │    │  conditional │
│  files       │    │              │    │  by year     │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                                                                        │
                                                                                    ┌───▼──────────┐
                                                                                    │  5. OUTPUT   │
                                                                                    │  Serialize   │
                                                                                    │  per contract│
                                                                                    └──────────────┘
```

### Stage 1: DISCOVER — Content-Based File Discovery

**Goal**: Find the authoritative data file for the target company, ignoring decoys.

**Method**:
1. Scan all files in the source directory
2. Search file **content** (not filenames) for the target company name or ticker
3. Score candidates by tabular data density (rows with numeric data) vs. log/cache markers
4. Select the highest-scoring file

**Decoy Awareness**: Financial directories often contain:
- Cache/log files with plausible but stale numbers (e.g., `[DATA] FY2024: Revenue=$58,000M`)
- Files for different companies (e.g., AMD data when NVIDIA is requested)
- Quarterly-only data when annual is needed
- Summary files with incomplete data

**Heuristic**: The authoritative source has the most complete structured table with
year-over-year data, not log-style annotations or partial summaries.

### Stage 2: PARSE — Format-Agnostic Parsing

**Goal**: Extract headers and data rows regardless of file format.

**Supported formats**:
| Format | Detection Signal | Parsing Strategy |
|--------|-----------------|------------------|
| CSV | Comma-separated with header row | Standard CSV parser |
| JSON | Starts with `{` or `[` | `json.loads` → extract array of objects |
| HTML | Contains `<table>` tags | Regex-based table cell extraction |
| Decorated text | `=====`, `-----` borders | Strip decoration, find header, parse as CSV |
| Fixed-width | Aligned columns by whitespace | Detect column boundaries |

**Key insight**: Detect format by **inspecting content**, not file extension. A `.dat`
file may be decorated text; a `.txt` file may contain CSV.

### Stage 3: CANONICALIZE — Schema Normalization

**Goal**: Map variant header labels to a standard schema.

**Standard fields**:
- `fiscal_year` — Year/period identifier (preserved as string)
- `revenue` — Total revenue / net sales
- `gross_profit` — Revenue minus cost of revenue
- `operating_income` — Gross profit minus operating expenses
- `net_income` — Final profit after all expenses and taxes
- `shareholders_equity` — Book value / total equity

**Normalization strategy**:
1. Direct lookup in synonym dictionary (case-insensitive)
2. Strip separators (underscores, hyphens, spaces) and retry
3. Split camelCase/PascalCase (`GrossProfit` → `gross profit`)
4. Substring matching as fallback

**Synonym examples**:
- Revenue: "Total Revenue", "Net Sales", "Sales", "Turnover", "Ventas"
- Gross Profit: "GP", "Gross Income", "Bénéfice brut"
- Net Income: "NI", "Net Profit", "Bottom Line", "Beneficio Neto"

### Stage 4: COMPUTE — Metric Calculation with Conditional Logic

**Metric formulas** (all expressed as percentages):

| Metric | Numerator | Denominator | Formula |
|--------|-----------|-------------|---------|
| `gross_margin` | Gross Profit | Revenue | GP / Revenue × 100 |
| `operating_margin` | Operating Income | Revenue | OI / Revenue × 100 |
| `net_margin` | Net Income | Revenue | NI / Revenue × 100 |
| `return_on_equity` | Net Income | Shareholders' Equity | NI / Equity × 100 |
| `year_over_year_growth` | Current − Prior | Prior | (Curr − Prior) / |Prior| × 100 |

**Note on year_over_year_growth**: The `--growth-field` parameter specifies which field to compute growth on (default: `revenue`). For example, `--metric year_over_year_growth --growth-field net_income` computes YoY growth of net income instead of revenue.

**Conditional branch pattern**:
Many tasks require: "Compute metric A; if latest year's value exceeds threshold T,
report A for all years; otherwise compute and report metric B instead."

Implementation:
1. Compute the primary metric for all years
2. Check the latest year's value against the threshold
3. If condition met → report primary metric
4. If not → compute and report the fallback metric

**Rounding**: All percentages rounded to specified decimal places (default: 2).

### Stage 5: OUTPUT — Serialization per Contract

**Goal**: Write results in the format specified by the task.

**Supported output formats**:
- CSV (default) — with configurable column names
- JSON — array of objects

**Column naming**: Read from the task instruction. Common patterns:
- `fiscal_year,gross_margin_pct`
- `year,net_margin_percent`
- `period,operating_margin`

## Usage

```bash
python scripts/pipeline.py \
    --source-dir /app/financials \
    --company "NVIDIA Corporation" \
    --ticker NVDA \
    --metric gross_margin \
    --conditional "if latest gross_margin > 70 then gross_margin else net_margin" \
    --output-path /app/results.csv \
    --output-columns fiscal_year,gross_margin_pct \
    --round 2
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--source-dir` | Yes | — | Directory containing financial data files |
| `--company` | Yes | — | Target company name (for content-based discovery) |
| `--ticker` | No | None | Company ticker symbol (additional discovery signal) |
| `--metric` | No | gross_margin | Metric to compute (without conditional) |
| `--conditional` | No | None | Conditional rule string |
| `--output-path` | No | /app/results.csv | Output file path |
| `--output-columns` | No | fiscal_year,{metric}_pct | Comma-separated column names |
| `--round` | No | 2 | Decimal places for rounding |
| `--growth-field` | No | revenue | Field for YoY growth (revenue, net_income, gross_profit, etc.) |

## Variation Handling

This skill addresses all spec axes:

1. **source_representation**: Stage 2 detects format from content, not extension. Handles CSV, JSON, HTML, decorated text, and fixed-width formats.
2. **statement_topology**: Stage 1 discovers ALL matching files; Stage 2.5 joins records by fiscal_year across multiple files (e.g., income statement + balance sheet).
3. **financial_metric**: Stage 4 implements all 5 metrics with correct formulas:
   - `gross_margin` = Gross Profit / Revenue
   - `operating_margin` = Operating Income / Revenue
   - `net_margin` = Net Income / Revenue
   - `return_on_equity` = Net Income / Shareholders' Equity
   - `year_over_year_growth` = (Current Revenue − Prior Revenue) / Prior Revenue
4. **schema_and_locale**: Stage 3 handles synonym mapping, camelCase, multi-language headers.
5. **output_contract**: Stage 5 serializes per specified columns and format (CSV or JSON).

## Common Pitfalls

1. **DO NOT hardcode data values.** Always run the pipeline script. The script discovers files, parses data, and computes metrics automatically. Hardcoding values from manual inspection is fragile and non-reusable.
2. **Decoy files**: Always verify the file contains structured tabular data, not just
   company name mentions. Cache/log files often contain stale or fabricated numbers.
3. **Numeric parsing**: Handle currency symbols ($, €), thousands separators (commas),
   European decimal format (1.234,56), and magnitude suffixes (M, B, K).
4. **Year formatting**: Preserve original year labels (FY2022, 2022, 2021-2022) as
   strings rather than converting to floats.
5. **Percentage scale**: Metrics are expressed as percentages (72.72 means 72.72%,
   not 0.7272) unless the instruction specifies otherwise.
6. **Conditional evaluation**: The threshold check applies to the **most recent** year
   only, not all years.

## Parsing Task Instructions → Pipeline Parameters

Common task phrasings and their pipeline equivalents:

| Task says | Pipeline parameter |
|-----------|------------------|
| "find data for NVIDIA Corporation" | `--company "NVIDIA Corporation"` |
| "in /app/financials/ directory" | `--source-dir /app/financials` |
| "Calculate Gross Margin" | `--metric gross_margin` |
| "Gross Margin = Gross Profit / Revenue" | (formula already encoded in pipeline) |
| "If most recent year's GM exceeds 70%" | `--conditional "if latest gross_margin > 70 then gross_margin else ..."` |
| "calculate Net Margin instead" | `... else net_margin"` |
| "write to /app/results.csv" | `--output-path /app/results.csv` |
| "columns: fiscal_year,gross_margin_pct" | `--output-columns fiscal_year,gross_margin_pct` |
| "Round to 2 decimal places" | `--round 2` |
| "ticker NVDA" | `--ticker NVDA` |
| "year-over-year growth of revenue" | `--metric year_over_year_growth` (default growth-field) |
| "year-over-year growth of net income" | `--metric year_over_year_growth --growth-field net_income` |
| "year-over-year growth of gross profit" | `--metric year_over_year_growth --growth-field gross_profit` |
| "YoY growth in operating income" | `--metric year_over_year_growth --growth-field operating_income` |

## References

- `scripts/pipeline.py` — Complete 5-stage pipeline implementation
