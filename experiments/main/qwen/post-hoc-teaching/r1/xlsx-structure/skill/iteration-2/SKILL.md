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
3. **Evaluate formulas** to numeric values where required.
4. **Detect the workbook topology** (blocks, sheets, ranges, headers, style-marked regions).
5. **Apply the transformation** (sort, filter, compact, append, extract, transpose, reconcile).
6. **Preserve all constraints** (styles, dimensions, other sheets, etc.).
7. **Save the output** to the specified path.

## ⚠ Critical Principles

### 1. Evaluate Before Transform

**Never let a structural transformation (sort, filter, transpose, compact) operate on cells that still contain unevaluated formulas.**

The correct pipeline order is:
1. **Evaluate & replace** all formulas → numeric values (snapshot pattern)
2. **Detect** topology (blocks, headers, ranges, style-marked regions)
3. **Transform** (sort, filter, compact, transpose, etc.)

If you transform first, formula strings get moved to new positions. Subsequent evaluation may fail when formulas have cross-column dependencies (e.g., F=`D+E` where D is also a formula). After replacement, all cells are plain numbers — transformations become trivial data moves.

### 2. Preserve What You Don't Touch

openpyxl preserves most workbook state automatically when you only modify cell values within a defined range. Always:
- Don't touch other sheets
- Don't modify values outside the transformation range
- Capture and restore styles/row heights on rows you move (sorting, filtering)
- Preserve blank row separators between blocks

### 3. Check for Merged Cells Before Transformation

**Before transforming, check for merged cells within the transformation range.** If merged cells exist in the range being sorted or filtered, you must unmerge them first. Otherwise:
- `capture_row` will capture `None` for non-anchor cells in merged ranges
- `restore_row` will crash with `AttributeError: 'MergedCell' object attribute 'value' is read-only` when writing to non-anchor cells

See **Pattern 11: Merged Cell Handling** for the solution.

## Environment Setup

```python
import openpyxl
from copy import copy
import re

# Load with formulas (for structure, styles, formula text)
wb = openpyxl.load_workbook('input.xlsx')

# Load data_only (for cached/computed formula values)
wb_data = openpyxl.load_workbook('input.xlsx', data_only=True)

# Identify target sheet and range from task instruction
ws = wb['Sheet1']  # or as specified
ws_data = wb_data['Sheet1']
```

## Core Patterns

### 1. Formula Evaluation (Unified Snapshot Pattern)

All formula evaluation uses a single unified approach with dependency resolution. This handles both cached values (Excel-saved files) and missing caches (programmatically generated files).

```python
def replace_formulas_in_range(ws, ws_data, min_row, max_row, columns):
    """Replace formula cells with evaluated numeric values.
    
    Evaluates column-by-column with snapshot for dependency resolution.
    This handles cases where column F references column D (also a formula).
    """
    snapshot = {}
    
    # Evaluate column by column (order matters for dependencies)
    for c in columns:
        for r in range(min_row, max_row + 1):
            cell = ws.cell(row=r, column=c)
            val = cell.value
            
            if val is None:
                continue
            
            # Check if it's a formula
            is_formula = (cell.data_type == 'f' or 
                         (isinstance(val, str) and val.startswith('=')))
            
            if is_formula:
                evaluated = evaluate_formula_cell(ws, ws_data, r, c, val, snapshot)
                snapshot[(r, c)] = evaluated
    
    # Apply all evaluated values
    for (r, c), val in snapshot.items():
        ws.cell(row=r, column=c).value = val

def evaluate_formula_cell(ws, ws_data, row, col, formula_str, snapshot):
    """Evaluate a formula cell using cached values or manual evaluation."""
    cell = ws.cell(row=row, column=col)
    
    # Try cached value first (fastest, most reliable)
    if cell.data_type == 'f':
        cached = ws_data.cell(row=row, column=col).value
        if cached is not None:
            return cached
    
    # Manual evaluation with snapshot for dependencies
    expr = formula_str[1:]  # Remove leading '='
    
    def replace_ref(match):
        ref = match.group(0)
        col_letters = ''.join(c for c in ref if c.isalpha())
        row_num = int(''.join(c for c in ref if c.isdigit()))
        col_idx = openpyxl.utils.column_index_from_string(col_letters)
        
        # Check snapshot first (already-evaluated formulas)
        if (row_num, col_idx) in snapshot:
            return str(snapshot[(row_num, col_idx)])
        
        # Then check cached values
        val = ws_data.cell(row=row_num, column=col_idx).value
        if val is not None:
            return str(val)
        
        return '0'
    
    expr = re.sub(r'[A-Z]+\d+', replace_ref, expr)
    
    try:
        return eval(expr, {"__builtins__": {}}, {})
    except:
        return formula_str  # Return original if evaluation fails
```

