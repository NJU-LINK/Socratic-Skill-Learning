---
name: xlsx-structure
description: >
  Perform structural transformations on Excel (.xlsx) workbooks using openpyxl.
  Covers block-local sorting, predicate/style-based filtering, header-aligned
  append, sparse-record reconciliation, row extraction, and layout transposition.
  Handles formula evaluation, block detection, style preservation, and
  multi-sheet workbook integrity.
---

# XLSX Structural Transformation Skill

## Overview

This skill addresses the family of tasks that require reading an Excel workbook,
performing a structural transformation on its data, and writing the result while
preserving all unrelated workbook state. The transformations operate on the
logical structure of the data (blocks, headers, IDs, ranges) rather than on
individual cell formatting.

## Core Methodology

Every task in this family follows the same high-level pipeline:

```
1. PARSE   → Understand the task instruction and identify the transformation type
2. LOAD    → Open the workbook preserving all metadata (styles, filters, panes, etc.)
3. LOCATE  → Identify source data regions, blocks, headers, and selection criteria
4. EVALUATE→ Resolve formulas to numeric values where required
5. SELECT  → Apply selection/alignment rules to determine which rows/cells to transform
6. TRANSFORM→ Execute the structural operation (sort, filter, transpose, append, etc.)
7. WRITE   → Place results in the designated output geometry
8. PRESERVE→ Ensure all non-target workbook state is untouched
9. SAVE    → Write the output workbook
```

## Step-by-Step Implementation Guide

### 1. Loading the Workbook

Always load with `data_only=False` to access formula strings. Use a separate
`data_only=True` load only if cached values are needed for verification.

```python
import openpyxl
from copy import copy

wb = openpyxl.load_workbook(input_path, data_only=False)
ws = wb[sheet_name]  # or wb.active
```

**Critical**: Never use `data_only=True` as the primary load for transformation,
because cached values may be absent or stale. Always evaluate formulas yourself.

### 2. Detecting Structural Elements

#### Block Detection (blank-row-separated groups)

```python
def detect_blocks(ws, min_row, max_row, min_col, max_col):
    """Detect contiguous non-empty row blocks separated by blank rows."""
    blocks = []
    current_block = []
    for row_idx in range(min_row, max_row + 1):
        all_empty = True
        for col_idx in range(min_col, max_col + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if cell.value is not None and str(cell.value).strip() != '':
                all_empty = False
                break
        if all_empty:
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(row_idx)
    if current_block:
        blocks.append(current_block)
    return blocks
```

#### Header Detection

Look for the first row that contains non-empty text labels. Headers may be in
any row; scan from the top until a row with multiple non-empty text cells is found.

```python
def detect_header_row(ws, min_row=1, max_row=20, min_col=1, max_col=None):
    """Find the header row by looking for a row with multiple text labels."""
    if max_col is None:
        max_col = ws.max_column
    for row_idx in range(min_row, max_row + 1):
        text_count = 0
        for col_idx in range(min_col, max_col + 1):
            v = ws.cell(row=row_idx, column=col_idx).value
            if isinstance(v, str) and v.strip():
                text_count += 1
        if text_count >= 2:  # At least 2 text cells suggests a header
            return row_idx
    return None
```

### 3. Formula Evaluation

Formulas in xlsx cells are stored as strings starting with `=`. They may reference
other cells in the same row or in other rows. For row-local formulas:

```python
import re
from openpyxl.utils import column_index_from_string

def evaluate_row_formulas(row_values, col_indices_to_eval=None):
    """
    Evaluate formulas in specified columns of a row.
    row_values: dict mapping 1-based column index to cell value
    col_indices_to_eval: list of column indices to evaluate (in dependency order)
    Returns: updated row_values dict with formulas replaced by numeric results
    """
    if col_indices_to_eval is None:
        col_indices_to_eval = sorted(row_values.keys())
    
    for col_idx in col_indices_to_eval:
        val = row_values[col_idx]
        if isinstance(val, str) and val.startswith('='):
            row_values[col_idx] = _eval_single_formula(val, row_values)
    return row_values

def _eval_single_formula(formula_str, row_vals):
    """Evaluate a simple arithmetic formula with cell references."""
    expr = formula_str[1:]  # Remove '='
    
    def replace_ref(match):
        col_letter = match.group(1).upper()
        # Guard: letter sequences > 3 chars are function names (SUM, ABS, MAX, etc.),
        # not column references. Valid Excel columns are 1-3 letters (A-XFD).
        if len(col_letter) > 3:
            return match.group(0)  # Leave function names untouched
        try:
            col_idx = column_index_from_string(col_letter)
        except ValueError:
            return match.group(0)  # Invalid column reference
        if col_idx in row_vals:
            v = row_vals[col_idx]
            if isinstance(v, (int, float)):
                return str(v)
            elif isinstance(v, str):
                try:
                    return str(float(v))
                except (ValueError, TypeError):
                    return '0'
        return '0'
    
    # Replace cell references (e.g., B1, C1, AA5) but NOT function names
    expr_eval = re.sub(r'([A-Za-z]+)\d+', replace_ref, expr)
    
    try:
        return eval(expr_eval, {"__builtins__": {}}, {})
    except Exception:
        return formula_str  # Return original if evaluation fails
```

