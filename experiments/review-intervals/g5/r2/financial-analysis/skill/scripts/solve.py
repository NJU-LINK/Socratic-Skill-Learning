#!/usr/bin/env python3
"""
Generalized Financial Analysis Solver

Discovers financial data files, extracts tabular data, computes metrics,
and writes results based on conditional logic.

Usage:
    python solve.py --company "NVIDIA" --directory /app/financials \
                    --output /app/results.csv \
                    --primary-metric gross_margin \
                    --threshold 70.0 \
                    --fallback-metric net_margin \
                    --output-columns fiscal_year,gross_margin_pct \
                    --fallback-columns fiscal_year,net_margin_pct
"""

import os
import sys
import csv
import io
import re
import argparse
import json


# ─── Metric Definitions ─────────────────────────────────────────────────────

METRICS = {
    'gross_margin': {
        'numerator_fields': ['grossprofit', 'gross_profit', 'gp'],
        'denominator_fields': ['revenue', 'total_revenue', 'rev', 'sales'],
        'formula': lambda num, den: (num / den) * 100 if den != 0 else 0.0,
        'description': 'Gross Profit / Revenue × 100',
    },
    'operating_margin': {
        'numerator_fields': ['operatingincome', 'operating_income', 'oi', 'opincome'],
        'denominator_fields': ['revenue', 'total_revenue', 'rev', 'sales'],
        'formula': lambda num, den: (num / den) * 100 if den != 0 else 0.0,
        'description': 'Operating Income / Revenue × 100',
    },
    'net_margin': {
        'numerator_fields': ['netincome', 'net_income', 'ni', 'net_profit', 'earnings'],
        'denominator_fields': ['revenue', 'total_revenue', 'rev', 'sales'],
        'formula': lambda num, den: (num / den) * 100 if den != 0 else 0.0,
        'description': 'Net Income / Revenue × 100',
    },
    'return_on_equity': {
        'numerator_fields': ['netincome', 'net_income', 'ni', 'net_profit'],
        'denominator_fields': ['shareholdersequity', 'shareholders_equity',
                               'equity', 'se', 'totalequity', 'total_equity'],
        'formula': lambda num, den: (num / den) * 100 if den != 0 else 0.0,
        'description': 'Net Income / Shareholders Equity × 100',
    },
    'year_over_year_growth': {
        'numerator_fields': ['revenue', 'total_revenue', 'rev', 'sales'],
        'denominator_fields': None,  # Special: needs prior period
        'formula': None,  # Special: computed differently
        'description': '(Current - Prior) / Prior × 100',
    },
}


# ─── File Discovery ──────────────────────────────────────────────────────────

def discover_file(directory, target_company):
    """
    Find the file containing the target company by content inspection.
    Scores candidates by CSV-data density to prefer files with tabular data.
    Returns (filepath, content) tuple.
    """
    candidates = []
    for fname in sorted(os.listdir(directory)):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, 'r', errors='replace') as f:
                content = f.read()
        except Exception:
            continue

        if target_company.lower() in content.lower():
            lines = content.strip().split('\n')
            csv_rows = sum(1 for l in lines if ',' in l and re.search(r'\d', l))
            candidates.append((fpath, content, csv_rows))

    if not candidates:
        raise FileNotFoundError(
            f"No file in '{directory}' contains '{target_company}'"
        )

    # Return highest-scoring candidate
    best = max(candidates, key=lambda x: x[2])
    print(f"[discover] Found '{target_company}' in: {best[0]} "
          f"(data density score: {best[2]})")
    return best[0], best[1]


# ─── CSV Block Extraction ────────────────────────────────────────────────────

