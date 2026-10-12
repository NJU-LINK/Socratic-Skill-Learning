#!/usr/bin/env python3
"""Inventory an xlsx workbook: sheets, extents, data types, blank rows, block
spans, formulas + cached values, styles (bold/fill), widths/heights, merges,
filters, panes, print areas. Run: python3 inspect_workbook.py <file.xlsx>

Use the output to locate the source/destination artifacts named by the task
instruction. Remember: max_row/max_column include styled-but-empty cells; for
data extents scan cell.value is not None."""
import sys
from collections import Counter

import openpyxl

from xlsx_common import find_blocks, parse_a1


def main(path):
    wb = openpyxl.load_workbook(path)
    wbv = openpyxl.load_workbook(path, data_only=True)
    print('sheets:', wb.sheetnames)
    for name in wb.sheetnames:
        ws, wsv = wb[name], wbv[name]
        print(f'\n=== sheet {name!r} ===')
        print('max_row/max_column:', ws.max_row, ws.max_column)
        print('merged:', list(ws.merged_cells.ranges))
        print('freeze_panes:', ws.freeze_panes)
        print('auto_filter:', ws.auto_filter.ref)
        print('print_area:', ws.print_area)
        widths = {c: ws.column_dimensions[c].width
                  for c in ws.column_dimensions if ws.column_dimensions[c].width}
        heights = {r: ws.row_dimensions[r].height
                   for r in ws.row_dimensions if ws.row_dimensions[r].height}
        print('column widths:', widths)
        print('row heights (first 12):', list(heights.items())[:12])
        # data extent (value-based)
        cells = [(r, c) for r in range(1, ws.max_row + 1)
                 for c in range(1, ws.max_column + 1)
                 if ws.cell(row=r, column=c).value is not None]
        if cells:
            rs = [r for r, _ in cells]; cs = [c for _, c in cells]
            print(f'data extent: A{min(rs)}:{openpyxl.utils.get_column_letter(max(cs))}{max(rs)} '
                  f'({len(cells)} non-empty cells)')
        # data types per column over data rows
        types = Counter()
        for r, c in cells:
            types[(c, ws.cell(row=r, column=c).data_type)] += 1
        print('data types (col -> counts):',
              {openpyxl.utils.get_column_letter(c) + k: n
               for (c, k), n in sorted(types.items())})
        # formulas and cached values
        formulas = [(r, c, ws.cell(row=r, column=c).value, wsv.cell(row=r, column=c).value)
                    for r, c in cells if ws.cell(row=r, column=c).data_type == 'f']
        text_formulas = [(r, c, ws.cell(row=r, column=c).value)
                         for r, c in cells
                         if isinstance(ws.cell(row=r, column=c).value, str)
                         and ws.cell(row=r, column=c).value.startswith('=')]
        print('formula cells (first 8):', formulas[:8], f'({len(formulas)} total)')
        print('text formulas (first 8):', text_formulas[:8], f'({len(text_formulas)} total)')
        # bold / fill-styled cells
        bold = [(r, c) for r, c in cells if ws.cell(row=r, column=c).font.bold]
        filled = [(r, c, ws.cell(row=r, column=c).fill.patternType,
                   ws.cell(row=r, column=c).fill.fgColor.rgb if ws.cell(row=r, column=c).fill.fgColor else None)
                  for r, c in cells
                  if ws.cell(row=r, column=c).fill.patternType not in (None, 'none')]
        print('bold cells (among non-empty cells):', len(bold), bold[:10])
        print('fill-styled cells:', filled[:10])
        # sample rows (first 12) with full column span
        cols = min(cs) if cells else 1
        for r in range(1, min(ws.max_row, 14) + 1):
            rowvals = []
            for c in range(1, max(cs) + 1 if cells else 1):
                cell = ws.cell(row=r, column=c)
                v = cell.value
                if cell.data_type == 'f':
                    v = 'F:' + repr(v)
                rowvals.append(repr(v)[:22])
            print(r, rowvals)
        # block structure over the data extent
        if cells:
            r1, r2 = min(rs), max(rs)
            c1, c2 = min(cs), max(cs)
            print('blocks (blank-separated, over data extent):',
                  find_blocks(ws, r1, r2, c1, c2))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/app/input.xlsx')