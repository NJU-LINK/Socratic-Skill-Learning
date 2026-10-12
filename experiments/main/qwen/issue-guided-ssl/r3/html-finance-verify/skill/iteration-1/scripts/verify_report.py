#!/usr/bin/env python3
"""
Generic HTML financial report verifier.

Parses an HTML financial report, extracts all line-numbered metrics,
separates dollar values from percentages, and identifies the single
incorrect percentage via systematic cross-checking.

Usage: python3 verify_report.py [html_file_path]
Default: /app/q2_earnings_report.html
Output: /app/value.txt with format "line_number,value"
"""

import re
import sys
import os
from html.parser import HTMLParser


class HTMLTableParser(HTMLParser):
    """Parse HTML tables and extract row/cell text content."""
    
    def __init__(self):
        super().__init__()
        self.rows = []  # list of list of cell texts
        self.current_row = []
        self.current_cell = ""
        self.in_td = False
        self.in_tr = False
        
    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.in_tr = True
            self.current_row = []
        elif tag == 'td':
            self.in_td = True
            self.current_cell = ""
            
    def handle_endtag(self, tag):
        if tag == 'td' and self.in_td:
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
        elif tag == 'tr' and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
                
    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data


def parse_html_tables(html_content):
    """Extract all table rows from HTML content."""
    parser = HTMLTableParser()
    parser.feed(html_content)
    return parser.rows


def extract_metric_from_row(cells):
    """
    Extract (line_number, label, value, value_type) from a table row.
    
    Returns None if the row doesn't contain a valid metric.
    """
    if len(cells) < 2:
        return None
    
    line_no = None
    label = None
    value = None
    value_type = None
    
    # First pass: identify line number, dollar value, percentage value
    for cell in cells:
        cell_stripped = cell.strip()
        
        # Check for line number: standalone integer (typically 2-4 digits)
        if re.fullmatch(r'\d{2,4}', cell_stripped) and line_no is None:
            line_no = int(cell_stripped)
            continue
        
        # Check for dollar value: $842.0, $1,234.5M, $(50.2), etc.
        dollar_match = re.search(r'\$[\(\)]?[\d,]+\.?\d*[\)]?[A-Z]?', cell_stripped)
        if dollar_match and value is None:
            # Extract the numeric part
            dollar_str = dollar_match.group(0)
            # Handle parenthesized negatives
            is_negative = '(' in dollar_str and ')' in dollar_str
            # Remove $, commas, parentheses, magnitude suffixes
            num_str = re.sub(r'[\$\(\),]', '', dollar_str)
            num_str = re.sub(r'[MBKmk]$', '', num_str)
            try:
                value = float(num_str)
                if is_negative:
                    value = -value
                # Apply magnitude suffix
                if dollar_str.endswith('M') or dollar_str.endswith('m'):
                    value *= 1_000_000
                elif dollar_str.endswith('B') or dollar_str.endswith('b'):
                    value *= 1_000_000_000
                elif dollar_str.endswith('K') or dollar_str.endswith('k'):
                    value *= 1_000
                value_type = 'dollar'
            except ValueError:
                pass
            continue
        
        # Check for percentage value: 60.8%, 28.5 %, etc.
        pct_match = re.search(r'([\d]+\.?\d*)\s*%', cell_stripped)
        if pct_match and value is None:
            try:
                value = float(pct_match.group(1))
                value_type = 'pct'
            except ValueError:
                pass
            continue
    
    # Second pass: extract label (non-numeric, non-value cell)
    if line_no is not None and value is not None:
        for cell in cells:
            cell_stripped = cell.strip()
            # Skip if it's the line number
            if re.fullmatch(r'\d{2,4}', cell_stripped):
                continue
            # Skip if it contains the value
            if value_type == 'dollar' and '$' in cell_stripped:
                continue
            if value_type == 'pct' and '%' in cell_stripped:
                continue
            # This should be the label
            if cell_stripped and not label:
                label = cell_stripped
    
    if line_no is not None and value is not None and label is not None:
        return (line_no, label, value, value_type)
    
    return None


def parse_report(html_path):
    """
    Parse an HTML financial report and extract all metrics.
    
    Returns:
        dollar_items: list of (line_no, label, value)
        pct_items: list of (line_no, label, value)
    """
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    rows = parse_html_tables(html_content)
    
    dollar_items = []
    pct_items = []
    
    for row in rows:
        result = extract_metric_from_row(row)
        if result is None:
            continue
        
        line_no, label, value, value_type = result
        
        if value_type == 'dollar':
            dollar_items.append((line_no, label, value))
        elif value_type == 'pct':
            pct_items.append((line_no, label, value))
    
    return dollar_items, pct_items


