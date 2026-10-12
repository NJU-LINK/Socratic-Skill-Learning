---
name: xlsx-structure
description: >
  Perform structural transformations on Excel workbooks (.xlsx) using openpyxl.
  Handles block-local sorting, filtering, compaction, header-aligned append,
  sparse-record reconciliation, row extraction, and layout transposition across
  diverse workbook topologies while preserving styles, dimensions, filters,
  merged ranges, panes, and other workbook state.
---

# XLSX Structural Transformation Skill

## Overview

This skill covers structural transformations on Excel workbooks. The core workflow is:

1. **Parse the task instruction** to identify: transformation type, source/destination topology, selection/alignment rules, output geometry, and preservation constraints.
2. **Load the workbook** with openpyxl (both formula-aware and data-only modes).
3. **Detect the workbook topology** (blocks, sheets, ranges, headers).
4. **Evaluate formulas** to numeric values where required.
5. **Apply the transformation** (sort, filter, compact, append, extract, transpose).
6. **Preserve all constraints** (styles, dimensions, other sheets, etc.).
7. **Save the output** to the specified path.

## ⚠ Critical Principle: Evaluate Before Transform

**Never let a structural transformation (sort, filter, transpose, compact) operate on cells that still contain unevaluated formulas.**

The correct pipeline order is:
1. **Evaluate & replace** all formulas → numeric values (snapshot pattern)
2. **Detect** topology (blocks, headers, ranges)
3. **Transform** (sort, filter, compact, transpose, etc.)

If you transform first, formula strings get moved to new positions. Subsequent evaluation may fail when formulas have cross-column dependencies (e.g., F=`D+E` where D is also a formula). After replacement, all cells are plain numbers — transformations become trivial data moves.

## Environment Setup

```python
import openpyxl
from copy import copy
import re

# Load with formulas (for structure, styles, formula text)
wb = openpyxl.load_workbook('input.xlsx')

# Load data_only (for cached/computed formula values)
wb_data = openpyxl.load_workbook('input.xlsx', data_only=True)
```

## Core Patterns

### 1. Block Detection

Blocks are contiguous groups of non-empty rows separated by blank rows. Detect them by scanning the data range:

```python
def find_blocks(ws, min_row, max_row, min_col, max_col):
    """Find contiguous non-blank row blocks within a range."""
    blank_rows = set()
    for r in range(min_row, max_row + 1):
        if all(ws.cell(row=r, column=c).value is None 
               for c in range(min_col, max_col + 1)):
            blank_rows.add(r)
    
    blocks = []
    current_start = None
    for r in range(min_row, max_row + 1):
        if r not in blank_rows:
            if current_start is None:
                current_start = r
        else:
            if current_start is not None:
                blocks.append((current_start, r - 1))
                current_start = None
    if current_start is not None:
        blocks.append((current_start, max_row))
    
    return blocks, blank_rows
```

**Key insight**: Block boundaries are detected from the workbook data, not assumed from fixed row counts. A blank row is one where ALL cells in the data range are None.

### 2. Formula Evaluation

Formulas may appear as:
- Native Excel formulas (data_type == 'f'): use `data_only=True` cached values
- Text strings that look like formulas (e.g., `"=B1+C1"` stored as string): parse and evaluate manually

```python
def evaluate_cell(ws_formula, ws_data, row, col):
    """Get the evaluated numeric value for a cell."""
    cell = ws_formula.cell(row=row, column=col)
    val = cell.value
    
    if val is None:
        return None
    
    # Native formula - use cached value
    if cell.data_type == 'f':
        cached = ws_data.cell(row=row, column=col).value
        if cached is not None:
            return cached
        # Fallback: manual evaluation
        return manual_eval_formula(ws_data, row, val)
    
    # String that looks like a formula
    if isinstance(val, str) and val.startswith('='):
        return manual_eval_formula(ws_data, row, val)
    
    # Already a number or plain text
    return val

def manual_eval_formula(ws_data, current_row, formula_str):
    """Manually evaluate simple arithmetic formulas with cell references."""
    expr = formula_str[1:]  # Remove leading '='
    
    def replace_ref(match):
        ref = match.group(0)
        col_letters = ''.join(c for c in ref if c.isalpha())
        row_num = int(''.join(c for c in ref if c.isdigit()))
        col_idx = openpyxl.utils.column_index_from_string(col_letters)
        val = ws_data.cell(row=row_num, column=col_idx).value
        if val is None:
            return '0'
        return str(val)
    
    # Replace cell references (e.g., B1, AA23) with their values
    expr = re.sub(r'[A-Z]+\d+', replace_ref, expr)
    
    try:
        return eval(expr, {"__builtins__": {}}, {})
    except:
        return formula_str  # Return original if evaluation fails
```

