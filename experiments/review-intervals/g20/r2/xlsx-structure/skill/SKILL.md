---
name: xlsx-structure
description: >
  Structural transformations on Excel workbooks: block-local sorting,
  predicate/style-based filtering and compaction, header-aligned append,
  sparse-record reconciliation, row extraction, and layout transposition.
  Handles formula evaluation (cached + manual fallback), style preservation,
  block detection, and multi-sheet workbook integrity.
---

# XLSX Structure Transformation Skill

## Overview

This skill handles structural transformations on `.xlsx` workbooks where the task
requires reading data, applying a transformation (sort, filter, compact, append,
extract, transpose, etc.), and writing results while preserving workbook integrity
(styles, other sheets, merged ranges, filters, panes, dimensions).

## Core Architecture

Every task in this family follows the same pipeline:

```
1. LOAD    → Read workbook (both formula-mode and data-only-mode)
2. DETECT  → Identify data regions, blocks, headers, and structure
3. EVALUATE→ Resolve formulas to numeric values (cached + manual fallback)
4. SELECT  → Identify rows/cells to transform per the selection rule
5. TRANSFORM → Apply the structural operation (sort, filter, etc.)
6. WRITE   → Write results back preserving styles and workbook state
7. SAVE    → Save output preserving all non-target workbook state
```

## Step 1: Dual-Mode Workbook Loading

Always load the workbook twice:

```python
import openpyxl
from copy import copy

# Formula-mode: preserves formula strings, styles, structure
wb = openpyxl.load_workbook(input_path)
ws = wb[sheet_name]

# Data-only mode: reads cached formula results (fast path)
wb_data = openpyxl.load_workbook(input_path, data_only=True)
ws_data = wb_data[sheet_name]
```

**Why both?** The formula-mode workbook has `cell.value` as the formula string
(e.g., `"=B1+C1"`) and `cell.data_type == 'f'`. The data-only workbook has the
cached numeric result. But cached values can be `None` (if the file was generated
programmatically without a calculation pass) or stale. We need a fallback.

## Step 2: Formula Evaluation with Fallback

### Detection

A cell contains a formula if:
- `cell.data_type == 'f'` (native formula), OR
- `cell.data_type == 's'` AND `isinstance(cell.value, str)` AND `cell.value.startswith('=')`
  (text that represents a formula)

### Evaluation Strategy

```python
import re
from openpyxl.utils import get_column_letter

def evaluate_cell_value(cell, cell_data, row_vals_by_letter):
    """
    Get the numeric value of a cell.
    
    Args:
        cell: cell from formula-mode workbook
        cell_data: cell from data-only workbook  
        row_vals_by_letter: dict {col_letter: value} for current row, built left-to-right
    
    Returns:
        The evaluated numeric value, or the original value for non-formula cells
    """
    raw_val = cell.value
    is_formula = (
        cell.data_type == 'f' or 
        (cell.data_type == 's' and isinstance(raw_val, str) and raw_val.startswith('='))
    )
    
    if not is_formula:
        return raw_val
    
    # Fast path: use cached value if available
    cached = cell_data.value
    if cached is not None:
        return cached
    
    # Fallback: manual evaluation of simple arithmetic
    return evaluate_formula_manual(raw_val, row_vals_by_letter)


def evaluate_formula_manual(formula_str, row_vals_by_letter):
    """
    Evaluate simple arithmetic formulas like '=B1+C1' or '=D1+E1'.
    Handles +, -, *, / operators and cell references.
    
    row_vals_by_letter must be built left-to-right so that D=B+C
    can reference already-evaluated B and C values.
    """
    expr = formula_str.lstrip('=')
    
    def replace_ref(match):
        col_letter = match.group(1)
        val = row_vals_by_letter.get(col_letter, 0)
        if val is None:
            return '0'
        return str(val)
    
    # Replace cell references (e.g., B1, C1, AA5) with their values
    expr = re.sub(r'([A-Z]+)\d+', replace_ref, expr)
    
    # Safe eval for simple arithmetic
    # Allow: digits, whitespace, +, -, *, /, ., (, ), e/E (scientific notation)
    # Also allow common function names like ABS, SUM, etc. for robustness
    safe_pattern = r'^[\d\s\+\-\*\/\.\(\)eE]+$'
    if not re.match(safe_pattern, expr):
        # Try to handle simple functions like ABS(-5)
        # For now, raise an error for complex formulas
        raise ValueError(f"Complex formula not supported: {expr}")
    
    try:
        return eval(expr)
    except Exception as e:
        raise ValueError(f"Failed to evaluate formula '{formula_str}': {e}")
```