**Important**: Evaluate in dependency order. If column F references column D,
evaluate D before F. When in doubt, do multiple passes until no more formulas
remain.

For formulas that reference cells in other rows, you need to resolve those
references from the worksheet data first.

### 4. Common Transformation Patterns

#### Block-Local Sorting

```python
def sort_blocks(ws, blocks, sort_col_idx, descending=True, min_col=1, max_col=None):
    """Sort rows within each block by evaluated numeric value, preserving styles.
    
    CRITICAL: Uses capture_row/write_row so that styles (font, fill, alignment,
    border) travel with the data, not stay pinned to the original row position.
    Without this, heterogeneous per-row styles (alternating colors, style-marked
    selection criteria) would become mismatched after sorting.
    """
    if max_col is None:
        max_col = ws.max_column
    
    for block_rows in blocks:
        # Capture values AND styles BEFORE any evaluation
        rows_data = []
        for row_idx in block_rows:
            cells = capture_row(ws, row_idx, min_col, max_col)
            rows_data.append((row_idx, cells))
        
        # Evaluate formulas in captured data, updating values in-place
        for _, cells in rows_data:
            row_vals = {}
            for i, cd in enumerate(cells):
                row_vals[min_col + i] = cd['value']
            # Evaluate in dependency order (left to right within the row)
            for col_idx in sorted(row_vals.keys()):
                val = row_vals[col_idx]
                if isinstance(val, str) and val.startswith('='):
                    evaluated = _eval_single_formula(val, row_vals)
                    row_vals[col_idx] = evaluated
            # Write evaluated values back into captured cell structures
            for i in range(len(cells)):
                cells[i]['value'] = row_vals[min_col + i]
        
        # Sort by the target column's evaluated numeric value (stable sort)
        def sort_key(item):
            cells = item[1]
            v = cells[sort_col_idx - min_col]['value']
            try:
                return float(v) if v is not None else float('-inf')
            except (ValueError, TypeError):
                return float('-inf')
        
        rows_data.sort(key=sort_key, reverse=descending)
        
        # Write back with BOTH values and styles
        for new_pos, (_, cells) in enumerate(rows_data):
            write_row(ws, block_rows[new_pos], cells, min_col)
```

#### Predicate-Based Filtering and Compaction

Select rows matching a predicate and write them compactly (no gaps).

```python
def filter_compact(ws, source_rows, dest_start_row, predicate, min_col, max_col,
                   preserve_styles=True):
    """Filter rows by predicate and write compactly to destination.
    
    CRITICAL: When preserve_styles=True (default), uses capture_row/write_row
    so styles travel with data. Without this, filtered rows lose their original
    formatting when written to the destination.
    """
    next_write = dest_start_row
    for row_idx in source_rows:
        row_vals = [ws.cell(row=row_idx, column=c).value for c in range(min_col, max_col+1)]
        if predicate(row_vals):
            if preserve_styles:
                cells = capture_row(ws, row_idx, min_col, max_col)
                write_row(ws, next_write, cells, min_col)
            else:
                for col_idx in range(min_col, max_col + 1):
                    ws.cell(row=next_write, column=col_idx).value = row_vals[col_idx - min_col]
            next_write += 1
    return next_write  # Next available row
```

#### Header-Aligned Append

Add new rows to a table, aligning values by header name.

```python
def append_by_header(ws, header_row, new_data_dicts, min_col, max_col):
    """Append rows aligned to headers. new_data_dicts: list of {header: value}."""
    # Build header map
    header_map = {}
    for col_idx in range(min_col, max_col + 1):
        h = ws.cell(row=header_row, column=col_idx).value
        if h:
            header_map[str(h).strip()] = col_idx
    
    # Find next empty row
    next_row = header_row + 1
    while any(ws.cell(row=next_row, column=c).value is not None 
              for c in range(min_col, max_col + 1)):
        next_row += 1
    
    for data_dict in new_data_dicts:
        for header, value in data_dict.items():
            if header in header_map:
                ws.cell(row=next_row, column=header_map[header]).value = value
        next_row += 1
```

#### Layout Transposition

Convert rows to columns or vice versa within a range.

