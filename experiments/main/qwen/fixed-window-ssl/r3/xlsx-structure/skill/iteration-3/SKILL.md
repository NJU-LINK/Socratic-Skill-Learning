---
name: xlsx-structure
description: Structural transformations on Excel workbooks including block detection, formula evaluation, sorting, and range manipulation while preserving workbook state
---

# XLSX Structure Transformation Skill

This skill handles structural transformations on Excel workbooks, including detecting data blocks, evaluating formulas, sorting within blocks, and writing results while preserving all other workbook state.

## Core Methodology

### 1. Block Detection

Scan the target range row by row. A block is a contiguous sequence of non-blank rows. Blank rows (all cells None or empty string) serve as separators between blocks.

```python
def is_blank_row(ws, row, start_col, end_col):
    """Check if a row is blank (all cells None or empty string)."""
    for c in range(start_col, end_col + 1):
        v = ws.cell(row=row, column=c).value
        if v is not None and v != '':
            return False
    return True

blocks = []
current_block = []
for r in range(start_row, end_row + 1):
    if is_blank_row(ws, r, start_col, end_col):
        if current_block:
            blocks.append(current_block)
            current_block = []
    else:
        vals = {c: ws.cell(row=r, column=c).value for c in range(start_col, end_col + 1)}
        current_block.append((r, vals))
if current_block:
    blocks.append(current_block)
```

**Key insight:** Detect block boundaries from the workbook data, not from assumed fixed row counts. Handle both `None` and empty strings as blank indicators.

### 2. Formula Evaluation with Dependency Resolution

When cells contain formula strings (text starting with `=`), evaluate them manually with automatic dependency resolution:

1. **Dependency-aware evaluation:** Use a cache to track evaluated columns. If a formula references a column that hasn't been evaluated yet and contains a formula, evaluate that dependency first.
2. **Parse cell references:** Use regex to find references like `B1`, `AA5`, etc. (supports multi-letter columns)
3. **Substitute values:** Replace each reference with the numeric value from the current row
4. **Evaluate arithmetic:** Use Python's `eval()` on the resulting numeric expression
5. **Round results:** Apply `round(result, 10)` to eliminate IEEE 754 floating-point noise

```python
import re

def to_number(val):
    """Convert cell value to float, handling None, int, float, string-numbers."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        if val == '':
            return 0.0
        try:
            return float(val)
        except ValueError:
            return 0.0
    return 0.0

def col_letters_to_idx(letters):
    """Convert column letters (A, B, ..., Z, AA, AB, ...) to 1-based index."""
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx

def eval_formula_with_deps(expr, row_vals, evaluated_cache):
    """
    Evaluate a formula string, resolving dependencies within the row.
    row_vals: dict {col_idx: original_value}
    evaluated_cache: dict {col_idx: evaluated_numeric_value} for already-evaluated columns
    """
    if not isinstance(expr, str) or not expr.startswith('='):
        return to_number(expr)
    
    expr_body = expr[1:]  # strip '='
    
    # Find all cell references
    refs = set(re.findall(r'([A-Z]+)(\d+)', expr_body))
    
    # Check if any referenced column needs evaluation first
    for col_letters, row_num in refs:
        col_idx = col_letters_to_idx(col_letters)
        if col_idx not in evaluated_cache:
            ref_val = row_vals.get(col_idx)
            if isinstance(ref_val, str) and ref_val.startswith('='):
                # Recursively evaluate dependency first
                evaluated_cache[col_idx] = eval_formula_with_deps(ref_val, row_vals, evaluated_cache)
    
    # Now substitute all references with their evaluated values
    def replace_ref(match):
        col_letters = match.group(1)
        col_idx = col_letters_to_idx(col_letters)
        if col_idx in evaluated_cache:
            return str(evaluated_cache[col_idx])
        val = row_vals.get(col_idx)
        return str(to_number(val))
    
    # Match multi-letter column references (A-Z, AA-ZZ, etc.)
    numeric_expr = re.sub(r'([A-Z]+)\d+', replace_ref, expr_body)
    result = eval(numeric_expr)
    return round(result, 10)

# Usage: evaluate all formula columns for a row
eval_cache = {}
for c in range(start_col, end_col + 1):
    v = vals[c]
    if isinstance(v, str) and v.startswith('='):
        eval_cache[c] = eval_formula_with_deps(v, vals, eval_cache)
        vals[c] = eval_cache[c]
```

