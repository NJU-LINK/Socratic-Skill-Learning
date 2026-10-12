#!/usr/bin/env python3
"""
HTML Financial Report Verifier

Parses HTML earnings reports, extracts financial data with line numbers,
and verifies internal consistency through additive and ratio checks.

Handles cascading failures where one wrong value causes multiple dependent
checks to fail, using label-guided involvement tracking and deterministic
root cause selection.
"""

import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from html.parser import HTMLParser


# Label synonyms for matching across variants (axis 1: section names vary)
LABEL_SYNONYMS = {
    'revenue': ['revenue', 'total revenue', 'net sales', 'total net sales', 'sales'],
    'cost_of_revenue': ['cost of revenue', 'cost of sales', 'cogs', 'cost of goods sold'],
    'gross_profit': ['gross profit', 'gross income', 'gross margin dollars', 'gross earnings'],
    'total_opex': ['total operating expenses', 'total opex', 'operating expenses', 'total operating costs'],
    'operating_income': ['operating income', 'operating profit', 'income from operations'],
    'net_income': ['net income', 'net profit', 'bottom line'],
    'other_income': ['other income', 'other income net', 'other expenses'],
    'shares': ['shares outstanding', 'shares', 'common shares'],
}

# Keywords for identifying expense lines (axis 1: metric families vary)
EXPENSE_KEYWORDS = ['research', 'development', 'marketing', 'general', 'administrative', 'r&d', 'sg&a', 'overhead']
EXCLUDE_KEYWORDS = ['cost of revenue', 'cost of sales', 'cogs', 'cost of goods sold', 'total']


class FinancialReportParser(HTMLParser):
    """Parse HTML financial reports extracting line-numbered values."""
    
    def __init__(self):
        super().__init__()
        self.records = []
        self.in_line_cell = False
        self.in_label_cell = False
        self.in_value_cell = False
        self.current_line = None
        self.current_label = None
        self.current_value = None
        self.cell_buffer = []
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ('td', 'th'):  # Handle both td and th for labels
            self.cell_buffer = []
            class_attr = attrs_dict.get('class', '')
            if 'line' in class_attr.split():
                self.in_line_cell = True
            elif 'num' in class_attr.split():
                self.in_value_cell = True
            else:
                self.in_label_cell = True
    
    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            content = ''.join(self.cell_buffer).strip()
            if self.in_line_cell:
                self.current_line = content
            elif self.in_label_cell:
                self.current_label = content
            elif self.in_value_cell:
                self.current_value = content
            self.in_line_cell = False
            self.in_label_cell = False
            self.in_value_cell = False
        elif tag == 'tr':
            if self.current_line and self.current_value:
                parsed = self._parse_value(self.current_value)
                self.records.append({
                    'line': self.current_line,
                    'label': self.current_label or '',
                    'raw_value': self.current_value,
                    'number': parsed['number'],
                    'is_percent': parsed['is_percent'],
                    'decimals': parsed['decimals'],
                    'unit': parsed['unit']
                })
            self.current_line = None
            self.current_label = None
            self.current_value = None
    
    def handle_data(self, data):
        self.cell_buffer.append(data)
    
    def _parse_value(self, raw):
        """Parse a raw value string into components with unit suffix support."""
        s = raw.strip()
        original = s
        is_percent = '%' in s
        
        # Remove formatting symbols
        s = s.replace('$', '').replace('%', '').replace(',', '')
        s = s.replace('&nbsp;', ' ').strip()
        
        # Handle parentheses negatives: (123.45) → -123.45
        if s.startswith('(') and s.endswith(')'):
            s = '-' + s[1:-1]
        
        # Detect and apply unit suffixes (K/M/B)
        unit = Decimal('1')
        s_upper = s.upper().rstrip()
        if s_upper.endswith('K'):
            unit = Decimal('1000')
            s = s[:-1]
        elif s_upper.endswith('M'):
            unit = Decimal('1000000')
            s = s[:-1]
        elif s_upper.endswith('B'):
            unit = Decimal('1000000000')
            s = s[:-1]
        
        s = s.strip()
        
        # Count decimals in displayed value
        decimals = 0
        if '.' in s:
            decimals = len(s.split('.')[1])
        
        # Parse number and apply unit
        number = None
        try:
            if s and s not in ['-', '—', '–', '']:
                number = Decimal(s) * unit
        except (InvalidOperation, ValueError):
            pass
        
        return {
            'number': number,
            'is_percent': is_percent,
            'decimals': decimals,
            'unit': unit,
            'raw': original
        }


