#!/usr/bin/env python3
"""
xlsx-structure second executable semantic: block-local predicate FILTER + COMPACTION.

This script demonstrates the family's payload-mapper architecture: the SAME
verified primitives as the sort pipeline (blank-row block detector, row-local
formula evaluator, exact-float patch, untouched-cell restoration) with a
different transformation semantics and a different output geometry.

Semantics (documented as reasoned extrapolation, verified on a synthetic probe):
  * Blocks are detected as in sort mode: maximal runs of non-blank rows inside
    the span, blank = all used span columns empty.
  * Within each block, every row is kept iff its evaluated keep-column value
    satisfies keepOP keepValue (numeric comparison; the keep column is
    evaluated with the same row-local formula evaluator).
  * Output geometry is COMPACTED: survivors of all blocks are written
    contiguously starting at the span's first row, with exactly one blank row
    between adjacent blocks' survivor groups, and the remaining rows of the
    span left blank. Every coordinate that previously held block data but is
    not reused by a survivor is explicitly CLEARED (and registered touched).
  * Everything else (non-block rows, cells outside the span, styles, other
    sheets) is preserved by the same mechanisms: in-place value-only rewrites,
    exact-float zip patch, restore_untouched_cells, and the verification suite.

Usage:
  python3 scripts/filter_compact.py input.xlsx output.xlsx \
      --span A1:H85 --eval-cols D:F --keep-col D --keep-op ge --keep-value 0 --check
"""
import argparse
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from transform import (  # shared, v01-verified primitives
    cell_value, detect_blocks, dimension_refs, eval_col_indices, exact_float_patch,
    parse_span, restore_untouched_cells, span_cols, style_signature, values_equal,
)

_OPS = {"ge": lambda a, b: a >= b,
        "gt": lambda a, b: a > b,
        "le": lambda a, b: a <= b,
        "lt": lambda a, b: a < b,
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b}


def filter_layout(ws, min_col, min_row, max_col, max_row, keep_col, keep_op, keep_value,
                  evcols, cached_wb=None, sheet=None):
    """
    Compute the compacted layout directly on a worksheet.
    Returns (survivors, cleared) where:
      survivors = {target_row: {col: value}}  (target coords to write)
      cleared   = set((row, col)) of old block coords to set None
    """
    blocks, _ = detect_blocks(ws, min_col, min_row, max_col, max_row)
    cols = span_cols(min_col, max_col)
    keep_idx = column_index_from_string(keep_col)
    op = _OPS[keep_op]
    survivors, cursor = {}, min_row
    for bi, (start, end) in enumerate(blocks):
        memo = {}
        picked = []
        for r in range(start, end + 1):
            v = ws.cell(row=r, column=keep_idx).value
            if isinstance(v, str):
                v = v.strip()
            if isinstance(v, str) and v.startswith("="):
                key = cell_value(ws, r, keep_idx, memo)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                key = v
            else:
                raise ValueError("keep column %s row %d has no numeric value: %r"
                                 % (get_column_letter(keep_idx), r, v))
            if not isinstance(key, (int, float)) or isinstance(key, bool):
                raise ValueError("keep key not numeric at row %d: %r" % (r, key))
            # full row payload with eval columns as numbers
            payload = {}
            for c in cols:
                pv = ws.cell(row=r, column=c).value
                if isinstance(pv, str):
                    pv = pv.strip()
                if c in evcols:
                    try:
                        if pv is None or pv == "":
                            raise ValueError("empty eval cell")
                        if isinstance(pv, (int, float)) and not isinstance(pv, bool):
                            payload[c] = pv
                        elif pv.startswith("="):
                            payload[c] = cell_value(ws, r, c, memo)
                        else:
                            raise ValueError("unexpected content %r" % pv)
                    except ValueError as exc:
                        if cached_wb is not None:
                            payload[c] = cached_wb[sheet if sheet else cached_wb.active.title] \
                                .cell(row=r, column=c).value
                        else:
                            raise ValueError(
                                "cannot evaluate %s row %d: %s (add --cached-fallback)"
                                % (get_column_letter(c), r, exc))
                else:
                    payload[c] = pv
            if op(key, keep_value):
                picked.append(payload)
        # write survivors contiguously, then one separator blank row between blocks
        for off, payload in enumerate(picked):
            survivors[cursor + off] = payload
        cursor += len(picked)
        if bi < len(blocks) - 1:
            cursor += 1
    # everything that held block data but is not reused must be cleared
    old_cells = {(r, c) for (s, e) in blocks for r in range(s, e + 1) for c in cols}
    survivor_cells = {(tr, c) for tr, payload in survivors.items() for c in payload}
    cleared = old_cells - survivor_cells
    return survivors, cleared


