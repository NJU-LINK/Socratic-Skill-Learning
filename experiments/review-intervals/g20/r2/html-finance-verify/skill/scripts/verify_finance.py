#!/usr/bin/env python3
"""
HTML Financial Verification with Root-Cause Analysis and Robust Brute-Force Fallback.

Parses an HTML earnings report, verifies internal consistency using a
relationship template catalog with scored fuzzy matching, and identifies
the single incorrect metric via root-cause analysis of cascading failures.
Falls back to robust brute-force percentage checking when templates don't match.

Usage:
    python verify_finance.py [html_file] [output_file]
    Defaults: /app/q2_earnings_report.html -> /app/value.txt
"""
from html.parser import HTMLParser
import sys
from collections import Counter


# ============================================================================
# HTML PARSING
# ============================================================================

class FinancialTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metrics = []
        self.in_td = False
        self.current_row = []
        self.current_data = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'td':
            self.in_td = True
            self.current_data = ""
        elif tag == 'tr':
            self.current_row = []

    def handle_endtag(self, tag):
        if tag == 'td' and self.in_td:
            self.in_td = False
            self.current_row.append(self.current_data.strip())
        elif tag == 'tr':
            if len(self.current_row) >= 3:
                line_text = self.current_row[0]
                name = self.current_row[1]
                value_text = self.current_row[2]
                if line_text.isdigit():
                    vc = value_text.replace('$', '').replace('%', '').replace(',', '').strip()
                    if vc.startswith('(') and vc.endswith(')'):
                        vc = '-' + vc[1:-1]
                    try:
                        self.metrics.append({
                            'line': int(line_text),
                            'name': name,
                            'value': float(vc),
                            'raw': value_text,
                            'is_percentage': '%' in value_text,
                            'is_dollar': '$' in value_text
                        })
                    except ValueError:
                        pass

    def handle_data(self, data):
        if self.in_td:
            self.current_data += data


# ============================================================================
# SCORED FUZZY MATCHING
# ============================================================================

def name_matches_score(metric_name, patterns):
    """Score how well metric_name matches any pattern. Higher = better. 0 = no match."""
    name_lower = metric_name.lower().strip()
    best = 0
    for pattern in patterns:
        p = pattern.lower().strip()
        if name_lower == p:
            best = max(best, 100)
        elif all(w in name_lower for w in p.split()):
            nw = len(name_lower.split())
            pw = len(p.split())
            best = max(best, 50 + int((pw / max(nw, 1)) * 30))
        elif p in name_lower:
            best = max(best, int(20 * len(p) / max(len(name_lower), 1)))
    return best


def find_metric(metrics, patterns, exclude_lines=None):
    """Find the best-scoring metric matching any pattern."""
    candidates = []
    for m in metrics:
        if exclude_lines and m['line'] in exclude_lines:
            continue
        score = name_matches_score(m['name'], patterns)
        if score > 0:
            candidates.append((score, m))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


# ============================================================================
# EXPENSE COMPONENT DETECTION (by exclusion)
# ============================================================================

KNOWN_NON_EXPENSE = [
    ['revenue', 'total revenue', 'net revenue', 'net sales'],
    ['cost of revenue', 'cogs', 'cost of goods sold', 'cost of sales'],
    ['gross profit'],
    ['total operating expenses', 'total opex'],
    ['operating income', 'operating profit', 'operating loss'],
    ['net income', 'net profit', 'net earnings'],
    ['other income', 'other expense', 'non-operating'],
    ['margin', 'gross margin', 'operating margin', 'net margin'],
    ['earnings per share', 'eps'],
    ['growth', 'yoy'],
    ['ratio'],
]


def is_known_non_expense(name):
    for patterns in KNOWN_NON_EXPENSE:
        if name_matches_score(name, patterns) > 0:
            return True
    return False


def detect_expense_components(metrics):
    """Detect operating expense line items by exclusion + keyword matching."""
    kw = ['research', 'development', 'r&d', 'sales', 'marketing', 's&m',
          'general', 'administrative', 'g&a', 'selling',
          'depreciation', 'amortization', 'compensation',
          'rent', 'lease', 'professional', 'legal', 'engineering']
    out = []
    for m in metrics:
        if m['is_percentage'] or is_known_non_expense(m['name']):
            continue
        nl = m['name'].lower()
        if any(k in nl for k in kw):
            out.append(m)
    return out


