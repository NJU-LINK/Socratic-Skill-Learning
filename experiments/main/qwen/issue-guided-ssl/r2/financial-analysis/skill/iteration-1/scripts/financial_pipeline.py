#!/usr/bin/env python3
"""
Financial Data Discovery, Parsing, and Metric Computation Pipeline

This script implements the reusable financial-analysis skill pipeline:
1. Content-based file discovery among decoys
2. Multi-format parsing (CSV, JSON, fixed-width text, HTML)
3. Financial metric computation (5 standard metrics)
4. Conditional computation branching
5. Output serialization

Usage:
    python3 financial_pipeline.py --config config.json
    # Or import as a library:
    from financial_pipeline import FinancialPipeline
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union


# ============================================================================
# SECTION 1: CONTENT-BASED FILE DISCOVERY
# ============================================================================

# Financial field keywords for scoring
FINANCIAL_KEYWORDS = [
    'revenue', 'gross profit', 'net income', 'operating income',
    'total assets', 'shareholders equity', 'total equity', 'stockholders equity',
    'gross margin', 'operating margin', 'net margin', 'ebit',
    'cost of revenue', 'operating expenses', 'net sales', 'turnover',
    'income statement', 'balance sheet', 'fiscal year'
]

# Decoy patterns
LOG_PREFIXES = ['[INFO]', '[WARN]', '[ERROR]', '[DATA]', '[DEBUG]']
PRODUCT_KEYWORDS = ['product', 'units', 'sku', 'quantity', 'item']
QUARTERLY_PATTERN = re.compile(r'Q[1-4]_\d{4}')


def score_file(filepath: str, target_company: str) -> float:
    """Score a file for relevance to the target company's financial data."""
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read(5000)  # Read first 5000 chars for preview
    except Exception:
        return -100

    score = 0.0
    content_lower = content.lower()

    # (a) Company match
    company_lower = target_company.lower()
    # Check for full company name or ticker
    if company_lower in content_lower:
        score += 10
    # Also check for common ticker patterns
    if re.search(rf'\b{re.escape(company_lower)}\b', content_lower):
        score += 5

    # (b) Financial field presence
    for keyword in FINANCIAL_KEYWORDS:
        if keyword in content_lower:
            score += 2

    # (c) Annual structure: year labels
    if re.search(r'FY\d{4}|FY\s*\d{4}|\b(19|20)\d{2}\b', content):
        score += 5

    # (d) Reject decoy patterns
    for prefix in LOG_PREFIXES:
        if prefix in content:
            score -= 15
            break

    # Product-level data detection
    product_count = sum(1 for kw in PRODUCT_KEYWORDS if kw in content_lower)
    if product_count >= 2:
        score -= 20

    # Quarterly-only detection
    quarterly_matches = QUARTERLY_PATTERN.findall(content)
    annual_matches = re.findall(r'FY\d{4}|\b(19|20)\d{2}\b', content)
    if quarterly_matches and not annual_matches:
        score -= 10

    return score


def discover_financial_file(directory: str, target_company: str) -> str:
    """Find the most relevant financial data file for the target company."""
    files = []
    for entry in os.listdir(directory):
        full_path = os.path.join(directory, entry)
        if os.path.isfile(full_path):
            files.append(full_path)

    if not files:
        raise FileNotFoundError(f"No files found in {directory}")

    scored = [(f, score_file(f, target_company)) for f in files]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_file, best_score = scored[0]
    if best_score <= 0:
        raise ValueError(
            f"No suitable financial file found for '{target_company}' in {directory}. "
            f"Best score: {best_score} for {best_file}"
        )

    return best_file


# ============================================================================
# SECTION 2: FORMAT DETECTION AND PARSING
# ============================================================================

