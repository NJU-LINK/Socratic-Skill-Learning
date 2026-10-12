#!/usr/bin/env python3
"""
find_wrong_metric.py -- locate the single incorrect metric in an HTML financial report.

Family: html-finance-verify
--------------------------------
Input  : an HTML financial report (earnings snapshot, income statement, KPI table,
         balance sheet, cash-flow statement, ...) whose rows carry line numbers and
         ONE displayed metric violates an internal accounting relationship.
Output : writes `line_number,value` (value exactly as displayed, with currency/percent
         formatting stripped) to the requested file (default /app/value.txt).

Uses only the Python standard library (bs4/lxml are NOT guaranteed in the task
container). It extracts every table, maps rows to (line, label, values), then builds
internal-consistency constraints: label-driven accounting identities, numerically
discovered subtotal/summary blocks, margins/ratios, growth, per-share - all with
rounding-aware tolerance.

Selection criterion (family invariant): exactly one cell c* exists such that
replacing c*'s displayed value with a value implied by its failed constraints
makes EVERY constraint pass (restoration test). Every cell that fails at least
one constraint contributes implied values - targets from the constraint's expected
value, inputs (additive and ratio) back-solved from the target's DISPLAYED value.
The answer is the unique row whose correction restores full consistency.

Usage:
    python3 find_wrong_metric.py --html /app/q2_earnings_report.html
    python3 find_wrong_metric.py --html report.html --out /app/value.txt
    python3 find_wrong_metric.py --task /app/task.yaml       # auto-detect html + out
    python3 find_wrong_metric.py --html r.html --verbose     # show all checks
Exit codes: 0 = answer found and written; 2 = ambiguous / not found (evidence printed).
"""

import argparse
import glob
import html
import os
import re
import sys
from html.parser import HTMLParser

# ----------------------------------------------------------------------------
# 1. HTML table extraction (stdlib only)
# ----------------------------------------------------------------------------

class TableParser(HTMLParser):
    """Collect all <table> elements as lists of rows of cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []          # table = list of rows; row = list of str
        self._t = None
        self._r = None
        self._c = None
        self._incell = False

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == 'table':
            self._t = []
        elif t == 'tr' and self._t is not None:
            self._r = []
        elif t in ('td', 'th') and self._r is not None:
            self._c = []
            self._incell = True

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ('td', 'th') and self._incell:
            self._r.append(re.sub(r'\s+', ' ', ''.join(self._c)).strip())
            self._c = None
            self._incell = False
        elif t == 'tr' and self._r is not None:
            self._t.append(self._r)
            self._r = None
        elif t == 'table' and self._t is not None:
            self.tables.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._incell:
            self._c.append(data)


# ----------------------------------------------------------------------------
# 2. Number normalization + label canonicalization
# ----------------------------------------------------------------------------

UNIT_SUFFIX = {
    'k': 1e3, 'm': 1e6, 'b': 1e9, 't': 1e12,
    'mn': 1e6, 'bn': 1e9, 'tn': 1e12, 'trn': 1e12,
    'thousand': 1e3, 'million': 1e6, 'billion': 1e9, 'trillion': 1e12,
    'x': 1.0,   # ratio displays like '2.5x'
}

def normalize_number(raw):
    """Parse a displayed figure into a float.

    Handles: leading $/currency symbols, trailing %, thousands separators,
    parentheses for negatives, unicode minus, spaces, unit suffixes (M/B/K/...).
    Returns None when the text is not a number.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    neg = False
    if s.startswith('(') and s.endswith(')'):
        neg = True
        s = s[1:-1].strip()
    for ch in '$€£¥%':
        s = s.replace(ch, '')
    s = s.replace('−', '-').replace('–', '-').replace('—', '-')
    s = s.replace(',', '')
    s = re.sub(r'\s+', '', s)
    if not s:
        return None
    m = re.match(r'^([+-]?)(\d+(?:\.\d+)?)([A-Za-z]*)$', s)
    if not m:
        return None
    sign, num, suf = m.groups()
    try:
        v = float(num)
    except ValueError:
        return None
    if suf:
        mult = UNIT_SUFFIX.get(suf.lower())
        if mult is None:          # unknown suffix -> refuse (avoids mis-parsing labels)
            return None
        v *= mult
    if neg or sign == '-':
        v = -v
    return v


def decimal_places(raw):
    m = re.search(r'\.(\d+)', raw or '')
    return len(m.group(1)) if m else 0


def half_unit(raw):
    return 0.5 * 10 ** (-decimal_places(raw or ''))


def strip_formatting(raw):
    """Value exactly as displayed, minus currency/percent/separator formatting;
    parenthesized negatives become a leading minus (e.g. '($5.0)' -> '-5.0');
    a trailing multiplier suffix is dropped ('0.6x' -> '0.6')."""
    s = (raw or '').strip()
    neg = s.startswith('(') and s.endswith(')')
    if neg:
        s = s[1:-1].strip()
    for ch in '$€£¥%':
        s = s.replace(ch, '')
    s = s.replace('−', '-').replace('–', '-').replace('—', '-')
    s = s.replace(',', '')
    s = re.sub(r'\s+', '', s)
    if s.endswith(('x', 'X')):
        s = s[:-1]
    if neg and not s.startswith('-'):
        s = '-' + s
    return s


def _norm_label(s):
    """Lowercase, &-to-and, punctuation to spaces, whitespace collapsed."""
    if s is None:
        return ''
    s = html.unescape(s).lower()
    s = s.replace('&', ' and ').replace('(', ' ').replace(')', ' ')
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _singularize(word):
    if len(word) <= 3:
        return word
    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    if word.endswith('s') and not word.endswith(('ss', 'us', 'is')) and len(word) > 3:
        return word[:-1]
    return word


def canonical_label(s):
    """Morphological canonical form: normalize, then singularize every token.
    Applied to BOTH aliases and labels so 'Total revenues' matches 'revenue',
    'Costs of Sales' matches 'cost of sales', 'share count' matches 'shares'."""
    return ' '.join(_singularize(t) for t in _norm_label(s).split())


# ----------------------------------------------------------------------------
# 3. Row model: (line, label, values per column, per-column unit scales)
# ----------------------------------------------------------------------------

class Row:
    __slots__ = ('table', 'rowidx', 'line', 'label', 'raws', 'vals', 'pcts',
                 'scales', 'scale_srcs', 'doc_scale')
    def __init__(self, table, rowidx, line, label, raws, vals, pcts,
                 scales=None, scale_srcs=None, doc_scale=1.0):
        self.table = table        # table index
        self.rowidx = rowidx      # row index inside the table
        self.line = line          # displayed line number (digits) or None
        self.label = label        # metric name as displayed
        self.raws = raws          # raw cell texts (one per value column)
        self.vals = vals          # floats, suffixes ALREADY applied; None where n/a
        self.pcts = pcts          # True where raw text contained '%'
        n = len(raws)
        self.scales = scales if scales is not None else [1.0] * n
        self.scale_srcs = scale_srcs if scale_srcs is not None else ['none'] * n
        self.doc_scale = doc_scale  # prose-noted document unit (1.0 if none)

    def __repr__(self):
        return f"<Row t{self.table}r{self.rowidx} {self.line} {self.label!r} {self.raws}>"


# ----------------------------------------------------------------------------
# 3b. Unit annotations: attached suffix / label phrase / column header / prose
# ----------------------------------------------------------------------------

