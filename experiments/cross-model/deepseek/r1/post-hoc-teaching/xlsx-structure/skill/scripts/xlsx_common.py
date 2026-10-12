#!/usr/bin/env python3
"""Shared machinery for xlsx-structure family tasks (openpyxl).

Verified pieces: block detection, row-local formula evaluation (matches cached
values on the anchor case), style-preserving row relocation, float cleaning,
a preservation diff harness, merged-cell capture/restore, row-surgery repair,
zip-manifest preflight, generic table-transform primitives, and a full
verification battery (verify_output) used by all per-semantics solver scripts.
"""
import math
import re
import zipfile
from copy import copy

import openpyxl
from openpyxl.utils import column_index_from_string
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import range_boundaries
from openpyxl.utils.cell import coordinate_from_string, get_column_letter

REF_RE = re.compile(r'([A-Za-z]{1,3})(\d*)')


def load_dual(path):
    """Return (wb_formulas, wb_cached). wb_cached is data_only=True (cached
    values, None where absent). Use wb_formulas for writing."""
    return (openpyxl.load_workbook(path),
            openpyxl.load_workbook(path, data_only=True))


def parse_a1(rng):
    """'A1:H85' -> (r1, r2, c1, c2) with 1-based inclusive bounds."""
    m = re.match(r'^([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)$', rng.strip())
    if not m:
        raise ValueError(f'bad A1 range: {rng!r}')
    c1 = column_index_from_string(m.group(1)); r1 = int(m.group(2))
    c2 = column_index_from_string(m.group(3)); r2 = int(m.group(4))
    return r1, r2, c1, c2


def strict_key(v, coord=''):
    """Convert a declared key (sort/filter/alignment) to a number, or RAISE.

    The family's declared selection rules require an *evaluated numeric* key:
    stored numbers pass, numeric TEXT coerces (Excel scalar coercion), and a
    blank or non-numeric key raises with the cell address. A plausible wrong
    key (e.g. text silently sorted as 0.0) would reorder the answer with no
    signal — implement-or-raise applies to every path that feeds the answer,
    not just formula evaluation."""
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        raise ValueError(f'blank sort key at {coord}')
    if isinstance(v, str):
        s = v.strip()
        if not s:
            raise ValueError(f'blank sort key at {coord}')
        try:
            return float(s)
        except ValueError:
            raise ValueError(f'non-numeric sort key {s!r} at {coord}: '
                             f'"evaluated numeric" ordering cannot coerce text')
    raise ValueError(f'sort key of type {type(v).__name__} at {coord}')


def clean_num(v, digits=10):
    """Round a computed float to a clean decimal; int for integral values."""
    if isinstance(v, float):
        v = round(v, digits)
        if v.is_integer():
            v = int(v)
    return v


_PENDING = object()  # cycle marker


