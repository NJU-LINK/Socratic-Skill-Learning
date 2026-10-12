#!/usr/bin/env python3
"""verify_report.py - locate the single incorrect metric in a line-numbered
HTML financial report and emit `line,value`.

Family: html-finance-verify.
Invariant: exactly ONE reported metric violates an internal cross-check
(sum/subtotal, difference, ratio/margin, YoY change, per-share, unit
conversion). Every other value is internally consistent and everything is
discoverable from the report itself (no external knowledge).

Environment constraint: the reference container is Python 3.12 stdlib-only
(no bs4, lxml, pandas) and may be offline - parsing here uses `re` + `html`.

ROUNDING-CONVENTION RULE (critical):
Never test a row at its own displayed precision - the wrong row's displayed
form may itself be the lie (e.g. convention is 1 dp, true value 61.805
-> correct display 61.8, variant injects "61.81"; rounding expected to the
row's own 2 dp would validate it). Instead:
  1. Compute the expected value for every template check.
  2. Vote PER METRIC FAMILY ('money' sums/differences, 'pct' ratios like
     margins/YoY, 'ps' per-share amounts): the family precision is the
     decimal count that makes the MOST rows of that family consistent
     (sums stay consistent at many d; ratios pin the precision).
  3. Report prose notes ("rounded to N decimal place") are an ADVISORY
     pre-vote oracle: they resolve singleton families and vote ties. A
     parsed note that conflicts with a unique family vote is a CONFLICT ->
     refuse to emit (human decision). A regex miss is neutral, not an error.
  4. A row is inconsistent iff round(expected, family_d*) != its value
     (digits compared exactly; epsilon only absorbs binary noise).
  5. A row whose own displayed precision differs from its family's is a red
     flag but never the pass/fail criterion.
  6. Singleton-family rows that fail at family_d* yet match their own
     displayed precision are AMBIGUOUS: fail closed (refuse to emit) - the
     human must confirm the convention from prose/siblings.

CHECK-CREATION LAW (see YoY/per-share blocks): a template generates a check
ONLY when it can positively confirm its layout assumptions; otherwise the
row stays in the uncovered list. A confident BAD on a fully consistent
report is worse than no template at all: the emit gate only counts 0 vs
>=2, it can never catch "one wrong for the wrong reason".

Usage:
    python3 verify_report.py [report.html] [answer.txt]
    python3 verify_report.py --selftest report.html   # invariant property tests
Defaults: report.html -> /app/q2_earnings_report.html (else ./report.html),
answer.txt -> /app/value.txt.

The answer writes the REPORT's line label (the number printed in the HTML,
e.g. 210) - never a file line offset - and the displayed numeric value with
symbols stripped (no %, $, commas, spaces; decimals and sign kept as shown).
"""
import re
import sys
import os
import html as H
from collections import Counter

SYM = re.compile(r'[$,%\s]')
PLACEHOLDERS = {'', '—', '–', '-', '--', 'n/m', 'N/A', 'na', 'n.a.', 'nm', 'n.m.'}
MAXDP = 6  # plausible display precisions to vote over


def parse_num(text):
    """Normalize a displayed number to float. (x) -> -x. None on placeholder."""
    s = H.unescape(text).strip().replace('\xa0', ' ')
    s = s.replace('\u2212', '-')  # typographic minus U+2212 / &minus; -> ASCII
    if s in PLACEHOLDERS:
        return None
    core0 = SYM.sub('', s).strip()  # strip symbols BEFORE the paren check:
    neg = core0.startswith('(') and core0.endswith(')')  # '$(1,234.5)' is negative
    core = core0.strip('()')
    if neg and core.startswith(('-', '+')):
        core = core[1:]  # redundant inner sign: parens already carry it
    try:
        v = float(core)
    except ValueError:
        return None
    return -v if neg else v


def shown_value(text):
    """Numeric string exactly as displayed, minus $, commas, %, whitespace;
    '(x)' -> '-x'. Used verbatim as the answer's value field."""
    s = H.unescape(text).strip().replace('\xa0', ' ')
    s = s.replace('\u2212', '-')  # typographic minus U+2212 / &minus; -> ASCII
    core0 = SYM.sub('', s).strip()
    neg = core0.startswith('(') and core0.endswith(')')
    core = core0.strip('()')
    if neg and core.startswith(('-', '+')):
        core = core[1:]  # redundant inner sign: parens already carry it
    return ('-' if neg else '') + core


