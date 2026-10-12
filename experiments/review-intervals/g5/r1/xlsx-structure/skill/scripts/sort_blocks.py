#!/usr/bin/env python3
"""
sort_blocks.py — Parameterized block-local descending sort for xlsx workbooks.

Detects variable-length nonempty blocks separated by blank rows within a
specified range, evaluates row-local formulas in dependency order, sorts each
block by a specified column in descending order (stable — ties preserve
original order), and writes results back preserving all cell styles.

Usage:
    python3 sort_blocks.py [OPTIONS]

Options:
    --input PATH        Input xlsx file (default: /app/input.xlsx)
    --output PATH       Output xlsx file (default: /app/output.xlsx)
    --range RANGE       Cell range to process, e.g. A1:H85 (default: auto-detect)
    --sort-col COL      Column letter to sort by (default: D)
    --reverse           Sort descending (default: True)
    --no-reverse        Sort ascending
    --formula-cols COLS Comma-separated columns that may contain formulas,
                        in dependency order, or "auto" to detect from data
                        (default: auto)
"""

import argparse
import re
import sys
from copy import copy

import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string


def parse_range(range_str):
    """Parse 'A1:H85' into (min_row, min_col, max_row, max_col)."""
    m = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', range_str.upper())
    if not m:
        raise ValueError(f"Invalid range: {range_str}")
    return (
        int(m.group(2)),
        column_index_from_string(m.group(1)),
        int(m.group(4)),
        column_index_from_string(m.group(3)),
    )


def is_blank_row(ws, row, min_col, max_col):
    """Check if all cells in [min_col, max_col] are None."""
    return all(ws.cell(row, c).value is None for c in range(min_col, max_col + 1))


def detect_blocks(ws, min_row, max_row, min_col, max_col):
    """
    Detect variable-length nonempty blocks separated by blank rows.
    Returns list of lists of row numbers.
    """
    blocks = []
    current_block = []
    for r in range(min_row, max_row + 1):
        if is_blank_row(ws, r, min_col, max_col):
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(r)
    if current_block:
        blocks.append(current_block)
    return blocks


def eval_formula(formula_str, row_values):
    """
    Evaluate a simple arithmetic formula string.
    row_values: dict mapping column letter (str) -> numeric value.
    Handles cell references like B1, C12, D5.
    Rounds float results to 10 decimal places to clean IEEE 754 noise.
    """
    if not isinstance(formula_str, str) or not formula_str.startswith('='):
        return formula_str
    expr = formula_str[1:]
    # Replace cell references (e.g., B1, C12) with their numeric values
    def sub(m):
        col = m.group(1).upper()
        val = row_values.get(col, 0)
        return str(val if val is not None else 0)
    expr = re.sub(r'([A-Z])\d+', sub, expr)
    result = eval(expr, {"__builtins__": {}}, {})
    if isinstance(result, float):
        result = round(result, 10)
    return result


def capture_cell(cell):
    """Capture a cell's value and all style attributes."""
    return {
        'value': cell.value,
        'font': copy(cell.font),
        'fill': copy(cell.fill),
        'border': copy(cell.border),
        'alignment': copy(cell.alignment),
        'number_format': cell.number_format,
        'protection': copy(cell.protection),
    }


def apply_cell(target_cell, captured):
    """Write captured value and styles into a target cell."""
    target_cell.value = captured['value']
    target_cell.font = captured['font']
    target_cell.fill = captured['fill']
    target_cell.border = captured['border']
    target_cell.alignment = captured['alignment']
    target_cell.number_format = captured['number_format']
    target_cell.protection = captured['protection']


def get_row_data(ws, row_num, min_col, max_col):
    """Capture all cells in a row within [min_col, max_col]."""
    return [capture_cell(ws.cell(row_num, c)) for c in range(min_col, max_col + 1)]


def evaluate_formulas_in_row(cells_data, min_col, formula_col_indices):
    """
    Evaluate formulas in specified columns in dependency order.
    cells_data: list of captured cell dicts (index 0 = min_col).
    formula_col_indices: list of 1-based column indices in dependency order.
    """
    # Build initial row_values from non-formula numeric values
    row_values = {}
    for i, cd in enumerate(cells_data):
        col_letter = get_column_letter(min_col + i)
        val = cd['value']
        if isinstance(val, (int, float)):
            row_values[col_letter] = val

    for col_idx in formula_col_indices:
        offset = col_idx - min_col
        if offset < 0 or offset >= len(cells_data):
            continue
        val = cells_data[offset]['value']
        if isinstance(val, str) and val.startswith('='):
            evaluated = eval_formula(val, row_values)
            cells_data[offset]['value'] = evaluated
            row_values[get_column_letter(col_idx)] = evaluated


