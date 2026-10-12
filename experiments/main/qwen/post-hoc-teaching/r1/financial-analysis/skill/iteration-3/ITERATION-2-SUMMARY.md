# Iteration 2 Improvements

## Status
✅ All 5 v01 tests pass (100% score)

## Most Consequential Weakness Fixed

### 1. Delimiter Handling Inconsistency (CRITICAL)
**Problem**: The parsing pipeline had inconsistent delimiter detection:
- `is_header_line()` checked for `,`, `\t`, `|`, `;`
- `looks_like_data_row()` only split on `,` and `\t`
- `split_data_row()` tried `,`, `\t`, `|`, `;` in order

This caused **silent failures** for variants using semicolons or pipes as delimiters.

**Fix**: 
- Added `detect_delimiter()` function that identifies the delimiter from the header line
- `try_csv_parse()` now detects the delimiter once and uses it consistently for all data rows
- `looks_like_data_row()` now takes the delimiter as a parameter

**Impact**: Enables parsing of CSV variants with different delimiters (common in European locales where semicolons are preferred to avoid conflicts with decimal commas).

### 2. HTML Parser Not in Pipeline (CRITICAL)
**Problem**: `try_html_parse()` was defined in "Additional Format Parsers" section but never called in `parse_financial_data()`. HTML table variants would fail.

**Fix**: Added HTML parsing to the format detection chain in `parse_financial_data()`:
```python
if '<table' in content.lower():
    records = try_html_parse(content)
    if records:
        return records
```

**Impact**: Enables parsing of HTML table variants (mentioned in spec as a valid source_representation).

### 3. No Subdirectory Search (HIGH)
**Problem**: `discover_file()` used `os.listdir()` which only searches the top-level directory. Spec says files "may require content-based discovery among decoys" — implying nested structures.

**Fix**: Changed to `os.walk()` for recursive search:
```python
for root, dirs, files in os.walk(data_dir):
    for fname in files:
        fpath = os.path.join(root, fname)
        # ... scoring logic
```

**Impact**: Enables discovery of files in subdirectories (e.g., `/app/financials/2024/nvidia.csv`).

### 4. Filename-Based Discovery (MEDIUM)
**Problem**: File discovery only checked content, not filenames. Spec says "Filenames may be explicit or may require content-based discovery."

**Fix**: Added filename matching to the scoring system:
```python
if company_name.lower() in fname.lower():
    score += 10  # High weight for filename match
if company_name.upper() in content.upper():
    score += 5   # Lower weight for content match
```

**Impact**: Enables discovery when filename is explicit (e.g., `nvidia_financials.csv`) even if content doesn't contain the company name.

### 5. Flexible Year Detection (MEDIUM)
**Problem**: `looks_like_data_row()` only matched `(FY)?\d{4}`, missing variants like:
- `FY24` (2-digit year)
- `2022-23` (year range)
- `Year 2024` (word prefix)
- `FY 2024` (space after FY)

**Fix**: Expanded `looks_like_year()` with multiple patterns:
```python
patterns = [
    r'^(FY)?\d{2,4}$',           # FY2024, FY24, 2024
    r'^\d{4}[-/]\d{2,4}$',       # 2022-23, 2022/2023
    r'^(year|fy)\s*\d{2,4}$',    # Year 2024, FY 2024
]
```

**Impact**: Enables parsing of variants with different year label formats (mentioned in spec under schema_and_locale).

### 6. Code Consolidation (MAINTAINABILITY)
**Problem**: Implementation was split across "Implementation Template" and "Additional Format Parsers" sections, creating confusion about which functions were actually used.

**Fix**: Consolidated all parsing code into a single "Complete Implementation" section with clear organization:
- Field mapping functions
- File discovery
- Parsing (JSON, HTML, CSV, fixed-width)
- Metric computation
- Output generation
- Multi-file joining

**Impact**: Easier to understand, maintain, and extend.

## Preserved Functionality

All working functionality from iteration 1 was preserved:
- ✅ Longest-match-wins field mapping (prevents "Cost of Revenue" → "revenue" collision)
- ✅ European number format handling (1.234,56 → 1234.56)
- ✅ All 5 financial metrics (gross_margin, operating_margin, net_margin, return_on_equity, year_over_year_growth)
- ✅ Conditional logic (threshold-based metric switching)
- ✅ Multi-file joining on fiscal year
- ✅ CamelCase field name handling (GrossProfit → gross_profit)

## Test Results

### v01 Tests (5/5 passed)
```
test_latest_year_selects_gross_margin_branch ✓
test_every_available_year_appears_once ✓
test_every_gross_margin_is_correct ✓
test_result_contains_only_declared_columns ✓
test_latest_year_is_not_silently_omitted ✓
```

### New Capability Tests
- ✅ Semicolon-delimited data parsing
- ✅ Pipe-delimited data parsing
- ✅ Year format variants (FY24, 2022-23, Year 2024, etc.)
- ✅ Recursive subdirectory search
- ✅ Filename-based discovery

## Generalization Improvements

The skill now handles all spec dimensions more robustly:

| Spec Dimension | Iteration 1 | Iteration 2 |
|----------------|-------------|-------------|
| source_representation | CSV, JSON, fixed-width | + HTML tables, subdirectories |
| statement_topology | Single/multi-file | Same (unchanged) |
| financial_metric | All 5 metrics | Same (unchanged) |
| schema_and_locale | Field mapping, European numbers | + Flexible year formats, delimiter variants |
| output_contract | CSV output | Same (unchanged) |

## Conclusion

Iteration 2 fixes critical parsing pipeline bugs that would cause silent failures on unseen family members, while preserving all working functionality. The skill is now more robust to variations in file structure, delimiters, year formats, and directory organization.