**Why this works**: Column-by-column evaluation with snapshot ensures that when F's formula references D (also a formula), D's evaluated value is already in the snapshot. This handles dependency chains without requiring multiple passes.

**Scope limitation**: The manual evaluator handles simple arithmetic with single-cell references only (e.g., `=B1+C1`, `=D1+E1`). It does NOT handle:
- Range references: `=SUM(A1:A5)` → regex leaves `SUM(:)` → eval crashes
- Absolute references: `=$B$1+C1` → regex strips `$B$` → wrong result
- Functions: `=MAX(B1,C1)`, `=IF(A1>0,B1,C1)` → eval crashes

When manual evaluation fails, the function returns the formula string unchanged. **If cached values are absent (programmatically generated xlsx) and formulas use functions or range references, the evaluation will silently fail.** In such cases:
1. Log a warning about the unsupported formula pattern
2. Consider whether the task requires a different evaluation strategy
3. For v01-style tasks with simple arithmetic formulas, the manual evaluator is sufficient

### 2. Block Detection

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

### 3. Row Capture and Restoration

When moving rows (sorting, filtering), capture all row attributes and restore them at new positions:

```python
def capture_row(ws, row, min_col, max_col):
    """Capture all attributes of a row for later restoration."""
    row_data = {
        'values': [ws.cell(row=row, column=c).value for c in range(min_col, max_col + 1)],
        'styles': {},
        'height': ws.row_dimensions[row].height if row in ws.row_dimensions else None,
    }
    for c in range(min_col, max_col + 1):
        cell = ws.cell(row=row, column=c)
        row_data['styles'][c] = {
            'font': copy(cell.font),
            'fill': copy(cell.fill),
            'border': copy(cell.border),
            'alignment': copy(cell.alignment),
            'number_format': cell.number_format,
        }
    return row_data

def restore_row(ws, target_row, row_data, min_col, max_col):
    """Restore a captured row at a new position."""
    for c_idx, c in enumerate(range(min_col, max_col + 1)):
        cell = ws.cell(row=target_row, column=c)
        cell.value = row_data['values'][c_idx]
        style = row_data['styles'][c]
        cell.font = style['font']
        cell.fill = style['fill']
        cell.border = style['border']
        cell.alignment = style['alignment']
        cell.number_format = style['number_format']
    if row_data['height'] is not None:
        ws.row_dimensions[target_row].height = row_data['height']
```

### 4. Block-Local Sorting

Sort rows within each block by a specified column's numeric value:

```python
def sort_block(ws, block_start, block_end, sort_col, min_col, max_col, descending=True):
    """Sort rows within a block by numeric value of sort_col."""
    # Capture all rows
    rows_data = []
    for r in range(block_start, block_end + 1):
        row_info = capture_row(ws, r, min_col, max_col)
        row_info['sort_key'] = ws.cell(row=r, column=sort_col).value
        rows_data.append(row_info)
    
    # Stable sort by numeric value
    rows_data.sort(
        key=lambda x: x['sort_key'] if x['sort_key'] is not None else float('-inf'),
        reverse=descending
    )
    
    # Restore sorted rows
    for i, rd in enumerate(rows_data):
        restore_row(ws, block_start + i, rd, min_col, max_col)
```

