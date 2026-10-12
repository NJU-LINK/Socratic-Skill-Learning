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
def filter_compact(ws, source_rows, dest_start_row, predicate, min_col, max_col):
    """Filter rows by predicate and write compactly to destination."""
    write_row = dest_start_row
    for row_idx in source_rows:
        row_vals = [ws.cell(row=row_idx, column=c).value for c in range(min_col, max_col+1)]
        if predicate(row_vals):
            for col_idx in range(min_col, max_col + 1):
                ws.cell(row=write_row, column=col_idx).value = row_vals[col_idx - min_col]
            write_row += 1
    return write_row  # Next available row
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
    """Transpose a rectangular range."""
    for r in range(src_min_row, src_max_row + 1):
        for c in range(src_min_col, src_max_col + 1):
            val = ws.cell(row=r, column=c).value
            # Transpose: (r, c) -> (dst_min_row + (c - src_min_col), dst_min_col + (r - src_min_row))
            dst_r = dst_min_row + (c - src_min_col)
            dst_c = dst_min_col + (r - src_min_row)
            ws.cell(row=dst_r, column=dst_c).value = val
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
