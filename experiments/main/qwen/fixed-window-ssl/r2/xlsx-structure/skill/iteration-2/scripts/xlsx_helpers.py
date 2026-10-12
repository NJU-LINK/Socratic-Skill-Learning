"""
Reusable helpers for xlsx structural transformations.

Usage:
    from xlsx_helpers import DualWorkbook, detect_blocks, capture_row, write_row

Provides the dual-workbook pattern, block detection, and style-preserving
row operations that are common across all xlsx-structure tasks.
"""

import openpyxl
from copy import copy
import re


class DualWorkbook:
    """Load an xlsx file twice: once for evaluated values, once for styles/writing.
    
    Attributes:
        wb_data: openpyxl workbook with data_only=True (evaluated values)
        wb: openpyxl workbook with formulas and styles (for writing)
    """
    
    def __init__(self, path):
        self.path = path
        self.wb_data = openpyxl.load_workbook(path, data_only=True)
        self.wb = openpyxl.load_workbook(path)
    
    def get_value(self, sheet_name, row, col):
        """Get evaluated value from data_only workbook."""
        return self.wb_data[sheet_name].cell(row=row, column=col).value
    
    def get_style_cell(self, sheet_name, row, col):
        """Get cell with style info from normal workbook."""
        return self.wb[sheet_name].cell(row=row, column=col)
    
    def get_write_cell(self, sheet_name, row, col):
        """Get cell for writing from normal workbook."""
        return self.wb[sheet_name].cell(row=row, column=col)
    
    def save(self, path):
        """Save the writable workbook."""
        self.wb.save(path)


def detect_blocks(ws, min_row, max_row, min_col, max_col, data_ws=None):
    """Detect blocks of non-empty rows separated by blank rows.
    
    A row is blank if ALL cells in [min_col, max_col] are None or empty string.
    Uses dual-source reading: checks both data_ws (evaluated values) and ws
    (formulas/styles) to avoid false blanks when formulas have no cached values.
    
    Args:
        ws: normal workbook worksheet (for formulas/styles)
        min_row, max_row: row range to scan (inclusive)
        min_col, max_col: column range for blank detection (inclusive)
        data_ws: optional separate worksheet for value reading (data_only)
    
    Returns:
        List of lists of row indices. Each inner list is one block.
    """
    blocks = []
    current_block = []
    
    for row_idx in range(min_row, max_row + 1):
        is_blank = True
        for c in range(min_col, max_col + 1):
            # Check data_ws first (evaluated values)
            if data_ws:
                data_val = data_ws.cell(row=row_idx, column=c).value
                if data_val is not None and data_val != '':
                    is_blank = False
                    break
            # Fall back to normal workbook (formulas/styles)
            norm_val = ws.cell(row=row_idx, column=c).value
            if norm_val is not None and norm_val != '':
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


def capture_cell_style(cell):
    """Capture all style attributes of a cell."""
    return {
        'font': copy(cell.font),
        'fill': copy(cell.fill),
        'border': copy(cell.border),
        'alignment': copy(cell.alignment),
        'number_format': cell.number_format,
        'protection': copy(cell.protection),
    }


def apply_cell_style(cell, style):
    """Apply captured style dict to a cell."""
    cell.font = style['font']
    cell.fill = style['fill']
    cell.border = style['border']
    cell.alignment = style['alignment']
    cell.number_format = style['number_format']
    cell.protection = style['protection']


def resolve_row_values(raw_values):
    """Resolve all text formulas in a row to numeric values.
    
    Handles chains of text formulas: if F1='=D1+E1' and D1='=B1+C1',
    resolving F1 recursively resolves D1 first.
    
    Also handles real formulas returned as strings by data_only when the
    workbook was never opened in Excel (cached value is None).
    
    Args:
        raw_values: dict mapping column index (1-based) to raw cell value
    
    Returns:
        dict mapping column index to resolved numeric value
    """
    resolved = {}
    resolving = set()  # cycle detection
    
    def resolve(col_idx):
        if col_idx in resolved:
            return resolved[col_idx]
        if col_idx in resolving:
            return 0  # circular reference guard
        
        val = raw_values.get(col_idx)
        resolving.add(col_idx)
        
        if isinstance(val, str) and val.startswith('='):
            # Text formula (or unevaluated formula) — compute it
            expr = val[1:]  # strip '='
            
            def replace_ref(match):
                col_letter = match.group(1)
                ref_col = ord(col_letter.upper()) - ord('A') + 1
                return str(resolve(ref_col))
            
            expr = re.sub(r'([A-Za-z]+)\d+', replace_ref, expr)
            
            try:
                result = eval(expr)  # simple arithmetic: +, -, *, /
            except Exception:
                result = val  # keep original string if eval fails
            
            resolved[col_idx] = result
        else:
            resolved[col_idx] = val if val is not None else 0
        
        resolving.discard(col_idx)
        return resolved[col_idx]
    
    for col_idx in list(raw_values.keys()):
        resolve(col_idx)
    
    return resolved