def round_half_up(value, decimals):
    """Round using ROUND_HALF_UP (not banker's rounding)."""
    if value is None:
        return None
    quantize_str = '0.' + '0' * decimals
    return value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def within_tolerance(reported, expected, decimals):
    """Check if values match within rounding tolerance."""
    if reported is None or expected is None:
        return False
    tolerance = Decimal('0.5') * (Decimal('10') ** (-decimals))
    return abs(reported - expected) <= tolerance


def label_matches(label, synonyms):
    """Check if label matches any synonym (case-insensitive)."""
    label_lower = label.lower()
    for syn in synonyms:
        if syn in label_lower:
            return True
    return False


def is_expense_line(r, total_opex_line):
    """Check if record is an expense line (not a total, not cost of revenue)."""
    if total_opex_line and r['line'] == total_opex_line:
        return False
    label_lower = r['label'].lower()
    # Exclude cost of revenue and totals
    if any(kw in label_lower for kw in EXCLUDE_KEYWORDS):
        return False
    return any(kw in label_lower for kw in EXPENSE_KEYWORDS)


def find_record_by_synonym(records, synonyms):
    """Find a record whose label matches any synonym."""
    for r in records:
        if label_matches(r['label'], synonyms):
            return r
    return None


def resolve_ratio_operands(pct, dollar_records):
    """Resolve numerator/denominator for a percentage based on its label."""
    label_lower = pct['label'].lower()
    
    # Map margin types to their operands
    if 'gross margin' in label_lower or 'gross' in label_lower:
        num = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['gross_profit'])
        den = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['revenue'])
        return num, den
    elif 'operating margin' in label_lower or 'operating' in label_lower:
        num = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['operating_income'])
        den = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['revenue'])
        return num, den
    elif 'net margin' in label_lower or 'net' in label_lower:
        num = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['net_income'])
        den = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['revenue'])
        return num, den
    
    return None, None


def check_additive_consistency(records):
    """Check additive relations with synonym matching."""
    dollar_records = [r for r in records if r['number'] is not None and not r['is_percent']]
    results = []
    checks_constructed = 0
    
    # Map labels to records using synonyms
    revenue = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['revenue'])
    cost_rev = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['cost_of_revenue'])
    gross = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['gross_profit'])
    total_opex = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['total_opex'])
    op_income = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['operating_income'])
    other = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['other_income'])
    net = find_record_by_synonym(dollar_records, LABEL_SYNONYMS['net_income'])
    
    # Find expense lines (exclude totals and cost of revenue)
    total_opex_line = total_opex['line'] if total_opex else None
    expenses = [r for r in dollar_records if is_expense_line(r, total_opex_line)]
    
    # Check gross profit = revenue - cost_of_revenue
    if revenue and cost_rev and gross:
        expected = revenue['number'] - cost_rev['number']
        expected_r = round_half_up(expected, gross['decimals'])
        involved = {revenue['line'], cost_rev['line'], gross['line']}
        results.append({
            'type': 'gross_profit',
            'record': gross,
            'involved': involved,
            'expected': expected_r,
            'is_consistent': within_tolerance(gross['number'], expected_r, gross['decimals'])
        })
        checks_constructed += 1
    
    # Check total opex = sum of expenses
    if total_opex and expenses:
        expected = sum(e['number'] for e in expenses)
        expected_r = round_half_up(expected, total_opex['decimals'])
        involved = {e['line'] for e in expenses} | {total_opex['line']}
        results.append({
            'type': 'total_opex',
            'record': total_opex,
            'involved': involved,
            'expected': expected_r,
            'is_consistent': within_tolerance(total_opex['number'], expected_r, total_opex['decimals'])
        })
        checks_constructed += 1
    
    # Check operating income = gross_profit - total_opex
    if gross and total_opex and op_income:
        expected = gross['number'] - total_opex['number']
        expected_r = round_half_up(expected, op_income['decimals'])
        involved = {gross['line'], total_opex['line'], op_income['line']}
        results.append({
            'type': 'operating_income',
            'record': op_income,
            'involved': involved,
            'expected': expected_r,
            'is_consistent': within_tolerance(op_income['number'], expected_r, op_income['decimals'])
        })
        checks_constructed += 1
    
    # Check net income = operating_income + other_income
    if op_income and net:
        expected = op_income['number'] + (other['number'] if other else Decimal('0'))
        expected_r = round_half_up(expected, net['decimals'])
        involved = {op_income['line'], net['line']}
        if other:
            involved.add(other['line'])
        results.append({
            'type': 'net_income',
            'record': net,
            'involved': involved,
            'expected': expected_r,
            'is_consistent': within_tolerance(net['number'], expected_r, net['decimals'])
        })
        checks_constructed += 1
    
    return results, checks_constructed


