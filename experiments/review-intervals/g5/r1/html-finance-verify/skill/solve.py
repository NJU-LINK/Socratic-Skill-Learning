#!/usr/bin/env python3
"""
General HTML financial verification solver.
Pipeline:
  1. Parse HTML -> extract (line_number, metric_name, numeric_value, is_percentage) tuples
  2. Find all valid relationships (additive, difference, ratio, growth, direct_ratio)
  3. Mark every participant in any valid relationship as verified
  4. The one value in NO valid relationship is the error
"""
import re, os, sys
from html.parser import HTMLParser
from itertools import combinations


class TableExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.current_cell = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
        elif tag == 'tr' and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ('td', 'th') and self.in_row:
            self.in_cell = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.in_cell:
            self.in_cell = False
            self.current_row.append(self.current_cell.strip())
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            if self.current_row:
                self.rows.append(self.current_row)
        elif tag == 'table':
            self.in_table = False

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def parse_html_report(html_path):
    with open(html_path, 'r') as f:
        html = f.read()

    parser = TableExtractor()
    parser.feed(html)

    entries = []
    for row in parser.rows:
        if len(row) < 3:
            continue

        line_num = None
        metric_name = None
        raw_value = None

        for cell_text in row:
            if re.match(r'^\d{2,4}$', cell_text) and line_num is None:
                line_num = int(cell_text)
            elif re.match(r'^[\$\(\-]?\s*[\d][\d,\.]*\s*[\$\%\)]?$', cell_text):
                raw_value = cell_text
            elif metric_name is None and cell_text and not re.match(r'^\d+$', cell_text):
                metric_name = cell_text

        if line_num is not None and raw_value is not None:
            is_percentage = '%' in raw_value
            is_negative = '(' in raw_value and ')' in raw_value

            num_str = raw_value.replace('$', '').replace(',', '').replace('%', '').strip()
            if is_negative:
                num_str = num_str.strip('()').strip()

            try:
                numeric_value = float(num_str)
                if is_negative:
                    numeric_value = -numeric_value
            except ValueError:
                continue

            entries.append({
                'line': line_num,
                'metric': metric_name or '',
                'value': numeric_value,
                'is_percentage': is_percentage,
                'raw': raw_value
            })

    return entries


def detect_precision(entries):
    precisions = []
    for e in entries:
        if e['is_percentage']:
            num_part = e['raw'].replace('%', '').replace('$', '').replace(',', '').strip()
            if '.' in num_part:
                precisions.append(len(num_part.split('.')[1]))
    return max(precisions) if precisions else 1


