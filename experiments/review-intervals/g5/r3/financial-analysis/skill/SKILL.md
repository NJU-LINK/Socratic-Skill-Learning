---
name: financial-analysis
description: Methodology for extracting, computing, and outputting financial metrics from heterogeneous data sources with conditional logic
---

# Financial Analysis Skill

This skill teaches a **generalizable methodology** for solving financial analysis tasks. The procedure works across all variants in the family, regardless of data format, metric type, or conditional logic.

## Core Procedure

Follow these steps in order. Each step handles a specific variation axis from the task family.

### Step 1: Discover the Correct Data File

**Problem**: The data directory contains multiple files, including decoys. You must identify which file contains the target company's financial data.

**Method**:
1. List all files in the data directory
2. Read each file's content
3. Check if the file contains the target company name (case-insensitive match)
4. Verify the file contains financial data (keywords: revenue, income, profit, equity, assets)
5. Reject files that:
   - Mention a different company
   - Contain only quarterly data when annual is required
   - Lack financial keywords
   - Are cache/log files with misleading numbers

**Example**: When searching for a target company:
- `product_sales.csv` → contains product data, no company name → REJECT
- `analysis_cache.txt` → contains cached results with potentially stale numbers → REJECT  
- `competitor_data.dat` → contains different company's data → REJECT (wrong company)
- `financial_report.dat` → contains target company name → ACCEPT

### Step 2: Parse the Data

**Problem**: Data may be in CSV, JSON, fixed-width, HTML, or embedded CSV in `.dat` files with decorative borders.

**Method**:
1. Read the file content
2. Find the CSV header line by looking for a line containing:
   - Commas (or other delimiters)
   - Recognizable financial field names (Year, Revenue, GrossProfit, NetIncome, etc.)
3. Extract headers and map them to canonical field names (see Field Normalization below)
4. Parse data rows, skipping:
   - Empty lines
   - Decorative lines (starting with `=`, `#`, `---`)
   - Notes sections
5. Convert numeric values to floats, handling:
   - Currency symbols ($, €, £)
   - Thousands separators (commas in US format)
   - European decimal format (comma as decimal separator)
   - Parentheses for negative numbers

**Field Normalization**: Map varying labels to canonical names:
- `revenue`: Revenue, Total Revenue, Sales, Net Sales, Umsatz
- `gross_profit`: GrossProfit, Gross Profit, GP, Bruttoergebnis
- `operating_income`: OperatingIncome, Operating Income, EBIT
- `net_income`: NetIncome, Net Income, Net Profit, Earnings
- `shareholders_equity`: Shareholders Equity, Equity, Stockholders Equity
- `fiscal_year`: Year, Fiscal Year, FY, Period

### Step 3: Extract Financial Values

**Problem**: You need specific fields (Revenue, Gross Profit, Net Income, etc.) for each fiscal year.

**Method**:
1. For each data row, extract:
   - `fiscal_year`: The year label (e.g., "FY2024", "2024")
   - `revenue`: Total revenue/sales
   - `gross_profit`: Gross profit (if needed for gross margin)
   - `operating_income`: Operating income (if needed for operating margin)
   - `net_income`: Net income (if needed for net margin or ROE)
   - `shareholders_equity`: Shareholders' equity (if needed for ROE)
2. Sort records by fiscal year (ascending)
3. Verify all required fields are present for the requested metric

### Step 4: Compute the Requested Metric

**Problem**: The task specifies which metric to compute. You must use the correct formula.

**Metric Formulas** (these are invariants across all variants):

```
gross_margin = (Gross Profit / Revenue) × 100
operating_margin = (Operating Income / Revenue) × 100
net_margin = (Net Income / Revenue) × 100
return_on_equity = (Net Income / Shareholders' Equity) × 100
year_over_year_growth = ((Current Year Value - Prior Year Value) / |Prior Year Value|) × 100
```

**Method**:
1. Identify the requested metric from the instruction
2. Apply the corresponding formula to each record
3. Round to the specified number of decimal places (usually 2)
4. Express as percentage (multiply by 100), not decimal

**Example**: If instruction says "Calculate Gross Margin", use:
```python
gross_margin = (gross_profit / revenue) * 100
```

### Step 5: Apply Conditional Logic (if present)

**Problem**: Some tasks include conditional logic like "If X exceeds Y%, use metric A; else use metric B."

**Method**:
1. Parse the conditional from the instruction:
   - Identify the check metric (e.g., "Gross Margin")
   - Identify the threshold (e.g., "70%")
   - Identify the comparison operator (e.g., "exceeds" = `>`)
   - Identify the fallback metric (e.g., "Net Margin")
2. Compute the check metric for the most recent year
3. Evaluate the condition:
   - If TRUE: Use the primary metric for all years
   - If FALSE: Use the fallback metric for all years
4. Output the appropriate metric based on the condition result

**Critical**: The fallback metric is introduced by negation signals like:
- "If it does NOT exceed..."
- "Otherwise..."
- "Else..."
- "If not..."

Do NOT match the first "calculate" verb after the threshold — match the one after the negation signal.

**Example**:
```
Instruction: "If most recent year's Gross Margin exceeds 70%, calculate Gross Margin for all years.
              If it does NOT exceed 70%, calculate Net Margin for all years instead."

Steps:
1. Compute Gross Margin for most recent year
2. If GM > 70%: output Gross Margin for all years
3. If GM <= 70%: output Net Margin for all years
```