def check_ratio_consistency(records):
    """Check if each percentage has explaining pairs of dollar values."""
    dollar_records = [r for r in records if r['number'] is not None and not r['is_percent']]
    percent_records = [r for r in records if r['number'] is not None and r['is_percent']]
    
    results = []
    for pct in percent_records:
        explaining_pairs = []
        decimals = pct['decimals']
        
        # Brute-force search for explaining pairs
        for num in dollar_records:
            for denom in dollar_records:
                if num == denom or denom['number'] == 0:
                    continue
                
                expected = (num['number'] / denom['number']) * Decimal('100')
                expected_r = round_half_up(expected, decimals)
                if within_tolerance(pct['number'], expected_r, decimals):
                    explaining_pairs.append((num, denom, expected_r, 'ratio'))
                
                expected_yoy = ((num['number'] - denom['number']) / denom['number']) * Decimal('100')
                expected_yoy_r = round_half_up(expected_yoy, decimals)
                if within_tolerance(pct['number'], expected_yoy_r, decimals):
                    explaining_pairs.append((num, denom, expected_yoy_r, 'yoy'))
        
        # Label-guided involvement: include resolved numerator/denominator
        num, den = resolve_ratio_operands(pct, dollar_records)
        involved = {pct['line']}
        if num:
            involved.add(num['line'])
        if den:
            involved.add(den['line'])
        
        results.append({
            'record': pct,
            'involved': involved,
            'explaining_pairs': explaining_pairs,
            'is_consistent': len(explaining_pairs) > 0
        })
    
    return results


def check_per_share(records):
    """Check per-share values like EPS (axis 2: per-share values)."""
    dollar_records = [r for r in records if r['number'] is not None and not r['is_percent']]
    per_share_records = [r for r in records if r['number'] is not None and not r['is_percent'] 
                       and any(kw in r['label'].lower() for kw in ['eps', 'per share', 'per unit'])]
    
    results = []
    for ps in per_share_records:
        decimals = ps['decimals']
        explaining_pairs = []
        
        # Search for explaining pairs (numerator / denominator)
        for num in dollar_records:
            for denom in dollar_records:
                if num == denom or denom['number'] == 0:
                    continue
                expected = num['number'] / denom['number']
                expected_r = round_half_up(expected, decimals)
                if within_tolerance(ps['number'], expected_r, decimals):
                    explaining_pairs.append((num, denom, expected_r))
        
        involved = {ps['line']}
        if explaining_pairs:
            # Include first explaining pair
            num, den, _ = explaining_pairs[0]
            involved.add(num['line'])
            involved.add(den['line'])
        
        results.append({
            'record': ps,
            'involved': involved,
            'is_consistent': len(explaining_pairs) > 0
        })
    
    return results


