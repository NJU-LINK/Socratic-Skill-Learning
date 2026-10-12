---
name: xlsx-structure
description: Structural transformations on Excel workbooks including block detection, formula evaluation, sorting, and range manipulation while preserving workbook state
---

# XLSX Structure Transformation Skill

This skill handles structural transformations on Excel workbooks, including detecting data blocks, evaluating formulas, sorting within blocks, and writing results while preserving all other workbook state.

## Core Methodology

### 1. Block Detection

Scan the target range row by row. A block is a contiguous sequence of non-blank rows. Blank rows (all cells None/empty) serve as separators between blocks.

```python
blocks = []
current_block = []
for r in range(start_row, end_row + 1):
    vals = {c: ws.cell(row=r, column=c).value for c in range(start_col, end_col + 1)}
    is_blank = all(v is None for v in vals.values())
    if is_blank:
        if current_block:
            blocks.append(current_block)
            current_block = []
    else:
        current_block.append((r, vals))
if current_block:
    blocks.append(current_block)
```

**Key insight:** Detect block boundaries from the workbook data, not from assumed fixed row counts.

### 2. Formula Evaluation

When cells contain formula strings (text starting with `=`), evaluate them manually:

1. **Dependency order matters:** If column F references column D, evaluate D first, then F
2. **Parse cell references:** Use regex to find references like `B1`, `C1`, etc.
3. **Substitute values:** Replace each reference with the numeric value from the current row
4. **Evaluate arithmetic:** Use Python's `eval()` on the resulting numeric expression
5. **Round results:** Apply `round(result, 10)` to eliminate IEEE 754 floating-point noise

```python
def to_number(val):
    """Convert cell value to float, handling strings and None."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        return float(val) if val else 0.0
    return float(val)

def eval_formula(expr, row_vals):
    """Evaluate formula string like '=B1+C1' using row values."""
    if not isinstance(expr, str) or not expr.startswith('='):
        return to_number(expr)
    
    expr_body = expr[1:]  # strip '='
    
    def replace_ref(match):
        col_letters = match.group(1)  # e.g., 'A', 'AA', 'AB'
        col_idx = 0
        for ch in col_letters:
            col_idx = col_idx * 26 + (ord(ch) - ord('A') + 1)
        return str(to_number(row_vals.get(col_idx)))
    
    # Match multi-letter column references (A-Z, AA-ZZ, etc.)
    numeric_expr = re.sub(r'([A-Z]+)\d+', replace_ref, expr_body)
    return round(eval(numeric_expr), 10)
```

**Critical:** openpyxl does NOT evaluate text strings as formulas. You must parse and evaluate them manually.

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
    if block != blocks[-1]:
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

**Style preservation:** When you modify `cell.value`, openpyxl preserves the existing style object on that cell. Just modify the value in place; don't create new Cell objects.

## Common Pitfalls

1. **Floating-point precision:** Always round evaluated formula results to eliminate IEEE 754 noise
2. **Formula evaluation order:** Respect dependencies (e.g., evaluate D before F if F references D)
3. **String vs numeric values:** Some cells store numbers as strings (e.g., `'115.6'`). Convert to float before arithmetic.
4. **Block detection:** Scan the actual data to find blank-row separators; don't assume fixed block sizes.
5. **Stable sort:** Use Python's built-in `sort()` which is stable for equal keys.

## Adaptation Guide

This skill generalizes across the xlsx-structure family:

- **Different transformations:** Replace sorting with filtering, transposition, or other structural operations
- **Different topologies:** Handle multiple sheets, non-contiguous ranges, or style-marked cells
- **Different selection rules:** Use predicates, style-based filtering, or ID matching instead of numeric sorting
- **Different output geometries:** Write to different ranges, sheets, or orientations
- **Different preservation constraints:** Identify which workbook state must remain intact

The core pattern remains: detect structure → transform → write back → preserve everything else.