UNIT_WORDS = {
    'thousand': 1e3, 'thousands': 1e3, 'k': 1e3, 'ks': 1e3, '000': 1e3, '000s': 1e3,
    'million': 1e6, 'millions': 1e6, 'm': 1e6, 'mm': 1e6, 'mn': 1e6,
    'billion': 1e9, 'billions': 1e9, 'b': 1e9, 'bn': 1e9,
    'trillion': 1e12, 'trillions': 1e12, 't': 1e12, 'tn': 1e12,
}


def has_attached_suffix(raw):
    """True when the displayed value carries a unit suffix like 'M'/'B' (the
    suffix has already been applied by normalize_number)."""
    if raw is None:
        return False
    s = raw.strip()
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1].strip()
    for ch in '$€£¥%':
        s = s.replace(ch, '')
    s = re.sub(r'[\s,]+', '', s.replace('−', '-'))
    m = re.match(r'^[+-]?(?:\d+(?:\.\d+)?)([A-Za-z]+)$', s)
    return bool(m and m.group(1).lower() in UNIT_SUFFIX)


def hint_scale_from_tokens(tokens):
    """Scale inferred from unit words in a token set (label or header text)."""
    best = 1.0
    for t in tokens:
        s = UNIT_WORDS.get(t)
        if s is not None and s > best:
            best = s
    return best


def label_hint_scale(label):
    return hint_scale_from_tokens(canonical_label(label).split())


def header_hint_scale(header_text):
    if header_text is None:
        return 1.0
    return hint_scale_from_tokens(canonical_label(header_text).split())


DOC_SCALE_EXCLUDE = ('per share', 'eps', 'ratio', 'margin', 'cent')

GROWTH_MARKERS = ('yoy', 'qoq', 'growth', 'increase', 'decrease', 'variance', 'vs prior', 'y y')


def doc_unit_scale(text):
    """Scale from prose like 'Dollars in millions except percentages'; 1.0 when
    no unit phrase is found."""
    if not text:
        return 1.0
    low = text.lower()
    pats = (r'\bin\s+(?:one\s+|dollars?\s+|usd\s+)?(thousands?|millions?|billions?|trillions?|000s?)\b',
            r'\b(?:dollars?|amounts?|values?|figures?)\s+(?:are\s+|in\s+)?(thousands?|millions?|billions?|trillions?|000s?)\b')
    for pat in pats:
        m = re.search(pat, low)
        if m:
            w = m.group(1).lower()
            if 'thousand' in w or '000' in w:
                return 1e3
            if 'million' in w:
                return 1e6
            if 'billion' in w:
                return 1e9
            if 'trillion' in w:
                return 1e12
    return 1.0


def doc_scale_applies(label, pcts):
    """The document note scales rows with no own hint that are not
    percentage / per-share / ratio / growth-like rows."""
    if any(p for p in pcts):
        return False
    cl = canonical_label(label)
    if not cl:
        return False
    return not any(x in cl for x in DOC_SCALE_EXCLUDE)


def row_scales_for(label, raws, header_hints, doc_scale):
    """Per-column (scale, source) for a metric row. Precedence: attached suffix
    (already applied => 1.0) > label phrase > column header > document note.
    Hints annotate the same figures; they never multiply. Header/document units
    apply only to dollar-like rows (no '%', not per-share/eps/ratio/margin/cent)
    so a percentage row under a '($M)' header keeps scale 1."""
    label_scale = label_hint_scale(label)
    elig = doc_scale_applies(label, ['%' in (r or '') for r in raws])
    scales, srcs = [], []
    for ci, raw in enumerate(raws):
        if has_attached_suffix(raw):
            scales.append(1.0)
            srcs.append('suffix')
        elif label_scale > 1.0 and elig:
            scales.append(label_scale)
            srcs.append('label')
        else:
            hs = header_hints[ci] if ci < len(header_hints) else 1.0
            if hs > 1.0 and elig:
                scales.append(hs)
                srcs.append('header')
            elif doc_scale > 1.0 and elig:
                scales.append(doc_scale)
                srcs.append('doc')
            else:
                scales.append(1.0)
                srcs.append('none')
    return scales, srcs


_LINE_HDR = {'line', 'ln', 'no', 'no.', 'no:', 'line #', '#'}
_LABEL_HDR = {'metric', 'item', 'description', 'label', 'line item', 'kpi', 'measure', 'indicator'}

def _is_line_number(text):
    t = (text or '').strip().lstrip('#').rstrip('.')
    return bool(re.fullmatch(r'\d+', t))

def _looks_like_header_row(row):
    if len(row) < 2:
        return False
    if any(normalize_number(c) is not None for c in row):
        return False
    joined = ' '.join(_norm_label(c) for c in row)
    return bool(re.search(r'\b(line|metric|item|description|amount|value|kpi)\b', joined))

def parse_rows(tables, doc_scale=1.0):
    """Return a flat list of Row objects (with per-column unit scales)."""
    rows = []
    for ti, table in enumerate(tables):
        table = [r for r in table if any(c for c in r)]
        if not table:
            continue
        # --- header detection / column role mapping ---
        hdr_idx = next((i for i, r in enumerate(table) if _looks_like_header_row(r)), None)
        line_col = label_col = None
        value_cols = []
        header_hints = {}
        if hdr_idx is not None:
            hdr = [_norm_label(c) for c in table[hdr_idx]]
            for ci, h in enumerate(hdr):
                if h in _LINE_HDR or re.fullmatch(r'line\s*#?', h):
                    line_col = ci
                elif h in _LABEL_HDR:
                    label_col = ci
                elif re.search(r'\d{4}|q[1-4]|quarter|year', h) or h in ('value', 'amount',
                      'current', 'prior', 'usd', 'us$', '$', '$m', '$mn'):
                    value_cols.append(ci)
            if label_col is None:
                label_col = next((ci for ci in range(len(hdr))
                                  if ci != line_col and hdr[ci] not in _LINE_HDR), None)
            if not value_cols:
                value_cols = [ci for ci in range(len(hdr))
                              if ci not in (line_col, label_col)]
            # unit words in the value column headers (e.g. '($ in thousands)'),
            # aligned with the per-row value list order (value_cols order)
            header_hints = [header_hint_scale(table[hdr_idx][ci]) if ci < len(table[hdr_idx]) else 1.0
                            for ci in value_cols]
        else:
            header_hints = []
        # --- data rows ---
        start = (hdr_idx + 1) if hdr_idx is not None else 0
        added = 0
        for ri in range(start, len(table)):
            row = table[ri]
            if not row:
                continue
            line, label, rest = None, None, []
            if value_cols:
                if line_col is not None and line_col < len(row) and _is_line_number(row[line_col]):
                    line = re.sub(r'\D', '', row[line_col])
                if label_col is not None and label_col < len(row):
                    label = row[label_col]
                rest = [row[ci] for ci in value_cols if ci < len(row)]
            else:
                # heuristic layout without headers
                if (len(row) >= 3 and _is_line_number(row[0])
                        and normalize_number(row[1]) is None):
                    line, label, rest = re.sub(r'\D', '', row[0]), row[1], row[2:]
                elif (len(row) >= 3 and _is_line_number(row[-1])
                      and normalize_number(row[0]) is None
                      and normalize_number(row[-2]) is not None):
                    line, label, rest = re.sub(r'\D', '', row[-1]), row[0], row[1:-1]
                elif (len(row) >= 2 and normalize_number(row[0]) is None
                      and normalize_number(row[-1]) is not None):
                    label, rest = row[0], row[1:]
                else:
                    continue
            if label is None or not rest or all(normalize_number(c) is None for c in rest):
                continue
            if normalize_number(label) is not None:
                continue  # no textual metric name
            raws = [c for c in rest]
            scales, srcs = row_scales_for(label, raws, header_hints, doc_scale)
            rows.append(Row(ti, ri, line, label, raws,
                            [normalize_number(c) for c in raws],
                            ['%' in (c or '') for c in raws],
                            scales, srcs, doc_scale))
            added += 1
        if added == 0:
            # fallback: rows may be single cells like "110 Revenue $842.0"
            for ri, row in enumerate(table):
                joined = ' '.join(row)
                m = re.match(r'^\s*(\d+)\s+(.+?)\s+([$€£¥(]?[+-]?\d[\d,]*(?:\.\d+)?%?)\)?\s*$',
                             joined)
                if m:
                    line, label, val = m.group(1), m.group(2), m.group(3)
                    scales, srcs = row_scales_for(label, [val], header_hints, doc_scale)
                    rows.append(Row(ti, ri, line, label, [val],
                                    [normalize_number(val)], ['%' in val],
                                    scales, srcs, doc_scale))
    return rows