def find_root_cause(failed_checks):
    """
    Find root cause with deterministic selection.
    
    Returns (line, value, diagnostics) where diagnostics is empty list on success,
    or candidate info on ambiguity.
    """
    if not failed_checks:
        return None, None, []
    
    if len(failed_checks) == 1:
        return failed_checks[0]['record']['line'], str(failed_checks[0]['record']['number']), []
    
    # Track participation
    line_participation = {}
    line_is_target = {}  # Track if line is a target (not just operand)
    check_ids = set(range(len(failed_checks)))
    
    for i, check in enumerate(failed_checks):
        for line in check['involved']:
            if line not in line_participation:
                line_participation[line] = set()
                line_is_target[line] = False
            line_participation[line].add(i)
            if check['record']['line'] == line:
                line_is_target[line] = True
    
    # Find lines that participate in ALL failed checks
    root_candidates = []
    for line, checks in line_participation.items():
        if checks == check_ids:
            root_candidates.append(line)
    
    for line in sorted(root_candidates):  # Sort for determinism
        for check in failed_checks:
            if check['record']['line'] == line:
                return line, str(check['record']['number']), []
    
    # No full coverage - use deterministic fallback
    # Sort by: (is_target, participation_count DESC, line_num ASC)
    scored = []
    for line, checks in line_participation.items():
        scored.append((line_is_target[line], len(checks), -int(line), line))
    
    scored.sort(reverse=True)
    
    if scored:
        best_line = scored[0][3]
        # Find check targeting this line
        for check in failed_checks:
            if check['record']['line'] == best_line:
                return best_line, str(check['record']['number']), scored
    
    return None, None, scored


def verify_report(html_path, verbose=True):
    """Main verification function."""
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    parser = FinancialReportParser()
    parser.feed(html_content)
    records = parser.records
    
    if verbose:
        print("PARSED RECORDS:")
        for r in records:
            print(f"  Line {r['line']}: {r['label'][:25]:25} = {r['raw_value']}")
    
    additive_results, additive_count = check_additive_consistency(records)
    ratio_results = check_ratio_consistency(records)
    per_share_results = check_per_share(records)
    
    if verbose:
        print(f"\nADDITIVE CHECKS ({additive_count} constructed):")
        if additive_count == 0:
            print("  WARNING: No additive checks could be constructed!")
        for res in additive_results:
            status = "✓" if res['is_consistent'] else "✗"
            print(f"  {status} Line {res['record']['line']}: {res['record']['label'][:20]} ({res['type']})")
        
        print(f"\nRATIO CHECKS ({len(ratio_results)} constructed):")
        for res in ratio_results:
            status = "✓" if res['is_consistent'] else "✗"
            print(f"  {status} Line {res['record']['line']}: {res['record']['label'][:20]} = {res['record']['raw_value']}")
        
        if per_share_results:
            print(f"\nPER-SHARE CHECKS ({len(per_share_results)} constructed):")
            for res in per_share_results:
                status = "✓" if res['is_consistent'] else "✗"
                print(f"  {status} Line {res['record']['line']}: {res['record']['label'][:20]}")
    
    # Find all failed checks
    all_checks = additive_results + ratio_results + per_share_results
    failed_checks = [c for c in all_checks if not c['is_consistent']]
    
    if verbose:
        print(f"\n{'='*50}")
        print(f"Total failed checks: {len(failed_checks)}")
    
    # Find root cause using coverage analysis
    line, value, diagnostics = find_root_cause(failed_checks)
    
    if verbose:
        if line and value:
            print(f"ANSWER: {line},{value}")
        elif failed_checks:
            print(f"AMBIGUOUS - candidates: {diagnostics}")
            if diagnostics:
                best = sorted(diagnostics, reverse=True)[0]
                print(f"BEST GUESS: {best[3]}")
        else:
            print("No failures found.")
    
    return line, value


def find_incorrect_metric(html_path):
    """
    Find the single incorrect metric in an HTML financial report.
    Silent/verbose=False version for programmatic use.
    Returns (line_number, value) or (None, None) if not found.
    """
    return verify_report(html_path, verbose=False)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: verify_report.py <html_file>")
        sys.exit(1)
    
    line, value = verify_report(sys.argv[1], verbose=True)
    if line and value:
        print(f"\nCANDIDATE: {line},{value}")
    else:
        print("\nNo clear answer found.")
        sys.exit(1)
