#!/usr/bin/env python3
"""
Multi-format financial data parser.

Handles CSV, JSON, fixed-width text, HTML tables, and mixed log/data formats.
Extracts financial line items with locale-aware numeric parsing.
"""

import csv
import json
import re
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ─── Synonym maps for financial concepts ───────────────────────────────────────

FIELD_SYNONYMS = {
    'revenue': [
        'revenue', 'total revenue', 'net sales', 'sales', 'net revenue',
        'total net sales', 'total net revenue', 'chiffre d\'affaires',
        'umsatz', 'ingresos', 'ricavi',
    ],
    'gross_profit': [
        'gross profit', 'gross margin', 'gross income',
        'profit before operating expenses', 'marge brute',
        'rohergebnis', 'bruttogewinn',
    ],
    'operating_income': [
        'operating income', 'operating profit', 'operating earnings',
        'ebit', 'income from operations', 'operating result',
        'betriebsergebnis', 'resultado operativo',
    ],
    'net_income': [
        'net income', 'net earnings', 'net profit', 'profit after tax',
        'profit for the year', 'net profit attributable',
        'income after tax', 'résultat net', 'nettoergebnis',
        'resultado neto', 'utile netto',
    ],
    'shareholders_equity': [
        "shareholders' equity", "stockholders' equity", 'total equity',
        'total shareholders equity', 'total stockholders equity',
        'book value', 'net assets', 'owners equity',
        'capitaux propres', 'eigenkapital', 'patrimonio neto',
    ],
    'cost_of_revenue': [
        'cost of revenue', 'cost of goods sold', 'cogs',
        'cost of sales', 'cost of net revenue',
        'coûts des ventes', 'kosten der umsatzerlöse',
    ],
}


# ─── Numeric parsing ──────────────────────────────────────────────────────────

def parse_number(text: str) -> Optional[float]:
    """
    Parse a numeric string, handling various locale formats:
    - US: 1,234.56
    - EU: 1.234,56
    - Space-separated: 1 234.56
    - Parenthetical negatives: (1,234) → -1234
    - Currency symbols: $1,234.56, €1.234,56
    - Suffixes: 1,234M, 1.2B, 1K
    """
    if text is None:
        return None

    text = str(text).strip()
    if not text or text == '-' or text == '—' or text == '':
        return None

    # Detect parenthetical negatives
    negative = False
    if text.startswith('(') and text.endswith(')'):
        negative = True
        text = text[1:-1].strip()

    # Remove currency symbols and whitespace
    text = re.sub(r'[$€£¥₹\s]', '', text)

    # Handle suffix multipliers
    multiplier = 1.0
    suffix_match = re.search(r'([KMBkmb])$', text)
    if suffix_match:
        suffix = suffix_match.group(1).upper()
        text = text[:-1]
        if suffix == 'K':
            multiplier = 1_000
        elif suffix == 'M':
            multiplier = 1_000_000
        elif suffix == 'B':
            multiplier = 1_000_000_000

    # Remove leading/trailing non-numeric except minus/dot/comma
    text = text.strip()

    # Determine locale format
    has_comma = ',' in text
    has_dot = '.' in text

    if has_comma and has_dot:
        last_comma = text.rfind(',')
        last_dot = text.rfind('.')
        if last_comma > last_dot:
            # EU format: 1.234,56 → comma is decimal
            text = text.replace('.', '')
            text = text.replace(',', '.')
        else:
            # US format: 1,234.56 → comma is thousands
            text = text.replace(',', '')
    elif has_comma and not has_dot:
        # Could be EU decimal (1234,56) or US thousands (1,234)
        if re.search(r',\d{3}$', text):
            text = text.replace(',', '')
        else:
            text = text.replace(',', '.')

    # Remove any remaining non-numeric chars except digits, dot, minus
    text = re.sub(r'[^\d.\-]', '', text)

    if not text or text == '-' or text == '.':
        return None

    try:
        value = float(text) * multiplier
        if negative:
            value = -value
        return value
    except ValueError:
        return None


# ─── Year label normalization ─────────────────────────────────────────────────

def normalize_year(label: str) -> Optional[int]:
    """
    Normalize various year label formats to an integer year.
    Handles: 2025, FY2025, FY25, Year Ended Jan 2025, 2024-2025, etc.
    """
    if label is None:
        return None
    label = str(label).strip()

    # FY2025 or FY25
    m = re.match(r'(?:FY|fy)\s*(\d{2,4})', label)
    if m:
        year = int(m.group(1))
        if year < 100:
            year += 2000
        return year

    # Year Ended ... 2025
    m = re.search(r'(\d{4})', label)
    if m:
        return int(m.group(1))

    # Plain number
    m = re.match(r'^(\d{4})$', label)
    if m:
        return int(m.group(1))

    return None


