#!/usr/bin/env python3
"""
HTML Financial Report Verification Script

This script parses an HTML financial report, verifies internal consistency
of income statement values and KPI percentages, and identifies the single
incorrect metric.

Usage:
    python verify_financials.py <html_file> <output_file>

Dependencies: Python standard library only (html.parser, re, sys)
"""

import sys
import re
from html.parser import HTMLParser


def extract_numeric(text):
    """Extract numeric value from text, handling $, commas, %, and negatives."""
    # Remove currency symbols, commas, percent signs
    cleaned = text.replace('$', '').replace(',', '').replace('%', '').strip()
    
    # Handle parentheses as negative (accounting notation)
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    
    try:
        return float(cleaned)
    except ValueError:
        return None


class TableParser(HTMLParser):
    """Generic HTML table parser that extracts rows without assuming structure."""
    
    def __init__(self):
        super().__init__()
        self.in_td = False
        self.current_row = []
        self.current_cell = ""
        self.rows = []
    
    def handle_starttag(self, tag, attrs):
        if tag == 'td':
            self.in_td = True
            self.current_cell = ""
    
    def handle_endtag(self, tag):
        if tag == 'td':
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
        elif tag == 'tr' and self.current_row:
            self.rows.append(self.current_row)
            self.current_row = []
    
    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data


def parse_html_financials(html_content):
    """
    Parse HTML and extract all metrics with line numbers.
    Uses generic HTMLParser and classifies columns by content, not structure.
    """
    parser = TableParser()
    parser.feed(html_content)
    
    metrics = {}
    
    for row in parser.rows:
        if len(row) < 3:
            continue
        
        # Classify columns by content
        line_num_cell = None
        value_cell = None
        name_cell = None
        
        for cell in row:
            # Check if this is a line number (pure integer)
            if re.match(r'^\d+$', cell):
                line_num_cell = cell
            # Check if this is a value (contains $ or %)
            elif '$' in cell or '%' in cell:
                value_cell = cell
            # Otherwise, it's likely the metric name
            elif cell and not cell.replace('.', '').replace('-', '').isdigit():
                # Avoid matching pure numbers that might be in name column
                name_cell = cell
        
        # If we found all three components, extract the metric
        if line_num_cell and value_cell and name_cell:
            try:
                line_num = int(line_num_cell)
                numeric_value = extract_numeric(value_cell)
                
                if numeric_value is not None:
                    metrics[line_num] = {
                        'name': name_cell,
                        'value': numeric_value,
                        'raw': value_cell,
                        'line': line_num
                    }
            except ValueError:
                continue
    
    return metrics


def verify_income_statement(metrics):
    """
    Verify income statement relationships.
    Returns the incorrect metric if found, None otherwise.
    """
    # Build lookup by metric name (case-insensitive, flexible matching)
    by_name = {}
    for m in metrics.values():
        by_name[m['name'].lower()] = m
    
    tolerance = 0.01  # Dollar amounts should match exactly
    
    def find_metric(*keywords):
        """Find a metric, preferring exact matches over substring matches."""
        exact = None
        best = None
        for key, metric in by_name.items():
            for kw in keywords:
                if key == kw:
                    return metric  # Exact match wins immediately
                if kw in key:
                    if best is None or len(key) < len(best[1]['name'].lower()):
                        best = (key, metric)
        return best[1] if best else None
    
    # Find key metrics
    revenue = find_metric('revenue')
    cost_of_revenue = find_metric('cost of revenue', 'cost of goods', 'cogs')
    gross_profit = find_metric('gross profit')
    
    # Check: Gross profit = Revenue - Cost of revenue
    if revenue and cost_of_revenue and gross_profit:
        expected = revenue['value'] - cost_of_revenue['value']
        reported = gross_profit['value']
        if abs(expected - reported) > tolerance:
            return gross_profit
    
    # Check: Total operating expenses = sum of individual expenses
    # Find all operating expense items (excluding total)
    expense_items = []
    total_opex = None
    
    for key, metric in by_name.items():
        if 'total operating expenses' in key or 'total operating' in key:
            total_opex = metric
        elif any(kw in key for kw in ['research', 'development', 'sales', 'marketing', 
                                      'general and', 'administrative']):
            # Avoid double-counting if it's a total
            if 'total' not in key:
                expense_items.append(metric)
    
    if total_opex and expense_items:
        expected = sum(item['value'] for item in expense_items)
        reported = total_opex['value']
        if abs(expected - reported) > tolerance:
            return total_opex
    
    # Check: Operating income = Gross profit - Total operating expenses
    operating_income = find_metric('operating income', 'operating profit')
    if gross_profit and total_opex and operating_income:
        expected = gross_profit['value'] - total_opex['value']
        reported = operating_income['value']
        if abs(expected - reported) > tolerance:
            return operating_income
    
    # Check: Net income = Operating income + Other income/expense items
    net_income = find_metric('net income')
    if operating_income and net_income:
        # Find all non-operating items between operating income and net income
        # These are items that come after operating income in the statement
        other_items = 0
        for line_num, metric in sorted(metrics.items()):
            # Skip operating income and net income themselves
            if metric['name'].lower() in ['operating income', 'operating profit', 'net income']:
                continue
            # Include items after operating income line number
            if line_num > operating_income['line'] and line_num < net_income['line']:
                # This is a non-operating item (interest, tax, etc.)
                other_items += metric['value']
        
        expected = operating_income['value'] + other_items
        reported = net_income['value']
        if abs(expected - reported) > tolerance:
            return net_income
    
    return None


