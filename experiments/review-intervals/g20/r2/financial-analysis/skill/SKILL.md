---
name: financial-analysis
description: Extract financial data from various sources, calculate standard financial metrics with conditional logic, and produce formatted output files
---

# Financial Analysis Skill

## Purpose
Extract company financial data from heterogeneous sources, compute standard financial metrics (margins, returns, growth rates), apply conditional logic based on thresholds, and produce correctly formatted output files.

## Core Workflow

### 1. Data Discovery and Validation
- **Explore the data directory** to identify all available files
- **Identify the target company** by examining file contents, headers, and metadata
- **Distinguish real data from decoys** by checking for:
  - Company name/ticker matches
  - Complete annual data (not quarterly-only)
  - Relevant financial line items
  - **Raw data vs pre-computed metrics**: Files containing pre-computed percentages (e.g., "Gross Margin for FY2024: 65.24%") are often decoys or cached results. Always prefer files with raw financial figures (Revenue, Gross Profit, Net Income) over files with pre-calculated ratios.
- **Verify data completeness** - ensure all required fields are present for the requested metric
- **Read ALL files**: Don't stop at the first file that looks plausible. Examine every file to confirm which one has the correct company's raw data.

### 2. Data Extraction and Cross-File Joins

#### ⚠️ CRITICAL: Programmatic Parsing Required
**NEVER hard-code financial values from the file into your script.** Always parse the file programmatically. Hard-coding works for v01 but fails on any variant with different data.

**Wrong approach (iteration 1 failure mode):**
```python
# ❌ FORBIDDEN: Hard-coded values from reading the file
data = [
    ("FY2022", 26914, 17475),
    ("FY2023", 26974, 15356),
    # ... manually transcribed from file
]
```

**Correct approach:**
```python
# ✅ REQUIRED: Parse the file dynamically
with open(filepath, 'r') as f:
    content = f.read()
# Then extract data using regex, CSV parsing, JSON parsing, etc.
```

#### Single-File Extraction
Handle multiple source formats:
- **CSV files**: Parse with standard CSV reader, handle varying column orders
- **Fixed-width text**: Identify data rows by pattern matching, extract numeric values
- **Nested JSON**: Navigate structure to find financial statements
- **HTML tables**: Parse table structure, handle merged headers

**Key extraction principles:**
- Normalize field names (e.g., "Revenue", "Total Revenue", "Sales" → revenue)
- Handle different numeric formats (commas, currency symbols, parentheses for negatives)
- Identify fiscal year labels (FY2024, 2024, 2024-01, etc.)
- Convert all monetary values to consistent units (millions, billions, or raw)

