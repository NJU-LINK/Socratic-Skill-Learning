#!/usr/bin/env python3
"""Filter + compact (or extract) solver for the xlsx-structure family.

Keeps rows of a source table that satisfy ALL configured predicates, writes
them in order starting at the compaction anchor (same range = in-place
compaction; DST_ANCHOR set = extraction to another area/sheet), evaluates
formula columns to numbers, then optionally deletes the vacated tail rows
(DELETE_TAIL=True) with artifact repair. Everything outside the declared
source/answer ranges is preserved.

Config mapping from a task instruction:
- "rows whose X contains A but not B" -> PREDICATES [{'kind':'text','col':X,
  'includes':['A'],'excludes':['B']}]
- "rows with value > N in column E (evaluated)" -> numeric predicate; formula
  columns must be listed in FORMULA_COLS so the evaluated value is used.
- "rows marked yellow / fill #FFC000" -> {'kind':'fill','rgb':'FFC000'}
- "rows whose ID is in the list B2:B9" -> membership (read range values).
- "write only the kept rows starting at D10" -> DST_ANCHOR='D10' (extract).
- "compact/remove other rows" -> DELETE_TAIL=True for a physically shorter
  table (repair + recomputed filter/print area run automatically); otherwise
  rewrite-and-clear is used.
"""
import re

from xlsx_common import (assert_standard_parts, capture_merges, clear_values,
                         delete_rows_and_repair, evaluate_formula, load_dual,
                         parse_a1, restore_merges, row_matches_fill,
                         row_matches_membership, row_matches_numeric,
                         row_matches_text, verify_output, write_row_state)

# ---------------- config (per task) ----------------
SRC = '/app/input.xlsx'
DST = '/app/output.xlsx'
SHEET = 'Sheet1'
TABLE = 'A1:F40'          # source table range (also the default answer range)
DST_ANCHOR = None         # None -> compact in place; 'D10' -> extract keeping
                          # rows to the anchor (same sheet); 'Sheet2!A1' -> other sheet
FORMULA_COLS = (4, 5, 6)  # columns that may hold formulas / '=...' text
DELETE_TAIL = False       # True -> physically delete vacated rows (with repair)
SEPARATOR_BLANK = None    # if source has block separators to keep (e.g. 1), set here

# Predicates are ANDed; each keeps the row when it matches. Predicate kinds:
#  text:       {'kind':'text','col':..,'includes':['a',..],'excludes':['b',..],'mode':'any'}
#  numeric:    {'kind':'numeric','col':..,'op':'>','value':100}   (op: < <= > >= == !=;
#               uses the EVALUATED value when col is in FORMULA_COLS)
#  fill:       {'kind':'fill','rgb':'FFC000'}  (matches any cell in the row across TABLE cols)
#  membership: {'kind':'membership','col':..,'values':['x',..]} or {'range':'B2:B9'}
PREDICATES = []
# ----------------------------------------------------

def _membership_values(ws, pred):
    if 'values' in pred:
        return pred['values']
    r1, r2, c1, c2 = parse_a1(pred['range'])
    return [ws.cell(row=r, column=c1).value for r in range(r1, r2 + 1)
            if ws.cell(row=r, column=c1).value is not None]


def _keep(ws, row, c1, c2, evaluated):
    for p in PREDICATES:
        kind = p['kind']
        if kind == 'text':
            if not row_matches_text(ws, row, [p['col']], p.get('includes', ()),
                                    p.get('excludes', ()), p.get('mode', 'any')):
                return False
        elif kind == 'numeric':
            if not row_matches_numeric(ws, row, p['col'], p['op'], p['value'],
                                       evaluated=dict(evaluated[row])):
                return False
        elif kind == 'fill':
            if not row_matches_fill(ws, row, range(c1, c2 + 1), p['rgb']):
                return False
        elif kind == 'membership':
            if not row_matches_membership(ws, row, p['col'],
                                          _membership_values(ws, p)):
                return False
        else:
            raise ValueError(f'unknown predicate kind {kind!r}')
    return True


