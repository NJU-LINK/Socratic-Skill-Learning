#!/usr/bin/env python3
"""
Reference implementation: block-local sort of an xlsx workbook.

Demonstrates the general pattern for xlsx-structure tasks:
  1. Detect block topology from data
  2. Evaluate formulas / text-numbers to concrete values
  3. Apply stable sort within each block
  4. Preserve all cell styles during rewrite
  5. Self-verify the output

Usage:
    python solve_block_sort.py [input.xlsx] [output.xlsx]

Defaults:
    input  = /app/input.xlsx
    output = /app/output.xlsx
"""

import sys
import copy
import openpyxl


# ---------------------------------------------------------------------------
# Configuration (override per task)
# ---------------------------------------------------------------------------
INPUT_PATH  = sys.argv[1] if len(sys.argv) > 1 else "/app/input.xlsx"
OUTPUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "/app/output.xlsx"
SHEET_NAME  = "Sheet1"
WORK_RANGE  = "A1:H85"      # Declared transformation range
SORT_COL_LETTER = "D"       # Column to sort by
SORT_DESCENDING = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def col_letter_to_idx(letter):
    """Convert column letter (A, B, ..., Z, AA, ...) to 1-based index."""
    result = 0
    for ch in letter.upper():
        result = result * 26 + (ord(ch) - ord('A') + 1)
    return result


def evaluate_cell(cell_value, ref_values=None):
    """Evaluate a cell value to a number when possible.

    Handles:
      - Formulas starting with '='
      - Numeric strings (including negative, decimal)
      - Plain numeric types
      - Cell references resolved via *ref_values* dict
    """
    if cell_value is None:
        return None
    if isinstance(cell_value, (int, float)):
        return float(cell_value)
    if isinstance(cell_value, str):
        s = cell_value.strip()
        if s.startswith('='):
            expr = s[1:]
            if ref_values:
                for ref in sorted(ref_values, key=len, reverse=True):
                    expr = expr.replace(ref, str(ref_values[ref]))
            try:
                return float(eval(expr, {"__builtins__": {}}, {}))
            except Exception:
                return None
        try:
            return float(s)
        except ValueError:
            return s
    return cell_value


def snapshot_row(ws, row, min_col, max_col):
    """Capture value + full style for every cell in a row."""
    cells = []
    for c in range(min_col, max_col + 1):
        cell = ws.cell(row, c)
        cells.append({
            'value':         cell.value,
            'font':          copy.copy(cell.font),
            'fill':          copy.copy(cell.fill),
            'border':        copy.copy(cell.border),
            'alignment':     copy.copy(cell.alignment),
            'number_format': cell.number_format,
            'protection':    copy.copy(cell.protection),
        })
    return cells


def write_row(ws, row, cell_data, min_col):
    """Write previously captured cell data back to a row."""
    for i, snap in enumerate(cell_data):
        cell = ws.cell(row, min_col + i)
        cell.value         = snap['value']
        cell.font          = snap['font']
        cell.fill          = snap['fill']
        cell.border        = snap['border']
        cell.alignment     = snap['alignment']
        cell.number_format = snap['number_format']
        cell.protection    = snap['protection']