**Universal Parsing Template** (schema-agnostic):
```python
import csv
import re
import os

# Step 0: Define field synonym map for schema normalization
FIELD_SYNONYMS = {
    'year':           ['year', 'fiscal year', 'fy', 'period', 'date'],
    'revenue':        ['revenue', 'total revenue', 'net sales', 'sales', 'net revenue'],
    'gross_profit':   ['gross profit', 'gross margin', 'gp'],
    'operating_income': ['operating income', 'operating profit', 'op income', 'oi'],
    'net_income':     ['net income', 'net earnings', 'net profit', 'ni'],
    'equity':         ['shareholders equity', 'stockholders equity', 'equity', 'total equity'],
}

def normalize_headers(actual_headers):
    """Map actual header names → canonical field names.
    CRITICAL: Normalize both sides by stripping non-alphanumeric chars to handle PascalCase/camelCase/spacing variations."""
    mapping = {}
    for actual in actual_headers:
        key = actual.lower().strip()
        # Remove non-alphanumeric chars for matching (handles PascalCase, spaces, etc.)
        key_normalized = re.sub(r'[^a-z0-9]', '', key)
        for canonical, synonyms in FIELD_SYNONYMS.items():
            for syn in synonyms:
                syn_normalized = re.sub(r'[^a-z0-9]', '', syn)
                if syn_normalized == key_normalized or syn_normalized in key_normalized:
                    mapping[actual] = canonical
                    break
            if actual in mapping:
                break
    return mapping

def parse_number(val):
    """Handle $, commas, parentheses-for-negatives, units."""
    s = str(val).strip().replace(',', '').replace('$', '').replace('€', '').replace('£', '')
    if s.startswith('(') and s.endswith(')'):
        return -float(s[1:-1])
    return float(s) if s else 0.0

# Step 1: Find correct file
target_company = "NVIDIA"  # or whatever the task specifies
for fname in os.listdir(financials_dir):
    with open(os.path.join(financials_dir, fname), 'r') as f:
        content = f.read()
    if target_company.lower() in content.lower():
        # Check it's annual data, not quarterly
        if 'quarter' in content.lower() and 'annual' not in content.lower():
            continue
        correct_file = fname
        break

# Step 2: Detect header (format-agnostic)
lines = content.strip().split('\n')
header_idx = None
for i, line in enumerate(lines):
    tokens = [re.sub(r'[^a-z0-9]', '', t.strip().lower()) for t in line.split(',')]
    # Count how many tokens match known field synonyms
    matches = sum(1 for t in tokens if any(
        re.sub(r'[^a-z0-9]', '', syn) in t
        for syns in FIELD_SYNONYMS.values() for syn in syns
    ))
    if matches >= 2:  # At least 2 recognized fields
        header_idx = i
        break

if header_idx is None:
    raise ValueError("Could not find CSV header with recognized financial fields")

# Step 3: Parse headers and map to canonical names
headers = [h.strip() for h in lines[header_idx].split(',')]
col_idx = {h: i for i, h in enumerate(headers)}
hmap = normalize_headers(headers)
# hmap: {'Year': 'year', 'Revenue': 'revenue', 'GrossProfit': 'gross_profit', ...}

# === CRITICAL VALIDATION: Check hmap completeness ===
# This prevents silent failures where missing fields default to 0
mapped_fields = set(hmap.values())
print(f"Mapped fields: {mapped_fields}")

# Define required fields for each metric family
REQUIRED_FIELDS = {
    'gross_margin': {'year', 'revenue', 'gross_profit'},
    'net_margin':   {'year', 'revenue', 'net_income'},
    'operating_margin': {'year', 'revenue', 'operating_income'},
    'roe':          {'year', 'net_income', 'equity'},
}

# Check which metrics can be computed with available fields
computable = {}
for metric, required in REQUIRED_FIELDS.items():
    missing = required - mapped_fields
    computable[metric] = len(missing) == 0
    if missing:
        print(f"  WARNING: {metric} missing fields: {missing}")

if not any(computable.values()):
    raise ValueError(f"No metric can be computed. Mapped fields: {mapped_fields}. Check FIELD_SYNONYMS coverage.")

print(f"Computable metrics: {[m for m, v in computable.items() if v]}")

# Step 4: Extract data rows using canonical field names
data_rows = []
for i in range(header_idx + 1, len(lines)):
    line = lines[i].strip()
    if not line or ',' not in line or line.startswith('='):
        continue
    parts = [p.strip() for p in line.split(',')]
    if len(parts) >= len(headers):
        row = {}
        for actual_h, canonical_h in hmap.items():
            row[canonical_h] = parse_number(parts[col_idx[actual_h]])
        data_rows.append(row)

# Step 5: Use parsed data with canonical names (no hard-coding!)
for row in data_rows:
    year = row.get('year')  # Works whether header was "Year", "Fiscal Year", "FY", etc.
    revenue = row.get('revenue')  # Works whether header was "Revenue", "Net Sales", etc.
    gross_profit = row.get('gross_profit')  # Works whether header was "GrossProfit", "Gross Margin ($M)", etc.
    # ... compute metrics
```