# ─── Format detection and parsing ─────────────────────────────────────────────

def detect_format(content: str) -> str:
    """Detect the format of the file content."""
    stripped = content.strip()
    if stripped.startswith('{') or stripped.startswith('['):
        return 'json'
    if '<table' in stripped.lower() or '<tr' in stripped.lower():
        return 'html'
    # Check for CSV-like structure
    lines = stripped.split('\n')
    if len(lines) > 1:
        first_line = lines[0]
        if ',' in first_line and len(first_line.split(',')) >= 2:
            return 'csv'
    return 'mixed'


def extract_csv_section(content: str) -> Optional[str]:
    """
    Find and extract the CSV data section from mixed content.
    Looks for a header line with financial field names followed by data rows.
    """
    lines = content.split('\n')

    # Find header line: a line with multiple comma-separated financial terms
    best_header_idx = -1
    best_field_count = 0

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if ',' not in line_stripped:
            continue
        parts = [p.strip().lower() for p in line_stripped.split(',')]
        field_count = 0
        for part in parts:
            for concept, synonyms in FIELD_SYNONYMS.items():
                if any(s == part or s in part for s in synonyms):
                    field_count += 1
                    break
            # Also check for 'year' or similar
            if part in ('year', 'fiscal year', 'period', 'date'):
                field_count += 1
        if field_count > best_field_count:
            best_field_count = field_count
            best_header_idx = i

    if best_header_idx < 0 or best_field_count < 2:
        return None

    # Extract from header to end of data (stop at non-data lines)
    csv_lines = [lines[best_header_idx]]
    for line in lines[best_header_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        # Stop if line doesn't look like data (no commas, or starts with special chars)
        if ',' not in stripped:
            break
        if stripped.startswith('=') or stripped.startswith('-') or stripped.startswith('#'):
            break
        # Check if at least one field looks numeric
        parts = stripped.split(',')
        has_number = any(re.search(r'\d', p) for p in parts[1:])
        if has_number:
            csv_lines.append(stripped)
        else:
            break

    return '\n'.join(csv_lines)


def parse_csv_data(content: str) -> List[Dict[str, Any]]:
    """Parse CSV content into records."""
    records = []
    reader = csv.DictReader(content.splitlines())
    for row in reader:
        records.append(dict(row))
    return records


def parse_json_data(content: str) -> List[Dict[str, Any]]:
    """Parse JSON content, handling nested structures."""
    data = json.loads(content)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ['data', 'records', 'financials', 'results', 'items']:
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    return []


def parse_html_tables(content: str) -> List[Dict[str, Any]]:
    """Parse HTML tables into records."""
    records = []
    tables = re.findall(r'<table[^>]*>(.*?)</table>', content, re.DOTALL | re.IGNORECASE)
    for table in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL | re.IGNORECASE)
        headers = []
        for row in rows:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if not headers:
                headers = cells
            else:
                record = {}
                for i, header in enumerate(headers):
                    if i < len(cells):
                        record[header] = cells[i]
                records.append(record)
    return records


def parse_mixed_content(content: str) -> List[Dict[str, Any]]:
    """
    Parse mixed content (log files with embedded data, fixed-width, etc.).
    First tries to find a CSV section within the content.
    Falls back to fixed-width or line-by-line extraction.
    """
    # First, try to extract a CSV section
    csv_section = extract_csv_section(content)
    if csv_section:
        return parse_csv_data(csv_section)

    # Fall back to line-by-line extraction
    records = []
    lines = content.split('\n')

    # Find header line
    header_line = None
    header_idx = -1
    for i, line in enumerate(lines):
        line_lower = line.lower()
        field_hits = sum(1 for concept, synonyms in FIELD_SYNONYMS.items()
                        if any(s in line_lower for s in synonyms))
        if field_hits >= 2:
            header_line = line
            header_idx = i
            break

    if header_line is None:
        return records

    # Detect delimiter
    if ',' in header_line:
        delimiter = ','
    elif '\t' in header_line:
        delimiter = '\t'
    else:
        delimiter = None

    if delimiter:
        headers = [h.strip() for h in header_line.split(delimiter)]
        for line in lines[header_idx + 1:]:
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(delimiter)]
            if len(parts) >= len(headers):
                record = {h: parts[i] for i, h in enumerate(headers)}
                records.append(record)
    else:
        col_starts = []
        headers = []
        for m in re.finditer(r'\S+', header_line):
            col_starts.append(m.start())
            headers.append(m.group())

        for line in lines[header_idx + 1:]:
            if not line.strip():
                continue
            record = {}
            for i, (start, header) in enumerate(zip(col_starts, headers)):
                end = col_starts[i + 1] if i + 1 < len(col_starts) else len(line)
                value = line[start:end].strip()
                record[header] = value
            records.append(record)

    return records