**Stable sort**: Python's `list.sort()` is stable. When two rows have the same sort key, their original relative order is preserved.

### 5. Filtering and Compaction

Filter rows based on predicates, optionally compacting (removing blanks):

```python
def filter_and_compact_block(ws, block_start, block_end, predicate, min_col, max_col):
    """Filter rows within a block based on a predicate, compacting results.
    
    Returns list of (original_row, row_data) for kept rows.
    """
    kept_rows = []
    for r in range(block_start, block_end + 1):
        row_data = capture_row(ws, r, min_col, max_col)
        if predicate(row_data['values'], r):
            kept_rows.append((r, row_data))
    return kept_rows

def write_compacted_rows(ws, start_row, kept_rows, min_col, max_col):
    """Write filtered rows starting at start_row, compacting them."""
    for i, (orig_row, row_data) in enumerate(kept_rows):
        restore_row(ws, start_row + i, row_data, min_col, max_col)
    return len(kept_rows)
```

### 6. Style-Based Selection

Select rows based on cell fill color or other style attributes:

```python
def get_fill_color(ws, row, col):
    """Get the fill color of a cell as a hex string or None."""
    cell = ws.cell(row=row, column=col)
    fill = cell.fill
    if fill and fill.start_color:
        # start_color can be a Color object or a string
        color = fill.start_color
        if hasattr(color, 'rgb') and color.rgb:
            return color.rgb
        elif hasattr(color, 'indexed') and color.indexed is not None:
            return f'indexed:{color.indexed}'
        elif hasattr(color, 'theme') and color.theme is not None:
            return f'theme:{color.theme}'
    return None

def select_rows_by_style(ws, min_row, max_row, style_col, target_color):
    """Select rows where the style_col cell has the target fill color."""
    selected = []
    for r in range(min_row, max_row + 1):
        color = get_fill_color(ws, r, style_col)
        if color == target_color:
            selected.append(r)
    return selected
```

### 7. ID-Based Alignment

Match rows across ranges by ID column for reconciliation or alignment:

```python
def build_id_map(ws, id_col, min_row, max_row):
    """Build a map from ID value to row number."""
    id_map = {}
    for r in range(min_row, max_row + 1):
        id_val = ws.cell(row=r, column=id_col).value
        if id_val is not None:
            id_map[id_val] = r
    return id_map

def align_by_id(ws_source, ws_dest, source_id_col, dest_id_col, 
                source_range, dest_range, columns_to_copy):
    """Copy data from source to dest, matching rows by ID."""
    source_ids = build_id_map(ws_source, source_id_col, *source_range)
    dest_ids = build_id_map(ws_dest, dest_id_col, *dest_range)
    
    for id_val, source_row in source_ids.items():
        if id_val in dest_ids:
            dest_row = dest_ids[id_val]
            # Copy specified columns
            for col in columns_to_copy:
                ws_dest.cell(row=dest_row, column=col).value = \
                    ws_source.cell(row=source_row, column=col).value
```

### 8. Header Detection and Mapping

When columns are identified by header names rather than positions:

```python
def find_header_row(ws, min_row=1, max_row=10, min_col=1, max_col=20):
    """Find the row that contains column headers."""
    for r in range(min_row, max_row + 1):
        non_empty = sum(1 for c in range(min_col, max_col + 1) 
                       if ws.cell(row=r, column=c).value is not None)
        if non_empty >= 2:
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

### 9. Header-Aligned Append

Append rows to a destination table, aligning columns by header names:

```python
def append_with_header_alignment(ws_source, ws_dest, source_header_row, 
                                  dest_header_row, source_data_start, 
                                  min_col, max_col):
    """Append source rows to dest, aligning columns by header names."""
    # Build header maps
    source_map = build_header_map(ws_source, source_header_row, min_col, max_col)
    dest_map = build_header_map(ws_dest, dest_header_row, min_col, max_col)
    
    # Find destination append position
    dest_row = ws_dest.max_row + 1
    
    # Copy source rows, aligning by header
    for source_row in range(source_data_start, ws_source.max_row + 1):
        for header_name, source_col in source_map.items():
            if header_name in dest_map:
                dest_col = dest_map[header_name]
                ws_dest.cell(row=dest_row, column=dest_col).value = \
                    ws_source.cell(row=source_row, column=source_col).value
        dest_row += 1
