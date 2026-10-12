#!/usr/bin/env python3
"""
Financial Analysis Pipeline — 5-stage reusable script.

Stages: DISCOVER → PARSE → CANONICALIZE → COMPUTE → OUTPUT

Usage:
    python pipeline.py \
        --source-dir /app/financials \
        --company "NVIDIA Corporation" \
        --ticker NVDA \
        --metric gross_margin \
        --conditional "if latest gross_margin > 70 then gross_margin else net_margin" \
        --output-path /app/results.csv \
        --output-columns fiscal_year,gross_margin_pct \
        --round 2

The --conditional flag is optional. When omitted, the script computes --metric
for all years unconditionally.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


# ---------------------------------------------------------------------------
# FIELD SYNONYMS — maps variant header labels to canonical field names
# ---------------------------------------------------------------------------
FIELD_SYNONYMS = {
    "fiscal_year": [
        "fiscal_year", "fiscal year", "year", "fy", "period",
        "financial year", "reporting period", "date",
    ],
    "revenue": [
        "revenue", "total revenue", "net revenue", "net sales",
        "sales", "total sales", "total net sales", "net_turnover",
        "turnover", "ventas", "ingresos", "chiffre_daffaires",
    ],
    "gross_profit": [
        "gross_profit", "gross profit", "gp", "total gross profit",
        "gross income", "bénéfice brut", "utilidad bruta",
    ],
    "cost_of_revenue": [
        "cost_of_revenue", "cost of revenue", "cogs", "cost of goods sold",
        "cost_of_goods_sold", "cost of sales", "cost_of_sales",
        "total cost of revenue", "total cost of goods sold",
        "direct costs", "costo de ventas", "coût des ventes",
    ],
    "operating_income": [
        "operating_income", "operating income", "oi", "op_income",
        "operating profit", "ebit", "operating earnings",
        "income from operations", "resultat_operationnel",
    ],
    "net_income": [
        "net_income", "net income", "ni", "net profit",
        "net earnings", "profit after tax", "bottom line",
        "income after tax", "beneficio neto",
    ],
    "shareholders_equity": [
        "shareholders_equity", "shareholders equity",
        "total equity", "stockholders equity", "equity",
        "total shareholders equity", "book value",
        "common equity", "total common equity",
    ],
}

# Build reverse lookup: lowercase variant → canonical name
_SYNONYM_LOOKUP: Dict[str, str] = {}
for canonical, variants in FIELD_SYNONYMS.items():
    for v in variants:
        _SYNONYM_LOOKUP[v.lower().strip()] = canonical


def _camel_to_words(s: str) -> str:
    """Convert camelCase or PascalCase to space-separated lowercase words.
    E.g., 'GrossProfit' → 'gross profit', 'OperatingIncome' → 'operating income'
    """
    # Insert space before each uppercase letter that follows a lowercase letter
    # or before an uppercase letter followed by a lowercase letter (for acronyms)
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    result = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', result)
    return result.lower().strip()


def normalize_header(raw: str) -> Optional[str]:
    """Map a raw header string to a canonical field name, or None."""
    cleaned = raw.strip().lower()
    # Direct lookup
    if cleaned in _SYNONYM_LOOKUP:
        return _SYNONYM_LOOKUP[cleaned]
    # Try removing underscores, hyphens, extra spaces
    for sep in ["_", "-", " "]:
        cleaned2 = cleaned.replace(sep, " ").strip()
        # Collapse multiple spaces
        cleaned2 = re.sub(r'\s+', ' ', cleaned2)
        if cleaned2 in _SYNONYM_LOOKUP:
            return _SYNONYM_LOOKUP[cleaned2]
    # Try camelCase splitting
    camel_words = _camel_to_words(raw.strip())
    if camel_words in _SYNONYM_LOOKUP:
        return _SYNONYM_LOOKUP[camel_words]
    # Try camelCase words with underscores
    camel_under = camel_words.replace(' ', '_')
    if camel_under in _SYNONYM_LOOKUP:
        return _SYNONYM_LOOKUP[camel_under]
    # Substring match for common patterns
    for canonical, variants in FIELD_SYNONYMS.items():
        for v in variants:
            if v in cleaned or cleaned in v:
                return canonical
    return None


# ---------------------------------------------------------------------------
# METRIC FORMULAS
# ---------------------------------------------------------------------------
METRIC_FORMULAS = {
    "gross_margin": {
        "numerator": "gross_profit",
        "denominator": "revenue",
        "description": "Gross Profit / Revenue",
    },
    "operating_margin": {
        "numerator": "operating_income",
        "denominator": "revenue",
        "description": "Operating Income / Revenue",
    },
    "net_margin": {
        "numerator": "net_income",
        "denominator": "revenue",
        "description": "Net Income / Revenue",
    },
    "return_on_equity": {
        "numerator": "net_income",
        "denominator": "shareholders_equity",
        "description": "Net Income / Shareholders' Equity",
    },
    "year_over_year_growth": {
        "numerator": None,  # determined by --growth-field parameter
        "denominator": None,
        "description": "(Current - Prior) / |Prior| × 100 for the specified growth field",
    },
}


# ---------------------------------------------------------------------------
# STAGE 1: DISCOVER — find the correct file(s) for the target company
# ---------------------------------------------------------------------------
def discover_files(source_dir: str, company: str, ticker: Optional[str] = None, max_files: int = 5) -> List[str]:
    """
    Scan all files in source_dir. Return paths that contain the target
    company name or ticker AND contain structured tabular data.
    
    Returns multiple files (up to max_files) sorted by score descending,
    to support multi-file join scenarios (e.g., income statement + balance sheet).
    
    Heuristic: prefer files with actual data tables over log/cache/summary files.
    Score each file by: (a) company match, (b) tabular data density.
    """
    candidates = []
    source_path = Path(source_dir)
    
    if not source_path.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")
    
    for fpath in sorted(source_path.rglob('*')):
        if not fpath.is_file():
            continue
        
        try:
            content = fpath.read_text(errors='replace')
        except Exception:
            continue
        
        # Check company/ticker presence
        content_lower = content.lower()
        company_match = False
        if company and company.lower() in content_lower:
            company_match = True
        if ticker and ticker.lower() in content_lower:
            company_match = True
        
        if not company_match:
            continue
        
        # Score tabular data density
        # Count lines that look like data rows (contain commas or consistent whitespace-separated numbers)
        lines = content.split('\n')
        data_lines = 0
        header_candidates = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Check if line has comma-separated values with numbers
            if ',' in stripped:
                parts = [p.strip() for p in stripped.split(',')]
                num_parts = sum(1 for p in parts if re.search(r'\d', p))
                if num_parts >= 2:
                    data_lines += 1
            # Check for fixed-width numeric patterns
            elif re.search(r'\d{3,}', stripped):
                data_lines += 1
        
        # Penalize log/cache files (contain [INFO], [WARN], [DATA] markers)
        log_markers = len(re.findall(r'\[(INFO|WARN|DATA|DEBUG|ERROR)\]', content))
        
        # Score: more data lines = better, fewer log markers = better
        score = data_lines * 10 - log_markers * 5
        
        candidates.append((str(fpath), score, data_lines, log_markers))
    
    if not candidates:
        raise ValueError(f"No files found matching company '{company}' in {source_dir}")
    
    # Sort by score descending, return the top-scoring files
    candidates.sort(key=lambda x: -x[1])
    
    # Return top files (supports multi-file join scenarios)
    return [c[0] for c in candidates[:max_files]]


# ---------------------------------------------------------------------------
# STAGE 2: PARSE — read file content into raw rows
# ---------------------------------------------------------------------------
def detect_and_parse(filepath: str) -> Tuple[List[str], List[List[str]]]:
    """
    Detect file format and parse into (headers, rows).
    Handles: CSV, JSON, decorated text (===== borders), fixed-width, HTML.
    """
    content = Path(filepath).read_text(errors='replace')
    
    # Try JSON first
    content_stripped = content.strip()
    if content_stripped.startswith('{') or content_stripped.startswith('['):
        try:
            data = json.loads(content_stripped)
            return _parse_json_data(data)
        except json.JSONDecodeError:
            pass
    
    # Try HTML table detection
    if '<table' in content.lower():
        return _parse_html_table(content)
    
    # For text files: strip decoration lines and find the CSV-like data
    lines = content.split('\n')
    
    # Remove decoration lines (=====, -----, *****, etc.)
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip pure decoration lines
        if re.match(r'^[=\-*#~_]{3,}$', stripped):
            continue
        # Skip lines that are mostly decoration with a single word
        if re.match(r'^[=\-*#~_\s]{5,}$', stripped):
            continue
        cleaned_lines.append(stripped)
    
    # Remove empty lines at start/end
    while cleaned_lines and not cleaned_lines[0]:
        cleaned_lines.pop(0)
    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()
    
    # Detect delimiter (comma, semicolon, or tab)
    delimiter = _detect_delimiter(cleaned_lines)
    
    # Skip leading non-data lines (metadata like "Company:", "Ticker:", etc.)
    # Find the header row: first line with multiple delimiter-separated fields
    header_idx = None
    for i, line in enumerate(cleaned_lines):
        if delimiter in line:
            parts = [p.strip() for p in line.split(delimiter)]
            if len(parts) >= 2:
                header_idx = i
                break
    
    if header_idx is None:
        raise ValueError(f"Could not find header row in {filepath}")
    
    headers = [p.strip() for p in cleaned_lines[header_idx].split(delimiter)]
    rows = []
    for line in cleaned_lines[header_idx + 1:]:
        if not line.strip():
            continue
        # Stop at notes/footer sections
        if line.strip().upper().startswith('NOTE') or line.strip().upper().startswith('==='):
            break
        parts = [p.strip() for p in line.split(delimiter)]
        if len(parts) == len(headers):
            rows.append(parts)
        elif len(parts) > 0:
            # Pad or truncate to match headers
            padded = parts[:len(headers)] + [''] * max(0, len(headers) - len(parts))
            rows.append(padded)
    
    return headers, rows


def _detect_delimiter(lines: List[str]) -> str:
    """Detect CSV delimiter by examining the first few non-empty lines."""
    # Check first 5 non-empty lines for delimiter patterns
    candidates = lines[:10]
    comma_count = 0
    semicolon_count = 0
    tab_count = 0
    
    for line in candidates:
        if not line.strip():
            continue
        comma_count += line.count(',')
        semicolon_count += line.count(';')
        tab_count += line.count('\t')
    
    # Return the most frequent delimiter
    if semicolon_count > comma_count and semicolon_count > tab_count:
        return ';'
    elif tab_count > comma_count and tab_count > semicolon_count:
        return '\t'
    else:
        return ','


def _parse_json_data(data: Any) -> Tuple[List[str], List[List[str]]]:
    """Parse JSON array of objects into headers + rows."""
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        headers = list(data[0].keys())
        rows = [[str(row.get(h, '')) for h in headers] for row in data]
        return headers, rows
    elif isinstance(data, dict):
        # Might be {columns: [...], data: [...]} or similar
        for key in ['data', 'records', 'rows', 'results']:
            if key in data and isinstance(data[key], list):
                return _parse_json_data(data[key])
    raise ValueError("Could not parse JSON as tabular data")


def _parse_html_table(content: str) -> Tuple[List[str], List[List[str]]]:
    """Simple HTML table parser using regex."""
    # Find first table
    table_match = re.search(r'<table[^>]*>(.*?)</table>', content, re.DOTALL | re.IGNORECASE)
    if not table_match:
        raise ValueError("No <table> found in HTML content")
    
    table_html = table_match.group(1)
    rows_html = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
    
    rows = []
    for row_html in rows_html:
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE)
        # Strip HTML tags from cell content
        cleaned = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if any(cleaned):
            rows.append(cleaned)
    
    if len(rows) < 2:
        raise ValueError("HTML table has insufficient rows")
    
    headers = rows[0]
    data_rows = rows[1:]
    return headers, data_rows


# ---------------------------------------------------------------------------
# STAGE 2.5: JOIN — merge records from multiple files by fiscal year
# ---------------------------------------------------------------------------
def join_records(all_records: List[List[Dict]]) -> List[Dict]:
    """
    Join records from multiple parsed files by fiscal_year.
    Each input list is records from one file. Records with the same
    fiscal_year are merged (fields from later files fill in missing values).
    """
    if len(all_records) == 1:
        return all_records[0]
    
    # Build a merged dict keyed by fiscal_year
    merged: Dict[str, Dict] = {}
    year_order: List[str] = []  # preserve chronological order
    
    for records in all_records:
        for rec in records:
            year = rec.get('fiscal_year', '')
            if year not in merged:
                merged[year] = {'fiscal_year': year}
                year_order.append(year)
            # Merge: add fields that aren't already present or are None
            for key, val in rec.items():
                if key == 'fiscal_year':
                    continue
                if val is not None and (key not in merged[year] or merged[year][key] is None):
                    merged[year][key] = val
    
    return [merged[y] for y in year_order]


# ---------------------------------------------------------------------------
# STAGE 3: CANONICALIZE — map headers to standard field names
# ---------------------------------------------------------------------------
def canonicalize(headers: List[str], rows: List[List[str]]) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """
    Map raw headers to canonical field names.
    Returns (field_index_map, list_of_record_dicts).
    """
    field_map = {}
    for i, h in enumerate(headers):
        canonical = normalize_header(h)
        if canonical and canonical not in field_map:
            field_map[canonical] = i
    
    records = []
    for row in rows:
        record = {}
        for canonical_name, idx in field_map.items():
            if idx < len(row):
                raw_val = row[idx].strip()
                # Fiscal year should remain as string (preserve original format)
                if canonical_name == 'fiscal_year':
                    record[canonical_name] = raw_val
                else:
                    # Parse numeric value
                    record[canonical_name] = _parse_numeric(raw_val)
        records.append(record)
    
    # Derived field computation: if gross_profit is missing but cost_of_revenue
    # and revenue are present, compute gross_profit = revenue - cost_of_revenue
    for record in records:
        if 'gross_profit' not in record or record['gross_profit'] is None:
            if ('cost_of_revenue' in record and record['cost_of_revenue'] is not None and
                'revenue' in record and record['revenue'] is not None):
                record['gross_profit'] = record['revenue'] - record['cost_of_revenue']
                field_map['gross_profit'] = -1  # Mark as derived
    
    return field_map, records


def _parse_numeric(val: str) -> Any:
    """Parse a string into a number, handling currency symbols, commas, etc."""
    if not val:
        return None
    
    # Remove currency symbols, whitespace, and thousands separators
    cleaned = val.strip()
    cleaned = re.sub(r'[$€£¥₹\s]', '', cleaned)
    
    # Handle European number format (1.234,56 → 1234.56)
    # Heuristic: if there's a comma followed by exactly 2 digits at end, treat as decimal
    if re.match(r'^-?\d{1,3}(\.\d{3})*,\d{2}$', cleaned):
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        # Remove thousands commas: 1,234,567.89 → 1234567.89
        cleaned = cleaned.replace(',', '')
    
    # Remove trailing 'M', 'B', 'K' suffixes (millions, billions, thousands)
    multiplier = 1
    if cleaned.upper().endswith('M'):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]
    elif cleaned.upper().endswith('B'):
        multiplier = 1_000_000_000
        cleaned = cleaned[:-1]
    elif cleaned.upper().endswith('K'):
        multiplier = 1_000
        cleaned = cleaned[:-1]
    
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return val  # Return as string if not numeric


# ---------------------------------------------------------------------------
# STAGE 4: COMPUTE — apply metric formulas with conditional logic
# ---------------------------------------------------------------------------
def parse_conditional(conditional_str: Optional[str]) -> Optional[Dict]:
    """
    Parse a conditional rule like:
    'if latest gross_margin > 70 then gross_margin else net_margin'
    Returns dict with keys: metric, threshold, direction, fallback_metric
    """
    if not conditional_str:
        return None
    
    pattern = r'if\s+latest\s+(\w+)\s*([><=]+)\s*([\d.]+)\s+then\s+(\w+)\s+else\s+(\w+)'
    match = re.match(pattern, conditional_str.strip(), re.IGNORECASE)
    if not match:
        return None
    
    return {
        'metric': match.group(1).lower(),
        'operator': match.group(2),
        'threshold': float(match.group(3)),
        'then_metric': match.group(4).lower(),
        'else_metric': match.group(5).lower(),
    }


def compute_metric(records: List[Dict], metric_name: str, round_digits: int = 2, growth_field: str = "revenue") -> List[Tuple[str, float]]:
    """
    Compute a financial metric for all records.
    Returns list of (year_label, percentage_value) tuples.
    
    For year_over_year_growth, growth_field specifies which canonical field
    to compute growth on (default: "revenue").
    """
    formula = METRIC_FORMULAS.get(metric_name)
    if not formula:
        raise ValueError(f"Unknown metric: {metric_name}. Available: {list(METRIC_FORMULAS.keys())}")
    
    results = []
    
    if metric_name == "year_over_year_growth":
        # Special case: needs sequential years and a specified growth field
        for i, rec in enumerate(records):
            if i == 0:
                continue  # No prior year for first record
            current_val = rec.get(growth_field)
            prior_val = records[i - 1].get(growth_field)
            if current_val is not None and prior_val is not None and prior_val != 0:
                growth = ((current_val - prior_val) / abs(prior_val)) * 100
                year_label = rec.get('fiscal_year', f'Year_{i}')
                results.append((str(year_label), round(growth, round_digits)))
    else:
        num_field = formula['numerator']
        den_field = formula['denominator']
        
        for rec in records:
            numerator = rec.get(num_field)
            denominator = rec.get(den_field)
            
            if numerator is not None and denominator is not None and denominator != 0:
                try:
                    value = (float(numerator) / float(denominator)) * 100
                    year_label = rec.get('fiscal_year', 'Unknown')
                    results.append((str(year_label), round(value, round_digits)))
                except (TypeError, ValueError):
                    continue
    
    return results


def apply_conditional(
    records: List[Dict],
    conditional: Dict,
    round_digits: int = 2,
    growth_field: str = "revenue"
) -> Tuple[str, List[Tuple[str, float]]]:
    """
    Apply conditional logic: compute the primary metric for the latest year,
    check threshold, then compute the appropriate metric for all years.
    Returns (metric_name_used, results).
    """
    primary_metric = conditional['metric']
    threshold = conditional['threshold']
    operator = conditional['operator']
    
    # Compute primary metric for all years to check latest
    primary_results = compute_metric(records, primary_metric, round_digits, growth_field)
    
    if not primary_results:
        raise ValueError(f"Could not compute {primary_metric} for any year")
    
    latest_value = primary_results[-1][1]
    
    # Evaluate threshold condition
    condition_met = False
    if operator == '>':
        condition_met = latest_value > threshold
    elif operator == '>=':
        condition_met = latest_value >= threshold
    elif operator == '<':
        condition_met = latest_value < threshold
    elif operator == '<=':
        condition_met = latest_value <= threshold
    elif operator in ('==', '='):
        condition_met = latest_value == threshold
    
    if condition_met:
        chosen_metric = conditional['then_metric']
    else:
        chosen_metric = conditional['else_metric']
    
    # Compute the chosen metric for all years
    final_results = compute_metric(records, chosen_metric, round_digits, growth_field)
    return chosen_metric, final_results


# ---------------------------------------------------------------------------
# STAGE 5: OUTPUT — serialize results
# ---------------------------------------------------------------------------
def write_csv_output(results: List[Tuple[str, float]], output_path: str, columns: List[str]):
    """Write results to CSV with specified column names."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for year, value in results:
            writer.writerow([year, value])