def extract_csv_block(content):
    """
    Extract the CSV data block from a decorated file.
    Finds header row by keyword matching, reads consecutive data rows.
    """
    lines = content.strip().split('\n')

    # Find header row
    header_idx = None
    financial_keywords = ['year', 'revenue', 'income', 'profit', 'quarter',
                          'period', 'date', 'sales', 'margin', 'equity',
                          'earnings', 'fiscal']
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(('=', '-', '*', '#')):
            continue
        if ',' in stripped:
            lower = stripped.lower()
            if any(kw in lower for kw in financial_keywords):
                header_idx = i
                break

    if header_idx is None:
        # Fallback: find any line with commas and digits
        for i, line in enumerate(lines):
            stripped = line.strip()
            if ',' in stripped and re.search(r'\d', stripped):
                # Check if next line also has data (suggests this is header)
                if i + 1 < len(lines) and ',' in lines[i + 1]:
                    header_idx = i
                    break

    if header_idx is None:
        raise ValueError("Could not find CSV header in file content")

    header = lines[header_idx].strip()

    # Collect data rows
    data_rows = []
    for i in range(header_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        # Stop conditions
        if stripped.startswith(('=', '-', '*', '#', '[', 'NOTE', 'Note',
                                'Source', 'source', 'END', 'end')):
            break
        if ',' in stripped and re.search(r'\d', stripped):
            data_rows.append(stripped)
        else:
            # Non-data line without digits
            if not re.search(r'\d', stripped):
                break

    csv_text = header + '\n' + '\n'.join(data_rows)
    print(f"[extract] Found CSV block: {len(data_rows)} data rows")
    return csv_text


def extract_json_data(content):
    """Extract tabular data from JSON format."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    # Navigate to find array of records
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        return data
    if isinstance(data, dict):
        # Look for common keys containing arrays
        for key in ['data', 'records', 'results', 'financials', 'statements',
                     'income_statement', 'balance_sheet']:
            if key in data and isinstance(data[key], list):
                return data[key]
        # Try nested structures
        for val in data.values():
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                return val
    return None


def extract_html_table(content):
    """Extract tabular data from HTML tables."""
    # Simple HTML table extraction
    import re as _re
    tables = _re.findall(r'<table[^>]*>(.*?)</table>', content, _re.DOTALL | _re.IGNORECASE)
    if not tables:
        return None

    best_table = None
    best_score = -1
    for table in tables:
        rows = _re.findall(r'<tr[^>]*>(.*?)</tr>', table, _re.DOTALL | _re.IGNORECASE)
        data_rows = [r for r in rows if _re.search(r'\d', r)]
        if len(data_rows) > best_score:
            best_score = len(data_rows)
            best_table = table

    if best_table is None:
        return None

    # Parse HTML table to CSV
    rows = _re.findall(r'<tr[^>]*>(.*?)</tr>', best_table, _re.DOTALL | _re.IGNORECASE)
    csv_rows = []
    for row in rows:
        cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, _re.DOTALL | _re.IGNORECASE)
        cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if cells:
            csv_rows.append(','.join(cells))

    return '\n'.join(csv_rows) if csv_rows else None


# ─── CSV Parsing ─────────────────────────────────────────────────────────────

def parse_numeric(val):
    """Clean and parse numeric values from various formats.
    
    Handles: $, €, £, ¥ currency symbols; thousands separators (, or .);
    scale suffixes (M, B, K); European decimal format; parentheses for negatives.
    
    Locale disambiguation heuristic:
    - Multiple commas (1,234,567) → US format, commas are thousands separators
    - Multiple periods (1.234.567) → European format, periods are thousands separators
    - Single comma with 1-2 digits after (1234,56) → European decimal
    - Single period with 1-2 digits after (1234.56) → US decimal
    """
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s.lower() in ('n/a', 'na', 'null', 'none', '-', '--'):
        return None
    
    # Remove currency symbols
    s = s.replace('$', '').replace('€', '').replace('£', '').replace('¥', '')
    
    # Locale disambiguation for thousands separators
    comma_count = s.count(',')
    period_count = s.count('.')
    
    if comma_count > 1 and period_count == 0:
        # US format: 1,234,567 → remove commas
        s = s.replace(',', '')
    elif period_count > 1 and comma_count == 0:
        # European format: 1.234.567 → remove periods
        s = s.replace('.', '')
    elif comma_count == 1 and period_count == 1:
        # Mixed: determine which is decimal
        comma_pos = s.rfind(',')
        period_pos = s.rfind('.')
        if comma_pos > period_pos:
            # European: 1.234,56 → period is thousands, comma is decimal
            s = s.replace('.', '').replace(',', '.')
        else:
            # US: 1,234.56 → comma is thousands, period is decimal
            s = s.replace(',', '')
    elif comma_count == 1 and period_count == 0:
        # Single comma: check if it's decimal or thousands
        parts = s.split(',')
        if len(parts[1]) <= 2:
            # European decimal: 1234,56
            s = s.replace(',', '.')
        else:
            # US thousands: 1,234
            s = s.replace(',', '')
    elif period_count == 1 and comma_count == 0:
        # Single period: likely US decimal (1234.56)
        # No transformation needed
        pass
    
    # Handle scale suffixes
    multiplier = 1.0
    if s.upper().endswith('M'):
        multiplier = 1_000_000
        s = s[:-1].strip()
    elif s.upper().endswith('B'):
        multiplier = 1_000_000_000
        s = s[:-1].strip()
    elif s.upper().endswith('K'):
        multiplier = 1_000
        s = s[:-1].strip()
    
    # Handle parentheses for negative numbers
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def parse_csv_block(csv_text):
    """Parse CSV text into list of dicts with numeric cleaning."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for row in reader:
        parsed = {}
        for key, val in row.items():
            key = key.strip() if key else key
            val = val.strip() if val else ''
            numeric = parse_numeric(val)
            parsed[key] = numeric if numeric is not None else val
        rows.append(parsed)
    return rows


# ─── Column Matching ─────────────────────────────────────────────────────────

def normalize_col(name):
    """Normalize column name for matching: lowercase, remove spaces/underscores."""
    return name.lower().replace(' ', '').replace('_', '').replace('-', '')


def find_column(columns, candidates):
    """Find a column name from a list of candidates (flexible matching)."""
    col_map = {normalize_col(c): c for c in columns}

    # Exact normalized match
    for candidate in candidates:
        norm = normalize_col(candidate)
        if norm in col_map:
            return col_map[norm]

    # Partial match
    for candidate in candidates:
        norm = normalize_col(candidate)
        for col in columns:
            if norm in normalize_col(col) or normalize_col(col) in norm:
                return col

    return None


def resolve_metric_columns(rows, metric_name):
    """Find numerator and denominator columns for a given metric."""
    if metric_name not in METRICS:
        raise ValueError(f"Unknown metric: {metric_name}")

    metric = METRICS[metric_name]
    columns = list(rows[0].keys())

    num_col = find_column(columns, metric['numerator_fields'])
    if num_col is None:
        raise ValueError(
            f"Cannot find numerator column for {metric_name}. "
            f"Tried: {metric['numerator_fields']}. Available: {columns}"
        )

    if metric['denominator_fields'] is not None:
        den_col = find_column(columns, metric['denominator_fields'])
        if den_col is None:
            raise ValueError(
                f"Cannot find denominator column for {metric_name}. "
                f"Tried: {metric['denominator_fields']}. Available: {columns}"
            )
    else:
        den_col = None

    return num_col, den_col


# ─── Year Handling ────────────────────────────────────────────────────────────

def extract_year(val):
    """Extract numeric year from various formats."""
    s = str(val).strip()
    m = re.search(r'(\d{4})', s)
    if m:
        return int(m.group(1))
    try:
        return int(float(s))
    except ValueError:
        return s


def format_year(val, preserve_format=True):
    """Format year for output. Default preserves source format (e.g., FY2022)."""
    if preserve_format:
        return str(val).strip()
    return extract_year(val)


def detect_year_format(rows, year_col):
    """Auto-detect whether source uses prefixed years (FY2022) or plain (2022).
    Returns True if most values have a non-numeric prefix like FY, Q, etc."""
    prefixed = 0
    total = 0
    for row in rows:
        val = str(row[year_col]).strip()
        if re.match(r'^[A-Za-z]', val) and re.search(r'\d{4}', val):
            prefixed += 1
        total += 1
    return prefixed > total * 0.5 if total > 0 else False


def join_datasets(datasets, year_col='year'):
    """Join multiple datasets by fiscal year (for multi-file scenarios).
    
    Args:
        datasets: list of list-of-dicts, each from a different file
        year_col: name of the year column to join on
    
    Returns:
        list of merged dicts, one per fiscal year
    """
    joined = {}
    for dataset in datasets:
        for row in dataset:
            # Find the year column in this dataset (may have different name)
            cols = list(row.keys())
            yc = find_column(cols, ['year', 'fiscal_year', 'fy', 'period'])
            if yc is None:
                continue
            year_key = extract_year(row[yc])
            if year_key not in joined:
                joined[year_key] = {}
            joined[year_key].update(row)
    
    # Return sorted by year
    return [joined[k] for k in sorted(joined.keys())]


# ─── Metric Computation ──────────────────────────────────────────────────────

def compute_metric(rows, metric_name, year_col, preserve_year_format=True):
    """Compute a metric for all rows, returning list of (year, value) tuples."""
    metric = METRICS[metric_name]
    num_col, den_col = resolve_metric_columns(rows, metric_name)

    # Sort by year
    rows_sorted = sorted(rows, key=lambda r: extract_year(r[year_col]))

    results = []
    if metric_name == 'year_over_year_growth':
        # Special case: needs consecutive periods
        for i, row in enumerate(rows_sorted):
            if i == 0:
                continue  # No prior period for first year
            curr_val = float(row[num_col])
            prev_val = float(rows_sorted[i - 1][num_col])
            if prev_val != 0:
                growth = ((curr_val - prev_val) / prev_val) * 100
            else:
                growth = 0.0
            year_out = format_year(row[year_col], preserve_year_format)
            results.append((year_out, round(growth, 2)))
    else:
        formula = metric['formula']
        for row in rows_sorted:
            num_val = float(row[num_col])
            den_val = float(row[den_col])
            value = formula(num_val, den_val)
            year_out = format_year(row[year_col], preserve_year_format)
            results.append((year_out, round(value, 2)))

    return results


# ─── Output ───────────────────────────────────────────────────────────────────

def write_results(results, output_path, col_names):
    """Write results to CSV."""
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(col_names)
        for row in results:
            writer.writerow(row)
    print(f"[output] Wrote {len(results)} rows to {output_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Financial Analysis Solver')
    parser.add_argument('--company', required=True, help='Target company name')
    parser.add_argument('--directory', required=True, help='Directory containing financial files')
    parser.add_argument('--output', required=True, help='Output CSV path')
    parser.add_argument('--primary-metric', default='gross_margin',
                        help='Primary metric to compute')
    parser.add_argument('--threshold', type=float, default=None,
                        help='Threshold for conditional logic')
    parser.add_argument('--threshold-compare', default='>',
                        choices=['>', '>=', '<', '<=', '==', '!='],
                        help='Comparison operator for threshold')
    parser.add_argument('--fallback-metric', default=None,
                        help='Fallback metric if threshold not met')
    parser.add_argument('--output-columns', default='fiscal_year,gross_margin_pct',
                        help='Comma-separated output column names')
    parser.add_argument('--fallback-columns', default=None,
                        help='Output column names for fallback metric')
    parser.add_argument('--preserve-year-format', action='store_true', default=True,
                        help='Preserve source year format in output (e.g., FY2022) [default]')
    parser.add_argument('--no-preserve-year-format', dest='preserve_year_format',
                        action='store_false', help='Strip year to numeric only (e.g., 2022)')
    parser.add_argument('--year-col-candidates', default='year,fiscal_year,fy,period',
                        help='Comma-separated year column name candidates')

    args = parser.parse_args()

    # Parse column names
    output_cols = [c.strip() for c in args.output_columns.split(',')]
    fallback_cols = None
    if args.fallback_columns:
        fallback_cols = [c.strip() for c in args.fallback_columns.split(',')]
    year_candidates = [c.strip() for c in args.year_col_candidates.split(',')]

    # Step 1: Discover file
    fpath, content = discover_file(args.directory, args.company)

    # Step 2: Extract data
    csv_text = None

    # Try CSV extraction first
    try:
        csv_text = extract_csv_block(content)
    except ValueError:
        pass

    # Try JSON if CSV extraction failed
    if csv_text is None:
        json_data = extract_json_data(content)
        if json_data:
            # Convert JSON to CSV text
            if json_data:
                keys = list(json_data[0].keys())
                csv_lines = [','.join(keys)]
                for record in json_data:
                    csv_lines.append(','.join(str(record.get(k, '')) for k in keys))
                csv_text = '\n'.join(csv_lines)

    # Try HTML if still no data
    if csv_text is None:
        html_csv = extract_html_table(content)
        if html_csv:
            csv_text = html_csv

    if csv_text is None:
        raise ValueError("Could not extract tabular data from file")

    print(f"[extract] CSV data:\n{csv_text}\n")

    # Step 3: Parse data
    rows = parse_csv_block(csv_text)
    if not rows:
        raise ValueError("No data rows parsed")
    print(f"[parse] Parsed {len(rows)} rows, columns: {list(rows[0].keys())}")

    # Step 4: Find year column
    columns = list(rows[0].keys())
    year_col = find_column(columns, year_candidates)
    if year_col is None:
        raise ValueError(f"Cannot find year column. Tried: {year_candidates}. Available: {columns}")
    print(f"[columns] Year column: {year_col}")

    # Step 5: Compute primary metric for most recent year (for threshold check)
    rows_sorted = sorted(rows, key=lambda r: extract_year(r[year_col]))
    most_recent = rows_sorted[-1]

    primary_num_col, primary_den_col = resolve_metric_columns(rows, args.primary_metric)
    most_recent_value = METRICS[args.primary_metric]['formula'](
        float(most_recent[primary_num_col]),
        float(most_recent[primary_den_col])
    )
    print(f"[check] Most recent year ({most_recent[year_col]}): "
          f"{args.primary_metric} = {most_recent_value:.2f}%")

    # Step 6: Conditional logic
    compare_ops = {
        '>': lambda a, b: a > b,
        '>=': lambda a, b: a >= b,
        '<': lambda a, b: a < b,
        '<=': lambda a, b: a <= b,
        '==': lambda a, b: a == b,
        '!=': lambda a, b: a != b,
    }

    if args.threshold is not None and args.fallback_metric:
        threshold_met = compare_ops[args.threshold_compare](
            most_recent_value, args.threshold
        )
        if threshold_met:
            print(f"[branch] {args.primary_metric} ({most_recent_value:.2f}%) "
                  f"{args.threshold_compare} {args.threshold} → using primary metric")
            results = compute_metric(rows, args.primary_metric, year_col,
                                     args.preserve_year_format)
            col_names = output_cols
        else:
            print(f"[branch] {args.primary_metric} ({most_recent_value:.2f}%) "
                  f"NOT {args.threshold_compare} {args.threshold} → using fallback metric")
            results = compute_metric(rows, args.fallback_metric, year_col,
                                     args.preserve_year_format)
            col_names = fallback_cols if fallback_cols else output_cols
    else:
        # No conditional logic, just compute the requested metric
        results = compute_metric(rows, args.primary_metric, year_col,
                                 args.preserve_year_format)
        col_names = output_cols

    # Step 7: Write output
    write_results(results, args.output, col_names)

    # Print results for verification
    print(f"\n[results]")
    with open(args.output, 'r') as f:
        print(f.read())


if __name__ == '__main__':
    main()