**Why this is truly universal:**
- **Schema variations**: Handles "Year" vs "Fiscal Year" vs "FY", "Revenue" vs "Net Sales" vs "Total Revenue", etc.
- **PascalCase/camelCase**: `re.sub(r'[^a-z0-9]', '', ...)` normalization handles "GrossProfit" → "grossprofit" matching "gross profit" synonym
- **Numeric formats**: Handles "$1,234", "(500)" for negatives, "€1.234,56" (European), etc.
- **Header detection**: Finds header by matching ≥2 known field synonyms, not by exact column names
- **Canonical vocabulary**: All downstream code uses normalized names (year, revenue, gross_profit) regardless of actual header text
- **Validation**: Checks that required fields are mapped before computing, preventing silent zero-default failures

#### Cross-File Joins (Statement Topology Variation)

When required values span multiple files (e.g., ROE needs Net Income from income statement + Shareholders' Equity from balance sheet):

**Step 1: Classify files by statement type**
- **Income statement files** contain: Revenue, Gross Profit, Operating Income, Net Income
- **Balance sheet files** contain: Total Assets, Total Liabilities, Shareholders' Equity, Retained Earnings
- Scan file headers and line items to classify each file (use FIELD_SYNONYMS to recognize fields regardless of actual header names)

**Step 2: Extract and normalize fiscal year keys**
Different files may use different year formats. Normalize to bare integer year for joining:
```python
import re
def normalize_year(label):
    """Extract 4-digit year from various formats: FY2024, 2024, Fiscal Year 2024, 2024-01"""
    m = re.search(r'\d{4}', str(label))
    return int(m.group(0)) if m else None
```

**Step 3: Build dictionaries keyed by normalized year**
Use the schema-agnostic parsing template from above. Each file gets parsed independently with its own header mapping:
```python
income_data = {}   # {2024: {'net_income': 29760, 'revenue': 60922}, ...}
balance_data = {}  # {2024: {'equity': 65000, 'assets': 120000}, ...}

# Extract from income statement file (uses canonical names from hmap)
for row in income_rows:
    year = normalize_year(row.get('year'))
    if year:
        income_data[year] = {
            'net_income': row.get('net_income'),
            'revenue': row.get('revenue')
        }

# Extract from balance sheet file (uses canonical names from hmap)
for row in balance_rows:
    year = normalize_year(row.get('year'))
    if year:
        balance_data[year] = {
            'equity': row.get('equity'),
            'assets': row.get('assets')
        }
```

**Step 4: Join on shared years**
Only compute metrics for years present in *both* datasets:
```python
shared_years = sorted(income_data.keys() & balance_data.keys())
for year in shared_years:
    ni = income_data[year]['net_income']
    equity = balance_data[year]['equity']
    roe = (ni / equity) * 100
```

**Step 5: Check for unit mismatches**
- Each file may state units independently ("in millions", "in billions", "in thousands")
- For ratios, units cancel as long as numerator and denominator use the *same* unit
- If units differ, normalize before computing (e.g., convert billions to millions)
- Always check file headers/metadata for unit declarations

**Example: ROE with cross-file join**
```
Income file: FY2024, Net Income = $29,760M
Balance file: Fiscal Year 2024, Shareholders' Equity = $65,000M

Normalize: both → year 2024
Join: income_data[2024]['net_income'] = 29760, balance_data[2024]['equity'] = 65000
Compute: ROE = (29760 / 65000) × 100 = 45.78%
```

### 3. Metric Calculation

#### Standard Financial Metrics

**Gross Margin**
```
Gross Margin = (Gross Profit / Revenue) × 100
```
- Numerator: Gross Profit (Revenue - Cost of Goods Sold)
- Denominator: Revenue (Total Sales)
- Interpretation: Percentage of revenue remaining after direct production costs

**Operating Margin**
```
Operating Margin = (Operating Income / Revenue) × 100
```
- Numerator: Operating Income (Gross Profit - Operating Expenses)
- Denominator: Revenue
- Interpretation: Profitability from core operations

**Net Margin**
```
Net Margin = (Net Income / Revenue) × 100
```
- Numerator: Net Income (bottom-line profit after all expenses, taxes, interest)
- Denominator: Revenue
- Interpretation: Overall profitability after all costs

**Return on Equity (ROE)**
```
ROE = (Net Income / Shareholders' Equity) × 100
```
- Numerator: Net Income
- Denominator: Average Shareholders' Equity (or ending equity if average unavailable)
- Interpretation: Profit generated per dollar of shareholder investment

**Year-over-Year Growth**
```
YoY Growth = ((Current Year Value - Prior Year Value) / |Prior Year Value|) × 100
```
- Can apply to Revenue, Net Income, or other metrics
- Requires at least two consecutive years of data
- **Output pattern**: Produces N-1 values for N years of input (one growth rate per year transition)
- **Denominator convention**: Use absolute value of prior year to handle negative values correctly

**YoY Growth computation procedure:**
```python
def calculate_yoy_growth(values_by_year):
    """
    Calculate year-over-year growth rates.
    Input: {2022: 100, 2023: 120, 2024: 150}
    Output: {2023: 20.0, 2024: 25.0}  # growth rates for each year with prior data
    """
    years = sorted(values_by_year.keys())
    growth_rates = {}
    
    for i in range(1, len(years)):
        current_year = years[i]
        prior_year = years[i-1]
        current_val = values_by_year[current_year]
        prior_val = values_by_year[prior_year]
        
        # Use absolute value of prior to handle negative denominators correctly
        if prior_val == 0:
            growth_rates[current_year] = None  # Division by zero
        else:
            growth = ((current_val - prior_val) / abs(prior_val)) * 100
            growth_rates[current_year] = round(growth, 2)
    
    return growth_rates
```

**YoY Growth edge cases:**
- **Negative prior value**: Going from -100 to -50 gives `((-50 - (-100)) / |-100|) × 100 = 50%` (improvement)
- **Zero prior value**: Report as N/M (not meaningful) or None
- **Sign flip**: Going from -50 to +100 gives `((100 - (-50)) / |-50|) × 100 = 300%` (major improvement)
- **Output format**: First year has no prior, so output has N-1 rows (or N rows with first marked as N/A)

**Example: Revenue YoY Growth**
```
FY2022: Revenue = $26,914M
FY2023: Revenue = $26,974M → YoY = ((26974 - 26914) / |26914|) × 100 = 0.22%
FY2024: Revenue = $60,922M → YoY = ((60922 - 26974) / |26974|) × 100 = 125.85%
FY2025: Revenue = $130,497M → YoY = ((130497 - 60922) / |60922|) × 100 = 114.20%
```

**Output structure for YoY Growth:**
```
fiscal_year,revenue_yoy_growth_pct
FY2023,0.22
FY2024,125.85
FY2025,114.20
```
Note: FY2022 is excluded (no prior year for comparison).

#### Calculation Rules
- **Percentage scale**: Always express as percentage (multiply by 100)
- **Rounding**: Round to specified decimal places (default: 2)
- **Sign convention**: Positive for growth/profit, negative for decline/loss
- **Division by zero**: Handle cases where denominator is zero or missing

### 4. Conditional Logic

Common conditional patterns:
- **Threshold-based metric selection**: If metric X exceeds threshold, calculate metric A; otherwise calculate metric B
- **Most recent year check**: Evaluate condition on most recent fiscal year, then apply to all years
- **Multi-year trends**: Calculate metric for all years if trend condition is met

**Implementation approach:**
1. Calculate the conditional metric for the most recent year
2. Evaluate the threshold condition
3. Based on result, determine which metric(s) to calculate for all years
4. Apply consistent logic across all fiscal periods

### 5. Output Formatting

#### CSV Output
- **Column naming**: Use exact column names specified in requirements
- **Fiscal year format**: Preserve original format (FY2024, 2024, etc.)
- **Numeric formatting**: 
  - Percentages as numbers (72.72, not 0.7272 or 72.72%)
  - Consistent decimal places
  - No thousands separators in output
- **Row ordering**: Typically chronological (oldest to newest)

#### Common Output Patterns
```
fiscal_year,metric_name
FY2022,64.93
FY2023,56.93
FY2024,72.72
```

## Implementation Checklist

Before writing output, verify:
- [ ] **NO VALUE HARD-CODING**: All data parsed programmatically from files
- [ ] **NO SCHEMA HARD-CODING**: Using FIELD_SYNONYMS normalization, not hard-coded column names like `row['Year']`
- [ ] **SPACE-MATCHING FIX**: `normalize_headers()` uses `re.sub(r'[^a-z0-9]', '', ...)` on both key and synonyms to handle PascalCase/camelCase
- [ ] **HMAP VALIDATED**: Print `hmap` after parsing and verify ALL expected canonical names are present (not just year and revenue)
- [ ] **REQUIRED FIELDS CHECK**: Validate that required fields for the target metric are in `mapped_fields` before computing
- [ ] **parse_number() used**: Handles "$1,234", "(500)", and other numeric formats
- [ ] Correct company data identified (not decoy, not pre-computed cache)
- [ ] All required fiscal years extracted
- [ ] Most recent year determined by parsing year labels numerically (not by file order or list position)
- [ ] If cross-file: files classified correctly (income vs balance sheet)
- [ ] If cross-file: year keys normalized and joined on shared years only
- [ ] If cross-file: units consistent across files (or normalized)
- [ ] Correct numerator and denominator for requested metric
- [ ] Conditional logic evaluated on most recent year
- [ ] Percentages expressed as numbers (×100), not decimals
- [ ] If YoY Growth: output has N-1 rows (not N), first year excluded
- [ ] If YoY Growth: denominator uses abs(prior_value) for negative handling
- [ ] Rounding applied correctly (specify decimal places)
- [ ] Output columns match required schema exactly
- [ ] Fiscal year labels preserved in original format
- [ ] File written to correct path with proper CSV formatting
- [ ] **ZERO-VALUE SANITY CHECK**: If computed metrics are all 0.0, something is wrong with field mapping — investigate before writing output

## Common Pitfalls

1. **❌ HARD-CODING VALUES**: The #1 failure mode. Reading a file, seeing the numbers, then typing them into your script. This works for v01 but fails on every other variant. ALWAYS parse programmatically.
2. **❌ SCHEMA HARD-CODING**: Hard-coding column names like `row['Year']`, `row['Revenue']`. Fails when header says "Fiscal Year" or "Net Sales". ALWAYS use FIELD_SYNONYMS normalization.
3. **❌ SPACE-MATCHING BUG**: The `normalize_headers()` function fails on PascalCase/camelCase headers (e.g., `GrossProfit`, `OperatingIncome`) when synonyms contain spaces (e.g., `'gross profit'`). The substring check `'gross profit' in 'grossprofit'` returns FALSE. **Fix**: Normalize both sides by stripping non-alphanumeric chars before matching: `re.sub(r'[^a-z0-9]', '', syn)` vs `re.sub(r'[^a-z0-9]', '', key)`.
4. **❌ SILENT FIELD MAPPING FAILURES**: If `normalize_headers()` fails to map a field, downstream code defaults to 0, producing wrong results without errors. **Fix**: Add validation after header mapping to check that required fields are present. Print `hmap` and verify all expected canonical names are present.
5. **Decoy data**: Files may contain data for wrong company or quarterly-only data
6. **Pre-computed metric decoys**: Files like `cache_results.txt` may contain plausible-looking financial metrics (e.g., "Gross Margin for FY2024: 65.24%") that are stale, fabricated, or for a different company. Always use raw data files, not pre-computed summaries.
7. **Unit confusion**: Ensure numerator and denominator are in same units (both in millions, etc.)
8. **Percentage scale**: Forgetting to multiply by 100 (outputting 0.72 instead of 72.72)
9. **Rounding errors**: Rounding intermediate calculations instead of final result
10. **Column names**: Using generic names instead of exact required names
11. **Missing years**: Not extracting all available fiscal years
12. **Conditional logic**: Evaluating condition on wrong year or wrong metric
13. **Most recent year determination**: Assuming file order = chronological order. Always parse year labels and find the maximum numerically.
14. **Numeric format crashes**: `float(val)` crashes on `"$1,234"` or `"(500)"`. Use `parse_number()` helper.
15. **Cross-file joins**: Failing to normalize year formats before joining (FY2024 vs 2024 vs Fiscal Year 2024)
16. **Statement classification**: Misidentifying which file contains income statement vs balance sheet items
17. **YoY Growth output count**: Producing N rows instead of N-1 (first year has no prior for comparison)
18. **YoY Growth with negative prior**: Using signed prior value instead of absolute value, causing sign errors
19. **Unit mismatches across files**: One file in millions, another in billions, without normalization

## Example: Gross Margin Analysis

**Scenario**: Calculate Gross Margin for all years if most recent year exceeds 70%

**Steps**:
1. Extract Revenue and Gross Profit for all fiscal years
2. Calculate Gross Margin for most recent year
3. If Gross Margin > 70%:
   - Calculate Gross Margin for all years
   - Write to CSV with columns: fiscal_year, gross_margin_pct
4. Else:
   - Calculate Net Margin for all years instead
   - Write to CSV with appropriate columns

**Calculation**:
```python
gross_margin = (gross_profit / revenue) * 100
gross_margin_rounded = round(gross_margin, 2)
```

## Adaptation to Variations

This skill handles the following spec-declared variations:

- **source_representation**: Parse any structured format (CSV, JSON, fixed-width, HTML)
- **statement_topology**: Join data across multiple files if needed (e.g., income statement + balance sheet)
- **financial_metric**: Apply correct formula for any standard metric
- **schema_and_locale**: Schema-agnostic parsing with FIELD_SYNONYMS map handles varying field labels, header depth, language, numeric punctuation, year labels, and irrelevant rows
- **output_contract**: Adapt column names and file format to requirements

### Extending FIELD_SYNONYMS for New Variants

The FIELD_SYNONYMS map is the key to schema-agnostic parsing. If you encounter a variant with unfamiliar field names:

1. **Add new synonyms** to the appropriate canonical field:
   ```python
   FIELD_SYNONYMS = {
       'year':           ['year', 'fiscal year', 'fy', 'period', 'date', 'accounting period'],
       'revenue':        ['revenue', 'total revenue', 'net sales', 'sales', 'net revenue', 'turnover'],
       # ... etc.
   }
   ```

2. **Add new canonical fields** if the variant requires metrics not in the current map:
   ```python
   FIELD_SYNONYMS = {
       # ... existing fields ...
       'ebitda':         ['ebitda', 'earnings before', 'ebitda'],
       'cash_flow':      ['cash flow', 'operating cash flow', 'ocf'],
   }
   ```

3. **Test the mapping** by printing `hmap` after parsing to verify headers are correctly normalized.

### Two Forms of Hard-Coding (Both Eliminated)

1. **Value hard-coding** (iteration 1 failure): Manually typing data values from the file into the script
   - **Fix**: Programmatic parsing with `parse_number()` and dynamic row extraction

2. **Schema hard-coding** (iteration 2 failure): Hard-coding column names like `row['Year']`, `row['Revenue']`
   - **Fix**: FIELD_SYNONYMS map with `normalize_headers()` to map actual headers → canonical names

3. **Space-matching bug** (iteration 2 discovery): The `normalize_headers()` function failed on PascalCase headers (e.g., `GrossProfit`) because synonyms contain spaces (e.g., `'gross profit'`). The substring check `'gross profit' in 'grossprofit'` returns FALSE.
   - **Fix**: Normalize both sides by stripping non-alphanumeric chars: `re.sub(r'[^a-z0-9]', '', syn)` vs `re.sub(r'[^a-z0-9]', '', key)`
   - **Lesson**: Always validate `hmap` after parsing. If only 2 of 5 fields are mapped, something is wrong.

The template is now truly universal: it works regardless of data values AND regardless of schema variations AND regardless of spacing/casing conventions.

## Testing Strategy

1. **Verify data extraction**: Print extracted values to confirm correct parsing
2. **Spot-check calculations**: Manually verify one or two metric calculations
3. **Validate conditional logic**: Confirm threshold evaluation on most recent year
4. **Check output format**: Verify column names, numeric formatting, and file structure
5. **Test edge cases**: Handle missing data, zero denominators, negative values
