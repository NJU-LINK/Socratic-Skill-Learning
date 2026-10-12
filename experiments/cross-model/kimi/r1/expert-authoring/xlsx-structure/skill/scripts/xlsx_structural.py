#!/usr/bin/env python3
"""
Reusable building blocks for xlsx structural-transformation tasks.

Design rule that prevents the most common bug in this family:
READ PHASE (evaluate/snapshot everything from the pristine workbook)
must fully finish before the WRITE PHASE (mutating cells) begins.
Never read formula cells from a worksheet you have already started
overwriting -- a later evaluation would see half-written values.

Requires: openpyxl (stdlib-only otherwise).
"""
import ast
import re
from copy import copy

import openpyxl

# ---------------------------------------------------------------- loading

def load_pair(path):
    """Return (wb_formulas, wb_cached).

    wb_formulas: cell.value gives '=B1+C1' for real formula cells.
    wb_cached:   cell.value gives the last cached result (only if the file
                 was saved by a calculating app; otherwise None). Use it as
                 an independent ORACLE to cross-check your own evaluation,
                 never as the sole source of truth (may be missing/stale).
    """
    return (openpyxl.load_workbook(path),
            openpyxl.load_workbook(path, data_only=True))

# ------------------------------------------------- formula / text evaluation

# Single cell ref, not preceded by identifier chars and never followed by
# '(' (so function names like LOG10 / ATAN2 are NOT mangled into refs).
_REF = re.compile(r"(?<![A-Za-z0-9_!])\$?([A-Za-z]{1,3})\$?([0-9]+)(?![0-9])(?!\s*\()")
# Rectangular range like A1:B5 (optionally $-anchored).
_RANGE = re.compile(
    r"(?<![A-Za-z0-9_!])\$?([A-Za-z]{1,3})\$?([0-9]+)"
    r":\$?([A-Za-z]{1,3})\$?([0-9]+)")

def _expand_range(m):
    from openpyxl.utils import column_index_from_string, get_column_letter
    c1, r1, c2, r2 = (m.group(1).upper(), int(m.group(2)),
                      m.group(3).upper(), int(m.group(4)))
    refs = []
    for ci in range(min(column_index_from_string(c1), column_index_from_string(c2)),
                    max(column_index_from_string(c1), column_index_from_string(c2)) + 1):
        for r in range(min(r1, r2), max(r1, r2) + 1):
            refs.append(f"{get_column_letter(ci)}{r}")
    return ",".join(refs)

def make_evaluator(ws):
    """cell_num(row, col_letter) -> float, resolving recursively.

    Handles real formula cells (data_type 'f'), TEXT cells whose string
    starts with '=' (text-that-represents-a-formula), plain numbers, and
    numeric-looking text. Supports + - * / , parentheses, unary minus,
    $-anchored refs, rectangular ranges inside aggregate calls, and
    SUM/ABS/ROUND/MIN/MAX/AVERAGE. Memoized; reads only `ws`, so finish
    all evaluation BEFORE mutating `ws`. Blank/unparseable -> 0.0.
    """
    cache = {}

    def cell_num(row, col):
        col = col.upper()
        key = (row, col)
        if key in cache:
            return cache[key]
        v = ws[f"{col}{row}"].value
        if v is None:
            res = 0.0
        elif isinstance(v, bool):
            res = float(v)
        elif isinstance(v, (int, float)):
            res = float(v)
        elif isinstance(v, str):
            s = v.strip()
            if s.startswith("="):
                res = _eval_expr(s[1:])
            else:
                try:
                    res = float(s.replace(",", ""))
                except ValueError:
                    res = 0.0
        else:
            res = 0.0
        cache[key] = res
        return res

    def _eval_expr(expr):
        expr = _RANGE.sub(_expand_range, expr)   # ranges first...
        sub = _REF.sub(lambda m: repr(cell_num(int(m.group(2)), m.group(1))),
                       expr)                      # ...then single refs
        return _ev(ast.parse(sub, mode="eval"))

    def _ev(n):
        if isinstance(n, ast.Expression):
            return _ev(n.body)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.BinOp):
            l, r = _ev(n.left), _ev(n.right)
            if isinstance(n.op, ast.Add): return l + r
            if isinstance(n.op, ast.Sub): return l - r
            if isinstance(n.op, ast.Mult): return l * r
            if isinstance(n.op, ast.Div): return l / r
            raise ValueError(f"unsupported op {n.op}")
        if isinstance(n, ast.UnaryOp):
            x = _ev(n.operand)
            return -x if isinstance(n.op, ast.USub) else x
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            args = [_ev(a) for a in n.args]
            fn = n.func.id.upper()
            if fn == "SUM": return sum(args)
            if fn == "ABS": return abs(args[0])
            if fn == "MIN": return min(args)
            if fn == "MAX": return max(args)
            if fn == "AVERAGE": return sum(args) / len(args)
            if fn == "ROUND": return round(args[0], int(args[1]) if len(args) > 1 else 0)
            raise ValueError(f"unsupported func {fn}")
        raise ValueError(f"unsupported node {ast.dump(n)}")

    return cell_num