```python
def transpose_range(ws, src_min_row, src_max_row, src_min_col, src_max_col,
                    dst_min_row, dst_min_col):
    """Transpose a rectangular range, preserving styles.
    
    CRITICAL: Captures ALL cells into memory BEFORE writing any destination cells.
    This prevents aliasing bugs when source and destination ranges overlap.
    Without this, in-place transposition reads stale (already-overwritten) values.
    """
    # Capture entire source range first
    captured = []
    for r in range(src_min_row, src_max_row + 1):
        row_cells = []
        for c in range(src_min_col, src_max_col + 1):
            cell = ws.cell(row=r, column=c)
            row_cells.append({
                'value': cell.value,
                'font': copy(cell.font),
                'fill': copy(cell.fill),
                'alignment': copy(cell.alignment),
                'border': copy(cell.border),
                'number_format': cell.number_format,
            })
        captured.append(row_cells)
    
    # Now write transposed data
    for r_offset, row_cells in enumerate(captured):
        for c_offset, cell_data in enumerate(row_cells):
            dst_r = dst_min_row + c_offset
            dst_c = dst_min_col + r_offset
            cell = ws.cell(row=dst_r, column=dst_c)
            cell.value = cell_data['value']
            cell.font = cell_data['font']
            cell.fill = cell_data['fill']
            cell.alignment = cell_data['alignment']
            cell.border = cell_data['border']
            cell.number_format = cell_data['number_format']
```

#### ID-Based Matching and Alignment

Match records across ranges or sheets by a key column (ID). Essential for
sparse-record reconciliation, row extraction by ID list, and cross-sheet lookups.

```python
def build_id_map(ws, id_col, data_cols, min_row, max_row, capture_styles=False):
    """Build a dict mapping ID value -> list of row data dicts.
    
    Args:
        ws: worksheet
        id_col: 1-based column index containing the ID/key
        data_cols: list of 1-based column indices to capture
        min_row, max_row: row range to scan
        capture_styles: if True, also capture cell styles for each data column
    
    Returns:
        dict: {id_value: [{col_idx: value, ...}, ...]}
              If capture_styles=True, each row_data also has a 'style' dict:
              {col_idx: style_dict} where style_dict has font, fill, alignment, etc.
        Multiple rows per ID are stored as a list (for duplicate IDs).
    """
    id_map = {}
    for row_idx in range(min_row, max_row + 1):
        id_val = ws.cell(row=row_idx, column=id_col).value
        if id_val is None:
            continue
        # Normalize ID for matching (strip whitespace, convert to string)
        id_key = str(id_val).strip() if not isinstance(id_val, str) else id_val.strip()
        row_data = {}
        if capture_styles:
            row_data['style'] = {}
        for col_idx in data_cols:
            cell = ws.cell(row=row_idx, column=col_idx)
            row_data[col_idx] = cell.value
            if capture_styles:
                row_data['style'][col_idx] = {
                    'font': copy(cell.font),
                    'fill': copy(cell.fill),
                    'alignment': copy(cell.alignment),
                    'border': copy(cell.border),
                    'number_format': cell.number_format,
                }
        if id_key not in id_map:
            id_map[id_key] = []
        id_map[id_key].append(row_data)
    return id_map

def reconcile_by_id(ws, source_id_map, dest_id_col, dest_data_cols,
                    dest_min_row, dest_max_row, match_mode='update',
                    preserve_source_style=False):
    """Reconcile destination rows with source data by ID matching.
    
    Args:
        ws: worksheet to modify
        source_id_map: dict from build_id_map()
        dest_id_col: 1-based column index of ID in destination
        dest_data_cols: list of 1-based column indices to update
        dest_min_row, dest_max_row: destination row range
        match_mode: 'update' (overwrite), 'fill_empty' (only fill None),
                    or 'append_missing' (add new rows for unmatched IDs)
        preserve_source_style: if True, copy styles from source cells to destination.
                               If False (default), destination cells keep their existing styles.
    
    Returns:
        list: IDs from source that had no match in destination
    
    CRITICAL: When preserve_source_style=True, uses copy_cell_style() to transfer
    formatting from source to destination cells. Without this, reconciled data
    loses the source's formatting (bold, colors, alignment, etc.).
    """
    matched_ids = set()
    unmatched_source = []
    
    for row_idx in range(dest_min_row, dest_max_row + 1):
        dest_id = ws.cell(row=row_idx, column=dest_id_col).value
        if dest_id is None:
            continue
        dest_key = str(dest_id).strip() if not isinstance(dest_id, str) else dest_id.strip()
        
        if dest_key in source_id_map:
            matched_ids.add(dest_key)
            source_rows = source_id_map[dest_key]
            # Use first matching source row (or implement multi-row logic)
            source_data = source_rows[0]
            for col_idx in dest_data_cols:
                if col_idx in source_data:
                    src_val = source_data[col_idx]
                    dest_cell = ws.cell(row=row_idx, column=col_idx)
                    
                    if match_mode == 'fill_empty':
                        if dest_cell.value is None:
                            dest_cell.value = src_val
                            if preserve_source_style and 'style' in source_data:
                                copy_cell_style(source_data['style'][col_idx], dest_cell)
                    else:  # 'update' or 'append_missing'
                        dest_cell.value = src_val
                        if preserve_source_style and 'style' in source_data:
                            copy_cell_style(source_data['style'][col_idx], dest_cell)
    
    # Collect unmatched source IDs
    for id_key in source_id_map:
        if id_key not in matched_ids:
            unmatched_source.append(id_key)
    
    return unmatched_source
```