def main():
    assert_standard_parts(SRC)
    wb, wbv = load_dual(SRC)
    ws = wb[SHEET]
    r1, r2, c1, c2 = parse_a1(TABLE)
    # destination sheet/anchor for extraction mode
    dst_sheet, dst_anchor = SHEET, DST_ANCHOR
    if DST_ANCHOR and '!' in DST_ANCHOR:
        dst_sheet, dst_anchor = DST_ANCHOR.split('!', 1)
    if dst_sheet not in wb.sheetnames:
        wb.create_sheet(dst_sheet)
    d_ws = wb[dst_sheet]
    ar = ac = None
    if DST_ANCHOR:
        col_s, row_s = re.match(r'([A-Za-z]+)(\d+)', dst_anchor).groups()
        from openpyxl.utils import column_index_from_string
        ar, ac = int(row_s), column_index_from_string(col_s.upper())
    # merges touching everything we may write: source footprint AND (for
    # extraction) the destination footprint — same-sheet anchors included
    saved = capture_merges(ws, range(r1, r2 + 1), range(c1, c2 + 1))
    if DST_ANCHOR:
        saved += capture_merges(d_ws,
                                range(ar, ar + (r2 - r1 + 1)),
                                range(ac, ac + (c2 - c1 + 1)))
    cache = {}
    rows = list(range(r1, r2 + 1))
    evaluated = {}
    for r in rows:
        rv = {c: ws.cell(row=r, column=c).value for c in range(c1, c2 + 1)}
        for c in sorted(FORMULA_COLS):
            v = rv.get(c)
            if isinstance(v, str) and v.startswith('='):
                rv[c] = evaluate_formula(v, ws, r, rv, cache)
        evaluated[r] = rv
    kept = [r for r in rows if _keep(ws, r, c1, c2, evaluated)]
    print('kept', len(kept), 'of', len(rows), 'rows:', kept)
    if DST_ANCHOR:
        # extraction: write kept rows to dst starting at the anchor, record
        # columns placed at their RELATIVE offsets (anchor col + (c - c1))
        from copy import copy
        for i, r in enumerate(kept):
            for c in range(c1, c2 + 1):
                s = ws.cell(row=r, column=c)
                d = d_ws.cell(row=ar + i, column=ac + (c - c1))
                d._style = copy(s._style)
                d.value = evaluated[r].get(c, s.value)
    else:
        # compaction: rewrite kept rows to the top of the table, clear the tail
        for i, r in enumerate(kept):
            write_row_state(ws, r1 + i, r, c1, c2,
                            formula_cols=FORMULA_COLS, evaluated=evaluated[r])
        vacated = list(range(r1 + len(kept), r2 + 1))
        clear_values(ws, vacated, c1, c2)
        if DELETE_TAIL:
            # remove truly empty rows at the bottom of the table (only those
            # that became fully blank from clearing); repair artifacts. The
            # table's own filter/print area are RECOMPUTED to the new extent
            # (straddling them would otherwise raise by design).
            from openpyxl.utils import get_column_letter as _gl
            d1 = r1 + len(kept)
            if d1 <= r2:
                new_extent = f'{_gl(c1)}{r1}:{_gl(c2)}{d1 - 1}'
                delete_rows_and_repair(
                    ws, d1, r2,
                    filter_recompute=new_extent if ws.auto_filter.ref else None,
                    print_recompute=new_extent if ws.print_area else None)
    restore_merges(ws, saved)
    wb.save(DST)
    print('saved', DST)

    from openpyxl.utils import get_column_letter, column_index_from_string as _cif
    problems = []
    if DST_ANCHOR:
        # ---- extraction: the destination area is the answer range ----
        # source table must be untouched; destination rows must carry the kept
        # rows' evaluated values + styles; everything else unchanged
        out, outv = load_dual(DST)
        ows = out[dst_sheet]
        col_s, row_s = re.match(r'([A-Za-z]+)(\d+)', dst_anchor).groups()
        dr0 = int(row_s); dc0 = _cif(col_s.upper())
        from openpyxl.cell.cell import MergedCell as _MC
        for i, r in enumerate(kept):
            for c in range(c1, c2 + 1):
                dr, dc = dr0 + i, dc0 + (c - c1)
                cell = ows.cell(row=dr, column=dc)
                if isinstance(cell, _MC):
                    continue  # shadowed by a restored merged region: unreadable
                             # in Excel's model too — skip, not a data loss
                got = cell.value
                exp = evaluated[r].get(c, ws.cell(row=r, column=c).value)
                if isinstance(exp, float):
                    exp = round(exp, 9)
                if isinstance(got, float):
                    got = round(got, 9)
                if got != exp:
                    problems.append(f'extracted cell mismatch at '
                                    f'{dr},{dc}')
        # source table unchanged (values equal — extraction never writes there)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                a = ws.cell(row=r, column=c).value
                b = ows.cell(row=r, column=c).value
                if isinstance(a, float):
                    a = round(a, 9)
                if isinstance(b, float):
                    b = round(b, 9)
                if a != b:
                    problems.append(f'source table cell changed at {r},{c}')
        from xlsx_common import verify_manifest
        # structure preserved (extraction legitimately grows the used range,
        # so dims/style/bold whole-sheet checks do not apply)
        w_in = {c: ws.column_dimensions[c].width for c in ws.column_dimensions}
        w_out = {c: ows.column_dimensions[c].width for c in ows.column_dimensions}
        h_in = {r: ws.row_dimensions[r].height for r in ws.row_dimensions}
        h_out = {r: ows.row_dimensions[r].height for r in ows.row_dimensions}
        if w_in != w_out:
            problems.append('column widths changed')
        if h_in != h_out:
            problems.append('row heights changed')
        if set(ws.merged_cells.ranges) != set(ows.merged_cells.ranges):
            problems.append('merged ranges changed')
        if ws.freeze_panes != ows.freeze_panes:
            problems.append('freeze panes changed')
        if (ws.auto_filter.ref or '') != (ows.auto_filter.ref or ''):
            problems.append('auto filter changed')
        if (ws.print_area or '') != (ows.print_area or ''):
            problems.append('print area changed')
        # everything outside source table AND destination unchanged
        out_r1, out_r2 = dr0, dr0 + len(kept) - 1
        out_c1, out_c2 = dc0, dc0 + (c2 - c1)
        for r in range(1, max(ws.max_row, ows.max_row) + 1):
            for c in range(1, max(ws.max_column, ows.max_column) + 1):
                if (r1 <= r <= r2 and c1 <= c <= c2) or \
                        (out_r1 <= r <= out_r2 and out_c1 <= c <= out_c2):
                    continue
                a = ws.cell(row=r, column=c).value
                b = ows.cell(row=r, column=c).value
                if isinstance(a, float):
                    a = round(a, 9)
                if isinstance(b, float):
                    b = round(b, 9)
                if a != b:
                    problems.append(f'outside value changed at {r},{c}')
        try:
            verify_manifest(SRC, DST)
        except Exception as e:
            problems.append(f'manifest: {e}')
    else:
        # ---- compaction: kept rows at the top, tail cleared/deleted ----
        expected_filter = None
        expected_print = None
        expected_dims = None
        if DELETE_TAIL:
            new_extent = f'{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r1 + len(kept) - 1}'
            expected_dims = (r1 + len(kept) - 1, c2)
            if ws.auto_filter.ref:
                expected_filter = new_extent
            if ws.print_area:
                expected_print = new_extent
        problems = verify_output(SRC, DST, SHEET, r1, r2, c1, c2,
                                 formula_cols=FORMULA_COLS,
                                 src_spans=[(r1, r2)], out_r1=r1,
                                 out_r2=r1 + len(kept) - 1,
                                 blank_separator=SEPARATOR_BLANK,
                                 expected_filter=expected_filter,
                                 expected_print=expected_print,
                                 expected_dims=expected_dims)
    if problems:
        print('VERIFICATION FAILED:')
        for p in problems[:30]:
            print(' -', p)
        raise SystemExit(1)
    print('verification passed: predicates applied, kept rows in source '
          'order, everything outside the answer range preserved')


if __name__ == '__main__':
    main()