def write_json_output(results: List[Tuple[str, float]], output_path: str, columns: List[str]):
    """Write results to JSON."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    records = []
    for year, value in results:
        record = {}
        for i, col in enumerate(columns):
            record[col] = year if i == 0 else value
        records.append(record)
    
    with open(output_path, 'w') as f:
        json.dump(records, f, indent=2)


# ---------------------------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------------------------
def run_pipeline(
    source_dir: str,
    company: str,
    ticker: Optional[str] = None,
    metric: str = "gross_margin",
    conditional: Optional[str] = None,
    output_path: str = "/app/results.csv",
    output_columns: Optional[List[str]] = None,
    round_digits: int = 2,
    growth_field: str = "revenue",
) -> List[Tuple[str, float]]:
    """Execute the full 5-stage pipeline."""
    
    # Default output columns
    if output_columns is None:
        output_columns = ["fiscal_year", f"{metric}_pct"]
    
    print(f"[STAGE 1] Discovering files for '{company}' in {source_dir}...")
    files = discover_files(source_dir, company, ticker)
    print(f"  → Found: {files}")
    
    # Parse all discovered files and canonicalize each
    all_records = []
    for fpath in files:
        print(f"[STAGE 2] Parsing {fpath}...")
        headers, rows = detect_and_parse(fpath)
        print(f"  → Headers: {headers}")
        print(f"  → Rows: {len(rows)}")
        
        print(f"[STAGE 3] Canonicalizing schema...")
        field_map, records = canonicalize(headers, rows)
        print(f"  → Mapped fields: {list(field_map.keys())}")
        print(f"  → Records: {len(records)}")
        all_records.append(records)
    
    # Join records from multiple files by fiscal_year
    if len(all_records) > 1:
        print(f"[STAGE 2.5] Joining {len(all_records)} files by fiscal_year...")
        records = join_records(all_records)
        print(f"  → Merged records: {len(records)}")
    else:
        records = all_records[0]
    
    print(f"[STAGE 4] Computing metrics...")
    cond = parse_conditional(conditional)
    if cond:
        chosen_metric, results = apply_conditional(records, cond, round_digits, growth_field)
        # Update output columns to reflect chosen metric
        if len(output_columns) >= 2:
            output_columns[1] = f"{chosen_metric}_pct"
        print(f"  → Conditional: latest {cond['metric']} {cond['operator']} {cond['threshold']}")
        print(f"  → Chosen metric: {chosen_metric}")
    else:
        results = compute_metric(records, metric, round_digits, growth_field)
        print(f"  → Metric: {metric}")
        if metric == "year_over_year_growth":
            print(f"  → Growth field: {growth_field}")
    
    print(f"  → Results: {results}")
    
    print(f"[STAGE 5] Writing output to {output_path}...")
    if output_path.endswith('.json'):
        write_json_output(results, output_path, output_columns)
    else:
        write_csv_output(results, output_path, output_columns)
    
    print(f"  → Done! Wrote {len(results)} rows.")
    return results


def main():
    parser = argparse.ArgumentParser(description="Financial Analysis Pipeline")
    parser.add_argument('--source-dir', required=True, help='Directory containing financial data files')
    parser.add_argument('--company', required=True, help='Target company name')
    parser.add_argument('--ticker', default=None, help='Target company ticker symbol')
    parser.add_argument('--metric', default='gross_margin', help='Financial metric to compute')
    parser.add_argument('--conditional', default=None, help='Conditional rule (e.g., "if latest gross_margin > 70 then gross_margin else net_margin")')
    parser.add_argument('--output-path', default='/app/results.csv', help='Output file path')
    parser.add_argument('--output-columns', default=None, help='Comma-separated output column names')
    parser.add_argument('--round', type=int, default=2, help='Decimal places for rounding')
    parser.add_argument('--growth-field', default='revenue',
                        help='Field to compute YoY growth on (default: revenue). '
                             'Use when task specifies growth of a specific metric like net_income.')
    
    args = parser.parse_args()
    
    output_columns = args.output_columns.split(',') if args.output_columns else None
    
    results = run_pipeline(
        source_dir=args.source_dir,
        company=args.company,
        ticker=args.ticker,
        metric=args.metric,
        conditional=args.conditional,
        output_path=args.output_path,
        output_columns=output_columns,
        round_digits=args.round,
        growth_field=args.growth_field,
    )
    
    return results


if __name__ == '__main__':
    main()
