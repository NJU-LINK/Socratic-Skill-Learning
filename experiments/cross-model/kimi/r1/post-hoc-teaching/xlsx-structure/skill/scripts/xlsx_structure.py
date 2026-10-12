"""
Core machinery for xlsx-structure transformations.

Provides:
- Robust formula evaluation with cycle detection and proper cell reference parsing
- Block detection in worksheet data
- Style preservation utilities
- Verification harness
- Helper functions for filtering, compaction, and append operations
"""

import re
from copy import copy
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter


# Regex for cell references with word-boundary guards
# Handles: A1, $A$1, AA123, but not LOG10 (function name) or "A1" (string literal)
CELL_REF = re.compile(r"""
    (?<![A-Za-z0-9_$])           # not inside a longer identifier
    \$?([A-Z]{1,3})\$?(\d{1,7})  # optional $ anchors, col + row
    (?![A-Za-z0-9_(])            # not a function name or identifier continuation
"", re.VERBOSE)


def make_evaluator(cell_values):
    """Create a formula evaluator with memoization and cycle detection.
    
    Args:
        cell_values: Dict mapping 'A1' notation to raw cell values
    
    Returns:
        Function eval_cell(addr) -> float
    """
    memo = {}
    in_progress = set()
    
    def to_number(v):
        """Convert a value to float, with sensible defaults."""
        if v is None:
            return 0.0
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.strip())
            except ValueError:
                return 0.0  # genuine text
        return 0.0
    
    def eval_cell(addr):
        """Evaluate a cell to a numeric value."""
        if addr in memo:
            return memo[addr]
        
        v = cell_values.get(addr)
        
        if isinstance(v, str) and v.startswith('='):
            # Formula - evaluate recursively
            if addr in in_progress:
                raise ValueError(f"circular reference at {addr}")
            
            in_progress.add(addr)
            expr = v[1:]
            
            # Replace cell references with their evaluated values (as repr for safety)
            def replace_ref(m):
                ref_addr = f"{m.group(1)}{m.group(2)}"
                try:
                    val = eval_cell(ref_addr)
                    return repr(val)
                except ValueError as e:
                    raise ValueError(f"in formula at {addr}: {e}")
            
            expr = CELL_REF.sub(replace_ref, expr)
            
            try:
                result = float(eval(expr, {"__builtins__": {}}, {}))
            except Exception as e:
                raise ValueError(f"cannot evaluate {v!r} at {addr} (expanded: {expr!r}): {e}")
            
            in_progress.discard(addr)
        else:
            result = to_number(v)
        
        memo[addr] = result
        return result
    
    return eval_cell


def capture_all_cell_values(ws):
    """Capture all cell values in the worksheet into a dict keyed by 'A1' notation."""
    cell_values = {}
    for row in range(1, ws.max_row + 1):
        for col in range(1, ws.max_column + 1):
            col_letter = get_column_letter(col)
            cell_values[f"{col_letter}{row}"] = ws.cell(row=row, column=col).value
    return cell_values


def is_blank_row(ws, row_num, max_col):
    """Check if all cells in a row up to max_col are None."""
    for col in range(1, max_col + 1):
        if ws.cell(row=row_num, column=col).value is not None:
            return False
    return True


def detect_blocks(ws, min_row, max_row, max_col):
    """Detect contiguous blocks of data separated by blank rows.
    
    Returns list of lists, where each inner list contains row numbers in a block.
    """
    blocks = []
    current_block = []
    
    for row_num in range(min_row, max_row + 1):
        if is_blank_row(ws, row_num, max_col):
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(row_num)
    
    if current_block:
        blocks.append(current_block)
    
    return blocks


def fill_signature(cell):
    """Get a signature for cell fill that handles rgb, theme, and indexed colors.
    
    Args:
        cell: openpyxl Cell object
    
    Returns:
        Tuple like ('rgb', 'FFFF0000') or ('theme', 6, 0.0) or ('indexed', 5)
        or None if no fill/transparent.
    """
    f = cell.fill
    if f is None or f.patternType is None:
        return None
    
    c = f.start_color
    if c is None:
        return None
    
    if c.type == 'rgb' and c.rgb and c.rgb != '00000000':
        return ('rgb', c.rgb)
    if c.type == 'theme':
        return ('theme', c.theme, c.tint)
    if c.type == 'indexed':
        return ('indexed', c.indexed)
    
    return None


def enumerate_fill_signatures(ws, rows, col):
    """Enumerate all distinct fill signatures in a column for a set of rows.
    
    Use this first when a task mentions "highlighted rows" or "fill color" - 
    print the distinct signatures, then match the instruction description to 
    what actually exists in the workbook.
    
    Args:
        ws: Worksheet
        rows: List of row numbers to check
        col: Column index (1-based)
    
    Returns:
        Dict mapping signature to count
    """
    signatures = {}
    for row_num in rows:
        cell = ws.cell(row=row_num, column=col)
        sig = fill_signature(cell)
        if sig:
            signatures[sig] = signatures.get(sig, 0) + 1
    return signatures


def select_rows_by_fill_signature(ws, rows, col, target_signature):
    """Select rows where the cell in column col has the target fill signature.
    
    Args:
        ws: Worksheet
        rows: List of row numbers to check
        col: Column index (1-based)
        target_signature: Signature tuple from fill_signature()
    
    Returns:
        List of row numbers matching the signature
    """
    selected = []
    for row_num in rows:
        cell = ws.cell(row=row_num, column=col)
        if fill_signature(cell) == target_signature:
            selected.append(row_num)
    return selected


def capture_cell_style(cell):
    """Capture all style attributes from a cell."""
    if not cell.has_style:
        return None
    return {
        'font': copy(cell.font),
        'border': copy(cell.border),
        'fill': copy(cell.fill),
        'number_format': cell.number_format,
        'protection': copy(cell.protection),
        'alignment': copy(cell.alignment)
    }


def apply_cell_style(cell, style):
    """Apply captured style to a cell."""
    if style is None:
        return
    cell.font = style['font']
    cell.border = style['border']
    cell.fill = style['fill']
    cell.number_format = style['number_format']
    cell.protection = style['protection']
    cell.alignment = style['alignment']


def write_value(cell, value, eval_cell=None, addr=None):
    """Write a value to a cell, evaluating formulas if needed.
    
    This is the universal choke point for formula evaluation. Use it in all
    transformation helpers to ensure formulas are never written as strings.
    
    Args:
        cell: Target cell
        value: Value to write (may be formula string)
        eval_cell: Formula evaluator function (optional)
        addr: Cell address for evaluation (e.g., 'A1')
    """
    if isinstance(value, str) and value.startswith('=') and eval_cell is not None and addr is not None:
        cell.value = eval_cell(addr)
    else:
        cell.value = value


def compact_rows(ws, min_row, max_row, max_col, eval_cell=None):
    """Remove blank rows within a region, shifting data up.
    
    Args:
        ws: Worksheet to modify
        min_row: First row of region
        max_row: Last row of region
        max_col: Last column to check for blanks
        eval_cell: Optional formula evaluator for evaluating formulas
    
    Returns:
        New last row number after compaction
    """
    write_row = min_row
    for read_row in range(min_row, max_row + 1):
        if not is_blank_row(ws, read_row, max_col):
            # Copy row data from read_row to write_row
            if read_row != write_row:
                for col in range(1, max_col + 1):
                    source = ws.cell(row=read_row, column=col)
                    target = ws.cell(row=write_row, column=col)
                    addr = f"{get_column_letter(col)}{read_row}"
                    write_value(target, source.value, eval_cell, addr)
            write_row += 1
    
    # Clear remaining rows
    for row in range(write_row, max_row + 1):
        for col in range(1, max_col + 1):
            ws.cell(row=row, column=col).value = None
    
    return write_row - 1


def align_by_headers(source_ws, source_rows, target_ws, target_start_row, eval_cell=None):
    """Append data aligning columns by header names.
    
    Assumes row 1 contains headers in both source and target.
    
    Args:
        source_ws: Source worksheet
        source_rows: List of row numbers to copy (excluding header row)
        target_ws: Target worksheet
        target_start_row: Row to start writing
        eval_cell: Optional formula evaluator
    
    Returns:
        Next available row after writing
    """
    # Build header -> column index map for target
    target_headers = {}
    for col in range(1, target_ws.max_column + 1):
        header = target_ws.cell(row=1, column=col).value
        if header:
            target_headers[header] = col
    
    write_row = target_start_row
    for src_row in source_rows:
        for src_col in range(1, source_ws.max_column + 1):
            header = source_ws.cell(row=1, column=src_col).value
            if header in target_headers:
                tgt_col = target_headers[header]
                value = source_ws.cell(row=src_row, column=src_col).value
                addr = f"{get_column_letter(src_col)}{src_row}"
                write_value(
                    target_ws.cell(row=write_row, column=tgt_col),
                    value, eval_cell, addr
                )
        write_row += 1
    
    return write_row


def filter_rows_by_predicate(ws, rows, predicate):
    """Filter rows based on a predicate function.
    
    Args:
        ws: Worksheet
        rows: List of row numbers to consider
        predicate: Function (row_num, ws) -> bool
    
    Returns:
        List of row numbers that satisfy the predicate
    """
    return [r for r in rows if predicate(r, ws)]


def filter_rows_by_text_predicate(ws, rows, col, pattern, exclude=False):
    """Filter rows by regex text pattern matching.
    
    Args:
        ws: Worksheet
        rows: List of row numbers to check
        col: Column index (1-based) to match against
        pattern: Regex pattern string
        exclude: If True, return rows that DON'T match
    
    Returns:
        List of row numbers matching (or not matching) the pattern
    """
    import re
    regex = re.compile(pattern)
    selected = []
    for row_num in rows:
        cell_value = ws.cell(row=row_num, column=col).value
        text = str(cell_value) if cell_value is not None else ""
        matches = bool(regex.search(text))
        if (matches and not exclude) or (not matches and exclude):
            selected.append(row_num)
    return selected


def transpose_range(ws, min_row, max_row, min_col, max_col, 
                    target_ws=None, target_start_row=1, target_start_col=1,
                    eval_cell=None):
    """Transpose a range (rows become columns, columns become rows).
    
    **CRITICAL**: Always captures ALL source data before ANY writes to avoid
    aliasing bugs when target overlaps source.
    
    Args:
        ws: Source worksheet
        min_row, max_row, min_col, max_col: Source range
        target_ws: Target worksheet (defaults to source)
        target_start_row: Starting row for output
        target_start_col: Starting column for output
        eval_cell: Formula evaluator (required for formula cells)
    
    Returns:
        (output_rows, output_cols) dimensions of transposed data
    """
    if target_ws is None:
        target_ws = ws
    
    # Source dimensions
    source_rows = max_row - min_row + 1
    source_cols = max_col - min_col + 1
    
    # CAPTURE PHASE: Read ALL source data before ANY writes
    # This prevents aliasing when target overlaps source
    matrix = []
    addr_matrix = []  # Keep track of source addresses for formula evaluation
    for i in range(source_rows):
        row_data = []
        addr_row = []
        for j in range(source_cols):
            src_row = min_row + i
            src_col = min_col + j
            row_data.append(ws.cell(row=src_row, column=src_col).value)
            addr_row.append(f"{get_column_letter(src_col)}{src_row}")
        matrix.append(row_data)
        addr_matrix.append(addr_row)
    
    # WRITE PHASE: Write to target (may be same as source)
    for i in range(source_rows):
        for j in range(source_cols):
            dst_row = target_start_row + j
            dst_col = target_start_col + i
            
            value = matrix[i][j]
            src_addr = addr_matrix[i][j]
            
            # Use write_value to ensure formula evaluation
            write_value(
                target_ws.cell(row=dst_row, column=dst_col),
                value, eval_cell, src_addr
            )
    
    return (source_cols, source_rows)  # Output dimensions (rows, cols)


def reconcile_sparse_records(id_list_ws, id_col, data_ws, data_col, 
                              output_ws, output_row_start,
                              eval_cell=None, strict_types=False):
    """Reconcile ordered ID list with sparse data table.
    
    Matches IDs from id_list_ws with data in data_ws, writing aligned
    records to output_ws.
    
    **WARNING**: Reports unmatched IDs and duplicate handling for visibility.
    By default uses string normalization for ID matching (handles '1001' vs 1001).
    
    Args:
        id_list_ws: Worksheet containing ordered ID list
        id_col: Column in id_list_ws containing IDs
        data_ws: Worksheet containing sparse data
        data_col: Column in data_ws containing IDs to match
        output_ws: Output worksheet
        output_row_start: Starting row for output
        eval_cell: Formula evaluator (optional)
        strict_types: If True, require exact type match; if False (default), 
                     normalize IDs to strings for matching
    
    Returns:
        (next_row, report) where report is a dict with:
            - 'written': count of records written
            - 'unmatched': list of IDs not found in data
            - 'duplicates_in_data': list of IDs appearing multiple times in data
            - 'duplicates_in_list': list of IDs appearing multiple times in list
    """
    # Normalize function for ID comparison
    def normalize_id(v):
        if v is None:
            return None
        if strict_types:
            return v
        return str(v).strip()
    
    # Build lookup from data_ws: normalized_ID -> (original_ID, row_data)
    # Track duplicates
    data_lookup = {}
    duplicates_in_data = []
    
    for row in range(1, data_ws.max_row + 1):
        id_val = data_ws.cell(row=row, column=data_col).value
        if id_val is not None:
            norm_id = normalize_id(id_val)
            
            # Capture full row data with addresses for formula evaluation
            row_data = []
            addr_row = []
            for col in range(1, data_ws.max_column + 1):
                row_data.append(data_ws.cell(row=row, column=col).value)
                addr_row.append(f"{get_column_letter(col)}{row}")
            
            if norm_id in data_lookup:
                duplicates_in_data.append(id_val)
            else:
                data_lookup[norm_id] = (id_val, row_data, addr_row)
    
    # Collect IDs from list, tracking duplicates
    ids_from_list = []
    duplicates_in_list = []
    
    for row in range(1, id_list_ws.max_row + 1):
        id_val = id_list_ws.cell(row=row, column=id_col).value
        if id_val is not None:
            norm_id = normalize_id(id_val)
            if norm_id in [normalize_id(x) for x in ids_from_list]:
                duplicates_in_list.append(id_val)
            ids_from_list.append(id_val)
    
    # Walk through ordered ID list and output aligned data
    output_row = output_row_start
    written = 0
    unmatched = []
    
    for id_val in ids_from_list:
        norm_id = normalize_id(id_val)
        
        if norm_id in data_lookup:
            orig_id, row_data, addr_row = data_lookup[norm_id]
            for col_idx, (value, src_addr) in enumerate(zip(row_data, addr_row), 1):
                # Use write_value for formula evaluation
                write_value(
                    output_ws.cell(row=output_row, column=col_idx),
                    value, eval_cell, src_addr
                )
            output_row += 1
            written += 1
        else:
            unmatched.append(id_val)
    
    # Build report
    report = {
        'written': written,
        'unmatched': unmatched,
        'duplicates_in_data': duplicates_in_data,
        'duplicates_in_list': duplicates_in_list,
    }
    
    # Warn about issues
    if unmatched:
        print(f"WARNING: {len(unmatched)} IDs from list not found in data: {unmatched[:5]}...")
    if duplicates_in_data:
        print(f"WARNING: Duplicate IDs in data (last wins): {duplicates_in_data}")
    if duplicates_in_list:
        print(f"WARNING: Duplicate IDs in list: {duplicates_in_list}")
    
    return output_row, report


def assert_no_formula_strings(ws, min_row, max_row, min_col, max_col):
    """Assert that no cell in the region contains a formula string.
    
    Call this after writing to ensure formulas were evaluated.
    """
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            val = ws.cell(row, col).value
            if isinstance(val, str) and val.startswith('='):
                raise AssertionError(f"Cell R{row}C{col} still contains formula: {val!r}")


def verify_preservation(input_path, output_path, sheet_name, transform_region):
    """Verify that non-transformed regions are preserved.
    
    Args:
        input_path: Path to input xlsx
        output_path: Path to output xlsx  
        sheet_name: Name of sheet to check
        transform_region: Tuple (min_row, max_row, min_col, max_col) of transformed area
    
    Raises:
        AssertionError if any preservation constraint is violated
    """
    wi = load_workbook(input_path)
    wo = load_workbook(output_path)
    
    # Check sheets preserved
    assert wi.sheetnames == wo.sheetnames, f"Sheet list changed: {wi.sheetnames} vs {wo.sheetnames}"
    
    si = wi[sheet_name]
    so = wo[sheet_name]
    
    # Check freeze panes preserved
    assert si.freeze_panes == so.freeze_panes, f"Freeze panes changed: {si.freeze_panes} vs {so.freeze_panes}"
    
    # Check auto filter preserved
    si_filter = si.auto_filter.ref if si.auto_filter else None
    so_filter = so.auto_filter.ref if so.auto_filter else None
    assert si_filter == so_filter, f"AutoFilter changed: {si_filter} vs {so_filter}"
    
    # Check merged cells preserved
    si_merged = sorted(map(str, si.merged_cells.ranges))
    so_merged = sorted(map(str, so.merged_cells.ranges))
    assert si_merged == so_merged, f"Merged cells changed"
    
    # Check dimensions preserved
    assert si.max_row == so.max_row, f"Max row changed: {si.max_row} vs {so.max_row}"
    assert si.max_column == so.max_column, f"Max column changed: {si.max_column} vs {so.max_column}"
    
    # Check row heights preserved
    for idx in set(si.row_dimensions) | set(so.row_dimensions):
        hi = si.row_dimensions[idx].height if idx in si.row_dimensions else None
        ho = so.row_dimensions[idx].height if idx in so.row_dimensions else None
        assert hi == ho, f"Row {idx} height changed: {hi} vs {ho}"
    
    # Check column widths preserved
    for idx in set(si.column_dimensions) | set(so.column_dimensions):
        wi_width = si.column_dimensions[idx].width if idx in si.column_dimensions else None
        wo_width = so.column_dimensions[idx].width if idx in so.column_dimensions else None
        assert wi_width == wo_width, f"Column {idx} width changed: {wi_width} vs {wo_width}"
    
    # Check values outside transform region are identical
    r1, r2, c1, c2 = transform_region
    for row in range(1, si.max_row + 1):
        for col in range(1, si.max_column + 1):
            if r1 <= row <= r2 and c1 <= col <= c2:
                continue
            vi = si.cell(row, col).value
            vo = so.cell(row, col).value
            assert vi == vo, f"Outside-region change at R{row}C{col}: {vi!r} vs {vo!r}"
    
    print(f"Verification passed for {input_path} -> {output_path}")
    return True