def detect_format(filepath: str) -> str:
    """Detect file format from extension and content."""
    ext = Path(filepath).suffix.lower()

    if ext == '.csv':
        return 'csv'
    elif ext == '.json':
        return 'json'
    elif ext == '.html' or ext == '.htm':
        return 'html'
    elif ext in ('.dat', '.txt', '.tsv'):
        # Check content
        with open(filepath, 'r', errors='ignore') as f:
            first_line = f.readline()
            if '<table' in first_line.lower() or '<html' in first_line.lower():
                return 'html'
            if first_line.strip().startswith('{') or first_line.strip().startswith('['):
                return 'json'
            if ext == '.tsv' or '\t' in first_line:
                return 'tsv'
            return 'fixed_width'

    # Fallback: check content
    with open(filepath, 'r', errors='ignore') as f:
        content = f.read(1000)
    if content.strip().startswith('{') or content.strip().startswith('['):
        return 'json'
    if '<table' in content.lower():
        return 'html'
    if ',' in content.split('\n')[0] and content.count(',') > 3:
        return 'csv'
    return 'fixed_width'


def normalize_numeric(value: str) -> Optional[float]:
    """Normalize a financial numeric string to a float."""
    if value is None:
        return None

    s = str(value).strip()
    if not s or s in ('-', '—', 'N/A', 'n/a', 'null', 'None', ''):
        return None

    # Remove currency symbols
    s = re.sub(r'[$€£¥₹]', '', s)
    # Remove parentheses for negative numbers: (1,234) -> -1234
    is_negative = False
    if s.startswith('(') and s.endswith(')'):
        is_negative = True
        s = s[1:-1]

    # Handle scale suffixes
    multiplier = 1.0
    s_upper = s.upper().strip()
    if s_upper.endswith('M') or 'MILLION' in s_upper:
        multiplier = 1_000_000
        s = re.sub(r'[Mm]\s*$|[Mm]illion', '', s, flags=re.IGNORECASE).strip()
    elif s_upper.endswith('B') or 'BILLION' in s_upper:
        multiplier = 1_000_000_000
        s = re.sub(r'[Bb]\s*$|[Bb]illion', '', s, flags=re.IGNORECASE).strip()
    elif s_upper.endswith('K') or 'THOUSAND' in s_upper:
        multiplier = 1_000
        s = re.sub(r'[Kk]\s*$|[Tt]housand', '', s, flags=re.IGNORECASE).strip()

    # Handle European decimal format BEFORE removing commas
    # European: "1.234,56" -> 1234.56 (period=thousands, comma=decimal)
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            # European format: remove periods (thousands sep), replace comma with period
            s = s.replace('.', '').replace(',', '.')
        else:
            # Standard format: remove commas (thousands sep)
            s = s.replace(',', '')
    elif ',' in s and '.' not in s:
        # Could be European decimal: "1234,56" -> 1234.56
        # Or thousands: "1,234" -> 1234
        # Heuristic: if digits after comma <= 2, treat as decimal
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')

    # Remove any remaining space thousands separators
    s = s.replace(' ', '')

    try:
        result = float(s) * multiplier
        return -result if is_negative else result
    except ValueError:
        return None


def parse_csv_file(filepath: str) -> List[Dict[str, Any]]:
    """Parse a CSV financial data file."""
    with open(filepath, 'r', errors='ignore') as f:
        reader = csv.DictReader(f)
        return list(reader)


def parse_fixed_width_file(filepath: str) -> List[Dict[str, Any]]:
    """Parse a fixed-width text file with financial data."""
    with open(filepath, 'r', errors='ignore') as f:
        lines = f.readlines()

    # Find header row
    header_idx = None
    for i, line in enumerate(lines):
        line_lower = line.lower()
        # Header should contain 'year' or 'fiscal' AND at least one financial field
        has_year = bool(re.search(r'\b(year|fiscal|fy)\b', line_lower))
        has_financial = any(kw in line_lower for kw in
                           ['revenue', 'profit', 'income', 'equity', 'margin'])
        if has_year and has_financial:
            header_idx = i
            break

    if header_idx is None:
        # Fallback: look for any line with comma-separated or multi-space-separated financial terms
        for i, line in enumerate(lines):
            if 'revenue' in line.lower() and ('year' in line.lower() or 'fy' in line.lower()):
                header_idx = i
                break

    if header_idx is None:
        raise ValueError(f"Cannot find header row in {filepath}")

    header_line = lines[header_idx].strip()

    # Detect delimiter
    if ',' in header_line:
        delimiter = ','
    elif '\t' in header_line:
        delimiter = '\t'
    else:
        delimiter = None  # Split on 2+ spaces

    if delimiter:
        headers = [h.strip() for h in header_line.split(delimiter)]
    else:
        headers = re.split(r'\s{2,}', header_line)

    # Parse data rows
    data = []
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        # Skip empty lines, separator lines, notes
        if not stripped:
            continue
        if re.match(r'^[=\-]+$', stripped):
            continue
        if stripped.startswith('NOTE') or stripped.startswith('Note'):
            continue
        if stripped.startswith('#'):
            continue

        if delimiter:
            values = [v.strip() for v in stripped.split(delimiter)]
        else:
            values = re.split(r'\s{2,}', stripped)

        if len(values) >= 2:
            row = {}
            for j, header in enumerate(headers):
                if j < len(values):
                    row[header] = values[j]
            data.append(row)

    return data


