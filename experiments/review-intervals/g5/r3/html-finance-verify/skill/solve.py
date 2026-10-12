#!/usr/bin/env python3
"""
HTML Finance Verify - Reference solver with cascading error resolution.

Usage:
    python3 solve.py                          # defaults: /app/q2_earnings_report.html -> /app/value.txt
    python3 solve.py --html FILE --output FILE  # custom paths

The solver:
1. Parses HTML to extract line-numbered metrics (dollar values and KPI percentages)
2. Checks dollar arithmetic relationships (GP = Rev - COGS, OpEx sum, OI = GP - OpEx, NI)
3. Checks KPI ratios against dollar values (margins, component ratios, balance sheet ratios)
4. Uses brute-force fallback for unknown KPI names (try all dollar items / revenue)
5. Resolves cascading errors via "max checkable relationships" tiebreaker
6. Writes line_number,value to output file
"""
import re, sys, os
from html.parser import HTMLParser


class FinancialHTMLParser(HTMLParser):
    """Parse financial HTML to extract line-numbered metric rows."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row_cells = []
        self.current_cell_data = ""
        self.in_td = False
        self.in_thead = False
        self.in_row = False
        self.notes = []
        self.in_note = False
        self.note_data = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get('class', '')
        if tag == 'thead':
            self.in_thead = True
        elif tag == 'tr':
            if not self.in_thead:
                self.in_row = True
                self.current_row_cells = []
        elif tag in ('td', 'th') and not self.in_thead:
            self.in_td = True
            self.current_cell_data = ""
        elif tag == 'p' and 'note' in cls:
            self.in_note = True
            self.note_data = ""

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.in_td:
            self.in_td = False
            self.current_row_cells.append(self.current_cell_data.strip())
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            if len(self.current_row_cells) >= 3:
                row = self._try_extract_row(self.current_row_cells)
                if row:
                    self.rows.append(row)
            self.current_row_cells = []
        elif tag == 'thead':
            self.in_thead = False
        elif tag == 'p' and self.in_note:
            self.in_note = False
            self.notes.append(self.note_data.strip())

    def handle_data(self, data):
        if self.in_td:
            self.current_cell_data += data
        if self.in_note:
            self.note_data += data

    def _try_extract_row(self, cells):
        """Identify line number, metric name, and value from table cells.

        Strategy: find the cell that looks like a line number (pure integer),
        the cell that looks like a value (contains $ or %), and treat the
        remaining cell(s) as the metric name.
        """
        line_idx = None
        value_idx = None
        for i, cell in enumerate(cells):
            if re.match(r'^\d{1,4}$', cell.strip()):
                if line_idx is None:
                    line_idx = i
            if '$' in cell or '%' in cell:
                if value_idx is None:
                    value_idx = i
        if line_idx is not None and value_idx is not None and line_idx != value_idx:
            metric_cells = [c for j, c in enumerate(cells)
                            if j != line_idx and j != value_idx]
            metric_name = ' '.join(metric_cells).strip()
            return {
                'line': cells[line_idx].strip(),
                'metric': metric_name,
                'value': cells[value_idx].strip()
            }
        return None


def parse_number(s):
    """Parse numeric string handling $, %, commas, parentheses for negatives."""
    s = s.strip()
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    if s.startswith('-'):
        negative = True
        s = s[1:]
    s = s.replace('$', '').replace('%', '').replace(',', '').replace(' ', '')
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def is_percentage(v):
    return '%' in v


def is_dollar(v):
    return '$' in v


def normalize(n):
    return re.sub(r'\s+', ' ', n.lower().strip())


def name_matches(name, patterns):
    n = normalize(name)
    return any(p in n for p in patterns)


# Canonical name -> list of alias patterns for matching
ITEM_ALIASES = {
    'revenue': ['revenue', 'net revenue', 'total revenue', 'net sales', 'sales'],
    'cogs': ['cost of revenue', 'cost of goods sold', 'cogs', 'cost of sales'],
    'gross_profit': ['gross profit'],
    'rd': ['research and development', 'research & development', 'r&d', 'r d'],
    'sm': ['sales and marketing', 'sales & marketing', 's&m'],
    'ga': ['general and administrative', 'general & administrative', 'g&a'],
    'total_opex': ['total operating expense', 'operating expenses'],
    'operating_income': ['operating income', 'operating earnings', 'ebit',
                         'income from operations'],
    'other_income': ['other income', 'non-operating income', 'other expense'],
    'tax': ['income tax', 'provision for income', 'tax expense'],
    'net_income': ['net income', 'net earnings', 'net profit'],
    'ebitda': ['ebitda'],
    'fcf': ['free cash flow'],
    'current_assets': ['current assets', 'total current assets'],
    'current_liabilities': ['current liabilities', 'total current liabilities'],
    'total_debt': ['total debt'],
    'total_equity': ['total equity', "stockholders' equity",
                     "shareholders' equity"],
    'shares': ['shares outstanding', 'diluted shares',
               'weighted average shares'],
}

# KPI name patterns that indicate "as % of revenue"
# These are component names that when found in a KPI label, imply component/revenue*100
COMPONENT_KPI_PATTERNS = {
    'rd': ['research', 'r&d', 'r d', 'research intensity', 'research ratio'],
    'sm': ['sales and marketing', 'sales & marketing', 's&m', 'marketing'],
    'ga': ['general and administrative', 'general & administrative', 'g&a'],
    'total_opex': ['operating expense', 'opex'],
    'cogs': ['cost of revenue', 'cogs', 'cost of goods sold', 'cost ratio'],
}


def find_value(dollar_items, canonical):
    """Find numeric value for a canonical item name."""
    patterns = ITEM_ALIASES.get(canonical, [canonical])
    for item in dollar_items:
        if name_matches(item['metric'], patterns):
            return item['numeric']
    return None


def try_compute_kpi(kpi_name, dollar_items, precision):
    """
    Try to compute what a KPI percentage should be.
    Returns (expected_value, True) if a known formula matches,
    or (expected_value, False) if found via brute-force fallback.
    Returns (None, False) if nothing matches.
    """
    name = normalize(kpi_name)
    revenue = find_value(dollar_items, 'revenue')

    if revenue and revenue != 0:
        # Known margin KPIs
        if name_matches(name, ['gross margin', 'gross profit margin']):
            v = find_value(dollar_items, 'gross_profit')
            if v is not None:
                return v / revenue * 100, True
        if name_matches(name, ['operating margin', 'op margin',
                                'operating income margin']):
            v = find_value(dollar_items, 'operating_income')
            if v is not None:
                return v / revenue * 100, True
        if name_matches(name, ['net margin', 'net profit margin',
                                'net income margin']):
            v = find_value(dollar_items, 'net_income')
            if v is not None:
                return v / revenue * 100, True
        if name_matches(name, ['ebitda margin']):
            v = find_value(dollar_items, 'ebitda')
            if v is not None:
                return v / revenue * 100, True
        if name_matches(name, ['free cash flow margin', 'fcf margin']):
            v = find_value(dollar_items, 'fcf')
            if v is not None:
                return v / revenue * 100, True

        # Component-as-%-of-revenue KPIs (relaxed matching)
        for canonical, patterns in COMPONENT_KPI_PATTERNS.items():
            if name_matches(name, patterns):
                v = find_value(dollar_items, canonical)
                if v is not None:
                    return v / revenue * 100, True

        # Brute-force fallback: try all dollar items as numerator / revenue
        for canonical in ITEM_ALIASES.keys():
            if canonical in ('current_assets', 'current_liabilities',
                             'total_debt', 'total_equity', 'shares'):
                continue  # balance sheet items not typically /revenue
            v = find_value(dollar_items, canonical)
            if v is not None and v != 0:
                ratio = v / revenue * 100
                if abs(round(ratio, precision) -
                       round(find_value(dollar_items, canonical) or 0,
                             precision)) > 100:
                    # Skip if the ratio is wildly different from the value
                    pass
                displayed = None
                # We need the displayed value to compare - caller handles this
                return ratio, False  # found via brute force

    # Balance-sheet ratios
    if name_matches(name, ['current ratio']):
        ca = find_value(dollar_items, 'current_assets')
        cl = find_value(dollar_items, 'current_liabilities')
        if ca is not None and cl is not None and cl != 0:
            return ca / cl, True

    if name_matches(name, ['debt']) and name_matches(name, ['equity']):
        d = find_value(dollar_items, 'total_debt')
        e = find_value(dollar_items, 'total_equity')
        if d is not None and e is not None and e != 0:
            return d / e, True

    # Per-share values
    if name_matches(name, ['eps', 'earnings per share']):
        ni = find_value(dollar_items, 'net_income')
        sh = find_value(dollar_items, 'shares')
        if ni is not None and sh is not None and sh != 0:
            return ni / sh, True

    return None, False


def check_all_relationships(dollar_items, kpi_items, precision,
                            exclude_line=None):
    """
    Check all arithmetic relationships, optionally excluding one line.
    Returns (num_mismatches, num_checked).
    """
    mismatches = 0
    checked = 0

    active_dollars = [d for d in dollar_items if d['line'] != exclude_line]
    active_kpis = [k for k in kpi_items if k['line'] != exclude_line]

    def get_active(canonical):
        return find_value(active_dollars, canonical)

    # --- Dollar relationships ---

    rev = get_active('revenue')
    cogs = get_active('cogs')
    gp = get_active('gross_profit')
    if rev is not None and cogs is not None and gp is not None:
        checked += 1
        if abs((rev - cogs) - gp) > 0.05:
            mismatches += 1

    opex_parts = [get_active(c) for c in ['rd', 'sm', 'ga']
                  if get_active(c) is not None]
    total_opex = get_active('total_opex')
    if opex_parts and total_opex is not None:
        checked += 1
        if abs(sum(opex_parts) - total_opex) > 0.05:
            mismatches += 1

    oi = get_active('operating_income')
    if gp is not None and total_opex is not None and oi is not None:
        checked += 1
        if abs((gp - total_opex) - oi) > 0.05:
            mismatches += 1

    ni = get_active('net_income')
    other = get_active('other_income')
    tax = get_active('tax')
    if oi is not None and ni is not None:
        if other is not None and tax is not None:
            checked += 1
            if abs((oi + other - tax) - ni) > 0.05:
                mismatches += 1
        elif other is not None:
            checked += 1
            if abs((oi + other) - ni) > 0.05:
                mismatches += 1

    # --- KPI relationships ---

    for kpi in active_kpis:
        name = normalize(kpi['metric'])
        revenue = get_active('revenue')
        displayed = round(kpi['numeric'], precision)

        expected = None

        if revenue and revenue != 0:
            # Known margin KPIs
            if name_matches(name, ['gross margin', 'gross profit margin']):
                v = get_active('gross_profit')
                if v is not None:
                    expected = v / revenue * 100
            elif name_matches(name, ['operating margin', 'op margin',
                                      'operating income margin']):
                v = get_active('operating_income')
                if v is not None:
                    expected = v / revenue * 100
            elif name_matches(name, ['net margin', 'net profit margin',
                                      'net income margin']):
                v = get_active('net_income')
                if v is not None:
                    expected = v / revenue * 100
            elif name_matches(name, ['ebitda margin']):
                v = get_active('ebitda')
                if v is not None:
                    expected = v / revenue * 100
            elif name_matches(name, ['free cash flow margin', 'fcf margin']):
                v = get_active('fcf')
                if v is not None:
                    expected = v / revenue * 100
            else:
                # Component-as-%-of-revenue (relaxed matching)
                matched = False
                for canonical, patterns in COMPONENT_KPI_PATTERNS.items():
                    if name_matches(name, patterns):
                        v = get_active(canonical)
                        if v is not None:
                            expected = v / revenue * 100
                            matched = True
                            break

                if not matched:
                    # Brute-force fallback: try each dollar item / revenue
                    for canonical in ITEM_ALIASES.keys():
                        if canonical in ('current_assets',
                                         'current_liabilities',
                                         'total_debt', 'total_equity',
                                         'shares'):
                            continue
                        v = get_active(canonical)
                        if v is not None and v != 0:
                            ratio = v / revenue * 100
                            if abs(round(ratio, precision) -
                                   displayed) < 0.01:
                                expected = ratio
                                break

        # Balance-sheet ratios
        if expected is None and name_matches(name, ['current ratio']):
            ca = get_active('current_assets')
            cl = get_active('current_liabilities')
            if ca is not None and cl is not None and cl != 0:
                expected = ca / cl

        if expected is None and name_matches(name, ['debt']) and \
                name_matches(name, ['equity']):
            d = get_active('total_debt')
            e = get_active('total_equity')
            if d is not None and e is not None and e != 0:
                expected = d / e

        # Per-share values
        if expected is None and name_matches(name, ['eps',
                                                      'earnings per share']):
            ni_v = get_active('net_income')
            sh = get_active('shares')
            if ni_v is not None and sh is not None and sh != 0:
                expected = ni_v / sh

        if expected is not None:
            checked += 1
            if abs(round(expected, precision) - displayed) > 0.001:
                mismatches += 1

    return mismatches, checked


def determine_precision(html_content, kpi_items, parser_notes):
    """Determine rounding precision from HTML notes or displayed values."""
    for note in parser_notes:
        m = re.search(r'rounded to (\d+) decimal', note, re.IGNORECASE)
        if m:
            return int(m.group(1))
    m = re.search(r'rounded to (\d+) decimal', html_content, re.IGNORECASE)
    if m:
        return int(m.group(1))
    for kpi in kpi_items:
        v = kpi['value'].replace('%', '').strip()
        if '.' in v:
            return len(v.split('.')[1])
    return 1


def find_root_cause(dollar_items, kpi_items, precision):
    """
    Cascading error resolution: try each item as the single-error hypothesis.

    For each candidate, remove it and check all remaining relationships.
    The correct error leaves zero mismatches AND maximizes checkable
    relationships.
    """
    all_items = dollar_items + kpi_items
    best_candidate = None
    best_checked = -1

    for candidate in all_items:
        mismatches, checked = check_all_relationships(
            dollar_items, kpi_items, precision,
            exclude_line=candidate['line']
        )
        if mismatches == 0 and checked > best_checked:
            best_candidate = candidate
            best_checked = checked

    return best_candidate


def main():
    html_file = '/app/q2_earnings_report.html'
    output_file = '/app/value.txt'
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--html' and i + 1 < len(args):
            html_file = args[i + 1]
            i += 2
        elif args[i] == '--output' and i + 1 < len(args):
            output_file = args[i + 1]
            i += 2
        else:
            i += 1

    with open(html_file, 'r') as f:
        html_content = f.read()
    parser = FinancialHTMLParser()
    parser.feed(html_content)

    dollar_items = []
    kpi_items = []
    for row in parser.rows:
        numeric = parse_number(row['value'])
        if numeric is None:
            continue
        row['numeric'] = numeric
        if is_percentage(row['value']):
            kpi_items.append(row)
        elif is_dollar(row['value']):
            dollar_items.append(row)

    precision = determine_precision(html_content, kpi_items, parser.notes)

    error = find_root_cause(dollar_items, kpi_items, precision)

    if error is None:
        print("ERROR: Could not find root cause!")
        sys.exit(1)

    error_val = error['value'].replace('%', '').replace('$', '').replace(
        ',', '').strip()
    if error_val.startswith('(') and error_val.endswith(')'):
        error_val = error_val[1:-1]

    output = f"{error['line']},{error_val}"
    with open(output_file, 'w') as f:
        f.write(output)
    print(f"Output: {output}")


if __name__ == '__main__':
    main()
