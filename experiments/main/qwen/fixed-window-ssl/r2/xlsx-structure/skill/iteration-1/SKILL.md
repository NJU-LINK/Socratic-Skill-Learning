---
name: xlsx-structure
description: >
  Perform structural transformations on Excel (.xlsx) workbooks using openpyxl:
  block-local sorting, predicate/style-based filtering, header-aligned append,
  sparse-record reconciliation, row extraction, and layout transposition.
  Handles formula evaluation, style preservation, block detection from blank-row
  separators, and multi-sheet workbook state conservation.
---

# xlsx-structure

## Overview

This skill covers structural transformations on `.xlsx` workbooks where the task
requires reading data from one or more sheets, applying a structural operation
(sort, filter, reorder, extract, transpose, append, reconcile), and writing the
result while preserving all unrelated workbook state (other sheets, styles,
merged ranges, column widths, row heights, filters, panes).

## Core Architecture: Dual-Workbook Pattern

The fundamental challenge is that openpyxl cannot simultaneously provide
**evaluated formula values** and **writable style information** from a single
load. The solution is the dual-workbook pattern:

```python
import openpyxl
from copy import copy

# Load twice: one for evaluated values, one for styles/writing
wb_data = openpyxl.load_workbook('input.xlsx', data_only=True)
ws_data = wb_data['SheetName']

wb = openpyxl.load_workbook('input.xlsx')
ws = wb['SheetName']
```

- `wb_data` (data_only=True): returns cached numeric values that Excel computed
  when the file was last saved. Use this for reading values that drive decisions
  (sort keys, filter predicates, etc.).
- `wb` (normal): retains formula strings and all style objects. Use this for
  reading/writing styles and as the workbook you save.