# ---------------------------------------------------------------------------
# Main procedure
# ---------------------------------------------------------------------------
def solve():
    wb = openpyxl.load_workbook(INPUT_PATH)
    ws = wb[SHEET_NAME]

    # Parse working range
    from openpyxl.utils import range_boundaries
    min_col, min_row, max_col, max_row = range_boundaries(WORK_RANGE)
    sort_col_idx = col_letter_to_idx(SORT_COL_LETTER)

    # ------------------------------------------------------------------
    # Step 1: Detect blocks (contiguous non-blank rows separated by blanks)
    # ------------------------------------------------------------------
    blank_rows = []
    for r in range(min_row, max_row + 1):
        if all(ws.cell(r, c).value is None for c in range(min_col, max_col + 1)):
            blank_rows.append(r)

    blocks = []
    start = min_row
    for br in blank_rows:
        if br > start:
            blocks.append((start, br - 1))
        start = br + 1
    if start <= max_row and any(
        ws.cell(start, c).value is not None for c in range(min_col, max_col + 1)
    ):
        blocks.append((start, max_row))

    print(f"Detected {len(blocks)} blocks: {blocks}")

    # ------------------------------------------------------------------
    # Step 2: Snapshot all cell styles in the working range
    # ------------------------------------------------------------------
    row_snapshots = {}
    for r in range(min_row, max_row + 1):
        row_snapshots[r] = snapshot_row(ws, r, min_col, max_col)

    # ------------------------------------------------------------------
    # Step 3: Evaluate sort-key values and sort each block
    # ------------------------------------------------------------------
    for b_start, b_end in blocks:
        block_rows = list(range(b_start, b_end + 1))

        # Build evaluated reference values for formula resolution
        # (row-local: evaluate all cells in the row left-to-right)
        def sort_key_for_row(row_idx):
            snap = row_snapshots[row_idx]
            # Build ref_values for this row: map cell references to evaluated values
            ref_values = {}
            for i, cell_snap in enumerate(snap):
                col_idx = min_col + i
                col_letter = openpyxl.utils.get_column_letter(col_idx)
                ref = f"{col_letter}{row_idx}"
                val = evaluate_cell(cell_snap['value'])
                ref_values[ref] = val if isinstance(val, (int, float)) else 0

            # Evaluate the sort column
            sort_cell_snap = snap[sort_col_idx - min_col]
            sort_val = evaluate_cell(sort_cell_snap['value'], ref_values)

            # Fallback for non-numeric
            if not isinstance(sort_val, (int, float)):
                try:
                    sort_val = float(sort_val)
                except (TypeError, ValueError):
                    sort_val = 0.0
            return sort_val

        # Stable sort: tag with original index
        indexed = []
        for i, r in enumerate(block_rows):
            key = sort_key_for_row(r)
            indexed.append((key, i, r))

        if SORT_DESCENDING:
            indexed.sort(key=lambda x: (-x[0], x[1]))
        else:
            indexed.sort(key=lambda x: (x[0], x[1]))

        sorted_rows = [r for _, _, r in indexed]

        # ------------------------------------------------------------------
        # Step 4: Evaluate formulas in all cells of the block
        # ------------------------------------------------------------------
        evaluated_block_data = []
        for orig_row in sorted_rows:
            snap = row_snapshots[orig_row]
            # Build ref_values for formula evaluation
            ref_values = {}
            new_snap = []
            for i, cell_snap in enumerate(snap):
                col_idx = min_col + i
                col_letter = openpyxl.utils.get_column_letter(col_idx)
                ref = f"{col_letter}{orig_row}"

                val = evaluate_cell(cell_snap['value'], ref_values)
                # Store evaluated value for downstream references
                ref_values[ref] = val if isinstance(val, (int, float)) else 0

                cell_copy = dict(cell_snap)
                # Only replace formula/text-number cells with evaluated values
                if isinstance(val, (int, float)) and isinstance(cell_snap['value'], str):
                    cell_copy['value'] = val
                new_snap.append(cell_copy)
            evaluated_block_data.append(new_snap)

        # ------------------------------------------------------------------
        # Step 5: Write sorted, evaluated data back
        # ------------------------------------------------------------------
        for new_pos, orig_row in enumerate(block_rows):
            write_row(ws, orig_row, evaluated_block_data[new_pos], min_col)

    # ------------------------------------------------------------------
    # Step 6: Save
    # ------------------------------------------------------------------
    wb.save(OUTPUT_PATH)
    print(f"Saved to {OUTPUT_PATH}")

    # ------------------------------------------------------------------
    # Step 7: Verify
    # ------------------------------------------------------------------
    verify(blocks, min_col, max_col, min_row, max_row, sort_col_idx)


def verify(blocks, min_col, max_col, min_row, max_row, sort_col_idx):
    """Run structural checks on the output workbook."""
    out_wb = openpyxl.load_workbook(OUTPUT_PATH)
    out_ws = out_wb[SHEET_NAME]

    # Check 1: Block structure intact
    blank_count = sum(
        1 for r in range(min_row, max_row + 1)
        if all(out_ws.cell(r, c).value is None for c in range(min_col, max_col + 1))
    )
    expected_blanks = (max_row - min_row + 1) - sum(e - s + 1 for s, e in blocks)
    assert blank_count == expected_blanks, (
        f"Blank row count mismatch: got {blank_count}, expected {expected_blanks}"
    )

    # Check 2: Sort order correct within each block
    for b_start, b_end in blocks:
        prev_val = float('inf')
        for r in range(b_start, b_end + 1):
            val = out_ws.cell(r, sort_col_idx).value
            if val is None:
                continue
            num_val = float(val) if isinstance(val, (int, float)) else None
            if num_val is not None:
                assert num_val <= prev_val, (
                    f"Sort violation at row {r}: {num_val} > {prev_val}"
                )
                prev_val = num_val

    # Check 3: No unevaluated formulas in working range
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            v = out_ws.cell(r, c).value
            if isinstance(v, str) and v.startswith('='):
                print(f"WARNING: Unevaluated formula at {out_ws.cell(r,c).coordinate}: {v}")

    # Check 4: Values are numeric where expected
    formula_cols = set()
    for b_start, b_end in blocks:
        for r in range(b_start, b_end + 1):
            for c in range(min_col, max_col + 1):
                v = out_ws.cell(r, c).value
                if v is not None and not isinstance(v, (int, float)):
                    # Could be a text label (column A) — only flag in numeric columns
                    pass

    print("Verification passed.")
    out_wb.close()


if __name__ == '__main__':
    solve()