def transform_filter_compact(wb, span, eval_spec, keep_col, keep_op, keep_value,
                             cached_wb=None, sheet=None):
    min_col, min_row, max_col, max_row = parse_span(span)
    evcols = eval_col_indices(eval_spec)
    ws = wb[sheet] if sheet else wb.active
    survivors, cleared = filter_layout(ws, min_col, min_row, max_col, max_row,
                                       keep_col, keep_op, keep_value, evcols,
                                       cached_wb=cached_wb, sheet=sheet)
    for (r, c) in cleared:
        ws.cell(row=r, column=c).value = None
    for tr, payload in survivors.items():
        for c, v in payload.items():
            ws.cell(row=tr, column=c).value = v
    touched = cleared | {(tr, c) for tr in survivors for c in survivors[tr]}
    return survivors, cleared, touched


def run_check(input_path, output_path, span, eval_spec, keep_col, keep_op, keep_value,
              touched_parts, sheet=None):
    """Mode-aware verification: (1) span hygiene, (5) preservation, (6) dimensions,
    (7) untouched value diff incl. cached view, (8) reference reconstruction."""
    problems = []
    touched_parts = touched_parts or {}
    ib = load_workbook(input_path, data_only=False)
    ob = load_workbook(output_path, data_only=False)
    ibd = load_workbook(input_path, data_only=True)
    obd = load_workbook(output_path, data_only=True)
    iws, ows = ib[sheet] if sheet else ib.active, ob[sheet] if sheet else ob.active
    min_col, min_row, max_col, max_row = parse_span(span)
    evcols = eval_col_indices(eval_spec)
    cols = span_cols(min_col, max_col)

    # (1) span hygiene
    for r in range(min_row, max_row + 1):
        for c in cols:
            v = ows.cell(row=r, column=c).value
            if isinstance(v, str) and v.strip().startswith("="):
                problems.append("formula text left in span: %s" % ows.cell(row=r, column=c).coordinate)
            if c in evcols and v is not None and not (isinstance(v, (int, float)) and not isinstance(v, bool)):
                problems.append("non-numeric eval cell %s: %r" % (ows.cell(row=r, column=c).coordinate, v))

    # (5) preservation diff on the target sheet
    if sorted(str(x) for x in iws.merged_cells.ranges) != sorted(str(x) for x in ows.merged_cells.ranges):
        problems.append("merged ranges differ")
    if (iws.freeze_panes, iws.auto_filter.ref) != (ows.freeze_panes, ows.auto_filter.ref):
        problems.append("freeze_panes/auto_filter differ")
    w_i = {k: (v.width, v.hidden) for k, v in iws.column_dimensions.items() if v.width is not None or v.hidden}
    w_o = {k: (v.width, v.hidden) for k, v in ows.column_dimensions.items() if v.width is not None or v.hidden}
    if w_i != w_o:
        problems.append("column widths differ")
    h_i = {k: (v.height, v.hidden) for k, v in iws.row_dimensions.items() if v.height is not None or v.hidden}
    h_o = {k: (v.height, v.hidden) for k, v in ows.row_dimensions.items() if v.height is not None or v.hidden}
    if h_i != h_o:
        problems.append("row heights differ")
    # (5) preservation diff on the target sheet (touched coordinates skipped:
    # their values are checked by (8), styles are value-only unchanged)
    tpart = "xl/worksheets/sheet%d.xml" % (ib.sheetnames.index(iws.title) + 1)
    ts_touched = touched_parts.get(tpart, set())
    for key in sorted(set(iws._cells) | set(ows._cells)):
        if key in ts_touched:
            continue  # transform wrote these; values are checked by (8)
        ci, co = iws._cells.get(key), ows._cells.get(key)
        vi = ci.value if ci is not None else None
        vo = co.value if co is not None else None
        if (vi is not None) != (vo is not None):
            problems.append("cell value presence differs at %s" % (key,))
        elif ci is not None and co is not None and style_signature(ci) != style_signature(co):
            problems.append("style differs at %s" % (ci.coordinate,))

    # (6) dimension tags per part
    d_in, d_out = dimension_refs(input_path), dimension_refs(output_path)
    if d_in != d_out:
        problems.append("dimension tags differ: %r vs %r" % (d_in, d_out))

    # (7) untouched value diff (formula + cached views), all sheets
    i_by = {w.title: w for w in ib.worksheets}
    o_by = {w.title: w for w in ob.worksheets}
    id_by = {w.title: w for w in ibd.worksheets}
    od_by = {w.title: w for w in obd.worksheets}
    for name, iw in i_by.items():
        if name not in o_by:
            continue
        ow = o_by[name]
        part = "xl/worksheets/sheet%d.xml" % (ib.sheetnames.index(name) + 1)
        touched = touched_parts.get(part, set())
        for key in sorted(set(iw._cells) | set(ow._cells)):
            if key in touched:
                continue
            ci, co = iw._cells.get(key), ow._cells.get(key)
            vi = ci.value if ci is not None else None
            vo = co.value if co is not None else None
            if (vi is not None) != (vo is not None):
                problems.append("untouched cell value presence differs at %s!%s" % (name, key))
                continue
            if ci is None:
                continue
            if not values_equal(ci.value, co.value):
                problems.append("untouched value changed at %s!%s: %r -> %r"
                                % (name, ci.coordinate, ci.value, co.value))
            di, do_ = id_by[name]._cells.get(key), od_by[name]._cells.get(key)
            if di is not None and do_ is not None and (di.value is not None or do_.value is not None) \
                    and not values_equal(di.value, do_.value):
                problems.append("untouched cached value changed at %s!%s: %r -> %r"
                                % (name, di.coordinate, di.value, do_.value))

    # (8) reference reconstruction (independent path): re-derive survivors + layout
    # from the input, then compare every span cell against the output.
    survivors, cleared = filter_layout(iws, min_col, min_row, max_col, max_row,
                                       keep_col, keep_op, keep_value, evcols,
                                       cached_wb=None, sheet=sheet)
    expected = {}
    for tr, payload in survivors.items():
        for c, v in payload.items():
            expected[(tr, c)] = v
    for (r, c) in cleared:
        expected[(r, c)] = None
    ref_bad = 0
    for (r, c), e in sorted(expected.items()):
        o = ows.cell(row=r, column=c).value
        if not values_equal(e, o):
            ref_bad += 1
            if ref_bad <= 10:
                problems.append("reference mismatch at %s: expected %r got %r"
                                % (ows.cell(row=r, column=c).coordinate, e, o))
    if ref_bad:
        problems.append("reference reconstruction: %d span-cell mismatches" % ref_bad)

    sheetnames_in, sheetnames_out = set(ib.sheetnames), set(ob.sheetnames)
    if sheetnames_in != sheetnames_out:
        problems.append("sheet set differs: %s vs %s" % (sheetnames_in, sheetnames_out))
    return problems, d_in, d_out


