#!/usr/bin/env python3
"""
General-purpose financial analysis script.

Handles the full family of financial-analysis tasks as defined by spec.yaml:
  - source_representation: CSV, JSON, fixed-width, HTML tables, .dat files with embedded CSV
  - statement_topology: single file or multi-file joins by fiscal year
  - financial_metric: gross_margin, operating_margin, net_margin, return_on_equity, year_over_year_growth
  - schema_and_locale: varying field labels, number formats, languages
  - output_contract: varying column names, paths, serialization

Usage:
  python3 financial_analysis.py --task-yaml /path/to/task.yaml
  python3 financial_analysis.py --instruction "..." --data-dir /app/financials/ --output /app/results.csv

The script:
  1. Parses the task instruction to extract: target company, data directory, requested metric,
     conditional logic (thresholds, fallback metrics), output path, and column names.
  2. Scans the data directory, reads each file, and selects the file(s) matching the target company.
  3. Parses the data flexibly (CSV, JSON, fixed-width, HTML).
  4. Computes the requested metric(s).
  5. Applies conditional logic from the instruction.
  6. Writes output matching the required contract.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


# =============================================================================
# METRIC DEFINITIONS
# =============================================================================

# Each metric maps to (numerator_field, denominator_field, scale, description)
# scale: 'pct' means multiply by 100, 'ratio' means keep as-is
METRIC_FORMULAS = {
    'gross_margin': {
        'numerator': 'gross_profit',
        'denominator': 'revenue',
        'scale': 'pct',
        'description': 'Gross Profit / Revenue',
    },
    'operating_margin': {
        'numerator': 'operating_income',
        'denominator': 'revenue',
        'scale': 'pct',
        'description': 'Operating Income / Revenue',
    },
    'net_margin': {
        'numerator': 'net_income',
        'denominator': 'revenue',
        'scale': 'pct',
        'description': 'Net Income / Revenue',
    },
    'return_on_equity': {
        'numerator': 'net_income',
        'denominator': 'shareholders_equity',
        'scale': 'pct',
        'description': 'Net Income / Shareholders Equity',
    },
    'year_over_year_growth': {
        'numerator': 'revenue',  # special: needs prior year
        'denominator': None,
        'scale': 'pct',
        'description': '(Current Revenue - Prior Revenue) / |Prior Revenue|',
    },
}


# =============================================================================
# FIELD NAME NORMALIZATION
# =============================================================================

# Maps various label variants to canonical field names
FIELD_ALIASES = {
    'revenue': [
        'revenue', 'total revenue', 'totalrevenue', 'sales', 'total sales',
        'net sales', 'netsales', 'net_revenue', 'netrevenue',
        'umsatz', 'erlose', 'chiffre daffaires', 'fatturato',
        'ingresos', 'receita', '売上', '营业收入', '收入',
    ],
    'gross_profit': [
        'grossprofit', 'gross profit', 'gross_profit', 'gp',
        'bruttoergebnis', 'marge brute', 'utile lordo',
        'beneficio bruto', 'lucro bruto', '粗利益', '毛利',
    ],
    'operating_income': [
        'operatingincome', 'operating income', 'operating_income', 'oi', 'ebit',
        'betriebsergebnis', 'résultat opérationnel', 'reddito operativo',
        'beneficio operativo', 'lucro operacional', '営業利益', '营业利润',
    ],
    'net_income': [
        'netincome', 'net income', 'net_income', 'ni', 'net profit',
        'netprofit', 'net_profit', 'earnings', 'bottom line',
        'jahresüberschuss', 'résultat net', 'utile netto',
        'beneficio neto', 'lucro líquido', '純利益', '净利润',
    ],
    'shareholders_equity': [
        'shareholders equity', 'shareholders_equity', 'equity',
        'stockholders equity', 'stockholders_equity', 'total equity',
        'total_equity', 'owners equity', 'owners_equity',
        'eigenkapital', 'capitaux propres', 'patrimonio netto',
        'patrimonio', 'patrimônio', '株主資本', '股东权益',
    ],
    'fiscal_year': [
        'year', 'fiscal year', 'fiscal_year', 'fy', 'period',
        'jahr', 'exercice', 'anno', 'ejercicio', 'ano', '年度', '年份', '会计年度',
    ],
}


def normalize_field_name(raw_name: str) -> Optional[str]:
    """Map a raw field label to a canonical field name, or None if unrecognized."""
    cleaned = raw_name.strip().lower().replace('-', ' ').replace('_', ' ')
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if cleaned == alias.lower():
                return canonical
    return None


# =============================================================================
# INSTRUCTION PARSER
# =============================================================================

def parse_instruction(instruction: str) -> Dict[str, Any]:
    """
    Extract structured parameters from a natural-language task instruction.
    
    Returns dict with keys:
      - target_company: str
      - data_dir: str
      - primary_metric: str (one of METRIC_FORMULAS keys)
      - output_path: str
      - output_columns: list of str
      - conditional: dict or None (with keys: check_metric, threshold, threshold_op, fallback_metric)
    """
    result = {}
    text = instruction.lower()
    
    # --- Target company ---
    # Look for patterns like "NVIDIA Corporation", "for Apple Inc.", etc.
    company_patterns = [
        r'for\s+([A-Z][A-Za-z\s\.]+(?:Corporation|Inc|Ltd|LLC|Company|Co|Group|AG|GmbH|SA|PLC))',
        r'company[:\s]+([A-Z][A-Za-z\s\.]+(?:Corporation|Inc|Ltd|LLC|Company|Co|Group|AG|GmbH|SA|PLC))',
    ]
    for pat in company_patterns:
        m = re.search(pat, instruction, re.IGNORECASE)
        if m:
            result['target_company'] = m.group(1).strip()
            break
    
    if 'target_company' not in result:
        # Fallback: look for any capitalized multi-word name near "company" or "corporation"
        m = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Corporation|Inc|Ltd)', instruction)
        if m:
            result['target_company'] = m.group(0).strip()
    
    # --- Data directory ---
    m = re.search(r'(?:in|from|directory|path)[:\s]+(/[^\s,;]+)', instruction, re.IGNORECASE)
    if m:
        result['data_dir'] = m.group(1).rstrip('/')
    else:
        result['data_dir'] = '/app/financials'
    
    # --- Primary metric ---
    for metric_name in METRIC_FORMULAS:
        # Check various ways the metric might be mentioned
        variants = [
            metric_name.replace('_', ' '),
            metric_name.replace('_', ''),
            metric_name,
        ]
        # Also check natural language descriptions
        if metric_name == 'gross_margin' and ('gross margin' in text or 'gross profit / revenue' in text or 'gross profit/revenue' in text):
            result['primary_metric'] = metric_name
            break
        elif metric_name == 'operating_margin' and ('operating margin' in text or 'operating income / revenue' in text):
            result['primary_metric'] = metric_name
            break
        elif metric_name == 'net_margin' and ('net margin' in text or 'net income / revenue' in text):
            result['primary_metric'] = metric_name
            break
        elif metric_name == 'return_on_equity' and ('return on equity' in text or 'roe' in text):
            result['primary_metric'] = metric_name
            break
        elif metric_name == 'year_over_year_growth' and ('year over year' in text or 'yoy' in text or 'year-over-year' in text):
            result['primary_metric'] = metric_name
            break
    
    if 'primary_metric' not in result:
        # Default to gross_margin
        result['primary_metric'] = 'gross_margin'
    
    # --- Output path ---
    m = re.search(r'(?:write|save|output|results?)\s+(?:to|at|in)?\s*([^\s]+\.(?:csv|json|tsv|txt))', text)
    if m:
        result['output_path'] = m.group(1)
    else:
        result['output_path'] = '/app/results.csv'
    
    # --- Output columns ---
    # Look for "columns: X, Y" or "with columns X, Y"
    m = re.search(r'columns?[:\s]+([a-z_]+(?:\s*,\s*[a-z_]+)+)', text)
    if m:
        result['output_columns'] = [c.strip() for c in m.group(1).split(',')]
    else:
        # Infer from metric
        metric = result['primary_metric']
        if metric == 'gross_margin':
            result['output_columns'] = ['fiscal_year', 'gross_margin_pct']
        elif metric == 'operating_margin':
            result['output_columns'] = ['fiscal_year', 'operating_margin_pct']
        elif metric == 'net_margin':
            result['output_columns'] = ['fiscal_year', 'net_margin_pct']
        elif metric == 'return_on_equity':
            result['output_columns'] = ['fiscal_year', 'roe_pct']
        elif metric == 'year_over_year_growth':
            result['output_columns'] = ['fiscal_year', 'yoy_growth_pct']
        else:
            result['output_columns'] = ['fiscal_year', 'value_pct']
    
    # --- Conditional logic ---
    # Look for patterns like "if most recent year's X exceeds Y%, calculate Z instead"
    conditional = None
    
    # Check for threshold-based conditional
    threshold_match = re.search(
        r'if\s+(?:the\s+)?(?:most\s+recent|latest|last)\s+year.s?\s+(\w[\w\s]*?)\s+(?:exceeds?|>\s*|is\s+(?:greater|more)\s+than)\s+(\d+\.?\d*)\s*%',
        text
    )
    if threshold_match:
        check_metric_text = threshold_match.group(1).strip()
        threshold_val = float(threshold_match.group(2))
        
        # Map check metric text to canonical name
        check_metric = None
        for mn in METRIC_FORMULAS:
            if mn.replace('_', ' ') in check_metric_text or mn.replace('_', '') in check_metric_text:
                check_metric = mn
                break
        if not check_metric:
            check_metric = result['primary_metric']
        
        # Look for fallback metric - search for negation/else signal first
        text_after_threshold = text[threshold_match.end():]
        
        # Find the negation/fallback signal (if not, otherwise, else, does not exceed, etc.)
        fallback_signal = re.search(
            r'(?:if\s+(?:it\s+)?(?:does\s+)?not|otherwise|else|if\s+not|does\s+not\s+exceed)',
            text_after_threshold
        )
        
        fallback_metric = None
        if fallback_signal:
            # Search for calculate/compute AFTER the fallback signal
            fallback_text = text_after_threshold[fallback_signal.end():]
            fallback_match = re.search(
                r'(?:calculate|compute|output|use)\s+([a-z\s]+?)(?:\s+\(|\s+(?:for|instead|in its place))',
                fallback_text
            )
            if fallback_match:
                fb_text = fallback_match.group(1).strip()
                for mn in METRIC_FORMULAS:
                    if mn.replace('_', ' ') in fb_text or mn.replace('_', '') in fb_text:
                        fallback_metric = mn
                        break
        
        conditional = {
            'check_metric': check_metric,
            'threshold': threshold_val,
            'threshold_op': '>',
            'fallback_metric': fallback_metric,
        }
    
    result['conditional'] = conditional
    
    # --- Rounding ---
    m = re.search(r'round\s+(?:to|percentages?\s+to)\s+(\d+)\s+decimal', text)
    if m:
        result['round_decimals'] = int(m.group(1))
    else:
        result['round_decimals'] = 2
    
    # --- Scale ---
    if 'percentage' in text or 'percent' in text or '%' in instruction:
        result['scale'] = 'pct'
    else:
        result['scale'] = 'pct'  # default to percentage
    
    return result


# =============================================================================
# FILE DISCOVERY
# =============================================================================

def discover_data_files(data_dir: str, target_company: Optional[str] = None) -> List[str]:
    """
    Scan data_dir for files containing financial data for the target company.
    Returns list of matching file paths.
    """
    candidates = []
    for fname in sorted(os.listdir(data_dir)):
        fpath = os.path.join(data_dir, fname)
        if not os.path.isfile(fpath):
            continue
        
        try:
            with open(fpath, 'r', errors='replace') as f:
                content = f.read()
        except:
            continue
        
        # Check if this file contains financial data indicators
        has_financial_data = False
        financial_keywords = ['revenue', 'income', 'profit', 'equity', 'assets',
                              'liabilities', 'earnings', 'sales', 'margin']
        content_lower = content.lower()
        for kw in financial_keywords:
            if kw in content_lower:
                has_financial_data = True
                break
        
        if not has_financial_data:
            continue
        
        # Check company match if specified
        if target_company:
            # Normalize company name for matching
            company_base = target_company.strip()
            # Try exact match first
            if company_base in content:
                candidates.append(fpath)
                continue
            # Try case-insensitive
            if company_base.lower() in content_lower:
                candidates.append(fpath)
                continue
            # Try just the main name (first word)
            main_name = company_base.split()[0]
            if main_name.lower() in content_lower:
                # But verify it's not a different company with similar name
                candidates.append(fpath)
                continue
        else:
            candidates.append(fpath)
    
    return candidates


# =============================================================================
# DATA PARSING
# =============================================================================

def parse_csv_like(content: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Parse CSV-like content, returning (headers, rows)."""
    lines = content.strip().split('\n')
    
    # Find header line (contains commas and recognizable field names)
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if ',' in stripped:
            parts = [p.strip() for p in stripped.split(',')]
            # Check if at least one part maps to a known financial field
            for p in parts:
                if normalize_field_name(p) is not None:
                    header_idx = i
                    break
        if header_idx is not None:
            break
    
    if header_idx is None:
        return [], []
    
    raw_headers = [p.strip() for p in lines[header_idx].strip().split(',')]
    headers = []
    col_map = {}  # index -> canonical name
    
    for j, h in enumerate(raw_headers):
        canonical = normalize_field_name(h)
        headers.append(h)
        if canonical:
            col_map[j] = canonical
    
    # Parse data rows
    rows = []
    for i in range(header_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line or line.startswith('=') or line.startswith('#') or line.startswith('---'):
            continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < len(headers) // 2:  # too few fields, skip
            continue
        
        row = {}
        for j, val in enumerate(parts):
            if j in col_map:
                row[col_map[j]] = val.strip()
        
        # Must have at least a year and one financial value
        if row.get('fiscal_year') or re.match(r'(FY)?\d{4}', parts[0] if parts else ''):
            if 'fiscal_year' not in row:
                row['fiscal_year'] = parts[0].strip()
            rows.append(row)
    
    return headers, rows


def parse_json_data(content: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Parse JSON financial data."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return [], []
    
    # Handle various JSON structures
    records = []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        # Look for a list-valued key
        for key in ['data', 'records', 'financials', 'statements', 'results', 'years']:
            if key in data and isinstance(data[key], list):
                records = data[key]
                break
        if not records:
            # Maybe the dict itself is one record
            records = [data]
    
    if not records:
        return [], []
    
    # Normalize field names
    rows = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        row = {}
        for k, v in rec.items():
            canonical = normalize_field_name(k)
            if canonical:
                row[canonical] = str(v)
            else:
                row[k.lower()] = str(v)
        rows.append(row)
    
    return list(rows[0].keys()) if rows else [], rows


def parse_fixed_width(content: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Parse fixed-width financial data."""
    lines = content.strip().split('\n')
    
    # Find header line
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith('=') or stripped.startswith('-'):
            continue
        # Check if line contains recognizable field names
        words = stripped.split()
        found_fields = sum(1 for w in words if normalize_field_name(w) is not None)
        if found_fields >= 2:
            header_idx = i
            break
    
    if header_idx is None:
        return [], []
    
    header_line = lines[header_idx]
    # Detect column positions by finding where each field name starts
    fields = []
    for m in re.finditer(r'\S+', header_line):
        canonical = normalize_field_name(m.group())
        if canonical:
            fields.append((m.start(), m.end(), canonical))
    
    if not fields:
        return [], []
    
    # Parse data rows using column positions
    rows = []
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.strip().startswith('=') or line.strip().startswith('-'):
            continue
        
        row = {}
        for col_idx, (start, end, canonical) in enumerate(fields):
            if col_idx < len(fields) - 1:
                val = line[start:fields[col_idx + 1][0]].strip()
            else:
                val = line[start:].strip()
            row[canonical] = val
        
        if any(row.values()):
            rows.append(row)
    
    return [f[2] for f in fields], rows


def parse_html_table(content: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Parse HTML table with financial data."""
    # Simple HTML table parser (no external dependencies)
    rows = []
    headers = []
    
    # Find table rows
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
    td_pattern = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.DOTALL | re.IGNORECASE)
    tag_strip = re.compile(r'<[^>]+>')
    
    for tr_match in tr_pattern.finditer(content):
        cells = []
        for td_match in td_pattern.finditer(tr_match.group(1)):
            cell_text = tag_strip.sub('', td_match.group(1)).strip()
            cells.append(cell_text)
        
        if not cells:
            continue
        
        if not headers:
            # First row is header
            headers = cells
        else:
            row = {}
            for j, val in enumerate(cells):
                if j < len(headers):
                    canonical = normalize_field_name(headers[j])
                    if canonical:
                        row[canonical] = val
                    else:
                        row[headers[j].lower()] = val
            rows.append(row)
    
    return headers, rows


def parse_number(val: str) -> Optional[float]:
    """Parse a numeric value, handling various formats."""
    if val is None:
        return None
    val = str(val).strip()
    if not val or val == '-' or val == 'N/A' or val == 'n/a':
        return None
    
    # Remove currency symbols and whitespace
    val = re.sub(r'[$€£¥\s]', '', val)
    
    # Handle parentheses as negative: (1,234) -> -1234
    if val.startswith('(') and val.endswith(')'):
        val = '-' + val[1:-1]
    
    # Detect locale: if comma is used as decimal separator
    # Heuristic: if there's a comma followed by exactly 1-2 digits at the end, it might be decimal
    # But if commas appear before groups of 3 digits, they're thousands separators
    
    # Remove thousands separators (commas in 1,234,567 pattern)
    val = val.replace(',', '')
    
    try:
        return float(val)
    except ValueError:
        # Try removing 'M', 'B', 'K' suffixes (millions, billions, thousands)
        m = re.match(r'^(-?\d+\.?\d*)\s*([MBKmbk])$', val)
        if m:
            num = float(m.group(1))
            suffix = m.group(2).upper()
            multiplier = {'M': 1e6, 'B': 1e9, 'K': 1e3}
            return num * multiplier.get(suffix, 1)
        return None


def parse_file(fpath: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Auto-detect file format and parse financial data.
    Returns (headers, rows) where rows have canonical field names and numeric values.
    """
    with open(fpath, 'r', errors='replace') as f:
        content = f.read()
    
    # Detect format
    if content.strip().startswith('{') or content.strip().startswith('['):
        raw_headers, raw_rows = parse_json_data(content)
    elif '<table' in content.lower() or '<tr' in content.lower():
        raw_headers, raw_rows = parse_html_table(content)
    else:
        # Try CSV-like first (most common, including .dat files with embedded CSV)
        raw_headers, raw_rows = parse_csv_like(content)
        
        # If CSV parsing found nothing, try fixed-width
        if not raw_rows:
            raw_headers, raw_rows = parse_fixed_width(content)
    
    # Convert values to numeric
    rows = []
    for raw_row in raw_rows:
        row = {}
        for k, v in raw_row.items():
            num = parse_number(v)
            if num is not None:
                row[k] = num
            else:
                row[k] = v  # keep as string (e.g., year labels)
        rows.append(row)
    
    return raw_headers, rows


# =============================================================================
# METRIC COMPUTATION
# =============================================================================

def compute_metric(records: List[Dict], metric_name: str, scale: str = 'pct', 
                   round_decimals: int = 2) -> List[Dict[str, Any]]:
    """
    Compute the specified metric for each record.
    Returns list of dicts with 'fiscal_year' and metric value.
    """
    formula = METRIC_FORMULAS.get(metric_name)
    if not formula:
        raise ValueError(f"Unknown metric: {metric_name}")
    
    results = []
    
    if metric_name == 'year_over_year_growth':
        # Special case: needs sorted records and prior year
        sorted_records = sorted(records, key=lambda r: str(r.get('fiscal_year', '')))
        for i, rec in enumerate(sorted_records):
            year = rec.get('fiscal_year', f'Year_{i}')
            if i == 0:
                # No prior year for first record
                continue
            current = rec.get('revenue')
            prior = sorted_records[i - 1].get('revenue')
            if current is not None and prior is not None and prior != 0:
                growth = ((current - prior) / abs(prior)) * 100
                results.append({
                    'fiscal_year': year,
                    'value': round(growth, round_decimals),
                })
    else:
        num_field = formula['numerator']
        den_field = formula['denominator']
        
        for rec in records:
            year = rec.get('fiscal_year', 'Unknown')
            numerator = rec.get(num_field)
            denominator = rec.get(den_field)
            
            if numerator is not None and denominator is not None and denominator != 0:
                value = numerator / denominator
                if scale == 'pct':
                    value *= 100
                results.append({
                    'fiscal_year': year,
                    'value': round(value, round_decimals),
                })
    
    return results


# =============================================================================
# CONDITIONAL LOGIC
# =============================================================================

def apply_conditional(records: List[Dict], conditional: Dict, scale: str = 'pct',
                      round_decimals: int = 2) -> Tuple[str, List[Dict]]:
    """
    Apply conditional logic from the instruction.
    Returns (metric_used, results).
    """
    check_metric = conditional['check_metric']
    threshold = conditional['threshold']
    threshold_op = conditional.get('threshold_op', '>')
    fallback_metric = conditional.get('fallback_metric')
    
    # Sort records by year to find most recent
    sorted_records = sorted(records, key=lambda r: str(r.get('fiscal_year', '')))
    latest = sorted_records[-1] if sorted_records else None
    
    if latest is None:
        return check_metric, []
    
    # Compute check metric for latest year
    formula = METRIC_FORMULAS.get(check_metric)
    if not formula:
        return check_metric, []
    
    num_field = formula['numerator']
    den_field = formula['denominator']
    numerator = latest.get(num_field)
    denominator = latest.get(den_field)
    
    if numerator is None or denominator is None or denominator == 0:
        # Can't compute, use fallback
        if fallback_metric:
            results = compute_metric(records, fallback_metric, scale, round_decimals)
            return fallback_metric, results
        return check_metric, []
    
    check_value = (numerator / denominator) * 100 if scale == 'pct' else (numerator / denominator)
    
    # Evaluate condition
    condition_met = False
    if threshold_op == '>':
        condition_met = check_value > threshold
    elif threshold_op == '>=':
        condition_met = check_value >= threshold
    elif threshold_op == '<':
        condition_met = check_value < threshold
    elif threshold_op == '<=':
        condition_met = check_value <= threshold
    
    if condition_met:
        # Use primary metric
        results = compute_metric(records, check_metric, scale, round_decimals)
        return check_metric, results
    else:
        # Use fallback metric
        if fallback_metric:
            results = compute_metric(records, fallback_metric, scale, round_decimals)
            return fallback_metric, results
        else:
            results = compute_metric(records, check_metric, scale, round_decimals)
            return check_metric, results


# =============================================================================
# OUTPUT
# =============================================================================

def write_output(results: List[Dict], output_path: str, output_columns: List[str],
                 metric_name: str):
    """Write results to output file."""
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    # Map results to output columns
    output_rows = []
    for r in results:
        row = {}
        for col in output_columns:
            if col == 'fiscal_year':
                row[col] = r.get('fiscal_year', '')
            elif 'value' in r:
                row[col] = r['value']
            else:
                row[col] = ''
        output_rows.append(row)
    
    # Determine file format from extension
    ext = os.path.splitext(output_path)[1].lower()
    
    if ext == '.json':
        with open(output_path, 'w') as f:
            json.dump(output_rows, f, indent=2)
    elif ext == '.tsv':
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=output_columns, delimiter='\t')
            writer.writeheader()
            writer.writerows(output_rows)
    else:
        # Default to CSV
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=output_columns)
            writer.writeheader()
            writer.writerows(output_rows)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Financial Analysis Tool')
    parser.add_argument('--task-yaml', help='Path to task.yaml file')
    parser.add_argument('--instruction', help='Task instruction text')
    parser.add_argument('--data-dir', help='Directory containing financial data files')
    parser.add_argument('--output', help='Output file path')
    args = parser.parse_args()
    
    # Get instruction
    instruction = None
    if args.task_yaml:
        import yaml
        with open(args.task_yaml, 'r') as f:
            task = yaml.safe_load(f)
        instruction = task.get('instruction', '')
    elif args.instruction:
        instruction = args.instruction
    else:
        print("Error: Must provide --task-yaml or --instruction", file=sys.stderr)
        sys.exit(1)
    
    # Parse instruction
    params = parse_instruction(instruction)
    print(f"Parsed parameters: {json.dumps(params, indent=2, default=str)}")
    
    # Override with CLI args if provided
    data_dir = args.data_dir or params.get('data_dir', '/app/financials')
    output_path = args.output or params.get('output_path', '/app/results.csv')
    target_company = params.get('target_company')
    primary_metric = params.get('primary_metric', 'gross_margin')
    output_columns = params.get('output_columns', ['fiscal_year', 'gross_margin_pct'])
    conditional = params.get('conditional')
    scale = params.get('scale', 'pct')
    round_decimals = params.get('round_decimals', 2)
    
    # Discover data files
    print(f"\nSearching for data files in {data_dir} for company: {target_company}")
    data_files = discover_data_files(data_dir, target_company)
    print(f"Found {len(data_files)} matching file(s): {data_files}")
    
    if not data_files:
        print("Error: No matching data files found", file=sys.stderr)
        sys.exit(1)
    
    # Parse data from all matching files
    all_records = []
    for fpath in data_files:
        print(f"\nParsing {fpath}...")
        headers, rows = parse_file(fpath)
        print(f"  Headers: {headers}")
        print(f"  Records: {len(rows)}")
        if rows:
            print(f"  Sample record: {rows[0]}")
        all_records.extend(rows)
    
    if not all_records:
        print("Error: No data records found", file=sys.stderr)
        sys.exit(1)
    
    print(f"\nTotal records: {len(all_records)}")
    
    # Compute metrics
    if conditional:
        print(f"\nApplying conditional logic: {conditional}")
        metric_used, results = apply_conditional(all_records, conditional, scale, round_decimals)
        print(f"Condition evaluated. Using metric: {metric_used}")
        
        # Update output columns if metric changed
        if metric_used != primary_metric:
            # Adjust output column name to match the actual metric
            for i, col in enumerate(output_columns):
                if 'pct' in col or 'value' in col:
                    output_columns[i] = f"{metric_used}_pct"
    else:
        print(f"\nComputing metric: {primary_metric}")
        results = compute_metric(all_records, primary_metric, scale, round_decimals)
    
    print(f"\nResults ({len(results)} rows):")
    for r in results:
        print(f"  {r}")
    
    # Write output
    print(f"\nWriting to {output_path} with columns: {output_columns}")
    write_output(results, output_path, output_columns, primary_metric)
    print("Done!")


if __name__ == '__main__':
    main()