# ─── Field matching ───────────────────────────────────────────────────────────

def _normalize_label(text: str) -> str:
    """Normalize a label for comparison: lowercase, strip spaces/underscores/hyphens."""
    return re.sub(r'[\s_\-]', '', text.lower().strip())


def match_field_label(label: str) -> Optional[str]:
    """Match a field label to a canonical financial concept."""
    label_norm = _normalize_label(label)

    # Exact match (normalized)
    for concept, synonyms in FIELD_SYNONYMS.items():
        for synonym in synonyms:
            if label_norm == _normalize_label(synonym):
                return concept

    # Partial match (normalized)
    for concept, synonyms in FIELD_SYNONYMS.items():
        for synonym in synonyms:
            syn_norm = _normalize_label(synonym)
            if syn_norm in label_norm or label_norm in syn_norm:
                return concept
    return None


def extract_financial_data(records: List[Dict[str, Any]]) -> Tuple[Dict[int, Dict[str, float]], Dict[int, str]]:
    """
    Extract financial data from parsed records.
    Returns:
        (data, year_labels) where:
        - data: {int_year: {concept: value, ...}, ...}  for internal computation
        - year_labels: {int_year: original_label_string, ...}  for output preservation
    
    The original year label (e.g., 'FY2022', '2022', 'Year Ended Jan 2025') is
    preserved in year_labels so it can be used in the output CSV. The integer
    key is used internally for sorting, joining, and metric computation.
    """
    result = {}
    year_labels = {}

    for record in records:
        # Find the year and its original label
        year = None
        original_label = None

        # First check if any key name suggests year (preferred approach)
        for key in record:
            if key.lower() in ('year', 'fiscal year', 'fiscal_year', 'period', 'fy'):
                original_label = str(record[key]).strip()
                y = normalize_year(original_label)
                if y is not None:
                    year = y
                    break

        # Fallback: check if any value looks like a year
        if year is None:
            for key, val in record.items():
                val_str = str(val).strip()
                y = normalize_year(val_str)
                if y is not None:
                    year = y
                    original_label = val_str
                    break

        if year is None:
            continue

        if year not in result:
            result[year] = {}
            year_labels[year] = original_label  # preserve first occurrence

        # Extract financial values
        for key, val in record.items():
            # Skip the year column
            if key.lower() in ('year', 'fiscal year', 'fiscal_year', 'period', 'fy'):
                continue

            concept = match_field_label(key)
            if concept:
                num = parse_number(val)
                if num is not None:
                    result[year][concept] = num

    return result, year_labels


def parse_financial_file(filepath: str) -> Tuple[Dict[int, Dict[str, float]], Dict[int, str]]:
    """
    Parse a financial data file and extract structured data.
    Returns:
        (data, year_labels) where:
        - data: {int_year: {concept: value, ...}, ...}  for internal computation
        - year_labels: {int_year: original_label_string, ...}  for output preservation
    
    The original year label from the source is preserved in year_labels.
    Use the integer keys for computation; use year_labels for output.
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    fmt = detect_format(content)

    if fmt == 'csv':
        records = parse_csv_data(content)
    elif fmt == 'json':
        records = parse_json_data(content)
    elif fmt == 'html':
        records = parse_html_tables(content)
    else:
        records = parse_mixed_content(content)

    return extract_financial_data(records)


if __name__ == '__main__':
    import sys
    filepath = sys.argv[1] if len(sys.argv) > 1 else '/app/financials/financial_summary.dat'
    data, year_labels = parse_financial_file(filepath)
    for year in sorted(data.keys()):
        label = year_labels.get(year, str(year))
        print(f"Year {label} (int={year}):")
        for concept, value in sorted(data[year].items()):
            print(f"  {concept}: {value:,.0f}")
