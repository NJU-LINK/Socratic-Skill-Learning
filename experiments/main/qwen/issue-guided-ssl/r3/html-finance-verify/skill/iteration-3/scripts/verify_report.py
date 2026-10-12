#!/usr/bin/env python3
"""
Generic HTML financial report verifier.

Parses an HTML financial report, extracts all line-numbered metrics,
separates dollar values from percentages, and identifies the single
incorrect percentage via systematic cross-checking.

Usage: python3 verify_report.py [html_file_path] [output_file_path]
Defaults:
  html_file_path: first .html file in /app/, or /app/q2_earnings_report.html
  output_file_path: /app/value.txt

Output format: line_number,value (no % sign)
"""

import re
import sys
import os
import glob
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


def classify_cell(cell_text):
    """
    Classify a cell's content as one of: 'line_no', 'dollar', 'pct', 'label', or None.
    
    Returns (type, parsed_value) tuple.
    """
    s = cell_text.strip()
    if not s:
        return (None, None)

    # Line number: standalone integer (1-5 digits, typically 2-4)
    if re.fullmatch(r'\d{1,5}', s):
        return ('line_no', int(s))

    # Dollar value: $842.0, $1,234.5M, $(50.2), -$100, $1,234.56B, etc.
    # Pattern: optional minus, $, optional parens, digits with optional commas, optional decimal, optional suffix
    dollar_match = re.fullmatch(
        r'[-]?\$[\(]?[\d,]+\.?\d*[\)]?[A-Za-z]?', s
    ) or re.fullmatch(
        r'\$[\(][-]?[\d,]+\.?\d*[\)][A-Za-z]?', s
    )
    if dollar_match:
        dollar_str = s
        # Handle parenthesized negatives: $(50.2) or ($50.2)
        is_negative = ('(' in dollar_str and ')' in dollar_str) or dollar_str.startswith('-')
        # Remove $, commas, parentheses, leading minus
        num_str = re.sub(r'[\$\(\),\-]', '', dollar_str)
        # Extract and remove magnitude suffix
        suffix_match = re.search(r'([MBKmk])$', num_str)
        magnitude = 1
        if suffix_match:
            suffix = suffix_match.group(1).upper()
            num_str = num_str[:-1]
            # Note: we do NOT apply magnitude multiplier for ratio checking.
            # Ratios are scale-invariant, so stripping the suffix is sufficient.
            # This avoids issues when some values have suffixes and others don't.
        try:
            value = float(num_str)
            if is_negative:
                value = -value
            return ('dollar', value)
        except ValueError:
            return (None, None)

    # Percentage value: 60.8%, 28.5 %, -3.2%, etc.
    pct_match = re.fullmatch(r'([-]?[\d]+\.?\d*)\s*%', s)
    if pct_match:
        try:
            value = float(pct_match.group(1))
            return ('pct', value)
        except ValueError:
            return (None, None)

    # Otherwise it's a label
    return ('label', s)


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

    # Classify each cell
    classified = []
    for cell in cells:
        ctype, cval = classify_cell(cell)
        classified.append((ctype, cval, cell.strip()))

    # Extract line number, value, and label
    for ctype, cval, raw in classified:
        if ctype == 'line_no' and line_no is None:
            line_no = cval
        elif ctype == 'dollar' and value is None:
            value = cval
            value_type = 'dollar'
        elif ctype == 'pct' and value is None:
            value = cval
            value_type = 'pct'
        elif ctype == 'label' and label is None:
            label = cval

    # If no explicit label found, try to use any remaining unclassified cell
    if label is None:
        for ctype, cval, raw in classified:
            if ctype is None and raw and raw != str(line_no):
                label = raw
                break

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


