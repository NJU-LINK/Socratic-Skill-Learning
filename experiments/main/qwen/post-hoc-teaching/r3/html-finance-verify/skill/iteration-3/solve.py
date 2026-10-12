#!/usr/bin/env python3
"""
HTML Financial Verification Solver v5
Parses HTML earnings reports, checks internal financial consistency,
and identifies the single incorrect metric.

Upgrades over v4:
- Structural relationship discovery (position-based, name-independent)
- Duplicate line number handling
- Exhaustive fallback search
- Balance sheet and cash flow pattern support

Usage: python3 solve.py [html_file] [output_file]
  html_file:   Path to HTML report (default: /app/q2_earnings_report.html)
  output_file: Path to write answer (default: /app/value.txt)
"""

import re
import sys
import os
from html.parser import HTMLParser
from itertools import combinations


class TableParser(HTMLParser):
    """Parse HTML tables to extract structured data."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = None
        self.current_row = None
        self.in_table = False
        self.in_thead = False
        self.in_row = False
        self.in_cell = False
        self.cell_data = ""
        self.cell_tag = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
            self.current_table = {'header': [], 'body': []}
        elif tag == 'thead':
            self.in_thead = True
        elif tag == 'tr' and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ('td', 'th') and self.in_row:
            self.in_cell = True
            self.cell_data = ""
            self.cell_tag = tag

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.in_cell:
            self.in_cell = False
            if self.current_row is not None:
                self.current_row.append(self.cell_data.strip())
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            if self.current_table is not None and self.current_row:
                if self.in_thead:
                    self.current_table['header'].append(self.current_row)
                else:
                    self.current_table['body'].append(self.current_row)
            self.current_row = None
        elif tag == 'thead':
            self.in_thead = False
        elif tag == 'table' and self.in_table:
            self.in_table = False
            self.tables.append(self.current_table)
            self.current_table = None

    def handle_data(self, data):
        if self.in_cell:
            self.cell_data += data


def parse_html(html_content):
    parser = TableParser()
    parser.feed(html_content)
    return parser.tables


def extract_numeric(value_str):
    """Extract numeric value from string like '$842.0', '60.8%', '$1,234.5', '(50.0)'."""
    s = value_str.strip()
    if not s or s in ('—', '-', 'N/A', '–'):
        return None
    is_negative = False
    if s.startswith('(') and s.endswith(')'):
        is_negative = True
        s = s[1:-1]
    s = re.sub(r'[$€£¥,]', '', s).replace('%', '').strip()
    try:
        val = float(s)
        return -val if is_negative else val
    except ValueError:
        return None


def extract_metrics_from_tables(tables):
    """Extract metrics from parsed tables. Returns list of metric dicts."""
    metrics = []
    for table in tables:
        all_rows = table.get('header', []) + table.get('body', [])
        for row in all_rows:
            line_num = None
            metric_name = None
            value = None
            raw_value = None
            is_percentage = False

            for cell_text in row:
                if not cell_text:
                    continue
                cell_text = cell_text.strip()

                # Line number: pure integer
                if re.match(r'^\d+$', cell_text) and line_num is None:
                    line_num = int(cell_text)
                    continue

                # Numeric value detection
                has_currency = bool(re.search(r'[$€£¥]', cell_text))
                has_percent = '%' in cell_text
                is_numeric_str = bool(re.match(
                    r'^[$€£¥]?\s*-?\(?\d[\d,]*\.?\d*\)?%?\s*$', cell_text))

                if is_numeric_str or (has_currency and extract_numeric(cell_text) is not None):
                    num = extract_numeric(cell_text)
                    if num is not None:
                        value = num
                        raw_value = cell_text
                        is_percentage = has_percent
                        continue

                # Metric name
                if cell_text and not re.match(r'^-?[\d.,]+$', cell_text.replace(',', '')):
                    if metric_name is None:
                        metric_name = cell_text

            if line_num is not None and value is not None:
                metrics.append({
                    'line': line_num,
                    'name': metric_name or '',
                    'value': value,
                    'raw_value': raw_value or str(value),
                    'is_percentage': is_percentage
                })
    return metrics


def classify_metric(name, is_percentage):
    """Classify metric by name. More specific patterns checked first."""
    n = name.lower().strip()

    if is_percentage:
        if any(p in n for p in ['gross margin', 'gross profit margin']):
            return 'margin_gross'
        if any(p in n for p in ['operating margin', 'op margin']):
            return 'margin_operating'
        if any(p in n for p in ['net margin', 'net profit margin', 'profit margin']):
            return 'margin_net'
        if 'ebitda margin' in n:
            return 'margin_ebitda'
        if any(p in n for p in ['fcf margin', 'free cash flow margin']):
            return 'margin_fcf'
        if any(p in n for p in ['change', 'growth', 'y/y', 'yoy', 'year-over-year']):
            return 'yoy_change'
        return 'percentage_other'

    # Dollar metrics - specific before general
    if any(p in n for p in ['cost of revenue', 'cost of goods sold', 'cogs',
                             'cost of sales', 'cost of goods']):
        return 'cost_of_revenue'
    if any(p in n for p in ['research and development', 'r&d', 'r & d']):
        return 'opex_rd'
    if any(p in n for p in ['sales and marketing', 'selling and marketing',
                             'selling & marketing']):
        return 'opex_sm'
    if any(p in n for p in ['general and administrative', 'g&a', 'g & a']):
        return 'opex_ga'
    if any(p in n for p in ['depreciation and amortization', 'd&a']):
        return 'opex_da_combined'
    if 'depreciation' in n and 'amortization' not in n:
        return 'opex_depreciation'
    if 'amortization' in n and 'depreciation' not in n:
        return 'opex_amortization'
    if any(p in n for p in ['total operating expenses', 'total operating costs',
                             'total opex', 'total operating cost']):
        return 'total_opex'
    if any(p in n for p in ['operating income', 'operating earnings',
                             'operating profit']):
        if 'margin' not in n:
            return 'operating_income'
    if 'ebitda' in n and 'margin' not in n:
        return 'ebitda'
    if 'ebit' in n and 'margin' not in n:
        return 'operating_income'
    if 'interest income' in n:
        return 'interest_income'
    if 'interest expense' in n:
        return 'interest_expense'
    if 'other income' in n:
        return 'other_income'
    if 'other expense' in n:
        return 'other_expense'
    if any(p in n for p in ['pretax', 'pre-tax', 'income before tax',
                             'earnings before tax']):
        return 'pretax_income'
    if any(p in n for p in ['income tax', 'tax expense', 'provision for tax',
                             'tax provision']):
        return 'income_tax'
    if any(p in n for p in ['net income', 'net earnings', 'net loss',
                             'net profit', 'profit for']):
        if 'margin' not in n:
            return 'net_income'
    if any(p in n for p in ['earnings per share', 'eps']):
        return 'eps_diluted' if 'diluted' in n else 'eps_basic'
    if any(p in n for p in ['shares outstanding', 'shares diluted',
                             'weighted average']):
        return 'shares_diluted' if 'diluted' in n else 'shares_basic'
    if any(p in n for p in ['revenue', 'total revenue', 'net revenue',
                             'net sales', 'total sales']):
        return 'revenue'
    if n == 'sales' or (n.startswith('sales') and
                         not any(p in n for p in ['and marketing', '& marketing'])):
        return 'revenue'
    if 'gross profit' in n:
        return 'gross_profit'
    if 'total expense' in n or 'total cost' in n:
        return 'total_opex'
    if 'operating expense' in n or 'operating cost' in n:
        return 'opex_other'
    if 'restructuring' in n:
        return 'opex_restructuring'
    if 'impairment' in n:
        return 'opex_impairment'

    # Balance sheet patterns
    if any(p in n for p in ['total assets', 'total asset']):
        return 'total_assets'
    if any(p in n for p in ['current assets']):
        return 'current_assets'
    if any(p in n for p in ['total liabilities', 'total liability']):
        return 'total_liabilities'
    if any(p in n for p in ['current liabilities']):
        return 'current_liabilities'
    if any(p in n for p in ['shareholders equity', "stockholders' equity",
                             'total equity', "shareholders' equity",
                             'stockholders equity', 'total stockholders']):
        return 'total_equity'
    if any(p in n for p in ['long-term debt', 'long term debt', 'long-term borrowings']):
        return 'long_term_debt'
    if any(p in n for p in ['cash and equivalents', 'cash and cash', 'cash']):
        return 'cash'
    if any(p in n for p in ['accounts receivable', 'receivables']):
        return 'receivables'
    if any(p in n for p in ['inventory', 'inventories']):
        return 'inventory'
    if any(p in n for p in ['accounts payable', 'payables']):
        return 'payables'
    if any(p in n for p in ['retained earnings']):
        return 'retained_earnings'

    # Cash flow patterns
    if any(p in n for p in ['operating cash flow', 'cash from operations',
                             'cash flow from operations', 'net cash from operating']):
        return 'operating_cf'
    if any(p in n for p in ['investing cash flow', 'cash from investing',
                             'cash flow from investing', 'net cash from investing']):
        return 'investing_cf'
    if any(p in n for p in ['financing cash flow', 'cash from financing',
                             'cash flow from financing', 'net cash from financing']):
        return 'financing_cf'
    if any(p in n for p in ['net change in cash', 'change in cash',
                             'net increase in cash', 'net decrease in cash']):
        return 'net_change_cash'
    if any(p in n for p in ['capital expenditure', 'capex', 'capex net']):
        return 'capex'
    if any(p in n for p in ['free cash flow', 'fcf']):
        return 'free_cash_flow'

    return 'unknown'


def categorize_all_metrics(metrics):
    """Categorize all metrics into structured dict."""
    cat = {
        'revenue': None, 'cost_of_revenue': None, 'gross_profit': None,
        'opex_items': {}, 'total_opex': None, 'operating_income': None,
        'ebitda': None, 'interest_income': None, 'interest_expense': None,
        'other_income': None, 'other_expense': None, 'pretax_income': None,
        'income_tax': None, 'net_income': None, 'eps_basic': None,
        'eps_diluted': None, 'shares_basic': None, 'shares_diluted': None,
        'margins': {}, 'yoy_changes': [], 'unknown': [],
        # Balance sheet
        'total_assets': None, 'current_assets': None, 'total_liabilities': None,
        'current_liabilities': None, 'total_equity': None, 'long_term_debt': None,
        'cash': None, 'receivables': None, 'inventory': None, 'payables': None,
        'retained_earnings': None,
        # Cash flow
        'operating_cf': None, 'investing_cf': None, 'financing_cf': None,
        'net_change_cash': None, 'capex': None, 'free_cash_flow': None,
    }
    opex_map = {
        'opex_rd': 'rd', 'opex_sm': 'sm', 'opex_ga': 'ga',
        'opex_depreciation': 'depreciation', 'opex_amortization': 'amortization',
        'opex_da_combined': 'da', 'opex_restructuring': 'restructuring',
        'opex_impairment': 'impairment', 'opex_other': 'other',
    }

    for m in metrics:
        c = classify_metric(m['name'], m['is_percentage'])
        if c == 'revenue': cat['revenue'] = m
        elif c == 'cost_of_revenue': cat['cost_of_revenue'] = m
        elif c == 'gross_profit': cat['gross_profit'] = m
        elif c in opex_map: cat['opex_items'][opex_map[c]] = m
        elif c == 'total_opex': cat['total_opex'] = m
        elif c == 'operating_income': cat['operating_income'] = m
        elif c == 'ebitda': cat['ebitda'] = m
        elif c == 'interest_income': cat['interest_income'] = m
        elif c == 'interest_expense': cat['interest_expense'] = m
        elif c == 'other_income': cat['other_income'] = m
        elif c == 'other_expense': cat['other_expense'] = m
        elif c == 'pretax_income': cat['pretax_income'] = m
        elif c == 'income_tax': cat['income_tax'] = m
        elif c == 'net_income': cat['net_income'] = m
        elif c == 'eps_basic': cat['eps_basic'] = m
        elif c == 'eps_diluted': cat['eps_diluted'] = m
        elif c == 'shares_basic': cat['shares_basic'] = m
        elif c == 'shares_diluted': cat['shares_diluted'] = m
        elif c.startswith('margin_'): cat['margins'][c.split('_')[1]] = m
        elif c == 'yoy_change': cat['yoy_changes'].append(m)
        elif c in ('total_assets', 'current_assets', 'total_liabilities',
                   'current_liabilities', 'total_equity', 'long_term_debt',
                   'cash', 'receivables', 'inventory', 'payables',
                   'retained_earnings', 'operating_cf', 'investing_cf',
                   'financing_cf', 'net_change_cash', 'capex', 'free_cash_flow'):
            cat[c] = m
        else:
            cat['unknown'].append(m)
    return cat


def build_relationships(metrics, cat):
    """Build list of (type, lines_dict, description) financial relationships."""
    rels = []

    # === INCOME STATEMENT ===

    # Gross Profit = Revenue - COGS
    if cat['revenue'] and cat['cost_of_revenue'] and cat['gross_profit']:
        rels.append(('subtractive',
            {'a': cat['revenue']['line'], 'b': cat['cost_of_revenue']['line'],
             'result': cat['gross_profit']['line']},
            'Revenue - COGS = Gross Profit'))

    # Total OpEx = sum of items
    opex_items = [m for m in cat['opex_items'].values() if m]
    if cat['total_opex'] and len(opex_items) >= 2:
        rels.append(('additive',
            {'components': [m['line'] for m in opex_items],
             'total': cat['total_opex']['line']},
            'Sum of OpEx = Total OpEx'))

    # Operating Income = Gross Profit - Total OpEx
    if cat['gross_profit'] and cat['total_opex'] and cat['operating_income']:
        rels.append(('subtractive',
            {'a': cat['gross_profit']['line'], 'b': cat['total_opex']['line'],
             'result': cat['operating_income']['line']},
            'Gross Profit - Total OpEx = Operating Income'))

    # Net Income paths
    if cat['operating_income'] and cat['other_income'] and cat['net_income']:
        components = [cat['operating_income']['line'], cat['other_income']['line']]
        subtract = []
        if cat['interest_expense']:
            subtract.append(cat['interest_expense']['line'])
        if cat['income_tax'] and not cat['pretax_income']:
            subtract.append(cat['income_tax']['line'])
        rels.append(('additive',
            {'components': components, 'total': cat['net_income']['line'],
             'subtract': subtract},
            'Op Income + Other Income = Net Income'))

    # Pretax Income
    if cat['pretax_income'] and cat['operating_income']:
        components = [cat['operating_income']['line']]
        subtract = []
        if cat['other_income']:
            components.append(cat['other_income']['line'])
        if cat['interest_income']:
            components.append(cat['interest_income']['line'])
        if cat['interest_expense']:
            subtract.append(cat['interest_expense']['line'])
        rels.append(('additive',
            {'components': components, 'total': cat['pretax_income']['line'],
             'subtract': subtract},
            'Components = Pretax Income'))

    # Net Income = Pretax - Tax
    if cat['pretax_income'] and cat['income_tax'] and cat['net_income']:
        rels.append(('subtractive',
            {'a': cat['pretax_income']['line'], 'b': cat['income_tax']['line'],
             'result': cat['net_income']['line']},
            'Pretax - Tax = Net Income'))

    # EBITDA = Operating Income + D&A
    if cat['ebitda'] and cat['operating_income']:
        da = []
        for k in ['depreciation', 'amortization', 'da']:
            if cat['opex_items'].get(k):
                da.append(cat['opex_items'][k]['line'])
        if da:
            rels.append(('additive',
                {'components': [cat['operating_income']['line']] + da,
                 'total': cat['ebitda']['line']},
                'Op Income + D&A = EBITDA'))

    # Margin ratios
    if cat['revenue']:
        for mt, pm in [('gross', cat['gross_profit']),
                       ('operating', cat['operating_income']),
                       ('net', cat['net_income']),
                       ('ebitda', cat['ebitda'])]:
            if mt in cat['margins'] and pm:
                rels.append(('ratio',
                    {'numerator': pm['line'], 'denominator': cat['revenue']['line'],
                     'result': cat['margins'][mt]['line']},
                    f'{pm["name"]} / Revenue = {cat["margins"][mt]["name"]}'))

    # EPS
    if cat['net_income']:
        for et, sk in [('basic', 'shares_basic'), ('diluted', 'shares_diluted')]:
            ek = f'eps_{et}'
            if cat.get(ek) and cat.get(sk):
                rels.append(('ratio_direct',
                    {'numerator': cat['net_income']['line'],
                     'denominator': cat[sk]['line'],
                     'result': cat[ek]['line']},
                    f'Net Income / Shares = EPS ({et})'))

    # === BALANCE SHEET ===

    # Assets = Liabilities + Equity
    if cat['total_assets'] and cat['total_liabilities'] and cat['total_equity']:
        rels.append(('additive',
            {'components': [cat['total_liabilities']['line'], cat['total_equity']['line']],
             'total': cat['total_assets']['line']},
            'Liabilities + Equity = Total Assets'))

    # Current Assets components (Cash + Receivables + Inventory ≈ Current Assets)
    ca_items = [m for m in [cat['cash'], cat['receivables'], cat['inventory']] if m]
    if cat['current_assets'] and len(ca_items) >= 2:
        rels.append(('additive',
            {'components': [m['line'] for m in ca_items],
             'total': cat['current_assets']['line']},
            'Cash + Receivables + Inventory ≈ Current Assets'))

    # === CASH FLOW ===

    # Operating CF + Investing CF + Financing CF = Net Change in Cash
    cf_items = [m for m in [cat['operating_cf'], cat['investing_cf'], cat['financing_cf']] if m]
    if cat['net_change_cash'] and len(cf_items) >= 2:
        rels.append(('additive',
            {'components': [m['line'] for m in cf_items],
             'total': cat['net_change_cash']['line']},
            'Operating CF + Investing CF + Financing CF = Net Change in Cash'))

    # Free Cash Flow = Operating CF - CapEx
    if cat['free_cash_flow'] and cat['operating_cf'] and cat['capex']:
        rels.append(('subtractive',
            {'a': cat['operating_cf']['line'], 'b': cat['capex']['line'],
             'result': cat['free_cash_flow']['line']},
            'Operating CF - CapEx = Free Cash Flow'))

    # === GENERIC: find unmatched totals ===
    dollar_metrics = sorted([m for m in metrics if not m['is_percentage']],
                           key=lambda m: m['line'])
    for m in dollar_metrics:
        if 'total' in m['name'].lower():
            already = any(r[1].get('total') == m['line'] for r in rels if r[0] == 'additive')
            if already:
                continue
            candidates = [x for x in dollar_metrics
                         if x['line'] < m['line'] and x['line'] >= m['line'] - 150]
            for size in range(2, min(len(candidates) + 1, 8)):
                found = False
                for combo in combinations(candidates, size):
                    if abs(sum(x['value'] for x in combo) - m['value']) < 0.15:
                        rels.append(('additive',
                            {'components': [x['line'] for x in combo],
                             'total': m['line']},
                            f'Sum = {m["name"]}'))
                        found = True
                        break
                if found:
                    break

    # === GENERIC: unmatched percentages ===
    for pm in [m for m in metrics if m['is_percentage']]:
        already = any(r[1].get('result') == pm['line'] for r in rels
                     if r[0] in ('ratio', 'ratio_direct'))
        if already:
            continue
        for num_m in dollar_metrics:
            for den_m in dollar_metrics:
                if num_m['line'] == den_m['line'] or den_m['value'] == 0:
                    continue
                expected = round((num_m['value'] / den_m['value']) * 100, 1)
                if abs(expected - pm['value']) < 0.06:
                    rels.append(('ratio',
                        {'numerator': num_m['line'], 'denominator': den_m['line'],
                         'result': pm['line']},
                        f'{num_m["name"]} / {den_m["name"]} = {pm["name"]}'))
                    break
            else:
                continue
            break

    return rels


def discover_structural_relationships(metrics):
    """
    Fallback: discover relationships from sequential structure + numerics.
    Works independently of metric naming conventions.
    Exploits the predictable sequential layout of financial statements.
    """
    rels = []
    dollar = [m for m in metrics if not m['is_percentage']]
    pct = [m for m in metrics if m['is_percentage']]

    # For each dollar metric, check if it equals sum/difference of preceding metrics
    for i, m in enumerate(dollar):
        # Subtractive: m = dollar[j] - sum(dollar[j+1:i]) for some j < i
        for j in range(i):
            if i - j < 2:
                continue
            block_sum = sum(dollar[k]['value'] for k in range(j+1, i))
            if abs(dollar[j]['value'] - block_sum - m['value']) < 0.15:
                rels.append(('structural_subtractive', {
                    'start': dollar[j]['line'],
                    'subtrahends': [dollar[k]['line'] for k in range(j+1, i)],
                    'result': m['line']
                }, f'Structural: line {dollar[j]["line"]} - intermediate = line {m["line"]}'))

        # Additive: m = sum(dollar[j:i]) for some j < i (contiguous block)
        for j in range(max(0, i-10), i):
            if i - j < 2:
                continue
            block_sum = sum(dollar[k]['value'] for k in range(j, i))
            if abs(block_sum - m['value']) < 0.15:
                rels.append(('structural_additive', {
                    'components': [dollar[k]['line'] for k in range(j, i)],
                    'total': m['line']
                }, f'Structural: sum of lines {dollar[j]["line"]}..{dollar[i-1]["line"]} = line {m["line"]}'))

    # For each percentage, try all dollar pairs
    for pm in pct:
        for num in dollar:
            for den in dollar:
                if den['value'] == 0 or num['line'] == den['line']:
                    continue
                expected = round((num['value'] / den['value']) * 100, 1)
                if abs(expected - pm['value']) < 0.06:
                    rels.append(('structural_ratio', {
                        'numerator': num['line'],
                        'denominator': den['line'],
                        'result': pm['line']
                    }, f'Structural ratio: {num["line"]}/{den["line"]} = {pm["line"]}'))

    return rels


def build_all_relationships(metrics, cat):
    """Build relationships using both name-based and structural discovery."""
    # Name-based relationships (fast path for standard reports)
    name_rels = build_relationships(metrics, cat)

    # Structural relationships (fallback for non-standard naming)
    struct_rels = discover_structural_relationships(metrics)

    # Merge: add structural relationships that don't duplicate name-based ones
    existing_line_sets = []
    for rtype, lines, desc in name_rels:
        if rtype == 'additive':
            line_set = frozenset(
                (lines.get('components', []) +
                 lines.get('subtract', []) +
                 ([lines['total']] if lines.get('total') else [])))
        elif rtype == 'subtractive':
            line_set = frozenset([lines['a'], lines['b'], lines['result']])
        elif rtype in ('ratio', 'ratio_direct'):
            line_set = frozenset([lines['numerator'], lines['denominator'], lines['result']])
        else:
            line_set = frozenset()
        existing_line_sets.append((rtype, line_set))

    merged = list(name_rels)
    for rtype, lines, desc in struct_rels:
        if rtype == 'structural_additive':
            line_set = frozenset(
                lines.get('components', []) +
                ([lines['total']] if lines.get('total') else []))
        elif rtype == 'structural_subtractive':
            line_set = frozenset(
                [lines['start']] +
                lines.get('subtrahends', []) +
                ([lines['result']] if lines.get('result') else []))
        elif rtype == 'structural_ratio':
            line_set = frozenset([lines['numerator'], lines['denominator'], lines['result']])
        else:
            line_set = frozenset()

        # Add if not a duplicate (same type and same line set)
        is_dup = any(rt == rtype and ls == line_set for rt, ls in existing_line_sets)
        if not is_dup:
            merged.append((rtype, lines, desc))
            existing_line_sets.append((rtype, line_set))

    return merged


def check_relationships(metrics, rels, overrides=None, tolerance=0.15):
    """Check relationships with optional value overrides. Returns (passing, failing)."""
    line_to_metric = {m['line']: m for m in metrics}

    def get_val(line):
        if overrides and line in overrides:
            return overrides[line]
        return line_to_metric[line]['value']

    passing, failing = [], []

    for rtype, lines, desc in rels:
        try:
            if rtype in ('additive', 'structural_additive'):
                comps = lines.get('components', [])
                total_l = lines.get('total')
                subs = lines.get('subtract', [])
                if not all(l in line_to_metric for l in comps + [total_l] + subs):
                    continue
                expected = sum(get_val(l) for l in comps) - sum(get_val(l) for l in subs)
                actual = get_val(total_l)
                (passing if abs(expected - actual) <= tolerance else failing).append(
                    (rtype, lines, desc, expected, actual))

            elif rtype in ('subtractive', 'structural_subtractive'):
                if rtype == 'structural_subtractive':
                    start_l = lines['start']
                    subs_l = lines.get('subtrahends', [])
                    result_l = lines['result']
                    if not all(l in line_to_metric for l in [start_l, result_l] + subs_l):
                        continue
                    expected = get_val(start_l) - sum(get_val(l) for l in subs_l)
                    actual = get_val(result_l)
                else:
                    if not all(l in line_to_metric for l in [lines['a'], lines['b'], lines['result']]):
                        continue
                    expected = get_val(lines['a']) - get_val(lines['b'])
                    actual = get_val(lines['result'])
                (passing if abs(expected - actual) <= tolerance else failing).append(
                    (rtype, lines, desc, expected, actual))

            elif rtype in ('ratio', 'ratio_direct', 'structural_ratio'):
                if not all(l in line_to_metric for l in [lines['numerator'], lines['denominator'], lines['result']]):
                    continue
                num_v = get_val(lines['numerator'])
                den_v = get_val(lines['denominator'])
                res_v = get_val(lines['result'])
                if den_v == 0:
                    continue
                expected = (num_v / den_v) * 100 if rtype in ('ratio', 'structural_ratio') else num_v / den_v
                raw = line_to_metric[lines['result']].get('raw_value', str(res_v))
                clean = raw.replace('%', '').replace('$', '').replace(',', '').strip()
                decimals = len(clean.split('.')[-1]) if '.' in clean else 0
                expected_r = round(expected, decimals)
                tol = max(0.05 * (10 ** (-decimals)), 0.005) if decimals > 0 else 0.5
                (passing if abs(expected_r - res_v) <= tol + 0.001 else failing).append(
                    (rtype, lines, desc, expected_r, res_v))
        except Exception:
            pass

    return passing, failing


def _get_lines_involved(rtype, lines):
    """Get all lines involved in a relationship."""
    if rtype in ('additive', 'structural_additive'):
        result = set(lines.get('components', []))
        result.update(lines.get('subtract', []))
        if lines.get('total'):
            result.add(lines['total'])
        return result
    elif rtype in ('subtractive', 'structural_subtractive'):
        if rtype == 'structural_subtractive':
            result = {lines['start'], lines['result']}
            result.update(lines.get('subtrahends', []))
            return result
        else:
            return {lines['a'], lines['b'], lines['result']}
    elif rtype in ('ratio', 'ratio_direct', 'structural_ratio'):
        return {lines['numerator'], lines['denominator'], lines['result']}
    return set()


def _compute_required_value(rtype, lines, candidate, line_to_metric):
    """Compute what value candidate should have to fix this relationship."""
    required = []

    if rtype in ('additive', 'structural_additive'):
        if candidate == lines.get('total'):
            s = sum(line_to_metric[l]['value'] for l in lines.get('components', [])
                   if l != candidate and l in line_to_metric)
            sub = sum(line_to_metric[l]['value'] for l in lines.get('subtract', [])
                     if l != candidate and l in line_to_metric)
            required.append(s - sub)
        elif candidate in lines.get('components', []):
            other = sum(line_to_metric[l]['value'] for l in lines.get('components', [])
                       if l != candidate and l in line_to_metric)
            sub = sum(line_to_metric[l]['value'] for l in lines.get('subtract', [])
                     if l in line_to_metric)
            total_v = line_to_metric[lines['total']]['value']
            required.append(total_v + sub - other)
        elif candidate in lines.get('subtract', []):
            comp = sum(line_to_metric[l]['value'] for l in lines.get('components', [])
                      if l in line_to_metric)
            other_sub = sum(line_to_metric[l]['value'] for l in lines.get('subtract', [])
                           if l != candidate and l in line_to_metric)
            total_v = line_to_metric[lines['total']]['value']
            required.append(comp - other_sub - total_v)

    elif rtype in ('subtractive', 'structural_subtractive'):
        if rtype == 'structural_subtractive':
            if candidate == lines['result']:
                start_v = line_to_metric[lines['start']]['value']
                subs_v = sum(line_to_metric[l]['value'] for l in lines.get('subtrahends', [])
                            if l in line_to_metric)
                required.append(start_v - subs_v)
            elif candidate == lines['start']:
                subs_v = sum(line_to_metric[l]['value'] for l in lines.get('subtrahends', [])
                            if l in line_to_metric)
                result_v = line_to_metric[lines['result']]['value']
                required.append(result_v + subs_v)
            elif candidate in lines.get('subtrahends', []):
                start_v = line_to_metric[lines['start']]['value']
                other_subs = sum(line_to_metric[l]['value'] for l in lines.get('subtrahends', [])
                                if l != candidate and l in line_to_metric)
                result_v = line_to_metric[lines['result']]['value']
                required.append(start_v - other_subs - result_v)
        else:
            if candidate == lines['result']:
                required.append(line_to_metric[lines['a']]['value'] -
                              line_to_metric[lines['b']]['value'])
            elif candidate == lines['a']:
                required.append(line_to_metric[lines['b']]['value'] +
                              line_to_metric[lines['result']]['value'])
            elif candidate == lines['b']:
                required.append(line_to_metric[lines['a']]['value'] -
                              line_to_metric[lines['result']]['value'])

    elif rtype in ('ratio', 'structural_ratio'):
        if candidate == lines['result']:
            num = line_to_metric[lines['numerator']]['value']
            den = line_to_metric[lines['denominator']]['value']
            if den != 0:
                required.append(round((num / den) * 100, 1))
        elif candidate == lines['numerator']:
            den = line_to_metric[lines['denominator']]['value']
            res = line_to_metric[lines['result']]['value']
            required.append(res * den / 100)
        elif candidate == lines['denominator']:
            num = line_to_metric[lines['numerator']]['value']
            res = line_to_metric[lines['result']]['value']
            if res != 0:
                required.append(num * 100 / res)

    return required


def identify_error(metrics, rels):
    """Identify the single incorrect metric using correction-based elimination."""
    # Handle duplicate line numbers
    line_to_metrics_list = {}
    for m in metrics:
        if m['line'] not in line_to_metrics_list:
            line_to_metrics_list[m['line']] = []
        line_to_metrics_list[m['line']].append(m)
    # Use first metric per line for correction computation
    line_to_metric = {line: ms[0] for line, ms in line_to_metrics_list.items()}

    passing, failing = check_relationships(metrics, rels)

    if not failing:
        return None

    # Collect lines involved in failures
    error_lines = set()
    for rtype, lines, desc, exp, act in failing:
        error_lines.update(_get_lines_involved(rtype, lines))
    error_lines.discard(None)

    for candidate in error_lines:
        required_values = []

        for rtype, lines, desc, exp, act in failing:
            involved = _get_lines_involved(rtype, lines)
            if candidate not in involved:
                continue
            required_values.extend(_compute_required_value(rtype, lines, candidate, line_to_metric))

        if not required_values:
            continue
        if len(set(round(v, 2) for v in required_values)) > 1:
            continue

        correct_value = required_values[0]
        _, test_failing = check_relationships(metrics, rels, {candidate: correct_value})
        if not test_failing:
            m = line_to_metric[candidate]
            return {**m, 'correct_value': correct_value}

    return None


def exhaustive_error_search(metrics, rels):
    """
    Last-resort fallback: for each metric, try replacing its value with
    computed values from relationships and check if all relationships pass.
    """
    line_to_metric = {m['line']: m for m in metrics}

    for candidate in metrics:
        # Try computed values from relationships involving this metric
        test_values = set()

        for rtype, lines, desc in rels:
            involved = _get_lines_involved(rtype, lines)
            if candidate['line'] not in involved:
                continue
            req = _compute_required_value(rtype, lines, candidate['line'], line_to_metric)
            test_values.update(round(v, 4) for v in req)

        # Also try values from other metrics
        for other in metrics:
            if other['line'] != candidate['line']:
                test_values.add(other['value'])

        for test_val in test_values:
            if abs(test_val - candidate['value']) < 0.001:
                continue
            _, failing = check_relationships(metrics, rels, {candidate['line']: test_val})
            if not failing:
                return {**candidate, 'correct_value': test_val}

    return None


def format_output_value(metric):
    """Format metric value for output (remove formatting chars)."""
    raw = metric.get('raw_value', str(metric['value']))
    if metric['is_percentage']:
        return raw.replace('%', '').replace('$', '').replace(',', '').strip()
    else:
        val = raw.replace('$', '').strip()
        if val.startswith('(') and val.endswith(')'):
            val = '-' + val[1:-1]
        return val.replace(',', '')


def solve(html_file, output_file='/app/value.txt'):
    """Main solver entry point."""
    with open(html_file, 'r') as f:
        html_content = f.read()

    tables = parse_html(html_content)
    metrics = extract_metrics_from_tables(tables)
    cat = categorize_all_metrics(metrics)

    # Build relationships using both name-based and structural discovery
    rels = build_all_relationships(metrics, cat)

    passing, failing = check_relationships(metrics, rels)
    error_metric = identify_error(metrics, rels)

    # Fallback: exhaustive search if primary method fails
    if not error_metric:
        error_metric = exhaustive_error_search(metrics, rels)

    if error_metric:
        val_str = format_output_value(error_metric)
        with open(output_file, 'w') as f:
            f.write(f"{error_metric['line']},{val_str}\n")
        return error_metric['line'], val_str
    return None, None


if __name__ == '__main__':
    html_file = sys.argv[1] if len(sys.argv) > 1 else '/app/q2_earnings_report.html'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '/app/value.txt'
    result = solve(html_file, output_file)
    if result[0]:
        print(f"Answer: {result[0]},{result[1]}")
    else:
        print("No error found")