**When data_only returns None**: If the workbook was never opened in Excel (e.g.,
created by a library that doesn't cache values), `data_only=True` will return
None for formula cells. In that case, fall back to manual formula evaluation:
parse the formula string (e.g., `=B1+C1`) and compute using values from the
data_only workbook or the normal workbook for literal cells.

## Formula Evaluation Strategies

### Strategy 1: Cached Values (Preferred)
```python
wb_data = openpyxl.load_workbook('input.xlsx', data_only=True)
value = wb_data['Sheet1'].cell(row=1, column=4).value  # Returns 230.0, not '=B1+C1'
```
Works when the file was last saved by Excel or a library that evaluates formulas.

### Strategy 2: Manual Row-Local Evaluation
For formulas that reference only cells within the same row:
```python
import re

def resolve_row_values(raw_values):
    """Resolve all text formulas in a row to numeric values.
    Handles chains: if F='=D+E' and D='=B+C', resolves D first."""
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
            expr = val[1:]  # strip '='
            def replace_ref(match):
                col_letter = match.group(1)
                ref_col = ord(col_letter.upper()) - ord('A') + 1
                return str(resolve(ref_col))
            expr = re.sub(r'([A-Za-z]+)\d+', replace_ref, expr)
            try:
                result = eval(expr)
            except Exception:
                result = val
            resolved[col_idx] = result
        else:
            resolved[col_idx] = val if val is not None else 0
        
        resolving.discard(col_idx)
        return resolved[col_idx]
    
    for col_idx in list(raw_values.keys()):
        resolve(col_idx)
    return resolved
```

### Strategy 3: Dual-Source Reading (Recommended)
Read from both workbooks and pick the right value. This handles all three cases:
1. Real formulas with cached values → use numeric from data_ws
2. Real formulas without cached values → use formula string from ws, resolve it
3. Text formulas (strings stored as text) → resolve them

```python
raw_values = {}
for col_idx in range(min_col, max_col + 1):
    data_val = ws_data.cell(row=row_idx, column=col_idx).value
    norm_val = ws.cell(row=row_idx, column=col_idx).value
    
    if data_val is not None and not (isinstance(data_val, str) and data_val.startswith('=')):
        raw_values[col_idx] = data_val  # cached numeric value
    elif isinstance(norm_val, str) and norm_val.startswith('='):
        raw_values[col_idx] = norm_val  # formula string to resolve
    else:
        raw_values[col_idx] = data_val if data_val is not None else norm_val

resolved = resolve_row_values(raw_values)
```

**Why this matters:** The spec says cells may contain "formulas or text that
represents formulas." When openpyxl writes `'=B1+C1'`, it stores it as a real
formula. If the workbook was never opened in Excel, `data_only=True` returns
`None` for that cell, but the normal workbook returns the formula string.
Without dual-source reading, you'd see `None` instead of the formula, and
`resolve_row_values` would treat it as 0 — a silent correctness bug.

## Block Detection

Many xlsx tasks involve data organized in **blocks** (contiguous non-empty rows)
separated by blank rows. Detection must use dual-source reading to avoid false
blanks when formula cells have no cached values:

```python
def detect_blocks(ws, min_row, max_row, min_col, max_col, data_ws=None):
    """Detect blocks using dual-source blank detection."""
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
            # Fall back to normal workbook (formulas)
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
```

**Key insight**: A "blank row" means ALL cells in the relevant column range are
None or empty string. A row with even one non-empty cell is part of a block.
When using dual-source reading, check both workbooks — a cell with a formula
but no cached value is NOT blank.

## Style-Preserving Row Operations

When moving/reordering rows, styles must travel with the data. Capture the full
style profile of each cell:

```python
def capture_cell_style(cell):
    """Capture all style attributes of a cell for later restoration."""
    return {
        'font': copy(cell.font),
        'fill': copy(cell.fill),
        'border': copy(cell.border),
        'alignment': copy(cell.alignment),
        'number_format': cell.number_format,
        'protection': copy(cell.protection),
    }

def apply_cell_style(cell, style):
    """Apply captured style to a cell."""
    cell.font = style['font']
    cell.fill = style['fill']
    cell.border = style['border']
    cell.alignment = style['alignment']
    cell.number_format = style['number_format']
    cell.protection = style['protection']
```

**Critical**: Use `copy()` from the `copy` module for font, fill, border,
alignment, and protection objects. Without deep copy, style objects are shared
by reference and mutations affect multiple cells.

## Complete Row Data Capture

For operations that move entire rows:

```python
def capture_row(ws, data_ws, row_idx, min_col, max_col):
    """Capture complete row data (values + styles) for later writing."""
    cells = []
    for col_idx in range(min_col, max_col + 1):
        src_cell = ws.cell(row=row_idx, column=col_idx)
        data_cell = data_ws.cell(row=row_idx, column=col_idx)
        cells.append({
            'value': data_cell.value,  # evaluated value
            **capture_cell_style(src_cell)
        })
    return cells

def write_row(ws, row_idx, cells):
    """Write captured row data to a target row position."""
    for col_offset, cell_data in enumerate(cells):
        dst = ws.cell(row=row_idx, column=col_offset + 1)  # adjust as needed
        dst.value = cell_data['value']
        apply_cell_style(dst, cell_data)
```

## Preservation Checklist

Before saving, verify these are preserved:

| Element | How Preserved |
|---------|--------------|
| Other sheets | Don't modify them; openpyxl keeps them on save |
| Column widths | Stored in `ws.column_dimensions`; not touched by cell writes |
| Row heights | Stored in `ws.row_dimensions`; not touched by cell writes |
| Merged ranges | Stored in `ws.merged_cells.ranges`; preserved unless explicitly unmerged |
| Auto filters | Stored in `ws.auto_filter`; preserved unless explicitly modified |
| Freeze panes | Stored in `ws.freeze_panes`; preserved unless explicitly modified |
| Cell styles outside transform range | Don't write to those cells |

## Transformation Patterns

### Pattern 1: Block-Local Sorting
```
For each block:
  1. Read all rows (values + styles)
  2. Sort by key column(s) with specified order
  3. Write sorted rows back to same positions
```
- Use Python's stable `sorted()` / `list.sort()` for tie-breaking
- `reverse=True` for descending order
- Sort key should use **evaluated numeric values**, not formula strings

### Pattern 2: Predicate-Based Filtering/Compaction
```
For each block (or the whole range):
  1. Read all rows
  2. Filter by predicate (value condition, style condition, etc.)
  3. Write filtered rows compactly (no gaps) or to specified destination
```

### Pattern 3: Header-Aligned Append
```
1. Read source data and destination header row
2. Map source columns to destination columns by header name
3. Append source rows to destination, aligning by header mapping
```

### Pattern 4: ID-Based Reconciliation
```
1. Read ID list from one range
2. Read data table from another range
3. For each ID, find matching row (or mark missing)
4. Write reconciled output
```

### Pattern 5: Layout Transposition
```
1. Read source block
2. Transpose: rows become columns, columns become rows
3. Write to destination range
```

## Implementation Template

```python
import openpyxl
from copy import copy

def solve(input_path, output_path):
    # 1. Load dual workbooks
    wb_data = openpyxl.load_workbook(input_path, data_only=True)
    wb = openpyxl.load_workbook(input_path)
    
    # 2. Identify sheets and ranges from task description
    ws_data = wb_data['SheetName']
    ws = wb['SheetName']
    
    # 3. Detect structure (blocks, headers, etc.)
    # ... varies by task
    
    # 4. Read source data with evaluated values
    # ... varies by task
    
    # 5. Apply transformation
    # ... varies by task (sort, filter, transpose, etc.)
    
    # 6. Write results preserving styles
    # ... varies by task
    
    # 7. Save
    wb.save(output_path)
```

## Common Pitfalls

1. **Sorting by formula string instead of evaluated value**: `'=B1+C1'` sorts
   lexically, not numerically. Always use evaluated values for sort keys.

2. **Text formulas masquerading as values**: A cell may contain the string
   `"=B1+C1"` as a literal value (not an actual Excel formula). `data_only=True`
   returns this string unchanged. You MUST detect strings starting with `=` and
   evaluate them manually. Without this, sort keys become strings and comparisons
   are lexical — a silent correctness bug.

3. **Formula chains in text formulas**: If cell F1 contains `"=D1+E1"` and D1
   contains `"=B1+C1"`, you must resolve D1 before evaluating F1. Use recursive
   resolution with cycle detection, not single-pass evaluation.

4. **Losing styles on row moves**: If you only copy `.value`, all formatting is
   lost. Always copy font, fill, border, alignment, number_format.

5. **Breaking blank-row separators**: When sorting within blocks, never move
   blank separator rows. Detect blocks first, sort within each block independently.

6. **Floating point display**: Evaluated values like `224.89999999999998` are
   correct — they're what Excel computes. Don't round unless the task says to.

7. **Overwriting cells outside the transform range**: Only write to cells within
   the specified output range. Everything else must remain untouched.

8. **Assuming fixed block sizes**: Always detect block boundaries from the
   workbook data rather than hardcoding row counts.

9. **Forgetting `data_only=True`**: Without it, formula cells return the formula
   string, not the computed value. This breaks sorting, filtering, and any
   numeric comparison.

## Verification Procedure

After generating output, always verify:

1. **No formulas remain** in the output range (if task requires evaluation)
2. **Sort order is correct** within each block (print key column values)
3. **Blank separators preserved** at correct positions
4. **Styles intact** on a sample of cells (spot-check bold, alignment, etc.)
5. **Column widths preserved** (compare to input)
6. **Other sheets unchanged** (check sheet names and spot-check values)
7. **Row count unchanged** (total rows in output range = total rows in input range)