# ----------------------------------------------------------------------------
# 4. Relationship library (label-driven accounting identities)
# ----------------------------------------------------------------------------

REV_ALIASES = ['revenue', 'net revenue', 'total revenue', 'revenues', 'net revenues',
               'total revenues', 'net sales', 'total net sales', 'sales', 'total sales']
REV_EXCLUDE = ('marketing', 'cost', 'selling', 'general', 'administrative',
               'expense', 'growth')
COST_ALIASES = ['cost of revenue', 'cost of revenues', 'cost of goods sold',
                'cost of sales', 'cogs', 'cost of products sold', 'costs of sales',
                'costs of revenue', 'costs of goods sold']
GP_ALIASES = ['gross profit', 'gross margin dollars', 'gross profit dollars']
TOTAL_OPEX_ALIASES = ['total operating expenses', 'total operating costs',
                      'total operating expense']
OPINC_ALIASES = ['operating income', 'income from operations', 'operating profit',
                 'operating earnings', 'income from operating activities']
OTHER_ALIASES = ['other income net', 'other income expense net', 'other income',
                 'other expense', 'other income net of interest', 'interest income',
                 'interest expense', 'other income and expense', 'other gains losses']
PRETAX_ALIASES = ['income before income taxes', 'income before taxes', 'pretax income',
                  'pre tax income', 'earnings before income taxes',
                  'income before provision for income taxes']
TAX_ALIASES = ['income tax expense', 'income taxes', 'provision for income taxes',
               'income tax provision', 'tax expense']
NI_ALIASES = ['net income', 'net earnings', 'net income attributable',
              'net income loss', 'net profit']
EBITDA_ALIASES = ['ebitda', 'adjusted ebitda']
DA_ALIASES = ['depreciation and amortization', 'depreciation amortization',
              'depreciation', 'amortization', 'd and a']
SHARES_ALIASES = ['weighted average diluted shares', 'diluted weighted average shares',
                  'diluted shares', 'weighted average shares outstanding',
                  'weighted average shares', 'shares outstanding',
                  'common shares outstanding', 'shares']
EPS_ALIASES = ['diluted earnings per share', 'diluted eps', 'basic earnings per share',
               'basic eps', 'earnings per share', 'net income per share', 'eps']
TA_ALIASES = ['total assets', 'total assets and liabilities']
TL_ALIASES = ['total liabilities', 'total liabilities and equity']
TE_ALIASES = ['total equity', 'total stockholders equity', "total stockholders' equity",
              'total shareholders equity', "total shareholders' equity",
              'total stockholder equity', 'total stockholders equity and liabilities']
CFO_ALIASES = ['net cash provided by operating activities',
               'net cash used in operating activities',
               'cash flows from operating activities',
               'net cash from operating activities', 'operating cash flow',
               'cash from operating activities', 'cash provided by operating activities',
               'cash used in operating activities', 'operating activities']
CFI_ALIASES = ['net cash used in investing activities',
               'net cash provided by investing activities',
               'cash flows from investing activities',
               'net cash from investing activities',
               'cash from investing activities', 'investing activities']
CFF_ALIASES = ['net cash used in financing activities',
               'net cash provided by financing activities',
               'cash flows from financing activities',
               'net cash from financing activities',
               'cash from financing activities', 'financing activities']
NCC_ALIASES = ['net change in cash', 'net increase decrease in cash',
               'net increase in cash', 'net decrease in cash', 'change in cash',
               'net change in cash and cash equivalents']
BEGC_ALIASES = ['cash and cash equivalents beginning', 'beginning cash',
                'cash cash equivalents beginning of period', 'cash beginning of period']
ENDC_ALIASES = ['cash and cash equivalents end', 'cash and cash equivalents at end',
                'ending cash', 'cash cash equivalents end of period', 'cash end of period']


def find_rows(rows, aliases, exclude=(), prefer_tables=None):
    """Match rows whose canonical label equals an alias or contains a multi-word
    alias as a whole word (one direction only). Both sides are canonicalized
    (normalized + singularized) so plural/spelling variants match.

    Tie-break priority for ambiguous matches:
      1. rows carrying NO explicit re-annotation (suffix/label/header hints);
      2. among the rest, rows whose scale matches the document (prose) scale;
      3. rows sharing a table with already-resolved base rows;
      4. document order.
    This keeps unit-annotated duplicates ('Net income (in thousands)') from
    hijacking base roles, and also resolves annotated-vs-annotated ties
    (a '(in millions)' statement vs a '(in thousands)' KPI duplicate)."""
    doc_scale = rows[0].doc_scale if rows else 1.0
    out = []
    for r in rows:
        cl = canonical_label(r.label)
        if exclude and any(x in cl for x in exclude):
            continue
        hit = False
        for a in aliases:
            ca = canonical_label(a)
            if not ca:
                continue
            if cl == ca:
                hit = True
                break
            if len(ca) >= 4 and re.search(r'\b' + re.escape(ca) + r'\b', cl):
                hit = True
                break
        if hit:
            out.append(r)

    def _key(r):
        unannotated = all(s in ('none', 'suffix', 'doc') for s in r.scale_srcs)
        doc_cols = (sum(1 for s in r.scales if s == doc_scale)
                    if doc_scale > 1.0 else 0)
        tbl = 0 if (prefer_tables and r.table in prefer_tables) else 1
        return (not unannotated, -doc_cols, tbl)

    out.sort(key=_key)
    return out


def lookup(rows, aliases, exclude=(), prefer_tables=None):
    found = find_rows(rows, aliases, exclude, prefer_tables)
    return found[0] if found else None


# ----------------------------------------------------------------------------
# 5. Checks
# ----------------------------------------------------------------------------

class Check:
    __slots__ = ('target', 'desc', 'expected', 'tol', 'inputs', 'coeffs', 'scales',
                 'prov')
    def __init__(self, target, desc, expected, tol, inputs, coeffs=None, scales=None,
                 prov='verified'):
        self.target = target      # Row
        self.desc = desc
        self.expected = expected  # per column, in EFFECTIVE units; None = n/a;
                                  # list of (e,t) for ratio checks
        self.tol = tol            # per column
        self.inputs = inputs      # list of Row (inputs of the constraint)
        self.coeffs = coeffs      # list of (row, coeff) for additive checks, else None
        self.scales = scales      # per-column scale candidates for ratio checks, else None
        self.prov = prov          # 'verified' (numerically grounded) or 'candidate'
                                  # (a block window that never matched the original doc)


def _v(row, ci):
    """Effective value of a cell (displayed x unit scale)."""
    if ci >= len(row.vals) or row.vals[ci] is None:
        return None
    return row.vals[ci] * row.scales[ci]