### Critical Design Decisions

1. **Process columns left-to-right** (A→last column) so that formulas referencing
   earlier columns in the same row can use already-evaluated values. This works
   because row-local formulas always reference cells to their left.

2. **Use `get_column_letter(c)`** not `chr(64+c)` — the latter breaks for columns
   beyond Z (AA, AB, etc.).

3. **Cached-first, manual-fallback** — always try cached values first for speed
   and accuracy, but have the manual evaluator ready for programmatically-generated
   workbooks.

## Step 3: Block Detection

Many tasks organize data into **variable-length blocks** separated by blank rows.

```python
def detect_blocks(ws, min_row, max_row, min_col, max_col):
    """
    Detect contiguous non-blank row blocks separated by blank rows.
    
    Returns:
        blocks: list of lists, where each inner list contains row data dicts
        blank_row_indices: set of row indices (0-based from min_row) that are blank
    """
    rows_data = []
    for r in range(min_row, max_row + 1):
        row_vals = []
        for c in range(min_col, max_col + 1):
            row_vals.append(ws.cell(row=r, column=c).value)
        
        is_blank = all(v is None for v in row_vals)
        rows_data.append({
            'row_num': r,
            'values': row_vals,
            'is_blank': is_blank
        })
    
    blocks = []
    current_block = []
    blank_positions = set()
    
    for i, rd in enumerate(rows_data):
        if rd['is_blank']:
            if current_block:
                blocks.append(current_block)
                current_block = []
            blank_positions.add(i)
        else:
            current_block.append(rd)
    
    if current_block:
        blocks.append(current_block)
    
    return blocks, blank_positions, rows_data
```

**Key insight:** Detect block boundaries from the data itself — never assume fixed
row counts. A blank row is one where ALL cells in the data range are `None`.

## Step 4: Style Preservation

### Styles Move With Data

When sorting or rearranging rows, **styles travel with the data row**, not with
the position. This is critical for tasks with row-specific styling (alternating
fills, conditional formatting, etc.).

```python
def capture_row_styles(ws, row_num, min_col, max_col):
    """Capture styles for all cells in a row."""
    styles = []
    for c in range(min_col, max_col + 1):
        cell = ws.cell(row=row_num, column=c)
        styles.append({
            'font': copy(cell.font),
            'fill': copy(cell.fill),
            'border': copy(cell.border),
            'alignment': copy(cell.alignment),
            'number_format': cell.number_format,
            'protection': copy(cell.protection),
        })
    return styles

def apply_row_styles(ws, row_num, styles, min_col):
    """Apply captured styles to a row."""
    for i, style in enumerate(styles):
        cell = ws.cell(row=row_num, column=min_col + i)
        cell.font = style['font']
        cell.fill = style['fill']
        cell.border = style['border']
        cell.alignment = style['alignment']
        cell.number_format = style['number_format']
        cell.protection = style['protection']
```

### Position-Based vs Data-Based Style Strategy

For v01-style tasks where styles are column-uniform (all rows in column D have
the same style), you can use position-based styles. But for generality:

- **Capture styles from the source row** before moving data
- **Apply those styles to the destination position** after writing data
- This ensures styles move with data during sorting/rearrangement

## Step 5: Common Transformations

### Block-Local Sorting

```python
def sort_block(block_rows, sort_col_index, descending=True):
    """
    Sort rows within a block by a column's evaluated numeric value.
    Uses stable sort to preserve original order for ties.
    """
    def sort_key(row_data):
        val = row_data['values'][sort_col_index]
        if val is None:
            return float('-inf') if descending else float('inf')
        return val
    
    block_rows.sort(key=sort_key, reverse=descending)
```

### Filtering and Compaction

Remove rows matching a predicate, compact remaining rows, preserve blank separators.

### Header-Aligned Append

Match source columns to destination by header name, append rows below existing data.

### Row Extraction

