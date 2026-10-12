#!/usr/bin/env python3
"""Sparse-record reconciliation solver for the xlsx-structure family.

An ordered ID list pairs with a sparse table whose rows carry an ID column.
Output: one row per list entry, in list order, starting at DST_ANCHOR; each
output row mirrors the sparse table's column layout at the anchor: the sparse
record's cells (values + styles, formulas evaluated) land at their relative
column offsets, the ID column slot holds the ID from the LIST (or the matched
record's ID); IDs absent from the sparse table produce a blank row (ID slot
only when WRITE_ID=True). Alignment is by exact ID identity.

Config mapping:
- "order the rows A2:A9 ... by the list in B1:B6" -> ID_LIST range = ID
  provider; SPARSE range = the table to reorder; SPARSE_ID_COL = its ID column.
- "write the result starting at D2 / into Sheet2!A1" -> DST_ANCHOR.
- "rows/IDs not present in the table stay blank" -> WRITE_ID=False (blank row).
"""
import re
from copy import copy

from openpyxl.utils import column_index_from_string

from xlsx_common import (assert_standard_parts, capture_merges, clean_num,
                         evaluate_formula, load_dual, parse_a1, restore_merges,
                         verify_manifest, verify_workbook_state)

# ---------------- config (per task) ----------------
SRC = '/app/input.xlsx'
DST = '/app/output.xlsx'
SHEET = 'Sheet1'
ID_LIST = 'B2:B9'        # ordered list of IDs (single-column range)
SPARSE = 'D2:F20'        # sparse table range (records carrying an ID column)
SPARSE_ID_COL = 1        # 1-based column WITHIN SPARSE holding the ID
DST_ANCHOR = 'A2'        # first output row ('Sheet2!A1' supported)
WRITE_ID = True          # True -> the ID slot of each output row = list ID
FORMULA_COLS = ()        # formula columns within SPARSE to evaluate to numbers
# ----------------------------------------------------


def main():
    assert_standard_parts(SRC)
    wb, wbv = load_dual(SRC)
    ws = wb[SHEET]
    sp_r1, sp_r2, sp_c1, sp_c2 = parse_a1(SPARSE)
    id_r1, id_r2, id_c1, id_c2 = parse_a1(ID_LIST)
    ids = [ws.cell(row=r, column=id_c1).value for r in range(id_r1, id_r2 + 1)
           if ws.cell(row=r, column=id_c1).value is not None]
    id_col = sp_c1 + SPARSE_ID_COL - 1
    slug = lambda v: str(v).strip().lower()
    by_id = {}
    cache = {}
    for r in range(sp_r1, sp_r2 + 1):
        key = ws.cell(row=r, column=id_col).value
        if key is None:
            continue
        rv = {c: ws.cell(row=r, column=c).value for c in range(sp_c1, sp_c2 + 1)}
        for c in sorted(FORMULA_COLS):
            v = rv.get(c)
            if isinstance(v, str) and v.startswith('='):
                rv[c] = evaluate_formula(v, ws, r, rv, cache)
        by_id.setdefault(slug(key), (r, rv))
    print('ids in list:', len(ids), '| sparse records:', len(by_id))

    dst_sheet, anchor = SHEET, DST_ANCHOR
    if '!' in anchor:
        dst_sheet, anchor = anchor.split('!', 1)
    if dst_sheet not in wb.sheetnames:
        wb.create_sheet(dst_sheet)
    col_s, row_s = re.match(r'([A-Za-z]+)(\d+)', anchor).groups()
    ar, ac = int(row_s), column_index_from_string(col_s.upper())
    d_ws = wb[dst_sheet]
    span = sp_c2 - sp_c1 + 1
    saved = capture_merges(d_ws, range(ar, ar + len(ids)),
                           range(ac, ac + span))
    n_missing = 0
    for i, key in enumerate(ids):
        dst_r = ar + i
        rec = by_id.get(slug(key))
        if rec is None:
            n_missing += 1
            if WRITE_ID:
                d_ws.cell(row=dst_r, column=ac + SPARSE_ID_COL - 1).value = key
            continue
        src_r, rv = rec
        # copy the whole sparse record (values + styles, formulas evaluated)
        for c in range(sp_c1, sp_c2 + 1):
            s = ws.cell(row=src_r, column=c)
            d = d_ws.cell(row=dst_r, column=ac + (c - sp_c1))
            d._style = copy(s._style)
            v = s.value
            if c in FORMULA_COLS and isinstance(v, str) and v.startswith('='):
                v = clean_num(rv.get(c, v))
            d.value = v
        if WRITE_ID:
            # ID slot shows the list's ID (style stays the record's)
            d_ws.cell(row=dst_r, column=ac + SPARSE_ID_COL - 1).value = key
    restore_merges(d_ws, saved)
    wb.save(DST)
    print('saved', DST, '| missing IDs (blank rows):', n_missing)

    # verification
    out, outv = load_dual(DST)
    ows = out[dst_sheet]
    problems = []
    out_ids = [ows.cell(row=ar + i, column=ac + SPARSE_ID_COL - 1).value
               for i in range(len(ids))]
    if [slug(x) if x is not None else None for x in out_ids] != [slug(x) for x in ids]:
        problems.append('destination ID column does not match the ID list order')
    if dst_sheet == SHEET:
        # source sparse table is the (possibly overlapping) answer area
        problems += verify_workbook_state(ws, ows, sp_r1, sp_r2, sp_c1, sp_c2,
                                          formula_cols=FORMULA_COLS, issues=[])
        try:
            verify_manifest(SRC, DST)
        except Exception as e:
            problems.append(f'manifest: {e}')
    else:
        # verify the SOURCE sheet is untouched and the manifest is safe
        problems += verify_workbook_state(ws, out[SHEET],
                                          1, ws.max_row, 1, ws.max_column,
                                          issues=[])
        try:
            verify_manifest(SRC, DST)
        except Exception as e:
            problems.append(f'manifest: {e}')
    if problems:
        print('VERIFICATION FAILED:')
        for p in problems[:30]:
            print(' -', p)
        raise SystemExit(1)
    print('verification passed: destination is in ID-list order, source intact')


if __name__ == '__main__':
    main()