**Critical:** 
- openpyxl does NOT evaluate text strings as formulas. You must parse and evaluate them manually.
- The dependency resolution handles arbitrary chains (e.g., F depends on D, D depends on B and C).
- Multi-letter columns (AA, AB, etc.) are supported via `col_letters_to_idx()`.

### 3. Block-Local Sorting

Sort rows within each block by the specified column(s):

```python
for block in blocks:
    block.sort(key=lambda x: to_number(x[1][sort_col]), reverse=descending)
```

**Stable sort:** Python's `sort()` is stable, preserving original order for equal keys.

### 4. Writing Results

Write transformed data back to the target range:

```python
output_row = start_row
for block in blocks:
    for orig_row, vals in block:
        for c in range(start_col, end_col + 1):
            ws.cell(row=output_row, column=c).value = vals[c]
        output_row += 1
    # Add blank row separator between blocks
    if block is not blocks[-1]:
        for c in range(start_col, end_col + 1):
            ws.cell(row=output_row, column=c).value = None
        output_row += 1
```

**Clear remaining rows:** If the transformed data doesn't fill the entire target range, clear any leftover cells.

### 5. Preservation Constraints

**Only modify the target range.** Preserve:
- All other sheets in the workbook
- All values outside the target range
- Existing cell styles (fonts, fills, borders, number formats)
- Merged cells, filters, panes, row heights, column widths

**Style preservation semantics:** When you modify `cell.value`, openpyxl preserves the existing style object **at that cell position**. This means:
- Styles are tied to positions, not to data rows
- When sorting moves data from row 5 to row 1, the style at position (1, col) is preserved
- The original style of the data row at position 5 is not carried along with the data
- Just modify `.value` in place; don't create new Cell objects

## Input Inspection Best Practices

Before applying transformations, inspect the input workbook to understand its structure:

1. **Check cell types for formula columns:** Use `type(cell.value)` to see if formulas are stored as strings (`str`), numbers, or other types. In openpyxl, formulas are typically read as plain strings like `'=B1+C1'`.

2. **Identify blank row indicators:** Check whether blank rows use `None`, empty strings `''`, or both. Your blank detection should handle all variants.

3. **Map the data topology:** Identify sheet names, target ranges, block structures, and any data outside the transformation range that must be preserved.

4. **Verify column references:** Check if formulas reference columns beyond Z (AA, AB, etc.) to ensure your column index conversion handles them.

```python
# Example inspection
for r in range(1, 5):
    for c in [4, 6]:  # Check formula columns
        cell = ws.cell(row=r, column=c)
        print(f"({r},{c}): value={cell.value!r}, type={type(cell.value).__name__}")
```

## Common Pitfalls

1. **Floating-point precision:** Always round evaluated formula results with `round(x, 10)` to eliminate IEEE 754 noise
2. **Formula dependencies:** Use dependency-aware evaluation, not hardcoded column order. If F references D, D must be evaluated first.
3. **String vs numeric values:** Some cells store numbers as strings (e.g., `'115.6'`). Convert to float before arithmetic.
4. **Blank row detection:** Handle both `None` and empty strings. Scan actual data, don't assume fixed block sizes.
5. **Stable sort:** Use Python's built-in `sort()` which is stable for equal keys.
6. **Multi-letter columns:** Use `col_letters_to_idx()` to handle columns beyond Z (AA, AB, etc.).
7. **Style semantics:** Styles are position-based, not row-based. Modifying `.value` preserves the style at that position.

## Transformation Patterns

The core methodology (detect → transform → write → preserve) adapts to various transformation types:

### Pattern 1: Block-Local Sorting (v01)
**Use when:** Rows form blocks separated by blanks, sort within each block by a column.

