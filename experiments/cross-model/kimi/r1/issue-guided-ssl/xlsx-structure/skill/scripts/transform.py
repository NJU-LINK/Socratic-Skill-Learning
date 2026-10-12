#!/usr/bin/env python3
"""
General-purpose structural transformation for Excel workbooks.

Supports multiple transformation semantics:
- block-sort: Sort rows within blocks by evaluated values
- block-filter: Filter rows within blocks based on predicates
- block-extract: Extract specific rows from blocks

Core pipeline: detect → extract → evaluate → transform → write → preserve
"""

import argparse
import math
import re
import sys
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple, Callable
import openpyxl


def col_letter_to_num(col_str: str) -> int:
    """Convert column letter (A, B, ..., Z, AA, ...) to 1-based column number."""
    result = 0
    for c in col_str:
        result = result * 26 + (ord(c) - ord('A') + 1)
    return result


def evaluate_formula(formula: Any, sheet, max_recursion: int = 10) -> Any:
    """
    Evaluate a formula string like '=B1+C1' or '=D1+E1'.
    
    Recursively resolves cell references and evaluates arithmetic.
    Returns numeric value or original value if not a formula.
    """
    if formula is None:
        return None
    
    if not isinstance(formula, str):
        try:
            return float(formula)
        except (ValueError, TypeError):
            return formula
    
    if not formula.startswith('='):
        try:
            return float(formula)
        except (ValueError, TypeError):
            return formula
    
    if max_recursion <= 0:
        raise RecursionError(f"Formula recursion depth exceeded (max={max_recursion}). "
                            "Possible circular reference in formula.")
    
    expr = formula[1:]
    pattern = r'([A-Z]+)(\d+)'
    
    def replace_ref(match):
        col_str, row_num = match.group(1), int(match.group(2))
        col_num = col_letter_to_num(col_str)
        
        cell_val = sheet.cell(row=row_num, column=col_num).value
        if cell_val is None:
            return '0'
        
        if isinstance(cell_val, str) and cell_val.startswith('='):
            cell_val = evaluate_formula(cell_val, sheet, max_recursion - 1)
        
        try:
            return str(float(cell_val))
        except (ValueError, TypeError):
            return '0'
    
    expr = re.sub(pattern, replace_ref, expr)
    
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        return result
    except Exception:
        return 0


def detect_blocks(sheet, max_row: int, cols_to_check: int = 8) -> List[List[int]]:
    """Detect blank-separated blocks in the sheet."""
    blocks = []
    current_block = []
    
    for row_idx in range(1, max_row + 1):
        is_blank = True
        for col in range(1, cols_to_check + 1):
            if sheet.cell(row=row_idx, column=col).value is not None:
                is_blank = False
                break
        
        if is_blank:
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(row_idx)
    
    if current_block:
        blocks.append(current_block)
    
    return blocks


def extract_row_data(sheet, row_idx: int, num_cols: int) -> List[Any]:
    """Extract all cell values from a row."""
    return [sheet.cell(row=row_idx, column=col).value 
            for col in range(1, num_cols + 1)]