def _h(row, ci):
    """Rounding half-unit of a cell in effective units."""
    raw = row.raws[ci] if ci < len(row.raws) else ''
    scl = row.scales[ci] if ci < len(row.scales) else 1.0
    return half_unit(raw) * scl


def check_pass(c, ci):
    tv = _v(c.target, ci)
    if c.tol[ci] is None:                       # ratio-style: list of (expected, tol)
        return any(abs(tv - e) <= t for e, t in c.expected[ci])
    if c.expected[ci] is None:
        return None
    return abs(tv - c.expected[ci]) <= c.tol[ci]


_BLOCK_FROZEN = {'key': None, 'windows': {}, 'locked': False}


def build_checks(rows, candidates=True):
    """Build all internal-consistency constraints.
    candidates=False disables candidate-class block checks (strict pass)."""
    checks = []
    by_table = {}
    for r in rows:
        by_table.setdefault(r.table, []).append(r)

    def row_by_aliases(aliases, exclude=()):
        # prefer the table of already-resolved base rows (rule 2 tie-break)
        hit = lookup(rows, aliases, exclude,
                     prefer_tables=({r.table for r in resolved_bases} if resolved_bases else None))
        if hit is not None:
            resolved_bases.append(hit)
        return hit

    resolved_bases = []
    rev = row_by_aliases(REV_ALIASES, REV_EXCLUDE)
    cost = row_by_aliases(COST_ALIASES)
    gp = row_by_aliases(GP_ALIASES)
    opex = row_by_aliases(TOTAL_OPEX_ALIASES)
    opinc = row_by_aliases(OPINC_ALIASES, ('other', 'non operating', 'nonoperating'))
    other = row_by_aliases(OTHER_ALIASES)
    pretax = row_by_aliases(PRETAX_ALIASES)
    tax = row_by_aliases(TAX_ALIASES)
    ni = row_by_aliases(NI_ALIASES)
    ebitda = row_by_aliases(EBITDA_ALIASES)
    da = row_by_aliases(DA_ALIASES)
    shares = row_by_aliases(SHARES_ALIASES)
    eps = row_by_aliases(EPS_ALIASES)
    ta = row_by_aliases(TA_ALIASES)
    tl = row_by_aliases(TL_ALIASES)
    te = row_by_aliases(TE_ALIASES)
    cfo = row_by_aliases(CFO_ALIASES, ('other',))
    cfi = row_by_aliases(CFI_ALIASES, ('other',))
    cff = row_by_aliases(CFF_ALIASES, ('other',))
    ncc = row_by_aliases(NCC_ALIASES)
    begc = row_by_aliases(BEGC_ALIASES)
    endc = row_by_aliases(ENDC_ALIASES)

    def additive(target, desc, terms, prov='verified'):
        """terms: list of (row, coeff). Expected/tolerance per column in
        EFFECTIVE units (displayed x row scale)."""
        exp, tol = [], []
        coeffs = list(terms)
        for ci in range(len(target.vals)):
            parts, eps_sum, ok = [], 0.0, True
            for row, coeff in terms:
                v = _v(row, ci)
                if v is None:
                    ok = False
                    break
                parts.append(coeff * v)
                eps_sum += abs(coeff) * _h(row, ci)
            tv = _v(target, ci)
            if not ok or tv is None:
                exp.append(None); tol.append(0.0)
                continue
            exp.append(sum(parts))
            tol.append(1e-9 + eps_sum + _h(target, ci))
        checks.append(Check(target, desc, exp, tol, [t[0] for t in terms], coeffs,
                            prov=prov))

    def ratio(target, num_row, den_row, desc):
        """target = num_row / den_row, scaled x100 when displayed as a %; EPS rows
        additionally accept a x100 (cents) reading when displayed without '%'.
        All values are compared in EFFECTIVE units (displayed x row scale)."""
        exp, tol, scales = [], [], []
        for ci in range(len(target.vals)):
            nv = _v(num_row, ci) if num_row.vals else _v(num_row, 0)
            if nv is None and ci < len(num_row.vals):
                nv = _v(num_row, 0)
            dv = _v(den_row, ci) if den_row.vals else _v(den_row, 0)
            if dv is None and ci < len(den_row.vals):
                dv = _v(den_row, 0)
            tv = _v(target, ci)
            if nv is None or dv is None or tv is None or dv == 0:
                exp.append(None); tol.append(0.0); scales.append([])
                continue
            raw_ratio = nv / dv
            if nv == 0 or dv == 0:
                prop = 0.0
            else:
                prop = abs(raw_ratio) * (_h(num_row, 0) / abs(nv)
                                         + _h(den_row, 0) / abs(dv))
            if target.pcts[ci]:
                s_list = [100.0]
            else:
                s_list = [1.0]
                if (find_rows([target], EPS_ALIASES)
                        or 'cent' in canonical_label(target.label)
                        or 'cent' in (target.raws[ci] or '').lower()):
                    s_list.append(100.0)
            cands = [(s * raw_ratio, _h(target, ci) + s * prop + 1e-9)
                     for s in s_list]
            exp.append(cands); tol.append(None); scales.append(s_list)
        checks.append(Check(target, desc, exp, tol, [num_row, den_row], scales=scales))

    def growth_check(g, desc):
        """A growth/% change row must equal (cur-prior)/prior*100 for some pair of
        numeric columns; a change row WITHOUT a '%' sign may equally match the
        absolute difference (cur - prior). If the growth label names a base metric
        ('Revenue growth'), only pairs from rows sharing a token with that label
        are accepted; otherwise all two-column rows in the report are tried.
        All values are compared in EFFECTIVE units."""
        stop = ('yoy', 'qoq', 'growth', 'change', 'increase', 'decrease', 'variance',
                'vs', 'prior', 'year', 'percent', 'pct', 'over', 'previous', 'y y')
        gtoks = {t for t in canonical_label(g.label).split() if t not in stop}

        def pairs_of(base):
            out = []
            for a in range(len(base.vals)):
                for b in range(len(base.vals)):
                    va, vb = _v(base, a), _v(base, b)
                    if (a != b and va is not None and vb is not None
                            and vb != 0 and va != 0):
                        diff = va - vb
                        e = diff / vb * 100.0
                        # percent tolerance: base rounding enters only RELATIVELY
                        # (prop), never as an absolute dollar half-unit
                        prop = abs(e) * (_h(base, a) / abs(va)
                                         + _h(base, b) / abs(vb))
                        pct = (e, prop + 1e-9)
                        abs_tol = (_h(base, a) + _h(base, b) + 1e-9)
                        out.append((pct, (diff, abs_tol)))
            return out

        base_pairs = []
        if gtoks:
            for base in rows:
                if base is g or len(base.vals) < 2:
                    continue
                btoks = set(canonical_label(base.label).split())
                if gtoks & btoks:
                    base_pairs.extend(pairs_of(base))
        if not base_pairs:   # unnamed growth row, or no shared-token base: try all
            for base in rows:
                if base is g or len(base.vals) < 2:
                    continue
                base_pairs.extend(pairs_of(base))
        if not base_pairs:
            return  # cannot verify -> treat as leaf (not a candidate)
        exp, tol = [], []
        for ci in range(len(g.vals)):
            if g.vals[ci] is None:
                exp.append(None); tol.append(0.0)
                continue
            cands = []
            for pct, absv in base_pairs:
                cands.append((pct[0], pct[1] + _h(g, ci)))
                if not g.pcts[ci] and not ('%' in (g.raws[ci] or '')):
                    cands.append((absv[0], absv[1] + _h(g, ci)))
            exp.append(cands); tol.append(None)
        checks.append(Check(g, desc, exp, tol, []))

    # ---- income statement identities ----
    if gp and rev and cost:
        additive(gp, "gross profit = revenue - cost of revenue", [(rev, 1.0), (cost, -1.0)])
    if opinc and gp and opex:
        additive(opinc, "operating income = gross profit - total operating expenses",
                 [(gp, 1.0), (opex, -1.0)])
    if opinc and rev and cost and opex:
        additive(opinc, "operating income = revenue - cost - total opex",
                 [(rev, 1.0), (cost, -1.0), (opex, -1.0)])
    if ni and opinc and other and not (pretax or tax):
        # shortcut identity: only valid when the report has no pretax/tax structure
        additive(ni, "net income = operating income + other income, net",
                 [(opinc, 1.0), (other, 1.0)])
    if pretax and opinc and other:
        additive(pretax, "pretax = operating income + other income, net",
                 [(opinc, 1.0), (other, 1.0)])
    if pretax and ni and tax:
        additive(pretax, "pretax = net income + income tax", [(ni, 1.0), (tax, 1.0)])
        additive(ni, "net income = pretax - income tax", [(pretax, 1.0), (tax, -1.0)])
    elif ni and pretax and tax:
        additive(ni, "net income = pretax - income tax", [(pretax, 1.0), (tax, -1.0)])
    if ebitda and opinc and da:
        for erow in find_rows(rows, EBITDA_ALIASES):
            if erow is opinc or erow is da:
                continue
            additive(erow, "EBITDA = operating income + D&A", [(opinc, 1.0), (da, 1.0)])
    if ni and shares:
        # EVERY per-share row (basic AND diluted EPS) is checked against net
        # income and the share count, not just the first match
        for erow in find_rows(rows, EPS_ALIASES):
            if erow is ni or erow is shares:
                continue
            ratio(erow, ni, shares, "EPS = net income / shares")

    # ---- margins and % of revenue ----
    for mrow in rows:
        cl = canonical_label(mrow.label)
        if 'margin' not in cl and '% of revenue' not in cl and 'as a percentage' not in cl:
            continue
        if rev is None:
            continue
        num_row = None
        for key, target_aliases in (('gross', 'gross profit'), ('operating', 'operating income'),
                                    ('net', 'net income'), ('profit', 'net income'),
                                    ('ebitda', 'ebitda'), ('pretax', 'pretax income'),
                                    ('pre tax', 'pretax income'), ('cost', 'cost of revenue'),
                                    ('research', 'rd'), ('r and d', 'rd'), ('rd', 'rd'),
                                    ('sales', 'sales and marketing'), ('marketing', 'sales and marketing'),
                                    ('general', 'general and administrative')):
            if key not in cl:
                continue
            if target_aliases == 'gross profit':
                num_row = gp
            elif target_aliases == 'operating income':
                num_row = opinc
            elif target_aliases == 'net income':
                num_row = ni
            elif target_aliases == 'ebitda':
                num_row = ebitda
            elif target_aliases == 'pretax income':
                num_row = pretax
            elif target_aliases == 'cost of revenue':
                num_row = cost
            elif target_aliases == 'rd':
                num_row = lookup(rows, ['research and development', 'rd', 'research development',
                                        'r and d', 'r d'])
            elif target_aliases == 'sales and marketing':
                num_row = lookup(rows, ['sales and marketing', 'sales marketing',
                                        'marketing and sales', 'selling and marketing'])
            elif target_aliases == 'general and administrative':
                num_row = lookup(rows, ['general and administrative', 'general administrative',
                                        'selling general and administrative',
                                        'selling and administrative'])
            break
        if num_row is None or num_row is mrow:
            continue
        ratio(mrow, num_row, rev, f"{num_row.label} as % of revenue")

    # ---- balance sheet ----
    if ta and tl and te:
        additive(ta, "total assets = total liabilities + total equity", [(tl, 1.0), (te, 1.0)])
    if tl and ta and te:
        additive(tl, "total liabilities = total assets - total equity", [(ta, 1.0), (te, -1.0)])
    if te and ta and tl:
        additive(te, "total equity = total assets - total liabilities", [(ta, 1.0), (tl, -1.0)])

    # ---- cash flow ----
    if ncc and cfo and cfi and cff:
        additive(ncc, "net change in cash = CFO + CFI + CFF",
                 [(cfo, 1.0), (cfi, 1.0), (cff, 1.0)])
    if endc and begc and ncc:
        additive(endc, "ending cash = beginning cash + net change",
                 [(begc, 1.0), (ncc, 1.0)])

    # ---- named ratios and derived KPIs (current ratio, tax rate, ...) ----
    def find_by_sub(sub):
        for rr in rows:
            if sub in canonical_label(rr.label):
                return rr
        return None

    def ratio_terms(target, num_terms, den_row, desc):
        """target = (sum coeff*num_term) / den_row, scaled like ratio().
        Input back-solving is skipped for compound numerators (len(inputs) > 2)."""
        exp, tol, scales = [], [], []
        for ci in range(len(target.vals)):
            nv, ok, eps = 0.0, True, 0.0
            for row, coeff in num_terms:
                v = _v(row, ci)
                if v is None:
                    ok = False
                    break
                nv += coeff * v
                eps += abs(coeff) * _h(row, ci)
            dv = _v(den_row, ci)
            tv = _v(target, ci)
            if dv is None and ci < len(den_row.vals):
                dv = _v(den_row, 0)
            if not ok or dv is None or tv is None or dv == 0:
                exp.append(None); tol.append(0.0); scales.append([])
                continue
            raw_ratio = nv / dv
            if nv == 0 or dv == 0:
                prop = 0.0
            else:
                prop = abs(raw_ratio) * (eps / abs(nv) + _h(den_row, 0) / abs(dv))
            s_list = [100.0] if target.pcts[ci] else [1.0]
            cands = [(s * raw_ratio, _h(target, ci) + s * prop + 1e-9)
                     for s in s_list]
            exp.append(cands); tol.append(None); scales.append(s_list)
        checks.append(Check(target, desc, exp, tol,
                            [den_row] + [r for r, _ in num_terms], scales=scales))

    for rrow in rows:
        cl = canonical_label(rrow.label)
        # additive derived KPI: working capital = current assets - current liabilities
        if 'working capital' in cl:
            ca2 = find_by_sub('current asset')
            cl2 = find_by_sub('current liabilit')
            if ca2 and cl2 and ca2 is not rrow and cl2 is not rrow:
                additive(rrow, "working capital = current assets - current liabilities",
                         [(ca2, 1.0), (cl2, -1.0)])
            continue
        num_row = den_row = None
        if 'current ratio' in cl or 'quick ratio' in cl:
            num_row = find_by_sub('current asset')
            den_row = find_by_sub('current liabilit')
            if num_row and den_row and num_row is not rrow and den_row is not rrow:
                if 'quick ratio' in cl:
                    inv = find_by_sub('inventory')
                    if inv and inv is not rrow:
                        ratio_terms(rrow, [(num_row, 1.0), (inv, -1.0)], den_row,
                                    "quick ratio = (current assets - inventory) / current liabilities")
                        continue
                ratio(rrow, num_row, den_row, "current assets / current liabilities")
                continue
        elif 'return on' in cl and 'equity' in cl:
            num_row, den_row = ni, te
        elif 'return on' in cl and 'asset' in cl:
            num_row, den_row = ni, ta
        elif 'tax rate' in cl:
            num_row, den_row = tax, pretax
        elif 'book value' in cl and 'per share' in cl:
            num_row, den_row = te, shares
        elif 'per share' in cl and ('revenue' in cl or 'sales' in cl):
            num_row, den_row = rev, shares
        elif 'debt' in cl and 'equity' in cl:
            num_row = find_by_sub('total debt') or find_by_sub('debt')
            den_row = te
        if num_row and den_row and num_row is not rrow and den_row is not rrow:
            ratio(rrow, num_row, den_row, f"{num_row.label} / {den_row.label}")

    # ---- unit-aware duplicate-metric cross-scale consistency ----
    # Two rows whose canonical labels resolve to the SAME metric family but with
    # different unit scales must agree in effective units (e.g. 'Net income'
    # vs 'Net income (in thousands)'). This is a plain additive equality; the
    # uniform restoration machinery then finds the wrong value on either side.
    FAMILY_GROUPS = (('revenue', REV_ALIASES, REV_EXCLUDE), ('cost', COST_ALIASES, ()),
                     ('gross profit', GP_ALIASES, ()), ('opex', TOTAL_OPEX_ALIASES, ()),
                     ('operating income', OPINC_ALIASES, ()), ('other income', OTHER_ALIASES, ()),
                     ('pretax', PRETAX_ALIASES, ()), ('tax', TAX_ALIASES, ()),
                     ('net income', NI_ALIASES, ()), ('ebitda', EBITDA_ALIASES, ()),
                     ('danda', DA_ALIASES, ()), ('shares', SHARES_ALIASES, ()),
                     ('eps', EPS_ALIASES, ()), ('total assets', TA_ALIASES, ()),
                     ('total liabilities', TL_ALIASES, ()), ('total equity', TE_ALIASES, ()),
                     ('cfo', CFO_ALIASES, ()), ('cfi', CFI_ALIASES, ()),
                     ('cff', CFF_ALIASES, ()), ('ncc', NCC_ALIASES, ()),
                     ('begin cash', BEGC_ALIASES, ()), ('end cash', ENDC_ALIASES, ()))

    def family_of(row):
        cl = canonical_label(row.label)
        if any(x in cl for x in GROWTH_MARKERS):
            return set()   # derived change rows are not metric duplicates
        fam = set()
        for name, aliases, excl in FAMILY_GROUPS:
            if excl and any(x in cl for x in excl):
                continue
            for a in aliases:
                ca = canonical_label(a)
                if not ca:
                    continue
                if cl == ca or (len(ca) >= 4 and re.search(r'\b' + re.escape(ca) + r'\b', cl)):
                    fam.add(name)
                    break
        return fam

    fam_map = {id(r): family_of(r) for r in rows}
    for i in range(len(rows)):
        r1 = rows[i]
        for j in range(i + 1, len(rows)):
            r2 = rows[j]
            # duplicates: identical canonical names must match in effective
            # value (family invariant - a repeated metric is a cross-check);
            # same-family rows additionally match when their scales differ
            # (unit conversions). Different-name same-family same-scale pairs
            # (basic vs diluted EPS, net income vs attributable) can differ
            # legitimately and are intentionally NOT cross-checked.
            same_name = canonical_label(r1.label) == canonical_label(r2.label)
            if not same_name and not (fam_map[id(r1)] & fam_map[id(r2)]):
                continue
            emit = same_name
            if not emit:
                for ci in range(min(len(r1.vals), len(r2.vals))):
                    if r1.vals[ci] is not None and r2.vals[ci] is not None \
                            and r1.scales[ci] != r2.scales[ci]:
                        emit = True
                        break
            if emit:
                additive(r1, f"duplicate-metric consistency (vs {r2.label})",
                         [(r2, 1.0)])

    # ---- numeric discovery of summary/subtotal blocks ----
    # Any row whose label suggests summary semantics ('total', 'subtotal',
    # 'current', 'net', ...) is tested against contiguous windows of the rows
    # directly above it (stopping at headline/HEAD rows). All window lengths are
    # tried, longest first; the longest window that sums to the row within
    # rounding tolerance yields a normal additive constraint (nested subtotals
    # like Total assets = Current assets + PP&E work because the window includes
    # the subtotal row). When NO window matches, the longest window is still
    # emitted as a candidate constraint - a wrong subtotal (e.g. 'Current
    # assets' off by 10) thus fails its own block check. Because restoration
    # REBUILDS constraints with the candidate value, the corrected document
    # re-derives its matching windows, while alternative fixes leave the
    # candidate constraint failing (this is what pins wrong totals/liabilities/
    # equities and rejects fixing their inputs instead).
    SUMMARY_TOKENS = ('total', 'subtotal', 'current', 'noncurrent', 'non current', 'net')
    SUMMARY_EXCLUDE = ('net income', 'net earnings', 'net profit', 'net loss',
                       'net margin', 'net sales', 'net revenue', 'net revenues',
                       'net income loss')

    def is_summary_gated(cl):
        if not cl:
            return False
        if any(x in cl for x in SUMMARY_EXCLUDE):
            return False
        return any(tok in cl for tok in SUMMARY_TOKENS)

    def window_matches(window, r):
        """True if the window sums to r within rounding tolerance in some column
        (all in EFFECTIVE units)."""
        for ci in range(len(r.vals)):
            rv = _v(r, ci)
            if rv is None:
                continue
            total, eps_sum, ok = 0.0, 0.0, True
            for x in window:
                v = _v(x, ci)
                if v is None:
                    ok = False
                    break
                total += v
                eps_sum += _h(x, ci)
            if ok and abs(rv - total) <= 1e-9 + eps_sum + _h(r, ci):
                return True
        return False

    HEAD_SRC = (REV_ALIASES, COST_ALIASES, GP_ALIASES, OPINC_ALIASES, NI_ALIASES,
                PRETAX_ALIASES, EBITDA_ALIASES, OTHER_ALIASES, TAX_ALIASES,
                TOTAL_OPEX_ALIASES, TA_ALIASES, TL_ALIASES, TE_ALIASES,
                NCC_ALIASES, BEGC_ALIASES, ENDC_ALIASES,
                CFO_ALIASES, CFI_ALIASES, CFF_ALIASES, SHARES_ALIASES, DA_ALIASES)
    HEAD_LABELS = {canonical_label(a) for src in HEAD_SRC for a in src}

    def same_inputs(r, win):
        win_ids = {id(x) for x in win}
        return any(c.target is r and {id(x) for x in c.inputs} == win_ids for c in checks)

    # confirmed = rows that were verified as summaries (a matching window exists).
    # Windows for rows BELOW a confirmed summary collapse to the strip from the
    # topmost confirmed summary down to the row: this keeps nested subtotals
    # (Total assets = Current assets + PP&E) while preventing spurious candidate
    # checks for unrelated summary-labeled rows (e.g. 'Total current
    # liabilities' placed directly under an asset block would otherwise be
    # 'matched' to Cash+AR+Inventory+Current assets and block every answer).
    #
    # MATCHING windows are FROZEN from the first build (structure of the
    # document): restoration rebuilds keep the same window for every row that
    # matched originally and recompute expectations from the hypothesis values,
    # so wrong hypotheses cannot make a verified block check disappear. Rows
    # with NO originally matching window follow the dynamic candidate path on
    # every rebuild (this is what lets a corrected subtotal find its window).
    struct_key = tuple((r.table, r.rowidx, canonical_label(r.label)) for r in rows)
    if _BLOCK_FROZEN['key'] != struct_key:
        _BLOCK_FROZEN['key'] = struct_key
        _BLOCK_FROZEN['windows'] = {}
        _BLOCK_FROZEN['locked'] = False
    # first = the initial structure-discovery build (records frozen windows);
    # afterwards (restorations, strict pass) recording is disabled so rebuilds
    # cannot mutate the frozen window set
    first = not _BLOCK_FROZEN['locked']
    frozen_windows = _BLOCK_FROZEN['windows']

    confirmed = set()
    for tb in by_table.values():
        confirmed = {r for r in confirmed if r.table == tb[0].table}
        for r in tb:
            cl = canonical_label(r.label)
            if not is_summary_gated(cl):
                continue
            if id(r) in frozen_windows:
                # frozen matching window from the original document structure
                additive(r, "summary row = sum of the block above",
                         [(x, 1.0) for x in frozen_windows[id(r)]])
                confirmed.add(r)
                continue
            # maximal contiguous segment of rows directly above r (no HEAD rows)
            segment = []
            for x in reversed(tb):
                if x.rowidx >= r.rowidx:
                    continue
                if canonical_label(x.label) in HEAD_LABELS:
                    break
                segment.append(x)
            segment.reverse()
            # collapse to the strip from the topmost confirmed summary down to r
            cidx = [i for i, x in enumerate(segment) if x in confirmed]
            if cidx:
                segment = segment[min(cidx):]
            if len(segment) < 2:
                continue
            # longest-first: find the longest matching window
            match = None
            for L in range(len(segment), 1, -1):
                for i in range(len(segment) - L + 1):
                    win = segment[i:i + L]
                    if window_matches(win, r):
                        match = win
                        break
                if match is not None:
                    break
            win = match if match is not None else segment
            if match is None:
                # Candidate (non-matching) block checks are only safe when the
                # window consists of primitive rows: confirmed summaries or
                # rows bound by NO other check and carrying no summary label.
                # Otherwise the window is a spurious catch-all (e.g. 'Total
                # liabilities' matched against [Current assets, TCL, Working
                # capital, LTD]) that would persist in every rebuild and block
                # the true answer.
                bad = [x for x in segment
                       if x not in confirmed
                       and (id(x) in {id(c.target) for c in checks}
                            or is_summary_gated(canonical_label(x.label)))]
                if bad:
                    continue
            if same_inputs(r, win):
                continue
            if match is not None:
                additive(r, "summary row = sum of the block above",
                         [(x, 1.0) for x in win])
                confirmed.add(r)
                if first:
                    frozen_windows[id(r)] = win
            elif candidates:
                additive(r, "summary row = sum of the block above (candidate)",
                         [(x, 1.0) for x in win], prov='candidate')

    if first:
        _BLOCK_FROZEN['locked'] = True

    # ---- growth / change rows (need a two-column base somewhere) ----
    skip_growth = {canonical_label(a) for a in (NCC_ALIASES + BEGC_ALIASES + ENDC_ALIASES)}
    for g in rows:
        cl = canonical_label(g.label)
        if not re.search(r'\b(yoy|qoq|growth|change|increase|decrease|variance|vs prior year)\b', cl):
            continue
        if cl in skip_growth or find_rows([g], EPS_ALIASES):
            continue
        growth_check(g, "growth/change row vs prior-period columns")

    return checks