```

### 10. Transposition

Transpose data (rows ↔ columns):

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

### 11. Merged Cell Handling

When merged cells exist within the transformation range, they must be unmerged before sorting or filtering. Otherwise:
- `capture_row` captures `None` for non-anchor cells in merged ranges
- `restore_row` crashes with `AttributeError: 'MergedCell' object attribute 'value' is read-only`

```python
def unmerge_in_range(ws, min_row, max_row, min_col, max_col):
    """Unmerge any merged ranges that overlap the given range.
    
    Call this BEFORE capture_row/sort_block/restore_row.
    The merged ranges are dissolved, so each cell becomes independently writable.
    The anchor cell retains its value; non-anchor cells become None.
    If you need the merged value to appear in every unmerged cell,
    fill it in after unmerging.
    
    Returns list of unmerged range strings for reference.
    """
    from openpyxl.utils import range_boundaries
    to_unmerge = []
    for mr in list(ws.merged_cells.ranges):
        mr_min_col, mr_min_row, mr_max_col, mr_max_row = range_boundaries(str(mr))
        # Check if this merged range overlaps our transformation range
        if (mr_min_row <= max_row and mr_max_row >= min_row and
            mr_min_col <= max_col and mr_max_col >= min_col):
            to_unmerge.append(str(mr))
    
    for mr_str in to_unmerge:
        ws.unmerge_cells(mr_str)
    return to_unmerge

def fill_merged_values(ws, unmerged_ranges):
    """After unmerging, fill each cell with the anchor cell's value.
    
    Call this after unmerge_in_range if the task semantics require
    that every cell in the former merged range has the same value.
    """
    from openpyxl.utils import range_boundaries
    for mr_str in unmerged_ranges:
        min_col, min_row, max_col, max_row = range_boundaries(mr_str)
        anchor_val = ws.cell(row=min_row, column=min_col).value
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                if r != min_row or c != min_col:  # Skip anchor
                    ws.cell(row=r, column=c).value = anchor_val
```

**Usage pattern**: Before sorting or filtering a range that may contain merged cells:
```python
# 1. Unmerge overlapping ranges
unmerged = unmerge_in_range(ws, min_row, max_row, min_col, max_col)

# 2. Optionally fill values (depends on task semantics)
# fill_merged_values(ws, unmerged)