def verify_dollar_consistency(dollars, tol=0.1):
    """
    Verify that dollar values are internally consistent.
    
    Checks additive relationships: for each dollar value, check if it equals
    the sum of some subset of other dollar values.
    
    Returns True if all relationships are consistent.
    """
    # For each value, check if it can be expressed as sum/difference of others
    # This is a simplified check - in practice, we'd need to understand the
    # report structure to know which values should add up
    # For now, we just verify that the dollars are mutually consistent
    # by checking common financial relationships
    
    # Build a map of values by label for easier lookup
    value_by_label = {label: val for _, label, val in dollars}
    
    # Check common relationships (these should all pass per spec)
    checks = []
    
    # Gross profit = Revenue - Cost of revenue
    if 'Revenue' in value_by_label and 'Cost of revenue' in value_by_label and 'Gross profit' in value_by_label:
        expected = value_by_label['Revenue'] - value_by_label['Cost of revenue']
        actual = value_by_label['Gross profit']
        checks.append(('Gross profit', expected, actual))
    
    # Total operating expenses = R&D + S&M + G&A
    if 'Research and development' in value_by_label and 'Sales and marketing' in value_by_label and 'General and administrative' in value_by_label and 'Total operating expenses' in value_by_label:
        expected = value_by_label['Research and development'] + value_by_label['Sales and marketing'] + value_by_label['General and administrative']
        actual = value_by_label['Total operating expenses']
        checks.append(('Total operating expenses', expected, actual))
    
    # Operating income = Gross profit - Total operating expenses
    if 'Gross profit' in value_by_label and 'Total operating expenses' in value_by_label and 'Operating income' in value_by_label:
        expected = value_by_label['Gross profit'] - value_by_label['Total operating expenses']
        actual = value_by_label['Operating income']
        checks.append(('Operating income', expected, actual))
    
    # Net income = Operating income + Other income
    if 'Operating income' in value_by_label and 'Other income, net' in value_by_label and 'Net income' in value_by_label:
        expected = value_by_label['Operating income'] + value_by_label['Other income, net']
        actual = value_by_label['Net income']
        checks.append(('Net income', expected, actual))
    
    # Verify all checks pass
    for name, expected, actual in checks:
        if abs(expected - actual) > tol:
            print(f"Warning: Dollar inconsistency detected for {name}: expected {expected}, got {actual}", file=sys.stderr)
            return False
    
    return True


def find_incorrect_percentage(dollars, percentages, tol=0.15):
    """
    Find the percentage that doesn't match any valid ratio of dollar values.
    
    For each percentage, try all ordered pairs of dollar values (numerator, denominator)
    and check if (numerator/denominator)*100 matches the percentage (rounded to 1 decimal).
    
    The incorrect percentage is the one that matches NO valid ratio.
    
    Returns:
        (line_no, value) of the incorrect percentage, or None if not found
    """
    results = []
    
    for p_line, p_label, p_val in percentages:
        matched = False
        matching_ratio = None
        
        # Try all ordered pairs of dollar values
        for i, (d1_line, d1_label, d1_val) in enumerate(dollars):
            for j, (d2_line, d2_label, d2_val) in enumerate(dollars):
                # Skip if same value or denominator is zero
                if i == j or abs(d2_val) < 0.001:
                    continue
                
                # Compute expected percentage
                expected = (d1_val / d2_val) * 100
                expected_rounded = round(expected, 1)
                
                # Check if it matches
                if abs(p_val - expected_rounded) < tol:
                    matched = True
                    matching_ratio = (d1_label, d2_label, expected_rounded)
                    break
            
            if matched:
                break
        
        results.append({
            'line': p_line,
            'label': p_label,
            'value': p_val,
            'matched': matched,
            'matching_ratio': matching_ratio
        })
    
    # Find the unmatched percentage
    for r in results:
        if not r['matched']:
            return (r['line'], r['value'])
    
    return None


def main():
    """Main entry point."""
    # Determine HTML file path
    html_path = sys.argv[1] if len(sys.argv) > 1 else '/app/q2_earnings_report.html'
    output_path = '/app/value.txt'
    
    if not os.path.exists(html_path):
        print(f"Error: HTML file not found: {html_path}", file=sys.stderr)
        sys.exit(1)
    
    # Parse the report
    print(f"Parsing report: {html_path}", file=sys.stderr)
    dollars, percentages = parse_report(html_path)
    
    print(f"Found {len(dollars)} dollar values and {len(percentages)} percentages", file=sys.stderr)
    
    # Debug: print parsed values
    for line, label, val in dollars:
        print(f"  Dollar: line {line}, {label} = {val}", file=sys.stderr)
    for line, label, val in percentages:
        print(f"  Percentage: line {line}, {label} = {val}%", file=sys.stderr)
    
    # Verify dollar consistency
    if not verify_dollar_consistency(dollars):
        print("Warning: Dollar values are not internally consistent", file=sys.stderr)
    
    # Find the incorrect percentage
    result = find_incorrect_percentage(dollars, percentages)
    
    if result is None:
        print("Error: Could not identify incorrect percentage", file=sys.stderr)
        sys.exit(1)
    
    line_no, bad_val = result
    print(f"\nFound incorrect metric: line {line_no}, value {bad_val}", file=sys.stderr)
    
    # Write output
    with open(output_path, 'w') as f:
        f.write(f"{line_no},{bad_val}")
    
    print(f"Answer written to {output_path}", file=sys.stderr)


if __name__ == '__main__':
    main()