# ----------------------------------------------------------------------------
# 6. Decision: the restoration criterion
# ----------------------------------------------------------------------------

def count_failures(rows, checks):
    """Number of check/column evaluations that fail on the CURRENT values."""
    n = 0
    for c in checks:
        for ci in range(len(c.target.vals)):
            if c.target.vals[ci] is None or c.expected[ci] is None:
                continue
            if check_pass(c, ci) is False:
                n += 1
    return n


def count_failures_with_replacement(rows, row, col, new_val, candidates=True):
    """Rebuild ALL constraints with row.vals[col] := new_val and count failures.
    Expectations are recomputed, so the other (correct) rows propagate.
    candidates=False disables candidate-class block checks (strict pass)."""
    old = row.vals[col]
    row.vals[col] = new_val
    try:
        checks = build_checks(rows, candidates=candidates)
        return count_failures(rows, checks)
    finally:
        row.vals[col] = old


def _select(accepted):
    """(row, col) when exactly one row is accepted; None otherwise."""
    rows_uniq = {r for r, ci in accepted}
    if len(rows_uniq) == 1:
        r = next(iter(rows_uniq))
        return r, next(ci for rr, ci in accepted if rr is r)
    return None


def _decide(rows, checks, candidates_flag, verbose):
    """Evaluate all checks, collect failed (check, column) pairs, build the
    implied-value map (in DISPLAYED units) for every touched cell, and run the
    restoration test. Returns (failed, impl, accepted, bound_cells, total_cells)."""
    total_cells = sum(1 for r in rows for v in r.vals if v is not None)
    bound_cells = set()
    for c in checks:
        for ci in range(len(c.target.vals)):
            if c.target.vals[ci] is not None and c.expected[ci] is not None:
                bound_cells.add((id(c.target), ci))
    if verbose:
        print(f"[info] parsed {len(rows)} metric rows, {len(checks)} checks, "
              f"coverage {len(bound_cells)}/{total_cells} cells bound by >=1 check")
        for r in rows:
            nb = sum(1 for (rid, ci) in bound_cells if rid == id(r))
            print(f"  row: t{r.table} line={r.line} label={r.label!r} raw={r.raws} "
                  f"scales={r.scales} checks={nb}")

    for c in checks:
        for ci in range(len(c.target.vals)):
            if c.target.vals[ci] is None or c.expected[ci] is None:
                continue
            ok = check_pass(c, ci)
            if ok is None:
                continue
            if verbose:
                exp = c.expected[ci]
                exp_str = (f"{exp:.8g}" if not isinstance(exp, list)
                           else '|'.join(f"{e:.8g}±{t:.3g}" for e, t in exp))
                print(f"  [{'PASS' if ok else 'FAIL'}] line {c.target.line} "
                      f"{c.target.label!r} col{ci}: displayed={c.target.vals[ci]} "
                      f"expected~{exp_str}  ({c.desc})")

    failed = [(c, ci) for c in checks for ci in range(len(c.target.vals))
              if c.target.vals[ci] is not None and c.expected[ci] is not None
              and check_pass(c, ci) is False]

    impl = {}   # (row, ci) -> set of implied DISPLAYED-unit values

    def add_impl(row, ci, v):
        if v is None or abs(v) > 1e15:
            return
        impl.setdefault((row, ci), set()).add(round(v, 9))

    for c, ci in failed:
        tv = _v(c.target, ci)                     # effective displayed target
        if tv is None:
            continue
        tscale = c.target.scales[ci]
        # target side: expected variants (effective) -> display units
        if isinstance(c.expected[ci], list):
            for e, t in c.expected[ci]:
                add_impl(c.target, ci, e / tscale)
        else:
            add_impl(c.target, ci, c.expected[ci] / tscale)
        # additive input side: back-solve from the TARGET'S DISPLAYED (effective)
        if c.coeffs:
            for row, k in c.coeffs:
                if k == 0 or ci >= len(row.vals) or row.vals[ci] is None:
                    continue
                other = sum(cf * (_v(r2, ci) if r2 is not None else 0.0)
                            for r2, cf in c.coeffs if r2 is not row)
                add_impl(row, ci, (tv - other) / k / row.scales[ci])
        # ratio input side: back-solve numerator and denominator per scale
        if c.scales is not None and len(c.inputs) == 2 and tv != 0:
            num_row, den_row = c.inputs
            nv = _v(num_row, ci)
            dv = _v(den_row, ci)
            if nv is None and ci < len(num_row.vals):
                nv = _v(num_row, 0)
            if dv is None and ci < len(den_row.vals):
                dv = _v(den_row, 0)
            if nv is not None and dv is not None:
                for s in (c.scales[ci] or [1.0]):
                    add_impl(num_row, ci, tv * dv / s / num_row.scales[ci])
                    add_impl(den_row, ci, nv * s / tv / den_row.scales[ci])

    # ---- restoration test: accept a cell iff some implied value fixes everything ----
    accepted = []
    for (row, ci) in sorted(impl.keys(), key=lambda rc: (rc[0].line or '', rc[1])):
        for v in impl[(row, ci)]:
            if count_failures_with_replacement(rows, row, ci, v, candidates=candidates_flag) == 0:
                accepted.append((row, ci))
                break

    if verbose and failed:
        print("[info] implied-value hypotheses per cell (displayed units):")
        for (row, ci) in sorted(impl.keys(), key=lambda rc: (rc[0].line or '', rc[1])):
            print(f"  cell line {row.line} '{row.label}' col{ci}: "
                  f"displayed={row.raws[ci]} implied={sorted(impl[(row, ci)])}")

    return failed, impl, accepted, bound_cells, total_cells