def dp_of(raw_cell):
    m = re.search(r'\.(\d+)', raw_cell)
    return len(m.group(1)) if m else 0


def almost(a, b):
    return abs(a - b) <= 1e-7 * max(1.0, abs(a), abs(b))


def _modal_dp(rows):
    """Most common displayed decimal count across all rows: the fallback
    convention oracle when no prose note pins a singleton family."""
    c = Counter(dp_of(r['raw']) for r in rows)
    return c.most_common(1)[0][0] if c else 0


def parse_precision_notes(html_text):
    """Extract prose rounding conventions ('rounded to one decimal place')
    and tag them by metric family from their context. Returns {family: dp}.
    ADVISORY pre-vote oracle: resolves singleton families and vote ties.
    A regex miss is neutral ({} returned), never an error; a parsed note
    that conflicts with a unique family vote becomes a CONFLICT upstream."""
    text = H.unescape(re.sub(r'<[^>]+>', ' ', html_text))
    text = re.sub(r'\s+', ' ', text)
    word = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}
    notes = {}
    pat = re.compile(
        r'(?:rounded|presented|reported|expressed|stated)\s+to\s+(?:a\s+)?'
        r'(one|two|three|four|five|six|\d+)\s+decimal\s+place[s]?', re.I)
    for m in pat.finditer(text):
        g = m.group(1).lower()
        d = int(g) if g.isdigit() else word[g]
        ctx = text[max(0, m.start() - 120): m.start()].lower()
        if 'per share' in ctx or 'per-share' in ctx:
            fam = 'ps'
        elif 'percent' in ctx or '%' in ctx or 'margin' in ctx or 'ratio' in ctx:
            fam = 'pct'
        elif 'dollar' in ctx or 'million' in ctx or 'amount' in ctx or 'share' in ctx:
            fam = 'money'
        else:
            fam = 'generic'
        notes[fam] = d
    return notes