# ----------------------------------------------------------- structure detection

def row_is_blank(ws, r, cols):
    """Blank = every cell of `cols` in row r is None or ''. Only inspect the
    columns of the declared region; values outside the region must not make
    a region-row 'non-blank'."""
    for c in cols:
        v = ws[f"{c}{r}"].value
        if v is not None and v != "":
            return False
    return True

def detect_blocks(ws, row_min, row_max, cols):
    """Split [row_min, row_max] into maximal non-blank row runs separated by
    blank rows. Returns (blocks, blank_rows). Detect, never assume, sizes."""
    blocks, blanks, cur = [], [], []
    for r in range(row_min, row_max + 1):
        if row_is_blank(ws, r, cols):
            blanks.append(r)
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(r)
    if cur:
        blocks.append(cur)
    return blocks, blanks

def first_empty_row(ws, col, start=1):
    """First row >= start whose cell in `col` is blank (append boundary)."""
    r = start
    while ws[f"{col}{r}"].value not in (None, ""):
        r += 1
    return r

def header_index(ws, row, cols):
    """{header_text: col_letter} for a header row. Match headers by exact
    text; normalize only surrounding whitespace unless told otherwise."""
    out = {}
    for cl in cols:
        v = ws[f"{cl}{row}"].value
        if isinstance(v, str):
            out[v.strip()] = cl
        elif v is not None:
            out[v] = cl
    return out

def fill_key(cell):
    """Normalized fill identifier for style-based selection predicates.
    Returns (patternType, fgColor) or None for unfilled cells."""
    fl = cell.fill
    if fl is None or fl.patternType is None:
        return None
    return (fl.patternType, getattr(fl.fgColor, "rgb", None))

# ---------------------------------------------------------------- row snapshots

def snapshot_row(ws, r, cols, cell_num=None):
    """[(final_value, style_copy), ...] for one row.

    If cell_num is given, formula cells AND '='-prefixed text cells are
    replaced by their evaluated numeric value NOW (read phase)."""
    out = []
    for cl in cols:
        c = ws[f"{cl}{r}"]
        v = c.value
        if cell_num is not None and isinstance(v, str) and v.strip().startswith("="):
            v = cell_num(r, cl)
        out.append((v, copy(c._style)))
    return out

def write_rows(ws, start_row, cols, rows):
    """WRITE PHASE. `rows` is a list of None (blank separator -> clear
    values, styles untouched) or snapshot_row results [(value, style), ...].
    Values and styles are written together so record-level styles travel
    with their record. A snapshot of an original blank row
    ([(None, style), ...]) is the safe way to pad: it clears values AND
    removes stale styles left behind by moved records. Note: an untouched
    cell's `_style` is None, and assigning None resets a styled cell to
    default -- exactly what blank padding needs. Verified on openpyxl 3.1."""
    for i, item in enumerate(rows):
        r = start_row + i
        for j, cl in enumerate(cols):
            c = ws[f"{cl}{r}"]
            if item is None:
                c.value = None
            else:
                c.value, c._style = item[j]

# ---------------------------------------------------------------- verification

def num_eq(a, b, tol=1e-9):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b

def diff_region(ws_a, ws_b, row_min, row_max, cols, tol=1e-9):
    """List of human-readable differences of VALUES between two worksheets
    over a region. Use to prove untouched regions are untouched."""
    diffs = []
    for r in range(row_min, row_max + 1):
        for cl in cols:
            va = ws_a[f"{cl}{r}"].value
            vb = ws_b[f"{cl}{r}"].value
            if not num_eq(va, vb, tol):
                diffs.append(f"{cl}{r}: {va!r} != {vb!r}")
    return diffs

def style_signature(cell):
    f, fl, b = cell.font, cell.fill, cell.border
    fg = fl.fgColor.rgb if fl.patternType else None
    return (f.name, f.sz, bool(f.b), bool(f.i), fl.patternType, fg,
            b.left.style, b.right.style, b.top.style, b.bottom.style,
            cell.number_format)
