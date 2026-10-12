#!/usr/bin/env python3
"""
HTML Financial Report Verifier

Identifies the single incorrect metric by checking financial identities.
Usage: python verify_report.py [--debug] <input.html> <output.txt>
"""

from html.parser import HTMLParser
import re
import sys
from collections import Counter
from typing import List, Dict, Tuple, Optional, Callable, Set


# =============================================================================
# CONFIGURATION
# =============================================================================

# ORDER MATTERS: more specific patterns first to avoid greedy matching
SYNONYMS: List[Tuple[str, List[str]]] = [
    ('cost_of_revenue', ['cost of revenue', 'cogs', 'cost of goods sold', 'cost of sales']),
    ('rd', ['research and development', 'r&d', 'rnd', 'research & development']),
    ('sm', ['sales and marketing', 's&m', 'marketing and sales']),
    ('ga', ['general and administrative', 'g&a', 'general & administrative']),
    ('total_opex', ['total operating expenses', 'total opex', 'operating expenses']),
    ('operating_income', ['operating income', 'operating profit', 'income from operations', 'ebit']),
    ('other_income', ['other income', 'other income net', 'other expenses net']),
    ('net_income', ['net income', 'net earnings', 'net profit', 'bottom line']),
    ('gross_profit', ['gross profit', 'gross income']),
    ('revenue', ['revenue', 'revenues', 'net sales', 'total revenue']),
    ('gross_margin', ['gross margin', 'gross margin %']),
    ('operating_margin', ['operating margin', 'operating margin %']),
    ('net_margin', ['net margin', 'profit margin', 'net profit margin']),
]


# =============================================================================
# PARSING: Content-based, with multi-column guard
# =============================================================================

class FinancialReportParser(HTMLParser):
    """Parse HTML financial tables. Multi-column tables filtered to single column."""
    
    def __init__(self):
        super().__init__()
        self.metrics: List[Dict] = []
        self._current_row: List[str] = []
        self._cell_buffer: List[str] = []
        self._in_row = False
        self._in_cell = False
        self._in_thead = False
        self._headers: List[str] = []
        self._multi_column_warned = False
        
    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str]]):
        if tag == 'thead':
            self._in_thead = True
        elif tag == 'tr':
            self._in_row = True
            self._current_row = []
        elif tag in ('td', 'th'):
            self._in_cell = True
            self._cell_buffer = []
            
    def handle_endtag(self, tag: str):
        if tag in ('td', 'th'):
            text = ''.join(self._cell_buffer).strip()
            self._current_row.append(text)
            self._in_cell = False
        elif tag == 'tr' and self._in_row:
            if self._in_thead:
                self._headers = self._current_row
            else:
                self._process_row()
            self._in_row = False
        elif tag == 'thead':
            self._in_thead = False
            
    def handle_data(self, data: str):
        if self._in_cell:
            self._cell_buffer.append(data)
    
    def _process_row(self):
        """Extract line, name, and values from row."""
        if len(self._current_row) < 3:
            return
        
        # Validate: first cell should be line number, second should be name
        line_str = self._current_row[0]
        metric_name = self._current_row[1]
        value_cells = self._current_row[2:]
        
        # Fallback: if first cell isn't a line number, try content classification
        if not line_str.isdigit():
            # Try to find line number and name by content
            line_num = None
            name = None
            values = []
            for cell in self._current_row:
                if line_num is None and cell.isdigit():
                    line_num = int(cell)
                elif re.search(r'[a-zA-Z]', cell) and not re.match(r'^[\$\d\.,%\(\)]+$', cell):
                    if name is None or len(cell) > len(name):
                        name = cell
                elif re.search(r'\d', cell):
                    values.append(cell)
            if line_num is None or name is None:
                return
            line_str = str(line_num)
            metric_name = name
            value_cells = values
        
        line_num = int(line_str)
        
        # Multi-column guard: if multiple value columns, warn and use first only
        if len(value_cells) > 1 and not self._multi_column_warned:
            print("WARNING: Multi-period table detected. Using first value column only.")
            print("         Full multi-column support not yet implemented.")
            self._multi_column_warned = True
        
        # Use only first value column for now (until full multi-column support)
        if not value_cells:
            return
        raw_value = value_cells[0]
        
        if not re.search(r'\d', raw_value):
            return
        
        # Parse numeric value
        clean = re.sub(r'[$,%]', '', raw_value)
        if clean.startswith('(') and clean.endswith(')'):
            clean = '-' + clean[1:-1]
        
        try:
            value = float(clean)
        except ValueError:
            return
        
        # Normalize metric name
        canonical = self._normalize(metric_name, raw_value)
        
        self.metrics.append({
            'line': line_num,
            'name': metric_name,
            'canonical': canonical,
            'column': 'Value',
            'value': value,
            'raw': raw_value
        })
    
    def _normalize(self, name: str, raw_value: str) -> Optional[str]:
        """Normalize metric name to canonical form."""
        name_lower = name.lower()
        has_percent = '%' in raw_value
        
        for canonical, variants in SYNONYMS:
            for variant in variants:
                if variant in name_lower:
                    if canonical == 'gross_margin' and not has_percent:
                        continue
                    if canonical == 'gross_profit' and has_percent:
                        continue
                    return canonical
        return None


