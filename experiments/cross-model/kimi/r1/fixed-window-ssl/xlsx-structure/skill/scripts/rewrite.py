"""
Value-in-place rewriting for xlsx-structure transformations.

Critical rule: Only assign cell.value, never move/copy cells.
This preserves styles, row heights, column widths, etc.
"""


def rewrite_block(ws, block_rows, sorted_values, num_cols=8):
    """
    Write sorted values back to original block positions.
    
    Args:
        ws: openpyxl worksheet
        block_rows: List of row numbers to write to (in order)
        sorted_values: List of row tuples, where sorted_values[i] goes to block_rows[i]
        num_cols: Number of columns to write (default 8 for A-H)
    
    Note:
        Assigns to cell.value, which preserves existing cell style.
        Does NOT modify blank separator rows.
    """
    for target_row, new_values in zip(block_rows, sorted_values):
        for col_idx, value in enumerate(new_values[:num_cols], 1):
            ws.cell(row=target_row, column=col_idx).value = value


def sort_block_by_key(ws, block_rows, key_func, value_func=None, reverse=True, num_cols=8):
    """
    Sort a block by an evaluated key function.
    
    Args:
        ws: openpyxl worksheet
        block_rows: List of row numbers in the block
        key_func: Function(row_number) -> sortable value for sorting
        value_func: Function(row_number, col_index) -> value for extraction.
                   If None, reads raw cell values (may include formula strings!)
        reverse: True for descending, False for ascending
        num_cols: Number of columns to preserve (A-H = 8)
    
    Returns:
        List of sorted value tuples
    
    Example:
        from xlsx_eval import evaluate_cell
        
        sorted_values = sort_block_by_key(
            ws, block_rows, 
            key_func=lambda r: evaluate_cell(ws, r, 4),  # Sort by column D
            value_func=lambda r, c: evaluate_cell(ws, r, c) if c in [4,5,6] 
                                    else ws.cell(row=r, column=c).value,
            reverse=True
        )
    """
    rows_with_key = []
    for row in block_rows:
        key_value = key_func(row)
        # Extract values using value_func if provided, else raw read
        if value_func:
            row_values = tuple(value_func(row, c) for c in range(1, num_cols + 1))
        else:
            row_values = tuple(ws.cell(row=row, column=c).value for c in range(1, num_cols + 1))
        rows_with_key.append((key_value, row_values))
    
    # Python's sort is stable - ties preserve original relative order
    rows_with_key.sort(key=lambda x: x[0], reverse=reverse)
    return [r[1] for r in rows_with_key]


def filter_block(ws, block_rows, predicate, value_func=None, num_cols=8):
    """
    Filter rows in a block based on a predicate.
    
    Args:
        ws: openpyxl worksheet
        block_rows: List of row numbers
        predicate: Function(row_number) -> bool, True to keep
        value_func: Function(row_number, col_index) -> value for extraction.
                   If None, reads raw cell values.
        num_cols: Number of columns to preserve
    
    Returns:
        List of (row_values) for rows that pass the predicate
    """
    result = []
    for row in block_rows:
        if predicate(row):
            if value_func:
                row_values = tuple(value_func(row, c) for c in range(1, num_cols + 1))
            else:
                row_values = tuple(ws.cell(row=row, column=c).value for c in range(1, num_cols + 1))
            result.append(row_values)
    return result