def parse_json_file(filepath: str) -> List[Dict[str, Any]]:
    """Parse a JSON financial data file."""
    with open(filepath, 'r') as f:
        data = json.load(f)

    # Find financial records in the JSON structure
    records = []

    def find_records(obj, depth=0):
        if depth > 10:
            return
        if isinstance(obj, list):
            # Check if this looks like financial records
            if obj and isinstance(obj[0], dict):
                keys = set(k.lower() for k in obj[0].keys())
                financial_keys = {'revenue', 'gross profit', 'net income',
                                 'operating income', 'year', 'fiscal_year'}
                if keys & financial_keys:
                    records.extend(obj)
                    return
            for item in obj:
                find_records(item, depth + 1)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                find_records(value, depth + 1)

    find_records(data)
    return records


def parse_financial_file(filepath: str) -> List[Dict[str, Any]]:
    """Parse a financial data file, auto-detecting format."""
    fmt = detect_format(filepath)

    if fmt == 'csv':
        return parse_csv_file(filepath)
    elif fmt == 'json':
        return parse_json_file(filepath)
    elif fmt == 'fixed_width':
        return parse_fixed_width_file(filepath)
    elif fmt == 'tsv':
        with open(filepath, 'r', errors='ignore') as f:
            reader = csv.DictReader(f, delimiter='\t')
            return list(reader)
    elif fmt == 'html':
        try:
            import pandas as pd
            tables = pd.read_html(filepath)
            if tables:
                return tables[0].to_dict('records')
        except ImportError:
            pass
        raise ValueError("HTML parsing requires pandas. Install with: pip install pandas lxml")
    else:
        raise ValueError(f"Unsupported format: {fmt}")


# ============================================================================
# SECTION 3: FIELD NAME NORMALIZATION
# ============================================================================

FIELD_ALIASES = {
    'revenue': ['revenue', 'total revenue', 'net sales', 'sales', 'turnover'],
    'gross_profit': ['gross profit', 'gross margin'],  # gross margin as amount
    'operating_income': ['operating income', 'ebit', 'operating profit'],
    'net_income': ['net income', 'net profit', 'net earnings', 'profit after tax'],
    'shareholders_equity': ['shareholders equity', 'total equity',
                           'stockholders equity', 'book value', "shareholders' equity"],
    'fiscal_year': ['year', 'fiscal year', 'fy', 'fiscal_year', 'period'],
}


def camel_case_to_spaces(name: str) -> str:
    """Convert camelCase or PascalCase to space-separated lowercase."""
    # Insert space before each uppercase letter that follows a lowercase letter
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # Insert space between consecutive uppercase followed by lowercase (e.g., "EBIT" -> "EBIT", "FY2024" -> "FY 2024")
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    return s.lower().strip()


def normalize_field_name(name: str) -> Optional[str]:
    """Map a field name to its canonical form."""
    # Try multiple normalizations
    candidates = [
        name.lower().strip(),                              # direct lowercase
        camel_case_to_spaces(name),                         # camelCase -> spaces
        name.lower().replace('_', ' ').strip(),             # underscores -> spaces
        name.lower().replace('-', ' ').strip(),             # hyphens -> spaces
    ]
    # Also try removing all spaces for matching against concatenated aliases
    for canonical, aliases in FIELD_ALIASES.items():
        for candidate in candidates:
            if candidate in aliases:
                return canonical
            # Also try without spaces on both sides
            candidate_nospace = candidate.replace(' ', '')
            for alias in aliases:
                if candidate_nospace == alias.replace(' ', ''):
                    return canonical
    return None