# 3. Now safe to capture/restore rows
sort_block(ws, ...)
```

## Decision Framework

When approaching a new xlsx-structure task:

1. **Identify the transformation type** from the instruction:
   - Sorting → use block-local sorting (Pattern 4)
   - Filtering → use predicate-based filtering (Pattern 5)
   - Compaction → filter + recompact (Pattern 5)
   - Append → find end of data, use header-aligned append (Pattern 9)
   - Extraction → copy specific rows/cells to destination
   - Transposition → swap row/column indices (Pattern 10)
   - Reconciliation → use ID-based alignment (Pattern 7)

2. **Identify the topology**:
   - Single sheet with blocks → detect blank-row separators (Pattern 2)
   - Multiple sheets → identify source and destination sheets
   - Header-mapped columns → find header row, build column map (Pattern 8)
   - Style-marked regions → scan for fill colors (Pattern 6)
   - ID-based alignment → match rows by ID column (Pattern 7)

3. **Identify the selection rule**:
   - Numeric order → evaluate and sort
   - Membership → check against a list/set
   - Header identity → match column names
   - Fill color → check cell.fill (Pattern 6)
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

1. **CRITICAL — Operation ordering**: Always evaluate and replace formulas BEFORE any structural transformation. The correct order: (1) replace formulas with values, (2) detect topology, (3) apply transformation.

2. **Formula dependency chains**: When column F's formula references column D (also a formula), use the unified snapshot pattern (Pattern 1) which evaluates column-by-column with dependency resolution.

3. **No cached values**: When xlsx files are generated programmatically (not saved by Excel), `data_only=True` returns `None` for formula cells. The snapshot pattern handles this via manual evaluation with dependency resolution.

4. **Floating point precision**: Excel arithmetic may produce floating-point artifacts (e.g., `-0.2999999999999972` instead of `-0.3`). This is expected and correct - don't round unless the task specifies it.

5. **Stable sort**: Always use stable sort when the task says "preserve original relative order" for ties. Python's `sort()` is stable by default.

6. **Block boundary detection**: Don't assume fixed block sizes. Detect boundaries from the actual data (blank rows).

7. **Style and row height preservation**: When moving rows (sorting, filtering), use the capture/restore pattern (Pattern 3) to preserve styles and row heights.

8. **Blank row preservation**: When sorting within blocks, maintain exactly one blank row between adjacent blocks. Don't accidentally merge or duplicate blank separators.

9. **Data type awareness**: Check `cell.data_type` to distinguish between formulas ('f'), numbers ('n'), strings ('s'), and booleans ('b'). A string starting with '=' might be a formula stored as text.

10. **Style-based selection**: When selecting by fill color, check both `fill.start_color.rgb` and theme/indexed colors. The exact attribute depends on how the color was set.

11. **Merged cells in transformation range**: Before sorting or filtering, check for merged cells within the range. Use `unmerge_in_range` (Pattern 11) to dissolve them. Otherwise `capture_row` captures `None` for non-anchor cells and `restore_row` crashes with `AttributeError`.

12. **auto_filter string crash**: Never use `str(ws.auto_filter)` or `print(ws.auto_filter)`. When `auto_filter.ref` is `None`, the `__str__` method crashes with `TypeError: expected string or bytes-like object, got 'NoneType'`. Instead, check `ws.auto_filter.ref` directly:
    ```python
    af_ref = ws.auto_filter.ref if ws.auto_filter and ws.auto_filter.ref else None
    ```

13. **Formula evaluation scope**: The manual evaluator handles simple arithmetic with single-cell references only. It does NOT handle range references (`SUM(A1:A5)`), absolute references (`$A$1`), or functions (`MAX`, `IF`). When manual evaluation fails, the formula string is returned unchanged. If cached values are absent and formulas use unsupported patterns, the evaluation silently fails. For such cases, consider whether the task requires a different strategy.

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
    min_row, max_row = 1, 85  # as specified in task
    min_col, max_col = 1, 8   # A-H, as specified
    
    # STEP 1: Replace formulas FIRST (evaluate → write numeric values)
    # This MUST happen before any structural transformation
    formula_cols = [4, 5, 6]  # D, E, F - as specified by task
    replace_formulas_in_range(ws, ws_data, min_row, max_row, formula_cols)
    # Now ALL cells in formula_cols contain plain numeric values
    
    # STEP 2: Detect topology (after formula replacement)
    blocks, blank_rows = find_blocks(ws, min_row, max_row, min_col, max_col)
    
    # STEP 3: Apply structural transformation
    # Example: Sort each block by column D descending
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
- [ ] Sort/filter order correct (descending/ascending, predicate logic)
- [ ] Stable sort maintained (ties preserve original order)
- [ ] Other sheets unchanged
- [ ] Values outside transformation range unchanged
- [ ] Column widths preserved
- [ ] Row heights preserved
- [ ] Sheet views/panes preserved
- [ ] Merged ranges preserved
- [ ] Auto filters preserved
- [ ] Styles preserved on moved rows