def auto_detect_formula_columns(ws, min_row, max_row, min_col, max_col):
    """
    Scan the transform range for cells containing formulas.
    Returns column indices sorted left-to-right (dependency order for
    simple row-local arithmetic where later columns may reference earlier ones).
    """
    formula_cols = set()
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            val = ws.cell(r, c).value
            if isinstance(val, str) and val.startswith('='):
                formula_cols.add(c)
    return sorted(formula_cols)


def sort_blocks_and_write(ws, blocks, min_col, max_col, sort_col_idx,
                          formula_col_indices, reverse=True):
    """
    For each block: read data, evaluate formulas, sort by sort_col, write back.
    """
    for block_rows in blocks:
        # Read all row data with styles
        rows_data = []
        for r in block_rows:
            cells = get_row_data(ws, r, min_col, max_col)
            rows_data.append(cells)

        # Evaluate formulas in dependency order
        for cells in rows_data:
            evaluate_formulas_in_row(cells, min_col, formula_col_indices)

        # Sort by the specified column (stable sort preserves ties)
        sort_offset = sort_col_idx - min_col
        rows_data.sort(
            key=lambda cells: (
                cells[sort_offset]['value']
                if isinstance(cells[sort_offset]['value'], (int, float))
                else float('-inf')
            ),
            reverse=reverse,
        )

        # Write back to original positions
        for i, cells in enumerate(rows_data):
            target_row = block_rows[i]
            for j, cd in enumerate(cells):
                apply_cell(ws.cell(target_row, min_col + j), cd)


def main():
    parser = argparse.ArgumentParser(description='Block-local sort for xlsx')
    parser.add_argument('--input', default='/app/input.xlsx')
    parser.add_argument('--output', default='/app/output.xlsx')
    parser.add_argument('--range', default=None,
                        help='Cell range to process (e.g. A1:H85). '
                             'Auto-detects from data if not specified.')
    parser.add_argument('--sort-col', default='D',
                        help='Column letter to sort by (default: D)')
    parser.add_argument('--reverse', action='store_true', default=True,
                        help='Sort descending (default)')
    parser.add_argument('--no-reverse', action='store_true', default=False,
                        help='Sort ascending')
    parser.add_argument('--formula-cols', default='auto',
                        help='Comma-separated formula columns in dependency order, '
                             'or "auto" to detect from data (default: auto)')
    args = parser.parse_args()

    reverse = not args.no_reverse
    sort_col_idx = column_index_from_string(args.sort_col.upper())

    # Load workbook (preserves styles, formulas, etc.)
    wb = openpyxl.load_workbook(args.input)
    ws = wb.active  # or wb['Sheet1'] — adapt to task

    # Determine processing range
    if args.range:
        min_row, min_col, max_row, max_col = parse_range(args.range)
    else:
        # Auto-detect: scan from A1 until we hit a stretch of blank rows
        min_row, min_col = 1, 1
        max_col = ws.max_column or 8
        max_row = ws.max_row or 1
        # Find actual data extent (last non-blank row)
        for r in range(ws.max_row, 0, -1):
            if not is_blank_row(ws, r, 1, ws.max_column or 8):
                max_row = r
                break

    # Determine formula columns
    if args.formula_cols.lower() == 'auto':
        formula_col_indices = auto_detect_formula_columns(
            ws, min_row, max_row, min_col, max_col
        )
        print(f"Auto-detected formula columns: "
              f"{[get_column_letter(c) for c in formula_col_indices]}")
    else:
        formula_col_indices = [
            column_index_from_string(c.strip().upper())
            for c in args.formula_cols.split(',')
        ]

    # Detect blocks
    blocks = detect_blocks(ws, min_row, max_row, min_col, max_col)
    print(f"Detected {len(blocks)} blocks in range "
          f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}")
    for i, b in enumerate(blocks):
        print(f"  Block {i}: rows {b[0]}-{b[-1]} ({len(b)} rows)")

    # Sort and write
    sort_blocks_and_write(
        ws, blocks, min_col, max_col,
        sort_col_idx, formula_col_indices, reverse
    )

    # Save
    wb.save(args.output)
    print(f"Saved to {args.output}")


if __name__ == '__main__':
    main()