#### Style-Based Selection

Select rows or cells based on their formatting (fill color, font, etc.).
Useful when the task specifies "select rows with yellow background" or
"filter by bold text".

```python
def get_cell_fill_color(cell):
    """Extract the fill color from a cell as an RGB hex string.
    
    Returns:
        str or None: RGB hex string like 'FFFF00' for yellow, or None if no fill.
    """
    fill = cell.fill
    if fill.patternType is None:
        return None
    # Check foreground color (fgColor)
    fg = fill.fgColor
    if fg.type == 'rgb' and fg.rgb and fg.rgb != '00000000':
        # RGB format: 'AARRGGBB' or 'RRGGBB'
        rgb = fg.rgb
        if len(rgb) == 8:  # AARRGGBB
            return rgb[2:]  # Return RRGGBB
        return rgb
    elif fg.type == 'indexed':
        # Indexed colors map to a palette; return the index
        return f'indexed:{fg.indexed}'
    elif fg.type == 'theme':
        # Theme colors require theme palette lookup
        return f'theme:{fg.theme}:tint:{fg.tint}'
    return None

def select_rows_by_style(ws, col_idx, min_row, max_row, style_predicate):
    """Select rows where a column's cell matches a style predicate.
    
    Args:
        ws: worksheet
        col_idx: 1-based column index to check
        min_row, max_row: row range
        style_predicate: callable(cell) -> bool
    
    Returns:
        list: row indices matching the predicate
    """
    matching_rows = []
    for row_idx in range(min_row, max_row + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        if style_predicate(cell):
            matching_rows.append(row_idx)
    return matching_rows

# Example usage:
# Select rows where column A has yellow fill
# yellow_rows = select_rows_by_style(ws, 1, 1, 100,
#     lambda cell: get_cell_fill_color(cell) == 'FFFF00')
```

#### Row Extraction

Extract rows matching criteria and write them to a destination range.

```python
def extract_rows(ws, source_rows, dest_ws, dest_start_row, min_col, max_col,
                 preserve_styles=True):
    """Extract rows from source to destination, optionally preserving styles.
    
    Args:
        ws: source worksheet
        source_rows: list of row indices to extract
        dest_ws: destination worksheet (can be same as source)
        dest_start_row: first row in destination
        min_col, max_col: column range
        preserve_styles: if True, copy styles along with values
    
    Returns:
        int: next available row in destination
    """
    write_row_idx = dest_start_row
    for src_row_idx in source_rows:
        if preserve_styles:
            cells = capture_row(ws, src_row_idx, min_col, max_col)
            write_row(dest_ws, write_row_idx, cells, min_col)
        else:
            for col_idx in range(min_col, max_col + 1):
                val = ws.cell(row=src_row_idx, column=col_idx).value
                dest_ws.cell(row=write_row_idx, column=col_idx).value = val
        write_row_idx += 1
    return write_row_idx
```

#### Membership-Based Filtering

Select rows where a column's value exists in a reference set. This implements the "membership in another range" selection rule from the spec.

```python
def filter_by_membership(ws, source_rows, ref_values, match_col, min_col, max_col,
                         dest_ws=None, dest_start_row=None, preserve_styles=True):
    """Select rows where match_col value exists in ref_values set.
    
    Args:
        ws: source worksheet
        source_rows: list of row indices to consider
        ref_values: set or list of values to match against
        match_col: 1-based column index to check for membership
        min_col, max_col: column range to extract
        dest_ws: destination worksheet (default: same as source)
        dest_start_row: first row in destination (default: after source_rows)
        preserve_styles: if True, copy styles along with values
    
    Returns:
        list: row indices that matched (for further processing if needed)
    
    Example:
        # Extract all rows where column A contains an ID from the ID list
        id_list = {'ID001', 'ID003', 'ID005'}
        matched = filter_by_membership(ws, range(1, 100), id_list, 1, 1, 8)
    """
    if dest_ws is None:
        dest_ws = ws
    if dest_start_row is None:
        dest_start_row = max(source_rows) + 1 if source_rows else 1
    
    ref_set = set(ref_values)  # Ensure it's a set for O(1) lookup
    matched_rows = []
    
    write_row_idx = dest_start_row
    for src_row_idx in source_rows:
        cell_value = ws.cell(row=src_row_idx, column=match_col).value
        if cell_value in ref_set:
            matched_rows.append(src_row_idx)
            if preserve_styles:
                cells = capture_row(ws, src_row_idx, min_col, max_col)
                write_row(dest_ws, write_row_idx, cells, min_col)
            else:
                for col_idx in range(min_col, max_col + 1):
                    val = ws.cell(row=src_row_idx, column=col_idx).value
                    dest_ws.cell(row=write_row_idx, column=col_idx).value = val
            write_row_idx += 1
    
    return matched_rows
```

#### Source-List Ordered Rearrangement

Reorder destination rows to match the order specified in a source list. This implements the "source-list order" selection rule from the spec.