def normalize_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize field names and numeric values in parsed records."""
    normalized = []
    for record in records:
        new_record = {}
        for key, value in record.items():
            canonical = normalize_field_name(key)
            if canonical:
                if canonical == 'fiscal_year':
                    new_record[canonical] = str(value).strip()
                else:
                    numeric = normalize_numeric(str(value))
                    if numeric is not None:
                        new_record[canonical] = numeric
            else:
                # Keep unrecognized fields as-is
                new_record[key] = value
        normalized.append(new_record)
    return normalized


# ============================================================================
# SECTION 4: METRIC COMPUTATION
# ============================================================================

def compute_gross_margin(records: List[Dict]) -> List[Tuple[str, float]]:
    """Compute gross margin for each period."""
    results = []
    for r in records:
        if 'revenue' in r and 'gross_profit' in r and r['revenue'] != 0:
            gm = (r['gross_profit'] / r['revenue']) * 100
            year = r.get('fiscal_year', 'unknown')
            results.append((year, round(gm, 2)))
    return results


def compute_operating_margin(records: List[Dict]) -> List[Tuple[str, float]]:
    """Compute operating margin for each period."""
    results = []
    for r in records:
        if 'revenue' in r and 'operating_income' in r and r['revenue'] != 0:
            om = (r['operating_income'] / r['revenue']) * 100
            year = r.get('fiscal_year', 'unknown')
            results.append((year, round(om, 2)))
    return results


def compute_net_margin(records: List[Dict]) -> List[Tuple[str, float]]:
    """Compute net margin for each period."""
    results = []
    for r in records:
        if 'revenue' in r and 'net_income' in r and r['revenue'] != 0:
            nm = (r['net_income'] / r['revenue']) * 100
            year = r.get('fiscal_year', 'unknown')
            results.append((year, round(nm, 2)))
    return results


def compute_return_on_equity(records: List[Dict]) -> List[Tuple[str, float]]:
    """Compute ROE for each period. Uses average equity if multiple years available."""
    equities = [(r.get('fiscal_year', 'unknown'), r.get('shareholders_equity'))
                for r in records if 'shareholders_equity' in r]

    results = []
    for i, r in enumerate(records):
        if 'net_income' in r and 'shareholders_equity' in r:
            equity = r['shareholders_equity']
            # If we have prior year equity, use average
            if i > 0 and 'shareholders_equity' in records[i-1]:
                avg_equity = (equity + records[i-1]['shareholders_equity']) / 2
            else:
                avg_equity = equity

            if avg_equity != 0:
                roe = (r['net_income'] / avg_equity) * 100
                year = r.get('fiscal_year', 'unknown')
                results.append((year, round(roe, 2)))
    return results


def compute_yoy_growth(records: List[Dict]) -> List[Tuple[str, Optional[float]]]:
    """Compute year-over-year revenue growth. First year is None."""
    results = []
    for i, r in enumerate(records):
        year = r.get('fiscal_year', 'unknown')
        if i == 0 or 'revenue' not in r or 'revenue' not in records[i-1]:
            results.append((year, None))
        else:
            prior_rev = records[i-1]['revenue']
            if prior_rev != 0:
                growth = ((r['revenue'] - prior_rev) / prior_rev) * 100
                results.append((year, round(growth, 2)))
            else:
                results.append((year, None))
    return results


METRIC_FUNCTIONS = {
    'gross_margin': compute_gross_margin,
    'operating_margin': compute_operating_margin,
    'net_margin': compute_net_margin,
    'return_on_equity': compute_return_on_equity,
    'year_over_year_growth': compute_yoy_growth,
}


def compute_metric(records: List[Dict], metric_name: str) -> List[Tuple[str, Any]]:
    """Compute a named financial metric."""
    if metric_name not in METRIC_FUNCTIONS:
        raise ValueError(f"Unknown metric: {metric_name}. Available: {list(METRIC_FUNCTIONS.keys())}")
    return METRIC_FUNCTIONS[metric_name](records)


# ============================================================================
# SECTION 5: CONDITIONAL COMPUTATION
# ============================================================================

def conditional_compute(
    records: List[Dict],
    primary_metric: str,
    threshold: float,
    comparison: str,  # 'exceeds', 'above', 'below', 'does_not_exceed'
    fallback_metric: Optional[str] = None,
    check_period: str = 'most_recent'
) -> Tuple[str, List[Tuple[str, Any]]]:
    """
    Compute primary metric, evaluate condition, optionally branch to fallback.

    Returns: (metric_name_used, results)
    """
    primary_values = compute_metric(records, primary_metric)

    # Get comparison value
    if check_period == 'most_recent':
        comparison_value = primary_values[-1][1] if primary_values else None
    else:
        # Find specific period
        comparison_value = None
        for year, val in primary_values:
            if year == check_period:
                comparison_value = val
                break

    # Evaluate condition
    condition_met = False
    if comparison_value is not None:
        if comparison in ('exceeds', 'above', '>'):
            condition_met = comparison_value > threshold
        elif comparison in ('below', '<'):
            condition_met = comparison_value < threshold
        elif comparison in ('does_not_exceed', '<=', 'not_above'):
            condition_met = comparison_value <= threshold

    if condition_met or fallback_metric is None:
        return primary_metric, primary_values
    else:
        fallback_values = compute_metric(records, fallback_metric)
        return fallback_metric, fallback_values


# ============================================================================
# SECTION 6: OUTPUT SERIALIZATION
# ============================================================================

def write_csv_output(
    results: List[Tuple[str, Any]],
    output_path: str,
    column_names: List[str] = None
):
    """Write results to CSV file."""
    if column_names is None:
        column_names = ['fiscal_year', 'value']

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(column_names)
        for year, value in results:
            if value is not None:
                writer.writerow([year, value])
            else:
                writer.writerow([year, ''])


# ============================================================================
# MAIN PIPELINE
# ============================================================================

class FinancialPipeline:
    """Complete financial analysis pipeline."""

    def __init__(self, data_dir: str, target_company: str):
        self.data_dir = data_dir
        self.target_company = target_company

    def discover(self) -> str:
        """Find the correct financial data file."""
        return discover_financial_file(self.data_dir, self.target_company)

    def parse(self, filepath: str) -> List[Dict]:
        """Parse and normalize financial data."""
        raw = parse_financial_file(filepath)
        return normalize_records(raw)

    def compute(self, records: List[Dict], metric: str) -> List[Tuple[str, Any]]:
        """Compute a financial metric."""
        return compute_metric(records, metric)

    def run(self, metric: str, output_path: str, output_columns: List[str] = None):
        """Run the complete pipeline."""
        filepath = self.discover()
        records = self.parse(filepath)
        results = self.compute(records, metric)
        write_csv_output(results, output_path, output_columns)
        return results


if __name__ == '__main__':
    # Example: NVIDIA gross margin computation
    pipeline = FinancialPipeline('/app/financials', 'NVIDIA Corporation')
    filepath = pipeline.discover()
    print(f"Discovered file: {filepath}")

    records = pipeline.parse(filepath)
    print(f"Parsed {len(records)} records")
    for r in records:
        print(f"  {r}")

    results = pipeline.compute(records, 'gross_margin')
    print(f"\nGross Margin results:")
    for year, gm in results:
        print(f"  {year}: {gm}%")

    # Check conditional: most recent year > 70%?
    most_recent_gm = results[-1][1]
    print(f"\nMost recent year gross margin: {most_recent_gm}%")
    print(f"Exceeds 70%? {most_recent_gm > 70}")

    if most_recent_gm > 70:
        write_csv_output(results, '/app/results.csv', ['fiscal_year', 'gross_margin_pct'])
        print("Wrote gross margin results to /app/results.csv")
    else:
        net_results = pipeline.compute(records, 'net_margin')
        write_csv_output(net_results, '/app/results.csv', ['fiscal_year', 'net_margin_pct'])
        print("Wrote net margin results to /app/results.csv")