# ============================================================================
# RELATIONSHIP TEMPLATES
# ============================================================================

TEMPLATES = [
    {'id': 'gp', 'result': ['gross profit'], 'op': 'sub',
     'operands': [['revenue', 'total revenue', 'net revenue', 'net sales'],
                  ['cost of revenue', 'cogs', 'cost of goods sold', 'cost of sales']]},
    {'id': 'opex', 'result': ['total operating expenses', 'total opex'],
     'op': 'sum_expenses'},
    {'id': 'oi', 'result': ['operating income', 'operating profit'],
     'op': 'sub', 'operands': [['gross profit'],
                                ['total operating expenses', 'total opex']]},
    {'id': 'ni_add', 'result': ['net income', 'net profit', 'net earnings'],
     'op': 'add', 'operands': [['operating income', 'operating profit'],
                                ['other income', 'non-operating income']]},
    {'id': 'ni_sub', 'result': ['net income', 'net profit'],
     'op': 'sub', 'operands': [['operating income', 'operating profit'],
                                ['other expense', 'net other expense']]},
    {'id': 'gm', 'result': ['gross margin', 'gross profit margin'],
     'op': 'pct', 'num': ['gross profit'],
     'denom': ['revenue', 'total revenue', 'net revenue', 'net sales']},
    {'id': 'om', 'result': ['operating margin', 'operating profit margin'],
     'op': 'pct', 'num': ['operating income', 'operating profit'],
     'denom': ['revenue', 'total revenue', 'net revenue', 'net sales']},
    {'id': 'nm', 'result': ['net margin', 'net profit margin', 'profit margin'],
     'op': 'pct', 'num': ['net income', 'net profit'],
     'denom': ['revenue', 'total revenue', 'net revenue', 'net sales']},
    {'id': 'eps', 'result': ['earnings per share', 'eps', 'diluted eps', 'basic eps'],
     'op': 'div', 'num': ['net income', 'net profit'],
     'denom': ['shares outstanding', 'diluted shares', 'weighted average shares']},
    {'id': 'rg', 'result': ['revenue growth', 'sales growth'],
     'op': 'yoy_pct', 'current': ['revenue', 'total revenue'],
     'prior': ['prior revenue', 'prior year revenue', 'previous revenue']},
    {'id': 'ng', 'result': ['net income growth', 'earnings growth'],
     'op': 'yoy_pct', 'current': ['net income', 'net profit'],
     'prior': ['prior net income', 'prior year net income']},
    {'id': 'cr', 'result': ['current ratio'],
     'op': 'div', 'num': ['current assets', 'total current assets'],
     'denom': ['current liabilities', 'total current liabilities']},
    {'id': 'de', 'result': ['debt to equity', 'debt-to-equity'],
     'op': 'div', 'num': ['total debt', 'debt'],
     'denom': ['total equity', 'shareholders equity', "stockholders' equity"]},
]


# ============================================================================
# TEMPLATE CHECKING — returns involved lines for root-cause tracking
# ============================================================================