def find_error(html_path):
    entries = parse_html_report(html_path)
    precision = detect_precision(entries)
    pct_tol = 0.5 * (10 ** (-precision))
    dollar_tol = 0.01

    print(f"Found {len(entries)} entries, precision={precision}dp")
    for e in entries:
        print(f"  Line {e['line']}: {e['metric']} = {e['value']} {'%' if e['is_percentage'] else ''}")

    n = len(entries)
    verified = set()
    relationships = []

    dollar_idx = [i for i in range(n) if not entries[i]['is_percentage']]
    pct_idx = [i for i in range(n) if entries[i]['is_percentage']]

    # === Phase 1: Additive relationships among dollar values ===
    for i in dollar_idx:
        target = entries[i]['value']
        others = [(entries[j]['value'], j) for j in dollar_idx if j != i]

        for size in range(1, min(7, len(others) + 1)):
            for combo in combinations(others, size):
                vals = [c[0] for c in combo]
                idxs = [c[1] for c in combo]
                if abs(sum(vals) - target) < dollar_tol:
                    all_participants = [i] + idxs
                    for p in all_participants:
                        verified.add(p)
                    relationships.append(('sum', all_participants))

    # Difference: entries[i] = entries[j] - entries[k]
    for i in dollar_idx:
        target = entries[i]['value']
        for j in dollar_idx:
            if j == i:
                continue
            for k in dollar_idx:
                if k == i or k == j:
                    continue
                if abs(entries[j]['value'] - entries[k]['value'] - target) < dollar_tol:
                    if abs(entries[k]['value']) > 0.001:
                        verified.add(i)
                        verified.add(j)
                        verified.add(k)
                        relationships.append(('diff', [i, j, k]))

    # Direct ratio: entries[i] = entries[j] / entries[k] (per-share, multiples)
    for i in dollar_idx:
        target = entries[i]['value']
        for j in dollar_idx:
            if j == i:
                continue
            for k in dollar_idx:
                if k == i or k == j:
                    continue
                if abs(entries[k]['value']) < 0.001:
                    continue
                computed = entries[j]['value'] / entries[k]['value']
                if abs(computed - target) < dollar_tol:
                    verified.add(i)
                    verified.add(j)
                    verified.add(k)
                    relationships.append(('direct_ratio', [i, j, k]))

    # === Phase 2: Percentage relationships ===
    for i in pct_idx:
        target = entries[i]['value']

        # Try A / B * 100
        found = False
        for j in dollar_idx:
            for k in dollar_idx:
                if j == k or abs(entries[k]['value']) < 0.001:
                    continue
                computed = entries[j]['value'] / entries[k]['value'] * 100
                if abs(computed - target) < pct_tol:
                    verified.add(i)
                    verified.add(j)
                    verified.add(k)
                    relationships.append(('ratio', [i, j, k]))
                    found = True
                    break
            if found:
                break

        # Try (A - B) / B * 100 (growth rate)
        if not found:
            for j in dollar_idx:
                for k in dollar_idx:
                    if j == k or abs(entries[k]['value']) < 0.001:
                        continue
                    computed = (entries[j]['value'] - entries[k]['value']) / entries[k]['value'] * 100
                    if abs(computed - target) < pct_tol:
                        verified.add(i)
                        verified.add(j)
                        verified.add(k)
                        relationships.append(('growth', [i, j, k]))
                        found = True
                        break
                if found:
                    break

        # Try 100 - other_pct
        if not found:
            for j in pct_idx:
                if j == i:
                    continue
                if abs((100 - entries[j]['value']) - target) < pct_tol:
                    verified.add(i)
                    verified.add(j)
                    relationships.append(('complement', [i, j]))
                    found = True
                    break

    # === Phase 3: Dollar values derivable from percentage * another dollar ===
    for i in dollar_idx:
        if i in verified:
            continue
        target = entries[i]['value']
        for p in pct_idx:
            pct_frac = entries[p]['value'] / 100.0
            for j in dollar_idx:
                if j == i:
                    continue
                if abs(entries[j]['value'] * pct_frac - target) < dollar_tol:
                    verified.add(i)
                    verified.add(p)
                    verified.add(j)
                    relationships.append(('pct_of', [i, p, j]))
                    break
            if i in verified:
                break

    # === Report ===
    print(f"\nFound {len(relationships)} relationships")
    for rel in relationships:
        rtype, participants = rel
        lines = [entries[p]['line'] for p in participants]
        print(f"  {rtype}: lines {lines}")

    print(f"\n=== Verification ({len(verified)}/{n} verified) ===")
    unverifiable = []
    for i, e in enumerate(entries):
        status = "V" if i in verified else "X"
        print(f"  {status} Line {e['line']} ({e['metric']}): {e['value']}")
        if i not in verified:
            unverifiable.append(e)

    if len(unverifiable) == 1:
        err = unverifiable[0]
        return err['line'], err['raw']
    elif len(unverifiable) == 0:
        print("\nAll values verified - no error found")
        return None, None
    else:
        print(f"\nWARNING: {len(unverifiable)} unverifiable values")
        for u in unverifiable:
            print(f"  Line {u['line']}: {u['value']}")
        return None, None


def format_raw_value(raw_str):
    """Convert a raw HTML value string to the clean numeric display form.
    Preserves trailing zeros and original decimal representation.
    E.g. '60.80%' -> '60.80', '$1,234.5' -> '1234.5', '(50.0)' -> '-50.0'
    """
    s = raw_str.replace('$', '').replace(',', '').replace('%', '').strip()
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1].strip()
    return s


if __name__ == '__main__':
    # Auto-discover HTML file
    html_path = None
    for f in os.listdir('/app'):
        if f.endswith('.html'):
            html_path = os.path.join('/app', f)
            break

    if html_path is None:
        print("No HTML file found in /app/")
        sys.exit(1)

    line, raw_value = find_error(html_path)
    if line is not None:
        val_str = format_raw_value(raw_value)
        result = f"{line},{val_str}"
        print(f"\nAnswer: {result}")
        with open('/app/value.txt', 'w') as f:
            f.write(result)
    else:
        print("\nCould not determine the error.")