**Critical**: When column F contains `=D1+E1` and D1 is itself a formula, the evaluation of F must use the EVALUATED value of D, not the formula string. The `data_only` workbook provides this automatically via cached values. However, when cached values are absent (programmatically generated xlsx), use the snapshot-based variant `evaluate_cell_with_snapshot` (see section 4) which resolves dependencies by evaluating columns in order and consulting the snapshot for already-evaluated cells.

### 3. Block-Local Sorting

Sort rows within each block by a specified column's numeric value. **Prerequisite**: formulas must already be replaced with numeric values (see section 4), so the sort column contains plain numbers.

```python
def sort_block(ws, block_start, block_end, sort_col, 
               min_col, max_col, descending=True):
    """Sort rows within a block by numeric value of sort_col.
    Assumes formulas have already been replaced with values."""
    rows_data = []
    for r in range(block_start, block_end + 1):
        # Capture all cell values (plain numbers, no formulas)
        row_info = {
            'values': [ws.cell(row=r, column=c).value for c in range(min_col, max_col + 1)],
            'sort_key': ws.cell(row=r, column=sort_col).value,  # plain number
            'styles': {},
            'height': ws.row_dimensions[r].height if r in ws.row_dimensions else None,
        }
        # Capture styles for each cell
        for c in range(min_col, max_col + 1):
            cell = ws.cell(row=r, column=c)
            row_info['styles'][c] = {
                'font': copy(cell.font),
                'fill': copy(cell.fill),
                'border': copy(cell.border),
                'alignment': copy(cell.alignment),
                'number_format': cell.number_format,
            }
        rows_data.append(row_info)
    
    # Stable sort by numeric value
    rows_data.sort(key=lambda x: x['sort_key'] if x['sort_key'] is not None else float('-inf'), 
                   reverse=descending)
    
    # Write back sorted rows
    for i, rd in enumerate(rows_data):
        target_row = block_start + i
        for c_idx, c in enumerate(range(min_col, max_col + 1)):
            cell = ws.cell(row=target_row, column=c)
            cell.value = rd['values'][c_idx]
            # Restore styles from the SOURCE row (they move with data)
            style = rd['styles'][c]
            cell.font = style['font']
            cell.fill = style['fill']
            cell.border = style['border']
            cell.alignment = style['alignment']
            cell.number_format = style['number_format']
        # Restore row height from the SOURCE row
        if rd['height'] is not None:
            ws.row_dimensions[target_row].height = rd['height']
```

**Stable sort**: Python's `list.sort()` is stable. When two rows have the same sort key, their original relative order is preserved.

**Style movement**: When sorting rows, styles should move with the data (the visual appearance of each row travels with it). Capture and restore styles per-row.

**Row height movement**: Row heights are stored on `ws.row_dimensions[row]`, not on individual cells. When sorting rows, row heights must be captured from source rows and restored at target positions.

### 4. Formula Value Replacement (MUST run BEFORE any structural transformation)

When the task requires writing evaluated numeric values instead of formulas, this step MUST execute before any sorting, filtering, transposition, or other structural transformation. The principle: **never let a structural transformation operate on cells that still contain unevaluated formulas. Always reduce formulas to their final values first, then move data.**

Use a snapshot pattern with dependency resolution to avoid cross-column dependency issues:

```python
def replace_formulas_with_values(ws, ws_data, min_row, max_row, columns):
    """Replace formula cells with their evaluated numeric values.
    Uses snapshot pattern with dependency resolution: evaluate formulas
    in column order, updating the snapshot after each column so that
    formulas referencing earlier columns get correct values."""
    # Snapshot: stores evaluated values for all formula cells
    snapshot = {}
    
    # Evaluate column by column (e.g., D before F)
    # This ensures that when F references D, D's evaluated value
    # is already in the snapshot
    for c in columns:
        for r in range(min_row, max_row + 1):
            cell = ws.cell(row=r, column=c)
            if cell.data_type == 'f' or (isinstance(cell.value, str) and cell.value.startswith('=')):
                # Evaluate using snapshot for already-evaluated cells
                val = evaluate_cell_with_snapshot(ws, ws_data, r, c, snapshot)
                snapshot[(r, c)] = val
    
    # Apply: write all evaluated values from the snapshot
    for (r, c), val in snapshot.items():
        ws.cell(row=r, column=c).value = val

def evaluate_cell_with_snapshot(ws_formula, ws_data, row, col, snapshot):
    """Evaluate a cell, using snapshot values for already-evaluated formula cells."""
    cell = ws_formula.cell(row=row, column=col)
    val = cell.value
    
    if val is None:
        return None
    
    # Native formula - try cached value first
    if cell.data_type == 'f':
        cached = ws_data.cell(row=row, column=col).value
        if cached is not None:
            return cached
        # Fallback: manual evaluation with snapshot
        return manual_eval_formula_with_snapshot(ws_data, row, val, snapshot)
    
    # String that looks like a formula
    if isinstance(val, str) and val.startswith('='):
        return manual_eval_formula_with_snapshot(ws_data, row, val, snapshot)
    
    # Already a number or plain text
    return val

def manual_eval_formula_with_snapshot(ws_data, current_row, formula_str, snapshot):
    """Manually evaluate formula, using snapshot for already-evaluated cells."""
    expr = formula_str[1:]  # Remove leading '='
    
    def replace_ref(match):
        ref = match.group(0)
        col_letters = ''.join(c for c in ref if c.isalpha())
        row_num = int(''.join(c for c in ref if c.isdigit()))
        col_idx = openpyxl.utils.column_index_from_string(col_letters)
        
        # First check snapshot (already-evaluated formula cells)
        if (row_num, col_idx) in snapshot:
            return str(snapshot[(row_num, col_idx)])
        
        # Then check ws_data (cached values)
        val = ws_data.cell(row=row_num, column=col_idx).value
        if val is not None:
            return str(val)
        
        return '0'
    
    expr = re.sub(r'[A-Z]+\d+', replace_ref, expr)
    
    try:
        return eval(expr, {"__builtins__": {}}, {})
    except:
        return formula_str
```

**Why snapshot with dependency resolution matters**: Without cached values (e.g., programmatically generated xlsx), `manual_eval_formula` reads from the frozen `ws_data`. If column F's formula references column D (also a formula), and we evaluate F before D, we'd get D's formula string or None. By evaluating column-by-column (D before F) and updating the snapshot after each column, F's evaluation finds D's already-evaluated numeric value in the snapshot.

### 5. Preservation Strategy

openpyxl preserves most workbook state automatically when you only modify cell values. Key preservation points:

```python
# Things preserved automatically by openpyxl when modifying cell values:
# - Other sheets (don't touch them)
# - Column widths (ws.column_dimensions)
# - Row heights (ws.row_dimensions) 
# - Sheet views / panes (ws.views)
# - Auto filters (ws.auto_filter)
# - Merged cells (ws.merged_cells)
# - Cell styles on UNMODIFIED cells

# Things that need explicit handling:
# - Styles on MODIFIED cells: capture before modification, restore after
# - Row heights on MODIFIED rows: capture before modification, restore after
#   (row heights are stored per-row on ws.row_dimensions, not per-cell;
#    when sorting/filtering rows, heights must travel with the data)
# - Values outside the transformation range: don't touch them
```

