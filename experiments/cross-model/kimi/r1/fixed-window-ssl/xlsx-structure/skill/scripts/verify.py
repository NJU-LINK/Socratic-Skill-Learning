"""
Verification harness for xlsx-structure transformations.

A verifier that can't fail is worse than no verifier.
All checks must be load-bearing: sys.exit(1) on failure.
"""

import sys
import math
from collections import Counter
from openpyxl import load_workbook


def is_close(a, b, abs_tol=1e-9):
    """Compare floats with tolerance for IEEE-754 noise."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=0, abs_tol=abs_tol)
    return a == b


def canonicalize_row(row_tuple, eval_cols=None):
    """
    Convert row to comparable form with float rounding for evaluated columns.
    
    Args:
        row_tuple: Tuple of cell values
        eval_cols: Set of 0-based column indices that may have float noise
    """
    if eval_cols is None:
        eval_cols = {3, 4, 5}  # D, E, F (0-indexed)
    
    result = []
    for i, v in enumerate(row_tuple):
        if i in eval_cols and isinstance(v, float):
            result.append(round(v, 9))
        else:
            result.append(v)
    return tuple(result)


def verify_full_grid(input_path, output_path, target_sheet='Sheet1',
                     target_range=None):
    """
    Verify that output matches input outside target range,
    and that target range has no string formulas.
    
    Args:
        input_path: Path to input xlsx
        output_path: Path to output xlsx
        target_sheet: Sheet name containing transformation
        target_range: (start_row, end_row, start_col, end_col) inclusive, 1-based
                     If None, checks entire sheet
    
    Raises:
        AssertionError: On any verification failure
    """
    # Check output has no formula strings in D/E/F (columns 4, 5, 6)
    wb_out = load_workbook(output_path, data_only=False)
    ws_out = wb_out[target_sheet]
    
    if target_range:
        tr_min_r, tr_max_r, tr_min_c, tr_max_c = target_range
        for r in range(tr_min_r, tr_max_r + 1):
            for c in range(tr_min_c, tr_max_c + 1):
                if c in [4, 5, 6]:  # D, E, F
                    v = ws_out.cell(row=r, column=c).value
                    assert not isinstance(v, str) or not v.startswith('='), \
                        f"Unevaluated formula at {target_sheet}!{r},{c}: {v!r}"
    
    # Check preservation outside target range
    wa = load_workbook(input_path, data_only=True)
    wb = load_workbook(output_path, data_only=True)
    
    assert wa.sheetnames == wb.sheetnames, \
        f"Sheet names differ: {wa.sheetnames} vs {wb.sheetnames}"
    
    tr_min_r = tr_max_r = tr_min_c = tr_max_c = None
    if target_range:
        tr_min_r, tr_max_r, tr_min_c, tr_max_c = target_range
    
    for sn in wa.sheetnames:
        a, b = wa[sn], wb[sn]
        max_r = max(a.max_row, b.max_row)
        max_c = max(a.max_column, b.max_column)
        
        for r in range(1, max_r + 1):
            for c in range(1, max_c + 1):
                in_target = (target_range and 
                           sn == target_sheet and 
                           tr_min_r <= r <= tr_max_r and 
                           tr_min_c <= c <= tr_max_c)
                
                if in_target:
                    continue  # Skip target range in preservation check
                
                # Outside target range: exact match required
                va, vb = a.cell(row=r, column=c).value, b.cell(row=r, column=c).value
                assert va == vb, \
                    f"Preservation violation at {sn}!{r},{c}: {va!r} vs {vb!r}"
    
    print("Full grid preservation check passed")


def verify_blank_separators(ws_in, ws_out, blank_rows, num_cols=8):
    """
    Verify blank separator rows are preserved (not clobbered).
    
    Args:
        ws_in: Input worksheet
        ws_out: Output worksheet  
        blank_rows: List of row numbers that should be blank
        num_cols: Columns to check
    
    Raises:
        AssertionError: If a blank row is clobbered
    """
    for r in blank_rows:
        for c in range(1, num_cols + 1):
            v = ws_out.cell(row=r, column=c).value
            assert v in (None, ''), f"Separator row {r} col {c} clobbered: {v!r}"
    print(f"Blank separators preserved: {len(blank_rows)} rows")


def verify_multiset(input_rows, output_rows, eval_cols=None):
    """
    Verify that input and output contain the same multiset of rows.
    
    Args:
        input_rows: List of row tuples from input
        output_rows: List of row tuples from output
        eval_cols: Columns that may have float noise
    
    Raises:
        AssertionError: If multisets differ
    """
    in_canon = [canonicalize_row(r, eval_cols) for r in input_rows]
    out_canon = [canonicalize_row(r, eval_cols) for r in output_rows]
    
    if Counter(in_canon) != Counter(out_canon):
        in_counter = Counter(in_canon)
        out_counter = Counter(out_canon)
        
        missing = list((in_counter - out_counter).elements())
        extra = list((out_counter - in_counter).elements())
        
        msg = f"Multiset mismatch: {len(missing)} missing, {len(extra)} extra"
        if missing:
            msg += f"\n  Missing: {missing[:3]}"
        if extra:
            msg += f"\n  Extra: {extra[:3]}"
        raise AssertionError(msg)
    
    print("Multiset check passed")


def verify_sorted(values, key_index=3, reverse=True, abs_tol=1e-9):
    """
    Verify that values are sorted by key_index.
    
    Args:
        values: List of row tuples
        key_index: 0-based index of sort key
        reverse: True if descending
        abs_tol: Float tolerance
    """
    for i in range(len(values) - 1):
        a, b = values[i][key_index], values[i + 1][key_index]
        if a is None or b is None:
            continue
        if reverse:
            assert is_close(a, b, abs_tol) or a >= b - abs_tol, \
                f"Not sorted descending at position {i}: {a} then {b}"
        else:
            assert is_close(a, b, abs_tol) or a <= b + abs_tol, \
                f"Not sorted ascending at position {i}: {a} then {b}"
    
    print(f"Sort order check passed ({'descending' if reverse else 'ascending'})")


def run_verification(input_path, output_path, blocks, blank_rows, target_sheet='Sheet1',
                     sort_key_col=4, reverse=True, eval_cols=None):
    """
    Run complete verification suite.
    
    Args:
        input_path: Path to input xlsx
        output_path: Path to output xlsx
        blocks: List of (start_row, end_row) tuples defining blocks
        blank_rows: List of row numbers that should be blank
        target_sheet: Sheet name
        sort_key_col: 1-based column index used for sorting
        reverse: True if descending sort
        eval_cols: Set of 0-based column indices with evaluated floats
                  Default: {3, 4, 5} for D, E, F
    
    Returns:
        True if all checks pass
    
    Raises:
        AssertionError: On first failure
    """
    if eval_cols is None:
        eval_cols = {3, 4, 5}  # D, E, F
    
    from openpyxl import load_workbook
    
    # Load input with formulas (for evaluation)
    wa_formula = load_workbook(input_path, data_only=False)
    ws_a_formula = wa_formula[target_sheet]
    
    # Load output with data (for comparison)
    wb = load_workbook(output_path, data_only=True)
    ws_b = wb[target_sheet]
    
    # Full grid preservation (checks no formula strings in output)
    max_r = max(r for _, r in blocks)
    verify_full_grid(input_path, output_path, target_sheet, (1, max_r, 1, 8))
    
    # Blank separator check
    ws_out_formula = load_workbook(output_path, data_only=False)[target_sheet]
    verify_blank_separators(ws_a_formula, ws_out_formula, blank_rows)
    
    # Per-block checks with evaluation
    from xlsx_eval import evaluate_cell
    
    for start, end in blocks:
        # Build input rows using evaluation (not cached values)
        in_rows = []
        for r in range(start, end + 1):
            row_vals = []
            for c in range(1, 9):
                if (c - 1) in eval_cols:
                    # Evaluate formula
                    row_vals.append(evaluate_cell(ws_a_formula, r, c))
                else:
                    # Read raw value
                    row_vals.append(ws_a_formula.cell(row=r, column=c).value)
            in_rows.append(tuple(row_vals))
        
        # Read output rows
        out_rows = [tuple(ws_b.cell(row=r, column=c).value 
                         for c in range(1, 9)) for r in range(start, end + 1)]
        
        # Multiset check
        verify_multiset(in_rows, out_rows, eval_cols)
        
        # Sort order check
        verify_sorted(out_rows, sort_key_col - 1, reverse)
    
    return True


if __name__ == '__main__':
    # Example usage
    import sys
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.xlsx output.xlsx")
        sys.exit(1)
    
    input_path, output_path = sys.argv[1], sys.argv[2]
    
    try:
        verify_full_grid(input_path, output_path, 'Sheet1', (1, 85, 1, 8))
        print("\nAll verification checks passed!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\nVERIFICATION FAILED: {e}")
        sys.exit(1)