```python
def reorder_by_source_list(ws, source_list, id_col, data_range_start, data_range_end,
                           min_col, max_col, preserve_styles=True):
    """Reorder rows in data_range to match the order in source_list.
    
    Args:
        ws: worksheet to modify
        source_list: list of ID values in desired order
        id_col: 1-based column index containing the ID/key
        data_range_start: first row of data to reorder
        data_range_end: last row of data to reorder
        min_col, max_col: column range to move
        preserve_styles: if True, copy styles along with values
    
    Returns:
        list: IDs from source_list that were not found in data_range
    
    Example:
        # Reorder rows 1-100 to match the order in id_list
        id_list = ['ID003', 'ID001', 'ID005', 'ID002']
        missing = reorder_by_source_list(ws, id_list, 1, 1, 100, 1, 8)
    """
    # Build a map of ID -> row data for the current data range
    id_to_row = {}
    for row_idx in range(data_range_start, data_range_end + 1):
        id_val = ws.cell(row=row_idx, column=id_col).value
        if id_val is not None:
            id_key = str(id_val).strip() if not isinstance(id_val, str) else id_val.strip()
            if preserve_styles:
                cells = capture_row(ws, row_idx, min_col, max_col)
                id_to_row[id_key] = cells
            else:
                row_data = {}
                for col_idx in range(min_col, max_col + 1):
                    row_data[col_idx] = ws.cell(row=row_idx, column=col_idx).value
                id_to_row[id_key] = row_data
    
    # Write rows in the order specified by source_list
    write_row_idx = data_range_start
    missing_ids = []
    
    for id_val in source_list:
        id_key = str(id_val).strip() if not isinstance(id_val, str) else id_val.strip()
        if id_key in id_to_row:
            row_data = id_to_row[id_key]
            if preserve_styles:
                write_row(ws, write_row_idx, row_data, min_col)
            else:
                for col_idx in range(min_col, max_col + 1):
                    ws.cell(row=write_row_idx, column=col_idx).value = row_data[col_idx]
            write_row_idx += 1
        else:
            missing_ids.append(id_val)
    
    # Clear any remaining rows in the data range (they weren't in source_list)
    for row_idx in range(write_row_idx, data_range_end + 1):
        for col_idx in range(min_col, max_col + 1):
            ws.cell(row=row_idx, column=col_idx).value = None
    
    return missing_ids
```

### 5. Preservation Constraints

When transforming a workbook, you MUST preserve:

- **All other sheets**: Never modify sheets not mentioned in the task
- **Values outside the target range**: Only write to the specified output range
- **Styles**: Copy font, fill, alignment, border, number_format from source cells
- **Column widths and row heights**: These are stored in `ws.column_dimensions` and `ws.row_dimensions`
- **Merged cells**: Stored in `ws.merged_cells.ranges`
- **Auto filters**: Stored in `ws.auto_filter`
- **Freeze panes**: Stored in `ws.freeze_panes`
- **Sheet-level properties**: `ws.sheet_properties`, `ws.page_setup`, etc.

**Strategy**: The safest approach is to modify cells in-place rather than creating
new workbooks. When you must move data between sheets or rearrange extensively,
copy styles explicitly:

```python
def copy_cell_style(src_cell, dst_cell):
    """Copy all style attributes from src to dst cell."""
    dst_cell.font = copy(src_cell.font)
    dst_cell.fill = copy(src_cell.fill)
    dst_cell.alignment = copy(src_cell.alignment)
    dst_cell.border = copy(src_cell.border)
    dst_cell.number_format = src_cell.number_format
    dst_cell.protection = copy(src_cell.protection)
```

### 6. Reading and Writing Cell Data with Styles

When you need to move rows around (e.g., sorting), capture both values and styles:

```python
def capture_row(ws, row_idx, min_col, max_col):
    """Capture values and styles for a row."""
    cells = []
    for col_idx in range(min_col, max_col + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        cells.append({
            'value': cell.value,
            'font': copy(cell.font),
            'fill': copy(cell.fill),
            'alignment': copy(cell.alignment),
            'border': copy(cell.border),
            'number_format': cell.number_format,
        })
    return cells

def write_row(ws, row_idx, cells_data, min_col=1):
    """Write captured row data back to a row, starting at min_col.
    
    Args:
        ws: worksheet
        row_idx: target row number
        cells_data: list of cell dicts from capture_row()
        min_col: the first column index that cells_data[0] corresponds to.
                 Must match the min_col used when capture_row was called.
    """
    for i, cell_data in enumerate(cells_data):
        col_idx = min_col + i
        cell = ws.cell(row=row_idx, column=col_idx)
        cell.value = cell_data['value']
        cell.font = cell_data['font']
        cell.fill = cell_data['fill']
        cell.alignment = cell_data['alignment']
        cell.border = cell_data['border']
        cell.number_format = cell_data['number_format']
```

## Decision Framework

When you receive a task instruction, classify it along these axes:

| Axis | Question to Answer |
|------|--------------------|
| **Transformation** | What operation? Sort, filter, transpose, append, extract, reconcile? |
| **Topology** | Where is the data? Single sheet? Multiple sheets? Blocks? Sparse? |
| **Selection** | How to choose rows/cells? By value? By style? By ID? By position? |
| **Output** | Where does output go? Same range? New sheet? Appended? Transposed? |
| **Preservation** | What must stay unchanged? Other sheets? Styles? Dimensions? |

### Transformation Type → Pattern Mapping

| Transformation Type | Primary Pattern | Key Considerations |
|---------------------|-----------------|-------------------|
| Block-local sorting | `sort_blocks()` | Stable sort, evaluate formulas first, preserve styles |
| Predicate filtering | `filter_compact()` | Define predicate clearly, handle empty results, preserve styles |
| Header-aligned append | `append_by_header()` | Build header map, handle missing headers |
| Sparse-record reconciliation | `build_id_map()` + `reconcile_by_id()` | Normalize IDs, handle duplicates, choose match_mode, optionally preserve styles |
| Row extraction | `extract_rows()` | Preserve styles if needed, handle cross-sheet |
| Layout transposition | `transpose_range()` | Capture all cells first to avoid aliasing, preserve styles |
| Style-based selection | `select_rows_by_style()` | Extract color correctly, handle theme/indexed colors |
| ID-based alignment | `build_id_map()` | Normalize IDs, handle missing matches |
| Membership-based filtering | `filter_by_membership()` | Use set for O(1) lookup, preserve styles |
| Source-list ordered rearrangement | `reorder_by_source_list()` | Capture all rows first, handle missing IDs, clear unused rows |

### Topology Variants

- **Single sheet, contiguous**: Simplest case, operate directly on range
- **Single sheet, blocks**: Use `detect_blocks()`, process each block independently
- **Single sheet, sparse**: Use ID-based matching, handle gaps
- **Multi-sheet**: Load all sheets, use cross-sheet operations, preserve untouched sheets
- **Style-marked regions**: Use `select_rows_by_style()` to identify regions

### Selection Rule Variants

- **Evaluated numeric order**: Evaluate formulas, sort by numeric value
- **Membership in another range**: Build set of IDs/values, filter by membership
- **Exact header/ID identity**: Use `build_id_map()`, match by normalized ID
- **Fill color / style**: Use `get_cell_fill_color()`, compare to target color
- **Text predicates**: Define predicate function, apply to cell values
- **Source-list order**: Maintain order from source list, align destination to it
- **Positional correspondence**: Map by row/column position, not by value

## Composing Transformations

Real-world tasks often require chaining multiple transformations. The order and method of composition matters for correctness and style preservation.

### Order of Operations

Apply transformations in this general order to avoid conflicts:

1. **Selection/Filtering first**: Identify which rows/cells to operate on
   - `select_rows_by_style()`, `filter_by_membership()`, `filter_compact()`
   - This reduces the data scope for subsequent operations

2. **Structural transformations second**: Rearrange the selected data
   - `sort_blocks()`, `reorder_by_source_list()`, `transpose_range()`
   - These operate on the filtered/selected data

3. **Data alignment third**: Match and reconcile data across ranges
   - `build_id_map()`, `reconcile_by_id()`
   - These work on the rearranged data

4. **Output operations last**: Write to final destination
   - `extract_rows()`, `append_by_header()`
   - These place the final result

**Why this order?**
- Filtering first reduces the scope, making subsequent operations faster
- Structural changes before alignment ensures IDs/values are in the right positions
- Output operations last ensures the final result is written correctly

### Common Composition Patterns

#### Pattern 1: Filter → Sort → Extract
```python
# 1. Filter rows by predicate
filtered_rows = filter_compact(ws, source_rows, dest_start_row, 
                                predicate, min_col, max_col, preserve_styles=True)

# 2. Detect blocks in filtered data
blocks = detect_blocks(ws, dest_start_row, filtered_rows - 1, min_col, max_col)

# 3. Sort within blocks
sort_blocks(ws, blocks, sort_col_idx, descending=True, min_col=min_col, max_col=max_col)

# 4. Extract to final destination
extract_rows(ws, range(dest_start_row, filtered_rows), final_ws, final_start_row,
             min_col, max_col, preserve_styles=True)
```

#### Pattern 2: Style Selection → ID Alignment → Reconcile
```python
# 1. Select rows by style
selected_rows = select_rows_by_style(ws, style_col, min_row, max_row, 
                                      lambda cell: get_cell_fill_color(cell) == 'FFFF00')

# 2. Build ID map from selected rows
id_map = build_id_map(ws, id_col, data_cols, min(selected_rows), max(selected_rows),
                      capture_styles=True)

# 3. Reconcile with destination
reconcile_by_id(dest_ws, id_map, dest_id_col, dest_data_cols,
                dest_min_row, dest_max_row, match_mode='update',
                preserve_source_style=True)
```