def verify_kpi_percentages(metrics):
    """
    Verify KPI percentage calculations.
    Returns the incorrect metric if found, None otherwise.
    """
    by_name = {}
    for m in metrics.values():
        by_name[m['name'].lower()] = m
    
    def find_metric(*keywords):
        """Find a metric, preferring exact matches over substring matches."""
        exact = None
        best = None
        for key, metric in by_name.items():
            for kw in keywords:
                if key == kw:
                    return metric  # Exact match wins immediately
                if kw in key:
                    if best is None or len(key) < len(best[1]['name'].lower()):
                        best = (key, metric)
        return best[1] if best else None
    
    # Need revenue for margin calculations
    revenue = find_metric('revenue')
    if not revenue or revenue['value'] == 0:
        return None
    
    tolerance = 0.05  # Percentages rounded to 1 decimal
    
    # Check: Gross margin = (Gross profit / Revenue) * 100
    gross_profit = find_metric('gross profit')
    gross_margin = find_metric('gross margin')
    if gross_profit and gross_margin:
        expected = (gross_profit['value'] / revenue['value']) * 100
        reported = gross_margin['value']
        if abs(expected - reported) > tolerance:
            return gross_margin
    
    # Check: Operating margin = (Operating income / Revenue) * 100
    operating_income = find_metric('operating income', 'operating profit')
    operating_margin = find_metric('operating margin')
    if operating_income and operating_margin:
        expected = (operating_income['value'] / revenue['value']) * 100
        reported = operating_margin['value']
        if abs(expected - reported) > tolerance:
            return operating_margin
    
    # Check: Net margin = (Net income / Revenue) * 100
    net_income = find_metric('net income')
    net_margin = find_metric('net margin')
    if net_income and net_margin:
        expected = (net_income['value'] / revenue['value']) * 100
        reported = net_margin['value']
        if abs(expected - reported) > tolerance:
            return net_margin
    
    return None


def main():
    if len(sys.argv) != 3:
        print("Usage: python verify_financials.py <html_file> <output_file>")
        sys.exit(1)
    
    html_file = sys.argv[1]
    output_file = sys.argv[2]
    
    # Read HTML file
    with open(html_file, 'r') as f:
        html_content = f.read()
    
    # Parse metrics
    metrics = parse_html_financials(html_content)
    
    if not metrics:
        print("Error: No metrics found in HTML file")
        sys.exit(1)
    
    print(f"Found {len(metrics)} metrics")
    for line_num, metric in sorted(metrics.items()):
        print(f"  Line {line_num}: {metric['name']} = {metric['raw']}")
    
    # Verify income statement
    print("\nVerifying income statement...")
    error = verify_income_statement(metrics)
    
    if error:
        print(f"ERROR FOUND: Line {error['line']} - {error['name']} = {error['raw']}")
    else:
        print("Income statement is consistent")
        
        # Verify KPI percentages
        print("\nVerifying KPI percentages...")
        error = verify_kpi_percentages(metrics)
        
        if error:
            print(f"ERROR FOUND: Line {error['line']} - {error['name']} = {error['raw']}")
        else:
            print("All KPI percentages are consistent")
            print("\nNo errors found!")
            sys.exit(1)
    
    # Write output
    # Extract numeric value without symbols
    value_str = error['raw'].replace('$', '').replace(',', '').replace('%', '').strip()
    
    output_line = f"{error['line']},{value_str}"
    
    with open(output_file, 'w') as f:
        f.write(output_line + '\n')
    
    print(f"\nOutput written to {output_file}: {output_line}")


if __name__ == '__main__':
    main()