class BlockTransformer(ABC):
    """Abstract base class for block transformations."""
    
    @abstractmethod
    def transform(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Transform a list of row dictionaries.
        
        Args:
            rows: List of {'orig_idx': int, 'values': List[Any], ...}
        
        Returns:
            Transformed list of rows
        """
        pass


class BlockSorter(BlockTransformer):
    """Sort rows within a block by a key column, descending, stable."""
    
    def __init__(self, sort_col: int, descending: bool = True):
        self.sort_col = sort_col
        self.descending = descending
    
    def transform(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Store sort value for each row
        for row in rows:
            values = row['values']
            row['sort_val'] = values[self.sort_col - 1] if self.sort_col <= len(values) else 0
        
        # Stable sort: use negative key for descending
        if self.descending:
            return sorted(rows, key=lambda r: -r['sort_val'])
        else:
            return sorted(rows, key=lambda r: r['sort_val'])


class BlockFilter(BlockTransformer):
    """Filter rows within a block based on a predicate."""
    
    def __init__(self, predicate: Callable[[List[Any]], bool]):
        self.predicate = predicate
    
    def transform(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [row for row in rows if self.predicate(row['values'])]


def process_block(sheet, block: List[int], transformer: BlockTransformer,
                  eval_cols: List[int], num_cols: int) -> List[Dict[str, Any]]:
    """
    Process a block: extract data, evaluate formulas, apply transformation.
    """
    rows = []
    
    for row_idx in block:
        values = extract_row_data(sheet, row_idx, num_cols)
        
        # Evaluate specified columns
        for col in eval_cols:
            if col <= len(values):
                values[col - 1] = evaluate_formula(values[col - 1], sheet)
        
        rows.append({
            'orig_idx': row_idx,
            'values': values
        })
    
    # Apply transformation
    return transformer.transform(rows)


def write_blocks(sheet, blocks_data: List[List[Dict[str, Any]]], 
                 start_row: int = 1, max_row: int = 85, num_cols: int = 8) -> int:
    """
    Write transformed blocks back to sheet with blank separators.
    
    Clears any remaining cells in the declared answer range below the written
    extent to prevent stale data from compaction transforms (filter, extract).
    """
    output_row = start_row
    
    for block_idx, block in enumerate(blocks_data):
        for row_data in block:
            for col_idx, value in enumerate(row_data['values']):
                sheet.cell(row=output_row, column=col_idx + 1).value = value
            output_row += 1
        
        # Add blank separator between blocks
        if block_idx < len(blocks_data) - 1:
            # Explicitly clear the separator row to prevent stale data
            for c in range(1, num_cols + 1):
                sheet.cell(row=output_row, column=c).value = None
            output_row += 1
    
    last_written = output_row - 1
    
    # Clear tail: compaction safety for filter/extract transforms
    # Stale data below written extent must be cleared
    for r in range(last_written + 1, max_row + 1):
        for c in range(1, num_cols + 1):
            sheet.cell(row=r, column=c).value = None
    
    return last_written


def transform_workbook(input_path: str, output_path: str,
                       transformer: BlockTransformer,
                       sheet_name: str = 'Sheet1',
                       max_row: int = 85,
                       eval_cols: List[int] = None,
                       num_cols: int = 8) -> None:
    """
    Transform a workbook using the given transformer.
    
    Core pipeline: detect → extract → evaluate → transform → write → preserve
    """
    if eval_cols is None:
        eval_cols = []
    
    # Load preserving formulas and structure
    wb = openpyxl.load_workbook(input_path)
    sheet = wb[sheet_name]
    
    # Detect blocks
    blocks = detect_blocks(sheet, max_row, num_cols)
    
    # Process each block
    blocks_data = []
    for block in blocks:
        rows = process_block(sheet, block, transformer, eval_cols, num_cols)
        blocks_data.append(rows)
    
    # Write back (with tail clearing for compaction safety)
    write_blocks(sheet, blocks_data, start_row=1, max_row=max_row, num_cols=num_cols)
    
    # Save (preserves styles, merges, panes, out-of-range data)
    wb.save(output_path)


def cells_equal(val1: Any, val2: Any) -> bool:
    """Compare two cell values, handling float comparison with tolerance."""
    if val1 is None and val2 is None:
        return True
    if val1 is None or val2 is None:
        return False
    
    try:
        f1, f2 = float(val1), float(val2)
        return math.isclose(f1, f2, rel_tol=1e-9, abs_tol=1e-9)
    except (ValueError, TypeError):
        pass
    
    return str(val1) == str(val2)


def verify_output_full(input_path: str, output_path: str,
                       transformer: BlockTransformer,
                       max_row: int = 85, eval_cols: List[int] = None, 
                       num_cols: int = 8) -> Tuple[bool, List[str]]:
    """
    Generic verification: recompute expected from input using same transformer,
    compare cell-by-cell including cleared tail.
    """
    if eval_cols is None:
        eval_cols = []
    
    errors = []
    
    # Recompute expected from input
    wb_in = openpyxl.load_workbook(input_path)
    sheet_in = wb_in['Sheet1']
    
    blocks = detect_blocks(sheet_in, max_row, num_cols)
    
    expected = []
    for block in blocks:
        rows = []
        for row_idx in block:
            values = extract_row_data(sheet_in, row_idx, num_cols)
            for col in eval_cols:
                if col <= len(values):
                    values[col - 1] = evaluate_formula(values[col - 1], sheet_in)
            rows.append({'values': values, 'orig_idx': row_idx})
        
        transformed = transformer.transform(rows)
        expected.extend(transformed)
        expected.append(None)  # blank separator
    
    if expected and expected[-1] is None:
        expected.pop()
    
    wb_in.close()
    
    # Compare with actual output
    wb_out = openpyxl.load_workbook(output_path)
    sheet_out = wb_out['Sheet1']
    
    for row_idx in range(1, max_row + 1):
        exp = expected[row_idx - 1] if row_idx <= len(expected) else None
        is_blank = all(sheet_out.cell(row=row_idx, column=c).value is None 
                      for c in range(1, num_cols + 1))
        
        if exp is None and not is_blank:
            errors.append(f"Row {row_idx}: expected blank, found data")
        elif exp is not None and is_blank:
            errors.append(f"Row {row_idx}: expected data, found blank")
        elif exp is not None:
            for col_idx in range(num_cols):
                actual = sheet_out.cell(row=row_idx, column=col_idx + 1).value
                expected_val = exp['values'][col_idx]
                if not cells_equal(actual, expected_val):
                    errors.append(f"Row {row_idx}, col {col_idx + 1}: "
                                f"expected {expected_val!r}, got {actual!r}")
    
    wb_out.close()
    return len(errors) == 0, errors


def verify_sort_output(input_path: str, output_path: str,
                       max_row: int = 85, sort_col: int = 4,
                       eval_cols: List[int] = None, num_cols: int = 8) -> Tuple[bool, List[str]]:
    """Verify sorted output by recomputing expected from input."""
    transformer = BlockSorter(sort_col, descending=True)
    return verify_output_full(input_path, output_path, transformer,
                             max_row, eval_cols, num_cols)


def verify_filter_output(input_path: str, output_path: str,
                         predicate: Callable[[List[Any]], bool],
                         max_row: int = 85, eval_cols: List[int] = None, 
                         num_cols: int = 8) -> Tuple[bool, List[str]]:
    """Verify filtered output by recomputing expected from input."""
    transformer = BlockFilter(predicate)
    return verify_output_full(input_path, output_path, transformer,
                             max_row, eval_cols, num_cols)


def test_negative_control(input_path: str, output_path: str,
                          transformer: BlockTransformer,
                          max_row: int = 85, eval_cols: List[int] = None,
                          num_cols: int = 8) -> bool:
    """
    Run verification with a negative control (corrupted output) to ensure
    the verifier can actually detect errors.
    """
    import shutil
    import tempfile
    import os
    
    # Create a corrupted copy
    temp_dir = tempfile.mkdtemp()
    corrupted_path = os.path.join(temp_dir, 'corrupted.xlsx')
    shutil.copy(output_path, corrupted_path)
    
    wb = openpyxl.load_workbook(corrupted_path)
    sheet = wb['Sheet1']
    
    # Corrupt a cell: change row 1, col 1
    sheet.cell(row=1, column=1).value = "CORRUPTED"
    wb.save(corrupted_path)
    wb.close()
    
    # Verify corrupted file fails
    passed, errors = verify_output_full(input_path, corrupted_path, 
                                       transformer, max_row, eval_cols, num_cols)
    
    # Cleanup
    os.remove(corrupted_path)
    os.rmdir(temp_dir)
    
    if passed:
        print("NEGATIVE CONTROL FAILED: verifier did not catch corrupted cell", 
              file=sys.stderr)
        return False
    
    print("NEGATIVE CONTROL PASSED: verifier correctly detects errors")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Transform Excel workbook with structural operations')
    parser.add_argument('input', help='Input Excel file')
    parser.add_argument('output', help='Output Excel file')
    parser.add_argument('--transform', default='block-sort',
                       choices=['block-sort', 'block-filter'],
                       help='Transformation type')
    parser.add_argument('--sheet', default='Sheet1', help='Sheet name')
    parser.add_argument('--max-row', type=int, default=85, help='Max row to process')
    parser.add_argument('--num-cols', type=int, default=8,
                       help='Number of columns in answer range')
    parser.add_argument('--sort-col', type=int, default=4,
                       help='Sort column for block-sort (1=A)')
    parser.add_argument('--descending', action='store_true', default=True,
                       help='Sort descending (default)')
    parser.add_argument('--ascending', action='store_true',
                       help='Sort ascending')
    parser.add_argument('--eval-cols', type=int, nargs='+', default=[4, 5, 6],
                       help='Columns to evaluate')
    parser.add_argument('--verify', action='store_true', help='Run verification')
    parser.add_argument('--test-negative-control', action='store_true',
                       help='Test verifier with corrupted output')
    
    args = parser.parse_args()
    
    # Create transformer
    if args.transform == 'block-sort':
        descending = not args.ascending
        transformer = BlockSorter(args.sort_col, descending)
    elif args.transform == 'block-filter':
        # Example: filter positive values in sort column
        col = args.sort_col
        transformer = BlockFilter(lambda values: 
            values[col - 1] > 0 if col <= len(values) and values[col - 1] is not None else False)
    else:
        raise ValueError(f"Unknown transform: {args.transform}")
    
    # Transform
    transform_workbook(args.input, args.output, transformer,
                      args.sheet, args.max_row, args.eval_cols, args.num_cols)
    
    print(f"Transformed with {args.transform}")
    
    # Verification and negative control
    if args.verify or args.test_negative_control:
        if args.test_negative_control:
            if not test_negative_control(args.input, args.output, transformer,
                                        args.max_row, args.eval_cols, args.num_cols):
                return 1
        
        if args.verify:
            if args.transform == 'block-sort':
                passed, errors = verify_sort_output(args.input, args.output,
                                                  args.max_row, args.sort_col,
                                                  args.eval_cols, args.num_cols)
            elif args.transform == 'block-filter':
                col = args.sort_col
                predicate = lambda values: values[col - 1] > 0 if col <= len(values) and values[col - 1] is not None else False
                passed, errors = verify_filter_output(args.input, args.output, predicate,
                                                     args.max_row, args.eval_cols, args.num_cols)
            else:
                passed, errors = verify_output_full(args.input, args.output, transformer,
                                                   args.max_row, args.eval_cols, args.num_cols)
            
            if passed:
                print("Verification PASSED")
            else:
                print("Verification FAILED:", file=sys.stderr)
                for e in errors[:10]:
                    print(f"  {e}", file=sys.stderr)
                return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