def solve(rows, verbose=False):
    """Uniform restoration criterion with a provenance-governed second pass:
    whenever a candidate-class block check participates in the failures, the
    decision is cross-checked against a strict build (candidate block checks
    disabled). Disagreement is reported with evidence instead of an answer."""
    # per-solve scope for frozen block windows (no process-global leakage)
    _BLOCK_FROZEN['key'] = None
    _BLOCK_FROZEN['windows'] = {}
    _BLOCK_FROZEN['locked'] = False

    checks = build_checks(rows)
    failed, impl, accepted, bound_cells, total_cells = _decide(rows, checks, True, verbose)
    answer = _select(accepted)

    candidate_involved = any(c.prov == 'candidate' for c, ci in failed)
    if candidate_involved:
        s_checks = build_checks(rows, candidates=False)
        sfailed, simpl, saccepted, _, _ = _decide(rows, s_checks, False, False)
        s_answer = _select(saccepted)
        full_only_candidate = bool(failed) and all(c.prov == 'candidate' for c, ci in failed)
        if answer and s_answer is None and not sfailed and full_only_candidate:
            # subtotal-only document: the only failures are candidate block
            # checks that re-verify under the repair (window then matches).
            print("[info] answer derived via candidate-class block check; "
                  "re-confirmed (window matches under repair)")
        elif answer and s_answer and s_answer[0] is answer[0] and s_answer[1] == answer[1]:
            pass   # full and strict passes agree
        else:
            print("[error] candidate-class block checks are involved and the "
                  "strict pass disagrees - refusing to answer:")
            print(f"  full pass  (with candidate block checks): "
                  f"{_fmt_cells(accepted, impl)}")
            print(f"  strict pass (candidate block checks disabled): "
                  f"{_fmt_cells(saccepted, simpl)}")
            if not answer and s_answer:
                print("[info] the strict pass points at the likely answer while the "
                      "full pass is blocked by an interrupted-subtotal candidate "
                      "check; inspect the evidence manually.")
            print(f"[info] coverage: {len(bound_cells)}/{total_cells} cells bound by >=1 check")
            return 2
    else:
        s_answer = None

    if answer is not None:
        answer_row, answer_col = answer
        line = answer_row.line if answer_row.line is not None else '?'
        out_val = strip_formatting(answer_row.raws[answer_col])
        print(f"[answer] line {line} col{answer_col}: {answer_row.raws[answer_col]}  "
              f"->  {line},{out_val}")
        return line, out_val

    # ---- no unique answer: report everything ----
    if not failed:
        print("[error] no constraint failed - the document appears internally "
              "consistent (out of family) or no relationship was recognized.")
    elif not accepted:
        print("[error] constraints failed but no single-cell correction restores "
              "consistency - re-check parsing/relationships.")
    else:
        print("[error] ambiguous: several single-cell corrections restore consistency:")
        for row, ci in accepted:
            print(f"  - line {row.line} '{row.label}' col{ci}: displayed "
                  f"'{row.raws[ci]}' implied={sorted(impl[(row, ci)])}")
    print(f"[info] coverage: {len(bound_cells)}/{total_cells} cells bound by >=1 check")
    return 2