# =============================================================================
# IDENTITY CHECKS
# =============================================================================

def get_display_precision(raw_value: str) -> int:
    """Count decimal places in displayed value."""
    clean = re.sub(r'[$,%\s()]', '', raw_value.strip())
    if '.' not in clean:
        return 0
    return len(clean.split('.')[-1])


def check_subtractive(result: str, minuend: str, subtrahend: str):
    """Check: result = minuend - subtrahend"""
    def check(get: Callable, raws: Dict[str, str]) -> Tuple[float, float]:
        r, m, s = get(result), get(minuend), get(subtrahend)
        if r is None or m is None or s is None:
            return (0.0, 1.0)
        
        d = get_display_precision(raws.get(result, ''))
        unit = 10 ** (-d) if d > 0 else 1.0
        tolerance = 0.5 * unit * 2 * 1.2
        
        return (abs(r - (m - s)), tolerance)
    return check


def check_additive(result: str, *components: str):
    """Check: result = sum(components)"""
    def check(get: Callable, raws: Dict[str, str]) -> Tuple[float, float]:
        r = get(result)
        c = [get(x) for x in components]
        if r is None or None in c:
            return (0.0, 1.0)
        
        d = get_display_precision(raws.get(result, ''))
        unit = 10 ** (-d) if d > 0 else 1.0
        n_terms = len(components) + 1
        tolerance = 0.5 * unit * n_terms * 1.2
        
        return (abs(r - sum(c)), tolerance)
    return check


def check_margin(margin_name: str, profit_name: str, revenue_name: str = 'revenue'):
    """Check: margin = (profit / revenue) * 100"""
    def check(get: Callable, raws: Dict[str, str]) -> Tuple[float, float]:
        m, p, r = get(margin_name), get(profit_name), get(revenue_name)
        if m is None or p is None or r is None:
            return (0.0, 1.0)
        
        d = get_display_precision(raws.get(margin_name, ''))
        unit = 10 ** (-d) if d > 0 else 1.0
        tolerance = 0.6 * unit
        
        expected = round((p / r) * 100, d)
        return (abs(m - expected), tolerance)
    return check


def build_identities() -> List[Tuple[Tuple[str, ...], Callable]]:
    """Build standard income statement identity checks."""
    return [
        (('revenue', 'cost_of_revenue', 'gross_profit'),
         check_subtractive('gross_profit', 'revenue', 'cost_of_revenue')),
        (('gross_profit', 'total_opex', 'operating_income'),
         check_subtractive('operating_income', 'gross_profit', 'total_opex')),
        (('rd', 'sm', 'ga', 'total_opex'),
         check_additive('total_opex', 'rd', 'sm', 'ga')),
        (('operating_income', 'other_income', 'net_income'),
         check_additive('net_income', 'operating_income', 'other_income')),
        (('gross_profit', 'revenue', 'gross_margin'),
         check_margin('gross_margin', 'gross_profit')),
        (('operating_income', 'revenue', 'operating_margin'),
         check_margin('operating_margin', 'operating_income')),
        (('net_income', 'revenue', 'net_margin'),
         check_margin('net_margin', 'net_income')),
    ]