def _scalar_number(v):
    """Excel scalar-arithmetic coercion: empty -> 0.0, numbers pass, booleans
    -> 1/0; any TEXT or other non-numeric raises (Excel #VALUE!). Implement-or-
    raise: a plausible wrong number is worse than an exception."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    raise ValueError(f'non-numeric value {v!r} in arithmetic (Excel would '
                     f'raise #VALUE!)')


def _range_numbers(vals):
    """Excel range-aggregate semantics: ONLY stored numbers participate;
    blanks and text inside a range are IGNORED (a stored 0 participates).
    Returns the participating numbers."""
    return [float(v) for v in vals
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _raw_value(ws, col, refrow, row, rowvals, cache):
    """Raw cell value for the evaluator. Same-row refs prefer already-evaluated
    rowvals values (dependency order); nested formulas evaluate recursively
    with the SHARED cache so memoization and cycle detection work globally."""
    if refrow == row and rowvals is not None and col in rowvals:
        return rowvals[col]
    v = ws.cell(row=refrow, column=col).value
    if isinstance(v, str) and v.startswith('='):
        return evaluate_formula(v, ws, refrow, rowvals, cache)
    return v


def evaluate_formula(text, ws, row, rowvals=None, cache=None):
    """Evaluate a row-local arithmetic formula such as '=B1+C1' or '=B+C'.

    - Refs with an explicit row number use that absolute row; bare column refs
      (e.g. 'B') use the formula's own row (row-local).
    - Refs to cells already evaluated in this row (rowvals dict col->value) are
      resolved from there, so D=B+C is available when evaluating F=D+E.
    - Refs to plain cells read the sheet; nested formulas are evaluated
      recursively (memoized, cycle-guarded).
    - Supports + - * / ( ) unary minus, trailing % (divide by 100), and the
      functions SUM, AVERAGE, MIN, MAX, ABS, ROUND over explicit refs or
      same-row ranges such as SUM(B1:F1). ROUND = Excel round-half-away.
    - Excel semantics (implement-or-raise): empty cells count as 0 in SCALAR
      arithmetic but are IGNORED inside range aggregates; text anywhere raises
      (#VALUE!); AVERAGE/MIN/MAX over a range with no numbers raise
      (#DIV/0! / #NUM!); circular references raise (#CIRC!). Unparsable or
      unsupported constructs raise ValueError so the agent notices instead of
      silently writing a number Excel would not produce.
    """
    text = str(text)
    body = text[1:] if text.startswith('=') else text
    key = (row, text)
    if cache is None:
        cache = {}
    if key in cache:
        if cache[key] is _PENDING:
            raise ValueError(f'circular reference in {text!r} at row {row} '
                             f'(Excel #CIRC!)')
        return cache[key]
    cache[key] = _PENDING  # cycle marker

    def resolve(col, refrow):
        """Excel scalar value of one cell (col, refrow), may raise on text."""
        return _scalar_number(_raw_value(ws, col, refrow, row, rowvals, cache))

    tokens = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or ch == '.':
            j = i
            while j < len(body) and (body[j].isdigit() or body[j] == '.'):
                j += 1
            tokens.append(('num', float(body[i:j]))); i = j; continue
        if ch.isalpha():
            j = i
            while j < len(body) and (body[j].isalpha() or body[j].isdigit()):
                j += 1
            name = body[i:j].upper()
            if j < len(body) and body[j] == '(':
                tokens.append(('func', name)); i = j; continue   # function call
            # cell ref (letters only; digits belong to the row number)
            j = i
            while j < len(body) and body[j].isalpha():
                j += 1
            letters = body[i:j]
            k = j
            while k < len(body) and body[k].isdigit():
                k += 1
            refrow = int(body[j:k]) if body[j:k] else row
            col = column_index_from_string(letters.upper())
            if k < len(body) and body[k] == ':' and k + 1 < len(body) and body[k + 1].isalpha():
                # range like B1:F1 or B:F (second ref)
                j2 = k + 1
                while j2 < len(body) and body[j2].isalpha():
                    j2 += 1
                letters2 = body[k + 1:j2]
                k3 = j2
                while k3 < len(body) and body[k3].isdigit():
                    k3 += 1
                refrow2 = int(body[j2:k3]) if body[j2:k3] else row
                col2 = column_index_from_string(letters2.upper())
                tokens.append(('range', (refrow, col, refrow2, col2)))
                i = k3; continue
            tokens.append(('ref', (refrow, col)))
            i = k; continue
        if ch in '+-*/()%,':
            tokens.append(('op', ch)); i += 1; continue
        raise ValueError(f'cannot parse formula {text!r} at {body[i:]!r}')

    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def expr():
        v = term()
        while peek() and peek()[1] in '+-':
            op = peek()[1]; pos[0] += 1
            v = v + term() if op == '+' else v - term()
        return v

    def term():
        v = factor()
        while peek() and peek()[1] in '*/':
            op = peek()[1]; pos[0] += 1
            r = factor()
            v = v * r if op == '*' else (0.0 if r == 0 else v / r)
        return v

    def args():
        """Parse comma-separated argument values of a function call."""
        vals = [expr()]
        while peek() and peek()[1] == ',':
            pos[0] += 1
            vals.append(expr())
        return vals

    def _agg(name, vs, op):
        nums = _range_numbers(vs)          # blanks/text ignored in ranges
        if name in ('AVERAGE', 'MIN', 'MAX') and not nums:
            err = '#DIV/0!' if name == 'AVERAGE' else '#NUM!'
            raise ValueError(f'{name} over a range with no numeric values '
                             f'(Excel {err})')
        return op(nums)

    FUNCS = {
        'SUM': lambda vs: _agg('SUM', vs, lambda ns: sum(ns)),
        'AVERAGE': lambda vs: _agg('AVERAGE', vs,
                                   lambda ns: sum(ns) / len(ns)),
        'MIN': lambda vs: _agg('MIN', vs, min),
        'MAX': lambda vs: _agg('MAX', vs, max),
        'ABS': lambda vs: abs(vs[0]),
        'ROUND': lambda vs: excel_round(vs[0], int(vs[1])),
    }

    def factor():
        t = peek()
        if t is None:
            raise ValueError(f'empty formula {text!r}')
        if t[1] == '-':
            pos[0] += 1; v = -factor()
        elif t[1] == '+':
            pos[0] += 1; v = factor()
        elif t[1] == '(':
            pos[0] += 1; v = expr()
            if not peek() or peek()[1] != ')':
                raise ValueError(f'bad parens in {text!r}')
            pos[0] += 1
        elif t[0] == 'num':
            pos[0] += 1; v = t[1]
        elif t[0] == 'ref':
            pos[0] += 1; v = resolve(t[1][1], t[1][0])
        elif t[0] == 'range':
            pos[0] += 1
            # horizontal/cell range: (r1, c1, r2, c2)
            r1, c1, r2, c2 = t[1]
            vals = []
            for rr in range(min(r1, r2), max(r1, r2) + 1):
                for cc in range(min(c1, c2), max(c1, c2) + 1):
                    vals.append(_raw_value(ws, cc, rr, row, rowvals, cache))
            return vals  # bare range value; only usable as a function argument
        elif t[0] == 'func':
            name = t[1]
            pos[0] += 1
            if not peek() or peek()[1] != '(':
                raise ValueError(f'function {name} without ( in {text!r}')
            pos[0] += 1
            v = expr()
            vals = [v] if not isinstance(v, list) else v
            while peek() and peek()[1] == ',':
                pos[0] += 1
                a = expr()
                vals.extend(a if isinstance(a, list) else [a])
            if not peek() or peek()[1] != ')':
                raise ValueError(f'unclosed args for {name} in {text!r}')
            pos[0] += 1
            if name not in FUNCS:
                raise ValueError(f'unsupported function {name} in {text!r}')
            v = FUNCS[name](vals)
        else:
            raise ValueError(f'unexpected token {t} in {text!r}')
        if peek() and peek()[1] == '%' and not isinstance(v, list):
            pos[0] += 1
            v = v / 100.0
        return v

    res = expr()
    if pos[0] != len(tokens):
        raise ValueError(f'trailing tokens in {text!r}: {tokens[pos[0]:]}')
    cache[key] = res
    return res


def excel_round(x, ndigits):
    """Excel ROUND: half away from zero."""
    if ndigits == 0:
        return float(math.floor(x + 0.5)) if x >= 0 else float(math.ceil(x - 0.5))
    p = 10 ** ndigits
    return math.floor(x * p + 0.5) / p if x >= 0 else math.ceil(x * p - 0.5) / p


def is_formula_like(v):
    return isinstance(v, str) and v.startswith('=')


def find_blocks(ws, r1, r2, c1, c2):
    """Split rows r1..r2 into blocks separated by fully blank rows (blankness
    judged across columns c1..c2 only). Returns [(start, end), ...]."""
    blocks, start = [], None
    for r in range(r1, r2 + 1):
        blank = all(ws.cell(row=r, column=c).value is None
                    for c in range(c1, c2 + 1))
        if not blank and start is None:
            start = r
        if blank and start is not None:
            blocks.append((start, r - 1)); start = None
    if start is not None:
        blocks.append((start, r2))
    return blocks


def snapshot_rows(ws, rows, c1, c2):
    """Full per-cell state (style, value, hyperlink, comment) for each row."""
    snap = []
    for r in rows:
        row_snap = []
        for c in range(c1, c2 + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell, MergedCell):
                raise ValueError(
                    f'cell {cell.coordinate} is a read-only MergedCell: run '
                    f'capture_merges() on the write footprint before '
                    f'snapshot/write on this range')
            row_snap.append((copy(cell._style), cell.value,
                             cell.hyperlink, cell.comment))
        snap.append(row_snap)
    return snap


def write_rows(ws, rows, snap, order, formula_cols=(), evaluated=None,
               clean=True, start_col=1):
    """Write rows in a new order, preserving styles.

    snap is the output of snapshot_rows(ws, rows_original, c1, c2); each
    snapshot item is (style, value, hyperlink, comment) in column order
    c1..c2 (pass start_col=c1).
    `order` lists the ORIGINAL row numbers in the desired new order (a
    permutation of rows), e.g. sorted(rows, key=...).
    formula_cols: 1-based columns whose values must be numbers — formula cells
    / '=...' text are replaced by evaluated values from `evaluated`, a dict
    {original_row: {col: value}} (caller computes these on original cells
    before reordering).
    """
    pos = {r: i for i, r in enumerate(rows)}
    for dst_r, orig_r in zip(rows, order):
        ev = (evaluated or {}).get(orig_r, {})
        src = snap[pos[orig_r]]
        for ci, (style, val, hl, cm) in enumerate(src):
            col = start_col + ci
            cell = ws.cell(row=dst_r, column=col)
            cell._style = style
            if col in formula_cols and isinstance(val, str) and val.startswith('='):
                val = ev.get(col, val)
                if clean:
                    val = clean_num(val)
            cell.value = val
            if hl is not None:
                cell.hyperlink = copy(hl)
            if cm is not None:
                cell.comment = copy(cm)


def row_tuple(ws, r, c1, c2, digits=9):
    """Normalized tuple of a row's values (floats rounded) for multiset checks."""
    out = []
    for c in range(c1, c2 + 1):
        v = ws.cell(row=r, column=c).value
        if isinstance(v, float):
            v = round(v, digits)
        out.append(v)
    return tuple(out)


def input_row_tuple(wsF, wsV, r, c1, c2, formula_cols=(), cache=None):
    """Normalized tuple of an INPUT row for multiset/order checks.

    Uses the cached value (wsV) where present; when a formula cell has NO cached
    value (openpyxl-generated inputs), evaluate it row-locally from wsF so the
    tuple is comparable with the evaluated output values."""
    out = []
    for c in range(c1, c2 + 1):
        v = wsV.cell(row=r, column=c).value
        if v is None and c in formula_cols:
            f = wsF.cell(row=r, column=c).value
            if isinstance(f, str) and f.startswith('='):
                rv = {cc: wsF.cell(row=r, column=cc).value
                      for cc in range(c1, c2 + 1)}
                for cc in sorted(formula_cols):
                    vv = rv.get(cc)
                    if isinstance(vv, str) and vv.startswith('='):
                        rv[cc] = evaluate_formula(vv, wsF, r, rv, cache)
                v = rv.get(c)
        if isinstance(v, float):
            v = round(v, 9)
        out.append(v)
    return tuple(out)


def verify_preservation(inp, out, table_r1, table_r2, table_c1, table_c2):
    """Assert values outside the declared table range are unchanged and that
    style-relevant workbook state (bold fonts, widths, dims, merges, panes,
    filter) matches. Returns list of human-readable issues (empty = clean)."""
    issues = []
    inp_max_r, inp_max_c = inp.max_row, inp.max_column
    out_max_r, out_max_c = out.max_row, out.max_column
    if (inp_max_r, inp_max_c) != (out_max_r, out_max_c):
        issues.append(f'dimensions changed: {(inp_max_r, inp_max_c)} -> '
                      f'{(out_max_r, out_max_c)}')
    for r in range(1, max(inp_max_r, out_max_r) + 1):
        for c in range(1, max(inp_max_c, out_max_c) + 1):
            if table_r1 <= r <= table_r2 and table_c1 <= c <= table_c2:
                continue
            a, b = inp.cell(row=r, column=c).value, out.cell(row=r, column=c).value
            if isinstance(a, float):
                a = round(a, 9)
            if isinstance(b, float):
                b = round(b, 9)
            if a != b:
                issues.append(f'outside-range value changed at {r},{c}: {a!r} != {b!r}')
                if len(issues) > 20:
                    return issues
    if {c: inp.column_dimensions[c].width for c in inp.column_dimensions} != \
       {c: out.column_dimensions[c].width for c in out.column_dimensions}:
        issues.append('column widths changed')
    if {r: inp.row_dimensions[r].height for r in inp.row_dimensions} != \
       {r: out.row_dimensions[r].height for r in out.row_dimensions}:
        issues.append('row heights changed')
    if set(inp.merged_cells.ranges) != set(out.merged_cells.ranges):
        issues.append('merged ranges changed')
    if inp.freeze_panes != out.freeze_panes:
        issues.append('freeze panes changed')
    if inp.auto_filter.ref != out.auto_filter.ref:
        issues.append('auto filter changed')
    if (inp.print_area or '') != (out.print_area or ''):
        issues.append('print area changed')
    return issues


def verify_no_formulas(ws, r1, r2, c1, c2):
    """Return coordinates of leftover formula cells / '=' strings in range."""
    bad = []
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and v.startswith('='):
                bad.append((r, c, v))
    return bad


# ---------------------------------------------------------------------------
# Merged cells: non-anchor cells of a merged range are read-only MergedCell
# objects (value always None; assignment raises AttributeError). They must be
# unmerged before any write to their coordinates and re-merged afterwards.
# openpyxl also discards the parsed per-cell styles of merged regions on load
# (they become default-styled MergedCell objects), so re-merging alone can
# change edge borders; saving the per-cell styles and re-applying them after
# restore keeps whatever in-memory styling existed.
# ---------------------------------------------------------------------------

def merged_touching(ws, rows, cols):
    """Merged ranges intersecting the rectangle rows x cols (1-based)."""
    rmin, rmax = min(rows), max(rows)
    cmin, cmax = min(cols), max(cols)
    return [r for r in ws.merged_cells.ranges
            if not (r.max_row < rmin or r.min_row > rmax
                    or r.max_col < cmin or r.min_col > cmax)]


def capture_merges(ws, rows, cols):
    """Unmerge every merged range touching the write footprint (rows x cols);
    return the data needed to restore them (bounds + per-cell styles).
    MUST run before snapshot/write touches those coordinates."""
    saved = []
    for r in merged_touching(ws, rows, cols):
        styles = {(rr, cc): copy(ws.cell(row=rr, column=cc)._style)
                  for rr in range(r.min_row, r.max_row + 1)
                  for cc in range(r.min_col, r.max_col + 1)}
        saved.append((r.min_row, r.min_col, r.max_row, r.max_col, styles))
        ws.unmerge_cells(start_row=r.min_row, start_column=r.min_col,
                         end_row=r.max_row, end_column=r.max_col)
    return saved


def restore_merges(ws, saved, shift=None):
    """Re-merge captured ranges and re-apply their per-cell styles.
    shift: optional (d1, d2) deleted-row span whose effect on the bounds
    should be applied (rows below d2 move up); pass None to restore at the
    original bounds. For transposition, pass a pre-shifted saved list."""
    for r1, c1, r2, c2, styles in saved:
        b = (r1, c1, r2, c2)
        if shift is not None:
            b = shift_bounds(b, shift[0], shift[1])
        ws.merge_cells(start_row=b[0], start_column=b[1],
                       end_row=b[2], end_column=b[3])
        for (rr, cc), st in styles.items():
            ws.cell(row=rr, column=cc)._style = st


# ---------------------------------------------------------------------------
# Row surgery repair: ws.delete_rows/insert_rows do NOT retarget merged
# ranges, auto-filter refs, freeze panes, or print areas. Repair them
# explicitly; surface straddling artifacts as errors instead of patching.
# ---------------------------------------------------------------------------

def shift_bounds(bounds, d1, d2):
    """New (r1, c1, r2, c2) after deleting rows d1..d2 (inclusive).
    Raises ValueError if the range straddles the deleted span: that artifact
    must be unmerged/recomputed from the table before cutting."""
    r1, c1, r2, c2 = bounds
    if r1 <= d2 and r2 >= d1:
        raise ValueError(f'range {bounds} straddles deleted rows {d1}-{d2}: '
                         f'unmerge or recompute it from the table before cutting')
    delta = sum(1 for r in range(d1, d2 + 1) if r < r1)
    return (r1 - delta, c1, r2 - delta, c2)


def shift_a1(rng, d1, d2):
    """Shift an A1-style range string ('A1:C5' or "'Sheet'!$A$1:$C$5") after
    deleting rows d1..d2. Raises on straddle."""
    prefix = ''
    body = rng.strip()
    if '!' in body:
        prefix, body = body.rsplit('!', 1)
        prefix += '!'
    min_col, min_row, max_col, max_row = range_boundaries(body)  # NOTE order!
    r1n, c1n, r2n, c2n = shift_bounds(
        (min_row, min_col, max_row, max_col), d1, d2)
    return f'{prefix}{get_column_letter(c1n)}{r1n}:{get_column_letter(c2n)}{r2n}'


def repair_artifacts_after_delete(ws, d1, d2, filter_recompute=None,
                                 print_recompute=None):
    """Retarget merged ranges, auto-filter, freeze panes, and print area after
    ws.delete_rows(d1, d2). Merges straddling the deleted span raise ValueError
    (unmerge or recompute them from the table before cutting). An auto-filter or
    print area that belongs to the table being cut is RECOMPUTED from the new
    extent instead: pass filter_recompute/print_recompute (A1 strings) and any
    straddling ref will be replaced by them; without them a straddle raises."""
    for rng in list(ws.merged_cells.ranges):
        b = shift_bounds((rng.min_row, rng.min_col, rng.max_row, rng.max_col),
                         d1, d2)
        ws.unmerge_cells(str(rng))
        ws.merge_cells(start_row=b[0], start_column=b[1],
                       end_row=b[2], end_column=b[3])
    if ws.auto_filter.ref:
        try:
            ws.auto_filter.ref = shift_a1(ws.auto_filter.ref, d1, d2)
        except ValueError:
            if filter_recompute is None:
                raise
            ws.auto_filter.ref = filter_recompute
    if ws.freeze_panes:
        col, row = coordinate_from_string(ws.freeze_panes)
        delta = sum(1 for r in range(d1, d2 + 1) if r < row)
        ws.freeze_panes = f'{col}{row - delta}'
    if ws.print_area:
        try:
            new_pa = ' '.join(shift_a1(r, d1, d2) for r in ws.print_area.split())
        except ValueError:
            if print_recompute is None:
                raise
            new_pa = print_recompute
        ws.print_area = ' '.join(new_pa.split())


# ---------------------------------------------------------------------------
# Zip manifest preflight: openpyxl silently drops parts it cannot model
# (drawings, charts, images, VBA). In-place openpyxl editing is only safe when
# the input package contains only parts openpyxl understands.
# ---------------------------------------------------------------------------

LOSSY_PART_HINTS = ('xl/drawings', 'xl/charts', 'xl/media', 'vbaProject',
                    'xl/pivotCache', 'customXml')


def zip_manifest(path):
    """Sorted list of parts in the xlsx package."""
    with zipfile.ZipFile(path) as z:
        return sorted(z.namelist())


def assert_standard_parts(path):
    """Raise if the workbook contains parts openpyxl cannot model; in that
    case in-place openpyxl editing would silently drop them (verified: a
    drawing part present in the input is absent from the output of a plain
    load->save). Fall back to raw sheet-XML surgery (see SKILL.md)."""
    parts = zip_manifest(path)
    bad = [p for p in parts if any(h in p for h in LOSSY_PART_HINTS)]
    if bad:
        raise RuntimeError(
            f'input contains parts openpyxl cannot model: {bad[:5]}... '
            f'use raw sheet-XML surgery instead of in-place openpyxl editing')
    return parts


def verify_manifest(src, dst):
    """Assert the output package drops nothing the input had, except the two
    parts openpyxl legitimately rewrites (verified on v01): calcChain.xml
    (formula cache) and sharedStrings.xml (openpyxl writes strings inline).
    Returns the dropped set (should be empty)."""
    dropped = set(zip_manifest(src)) - set(zip_manifest(dst))
    forbidden = dropped - {'xl/calcChain.xml', 'xl/sharedStrings.xml'}
    if forbidden:
        raise RuntimeError(f'output dropped input parts: {sorted(forbidden)}')
    return dropped

# ---------------------------------------------------------------------------
# Generic table-transform primitives (iteration 2): row copying, selection
# predicates, header mapping, transposition, compaction helpers.
# ---------------------------------------------------------------------------

def blank_runs(ws, r1, r2, c1, c2):
    """Lengths of consecutive fully-blank rows inside the range (list of ints)."""
    runs, cur = [], 0
    for r in range(r1, r2 + 1):
        blank = all(ws.cell(row=r, column=c).value is None for c in range(c1, c2 + 1))
        if blank:
            cur += 1
        elif cur:
            runs.append(cur); cur = 0
    if cur:
        runs.append(cur)
    return runs


def read_row_values(ws, row, c1, c2):
    """{col: raw value} for one row."""
    return {c: ws.cell(row=row, column=c).value for c in range(c1, c2 + 1)}


def write_row_state(ws, dst_r, src_r, c1, c2, formula_cols=(), evaluated=None,
                    clean=True):
    """Copy src_r's full cell state (style, value, hyperlink, comment) to dst_r,
    replacing formula cells / '=...' text with evaluated numbers when provided
    (evaluated: {col: value}). Used for extraction/append/reconciliation where
    rows are copied without a permutation."""
    for c in range(c1, c2 + 1):
        s = ws.cell(row=src_r, column=c)
        d = ws.cell(row=dst_r, column=c)
        if isinstance(s, MergedCell):
            raise ValueError(f'source {s.coordinate} is a MergedCell: '
                             f'capture_merges() before copying rows')
        d._style = copy(s._style)
        v = s.value
        if c in formula_cols and isinstance(v, str) and v.startswith('='):
            v = (evaluated or {}).get(c, v)
            if clean:
                v = clean_num(v)
        d.value = v
        if s.hyperlink is not None:
            d.hyperlink = copy(s.hyperlink)
        if s.comment is not None:
            d.comment = copy(s.comment)


def clear_values(ws, rows, c1, c2):
    """Rewrite-and-clear: set values None on rows (styles stay) — the preferred
    compaction when the instruction does not force delete_rows."""
    for r in rows:
        for c in range(c1, c2 + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell, MergedCell):
                raise ValueError(f'{cell.coordinate} is a MergedCell: '
                                 f'capture_merges() before clearing')
            cell.value = None


def delete_rows_and_repair(ws, d1, d2, filter_recompute=None,
                           print_recompute=None):
    """delete_rows + repair merges/filter/freeze/print area. Straddling
    filters/print areas are replaced by the recompute args when given (use for
    artifacts that belong to the table being cut); merges always raise."""
    ws.delete_rows(d1, amount=d2 - d1 + 1)  # NOTE: amount = COUNT, not end row
    repair_artifacts_after_delete(ws, d1, d2,
                                  filter_recompute=filter_recompute,
                                  print_recompute=print_recompute)


def header_map(ws, header_row, c1, c2):
    """{normalized header text: column index} (normalize: strip, lower, collapse ws)."""
    import re as _re
    out = {}
    for c in range(c1, c2 + 1):
        v = ws.cell(row=header_row, column=c).value
        if v is None:
            continue
        key = _re.sub(r'\s+', ' ', str(v)).strip().lower()
        if key and key not in out:
            out[key] = c
    return out


def cell_fill_rgb(cell):
    """'RRGGBB' of a solid fill, else None."""
    f = cell.fill
    if f is None or f.patternType is None or f.patternType == 'none':
        return None
    rgb = f.fgColor.rgb if f.fgColor else None
    if not rgb:
        return None
    s = str(rgb).lstrip('#')
    return s[-6:] if len(s) >= 6 else None


def row_matches_fill(ws, row, cols, rgb):
    """True if any cell in cols has a solid fill ending in the given hex (case-insens)."""
    target = str(rgb).lstrip('#').upper()[-6:]
    for c in cols:
        v = cell_fill_rgb(ws.cell(row=row, column=c))
        if v is not None and v.upper() == target:
            return True
    return False


def _text_hit(value, pat):
    v = str(value).lower()
    p = str(pat).lower()
    if p.startswith('startswith:'):
        return v.startswith(p[len('startswith:'):])
    if p.startswith('endswith:'):
        return v.endswith(p[len('endswith:'):])
    return p in v


def row_matches_text(ws, row, cols, includes=(), excludes=(), mode='any'):
    """Text predicate over the row's cells in cols. includes/excludes are
    substring patterns (prefixes startswith:/endswith: allowed, case-insens).
    mode 'any' -> at least one include hit; 'all' -> every non-empty cell hits."""
    vals = [ws.cell(row=row, column=c).value for c in cols
            if ws.cell(row=row, column=c).value is not None]
    if includes:
        hits = [any(_text_hit(v, p) for p in includes) for v in vals]
        if mode == 'any':
            if not any(hits):
                return False
        else:
            if not vals or not all(hits):
                return False
    for p in excludes:
        if any(_text_hit(v, p) for v in vals):
            return False
    return True


def row_matches_numeric(ws, row, col, op, value, evaluated=()):
    """Numeric comparison on a single column; op in < <= > >= == !=.
    `evaluated` is an optional {col: value} dict for formula columns.
    The CELL side is strict (strict_key): a blank/text cell under a numeric
    predicate raises with its address instead of comparing as 0.0."""
    coord = f'{get_column_letter(col)}{row}'
    v = evaluated.get(col) if col in evaluated else ws.cell(row=row, column=col).value
    v = strict_key(v, coord=coord)
    t = float(value)  # threshold comes from the instruction; junk config raises
    return {'<': v < t, '<=': v <= t, '>': v > t, '>=': v >= t,
            '==': abs(v - t) < 1e-9, '!=': abs(v - t) >= 1e-9}[op]


def row_matches_membership(ws, row, col, values, numeric=False):
    """True if the cell value is in `values` (exact string match, or numeric
    equality with tolerance when numeric=True)."""
    v = ws.cell(row=row, column=col).value
    if v is None:
        return False
    if numeric:
        coord = f'{get_column_letter(col)}{row}'
        vn = strict_key(v, coord=coord)
        return any(abs(vn - strict_key(x, coord=f'{coord} (member)')) < 1e-9
                   for x in values)
    return str(v) in {str(x) for x in values}


def transpose_block(ws, r1, r2, c1, c2, dst_r, dst_c, formula_cols=(),
                    evaluated=None):
    """Write the matrix from (r1..r2 x c1..c2) transposed (values + styles)
    starting at cell (dst_r, dst_c): output(rr, cc) = input(c1+cc-1...)."""
    for rr in range(r1, r2 + 1):
        for cc in range(c1, c2 + 1):
            s = ws.cell(row=rr, column=cc)
            d = ws.cell(row=dst_r + (cc - c1), column=dst_c + (rr - r1))
            if isinstance(s, MergedCell):
                raise ValueError(f'source {s.coordinate} is a MergedCell: '
                                 f'capture_merges() before transposing')
            d._style = copy(s._style)
            v = s.value
            if cc in formula_cols and isinstance(v, str) and v.startswith('='):
                v = (evaluated or {}).get(cc, v)
                v = clean_num(v)
            d.value = v


# ---------------------------------------------------------------------------
# Full verification battery (iteration 2). The per-semantics solver scripts
# call verify_output() before declaring success; it subsumes the ad-hoc checks
# the iteration-1 solver had to reimplement by hand.
# ---------------------------------------------------------------------------

def _style_signature(cell):
    return (cell.font.bold, cell.font.name, cell.font.size, cell.fill.patternType,
            cell.number_format, cell.alignment.horizontal, cell.alignment.vertical,
            cell.border.left.style, cell.border.right.style,
            cell.border.top.style, cell.border.bottom.style)


def verify_workbook_state(inp, out, r1, r2, c1, c2, formula_cols=(), issues=None,
                          style_sig=True, bold_sig=True, expected_filter=None,
                          expected_print=None, expected_dims=None):
    """Structural + preservation battery. inp/out are worksheets (formula mode).
    Checks: answer range free of formulas/'=...' text, formula_cols numeric,
    values outside the table unchanged (rounded), widths, heights, dims,
    merges, freeze panes, auto-filter, print area, sheet properties, style
    signature multiset inside the table, and bold-cell set across the sheet.
    Appends to `issues` (list) and returns it."""
    if issues is None:
        issues = []
    # NOTE: ws.cell() materializes empty cells and INFLATES max_row/max_column,
    # so capture the sheet dimensions BEFORE any cell access below.
    inp_max_r, inp_max_c = inp.max_row, inp.max_column
    out_max_r, out_max_c = out.max_row, out.max_column
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            cell = out.cell(row=r, column=c)
            v = cell.value
            if isinstance(v, str) and v.startswith('='):
                issues.append(f'formula string at {r},{c}: {v!r}')
            if c in formula_cols and v is not None and not isinstance(v, (int, float)):
                issues.append(f'non-numeric formula-col at {r},{c}: {v!r}')
    from collections import Counter
    for r in range(1, max(inp_max_r, out_max_r) + 1):
        for c in range(1, max(inp_max_c, out_max_c) + 1):
            if r1 <= r <= r2 and c1 <= c <= c2:
                continue
            a, b = inp.cell(row=r, column=c).value, out.cell(row=r, column=c).value
            if isinstance(a, float):
                a = round(a, 9)
            if isinstance(b, float):
                b = round(b, 9)
            if a != b:
                issues.append(f'outside value changed at {r},{c}: {a!r} != {b!r}')
    if {c: inp.column_dimensions[c].width for c in inp.column_dimensions} != \
       {c: out.column_dimensions[c].width for c in out.column_dimensions}:
        issues.append('column widths changed')
    if {r: inp.row_dimensions[r].height for r in inp.row_dimensions} != \
       {r: out.row_dimensions[r].height for r in out.row_dimensions}:
        issues.append('row heights changed')
    exp_dims = expected_dims if expected_dims is not None else (inp_max_r, inp_max_c)
    if exp_dims != (out_max_r, out_max_c):
        issues.append('dimensions changed')
    if set(inp.merged_cells.ranges) != set(out.merged_cells.ranges):
        issues.append('merged ranges changed')
    if inp.freeze_panes != out.freeze_panes:
        issues.append('freeze panes changed')
    exp_f = expected_filter if expected_filter is not None else inp.auto_filter.ref
    if (exp_f or '') != (out.auto_filter.ref or ''):
        issues.append('auto filter changed')
    exp_p = expected_print if expected_print is not None else inp.print_area
    if (exp_p or '') != (out.print_area or ''):
        issues.append('print area changed')
    if inp.parent.sheetnames != out.parent.sheetnames:
        issues.append('sheetnames changed')
    if style_sig:
        sig_in = Counter(_style_signature(inp.cell(row=r, column=c))
                         for r in range(r1, r2 + 1) for c in range(c1, c2 + 1))
        sig_out = Counter(_style_signature(out.cell(row=r, column=c))
                          for r in range(r1, r2 + 1) for c in range(c1, c2 + 1))
        if sig_in != sig_out:
            issues.append('style signature multiset changed in answer range')
    if bold_sig:
        # compare rows/cols that exist in BOTH sheets (deleted rows legitimately
        # vanish from the output geometry)
        rmax = min(inp_max_r, out_max_r)
        cmax = min(inp_max_c, out_max_c)
        bold_in = {(r, c) for r in range(1, rmax + 1) for c in range(1, cmax + 1)
                   if inp.cell(row=r, column=c).font.bold}
        bold_out = {(r, c) for r in range(1, rmax + 1) for c in range(1, cmax + 1)
                    if out.cell(row=r, column=c).font.bold}
        if bold_in != bold_out:
            issues.append('bold cell set changed')
    return issues


def verify_permutation_order(inpF, inpV, outV, spans, key_col, desc, c1, c2,
                             formula_cols=(), tol=1e-9, issues=None):
    """For an in-place permutation transform (e.g. block sort): each span's row
    multiset equals the input's; keys follow the order rule; ties keep the
    original relative order (mapped via full-row identity). inpF is the formula
    worksheet and inpV the data_only worksheet of the INPUT; outV the data_only
    worksheet of the OUTPUT."""
    if issues is None:
        issues = []
    from collections import Counter
    cache = {}
    for rs, re in spans:
        rows = list(range(rs, re + 1))
        in_map = {input_row_tuple(inpF, inpV, r, c1, c2, formula_cols, cache): r
                  for r in rows}
        if Counter(input_row_tuple(inpF, inpV, r, c1, c2, formula_cols, cache)
                   for r in rows) != \
           Counter(row_tuple(outV, r, c1, c2) for r in rows):
            issues.append(f'span {rs}-{re}: row multiset changed')
        keys_out, orig = [], []
        for r in rows:
            t = row_tuple(outV, r, c1, c2)
            if t not in in_map:
                issues.append(f'span {rs}-{re}: output row at {r} not from input')
                continue
            orig.append(in_map[t])
            keys_out.append(strict_key(
                outV.cell(row=r, column=key_col).value,
                coord=f'{get_column_letter(key_col)}{r}'))
        for i in range(len(keys_out) - 1):
            bad = keys_out[i] < keys_out[i + 1] - tol if desc else \
                  keys_out[i] > keys_out[i + 1] + tol
            if bad:
                issues.append(f'span {rs}-{re}: order violated at {rs + i}')
        for i in range(len(keys_out) - 1):
            if abs(keys_out[i] - keys_out[i + 1]) <= tol and orig[i] > orig[i + 1]:
                issues.append(f'span {rs}-{re}: tie order not preserved at {rs + i}')
    return issues


def verify_subset_preserved_order(inpF, inpV, outV, outF, src_spans,
                                  out_r1, out_r2, c1, c2, formula_cols=(),
                                  issues=None):
    """For in-place filtering/compaction: every output row within out_r1..out_r2
    must exist in the input spans (multiset subset) and keep the input relative
    order (mapped via row identity). Also checks that the style multiset of the
    kept output rows equals the style multiset of their matched input rows
    (styles ride with the rows)."""
    if issues is None:
        issues = []
    from collections import Counter
    cache = {}
    in_rows = [input_row_tuple(inpF, inpV, r, c1, c2, formula_cols, cache)
               for (rs, re) in src_spans for r in range(rs, re + 1)]
    in_counter = Counter(in_rows)
    order_index = {t: i for i, t in enumerate(in_rows)}
    out_rows = [row_tuple(outV, r, c1, c2) for r in range(out_r1, out_r2 + 1)
                if any(v is not None for v in row_tuple(outV, r, c1, c2))]
    out_counter = Counter(out_rows)
    if not (out_counter <= in_counter):
        issues.append('output rows are not a multiset-subset of input rows')
    last = -1
    matched = []
    for t in out_rows:
        if t not in order_index:
            issues.append('output row not found in input')
            continue
        idx = order_index[t]
        if idx < last:
            issues.append('output order not preserved')
        last = idx
        matched.append(idx)
    # styles follow rows: signature multiset of kept rows vs their input rows
    in_sigs = Counter()
    for i, t in enumerate(out_rows):
        if t not in order_index:
            continue
        idx = order_index[t]
        # input row number for the idx-th input row (list of (r, tup))
        in_row_nums = [r for (rs, re) in src_spans for r in range(rs, re + 1)]
        src_r = in_row_nums[idx]
        for c in range(c1, c2 + 1):
            in_sigs[_style_signature(inpF.cell(row=src_r, column=c))] += 1
    out_sigs = Counter()
    for i, r in enumerate(range(out_r1, out_r2 + 1)):
        if any(v is not None for v in row_tuple(outV, r, c1, c2)):
            for c in range(c1, c2 + 1):
                out_sigs[_style_signature(outF.cell(row=r, column=c))] += 1
    if in_sigs != out_sigs:
        issues.append('kept rows style signature multiset changed')
    return issues


def verify_output(inp_path, out_path, sheet, r1, r2, c1, c2, formula_cols=(),
                  spans=None, sort_col=None, desc=True, blank_separator=None,
                  out_r1=None, out_r2=None, src_spans=None, tol=1e-9,
                  expected_filter=None, expected_print=None, expected_dims=None,
                  quiet=True):
    """Umbrella verification for the family's outputs.
    - structural battery always (verify_workbook_state, verify_manifest, and
      block spans + blank-run lengths when spans/blank_separator given)
    - verify_permutation_order when sort_col is given (per `spans`)
    - verify_subset_preserved_order when src_spans/out_r1/out_r2 are given;
      in that mode the style-signature check is scoped to the kept rows
      (a compacted region cannot satisfy a whole-range style multiset).
    Returns the list of issues (empty = success)."""
    wb, wbv = load_dual(inp_path)
    out, outv = load_dual(out_path)
    issues = []
    if spans is not None:
        if find_blocks(out[sheet], r1, r2, c1, c2) != spans:
            issues.append('block spans changed')
        if blank_separator is not None:
            runs = blank_runs(out[sheet], r1, r2, c1, c2)
            if any(x != blank_separator for x in runs):
                issues.append(f'blank runs not {blank_separator}: {runs}')
    subset_mode = (src_spans is not None and out_r1 is not None
                   and out_r2 is not None)
    verify_workbook_state(wb[sheet], out[sheet], r1, r2, c1, c2,
                          formula_cols=formula_cols, issues=issues,
                          style_sig=not subset_mode,
                          expected_filter=expected_filter,
                          expected_print=expected_print,
                          expected_dims=expected_dims)
    if sort_col is not None and spans is not None:
        verify_permutation_order(wb[sheet], wbv[sheet], outv[sheet], spans,
                                 sort_col, desc, c1, c2,
                                 formula_cols=formula_cols, tol=tol,
                                 issues=issues)
    if src_spans is not None and out_r1 is not None and out_r2 is not None:
        verify_subset_preserved_order(wb[sheet], wbv[sheet], outv[sheet],
                                      out[sheet], src_spans, out_r1, out_r2,
                                      c1, c2, formula_cols=formula_cols,
                                      issues=issues)
    try:
        verify_manifest(inp_path, out_path)
    except Exception as e:
        issues.append(f'manifest: {e}')
    if not quiet:
        for p in issues[:30]:
            print(' -', p)
    return issues