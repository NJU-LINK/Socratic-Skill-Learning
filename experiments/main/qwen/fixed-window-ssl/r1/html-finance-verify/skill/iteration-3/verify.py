#!/usr/bin/env python3
"""
HTML Financial Report Verification Script

Identifies a single incorrect metric in an HTML financial report
by checking internal consistency across all reported values.

Algorithm (two-phase consistency check):
1. Parse HTML to extract all metrics with (line_number, name, value, type)
2. For each metric, try to derive it using known financial relationship patterns
3. Classify each metric as:
   - CONFIRMED: at least one derivation matches within tolerance
   - CONTRADICTED: derivations exist but disagree with reported value
   - UNCHECKED: no derivation rules apply
4. The CONTRADICTED metric is the error
5. Output line_number,value to the specified file
"""

import re
import sys
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Optional

# Tolerance for floating point comparisons
DOLLAR_TOLERANCE = 0.05
PERCENTAGE_TOLERANCE = 0.15

# Opex patterns for direct name checking
OPEX_PATTERNS = ['research', 'development', 'sales', 'marketing', 'general', 'administrative']
OPEX_EXCLUSIONS = ['net', 'revenue', 'income', 'cost']


class TableParser(HTMLParser):
    """Parse HTML tables to extract structured data"""
    
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_cell = ""
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.is_header = False
        
    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
            self.current_table = []
        elif tag == 'tr' and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ['td', 'th'] and self.in_row:
            self.in_cell = True
            self.current_cell = ""
            self.is_header = (tag == 'th')
            
    def handle_endtag(self, tag):
        if tag == 'table' and self.in_table:
            self.in_table = False
            if self.current_table:
                self.tables.append(self.current_table)
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            if self.current_row:
                self.current_table.append(self.current_row)
        elif tag in ['td', 'th'] and self.in_cell:
            self.in_cell = False
            self.current_row.append({
                'text': self.current_cell.strip(),
                'is_header': self.is_header
            })
            
    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def parse_numeric_value(text: str) -> Tuple[Optional[float], str]:
    """Parse a numeric value from text, handling various formats."""
    text = text.strip()
    is_dollar = '$' in text
    is_percentage = '%' in text
    cleaned = re.sub(r'[$%,\s]', '', text)
    
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    
    try:
        value = float(cleaned)
        if is_dollar:
            return value, 'dollar'
        elif is_percentage:
            return value, 'percentage'
        else:
            return value, 'number'
    except ValueError:
        return None, 'unknown'


def extract_metrics_from_html(html_path: str) -> List[Dict]:
    """Extract all metrics from HTML tables."""
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    parser = TableParser()
    parser.feed(html_content)
    
    metrics = []
    
    for table in parser.tables:
        for row in table:
            if len(row) < 3 or row[0]['is_header']:
                continue
            
            line_text = row[0]['text']
            name_text = row[1]['text']
            value_text = row[2]['text']
            
            try:
                line_num = int(line_text)
            except ValueError:
                continue
            
            value, value_type = parse_numeric_value(value_text)
            if value is None:
                continue
            
            metrics.append({
                'line': line_num,
                'name': name_text.lower(),
                'value': value,
                'type': value_type,
                'raw': value_text
            })
    
    return metrics


def find_metric(metrics: List[Dict], *patterns: str) -> Optional[Dict]:
    """Find first metric matching any of the given name patterns using word boundaries."""
    for m in metrics:
        for p in patterns:
            if re.search(r'\b' + re.escape(p) + r'\b', m['name']):
                return m
    return None


def find_all_metrics(metrics: List[Dict], *patterns: str) -> List[Dict]:
    """Find all metrics matching any of the given name patterns using word boundaries, excluding totals."""
    results = []
    for m in metrics:
        for p in patterns:
            if re.search(r'\b' + re.escape(p) + r'\b', m['name']) and 'total' not in m['name']:
                results.append(m)
                break
    return results


def get_tolerance(metric: Dict) -> float:
    """Get appropriate tolerance based on metric type."""
    if metric['type'] == 'percentage':
        return PERCENTAGE_TOLERANCE
    return DOLLAR_TOLERANCE


def structure_guided_percentage_check(target: Dict, others: List[Dict]) -> List[float]:
    """
    Structure-guided fallback for percentage metrics.
    For percentages, try: target ≈ some_dollar / max_dollar * 100
    This works regardless of metric names.
    """
    if target['type'] != 'percentage':
        return []
    
    dollar_values = [m for m in others if m['type'] == 'dollar']
    if not dollar_values:
        return []
    
    # The largest dollar value is almost certainly the denominator (revenue)
    denominator = max(dollar_values, key=lambda m: abs(m['value']))
    
    derivations = []
    for dm in dollar_values:
        if dm['value'] != 0 and dm['line'] != target['line']:
            ratio = dm['value'] / denominator['value'] * 100
            derivations.append(ratio)
    
    return derivations