_API_DOC = """\
Filter/compact mode contract (python3 filter_compact.py --api prints this):
  CLI: filter_compact.py INPUT OUTPUT --span RANGE --eval-cols D:F
       --keep-col D --keep-op ge|gt|le|lt|eq|ne --keep-value NUM
       [--sheet S] [--cached-fallback] [--no-exact-floats] [--no-restore] [--check]
  filter_layout(ws, min_col, min_row, max_col, max_row, keep_col, keep_op,
                keep_value, evcols, cached_wb=None, sheet=None)
      -> (survivors, cleared)
         survivors = {target_row: {col: evaluated_payload_value}}
         cleared   = set((row, col)) of old block cells that must be set None
  transform_filter_compact(wb, span, eval_spec, keep_col, keep_op, keep_value,
                           cached_wb=None, sheet=None)
      -> (survivors, cleared, touched)   # touched = cleared | survivor coords
  _OPS = {'ge':>=, 'gt':>, 'le':<=, 'lt':<, 'eq':==, 'ne':!=}  (numeric)
  Semantics: within each block keep rows whose evaluated keep-col satisfies
  keepOP keepValue; survivors compacted from span start with exactly one blank
  row between groups; every vacated old-block cell is cleared and registered
  touched; styles stay POSITIONAL (value-only compaction); all other cells
  preserved by restore_untouched_cells. Reused primitives from transform.py:
  detect_blocks, cell_value, eval_col_indices, parse_span, span_cols,
  values_equal, style_signature, dimension_refs, exact_float_patch,
  restore_untouched_cells. Independent oracle: scripts/family_probe.py.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="input xlsx (omit with --api)")
    ap.add_argument("output", nargs="?", help="output xlsx (omit with --api)")
    ap.add_argument("--api", action="store_true",
                    help="print the filter/compact mode contract and exit")
    ap.add_argument("--span", default="A1:H85")
    ap.add_argument("--eval-cols", default="D:F")
    ap.add_argument("--keep-col", default="D")
    ap.add_argument("--keep-op", default="ge", choices=sorted(_OPS))
    ap.add_argument("--keep-value", type=float, default=0.0)
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--cached-fallback", action="store_true")
    ap.add_argument("--no-exact-floats", action="store_true")
    ap.add_argument("--no-restore", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.api:
        print(_API_DOC)
        return 0
    if not args.input or not args.output:
        ap.error("input and output paths are required (or use --api)")

    wb = load_workbook(args.input, data_only=False)
    cached_wb = load_workbook(args.input, data_only=True) if args.cached_fallback else None
    survivors, cleared, touched = transform_filter_compact(
        wb, args.span, args.eval_cols, args.keep_col, args.keep_op, args.keep_value,
        cached_wb=cached_wb, sheet=args.sheet)
    target = wb[args.sheet] if args.sheet else wb.active
    wb.save(args.output)
    if not args.no_exact_floats:
        exact_float_patch(args.output, wb)
    part = "xl/worksheets/sheet%d.xml" % (wb.worksheets.index(target) + 1)
    touched_parts = {part: touched}
    restored = 0
    if not args.no_restore:
        restored = restore_untouched_cells(args.output, args.input, touched_parts)
    kept = len(survivors)  # survivor GROUPS keyed by target row, hence row count
    if args.check:
        problems, d_in, d_out = run_check(args.input, args.output, args.span, args.eval_cols,
                                          args.keep_col, args.keep_op, args.keep_value,
                                          touched_parts, sheet=args.sheet)
        if problems:
            print("\nCHECK FAILED (%d problems):" % len(problems))
            for p in problems:
                print(" -", p)
            return 1
        print("CHECK PASSED: filtered rows dropped, %d survivor rows compacted with one "
              "blank between groups, cleared cells registered, preservation diff empty, "
              "untouched values identical (incl. cached view), reference reconstruction "
              "clean, dimensions %s" % (kept, "all matched" if d_in == d_out else "MISMATCH"))
    else:
        print("filtered -> %d survivor rows (restored %d untouched cells)"
              % (kept, restored))
    return 0


if __name__ == "__main__":
    sys.exit(main())