def check_template(template, metrics):
    """
    Returns (matched, involved_lines: set[int], failing_line: int|None,
             failing_metric: dict|None, reported, calculated)
    """
    op = template['op']

    if op in ('sub', 'add'):
        rm = find_metric(metrics, template['result'])
        if not rm:
            return False, set(), None, None, 0, 0
        o1 = find_metric(metrics, template['operands'][0])
        o2 = find_metric(metrics, template['operands'][1])
        if not o1 or not o2:
            return False, set(), None, None, 0, 0
        involved = {rm['line'], o1['line'], o2['line']}
        calc = o1['value'] - o2['value'] if op == 'sub' else o1['value'] + o2['value']
        if abs(calc - rm['value']) >= 0.5:
            return True, involved, rm['line'], rm, rm['value'], calc
        return True, involved, None, None, rm['value'], calc

    elif op == 'sum_expenses':
        rm = find_metric(metrics, template['result'])
        if not rm:
            return False, set(), None, None, 0, 0
        comps = detect_expense_components(metrics)
        if len(comps) < 2:
            return False, set(), None, None, 0, 0
        involved = {rm['line']} | {c['line'] for c in comps}
        calc = sum(c['value'] for c in comps)
        if abs(calc - rm['value']) >= 0.5:
            return True, involved, rm['line'], rm, rm['value'], calc
        return True, involved, None, None, rm['value'], calc

    elif op == 'pct':
        rm = find_metric(metrics, template['result'])
        if not rm:
            return False, set(), None, None, 0, 0
        nm = find_metric(metrics, template['num'])
        dm = find_metric(metrics, template['denom'])
        if not nm or not dm or dm['value'] == 0:
            return False, set(), None, None, 0, 0
        involved = {rm['line'], nm['line'], dm['line']}
        calc = (nm['value'] / dm['value']) * 100
        if abs(calc - rm['value']) >= 0.15:
            return True, involved, rm['line'], rm, rm['value'], calc
        return True, involved, None, None, rm['value'], calc

    elif op == 'div':
        rm = find_metric(metrics, template['result'])
        if not rm:
            return False, set(), None, None, 0, 0
        nm = find_metric(metrics, template['num'])
        dm = find_metric(metrics, template['denom'])
        if not nm or not dm or dm['value'] == 0:
            return False, set(), None, None, 0, 0
        involved = {rm['line'], nm['line'], dm['line']}
        calc = nm['value'] / dm['value']
        failing = False
        if abs(calc) > 0:
            failing = abs(calc - rm['value']) / abs(calc) >= 0.02
        else:
            failing = abs(calc - rm['value']) >= 0.01
        if failing:
            return True, involved, rm['line'], rm, rm['value'], calc
        return True, involved, None, None, rm['value'], calc

    elif op == 'yoy_pct':
        rm = find_metric(metrics, template['result'])
        if not rm:
            return False, set(), None, None, 0, 0
        cm = find_metric(metrics, template['current'])
        pm = find_metric(metrics, template['prior'])
        if not cm or not pm or pm['value'] == 0:
            return False, set(), None, None, 0, 0
        involved = {rm['line'], cm['line'], pm['line']}
        calc = ((cm['value'] - pm['value']) / abs(pm['value'])) * 100
        if abs(calc - rm['value']) >= 0.15:
            return True, involved, rm['line'], rm, rm['value'], calc
        return True, involved, None, None, rm['value'], calc

    return False, set(), None, None, 0, 0


# ============================================================================
# ROOT-CAUSE ANALYSIS
# ============================================================================

def find_root_cause(metrics, failures):
    """
    Given a list of failures [(involved_lines, failing_line, failing_metric, ...)],
    find the single metric that is the root cause of all failures.
    """
    if not failures:
        return None

    all_sets = [f[0] for f in failures]
    intersection = all_sets[0].copy()
    for s in all_sets[1:]:
        intersection &= s

    result_lines = {f[1] for f in failures}

    if intersection:
        root_candidates = [ln for ln in intersection if ln in result_lines]
        if root_candidates:
            rc = Counter(f[1] for f in failures)
            root_candidates.sort(key=lambda ln: -rc.get(ln, 0))
            root_line = root_candidates[0]
        else:
            freq = Counter()
            for involved, _, _, _, _ in failures:
                for ln in involved:
                    freq[ln] += 1
            root_line = max(intersection, key=lambda ln: freq[ln])
    else:
        freq = Counter()
        for involved, _, _, _, _ in failures:
            for ln in involved:
                freq[ln] += 1
        root_line = freq.most_common(1)[0][0]

    return next((m for m in metrics if m['line'] == root_line), None)


# ============================================================================
# ROBUST BRUTE-FORCE PERCENTAGE CHECK
# ============================================================================