# =============================================================================
# BLAME INTERSECTION
# =============================================================================

def find_culprit(metrics: List[Dict], identities: List[Tuple[Tuple[str, ...], Callable]], 
                 debug: bool = False) -> Optional[Dict]:
    """Find incorrect metric using identity-based blame intersection."""
    by_canonical: Dict[str, Dict] = {}
    for m in metrics:
        if m['canonical']:
            by_canonical[m['canonical']] = m
    
    def get(canonical: str) -> Optional[float]:
        return by_canonical.get(canonical, {}).get('value')
    
    def get_raw(canonical: str) -> str:
        return by_canonical.get(canonical, {}).get('raw', '')
    
    raws = {c: m['raw'] for c, m in by_canonical.items()}
    
    failed: List[Dict] = []
    passed: List[Dict] = []
    
    for participants, check_fn in identities:
        if not all(get(p) is not None for p in participants):
            continue
        
        disc, tol = check_fn(get, raws)
        
        if disc > tol:
            failed.append({'participants': set(participants), 'discrepancy': disc, 'tolerance': tol})
        else:
            passed.append({'participants': set(participants)})
    
    if debug:
        print("=== Parsed Metrics ===")
        for c, m in sorted(by_canonical.items()):
            print(f"  {c}: line={m['line']}, value={m['value']}, raw={m['raw']}")
        print("\n=== Identity Checks ===")
        for f in failed:
            print(f"  FAIL: {f['participants']} disc={f['discrepancy']:.3f} tol={f['tolerance']:.3f}")
        for p in passed:
            print(f"  PASS: {p['participants']}")
    
    if not failed:
        return None
    
    intersection = set.intersection(*[f['participants'] for f in failed])
    
    passed_metrics: Set[str] = set()
    for p in passed:
        passed_metrics.update(p['participants'])
    
    candidates = intersection - passed_metrics
    
    if debug:
        print(f"\n  Intersection: {intersection}")
        print(f"  Passed metrics: {passed_metrics}")
        print(f"  Candidates: {candidates}")
    
    if len(candidates) == 1:
        return by_canonical.get(candidates.pop())
    
    failed_counts = Counter([p for f in failed for p in f['participants']])
    passed_counts = Counter([p for p in passed_metrics])
    
    all_metrics = set(failed_counts.keys()) | set(passed_counts.keys())
    scores: Dict[str, float] = {}
    for m in all_metrics:
        scores[m] = failed_counts.get(m, 0) - passed_counts.get(m, 0)
    
    for m in intersection:
        scores[m] = scores.get(m, 0) + 10
    
    if debug:
        print(f"\n  Scores: {scores}")
    
    if scores:
        best = max(scores, key=scores.get)
        return by_canonical.get(best)
    
    return None


def format_output(raw_value: str) -> str:
    """Preserve display format, strip only forbidden symbols."""
    result = raw_value.strip()
    result = re.sub(r'[$,%]', '', result)
    
    if result.startswith('(') and result.endswith(')'):
        result = '-' + result[1:-1]
    
    return result.strip()


def verify_report(input_path: str, output_path: str, debug: bool = False) -> Tuple[int, str]:
    """Main verification workflow."""
    parser = FinancialReportParser()
    with open(input_path, 'r') as f:
        parser.feed(f.read())
    
    if not parser.metrics:
        raise ValueError("No metrics found")
    
    if debug:
        print(f"Parsed {len(parser.metrics)} metrics")
    
    identities = build_identities()
    culprit = find_culprit(parser.metrics, identities, debug=debug)
    
    if not culprit:
        if debug:
            raise ValueError("No incorrect metric found (see debug output above)")
        else:
            raise ValueError("No incorrect metric found (run with --debug for details)")
    
    output_value = format_output(culprit['raw'])
    
    with open(output_path, 'w') as f:
        f.write(f"{culprit['line']},{output_value}")
    
    return culprit['line'], output_value


if __name__ == '__main__':
    debug = '--debug' in sys.argv
    if debug:
        sys.argv.remove('--debug')
    
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} [--debug] <input_html> <output_file>")
        sys.exit(1)
    
    try:
        line, val = verify_report(sys.argv[1], sys.argv[2], debug=debug)
        print(f"Found incorrect metric: line {line}, value {val}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
