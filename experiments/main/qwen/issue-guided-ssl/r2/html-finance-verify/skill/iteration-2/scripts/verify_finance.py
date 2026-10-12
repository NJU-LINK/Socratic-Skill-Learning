#!/usr/bin/env python3
"""
Generic HTML Financial Report Verifier

Parses any HTML financial report containing line-numbered metrics,
extracts all values, cross-checks financial relationships, and
isolates the single incorrect metric.

Usage:
    python3 verify_finance.py <html_path> <output_path> [--tolerance TOL]

Algorithm:
1. Parse HTML to extract all (line_number, metric_name, raw_value, parsed_value) tuples
2. Generate financial relationship checks:
   - Ratio (margin-style): pct = A / B * 100 for percentage entries
   - Growth (YoY-style): pct = (A - B) / B * 100 for percentage entries
   - Additive/Subtractive: target = sum(subset of 2-4) for dollar entries
   - Division (per-share-style): value = A / B for dollar entries
   - Multiplicative: target = A * B for dollar entries
3. Evaluate each check with tight tolerance (0.15)
4. Isolate the incorrect metric:
   - For percentages: no passing check of any applicable type (ratio or growth)
   - For dollars: clustering-based correction consistency across all check types
5. Write output as line_number,value (the incorrect value as displayed)
"""

import re
import sys
import os
from html.parser import HTMLParser
from itertools import combinations
from collections import Counter


# ---------------------------------------------------------------------------
# Stage 1: HTML Parsing and Value Extraction
# ---------------------------------------------------------------------------

