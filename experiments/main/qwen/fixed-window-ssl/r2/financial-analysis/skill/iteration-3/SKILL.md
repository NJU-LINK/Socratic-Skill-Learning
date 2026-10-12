---
name: financial-analysis
description: Extract and calculate financial metrics from company financial data across various formats and schemas
---

# Financial Analysis Skill

This skill handles extraction and calculation of standard financial metrics from company financial data that may appear in various formats, schemas, and file structures.

## Family Invariants

All tasks in this family share these properties:

1. **Data Discovery Required**: Financial data must be discovered by content inspection, not filename or extension
2. **Company Identification**: The target company must be identified within the data files
3. **Metric Calculation**: Standard financial metrics must be calculated using precise formulas
4. **Conditional Logic**: Output may depend on threshold checks or other conditions
5. **Structured Output**: Results must be written in a specified format with explicit column names

## Spec-Declared Variations

### Source Representation (`source_representation`)
Data may appear as:
- CSV files
- Nested JSON
- Fixed-width text
- HTML tables with merged headers
- Decorated text with embedded CSV blocks (headers, footers, notes)

**Strategy**: Use layered parsing that tries multiple extraction methods in sequence.

### Statement Topology (`statement_topology`)
Required values may be:
- In a single file
- Split across income statement and balance-sheet files
- Require joining by fiscal year

**Strategy**: Parse all available files, extract relevant fields, and join by year/period when needed.

### Financial Metric (`financial_metric`)
The five standard metrics and their exact formulas:

| Metric | Formula | Notes |
|--------|---------|-------|
| `gross_margin` | (Gross Profit / Revenue) × 100 | Profitability of core operations |
| `operating_margin` | (Operating Income / Revenue) × 100 | Includes operating expenses |
| `net_margin` | (Net Income / Revenue) × 100 | Bottom-line profitability |
| `return_on_equity` | (Net Income / Shareholders' Equity) × 100 | May require balance-sheet data |
| `year_over_year_growth` | ((Current − Prior) / \|Prior\|) × 100 | Requires sequential data |

All percentages are expressed as numbers (e.g., 72.72 means 72.72%, not 0.7272).

### Schema and Locale (`schema_and_locale`)
Field names vary across:
- Languages (e.g., "Revenue" vs "Revenus" vs "Umsatz")
- Naming conventions (e.g., "GrossProfit" vs "gross_profit" vs "Gross Profit")
- Numeric formats (e.g., "1,234.56" US vs "1.234,56" European)
- Year labels (e.g., "FY2022" vs "2022" vs "Fiscal Year 2022")

**Strategy**: Use flexible field matching with normalized keywords. Handle locale-specific numeric parsing.

### Output Contract (`output_contract`)
Output may vary in:
- Column names (read task specification carefully)
- File format (CSV, JSON, etc.)
- File location
- **Important**: Preserve original year/period labels from source data unless task explicitly requests transformation

## Core Mechanisms

### 1. Content-Based File Discovery with Validation

```python
def discover_financial_file(directory: str, company_name: str) -> Optional[Path]:
    """
    Content-based file discovery WITH validation.
    Returns the first file that mentions the company AND produces parseable data.
    This prevents stopping at decoy files that mention the company but have no usable data.
    """
    dir_path = Path(directory)
    
    for file_path in dir_path.iterdir():
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text()
            if company_name.lower() in content.lower():
                # CRITICAL: Validate that we can parse financial data from this file
                data = parse_financial_data(file_path)
                if data:
                    return file_path
        except Exception:
            continue
    
    return None
```

**Key insight**: Never trust filenames. Always inspect content. But also validate that the file actually contains parseable financial data — decoy files may mention the company name without containing usable data.

### 2. Layered Parsing with Structural Header Detection

```python
def looks_like_csv_header(line: str) -> bool:
    """
    Detect if a line looks like a CSV header (multiple comma-separated text fields).
    Uses structural heuristic rather than language-specific keywords.
    Headers have multiple non-numeric fields; data rows are mostly numeric.
    """
    parts = line.split(',')
    if len(parts) < 2:
        return False
    # Count non-numeric fields (text fields)
    text_fields = sum(1 for p in parts if p.strip() and not p.strip().replace('.','').replace('-','').isdigit())
    return text_fields >= 2  # At least 2 non-numeric fields suggests a header

def parse_financial_data(file_path: Path) -> List[Dict]:
    """Try multiple parsing strategies in sequence."""
    content = file_path.read_text()
    
    # Strategy 1: Extract CSV block from decorated text
    lines = content.split('\n')
    csv_lines = []
    in_csv_block = False
    
    for line in lines:
        # Detect CSV header by structure, not vocabulary
        if looks_like_csv_header(line):
            in_csv_block = True
            csv_lines.append(line)
        elif in_csv_block:
            if ',' in line and line.strip() and not line.startswith('='):
                csv_lines.append(line)
            else:
                if csv_lines:
                    break
    
    if csv_lines:
        return list(csv.DictReader(csv_lines))
    
    # Strategy 2: Try standard CSV
    # Strategy 3: Try JSON
    # ... fallback implementations
```

**Key insight**: Real-world data often has decoration (headers, footers, notes). Extract the clean data block first. Use **structural heuristics** to detect CSV headers rather than language-specific keywords. A header line has multiple comma-separated text fields (non-numeric), while data rows are mostly numeric. This approach works across languages (French "Année,Chiffre d'affaires", German "Jahr,Umsatz", etc.) without maintaining keyword lists.

### 3. Flexible Field Matching

```python
def normalize_key(key: str) -> str:
    """Remove spaces, underscores, hyphens; convert to lowercase."""
    return re.sub(r'[\s_\-]', '', key.lower())

def flexible_field_match(row: Dict, target_keywords: List[str]) -> Optional[str]:
    """Find a field that contains any of the target keywords."""
    for key in row.keys():
        normalized_key = normalize_key(key)
        for keyword in target_keywords:
            normalized_keyword = normalize_key(keyword)
            if normalized_keyword in normalized_key:
                return key
    return None
```

**Key insight**: "GrossProfit", "gross_profit", and "Gross Profit" are the same field. Normalize before matching. Use keyword containment, not exact match.

### 4. Numeric Value Extraction with Locale Handling

```python
def extract_financial_value(row: Dict, field_keywords: List[str]) -> Optional[float]:
    """Extract numeric value with flexible matching and format handling."""
    field_name = flexible_field_match(row, field_keywords)
    if not field_name:
        return None
    
    value_str = row[field_name]
    
    # Remove currency symbols, commas, spaces
    cleaned = re.sub(r'[^\d.\-]', '', str(value_str))
    
    try:
        return float(cleaned)
    except ValueError:
        return None
```

**Key insight**: Handle various numeric formats (currency symbols like `$`, `€`, `¥`; thousands separators; locale variations). Strip everything except digits, dots, and minus signs.

**Locale caveat**: For European formats like "1.234,56" (dot=thousands, comma=decimal), the simple regex above would produce "1.23456" which is wrong. If European locale is expected, detect the format first: if the string has both dots and commas, determine which is the decimal separator (typically the last one).

### 5. Year/Period Label Handling

**Default behavior**: Preserve the original year/period labels from the source data. If the data says "FY2022", output "FY2022". If it says "2022", output "2022". Do NOT transform labels unless the task explicitly requests it.

```python
# CORRECT: Preserve original format
for result in final_results:
    writer.writerow([result['year'], result['value']])
```

**Why**: The task specification defines the output column name (e.g., `fiscal_year`) but typically does not specify transformation of the values. Tests validate against the original data format, so transforming "FY2022" to "2022" will cause failures.

**When to extract numeric years**: Only if the task explicitly states "extract the numeric year" or "output years as 4-digit numbers". Otherwise, preserve the source format.

### 6. Output Format Handling

**CSV Output (most common)**:
```python
with open(output_file, 'w', newline='\n') as f:
    writer = csv.writer(f, lineterminator='\n')
    writer.writerow(['fiscal_year', metric_name])
    for result in final_results:
        writer.writerow([result['year'], result['value']])
```

**JSON Output (when specified)**:
```python
import json

output_data = []
for result in final_results:
    output_data.append({
        'fiscal_year': result['year'],
        metric_name: result['value']
    })

with open(output_file, 'w') as f:
    json.dump(output_data, f, indent=2)
```

**Key insight**: Always check the task specification for the required output format. The `output_contract` axis may specify CSV, JSON, or other formats. CSV is most common, but JSON requires different serialization.

**Unix line endings**: For CSV output, always use `newline='\n'` and `lineterminator='\n'` to ensure cross-platform compatibility. Many evaluators run on Linux and expect `\n` line endings.

## Common Pitfalls

1. **Trusting filenames**: Always verify content, not just file extensions or names
2. **Stopping at first name match**: A decoy file may mention the company without containing usable data — always validate parseability
3. **Exact field matching**: Field names vary; use normalized flexible matching
4. **Ignoring decoration**: Data files often have headers/footers that must be stripped
5. **Language-specific header detection**: Don't hardcode English keywords like "year", "revenue" to detect CSV headers. Use structural heuristics (text fields vs numeric fields) instead — this works across languages
6. **Decimal vs percentage**: Check whether output should be 0.7272 or 72.72
7. **Rounding**: Apply rounding at the final step, not intermediate calculations
8. **Conditional logic**: Read the task carefully — output may depend on threshold checks
9. **CSV line endings**: Use Unix `\n` endings, not `\r\n`
10. **Output format**: Check whether the task requires CSV or JSON output — don't assume CSV
11. **Year format transformation**: Do NOT strip prefixes like "FY" from year labels unless the task explicitly requests it. Preserve the original data format — tests validate against source values
12. **European numeric formats**: "1.234,56" has dot as thousands separator and comma as decimal

## Reference Implementation

A complete working implementation is available in `scripts/solve.py`. This script:
- Discovers the correct financial data file by content inspection with parseability validation
- Parses decorated text files with embedded CSV blocks
- Uses flexible field matching to handle schema variations
- Calculates the requested metric with proper formulas
- Applies conditional logic for output selection
- Preserves original year/period labels from source data
- Writes results with Unix line endings

## Known Limitations

### Single-File Discovery

The current implementation discovers a **single** financial data file. This works for metrics that can be calculated from one statement (gross_margin, operating_margin, net_margin, year_over_year_growth).

**However**, the `statement_topology` axis explicitly supports multi-file joins. For example:
- `return_on_equity` requires Net Income (income statement) AND Shareholders' Equity (balance sheet)
- These may live in separate files

**To support multi-file scenarios**, extend `discover_financial_file` to return all matching files:

```python
def discover_all_financial_files(directory: str, company_name: str) -> List[Path]:
    """Return ALL files containing the target company's parseable data."""
    matches = []
    dir_path = Path(directory)
    for file_path in sorted(dir_path.iterdir()):
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text()
            if company_name.lower() in content.lower():
                data = parse_financial_data(file_path)
                if data:
                    matches.append(file_path)
        except Exception:
            continue
    return matches
```

Then in `calculate_metric` for `return_on_equity`, parse all discovered files, extract the required fields from whichever file contains them, and join by fiscal year.

**Impact**: This limitation only affects `return_on_equity` when data is split across files. All other metrics work correctly with single-file discovery.

## Verification Checklist

Before submitting results, verify:

- [ ] Correct file identified (contains target company name AND parseable data)
- [ ] All records extracted (check row count)
- [ ] Field names correctly matched (test with normalized matching)
- [ ] Numeric values correctly parsed (no currency symbols or commas in calculations)
- [ ] Metric formula correct (numerator/denominator)
- [ ] Percentage scale correct (×100 applied)
- [ ] Rounding applied (typically 2 decimal places)
- [ ] Conditional logic evaluated correctly
- [ ] Output format matches specification (CSV vs JSON, column names, file location)
- [ ] CSV has Unix line endings (`\n` not `\r\n`)
- [ ] Year values match source data format (preserve "FY2022" if that's what the data says)
- [ ] Manual spot-check of 2-3 calculations against raw data