def extract_tables(html_text):
    """Split the document into tables; return list of (table_id, rows).
    A data row has >=3 cells with a bare integer in cell 0 (the line label).
    All numeric cells after the label are kept (multi-column variants)."""
    tables = []
    for tid, tbl in enumerate(re.findall(r'<table[^>]*>(.*?)</table>', html_text, re.S)):
        rows = []
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tbl, re.S):
            cells = [H.unescape(re.sub(r'<[^>]+>', '', c)).strip()
                     for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
            if len(cells) < 3:
                continue
            if re.fullmatch(r'\d+', cells[0]):
                line_num = int(cells[0])  # real report label (answerable)
            else:
                # unlabeled row: keep as relation INPUT with a synthetic
                # negative key; it must never become the answer's line
                line_num = -((tid + 1) * 10000 + len(rows))
            nums = []
            for c in cells[2:]:
                v = parse_num(c)
                if v is not None:
                    nums.append((v, shown_value(c), c))
            if not nums:
                continue
            rows.append({'line': line_num, 'name': cells[1],
                         'val': nums[0][0], 'shown': nums[0][1],
                         'raw': nums[0][2], 'nums': nums})
        if rows:
            tables.append((tid, rows))
    return tables


def all_rows(tables):
    return [r for _, rows in tables for r in rows]


def find_row(rows, *pats):
    for r in rows:
        if any(re.search(p, r['name'], re.I) for p in pats):
            return r
    return None


def verify(html_text, tables, verbose=True):
    rows = all_rows(tables)
    checks = {}       # line -> (name, expected, description, own_dp, fam)
    col_checks = {}   # line -> [(k, expected_k, desc_k)] for multi-column tables
    total_cands = {}  # line -> (row, [(start_line, acc, description, lines), ...])
    explained = set()

    rev = find_row(rows, r'^net revenue$', r'^revenue$', r'^net sales$', r'^sales$')

    # ---------- 1. Totals / subtotals -------------------------------
    # Candidate sums are every contiguous run of non-total rows ending just
    # before the total (same table). The correct grouping is resolved after
    # the convention vote: the run whose sum rounds to the reported total at
    # the convention precision (exactly one match in v01: 140..160 = 280.6).
    for _, tbl in tables:
        for i, r in enumerate(tbl):
            if not re.search(r'\b(total|subtotal)\b', r['name'], re.I):
                continue
            cands = []
            for j in range(i - 1, -1, -1):
                if re.search(r'\b(total|subtotal)\b', tbl[j]['name'], re.I):
                    break
                run = tbl[j:i]
                if len(run) < 2:
                    continue
                acc = sum(x['val'] for x in run)
                cands.append((tbl[j]['line'], acc,
                              'sum[' + ' + '.join(x['name'] for x in run) + ']',
                              [x['line'] for x in run]))
            if cands:
                total_cands[r['line']] = (r, cands)

    # ---------- 2. Difference chains (income-statement identities) --
    gp = find_row(rows, r'^gross profit$', r'^gross income$', r'\bgross profit\b')
    if gp is not None:
        cogs = find_row(rows, r'^cost of revenue$', r'^cost of sales$',
                        r'^cost of goods sold$', r'^cost of (?:products|services)$')
        if rev is not None and cogs is not None:
            checks[gp['line']] = (gp['name'], rev['val'] - cogs['val'],
                                  'revenue - cost of revenue', dp_of(gp['raw']), 'money')
            n = min(len(gp['nums']), len(rev['nums']), len(cogs['nums']))
            for k in range(1, n):
                col_checks.setdefault(gp['line'], []).append(
                    (k, rev['nums'][k][0] - cogs['nums'][k][0],
                     'revenue - cost of revenue'))
            explained.update({gp['line'], rev['line'], cogs['line']})

    oi = find_row(rows, r'^operating income$', r'^income from operations$',
                  r'^operating profit$')
    if oi is not None and gp is not None:
        tot_opex = find_row(rows, r'^total operating expenses$',
                            r'^total operating costs$', r'^operating expenses$')
        if tot_opex is not None:
            checks[oi['line']] = (oi['name'], gp['val'] - tot_opex['val'],
                                  'gross profit - total operating expenses',
                                  dp_of(oi['raw']), 'money')
            n = min(len(oi['nums']), len(gp['nums']), len(tot_opex['nums']))
            for k in range(1, n):
                col_checks.setdefault(oi['line'], []).append(
                    (k, gp['nums'][k][0] - tot_opex['nums'][k][0],
                     'gross profit - total operating expenses'))
            explained.update({oi['line'], tot_opex['line']})

    pretax = find_row(rows, r'^income before income taxes$', r'^income before taxes$',
                      r'^pre-?tax income$', r'^earnings before taxes$')
    ni = find_row(rows, r'^net income$', r'^net earnings$', r'^net income \(loss\)$')
    if ni is not None:
        if pretax is not None:
            tax = find_row(rows, r'^income tax expense$',
                           r'^provision for income taxes$', r'^tax expense$')
            if tax is not None:
                checks[ni['line']] = (ni['name'], pretax['val'] - tax['val'],
                                      'pretax income - income tax expense',
                                      dp_of(ni['raw']), 'money')
                n = min(len(ni['nums']), len(pretax['nums']), len(tax['nums']))
                for k in range(1, n):
                    col_checks.setdefault(ni['line'], []).append(
                        (k, pretax['nums'][k][0] - tax['nums'][k][0],
                         'pretax income - income tax expense'))
                explained.update({ni['line'], pretax['line'], tax['line']})
        elif oi is not None:
            other = find_row(rows, r'^other income', r'^other expense',
                             r'^other income \(expense\)')
            if other is not None:
                sign = 1.0 if re.search(r'income', other['name'], re.I) else -1.0
                checks[ni['line']] = (ni['name'], oi['val'] + sign * other['val'],
                                      'operating income +/- other income, net',
                                      dp_of(ni['raw']), 'money')
                n = min(len(ni['nums']), len(oi['nums']), len(other['nums']))
                for k in range(1, n):
                    col_checks.setdefault(ni['line'], []).append(
                        (k, oi['nums'][k][0] + sign * other['nums'][k][0],
                         'operating income +/- other income, net'))
                explained.update({ni['line'], oi['line'], other['line']})

    if pretax is not None and oi is not None:
        other = find_row(rows, r'^other income', r'^other expense',
                         r'^other income \(expense\)')
        if other is not None:
            sign = 1.0 if re.search(r'income', other['name'], re.I) else -1.0
            checks[pretax['line']] = (pretax['name'], oi['val'] + sign * other['val'],
                                      'operating income +/- other income, net',
                                      dp_of(pretax['raw']), 'money')
            n = min(len(pretax['nums']), len(oi['nums']), len(other['nums']))
            for k in range(1, n):
                col_checks.setdefault(pretax['line'], []).append(
                    (k, oi['nums'][k][0] + sign * other['nums'][k][0],
                     'operating income +/- other income, net'))
            explained.update({pretax['line'], oi['line'], other['line']})

    # ---------- 3. Margins: '<prefix> margin' = <prefix profit>/revenue*100
    if rev is not None:
        for r in rows:
            if not re.search(r'margin', r['name'], re.I):
                continue
            m = re.match(r'^(gross|operating|net|pre-?tax|ebitda|ebit)', r['name'], re.I)
            if not m:
                continue
            pre = m.group(1).lower()
            base = None
            for cand, pats in (
                ('gross', [r'^gross profit$', r'^gross income$']),
                ('operating', [r'^operating income$', r'^operating profit$',
                               r'^income from operations$']),
                ('net', [r'^net income$', r'^net earnings$']),
                ('pretax', [r'^income before income taxes$', r'^pre-?tax income$']),
                ('pre-tax', [r'^income before income taxes$', r'^pre-?tax income$']),
                ('ebitda', [r'^ebitda$']),
                ('ebit', [r'^ebit$']),
            ):
                if pre == cand:
                    base = find_row(rows, *pats)
                    break
            if base is None:
                base = find_row(rows, re.compile(
                    r'^' + re.escape(pre) + r'\s+(profit|income|earnings)', re.I))
            if base is not None and base['val'] != 0:
                checks[r['line']] = (r['name'], base['val'] / rev['val'] * 100.0,
                                     base['name'] + ' / revenue * 100',
                                     dp_of(r['raw']), 'pct')
                n = min(len(r['nums']), len(base['nums']), len(rev['nums']))
                for k in range(1, n):
                    if rev['nums'][k][0] != 0:
                        col_checks.setdefault(r['line'], []).append(
                            (k, base['nums'][k][0] / rev['nums'][k][0] * 100.0,
                             base['name'] + ' / revenue * 100'))
                explained.update({r['line'], base['line'], rev['line']})

    # ---------- 4. YoY / change rows: [current, prior, growth%] layout --
    # CHECK-CREATION LAW: a check is created only when the layout is
    # POSITIVELY confirmed: >=3 numeric cells AND a %-suffixed final cell
    # (the growth cell). Two-cell (Current/Prior columns) and one-cell
    # layouts are NOT confirmed -> skip to uncovered; a growth formula is
    # never compared against the current-period cell.
    for r in rows:
        if not re.search(r'\b(yoy|change|growth|increase|decrease|improvement|decline)\b',
                         r['name'], re.I):
            continue
        if len(r['nums']) < 3 or not r['nums'][-1][2].rstrip().endswith('%'):
            continue
        cur, prior = r['nums'][0][0], r['nums'][1][0]
        if prior == 0:
            continue
        r['val'], r['shown'], r['raw'] = r['nums'][-1]  # record = growth cell
        checks[r['line']] = (r['name'], (cur - prior) / abs(prior) * 100.0,
                             '(current - prior) / |prior| * 100',
                             dp_of(r['raw']), 'pct')
        explained.add(r['line'])

    # ---------- 5. Per-share rows ------------------------------------
    shares = find_row(rows, r'shares outstanding', r'weighted average shares',
                      r'common shares', r'shares issued')
    for r in rows:
        if re.search(r'per share|per unit', r['name'], re.I):
            related = None
            if re.search(r'eps|earnings per', r['name'], re.I):
                related = ni
            elif re.search(r'dividend', r['name'], re.I):
                related = find_row(rows, r'^dividends?$', r'^dividends declared$')
            elif re.search(r'book value', r['name'], re.I):
                related = find_row(rows, r'^shareholders.equity$',
                                   r'^total equity$', r'^stockholders.equity$')
            if related is not None and shares is not None and shares['val'] != 0:
                # unit conversion: shares may be displayed in thousands (name
                # suffix); scale so per-share = related$ / shares_in_M
                scale = 1000.0 if re.search(r'thousand|000s', shares['name'], re.I) else 1.0
                checks[r['line']] = (r['name'],
                                     related['val'] * scale / shares['val'],
                                     related['name'] + ' / shares outstanding'
                                     + (' (shares in thousands x1000)' if scale != 1.0 else ''),
                                     dp_of(r['raw']), 'ps')
                n = min(len(r['nums']), len(related['nums']), len(shares['nums']))
                for k in range(1, n):
                    if shares['nums'][k][0] != 0:
                        col_checks.setdefault(r['line'], []).append(
                            (k, related['nums'][k][0] * scale / shares['nums'][k][0],
                             related['name'] + ' / shares outstanding'))
                explained.update({r['line'], related['line'], shares['line']})

    # ---------- Convention vote --------------------------------------
    def resolve_totals(d):
        resolved = {}
        for line, (r, cands) in total_cands.items():
            hits = [c for c in cands if almost(round(c[1] + 1e-9, d), r['val'])]
            if len(hits) == 1:
                resolved[line] = hits[0]
            elif len(hits) > 1:
                resolved[line] = cands[0]  # longest run; ambiguity = red flag
        return resolved

    def total_exp(line, d):
        res = resolve_totals(d)
        if line in res:
            return res[line][1]
        return total_cands[line][1][0][1]  # longest run's sum as expected

    def total_desc(line, d):
        res = resolve_totals(d)
        if line in res:
            return res[line][2]
        return total_cands[line][1][0][2]

    def consistent_at(line, d):
        r = next(x for x in rows if x['line'] == line)
        if line in total_cands:
            if resolve_totals(d).get(line):
                return True
            return almost(round(total_exp(line, d) + 1e-9, d), r['val'])
        name, exp, desc, own_dp, _ = checks[line]
        return almost(round(exp + 1e-9, d), r['val'])

    checked_lines = set(checks) | set(total_cands)

    # ---------- Per-family convention vote ---------------------------
    # Families: 'money' (totals/differences), 'pct' (margins/YoY ratios),
    # 'ps' (per-share amounts). Each family votes for its own precision:
    # sums stay consistent at many d, ratios pin the precision. Singleton
    # families use the prose-note oracle, NEVER their own displayed dp.
    def fam_of(line):
        return 'money' if line in total_cands else checks[line][4]

    fam_rows = {}
    for line in checked_lines:
        fam_rows.setdefault(fam_of(line), []).append(line)

    notes = parse_precision_notes(html_text)  # advisory pre-vote oracle

    fam_prec = {}     # line -> (family, d_fam)
    ambiguous = set()  # fail-closed singleton rows
    conflicts = []     # parsed note vs unique family vote: human decision
    fam_votes = {}
    for fam, lines in fam_rows.items():
        fv = {d: sum(1 for l in lines if consistent_at(l, d))
              for d in range(0, MAXDP + 1)}
        fam_votes[fam] = fv
        fam_modal = Counter(
            dp_of(next(x for x in rows if x['line'] == l)['raw'])
            for l in lines).most_common(1)[0][0]
        note_d = notes.get(fam, notes.get('generic'))
        best = max(fv.values())
        argmax = {d for d, v in fv.items() if v == best}
        if len(argmax) == 1 and note_d is not None:
            best_d = next(iter(argmax))
            if best_d != note_d:
                conflicts.append(f"family '{fam}': vote pins {best_d} dp, "
                                 f"prose note says {note_d} dp")
        if len(lines) >= 2:
            tie = note_d if note_d is not None else fam_modal
            d_fam = max(fv, key=lambda d: (fv[d], -abs(d - tie)))
        else:  # singleton family: oracle precedence, never own-dp
            d_fam = note_d if note_d is not None else _modal_dp(rows)
        for l in lines:
            fam_prec[l] = (fam, d_fam)
        if len(lines) == 1:
            l = lines[0]
            r0 = next(x for x in rows if x['line'] == l)
            if (not consistent_at(l, d_fam)
                    and consistent_at(l, dp_of(r0['raw']))
                    and dp_of(r0['raw']) != d_fam):
                ambiguous.add(l)  # fail closed: convention cannot be pinned

    # ---------- Apply convention -------------------------------------
    issues = []
    for line in sorted(checked_lines):
        r = next(x for x in rows if x['line'] == line)
        fam, d_fam = fam_prec[line]
        own_dp = dp_of(r['raw'])
        if line in total_cands:
            # grouping ambiguity: >1 candidate run matching at d_fam means
            # the grouping must be hand-decided, never auto-emitted
            hits = [c for c in total_cands[line][1]
                    if almost(round(c[1] + 1e-9, d_fam), r['val'])]
            name, exp_raw, desc = r['name'], total_exp(line, d_fam), total_desc(line, d_fam)
            # per-column consistency ("Current vs Prior" tables): every
            # numeric column of the resolved run must sum to its total cell
            res = resolve_totals(d_fam)
            run_lines = res[line][3] if line in res else total_cands[line][1][0][3]
            run_rows = [next(x for x in rows if x['line'] == ln) for ln in run_lines]
            ncols = min([len(r['nums'])] + [len(x['nums']) for x in run_rows])
            for k in range(1, ncols):
                col_checks.setdefault(line, []).append(
                    (k, sum(x['nums'][k][0] for x in run_rows), desc))
        else:
            name, exp, desc, own_dp, _ = checks[line]
            exp_raw = exp
            hits = []
        exp_r = round(exp_raw + 1e-9, d_fam)
        ok = almost(exp_r, r['val'])
        if not ok:
            issues.append((r, exp_raw, desc, fam, None))
        # secondary-column issues (cell k > 0)
        for k, exp_k, desc_k in col_checks.get(line, []):
            expk_r = round(exp_k + 1e-9, d_fam)
            if not almost(expk_r, r['nums'][k][0]):
                issues.append((r, exp_k, desc_k + f' [col{k}]', fam, k))
        if verbose:
            flag = ''
            if ok and own_dp != d_fam:
                flag = 'REDFLAG(dp!=conv)'
            if line in total_cands and len(hits) > 1:
                flag = 'AMBIGUOUS-GROUPING: ' + ' | '.join(h[2] for h in hits)
            print(f"L{line:<4} {'OK ' if ok else 'BAD'} {name:<28} {desc} "
                  f"-> expected {exp_r} @{d_fam}dp[{fam}] {flag}")

    # mark the resolved component runs as explained (they are total inputs)
    for line in total_cands:
        res = resolve_totals(fam_prec[line][1])
        if line in res:
            explained.update(res[line][3])
    uncovered = sorted({x['line'] for x in rows} - explained - checked_lines)
    for line in uncovered:
        if verbose:
            print(f"L{line:<4} ---- {next(x['name'] for x in rows if x['line'] == line)}"
                  f": no template relation (hand-derive from name/neighbors)")

    if verbose:
        gv = {d: sum(1 for l in checked_lines if consistent_at(l, d))
              for d in range(0, MAXDP + 1)}
        fam_sum = '; '.join(
            f"{f}:{v}->{fam_prec[list(fam_rows[f])[0]][1]}dp" for f, v in fam_votes.items())
        print(f"\nglobal votes: {gv}; families: {fam_sum}; "
              f"rows checked: {len(checked_lines)}, issues: {len(issues)}"
              + (f"; AMBIGUOUS: {sorted(ambiguous)}" if ambiguous else "")
              + (f"; CONFLICTS: {conflicts}" if conflicts else ""))
    return issues, fam_prec, uncovered, checked_lines, ambiguous, conflicts


def replace_raw(html_text, raw, newv, line):
    """Replace the displayed cell text `raw` with `newv` inside the <tr> whose
    line label is `line`. Fast path when `raw` occurs exactly once; otherwise
    localize by the line-label context window and assert success (a KPI value
    that numerically equals a dollar figure elsewhere must not be patched in
    the wrong place)."""
    occ = list(re.finditer(re.escape(raw), html_text))
    if len(occ) == 1:
        return html_text[:occ[0].start()] + newv + html_text[occ[0].end():]
    for m in occ:
        win = html_text[max(0, m.start() - 300): m.end() + 300]
        if f'>{line}<' in win:
            return html_text[:m.start()] + newv + html_text[m.end():]
    raise AssertionError(f"raw cell {raw!r} for line {line} not localized")


def run_selftest(report_path):
    """Property tests of the family invariants, derived from the report itself
    (no hardcoded numbers - works on any in-family variant):
      A. original report: exactly 1 inconsistent row (and NO precision
         ambiguity/conflict on the flagged row);
      B. corrected copy (flagged row set to round(expected, family_d*)):
         0 issues - this is the FALSE-POSITIVE TRIPWIRE: a row misflagged
         for the wrong reason survives correction and fails B;
      C. two-bad copy (perturb a second CHECKED row): >=2 issues, so the
         emit-gate ABORTs - never a multi-row answer;
      D. precision trap (expected shown at family_d*+1 decimals, e.g. 61.81
         vs convention 61.8): the same row must STILL be flagged.
    The suite validates the checker's internal mechanics ONLY: every scenario
    ranks against the checker's own computed expectation, so a template with
    a wrong denominator would pass it. Hand-verification of the flagged row's
    expected value is a separate, non-optional step in SKILL.md."""
    with open(report_path, encoding='utf-8') as f:
        html = f.read()
    issues, fam_prec, uncovered, _, ambiguous, conflicts = verify(
        html, extract_tables(html), verbose=False)
    fails = []
    notes = []
    if conflicts:
        return False, 'prose-note vs family-vote CONFLICT: ' + '; '.join(conflicts)
    if len(issues) != 1:
        return False, (f'invariant violated on ORIGINAL report: {len(issues)} '
                       'issues (expected exactly 1)')
    r, exp_raw, desc, fam, cell = issues[0]
    if r['line'] < 0:
        return False, ('flagged row carries a synthetic key (no line label in the '
                       'report) - the task answer requires a real line number; '
                       'hand-derive the metric and give its row label explicitly')
    if r['line'] in ambiguous:
        return False, (f'flagged row L{r["line"]} is AMBIGUOUS: inconsistent at '
                       f'family convention {fam_prec[r["line"]][1]} dp but consistent '
                       'at its own displayed precision, and no prose note pins the '
                       'family convention - apply the oracle by hand before proceeding')
    d_fam = fam_prec[r['line']][1]
    raw_cell = r['nums'][cell][2] if cell is not None else r['raw']
    shown_cell = r['nums'][cell][1] if cell is not None else r['shown']
    suffix = '%' if raw_cell.strip().endswith('%') else ''

    # B. corrected copy
    correct_val = f"{round(exp_raw + 1e-9, d_fam):.{d_fam}f}" + suffix
    html_c = replace_raw(html, raw_cell, correct_val, r['line'])
    issues_c, fam_prec_c, _, checked_c, _, _ = verify(
        html_c, extract_tables(html_c), verbose=False)
    if len(issues_c) != 0:
        fails.append('corrected copy: ' +
                     '; '.join(f"L{i[0]['line']}:{round(i[1] + 1e-9, fam_prec_c[i[0]['line']][1])}"
                               for i in issues_c[:5]) + ' (expected 0 issues)')

    # C. two-bad copy: perturb a second CHECKED row (a row the checker
    # actually examines). If fewer than 2 checked rows exist, skip C.
    crows = [x for x in all_rows(extract_tables(html_c))
             if x['line'] in checked_c and x['line'] != r['line']]
    made = False
    for cand in sorted(crows, key=lambda x: x['line']):
        cand_suffix = '%' if cand['raw'].strip().endswith('%') else ''
        newv = f"{parse_num(cand['raw']) + 1.0:.{dp_of(cand['raw'])}f}" + cand_suffix
        html_b = replace_raw(html_c, cand['raw'], newv, cand['line'])
        issues_b, _, _, _, _, _ = verify(html_b, extract_tables(html_b), verbose=False)
        if len(issues_b) >= 2:
            made = True
            break
    if len(crows) < 2:
        notes.append('C skipped: fewer than 2 checked rows on this report')
    elif not made:
        fails.append('two-bad copy: no checked-row perturbation produced >=2 issues')

    # D. precision trap: expected value shown at family_d*+1 decimals
    trap_val = f"{round(exp_raw + 1e-9, d_fam + 1):.{d_fam + 1}f}" + suffix
    trap_num = parse_num(trap_val)
    if trap_num is None or abs(trap_num - round(exp_raw + 1e-9, d_fam)) <= 1e-9:
        notes.append('D skipped: expected value is identical at family d*+1 '
                     'decimals (sum-type row; trap not exerciseable)')
    else:
        html_t = replace_raw(html, raw_cell, trap_val, r['line'])
        issues_t, fam_prec_t, _, _, _, _ = verify(html_t, extract_tables(html_t), verbose=False)
        if len(issues_t) == 1 and issues_t[0][0]['line'] == r['line']:
            notes.append(f'D PASS: precision trap ({trap_val!r}) still flagged '
                         f'L{r["line"]} at convention {fam_prec_t[r["line"]][1]} dp')
        elif len(issues_t) == 0:
            notes.append('D COLLAPSED: 0 issues under the precision trap - the '
                         'family vote cannot pin this row\'s convention; apply '
                         'the fallback oracle (prose note / sibling modal dp) '
                         'and hand-check the flagged row before emitting')
        else:
            fails.append(f'precision trap ({trap_val!r}): {len(issues_t)} issues '
                         f'(expected 1 on L{r["line"]})')

    msg = '; '.join(notes) if notes else ''
    if fails:
        return False, '; '.join(fails) + ((' | ' + msg) if msg else '')
    return True, ('all selftest assertions passed (A,B,C) | ' + msg if msg
                  else 'all selftest assertions passed')


def main():
    selftest_mode = '--selftest' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--selftest']
    report = args[0] if args else \
        ('/app/q2_earnings_report.html' if os.path.exists('/app/q2_earnings_report.html')
         else 'report.html')
    out = args[1] if len(args) > 1 else '/app/value.txt'

    if selftest_mode:
        ok, msg = run_selftest(report)
        print('SELFTEST ' + ('PASS' if ok else 'FAIL') + ': ' + msg)
        sys.exit(0 if ok else 1)

    with open(report, encoding='utf-8') as f:
        html_text = f.read()
    tables = extract_tables(html_text)
    issues, fam_prec, uncovered, _, ambiguous, conflicts = verify(html_text, tables, verbose=True)

    if conflicts:
        print('ABORT: prose-note vs family-vote CONFLICT (human decision needed):')
        for c in conflicts:
            print('  ' + c)
        sys.exit(1)
    if len(issues) != 1:
        print(f"ABORT: expected exactly 1 inconsistent row, found {len(issues)}")
        for r, exp, desc, fam, cell in issues:
            d = fam_prec[r['line']][1]
            shown = r['nums'][cell][1] if cell is not None else r['shown']
            print(f"  L{r['line']} {r['name']}: reported {shown}, "
                  f"expected {round(exp + 1e-9, d)} @{d}dp[{fam}] ({desc})")
        if uncovered:
            print("  rows without a template relation (hand-derive): "
                  + ', '.join(f"L{l}" for l in uncovered))
        if len(issues) > 1:
            print("  propagation hint: when one issue's inputs include another issue's")
            print("  line, the culprit is the row whose inputs are ALL consistent - a")
            print("  bad component makes its dependents fail too (e.g. prior opex ->")
            print("  L170 [col1] + L180 [col1]).")
        sys.exit(1)

    r, exp, desc, fam, cell = issues[0]
    if r['line'] < 0:
        print(f"ABORT: flagged row L{r['line']!r} has no line label - the task's "
              "answer requires a real line number; hand-derive the metric and "
              "emit its row label manually.")
        sys.exit(1)
    if r['line'] in ambiguous:
        d = fam_prec[r['line']][1]
        print(f"ABORT: flagged row L{r['line']} is AMBIGUOUS - inconsistent at family "
              f"convention {d} dp but consistent at its own displayed precision "
              f"({dp_of(r['raw'])} dp), and no prose note pins its family convention. "
              "Read the report note and hand-check before emitting.")
        sys.exit(1)
    shown = r['nums'][cell][1] if cell is not None else r['shown']
    ans = f"{r['line']},{shown}"
    with open(out, 'w') as f:
        f.write(ans + '\n')
    print(f"\nANSWER: {ans}  (line label from report; value as displayed, symbols stripped)")


if __name__ == '__main__':
    main()