**Pattern for safe modification**:
```python
def safe_transform(wb, ws, ws_data, transform_func, data_range, preserve_range):
    """
    Apply transform_func to data_range while preserving everything in preserve_range.
    """
    # 1. Snapshot anything outside data_range that might be affected
    # 2. Apply transformation within data_range
    # 3. Verify preservation constraints
    pass
```

### 6. Multi-Sheet Operations

When the task involves multiple sheets:

```python
# Access sheets by name
ws_source = wb['SourceSheet']
ws_dest = wb['DestSheet']

# Or create new sheets
ws_new = wb.create_sheet('NewSheet')

# Copy data between sheets
for r in range(min_row, max_row + 1):
    for c in range(min_col, max_col + 1):
        src_cell = ws_source.cell(row=r, column=c)
        dst_cell = ws_dest.cell(row=r, column=c)
        dst_cell.value = src_cell.value
        dst_cell.font = copy(src_cell.font)
        # ... copy other style attributes
```

### 7. Header Detection and Alignment

When columns are identified by header names rather than positions:

```python
def find_header_row(ws, min_row=1, max_row=10, min_col=1, max_col=20):
    """Find the row that contains column headers."""
    for r in range(min_row, max_row + 1):
        non_empty = sum(1 for c in range(min_col, max_col + 1) 
                       if ws.cell(row=r, column=c).value is not None)
        if non_empty >= 2:  # At least 2 non-empty cells suggests a header row
            return r
    return min_row

def build_header_map(ws, header_row, min_col, max_col):
    """Map header names to column indices."""
    header_map = {}
    for c in range(min_col, max_col + 1):
        val = ws.cell(row=header_row, column=c).value
        if val is not None:
            header_map[str(val).strip()] = c
    return header_map
```

### 8. Filtering and Compaction

When the task requires filtering rows based on predicates:

```python
def filter_block(ws, ws_data, block_start, block_end, predicate, min_col, max_col):
    """Filter rows within a block based on a predicate function."""
    kept_rows = []
    for r in range(block_start, block_end + 1):
        row_vals = [ws.cell(row=r, column=c).value for c in range(min_col, max_col + 1)]
        if predicate(row_vals, r):
            kept_rows.append((r, row_vals))
    return kept_rows
```

### 9. Transposition

When the task requires transposing data (rows ↔ columns):

```python
def transpose_range(ws, src_min_row, src_max_row, src_min_col, src_max_col, 
                    dst_row, dst_col):
    """Transpose a range: rows become columns and vice versa."""
    for r in range(src_min_row, src_max_row + 1):
        for c in range(src_min_col, src_max_col + 1):
            val = ws.cell(row=r, column=c).value
            # Transpose: (r, c) -> (dst_row + (c - src_min_col), dst_col + (r - src_min_row))
            ws.cell(row=dst_row + (c - src_min_col), 
                   column=dst_col + (r - src_min_row)).value = val
```

## Decision Framework

When approaching a new xlsx-structure task:

1. **Identify the transformation type** from the instruction:
   - Sorting → use block-local sorting pattern
   - Filtering → use predicate-based filtering
   - Compaction → filter + recompact (remove blanks)
   - Append → find end of data, write new rows
   - Extraction → copy specific rows/cells to destination
   - Transposition → swap row/column indices

2. **Identify the topology**:
   - Single sheet with blocks → detect blank-row separators
   - Multiple sheets → identify source and destination sheets
   - Header-mapped columns → find header row, build column map
   - Style-marked regions → scan for fill colors or other style markers
   - ID-based alignment → match rows by ID column

3. **Identify the selection rule**:
   - Numeric order → evaluate and sort
   - Membership → check against a list/set
   - Header identity → match column names
   - Fill color → check cell.fill
   - Text predicate → string matching with exclusions

4. **Identify output geometry**:
   - In-place → modify the same range
   - New range → write to specified coordinates
   - New sheet → create or use existing sheet
   - Append → find last row, write after

5. **Identify preservation constraints**:
   - Always preserve: other sheets, values outside transformation range
   - Check for: styles, filters, merged ranges, panes, row heights, column widths

