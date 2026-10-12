# openpyxl Patterns

## Table of Contents
- [Manual Formula Evaluation](#manual-formula-evaluation)
- [Detect Blocks and Stable Sort](#detect-blocks-and-stable-sort)
- [In-Place Block Sorting](#in-place-block-sorting)
- [Preserve Cell Styles During Rearrangement](#preserve-cell-styles-during-rearrangement)

## Manual Formula Evaluation
Since openpyxl reads formulas as strings, manually evaluate row-local arithmetic and interdependent formulas sequentially in dependency order. Replace formula strings with computed numeric values *before* sorting to ensure numeric sorting. Apply `round(result, 10)` to evaluated numeric values to eliminate IEEE 754 floating-point artifacts (e.g., 1.599999999999994 -> 1.6).
```python
d_val = round(b_val + c_val, 10)
f_val = round(d_val + e_val, 10)
```

## Detect Blocks and Stable Sort
To process variable-length data blocks separated by blank rows, group consecutive non-blank rows into discrete lists. Use Python's native `list.sort()` or `sorted()` with a numeric key to guarantee stable sorting (preserving original relative order for tied values) and maintain blank row separators.
```python
# Grouping
if all(cell.value is None for cell in row):
    if current_block:
        blocks.append(current_block)
        current_block = []
else:
    current_block.append(row)

# Stable sort
block.sort(key=lambda r: r['sort_val'], reverse=True)
```

## In-Place Block Sorting
When sorting rows within a detected block, capture original row indices before sorting data tuples. Map sorted data back using these pre-sorted positional indices so rows land in correct physical locations.
```python
original_positions = [rn for rn, _ in block]
evaluated_rows.sort(key=lambda x: x[1][sort_col_idx], reverse=True)
for idx, (orig_row_num, eval_vals) in enumerate(evaluated_rows):
    target_row = original_positions[idx]
    # write eval_vals to target_row
```

## Preserve Cell Styles During Rearrangement
When sorting or moving rows in `openpyxl`, assigning `.value` does not move formatting. Explicitly snapshot and copy all style attributes (`font`, `fill`, `alignment`, `number_format`, `border`, `protection`) from source to destination cells before modification, and re-apply them after writing sorted values.
```python
from copy import copy

styles = {
    'font': copy(cell.font), 
    'fill': copy(cell.fill), 
    'alignment': copy(cell.alignment), 
    'border': copy(cell.border), 
    'number_format': cell.number_format,
    'protection': copy(cell.protection)
}
dest_cell.value = source_cell.value
dest_cell.font = styles['font']
dest_cell.fill = styles['fill']
dest_cell.alignment = styles['alignment']
dest_cell.border = styles['border']
dest_cell.number_format = styles['number_format']
dest_cell.protection = styles['protection']
```