```python
# After detecting blocks and evaluating formulas:
for block in blocks:
    block.sort(key=lambda x: to_number(x[1][sort_col]), reverse=descending)
```

### Pattern 2: Predicate-Based Filtering
**Use when:** Select rows matching a condition, compact output (no blank separators).

```python
# Filter rows by predicate
def matches_predicate(vals, predicate_col, predicate_fn):
    return predicate_fn(vals[predicate_col])

filtered_rows = []
for block in blocks:
    for orig_row, vals in block:
        if matches_predicate(vals, filter_col, lambda v: to_number(v) > threshold):
            filtered_rows.append(vals)

# Write compact output (no blank separators)
for i, vals in enumerate(filtered_rows):
    for c in range(start_col, end_col + 1):
        ws.cell(row=output_start + i, column=c).value = vals[c]
```

### Pattern 3: Style-Based Selection
**Use when:** Select rows based on cell fill color or other style attributes.

```python
from openpyxl.styles import PatternFill

def get_fill_color(cell):
    """Extract fill color from cell."""
    fill = cell.fill
    if fill.patternType:
        if fill.fgColor and fill.fgColor.rgb:
            return fill.fgColor.rgb
    return None

# Select rows by fill color
target_color = 'FFFF00'  # Yellow
selected_rows = []
for r in range(start_row, end_row + 1):
    cell = ws.cell(row=r, column=style_col)
    if get_fill_color(cell) == target_color:
        vals = {c: ws.cell(row=r, column=c).value for c in range(start_col, end_col + 1)}
        selected_rows.append(vals)
```

### Pattern 4: ID-Based Alignment
**Use when:** Source and destination have different orders, align by ID column.

```python
# Build ID-to-row mapping from source
source_map = {}
for block in blocks:
    for orig_row, vals in block:
        id_val = vals[id_col]
        source_map[id_val] = vals

# Read destination ID list and align
dest_ids = []
for r in range(dest_start, dest_end + 1):
    id_val = ws.cell(row=r, column=dest_id_col).value
    if id_val is not None:
        dest_ids.append(id_val)

# Write aligned data
for i, id_val in enumerate(dest_ids):
    if id_val in source_map:
        vals = source_map[id_val]
        for c in range(start_col, end_col + 1):
            ws.cell(row=dest_start + i, column=c).value = vals[c]
```

### Pattern 5: Transposition
**Use when:** Rotate data from rows to columns or vice versa.

```python
# Read source data
source_data = []
for r in range(start_row, end_row + 1):
    row_vals = [ws.cell(row=r, column=c).value for c in range(start_col, end_col + 1)]
    source_data.append(row_vals)

# Transpose: rows become columns
num_rows = len(source_data)
num_cols = len(source_data[0]) if source_data else 0

for r in range(num_rows):
    for c in range(num_cols):
        # Write to transposed position
        ws.cell(row=dest_start + c, column=dest_start_col + r).value = source_data[r][c]
```

### Pattern 6: Header-Aligned Append
**Use when:** Append data to existing table, aligning columns by header names.

```python
# Read existing headers
headers = {}
for c in range(start_col, end_col + 1):
    header_val = ws.cell(row=header_row, column=c).value
    if header_val:
        headers[header_val] = c

# Append new data aligned by headers
append_row = last_data_row + 1
for new_row_data in new_data:
    for col_name, value in new_row_data.items():
        if col_name in headers:
            ws.cell(row=append_row, column=headers[col_name]).value = value
    append_row += 1
```

## Adaptation Guide

This skill generalizes across the xlsx-structure family:

- **Different transformations:** Use the patterns above (sorting, filtering, transposition, ID alignment, etc.)
- **Different topologies:** Handle multiple sheets, non-contiguous ranges, or style-marked cells
- **Different selection rules:** Use predicates, style-based filtering, or ID matching instead of numeric sorting
- **Different output geometries:** Write to different ranges, sheets, or orientations
- **Different preservation constraints:** Identify which workbook state must remain intact

The core pattern remains: **detect structure → transform → write back → preserve everything else**.