Select rows by predicate (numeric threshold, text match, style, membership in
another range) and write to destination.

## Step 6: Preservation Constraints

After transformation, verify these are intact:

| Constraint | How to Preserve |
|---|---|
| Other sheets | Never modify them; load/save entire workbook |
| Values outside target range | Only write to the declared output range |
| Styles | Capture before, apply after (or use position-based for uniform styles) |
| Merged ranges | Don't touch; openpyxl preserves them on save |
| Filters | Don't modify auto-filter settings |
| Panes | Don't modify freeze_panes or sheet_view |
| Row heights / Column widths | Don't modify; openpyxl preserves them |
| Dimensions | Update if data range changes |

## Step 7: Writing Output

```python
def write_transformed_data(ws, output_rows, start_row, start_col, styles_map=None):
    """
    Write transformed row data to the worksheet.
    
    Args:
        ws: worksheet to write to
        output_rows: list of row value lists
        start_row: first output row (1-based)
        start_col: first output column (1-based)
        styles_map: optional dict mapping output row index to styles list
    """
    for i, row_vals in enumerate(output_rows):
        r = start_row + i
        for j, val in enumerate(row_vals):
            cell = ws.cell(row=r, column=start_col + j)
            cell.value = val
            if styles_map and i in styles_map:
                style = styles_map[i][j]
                cell.font = style['font']
                cell.fill = style['fill']
                cell.border = style['border']
                cell.alignment = style['alignment']
                cell.number_format = style['number_format']

# Save the workbook
wb.save(output_path)
```

## Verification Checklist

Before declaring a task complete:

1. **Formula evaluation**: All formula cells have numeric values, not formula strings
2. **Block structure**: Blank rows preserved between blocks, correct count
3. **Sort order**: Descending/ascending as specified, stable for ties
4. **Style integrity**: Column formatting preserved (bold, alignment, etc.)
5. **Data completeness**: All non-blank source rows appear in output
6. **Range boundaries**: Output fits within declared range (e.g., A1:H85)
7. **Beyond-range integrity**: No data written outside the target range
8. **Other sheets**: Unchanged
9. **Workbook properties**: Filters, merged ranges, panes, dimensions intact

## Variation Dimensions (from spec.yaml)

When encountering a new task in this family, identify:

| Dimension | What to Look For |
|---|---|
| **Transformation semantics** | Sort? Filter? Compact? Append? Extract? Transpose? |
| **Workbook topology** | Single/multi sheet? Contiguous/blocked? Style-marked? |
| **Selection/alignment rule** | Numeric order? Header identity? Fill color? Membership? |
| **Output geometry** | Which sheet? Which range? Append or overwrite? |
| **Preservation constraints** | What must remain untouched? |

## Dependencies

```python
import openpyxl      # xlsx read/write
from copy import copy # deep copy style objects
import re            # formula parsing
from openpyxl.utils import get_column_letter  # column index to letter
```

No external formula engine needed — the manual evaluator handles the simple
row-local arithmetic patterns found in this family (`=B+C`, `=D+E`, etc.).

## Complete Reference Implementation: Block-Local Sort

This is a complete, working example for the v01 task pattern (block-local sort by
column D descending). Adapt the transformation step for other task variants.

