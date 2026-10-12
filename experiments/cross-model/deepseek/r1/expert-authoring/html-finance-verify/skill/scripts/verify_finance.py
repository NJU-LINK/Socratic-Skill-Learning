#!/usr/bin/env python3
"""verify_finance.py — reconciliation aid for HTML financial-verification tasks.

Extracts line-numbered metric rows from any HTML report using only the standard
library, re-derives displayed values from internal identities (total/subtotal
sums, known margin ratios) and prints every inconsistency together with the
derived expectation. With --output it writes `line,value` — the displayed
(incorrect) value with currency/percent/grouping symbols stripped — but only
when exactly one line fails its checks. Otherwise it exits non-zero so the
agent audits by hand.

Usage:
  python3 verify_finance.py REPORT.html
  python3 verify_finance.py REPORT.html --output /app/value.txt
"""

import argparse
import decimal
import re
import sys

decimal.getcontext().prec = 28

RE_EVENT = re.compile(
    r'(<table[^>]*>.*?</table>|<h[1-6][^>]*>.*?</h[1-6]>)', re.S | re.I)
RE_TR = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S | re.I)
RE_CELL = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.S | re.I)
RE_TAG = re.compile(r'<[^>]+>')
RE_WS = re.compile(r'\s+')

CURRENCIES = ('$', '\u20ac', '\u00a3', '\u00a5')  # $ € £ ¥
DASHES = ('\u2212', '\u2013', '\u2014')           # − – —


def clean_cell(raw):
    """Strip tags and common entities, collapse whitespace."""
    t = RE_TAG.sub('', raw)
    t = (t.replace('&nbsp;', ' ').replace('&numsp;', ' ')
          .replace('&#160;', ' ').replace('&minus;', '-')
          .replace('&#8211;', '-').replace('&ndash;', '-')
          .replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>'))
    return RE_WS.sub(' ', t).strip()


def looks_numeric(text):
    """True if the cell is a pure displayed number (with optional $ % ( ) ,).
    Rejects labels such as 'Q2 2025' even when they contain digits."""
    t = text.strip()
    if not t:
        return False
    neg = False
    if t.startswith('(') and t.endswith(')'):
        neg = True
        t = t[1:-1].strip()
    for sym in CURRENCIES:
        t = t.replace(sym, '')
    t = t.replace('%', '')
    for d in DASHES:
        t = t.replace(d, '-')
    t = re.sub(r'[\u00a0\u202f\u2009 ]', '', t)
    if not t:
        return False
    patterns = (
        r'-?\d+(?:\.\d+)?',                           # 842.0 / 60.8 / -12.3
        r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?',            # 1,234.5
        r'-?\d{1,3}(?:\.\d{3})+(?:,\d+)?',            # 1.234,5
        r'-?\d+,\d+',                                  # 600,0 (decimal comma)
    )
    # neg (parentheses) is handled in parse_number; a leading '-' is fine too
    return bool(any(re.fullmatch(p, t) for p in patterns))


def parse_number(text):
    """Parse a displayed numeric cell to Decimal; None when unparseable."""
    t = clean_cell(text)
    if not t:
        return None
    neg = False
    if t.startswith('(') and t.endswith(')'):
        neg = True
        t = t[1:-1].strip()
    for sym in CURRENCIES + ('%',):
        t = t.replace(sym, '')
    for d in DASHES:
        t = t.replace(d, '-')
    t = re.sub(r'[\u00a0\u202f\u2009 ]', '', t)
    if t.lower() in ('n/a', 'na', 'n.m.', '-', ''):
        return None
    m = re.fullmatch(r'(\d{1,3}(?:\.\d{3})*),(\d{1,2})', t)  # 1.234,5
    if m:
        t = m.group(1).replace('.', '') + '.' + m.group(2)
    else:
        m = re.fullmatch(r'(\d+),(\d{1,2})', t)               # 600,0
        if m:
            t = m.group(1) + '.' + m.group(2)
        else:
            t = t.replace(',', '')
    m = re.search(r'-?\d+(?:\.\d+)?', t)
    if not m:
        return None
    val = decimal.Decimal(m.group(0))
    return -val if neg else val


def display_value(raw):
    """Answer-token form: displayed value minus %, currency, grouping."""
    t = clean_cell(raw)
    neg = t.startswith('(') and t.endswith(')')
    if neg:
        t = t[1:-1].strip()
    for sym in CURRENCIES + ('%',):
        t = t.replace(sym, '')
    for d in DASHES:
        t = t.replace(d, '-')
    t = re.sub(r'[\u00a0\u202f\u2009 ]', '', t)
    # Decimal-comma formats (600,0 / 1.234,5) become dotted tokens; any other
    # comma is a grouping separator and is dropped.
    m = re.fullmatch(r'(-?)(\d{1,3}(?:\.\d{3})+|\d+),(\d{1,2})', t)
    if m:
        t = m.group(1) + m.group(2).replace('.', '') + '.' + m.group(3)
    else:
        t = t.replace(',', '')
    t = t.strip()
    if neg and t and not t.startswith('-'):
        t = '-' + t
    return t


def decimals_of(value):
    """Number of decimals a displayed Decimal carries."""
    exp = value.as_tuple().exponent
    return 0 if exp >= 0 else -exp


def round_half_up(value, places):
    q = decimal.Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=decimal.ROUND_HALF_UP)