#### Pattern 3: Membership Filter → Reorder → Transpose
```python
# 1. Filter by membership
matched_rows = filter_by_membership(ws, source_rows, ref_values, match_col,
                                     min_col, max_col, preserve_styles=True)

# 2. Reorder to match source list
reorder_by_source_list(ws, source_list, id_col, min(matched_rows), max(matched_rows),
                       min_col, max_col, preserve_styles=True)

# 3. Transpose result
transpose_range(ws, min(matched_rows), max(matched_rows), min_col, max_col,
                dest_min_row, dest_min_col)
```

### Data Flow Between Transformations

When composing transformations, ensure data flows correctly:

1. **Preserve styles throughout**: Use `preserve_styles=True` in all operations
2. **Track row ranges**: Each transformation may change the row range
   - After filtering: new range is `[dest_start_row, next_write - 1]`
   - After sorting: range stays the same
   - After transposing: rows become columns, columns become rows
3. **Capture before rearranging**: Always use `capture_row()` before moving data
4. **Write after all transformations**: Minimize intermediate writes to avoid style loss

### Anti-Patterns to Avoid

**❌ Don't sort then filter**: Filtering after sorting wastes effort sorting rows that will be discarded.

**❌ Don't transpose then sort**: Transposing changes the data structure; sorting after transpose may not make sense.

**❌ Don't write intermediate results**: Each write operation can lose styles. Chain transformations in memory, then write once.

**❌ Don't ignore row range changes**: After filtering or extraction, the row range changes. Update your range tracking.

### Example: Multi-Step Workflow

Task: "Extract rows with yellow fill from Sheet1, sort by column D, and write to Sheet2"

```python
# Step 1: Select rows by style
yellow_rows = select_rows_by_style(ws1, 1, 1, 100, 
                                    lambda cell: get_cell_fill_color(cell) == 'FFFF00')

# Step 2: Capture all selected rows with styles
captured_data = []
for row_idx in yellow_rows:
    cells = capture_row(ws1, row_idx, 1, 8)
    captured_data.append(cells)

# Step 3: Evaluate formulas in captured data
for cells in captured_data:
    row_vals = {i+1: cd['value'] for i, cd in enumerate(cells)}
    for col_idx in sorted(row_vals.keys()):
        val = row_vals[col_idx]
        if isinstance(val, str) and val.startswith('='):
            evaluated = _eval_single_formula(val, row_vals)
            row_vals[col_idx] = evaluated
            cells[col_idx-1]['value'] = evaluated

# Step 4: Sort by column D (index 3)
captured_data.sort(key=lambda cells: float(cells[3]['value']), reverse=True)

# Step 5: Write to Sheet2 in one operation
for i, cells in enumerate(captured_data):
    write_row(ws2, i+1, cells, 1)

wb.save('output.xlsx')
```

**Key principles:**
- Capture once, transform in memory, write once
- Preserve styles throughout the pipeline
- Track data structure changes (rows → columns after transpose)
- Evaluate formulas before sorting/filtering

## Common Pitfalls