class TableRowExtractor(HTMLParser):
    """Extract table rows with their cell contents from HTML."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._in_row = False
        self._in_cell = False
        self._current_row = []
        self._current_cell_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self._in_row = True
            self._current_row = []
        elif tag in ('td', 'th') and self._in_row:
            self._in_cell = True
            self._current_cell_text = ""

    def handle_endtag(self, tag):
        if tag == 'tr' and self._in_row:
            self._in_row = False
            if self._current_row:
                self.rows.append(self._current_row)
        elif tag in ('td', 'th') and self._in_cell:
            self._in_cell = False
            self._current_row.append(self._current_cell_text.strip())

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell_text += data


def parse_numeric(text):
    """Parse a financial numeric string into a float.
    Handles: $1,234.5, (123.4) for negatives, 60.8%, 1.5K, 2.3M, 1.1B suffixes.
    """
    if not text:
        return None, False

    original = text.strip()
    is_pct = '%' in original

    cleaned = original
    cleaned = cleaned.replace('$', '').replace(',', '').replace('%', '').strip()

    # Handle unit suffixes (K=thousands, M=millions, B=billions)
    multiplier = 1.0
    if cleaned.upper().endswith('K'):
        multiplier = 1_000.0
        cleaned = cleaned[:-1]
    elif cleaned.upper().endswith('M'):
        multiplier = 1_000_000.0
        cleaned = cleaned[:-1]
    elif cleaned.upper().endswith('B'):
        multiplier = 1_000_000_000.0
        cleaned = cleaned[:-1]

    # Handle parentheses as negative: (123.4) -> -123.4
    paren_match = re.match(r'^\((.+)\)$', cleaned)
    if paren_match:
        cleaned = '-' + paren_match.group(1)

    cleaned = cleaned.strip()
    if not cleaned:
        return None, False

    try:
        return float(cleaned) * multiplier, is_pct
    except ValueError:
        return None, False


def extract_line_values(html_path):
    """Extract all line-numbered financial values from an HTML report."""
    with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
        html_content = f.read()

    parser = TableRowExtractor()
    parser.feed(html_content)

    results = []
    for row in parser.rows:
        if len(row) < 2:
            continue

        line_num = None
        line_idx = None
        for i, cell in enumerate(row):
            stripped = cell.strip()
            if re.match(r'^\d{1,4}$', stripped):
                candidate = int(stripped)
                if 1 <= candidate <= 9999:
                    line_num = candidate
                    line_idx = i
                    break

        if line_num is None:
            continue

        metric_name = None
        raw_value = None
        parsed_value = None
        is_pct = False

        for i, cell in enumerate(row):
            if i == line_idx:
                continue
            val, pct = parse_numeric(cell)
            if val is not None and cell.strip() != str(line_num):
                parsed_value = val
                raw_value = cell.strip()
                is_pct = pct
            elif val is None and cell.strip():
                metric_name = cell.strip()

        if line_num is not None and parsed_value is not None:
            results.append({
                'line': line_num,
                'metric': metric_name or '',
                'raw_value': raw_value or '',
                'value': parsed_value,
                'is_pct': is_pct,
            })

    return results


# ---------------------------------------------------------------------------
# Stage 2: Financial Relationship Discovery
# ---------------------------------------------------------------------------

def discover_ratio_checks(entries):
    """
    Generate ALL possible margin-style ratio checks: pct = A / B * 100
    For each percentage entry, try all pairs of dollar entries.
    """
    dollar_entries = [e for e in entries if not e['is_pct']]
    pct_entries = [e for e in entries if e['is_pct']]
    checks = []

    for pct_entry in pct_entries:
        for a_entry in dollar_entries:
            for b_entry in dollar_entries:
                if a_entry['line'] == b_entry['line']:
                    continue
                if abs(b_entry['value']) < 0.01:
                    continue
                expected_pct = a_entry['value'] / b_entry['value'] * 100
                checks.append({
                    'type': 'ratio',
                    'description': f"Line {pct_entry['line']} ({pct_entry['metric']}) = Line {a_entry['line']} ({a_entry['metric']}) / Line {b_entry['line']} ({b_entry['metric']}) * 100",
                    'all_lines': {pct_entry['line'], a_entry['line'], b_entry['line']},
                    'actual_line': pct_entry['line'],
                    'expected': expected_pct,
                    'numerator_line': a_entry['line'],
                    'denominator_line': b_entry['line'],
                })

    return checks


def discover_growth_checks(entries):
    """
    Generate ALL possible YoY growth checks: pct = (A - B) / B * 100
    For each percentage entry, try all pairs of dollar entries.
    This handles year-over-year change percentages.
    """
    dollar_entries = [e for e in entries if not e['is_pct']]
    pct_entries = [e for e in entries if e['is_pct']]
    checks = []

    for pct_entry in pct_entries:
        for a_entry in dollar_entries:
            for b_entry in dollar_entries:
                if a_entry['line'] == b_entry['line']:
                    continue
                if abs(b_entry['value']) < 0.01:
                    continue
                expected_pct = (a_entry['value'] - b_entry['value']) / b_entry['value'] * 100
                checks.append({
                    'type': 'growth',
                    'description': f"Line {pct_entry['line']} ({pct_entry['metric']}) = (Line {a_entry['line']} ({a_entry['metric']}) - Line {b_entry['line']} ({b_entry['metric']})) / Line {b_entry['line']} * 100",
                    'all_lines': {pct_entry['line'], a_entry['line'], b_entry['line']},
                    'actual_line': pct_entry['line'],
                    'expected': expected_pct,
                    'numerator_line': a_entry['line'],
                    'denominator_line': b_entry['line'],
                })

    return checks


def discover_subset_checks(entries, discovery_tolerance=10.0):
    """
    Find additive/subtractive relationships via subset-sum enumeration.
    For each dollar entry, check if any subset of 2-4 OTHER dollar entries
    sums to its value (within discovery tolerance).
    """
    dollar_entries = [e for e in entries if not e['is_pct']]
    checks = []
    
    for target in dollar_entries:
        others = [e for e in dollar_entries if e['line'] != target['line']]
        
        for size in range(2, min(len(others) + 1, 5)):
            for subset in combinations(others, size):
                subset_sum = sum(e['value'] for e in subset)
                if abs(subset_sum - target['value']) < discovery_tolerance:
                    subset_lines = [e['line'] for e in subset]
                    checks.append({
                        'type': 'additive',
                        'description': f"Line {target['line']} ({target['metric']}) = sum({subset_lines})",
                        'all_lines': {target['line']} | set(subset_lines),
                        'actual_line': target['line'],
                        'expected': subset_sum,
                    })
    
    return checks


def discover_division_checks(entries, discovery_tolerance=10.0):
    """
    Find per-share-style division relationships: value = A / B
    For each dollar entry, check if it equals any pair of other dollar entries divided.
    """
    dollar_entries = [e for e in entries if not e['is_pct']]
    checks = []
    
    for target in dollar_entries:
        others = [e for e in dollar_entries if e['line'] != target['line']]
        
        for a_entry in others:
            for b_entry in others:
                if a_entry['line'] == b_entry['line']:
                    continue
                if abs(b_entry['value']) < 0.01:
                    continue
                expected = a_entry['value'] / b_entry['value']
                if abs(expected - target['value']) < discovery_tolerance:
                    checks.append({
                        'type': 'division',
                        'description': f"Line {target['line']} ({target['metric']}) = Line {a_entry['line']} ({a_entry['metric']}) / Line {b_entry['line']} ({b_entry['metric']})",
                        'all_lines': {target['line'], a_entry['line'], b_entry['line']},
                        'actual_line': target['line'],
                        'expected': expected,
                        'numerator_line': a_entry['line'],
                        'denominator_line': b_entry['line'],
                    })
    
    return checks


def discover_multiplicative_checks(entries, discovery_tolerance=10.0):
    """
    Find multiplicative relationships: target = A * B
    For each dollar entry, check if it equals any pair of other dollar entries multiplied.
    """
    dollar_entries = [e for e in entries if not e['is_pct']]
    checks = []
    
    for target in dollar_entries:
        others = [e for e in dollar_entries if e['line'] != target['line']]
        
        for i, a_entry in enumerate(others):
            for b_entry in others[i+1:]:
                expected = a_entry['value'] * b_entry['value']
                if abs(expected - target['value']) < discovery_tolerance:
                    checks.append({
                        'type': 'multiplicative',
                        'description': f"Line {target['line']} ({target['metric']}) = Line {a_entry['line']} ({a_entry['metric']}) * Line {b_entry['line']} ({b_entry['metric']})",
                        'all_lines': {target['line'], a_entry['line'], b_entry['line']},
                        'actual_line': target['line'],
                        'expected': expected,
                        'factor1_line': a_entry['line'],
                        'factor2_line': b_entry['line'],
                    })
    
    return checks


def deduplicate_checks(checks):
    """Remove duplicate checks."""
    seen = set()
    unique = []
    for c in checks:
        if c['type'] in ('ratio', 'growth', 'division'):
            key = (c['type'], c['actual_line'], 
                   c.get('numerator_line'), c.get('denominator_line'))
        elif c['type'] == 'multiplicative':
            key = (c['type'], c['actual_line'],
                   c.get('factor1_line'), c.get('factor2_line'))
        else:
            key = (c['type'], tuple(sorted(c['all_lines'])), c['actual_line'])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


# ---------------------------------------------------------------------------
# Stage 3: Evaluate and Isolate
# ---------------------------------------------------------------------------

def evaluate_checks(checks, entries_by_line, tolerance=0.15):
    """Evaluate all checks. Return list of (check, passed: bool)."""
    results = []
    for check in checks:
        actual = entries_by_line[check['actual_line']]['value']
        expected = check['expected']
        passed = abs(actual - expected) < tolerance
        results.append((check, passed))
    return results


def compute_correction(check, candidate_line, entries_by_line):
    """
    Compute what candidate_line's value should be for the check to pass.
    Returns None if candidate_line is not involved in the check.
    """
    if candidate_line not in check['all_lines']:
        return None
    
    check_type = check['type']
    
    if check_type == 'ratio':
        # pct = A / B * 100
        pct_line = check['actual_line']
        a_line = check['numerator_line']
        b_line = check['denominator_line']
        
        if candidate_line == pct_line:
            return entries_by_line[a_line]['value'] / entries_by_line[b_line]['value'] * 100
        elif candidate_line == a_line:
            return entries_by_line[pct_line]['value'] * entries_by_line[b_line]['value'] / 100
        elif candidate_line == b_line:
            return entries_by_line[a_line]['value'] * 100 / entries_by_line[pct_line]['value']
    
    elif check_type == 'growth':
        # pct = (A - B) / B * 100
        pct_line = check['actual_line']
        a_line = check['numerator_line']
        b_line = check['denominator_line']
        
        if candidate_line == pct_line:
            return (entries_by_line[a_line]['value'] - entries_by_line[b_line]['value']) / entries_by_line[b_line]['value'] * 100
        elif candidate_line == a_line:
            return entries_by_line[b_line]['value'] * (entries_by_line[pct_line]['value'] / 100 + 1)
        elif candidate_line == b_line:
            return entries_by_line[a_line]['value'] / (entries_by_line[pct_line]['value'] / 100 + 1)
    
    elif check_type == 'additive':
        # target = sum(subset)
        target_line = check['actual_line']
        
        if candidate_line == target_line:
            return check['expected']
        else:
            # candidate is in the subset
            other_sum = sum(entries_by_line[l]['value'] 
                           for l in check['all_lines'] 
                           if l != candidate_line and l != target_line)
            target = entries_by_line[target_line]['value']
            return target - other_sum
    
    elif check_type == 'division':
        # value = A / B
        value_line = check['actual_line']
        a_line = check['numerator_line']
        b_line = check['denominator_line']
        
        if candidate_line == value_line:
            return entries_by_line[a_line]['value'] / entries_by_line[b_line]['value']
        elif candidate_line == a_line:
            return entries_by_line[value_line]['value'] * entries_by_line[b_line]['value']
        elif candidate_line == b_line:
            return entries_by_line[a_line]['value'] / entries_by_line[value_line]['value']
    
    elif check_type == 'multiplicative':
        # target = A * B
        target_line = check['actual_line']
        a_line = check['factor1_line']
        b_line = check['factor2_line']
        
        if candidate_line == target_line:
            return entries_by_line[a_line]['value'] * entries_by_line[b_line]['value']
        elif candidate_line == a_line:
            if abs(entries_by_line[b_line]['value']) < 0.01:
                return None
            return entries_by_line[target_line]['value'] / entries_by_line[b_line]['value']
        elif candidate_line == b_line:
            if abs(entries_by_line[a_line]['value']) < 0.01:
                return None
            return entries_by_line[target_line]['value'] / entries_by_line[a_line]['value']
    
    return None


def isolate_incorrect(check_results, entries_by_line, entries):
    """
    Find the single line that is incorrect.

    Strategy:
    1. For percentage entries: check if they have ANY passing check of applicable type
       (ratio or growth). A correct percentage will have at least one; an incorrect one will have none.
    2. For dollar entries: find the one that has a consistent correction across
       all failing checks involving it (any applicable type: additive, division, multiplicative).
    """
    pct_entries = [e for e in entries if e['is_pct']]

    # --- Approach 1: Check percentages ---
    # Applicable check types for percentages: ratio, growth
    pct_has_passing = {}
    for pct_entry in pct_entries:
        pct_line = pct_entry['line']
        has_passing = False
        for check, passed in check_results:
            if check['type'] in ('ratio', 'growth') and check['actual_line'] == pct_line and passed:
                has_passing = True
                break
        pct_has_passing[pct_line] = has_passing

    pcts_without_passing = [l for l, has in pct_has_passing.items() if not has]

    # If exactly one percentage has no passing check, that's our answer
    if len(pcts_without_passing) == 1:
        line = pcts_without_passing[0]
        entry = entries_by_line[line]
        return line, entry, None

    # --- Approach 2: Find dollar value with consistent correction ---
    # Applicable check types for dollar entries: additive, division, multiplicative
    failing_dollar_checks = [c for c, p in check_results 
                            if not p and c['type'] in ('additive', 'division', 'multiplicative')]
    
    if failing_dollar_checks:
        # Get all candidate lines from failing checks
        candidate_lines = set()
        for fc in failing_dollar_checks:
            candidate_lines.update(fc['all_lines'])
        
        # Filter to dollar entries
        dollar_candidates = {l for l in candidate_lines
                            if any(e['line'] == l and not e['is_pct'] for e in entries)}
        
        # For each candidate, compute corrections from all failing checks
        best_candidate = None
        best_cluster_size = 0
        
        for candidate_line in dollar_candidates:
            corrections = []
            
            for check in failing_dollar_checks:
                correction = compute_correction(check, candidate_line, entries_by_line)
                if correction is not None:
                    corrections.append(correction)
            
            # Find the largest cluster of consistent corrections
            if len(corrections) >= 2:
                sorted_corrections = sorted(corrections)
                best_cluster = []
                for i in range(len(sorted_corrections)):
                    cluster = [sorted_corrections[i]]
                    for j in range(i + 1, len(sorted_corrections)):
                        if abs(sorted_corrections[j] - sorted_corrections[i]) < 0.3:
                            cluster.append(sorted_corrections[j])
                        else:
                            break
                    if len(cluster) > len(best_cluster):
                        best_cluster = cluster
                
                # Check if the cluster mean is significantly different from the actual value
                # This filters out spurious relationships where the candidate is actually correct
                if len(best_cluster) >= 2:
                    cluster_mean = sum(best_cluster) / len(best_cluster)
                    actual_value = entries_by_line[candidate_line]['value']
                    
                    # The cluster should point to a value different from the actual value
                    # Otherwise, the candidate is likely correct and the failing checks are spurious
                    if abs(cluster_mean - actual_value) > 0.5 and len(best_cluster) > best_cluster_size:
                        best_candidate = candidate_line
                        best_cluster_size = len(best_cluster)
        
        if best_candidate is not None:
            entry = entries_by_line[best_candidate]
            return best_candidate, entry, None
        
        # Fallback: pick the candidate in most failing checks
        if dollar_candidates:
            line_counts = Counter()
            for fc in failing_dollar_checks:
                for l in fc['all_lines']:
                    if l in dollar_candidates:
                        line_counts[l] += 1
            if line_counts:
                line = line_counts.most_common(1)[0][0]
                entry = entries_by_line[line]
                return line, entry, None

    return None, None, "Could not isolate incorrect value"


# ---------------------------------------------------------------------------
# Stage 4: Output
# ---------------------------------------------------------------------------

def format_output(line_num, raw_value):
    """Format output as line_number,value, stripping formatting characters."""
    cleaned = raw_value.replace('$', '').replace(',', '').replace('%', '').strip()
    # Remove unit suffixes
    if cleaned.upper().endswith(('K', 'M', 'B')):
        cleaned = cleaned[:-1]
    paren_match = re.match(r'^\((.+)\)$', cleaned)
    if paren_match:
        cleaned = '-' + paren_match.group(1)
    return f"{line_num},{cleaned}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 verify_finance.py <html_path> <output_path> [--tolerance TOL]")
        sys.exit(1)

    html_path = sys.argv[1]
    output_path = sys.argv[2]
    tolerance = 0.15

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--tolerance' and i + 1 < len(sys.argv):
            tolerance = float(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    # Stage 1: Extract
    print(f"Parsing {html_path}...")
    entries = extract_line_values(html_path)
    if not entries:
        print("ERROR: No line-numbered values found in HTML")
        sys.exit(1)

    entries_by_line = {e['line']: e for e in entries}
    print(f"Found {len(entries)} line-numbered metrics:")
    for e in entries:
        pct_str = "%" if e['is_pct'] else ""
        print(f"  Line {e['line']}: {e['metric']} = {e['raw_value']} (parsed: {e['value']}{pct_str})")

    # Stage 2: Discover relationships
    print("\nDiscovering financial relationships...")

    ratio_checks = discover_ratio_checks(entries)
    print(f"  Ratio checks (margin-style): {len(ratio_checks)}")

    growth_checks = discover_growth_checks(entries)
    print(f"  Growth checks (YoY-style): {len(growth_checks)}")

    subset_checks = discover_subset_checks(entries, discovery_tolerance=10.0)
    print(f"  Subset checks (additive/subtractive): {len(subset_checks)}")

    division_checks = discover_division_checks(entries, discovery_tolerance=10.0)
    print(f"  Division checks (per-share-style): {len(division_checks)}")

    multiplicative_checks = discover_multiplicative_checks(entries, discovery_tolerance=10.0)
    print(f"  Multiplicative checks: {len(multiplicative_checks)}")

    all_checks = ratio_checks + growth_checks + subset_checks + division_checks + multiplicative_checks
    all_checks = deduplicate_checks(all_checks)
    print(f"  Total unique checks: {len(all_checks)}")

    # Stage 3: Evaluate
    print(f"\nEvaluating checks (tolerance={tolerance})...")
    check_results = evaluate_checks(all_checks, entries_by_line, tolerance)

    passing = sum(1 for _, p in check_results if p)
    failing = sum(1 for _, p in check_results if not p)
    print(f"  Passing: {passing}, Failing: {failing}")

    failing_by_type = Counter()
    for check, passed in check_results:
        if not passed:
            failing_by_type[check['type']] += 1
    if failing > 0:
        print(f"  Failing by type: {dict(failing_by_type)}")

    # Isolate
    line_num, entry, error = isolate_incorrect(check_results, entries_by_line, entries)

    if error:
        print(f"\nERROR: {error}")
        sys.exit(1)

    # Stage 4: Output
    output = format_output(line_num, entry['raw_value'])
    print(f"\nIncorrect metric found:")
    print(f"  Line {line_num}: {entry['metric']} = {entry['raw_value']}")
    print(f"  Output: {output}")

    with open(output_path, 'w') as f:
        f.write(output + '\n')

    print(f"\nWritten to {output_path}")


if __name__ == '__main__':
    main()