AGG_RE = re.compile(r'(?i)(^|\W)(total|subtotal)(\W|$)')


def extract_sections(html_text):
    """Return [(section_title, [row dicts])]; section = nearest heading."""
    sections = []
    current = '(document)'
    for ev in RE_EVENT.finditer(html_text):
        chunk = ev.group(1)
        if chunk.lower().startswith('<table'):
            rows = []
            for tr in RE_TR.findall(chunk):
                cells = [c for c in (clean_cell(x) for x in
                                     RE_CELL.findall(tr)) if c]
                if not cells:
                    continue
                line_cell, label, raws = None, None, []
                for c in cells:
                    if line_cell is None and re.fullmatch(r'\d+', c):
                        line_cell = c
                    elif looks_numeric(c):
                        raws.append(c)
                    elif label is None:
                        label = c
                if line_cell is None or not raws:
                    continue  # header row or footer note
                rows.append({
                    'line': int(line_cell),
                    'line_text': line_cell,
                    'label': label or '',
                    'raws': raws,
                    'values': [parse_number(r) for r in raws],
                })
            if rows:
                sections.append((current, rows))
        else:
            title = RE_WS.sub(' ', RE_TAG.sub('', chunk)).strip()
            if title:
                current = title
    return sections


def runs(opts, sections):
    rows = [r for _, rs in sections for r in rs]

    def find_label(pattern, exclude_line=None):
        for r in rows:
            if re.search(pattern, r['label'], re.I) and (
                    exclude_line is None or r['line'] != exclude_line):
                return r
        return None

    print('=== Extracted rows ===')
    for title, rs in sections:
        print('Section: %s' % (title or '(untitled)'))
        for r in rs:
            vals = ', '.join('' if v is None else str(v) for v in r['values'])
            print('  line %-5s %-28s %-14s -> %s'
                  % (r['line_text'], r['label'][:28], ' | '.join(r['raws']), vals))

    issues = []  # (kind, line, label, displayed, derived)
    derived_re = re.compile(
        r'(?i)\b(profit|income|loss|earnings|ebitda|ebit|margin)\b')

    def unit_tol(dec_places):
        return decimal.Decimal('0.5') * (decimal.Decimal(10) ** -dec_places) \
            + decimal.Decimal('1e-9')

    # 1) Additive checks inside each section.
    # A Total = sum of a contiguous run of pending leaf rows (suffix or any
    # sub-run) OR = the previous total plus the pending leaves (cumulative
    # layouts such as balance sheets). Derived statement lines reset the
    # pending set so they are not misread as components.
    print('\n=== Identity checks ===')
    for title, rs in sections:
        pending = []
        last_total = None
        for r in rs:
            if AGG_RE.search(' %s ' % r['label']):
                disp = r['values'][-1]
                if disp is None:
                    pending = []
                    continue
                vals = [p['values'][-1] for p in pending
                        if p['values'][-1] is not None]
                if not vals and last_total is None:
                    print('  ADD   line %-5s %-28s no components above - skip'
                          % (r['line_text'], r['label'][:28]))
                    last_total = disp
                    pending = []
                    continue
                ok_runs = []
                for i in range(len(vals)):
                    for j in range(i, len(vals)):
                        s = sum(vals[i:j + 1], decimal.Decimal(0))
                        dc = max([decimals_of(v) for v in vals[i:j + 1]]
                                 + [decimals_of(disp)])
                        if abs(s - disp) <= unit_tol(dc) \
                                or abs(s + disp) <= unit_tol(dc):
                            ok_runs.append((i, j, s))
                cumulative = None
                if last_total is not None:
                    cand = last_total + sum(vals, decimal.Decimal(0))
                    dc = max([decimals_of(v) for v in vals]
                             + [decimals_of(disp), decimals_of(last_total)])
                    if abs(cand - disp) <= unit_tol(dc):
                        cumulative = cand
                if ok_runs or cumulative is not None:
                    detail = ('components [%s]' % ','.join(
                        str(p['line']) for p in pending)) if ok_runs else ''
                    if cumulative is not None:
                        detail = 'cumulative (prev total + %s)' % ','.join(
                            str(p['line']) for p in pending)
                    print('  ADD   line %-5s %-28s displayed %s -> OK (%s)'
                          % (r['line_text'], r['label'][:28], disp, detail))
                else:
                    total = sum(vals, decimal.Decimal(0))
                    print('  ADD   line %-5s %-28s displayed %s vs best sum %s '
                          '-> FAIL' % (r['line_text'], r['label'][:28],
                                        disp, total))
                    issues.append(('ADD', r['line'], r['label'], disp, total))
                last_total = disp
                pending = []
            elif derived_re.search(r['label']):
                pending = []  # derived statement line, not a leaf component
            else:
                pending.append(r)

    # 2) Ratio (margin) checks across all tables.
    numerator_map = [
        ('gross', ['gross profit']),
        ('operating', ['operating income', 'operating profit']),
        ('ebitda', ['ebitda']),
        ('ebit', ['ebit']),
        ('pretax', ['income before', 'pretax']),
        ('net', ['net income', 'net profit']),
    ]
    growth_hint_re = re.compile(
        r'(?i)(growth|change|yoy|year.over.year|increase|decrease)')

    for r in rows:
        if not any('%' in raw for raw in r['raws']) and not re.search(
                r'(?i)(margin|rate|ratio|yield)', r['label']):
            continue
        if r['values'][-1] is None:
            continue
        disp = r['values'][-1]
        d = decimals_of(disp)
        if growth_hint_re.search(r['label']):
            print('  HINT  line %-5s %-28s growth/change metric: locate the two'
                  ' period values and compute (cur - prior) / |prior| * 100'
                  % (r['line_text'], r['label'][:28]))
            continue
        # Select the numerator by the keyword that appears in THIS row's label.
        numerator = None
        for kw, cands in numerator_map:
            kw_match = re.search(r'\b%s\b' % kw, r['label'], re.I)
            if kw_match:
                for cand in cands:
                    found = find_label(
                        r'\b%s\b' % r'\s+'.join(
                            map(re.escape, cand.split())))
                    if found:
                        numerator = found
                        break
            if numerator:
                break
        denom = find_label(r'^(net |total )?(revenue|sales)$')
        if numerator is None or denom is None \
                or numerator['values'][-1] is None:
            print('  SKIP  line %-5s %-28s cannot map to component/denominator'
                  ' (audit by hand)' % (r['line_text'], r['label'][:28]))
            continue
        expected = round_half_up(decimal.Decimal(100) *
                                 numerator['values'][-1] / denom['values'][-1], d)
        tol = unit_tol(d)
        tag = 'OK ' if abs(disp - expected) <= tol else 'FAIL'
        print('  RATIO line %-5s %-28s displayed %s%% vs %s/%s = %s%% -> %s'
              % (r['line_text'], r['label'][:28], disp, numerator['label'],
                 denom['label'], expected, tag))
        if tag == 'FAIL':
            issues.append(('RATIO', r['line'], r['label'], disp, expected))

    return rows, issues


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('html', help='path to the HTML report')
    ap.add_argument('--output', metavar='PATH',
                    help='write `line,value` here when exactly one line fails')
    args = ap.parse_args(argv)

    with open(args.html, 'r', encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    sections = extract_sections(text)
    rows, issues = runs(args, sections)

    failing = {}
    for _, line, label, disp, derived in issues:
        failing.setdefault(line, []).append((label, disp, derived))

    print('\n=== Result ===')
    n_metrics = len(rows)
    print('Rows extracted: %d   Failing lines: %d' % (n_metrics, len(failing)))
    if n_metrics == 0:
        print('No metric rows extracted: the document may not contain'
              ' line-numbered values, or the line cells are not plain'
              ' integers. Inspect the HTML structure directly.')
    if len(failing) == 1:
        line = next(iter(failing))
        row = next(r for r in rows if r['line'] == line)
        display = display_value(row['raws'][-1])
        print('Single failing line %s (%s) — displayed value token: %s'
              % (row['line_text'], row['label'], display))
        print('Answer: %s,%s' % (row['line_text'], display))
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as fh:
                fh.write('%s,%s\n' % (row['line_text'], display))
            print('Wrote %s' % args.output)
        return 0
    elif len(failing) == 0:
        print('No violations found. Re-check extraction, unit scale, displayed'
              ' precision, and unhandled identity classes (growth/per-share).')
    else:
        print('Multiple failing lines — do NOT write blindly. Score each line by'
              ' number of fails (unique max wins), then audit by hand:')
        for line, events in sorted(failing.items(),
                                   key=lambda kv: -len(kv[1])):
            print('  line %s: %d failing checks' % (line, len(events)))
    if args.output:
        print('Not writing %s (need exactly one failing line).' % args.output)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))