1. **Formula evaluation order**: If F depends on D, evaluate D first. Use dependency-aware ordering.
2. **Blank row detection**: A row is blank only if ALL cells in the relevant range are empty/None.
3. **Stable sort**: When sorting, use stable sort to preserve original order for equal keys.
4. **String-to-number coercion**: Cell values may be strings that look like numbers. Always attempt `float()` conversion before sorting numerically.
5. **Formula text**: Some cells contain formula text (starting with `=`) as their value. These must be evaluated, not sorted lexically.
6. **Preserving column D-F values**: After evaluation, write the numeric result, not the formula string.
7. **openpyxl limitations**: openpyxl cannot evaluate formulas itself. You must implement evaluation for the arithmetic patterns present in the workbook.
8. **Floating point precision**: Use the raw float values; do not round unless the task specifies it.
9. **Style follows data, not position**: In openpyxl, styles are attached to cell objects at positions, not to data. When rearranging rows (sorting, filtering, transposing), you MUST capture both values and styles together, then write them together. If you only move values, styles stay pinned to the original row positions and become mismatched with the moved data. This is invisible when all rows in a block share identical per-column styles, but causes silent corruption with heterogeneous row styles (alternating colors, style-marked selection criteria).
10. **Formula regex must not corrupt function names**: The regex `([A-Za-z]+)\d+` matches any letter sequence followed by digits. Excel function names like `SUM`, `ABS`, `MAX`, `ROUND` have no trailing digits and won't match, but if a formula contains `SUM1` or similar, it could be misidentified as a cell reference. Always guard by checking that the letter part is ≤ 3 characters (valid Excel column range is A-XFD). Letter sequences > 3 chars are always function names, not columns.
11. **Column offset in write_row**: When `capture_row` is called with `min_col=3`, the returned list has elements for columns 3, 4, 5, ... If `write_row` hardcodes `col_idx = i + 1`, it writes to columns 1, 2, 3, ... instead. Always pass `min_col` to `write_row` and compute `col_idx = min_col + i`.
12. **ID normalization**: When matching records by ID, normalize IDs consistently: strip whitespace, handle case sensitivity (usually case-insensitive), convert numeric IDs to strings. Otherwise "ABC " won't match "ABC", or 123 won't match "123".
13. **Theme and indexed colors**: Excel fill colors can be RGB, theme-based, or indexed. `get_cell_fill_color()` returns different formats for each. When comparing colors, ensure you're comparing the same type. Theme colors require the workbook's theme palette to resolve to RGB.
14. **Cross-sheet preservation**: When operating on multiple sheets, never modify sheets not mentioned in the task. Load all sheets, operate only on the target sheet(s), and save the entire workbook. Openpyxl preserves other sheets automatically if you don't modify them.
15. **Multi-pass formula evaluation**: Some formulas reference other formulas. If D1 contains `=B1+C1` and F1 contains `=D1+E1`, you must evaluate D1 before F1. Use iterative evaluation: keep evaluating until no more formulas remain, or detect cycles.
16. **Duplicate IDs in reconciliation**: When building an ID map, multiple rows may have the same ID. Store them as a list. Decide how to handle duplicates: use first match, merge values, or flag as error.
17. **Empty results in filtering**: When filtering produces no matching rows, the destination range may be empty. Handle this gracefully: either leave the range blank or write a header/placeholder as specified by the task.
18. **Range aliasing in transpose**: If source and destination ranges overlap, in-place cell-by-cell transposition reads stale (already-overwritten) values. Always capture the entire source range into memory before writing any destination cells. This is the same "capture first, write second" principle used in sorting.
19. **Audit all data-moving functions for style preservation**: When you fix a style-preservation bug in one function (e.g., `sort_blocks`), audit ALL other functions that move, copy, or rearrange data. A grep for `.value` assignments without corresponding style copies will catch violations. The universal rule: any function that MOVES data MUST capture styles alongside values, unless the task explicitly says styles should be discarded.
20. **Composition order matters**: When chaining transformations, apply them in the correct order: selection/filtering → structural changes → data alignment → output. Wrong order can cause wasted effort (sorting then filtering), data loss (transposing then sorting), or incorrect results.
21. **Track row range changes through composition**: Each transformation may change the row range. After filtering: `[dest_start_row, next_write - 1]`. After transposing: rows become columns. Always update your range tracking between steps.
22. **Minimize intermediate writes in compositions**: Each write operation can lose styles if not done carefully. Chain transformations in memory (capture → transform → transform → write) rather than writing after each step.

## Complete Workflow Template

```python
import openpyxl
from copy import copy
import re
from openpyxl.utils import column_index_from_string

def solve_xlsx_structure(input_path, output_path, task_instruction):
    """
    General template for xlsx structural transformation tasks.
    Adapt the LOCATE, SELECT, and TRANSFORM steps to the specific task.
    """
    # LOAD
    wb = openpyxl.load_workbook(input_path, data_only=False)
    ws = wb[task_instruction.get('sheet', 'Sheet1')]
    
    # LOCATE - identify the data region and structural elements
    min_row = task_instruction.get('min_row', 1)
    max_row = task_instruction.get('max_row', ws.max_row)
    min_col = task_instruction.get('min_col', 1)
    max_col = task_instruction.get('max_col', ws.max_column)
    
    # Determine structural elements based on task type
    # (blocks, headers, ID columns, etc.)
    
    # EVALUATE - resolve formulas to values
    # (evaluate formulas in relevant columns)
    
    # SELECT + TRANSFORM - apply the transformation
    # (sort, filter, transpose, etc.)
    
    # WRITE + PRESERVE - write results, preserve everything else
    wb.save(output_path)
```

## Verification Checklist

After implementing a solution, verify:

- [ ] All formulas in the target range are evaluated to numeric values
- [ ] Block boundaries are correctly detected and maintained
- [ ] Sorting/filtering uses evaluated numeric values, not text
- [ ] Stable sort preserves original order for equal keys
- [ ] All sheets other than the target are unchanged
- [ ] Values outside the target range are unchanged
- [ ] Styles (font, fill, alignment, border) are preserved for moved data
- [ ] Column widths, row heights, merged cells, filters, panes are intact
- [ ] Output file is valid xlsx that opens correctly
- [ ] ID matching normalizes IDs consistently (whitespace, case, type)
- [ ] Style-based selection correctly extracts and compares colors
- [ ] Cross-sheet operations preserve untouched sheets
- [ ] Duplicate IDs are handled according to task requirements
- [ ] Empty filter results are handled gracefully
- [ ] Multiple transformations are composed in correct order (filter → sort → align → output)
- [ ] Row ranges are tracked correctly through composition pipeline
- [ ] Styles are preserved through all transformation steps
- [ ] Formulas are evaluated before sorting/filtering operations
- [ ] Data is captured once, transformed in memory, written once (minimize intermediate writes)