def capture_row(ws, data_ws, row_idx, min_col, max_col):
    """Capture complete row data (evaluated values + styles).
    
    Uses dual-source reading to handle all formula cases:
    1. Real formulas with cached values: uses numeric from data_ws
    2. Real formulas without cached values: uses formula string from ws, resolves it
    3. Text formulas (strings stored as text): resolves them
    
    Args:
        ws: normal workbook worksheet (for styles and formula strings)
        data_ws: data_only workbook worksheet (for evaluated values)
        row_idx: row number to capture
        min_col, max_col: column range (inclusive)
    
    Returns:
        List of cell dicts, one per column in [min_col, max_col].
    """
    # First pass: read raw values from both sources
    raw_values = {}
    for col_idx in range(min_col, max_col + 1):
        data_val = data_ws.cell(row=row_idx, column=col_idx).value
        norm_val = ws.cell(row=row_idx, column=col_idx).value
        
        # Decision logic:
        # - If data_val is numeric (not None, not formula string), use it
        # - If data_val is None and norm_val is a formula string, use norm_val
        # - Otherwise use data_val (may be None, string, or number)
        if data_val is not None and not (isinstance(data_val, str) and data_val.startswith('=')):
            raw_values[col_idx] = data_val
        elif isinstance(norm_val, str) and norm_val.startswith('='):
            # data_val is None or unevaluated, but we have a formula string
            raw_values[col_idx] = norm_val
        else:
            raw_values[col_idx] = data_val if data_val is not None else norm_val
    
    # Resolve any text formulas to numeric values
    resolved = resolve_row_values(raw_values)
    
    # Second pass: build cell data with resolved values + styles
    cells = []
    for col_idx in range(min_col, max_col + 1):
        src_cell = ws.cell(row=row_idx, column=col_idx)
        cells.append({
            'value': resolved[col_idx],
            **capture_cell_style(src_cell)
        })
    return cells


def write_row(ws, row_idx, cells, min_col=1):
    """Write captured row data to a target row.
    
    Args:
        ws: worksheet to write to
        row_idx: target row number
        cells: list of cell dicts from capture_row
        min_col: starting column for writing (default 1)
    """
    for col_offset, cell_data in enumerate(cells):
        dst = ws.cell(row=row_idx, column=min_col + col_offset)
        dst.value = cell_data['value']
        apply_cell_style(dst, cell_data)


def sort_block_in_place(ws, data_ws, block_rows, min_col, max_col, key_col, reverse=True):
    """Sort a block of rows by a key column, preserving styles.
    
    Args:
        ws: normal workbook worksheet
        data_ws: data_only workbook worksheet
        block_rows: list of row indices in the block
        min_col, max_col: column range
        key_col: column index to sort by (1-based)
        reverse: True for descending, False for ascending
    
    Returns:
        None (modifies ws in place)
    """
    # Capture all rows
    row_data = []
    for row_idx in block_rows:
        cells = capture_row(ws, data_ws, row_idx, min_col, max_col)
        key_value = cells[key_col - min_col]['value']
        # Handle None values: treat as 0 for numeric sort
        if key_value is None:
            key_value = 0
        row_data.append((key_value, cells))
    
    # Stable sort by key
    row_data.sort(key=lambda rd: rd[0], reverse=reverse)
    
    # Write back
    for write_pos, (key_val, cells) in enumerate(row_data):
        target_row = block_rows[write_pos]
        write_row(ws, target_row, cells, min_col)


def evaluate_formula_manual(formula_str, row_values):
    """Manually evaluate a single row-local formula like =B1+C1.
    
    For evaluating an entire row of potentially chained text formulas,
    prefer resolve_row_values() which handles dependencies automatically.
    
    Args:
        formula_str: formula string (e.g., '=B1+C1')
        row_values: dict mapping column index (1-based) to numeric value
    
    Returns:
        Evaluated numeric result, or original value if not a formula.
    """
    if not isinstance(formula_str, str) or not formula_str.startswith('='):
        return formula_str
    
    expr = formula_str[1:]  # strip '='
    
    def replace_ref(match):
        col_letter = match.group(1)
        col_idx = ord(col_letter.upper()) - ord('A') + 1
        val = row_values.get(col_idx, 0)
        if val is None:
            val = 0
        return str(val)
    
    expr = re.sub(r'([A-Za-z]+)\d+', replace_ref, expr)
    
    try:
        return eval(expr)  # Safe for simple arithmetic: +, -, *, /
    except Exception:
        return formula_str