def try_derive_all(target: Dict, others: List[Dict]) -> List[float]:
    """
    Try all possible derivations of the target metric from others.
    Returns list of all derived values (may be empty if no rules apply).
    
    Uses two-layer approach:
    1. Name-based pattern matching (primary, specific)
    2. Structure-guided fallback (for renamed metrics)
    """
    target_name = target['name']
    derived_values = []
    
    def find(*patterns):
        return find_metric(others, *patterns)
    
    def find_all(*patterns):
        return find_all_metrics(others, *patterns)
    
    # Income statement relationships
    revenue = find('revenue', 'net sales', 'total sales', 'net revenue', 'sales revenue')
    cogs = find('cost of revenue', 'cost of goods', 'cost of sales', 'cogs')
    gross_profit = find('gross profit')
    total_opex = find('total operating', 'total opex')
    operating_income = find('operating income')
    other_income = find('other income', 'other expense')
    net_income = find('net income')
    
    opex_items_unfiltered = find_all('research', 'development', 'sales', 'marketing', 
                                     'general', 'administrative')
    # Exclude non-opex items that might match by substring (e.g., 'net sales', 'cost of sales')
    opex_items_unfiltered = [m for m in opex_items_unfiltered
                             if 'net' not in m['name'] 
                             and 'revenue' not in m['name']
                             and 'income' not in m['name']
                             and 'cost' not in m['name']]
    opex_items = [m for m in opex_items_unfiltered if m['line'] != target['line']]
    
    # Gross profit = Revenue - COGS
    if 'gross profit' in target_name and revenue and cogs:
        derived_values.append(revenue['value'] - cogs['value'])
    
    # COGS = Revenue - Gross profit
    if ('cost of revenue' in target_name or 'cost of goods' in target_name or 'cost of sales' in target_name) and revenue and gross_profit:
        derived_values.append(revenue['value'] - gross_profit['value'])
    
    # Revenue = Gross profit + COGS
    if ('revenue' in target_name or 'net sales' in target_name or 'total sales' in target_name) and 'gross' not in target_name and gross_profit and cogs:
        derived_values.append(gross_profit['value'] + cogs['value'])
    
    # Total opex = sum of items
    if ('total operating' in target_name or 'total opex' in target_name) and opex_items:
        derived_values.append(sum(m['value'] for m in opex_items))
    
    # Individual opex item = Total opex - other items
    # LEAVE-ONE-OUT CLOSURE TRAP: Check target_name directly, not via find_all(others, ...)
    target_is_opex = (
        any(re.search(r'\b' + re.escape(p) + r'\b', target_name) for p in OPEX_PATTERNS)
        and 'total' not in target_name
        and not any(excl in target_name for excl in OPEX_EXCLUSIONS)
    )
    if target_is_opex and total_opex:
        other_items = [m for m in opex_items if m['line'] != target['line']]
        if other_items:
            derived_values.append(total_opex['value'] - sum(m['value'] for m in other_items))
    
    # Operating income = Gross profit - Total opex
    if 'operating income' in target_name and gross_profit and total_opex:
        derived_values.append(gross_profit['value'] - total_opex['value'])
    
    # Gross profit = Operating income + Total opex
    if 'gross profit' in target_name and operating_income and total_opex:
        derived_values.append(operating_income['value'] + total_opex['value'])
    
    # Total opex = Gross profit - Operating income
    if ('total operating' in target_name or 'total opex' in target_name) and gross_profit and operating_income:
        derived_values.append(gross_profit['value'] - operating_income['value'])
    
    # Net income = Operating income + Other income
    if 'net income' in target_name and operating_income and other_income:
        derived_values.append(operating_income['value'] + other_income['value'])
    
    # Operating income = Net income - Other income
    if 'operating income' in target_name and net_income and other_income:
        derived_values.append(net_income['value'] - other_income['value'])
    
    # Other income = Net income - Operating income
    if ('other income' in target_name or 'other expense' in target_name) and net_income and operating_income:
        derived_values.append(net_income['value'] - operating_income['value'])
    
    # === Margin ratio derivations ===
    gross_margin = find('gross margin')
    operating_margin = find('operating margin')
    net_margin = find('net margin')
    
    # Gross margin = Gross profit / Revenue * 100
    if 'gross margin' in target_name and target['type'] == 'percentage' and gross_profit and revenue:
        derived_values.append(gross_profit['value'] / revenue['value'] * 100)
    
    # Operating margin = Operating income / Revenue * 100
    if 'operating margin' in target_name and target['type'] == 'percentage' and operating_income and revenue:
        derived_values.append(operating_income['value'] / revenue['value'] * 100)
    
    # Net margin = Net income / Revenue * 100
    if 'net margin' in target_name and target['type'] == 'percentage' and net_income and revenue:
        derived_values.append(net_income['value'] / revenue['value'] * 100)
    
    # Reverse: Gross profit = Gross margin / 100 * Revenue
    if 'gross profit' in target_name and gross_margin and revenue:
        derived_values.append(gross_margin['value'] / 100 * revenue['value'])
    
    # Reverse: Operating income = Operating margin / 100 * Revenue
    if 'operating income' in target_name and operating_margin and revenue:
        derived_values.append(operating_margin['value'] / 100 * revenue['value'])
    
    # Reverse: Net income = Net margin / 100 * Revenue
    if 'net income' in target_name and net_margin and revenue:
        derived_values.append(net_margin['value'] / 100 * revenue['value'])
    
    # Reverse: Revenue = Gross profit / (Gross margin / 100)
    if ('revenue' in target_name or 'net sales' in target_name) and 'gross' not in target_name and gross_profit and gross_margin:
        if gross_margin['value'] != 0:
            derived_values.append(gross_profit['value'] / (gross_margin['value'] / 100))
    
    # === EPS derivations ===
    eps = find('earnings per share', 'eps')
    shares = find('shares outstanding', 'diluted shares', 'basic shares')
    
    if ('earnings per share' in target_name or target_name == 'eps') and net_income and shares:
        if shares['value'] != 0:
            derived_values.append(net_income['value'] * 1_000_000 / shares['value'])
    
    if ('shares outstanding' in target_name or 'diluted shares' in target_name or 'basic shares' in target_name):
        if net_income and eps and eps['value'] != 0:
            derived_values.append(net_income['value'] * 1_000_000 / eps['value'])
    
    # Structure-guided fallback: if name-based patterns produced nothing,
    # try generic percentage derivations that don't depend on metric names
    if not derived_values:
        derived_values.extend(structure_guided_percentage_check(target, others))
    
    return derived_values