### Step 6: Write Output

**Problem**: The task specifies output path, column names, and format.

**Method**:
1. Identify output path from instruction (e.g., "/app/results.csv")
2. Identify column names from instruction (e.g., "fiscal_year,gross_margin_pct")
3. Write data in the specified format:
   - CSV: Use `csv.writer` with specified columns
   - JSON: Use `json.dump` with list of dicts
   - TSV: Use `csv.writer` with `delimiter='\t'`
4. Ensure values are rounded to specified decimal places
5. Ensure percentages are expressed as numbers (e.g., 65.43), not decimals (0.6543)

## Key Invariants

These properties are constant across all variants in the family:

1. **Metric formulas**: The formulas for gross_margin, operating_margin, net_margin, ROE, and YoY growth are standard financial definitions
2. **Percentage scale**: All metrics are expressed as percentages (×100), not decimals
3. **Rounding**: Values are rounded to 2 decimal places (unless instruction specifies otherwise)
4. **Fiscal year ordering**: Data is sorted by fiscal year (ascending)
5. **Conditional evaluation**: The condition is evaluated on the most recent year's value

## Key Variations

These properties vary across variants (per spec.yaml):

1. **source_representation**: CSV, JSON, fixed-width, HTML, embedded CSV
2. **statement_topology**: Single file or multi-file joins
3. **financial_metric**: Which metric to compute (gross_margin, operating_margin, etc.)
4. **schema_and_locale**: Field labels, number formats, languages
5. **output_contract**: Column names, file format, output path

## Reference Implementation

A Python script implementing this methodology is provided at `financial_analysis.py`. It handles:
- Multi-format parsing (CSV, JSON, fixed-width, HTML)
- Field normalization (50+ aliases → 6 canonical names)
- Locale-aware number parsing (US & European formats)
- Instruction parsing with conditional logic
- File discovery with decoy rejection

**Usage**:
```bash
python3 financial_analysis.py --instruction "Task instruction text" --data-dir /app/financials/ --output /app/results.csv
```

However, for simple cases, you can implement the procedure inline with a short Python snippet following the 6-step methodology above.

## Quick Start Template

For most variants, use this minimal template. It's shorter than hardcoding and works for ANY variant:

```python
import csv, os, re

# Extract from instruction
TARGET_COMPANY = "[Company Name from instruction]"
DATA_DIR = "[directory path from instruction]"
OUTPUT_PATH = "[output path from instruction]"
OUTPUT_COLUMNS = ["fiscal_year", "[metric_name]_pct"]

# Step 1: Find correct file
correct_file = None
for fname in os.listdir(DATA_DIR):
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.isfile(fpath):
        continue
    with open(fpath, 'r', errors='replace') as f:
        if TARGET_COMPANY.lower() in f.read().lower():
            correct_file = fpath
            break

# Step 2: Parse data (find CSV header)
with open(correct_file) as f:
    lines = f.readlines()

header_idx = next(i for i, line in enumerate(lines) 
                  if 'Year' in line and 'Revenue' in line and ',' in line)
headers = [h.strip() for h in lines[header_idx].split(',')]

records = []
for line in lines[header_idx+1:]:
    line = line.strip()
    if not line or line.startswith('=') or line.upper().startswith('NOTE'):
        continue
    parts = [p.strip() for p in line.split(',')]
    if len(parts) == len(headers) and re.match(r'(FY)?\d{4}', parts[0]):
        records.append(dict(zip(headers, parts)))

# Step 3: Extract and compute
for r in records:
    r['revenue'] = float(r.get('Revenue', 0))
    r['gross_profit'] = float(r.get('GrossProfit', 0))
    r['net_income'] = float(r.get('NetIncome', 0))
    # Add other fields as needed

# Step 4: Apply formula from instruction
# Example: gross_margin = (gross_profit / revenue) * 100
# Use the formula specified in the task

# Step 5: Evaluate conditional (if present)
# Check most recent year's value against threshold
# Choose primary or fallback metric accordingly

# Step 6: Write output
with open(OUTPUT_PATH, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(OUTPUT_COLUMNS)
    for r in records:
        writer.writerow([r['Year'], round(r['computed_metric'], 2)])
```

**When to use the full script instead**: Use `financial_analysis.py` for complex cases:
- JSON or HTML data sources
- Multi-file joins (income statement + balance sheet)
- Unusual number formats (European locale, mixed formats)
- Complex conditional logic with multiple thresholds

## Common Pitfalls

1. **Answer leakage**: Do NOT hardcode v01-specific values. The methodology works for ANY variant.
2. **Decoy files**: Always verify the file contains the target company, not just financial keywords.
3. **Conditional parsing**: Match the fallback metric after the negation signal, not the first "calculate" verb.
4. **Number formats**: Handle both US (1,234.56) and European (1.234,56) formats correctly.
5. **Percentage scale**: Multiply by 100 to convert to percentage, don't output raw ratios.

## Testing Your Solution

After writing output, verify:
1. ✓ Correct file was selected (contains target company)
2. ✓ All fiscal years are present
3. ✓ Metric formula is correct for the requested metric
4. ✓ Conditional logic was evaluated correctly (if present)
5. ✓ Values are rounded to specified decimal places
6. ✓ Output format matches instruction (CSV/JSON/TSV, correct columns)