def brute_force_percentage_check_robust(metrics):
    """
    Robust brute-force that handles edge cases:
    - 0 unmatched (all match some pair): use closest-match with gap detection
    - 1 unmatched: return it
    - 2+ unmatched: use closest-match approach
    
    For each percentage, computes:
    - min_diff: minimum distance to any dollar pair
    - match_count: number of pairs within tolerance (0.15)
    
    The error is the percentage with the largest min_diff (when gap is clear).
    """
    dollars = [m for m in metrics if m['is_dollar'] and not m['is_percentage']]
    pcts = [m for m in metrics if m['is_percentage']]
    
    if not dollars or not pcts:
        return None
    
    # For each percentage, find min distance and match count
    pct_info = []
    for pct in pcts:
        min_diff = float('inf')
        match_count = 0
        for i, num in enumerate(dollars):
            for j, denom in enumerate(dollars):
                if i == j or denom['value'] == 0:
                    continue
                calc = (num['value'] / denom['value']) * 100
                diff = abs(calc - pct['value'])
                if diff < 0.15:
                    match_count += 1
                if diff < min_diff:
                    min_diff = diff
        pct_info.append({
            'metric': pct,
            'min_diff': min_diff,
            'match_count': match_count
        })
    
    # Count unmatched (0 matches within tolerance)
    unmatched = [p for p in pct_info if p['match_count'] == 0]
    
    if len(unmatched) == 1:
        # Exactly one unmatched - it's the error
        return unmatched[0]['metric']
    elif len(unmatched) == 0 or len(unmatched) >= 2:
        # All match some pair OR multiple unmatched
        # Use closest-match approach: error has largest min_diff
        pct_info.sort(key=lambda x: -x['min_diff'])
        
        # Check if there's a clear gap between the top candidate and the rest
        if len(pct_info) >= 2:
            gap = pct_info[0]['min_diff'] - pct_info[1]['min_diff']
            if gap > 0.3:  # Clear gap
                return pct_info[0]['metric']
        
        # No clear gap - ambiguous, but return the best candidate
        return pct_info[0]['metric']
    
    return None


# ============================================================================
# MAIN VERIFICATION
# ============================================================================

def verify_report(metrics):
    """Run all templates, return (root_cause_metric, failures, matched_count)."""
    failures = []
    total_matched = 0

    for t in TEMPLATES:
        matched, involved, fail_line, fail_metric, reported, calculated = check_template(t, metrics)
        if matched:
            total_matched += 1
            if fail_line is not None:
                failures.append((involved, fail_line, fail_metric, reported, calculated))

    if not failures:
        return None, [], total_matched

    root = find_root_cause(metrics, failures)
    return root, failures, total_matched


def format_value(metric):
    """Format metric value for output (remove % sign, preserve original format)."""
    raw = metric['raw']
    v = raw.replace('%', '').replace('$', '').replace(',', '').strip()
    if v.startswith('(') and v.endswith(')'):
        v = '-' + v[1:-1]
    return v


def main():
    html_file = sys.argv[1] if len(sys.argv) > 1 else '/app/q2_earnings_report.html'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '/app/value.txt'

    with open(html_file, 'r') as f:
        parser = FinancialTableParser()
        parser.feed(f.read())
    metrics = parser.metrics

    print(f"Extracted {len(metrics)} metrics")
    for m in metrics:
        print(f"  Line {m['line']}: {m['name']} = {m['raw']}")

    # Try template-based verification first
    root, failures, matched = verify_report(metrics)

    print(f"\nMatched {matched} templates, {len(failures)} failure(s)")

    if root:
        for involved, fail_line, fail_metric, reported, calculated in failures:
            print(f"  FAIL: line {fail_line} ({fail_metric['name']}): "
                  f"reported={reported}, calculated={calculated:.2f}")

        value_str = format_value(root)
        answer = f"{root['line']},{value_str}"
        with open(output_file, 'w') as f:
            f.write(answer)
        print(f"\nRoot cause: Line {root['line']} ({root['name']})")
        print(f"Answer: {answer}")
    else:
        # Templates found nothing — fall back to robust brute-force
        print("\nTemplates found no errors. Trying robust brute-force percentage check...")
        error_pct = brute_force_percentage_check_robust(metrics)
        
        if error_pct:
            value_str = format_value(error_pct)
            answer = f"{error_pct['line']},{value_str}"
            with open(output_file, 'w') as f:
                f.write(answer)
            print(f"Brute-force found: Line {error_pct['line']} ({error_pct['name']})")
            print(f"Answer: {answer}")
        else:
            print("No errors found via templates or brute-force.")
            sys.exit(1)


if __name__ == '__main__':
    main()