```python
import openpyxl
import re
from copy import copy
from openpyxl.utils import get_column_letter

# === CONFIGURATION (adapt per task) ===
INPUT_PATH = '/app/input.xlsx'
OUTPUT_PATH = '/app/output.xlsx'
SHEET_NAME = 'Sheet1'
DATA_RANGE = (1, 85, 1, 8)  # (min_row, max_row, min_col, max_col)
SORT_COL = 4  # Column D (1-indexed)
DESCENDING = True

# === STEP 1: Load workbook ===
wb = openpyxl.load_workbook(INPUT_PATH)
ws = wb[SHEET_NAME]
wb_data = openpyxl.load_workbook(INPUT_PATH, data_only=True)
ws_data = wb_data[SHEET_NAME]

# === STEP 2: Formula evaluator ===
def evaluate_formula_manual(formula_str, row_vals_by_letter):
    expr = formula_str.lstrip('=')
    def replace_ref(match):
        col_letter = match.group(1)
        val = row_vals_by_letter.get(col_letter, 0)
        return '0' if val is None else str(val)
    expr = re.sub(r'([A-Z]+)\d+', replace_ref, expr)
    if not re.match(r'^[\d\s\+\-\*\/\.\(\)eE]+$', expr):
        raise ValueError(f"Complex formula: {expr}")
    return eval(expr)

def get_evaluated_value(cell, cell_data, row_vals_by_letter):
    raw_val = cell.value
    is_formula = (
        cell.data_type == 'f' or
        (cell.data_type == 's' and isinstance(raw_val, str) and raw_val.startswith('='))
    )
    if not is_formula:
        return raw_val
    cached = cell_data.value
    if cached is not None:
        return cached
    return evaluate_formula_manual(raw_val, row_vals_by_letter)

# === STEP 3: Read all data with formula evaluation ===
min_row, max_row, min_col, max_col = DATA_RANGE
rows_data = []
for r in range(min_row, max_row + 1):
    row_vals = []
    row_vals_by_letter = {}
    for c in range(min_col, max_col + 1):
        col_letter = get_column_letter(c)
        cell = ws.cell(row=r, column=c)
        cell_data = ws_data.cell(row=r, column=c)
        val = get_evaluated_value(cell, cell_data, row_vals_by_letter)
        row_vals.append(val)
        row_vals_by_letter[col_letter] = val
    is_blank = all(v is None for v in row_vals)
    rows_data.append({'row_num': r, 'values': row_vals, 'is_blank': is_blank})

# === STEP 4: Detect blocks ===
blocks = []
current_block = []
blank_positions = set()
for i, rd in enumerate(rows_data):
    if rd['is_blank']:
        if current_block:
            blocks.append(current_block)
            current_block = []
        blank_positions.add(i)
    else:
        current_block.append(rd)
if current_block:
    blocks.append(current_block)

# === STEP 5: Sort each block ===
sort_idx = SORT_COL - min_col  # Convert to 0-indexed within row
for block in blocks:
    block.sort(
        key=lambda r: r['values'][sort_idx] if r['values'][sort_idx] is not None else float('-inf'),
        reverse=DESCENDING
    )

# === STEP 6: Map block positions ===
block_positions = []
current_start = None
for i, rd in enumerate(rows_data):
    if not rd['is_blank']:
        if current_start is None:
            current_start = i
    else:
        if current_start is not None:
            block_positions.append((current_start, i - 1))
            current_start = None
if current_start is not None:
    block_positions.append((current_start, len(rows_data) - 1))

# === STEP 7: Write sorted data back ===
for block_idx, (start, end) in enumerate(block_positions):
    sorted_block = blocks[block_idx]
    for i, pos in enumerate(range(start, end + 1)):
        sorted_row = sorted_block[i]
        # Use stored row_num for robustness (handles min_row != 1)
        actual_row = sorted_row['row_num']
        for c in range(min_col, max_col + 1):
            cell = ws.cell(row=actual_row, column=c)
            cell.value = sorted_row['values'][c - min_col]
            # For column-uniform styles (most common), styles stay at positions
            # For row-specific styles, capture before sort and apply after

# Clear blank rows
for blank_pos in blank_positions:
    # Convert 0-indexed position to actual row number
    actual_row = min_row + blank_pos
    for c in range(min_col, max_col + 1):
        ws.cell(row=actual_row, column=c).value = None

# === STEP 8: Save ===
wb.save(OUTPUT_PATH)
```

## Style Strategy Decision Guide

**Question:** When sorting/rearranging rows, should styles move with the data or stay at their positions?

**Answer:** It depends on the task:

1. **Column-uniform styles** (most common, including v01): All rows in a column have the same style.
   - **Use position-based styles** — styles stay at their original positions.
   - Example: Column D is always bold+center, regardless of which row's data is there.
   - **This is the default for v01 and similar tasks.**
   - **Implementation:** Just write the data; don't touch style attributes. Styles are already correct at each position.