def check_metric(target: Dict, others: List[Dict]) -> str:
    """
    Try every possible way to derive target from other metrics.
    Returns: 'confirmed', 'contradicted', or 'unchecked'
    """
    derivations = try_derive_all(target, others)
    
    if not derivations:
        return 'unchecked'
    
    tolerance = get_tolerance(target)
    
    for derived in derivations:
        if abs(derived - target['value']) < tolerance:
            return 'confirmed'
    
    return 'contradicted'


def find_inconsistent_metric(metrics: List[Dict]) -> Optional[Dict]:
    """Find the single metric that is contradicted by derivations."""
    contradicted = []
    
    for i, target in enumerate(metrics):
        others = [m for j, m in enumerate(metrics) if j != i]
        status = check_metric(target, others)
        
        if status == 'contradicted':
            contradicted.append(target)
    
    if len(contradicted) == 1:
        return contradicted[0]
    elif len(contradicted) == 0:
        print("Warning: All metrics appear consistent. No error found.", file=sys.stderr)
        return None
    else:
        print(f"Warning: Found {len(contradicted)} contradicted metrics. Expected 1.", file=sys.stderr)
        return contradicted[0] if contradicted else None


def main():
    """Main entry point"""
    html_path = '/app/q2_earnings_report.html'
    output_path = '/app/value.txt'
    
    if len(sys.argv) >= 2:
        html_path = sys.argv[1]
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    
    if not Path(html_path).exists():
        print(f"Error: Input file {html_path} not found", file=sys.stderr)
        sys.exit(1)
    
    metrics = extract_metrics_from_html(html_path)
    
    if not metrics:
        print("Error: No metrics found in HTML file", file=sys.stderr)
        sys.exit(1)
    
    error_metric = find_inconsistent_metric(metrics)
    
    if error_metric is None:
        print("Error: Could not identify inconsistent metric", file=sys.stderr)
        sys.exit(1)
    
    output_line = f"{error_metric['line']},{error_metric['value']}"
    with open(output_path, 'w') as f:
        f.write(output_line)
    
    print(f"Output: {output_line}", file=sys.stderr)


if __name__ == '__main__':
    main()