def _fmt_cells(accepted, impl):
    if not accepted:
        return 'none'
    parts = []
    for row, ci in accepted:
        parts.append(f"line {row.line} '{row.label}' col{ci} "
                     f"(displayed {row.raws[ci]}, implied {sorted(impl.get((row, ci), []))})")
    return '; '.join(parts)


# ----------------------------------------------------------------------------
# 7. Main
# ----------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--html', help='path to the HTML report (default: the only *.html in /app)')
    ap.add_argument('--out', help='output file (default /app/value.txt)')
    ap.add_argument('--task', help='path to task.yaml: auto-detect --html and --out from its instruction text')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args(argv)

    html_path, out_path = args.html, args.out
    if args.task and os.path.isfile(args.task):
        text = open(args.task, encoding='utf-8', errors='replace').read()
        # backticked paths first (most reliable), then plain /app paths
        for m in re.finditer(r'`(/app/[^`\s]+\.html)`', text):
            if html_path is None:
                html_path = m.group(1)
        m = re.search(r'`(/app/[^`\s]+\.(?:txt|out|ans|answer|result))`', text)
        if m and out_path is None:
            out_path = m.group(1)
        if html_path is None:
            m = re.search(r'(/app/[A-Za-z0-9_./-]+\.html)', text)
            if m:
                html_path = m.group(1)
        if out_path is None:
            m = re.search(r'(/app/[A-Za-z0-9_./-]+\.(?:txt|out|ans|answer|result))', text)
            if m:
                out_path = m.group(1)
    if not html_path:
        cand = sorted(glob.glob('/app/*.html'))
        if len(cand) == 1:
            html_path = cand[0]
        elif cand:
            print('[error] multiple html files in /app; use --html', file=sys.stderr)
            return 2
    if not html_path or not os.path.isfile(html_path):
        print(f'[error] report not found: {html_path}', file=sys.stderr)
        return 2
    out_path = out_path or '/app/value.txt'
    print(f'[info] report={html_path} output={out_path} '
          f'(override with --html/--out if the instruction differs)')

    text = open(html_path, encoding='utf-8', errors='replace').read()
    doc_scale = doc_unit_scale(text)
    tp = TableParser()
    tp.feed(text)
    tables = tp.tables
    if not tables:
        # report has no <table> elements: fall back to <tr>/<td> anywhere in the doc
        tables = [[]]
        for rb in re.findall(r'<tr[^>]*>(.*?)</tr>', text, flags=re.S | re.I):
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', rb, flags=re.S | re.I)
            cells = [re.sub(r'<[^>]+>', ' ', html.unescape(c)) for c in cells]
            tables[0].append([re.sub(r'\s+', ' ', c).strip() for c in cells])
    rows = parse_rows(tables, doc_scale=doc_scale)
    if not rows:
        print('[error] no metric rows found in the report', file=sys.stderr)
        return 2

    result = solve(rows, verbose=args.verbose)
    if isinstance(result, tuple):
        line, val = result
        if line == '?':
            print('[error] the incorrect metric row has no line number', file=sys.stderr)
            return 2
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(f"{line},{val}\n")
        print(f"[written] {out_path}: {line},{val}")
        return 0
    return result


if __name__ == '__main__':
    sys.exit(main())