## Common Pitfalls

1. **CRITICAL — Operation ordering**: Always evaluate and replace formulas BEFORE any structural transformation (sort, filter, transpose). If you sort first, formula strings get moved to new positions, and subsequent evaluation may fail when formulas have cross-column dependencies (e.g., F references D which is also a formula). The correct order: (1) replace formulas with values, (2) detect topology, (3) apply transformation.

2. **Formula dependency chains**: When column F's formula references column D, and D is also a formula, the evaluation of F must use D's EVALUATED numeric value, not its formula string. Use the `data_only` workbook's cached values, or use the snapshot pattern in `replace_formulas_with_values` to evaluate everything against the original frozen state.

3. **No cached values**: When xlsx files are generated programmatically (not saved by Excel), `data_only=True` returns `None` for formula cells. The `manual_eval_formula` fallback must handle this. The snapshot pattern ensures all formulas are evaluated against the original state before any modifications.

4. **Floating point precision**: Excel arithmetic may produce floating-point artifacts (e.g., `-0.2999999999999972` instead of `-0.3`). This is expected and correct - don't round unless the task specifies it.

5. **Stable sort**: Always use stable sort when the task says "preserve original relative order" for ties. Python's `sort()` is stable by default.

6. **Block boundary detection**: Don't assume fixed block sizes. Detect boundaries from the actual data (blank rows).

7. **Style preservation**: When moving rows (sorting), styles should move with the data. Capture styles before modification and restore them at the new positions.

8. **Row height preservation**: Row heights are stored on `ws.row_dimensions[row]`, not on cells. When sorting rows, row heights must be captured from source rows and restored at target positions, just like styles.

9. **Blank row preservation**: When sorting within blocks, maintain exactly one blank row between adjacent blocks. Don't accidentally merge or duplicate blank separators.

10. **Data type awareness**: Check `cell.data_type` to distinguish between formulas ('f'), numbers ('n'), strings ('s'), and booleans ('b'). A string starting with '=' might be a formula stored as text.

## Complete Workflow Template

```python
import openpyxl
from copy import copy
import re

def solve_xlsx_structure(input_path, output_path):
    # Load workbooks
    wb = openpyxl.load_workbook(input_path)
    wb_data = openpyxl.load_workbook(input_path, data_only=True)
    
    # Identify target sheet and range from task instruction
    ws = wb['Sheet1']  # or as specified
    ws_data = wb_data['Sheet1']
    
    # Define data range from task instruction
    min_row, max_row = 1, 85  # as specified
    min_col, max_col = 1, 8   # A-H
    
    # STEP 1: Replace formulas FIRST (evaluate → write numeric values)
    # This MUST happen before any structural transformation
    formula_cols = [4, 5, 6]  # D, E, F - as specified by task
    replace_formulas_with_values(ws, ws_data, min_row, max_row, formula_cols)
    # Now ALL cells in D-F contain plain numeric values, not formula strings
    
    # STEP 2: Detect blocks (after formula replacement, data is plain values)
    blocks, blank_rows = find_blocks(ws, min_row, max_row, min_col, max_col)
    
    # STEP 3: Apply structural transformation to each block
    # (formulas already replaced, so sort keys are plain numbers)
    for block_start, block_end in blocks:
        sort_block(ws, block_start, block_end, 
                   sort_col=4, min_col=min_col, max_col=max_col,
                   descending=True)
    
    # Save
    wb.save(output_path)
```

## Verification Checklist

After generating output, verify:
- [ ] Transformation applied correctly (spot-check a few rows)
- [ ] Formulas replaced with numeric values (no formula strings remain)
- [ ] Block boundaries preserved (blank rows in correct positions)
- [ ] Sort order correct (descending/ascending as specified)
- [ ] Stable sort maintained (ties preserve original order)
- [ ] Other sheets unchanged
- [ ] Values outside transformation range unchanged
- [ ] Column widths preserved
- [ ] Row heights preserved
- [ ] Sheet views/panes preserved
- [ ] Merged ranges preserved
- [ ] Auto filters preserved