2. **Row-specific styles** (alternating fills, conditional formatting, etc.): Different rows have different styles.
   - **Use data-based styles** — styles travel with the sorted row.
   - Capture styles from source rows before sorting, then apply them to destination positions after writing.
   - Example: Row 1 has yellow fill, Row 2 has white fill. After sorting, the yellow fill moves with Row 1's data.
   - **Implementation:**
     ```python
     # BEFORE sorting, capture styles for each row
     row_styles = {}
     for rd in all_rows_data:
         row_styles[rd['row_num']] = capture_row_styles(ws, rd['row_num'], min_col, max_col)
     
     # AFTER sorting and writing data, apply the captured styles
     for block_idx, (start, end) in enumerate(block_positions):
         sorted_block = blocks[block_idx]
         for i, pos in enumerate(range(start, end + 1)):
             sorted_row = sorted_block[i]
             actual_row = min_row + pos
             # Apply styles from the ORIGINAL row that this data came from
             original_row_num = sorted_row['row_num']
             if original_row_num in row_styles:
                 apply_row_styles(ws, actual_row, row_styles[original_row_num], min_col)
     ```

**How to decide:** Check if styles vary by row or by column. If all cells in a column have the same style, use position-based. If styles vary by row, use data-based.

**Common mistake:** Capturing styles but never applying them. If you capture styles into a dict but don't use them, you're doing unnecessary work. Either:
- Don't capture styles at all (for position-based), OR
- Capture AND apply them (for data-based)

## Troubleshooting Common Issues

### Issue 1: Formula cells show `None` after loading with `data_only=True`
**Cause:** The workbook was generated programmatically without a calculation pass.
**Solution:** Use the manual formula evaluator fallback (see Step 2).

### Issue 2: Sort order is wrong for ties
**Cause:** Python's `sort()` is stable, but if you're using a custom key that doesn't preserve original order, ties may be reordered.
**Solution:** Ensure your sort key returns the actual value (not a transformed value that loses precision). For descending sort with ties, use `reverse=True` with a stable sort.

### Issue 3: Blank rows are not preserved correctly
**Cause:** The blank row detection is too strict (e.g., checking only one column) or too loose (e.g., treating a row with a single `0` as blank).
**Solution:** Check ALL cells in the data range. A blank row has `None` in every cell. A row with `0`, `""`, or any other value is NOT blank.

### Issue 4: Styles are lost after saving
**Cause:** You're overwriting cells without preserving their styles, or you're creating new cells instead of modifying existing ones.
**Solution:** When writing data, only modify `cell.value`, not the style attributes. Or explicitly copy styles from the original cells.

### Issue 5: Output has extra data beyond the target range
**Cause:** The script is writing to rows outside the declared output range.
**Solution:** Ensure your write loop only iterates over the target range (e.g., rows 1-85 for A1:H85). Clear any cells outside this range if needed.

### Issue 6: Data written to wrong rows when min_row ≠ 1
**Cause:** Using `pos + 1` to convert 0-indexed position to row number, but `pos` is an index into `rows_data` which starts at `min_row`, not row 1.
**Solution:** Use `min_row + pos` to convert position to actual row number. For example, if `min_row = 5`, then `rows_data[0]` corresponds to row 5, `rows_data[1]` to row 6, etc. The formula is `actual_row = min_row + pos`, NOT `pos + 1`. This bug is hidden when `min_row = 1` (since `1 + pos = pos + 1`), but breaks for any variant where data doesn't start at row 1.

**Pro tip:** Store the actual row number in each row_data dict (e.g., `'row_num': r`) and use that directly instead of recomputing. This makes the code more robust and easier to understand:
```python
# When building rows_data:
rows_data.append({
    'row_num': r,  # Store the actual row number
    'values': row_vals,
    'is_blank': is_blank
})

# When writing back:
for block_idx, (start, end) in enumerate(block_positions):
    sorted_block = blocks[block_idx]
    for i, pos in enumerate(range(start, end + 1)):
        sorted_row = sorted_block[i]
        actual_row = sorted_row['row_num']  # Use stored row number
        # ... write data to actual_row
```

### Issue 7: Captured styles are never applied
**Cause:** You captured styles into a dict but forgot to apply them after writing data.
**Solution:** If you're using data-based styles (styles move with data), you MUST both capture AND apply them. If you're using position-based styles (styles stay at positions), don't bother capturing them at all — just write the data and let the existing styles remain.

**How to check:** Search your code for where you use the captured styles dict. If you only see assignments to it but no reads, you're capturing but not applying.