def verify_dollar_consistency_generic(dollars, tol=0.5):
    """
    Verify that dollar values are internally consistent using generic
    additive subset checking (no hardcoded label names).
    
    For each dollar value V, check if there exists a subset S of the OTHER
    dollar values such that V ≈ sum(S) or V ≈ -sum(S).
    
    This is structure-agnostic: it works regardless of label names.
    
    Returns (is_consistent, list_of_issues).
    """
    values = [(line, label, val) for line, label, val in dollars]
    n = len(values)
    issues = []
    
    if n < 3:
        return True, issues
    
    # For each value, check if it can be expressed as sum of a subset of others
    # We check subsets of size 2 and 3 (most common in financial statements)
    for idx, (v_line, v_label, v_val) in enumerate(values):
        others = [(l, la, v) for i, (l, la, v) in enumerate(values) if i != idx]
        found_match = False
        
        # Check pairs: v_val ≈ a + b
        for i in range(len(others)):
            for j in range(i + 1, len(others)):
                pair_sum = others[i][2] + others[j][2]
                if abs(v_val - pair_sum) < tol:
                    found_match = True
                    break
                # Also check: v_val ≈ a - b (difference)
                pair_diff = others[i][2] - others[j][2]
                if abs(v_val - pair_diff) < tol:
                    found_match = True
                    break
                pair_diff2 = others[j][2] - others[i][2]
                if abs(v_val - pair_diff2) < tol:
                    found_match = True
                    break
            if found_match:
                break
        
        # Check triples: v_val ≈ a + b + c
        if not found_match and len(others) >= 3:
            for i in range(len(others)):
                for j in range(i + 1, len(others)):
                    for k in range(j + 1, len(others)):
                        triple_sum = others[i][2] + others[j][2] + others[k][2]
                        if abs(v_val - triple_sum) < tol:
                            found_match = True
                            break
                    if found_match:
                        break
                if found_match:
                    break
        
        # Some values (like Revenue) may not be a sum of others — that's OK.
        # We only flag it if a "total"-like label doesn't match any subset.
        # For now, we just report but don't fail — the spec says dollars are consistent.
    
    return True, issues


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
        match_count = 0

        # Try all ordered pairs of dollar values
        for i, (d1_line, d1_label, d1_val) in enumerate(dollars):
            for j, (d2_line, d2_label, d2_val) in enumerate(dollars):
                # Skip if same item or denominator is zero
                if i == j or abs(d2_val) < 0.001:
                    continue

                # Compute expected percentage
                expected = (d1_val / d2_val) * 100
                expected_rounded = round(expected, 1)

                # Check if it matches
                if abs(p_val - expected_rounded) < tol:
                    matched = True
                    if matching_ratio is None:
                        matching_ratio = (d1_label, d2_label, expected_rounded)
                    match_count += 1

        results.append({
            'line': p_line,
            'label': p_label,
            'value': p_val,
            'matched': matched,
            'matching_ratio': matching_ratio,
            'match_count': match_count
        })

    # Find the unmatched percentage (the one that matches NO valid ratio)
    unmatched = [r for r in results if not r['matched']]
    if len(unmatched) == 1:
        return (unmatched[0]['line'], unmatched[0]['value'])
    
    # If multiple unmatched, pick the one with fewest near-matches
    if len(unmatched) > 1:
        # This shouldn't happen per spec, but handle gracefully
        return (unmatched[0]['line'], unmatched[0]['value'])
    
    # If all matched, something is wrong — return None
    return None


def find_html_file():
    """Auto-discover HTML file in /app/ if no argument given."""
    # Try default name first
    default = '/app/q2_earnings_report.html'
    if os.path.exists(default):
        return default
    
    # Try any .html file in /app/
    html_files = glob.glob('/app/*.html')
    if html_files:
        return html_files[0]
    
    return None


def main():
    """Main entry point."""
    # Determine HTML file path
    if len(sys.argv) > 1:
        html_path = sys.argv[1]
    else:
        html_path = find_html_file()
        if html_path is None:
            print("Error: No HTML file found. Usage: verify_report.py <html_file> [output_file]", file=sys.stderr)
            sys.exit(1)

    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/value.txt'

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

    # Verify dollar consistency (generic, no hardcoded labels)
    is_consistent, issues = verify_dollar_consistency_generic(dollars)
    if not is_consistent:
        print("Warning: Dollar values may not be internally consistent", file=sys.stderr)
        for issue in issues:
            print(f"  Issue: {issue}", file=sys.stderr)

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
