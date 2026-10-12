---
name: xlsx-structure
description: >
  Structural transformations on Excel workbooks: detect block/range topology,
  evaluate row-local formulas, sort/filter/reconcile/transpose data blocks,
  and write results while preserving all workbook metadata outside the
  transformation range.
---

# xlsx-structure

Reusable skill for performing structural transformations on `.xlsx` workbooks
using `openpyxl`. Covers the family of tasks where data is organized in
variable-topology workbook layouts and must be rearranged according to
evaluated numeric or predicate-based rules while preserving all surrounding
workbook state.

## When to Use

- The task asks to read an input `.xlsx`, transform data within a specified
  range or sheet region, and write the result to an output `.xlsx`.
- The transformation involves one or more of: block-local sorting,
  predicate/style-based filtering, header-aligned append, sparse-record
  reconciliation, row extraction, or layout transposition.
- Formulas or formula-text strings in cells must be evaluated to numeric
  values before sorting or writing.
- All workbook metadata (styles, filters, merged ranges, panes, other sheets,
  data outside the transformation range) must be preserved intact.

## Core Architecture

Every task in this family follows the same pipeline:

```
1. LOAD       → openpyxl.load_workbook(input_path, data_only=False)
2. DETECT     → identify topology: blocks, headers, blank separators, ranges
3. EVALUATE   → resolve formula strings to numeric values (dependency order)
4. TRANSFORM  → sort / filter / reconcile / transpose as specified
5. WRITE      → write evaluated values back, preserving cell positions for styles
6. SAVE       → save to output path; everything outside range is untouched
```

## Step-by-Step Procedure

### 1. Load Workbook

```python
import openpyxl
wb = openpyxl.load_workbook(input_path, data_only=False)
ws = wb[sheet_name]  # or wb[wb.sheetnames[0]] for first sheet
```

**Why `data_only=False`:** We need the raw formula strings to evaluate them
ourselves. Using `data_only=True` returns cached values which may be `None`
for programmatically-created files that were never opened in Excel.

### 2. Detect Block Topology

Blocks are contiguous non-blank row groups separated by blank rows. Detect
them dynamically from the data rather than assuming fixed sizes:

```python
def detect_blocks(ws, min_row, max_row, min_col, max_col):
    """Return (blocks, blank_positions) where blocks is a list of lists of
    (row_index, [cell_values]) and blank_positions is a set of blank row indices."""
    blank_positions = set()
    rows_data = []

    for row_idx in range(min_row, max_row + 1):
        vals = []
        all_none = True
        for col_idx in range(min_col, max_col + 1):
            v = ws.cell(row=row_idx, column=col_idx).value
            vals.append(v)
            if v is not None:
                all_none = False
        if all_none:
            blank_positions.add(row_idx)
            rows_data.append((row_idx, None))
        else:
            rows_data.append((row_idx, vals))

    blocks = []
    current = []
    for row_idx, vals in rows_data:
        if vals is None:
            if current:
                blocks.append(current)
                current = []
        else:
            current.append((row_idx, vals))
    if current:
        blocks.append(current)

    return blocks, blank_positions
```

**Key invariant:** Blank row positions are recorded but never moved. The
transformation only rearranges data rows within their block; blank separators
stay at their original positions.

### 3. Evaluate Row-Local Formulas

Formula strings (e.g., `'=B1+C1'`) must be resolved to numeric values. The
critical insight is **dependency order within a row**:

1. Raw numeric columns (e.g., B, C, E) are read directly.
2. Dependent columns (e.g., D = B+C) are evaluated first.
3. Columns depending on already-evaluated columns (e.g., F = D+E) are
   evaluated after their dependencies.

```python
import re

def eval_formula(formula_str, local_vals):
    """Evaluate a row-local arithmetic formula string.
    local_vals: dict mapping column letters to numeric values.
    Returns numeric result."""
    if not isinstance(formula_str, str) or not formula_str.startswith('='):
        if formula_str is None:
            return 0.0
        return float(formula_str)

    expr = formula_str[1:]  # strip '='

    def replace_ref(match):
        col = match.group(1)
        return str(local_vals.get(col, 0.0))

    expr = re.sub(r'([A-Z]+)\d+', replace_ref, expr)
    result = float(eval(expr))
    return round(result, 10)  # remove floating-point noise
```

**Dependency ordering pattern:**

```python
def evaluate_row(vals, formula_cols, raw_cols):
    """
    vals: list of cell values for the row (indexed by column position)
    formula_cols: list of (col_index, formula_string_or_None) in dependency order
    raw_cols: list of (col_index, column_letter) for raw numeric columns
    """
    local = {}
    for col_idx, col_letter in raw_cols:
        v = vals[col_idx]
        local[col_letter] = float(v) if v is not None else 0.0

    result = list(vals)
    for col_idx, formula_str in formula_cols:
        if formula_str is not None and isinstance(formula_str, str) and formula_str.startswith('='):
            val = eval_formula(formula_str, local)
        elif vals[col_idx] is not None:
            val = float(vals[col_idx])
        else:
            val = 0.0
        result[col_idx] = val
        # Determine column letter for this index (A=0, B=1, ...)
        col_letter = chr(ord('A') + col_idx)
        local[col_letter] = val

    return result
```

### 4. Transform (Sort / Filter / Reconcile / Transpose)

**Block-local sorting** (the v01 anchor case):

```python
for block in blocks:
    evaluated = [(row_idx, orig_vals, ev_vals) for row_idx, orig_vals, ev_vals in
                 [(ri, ov, evaluate_row(ov, ...)) for ri, ov in block]]
    # Stable sort by sort key (e.g., evaluated column D)
    evaluated.sort(key=lambda x: x[2][sort_col_index], reverse=descending)
```

Python's `sorted()` and `list.sort()` are **stable by default**, which
satisfies "preserve original relative order for ties."

**Other transformation patterns** (from spec dimensions):

| Pattern | Approach |
|---------|----------|
| Predicate filtering | Iterate rows, keep those matching predicate, compact |
| Header-aligned append | Match source headers to destination headers by name |
| Sparse reconciliation | Build dict keyed by ID, merge with destination |
| Row extraction | Select rows matching criteria, write to destination range |
| Layout transposition | Swap row/col indices when writing |

### 5. Write Back (Preserving Styles)

The safest preservation strategy: **modify only `.value` on existing cells.**
openpyxl stores styles per cell position, so changing only the value leaves
font, fill, border, alignment, and number_format intact.

```python
# Collect data row positions (non-blank) in original order
data_positions = [r for r, v in rows_data if v is not None]

# Flatten sorted/transformed rows
all_output_rows = []
for block in sorted_blocks:
    for _, _, ev_vals in block:
        all_output_rows.append(ev_vals)

# Write values only — styles remain on their cell positions
for i, pos in enumerate(data_positions):
    for col_idx, value in enumerate(all_output_rows[i]):
        ws.cell(row=pos, column=min_col + col_idx).value = value
```

### 6. Save

```python
wb.save(output_path)
```

Everything outside the transformation range (other sheets, rows beyond the
range, columns beyond the range, merged cells, filters, panes, row heights,
column widths) is automatically preserved because we never touched it.

## Preservation Checklist

Before saving, verify:
- [ ] All sheets present in input are present in output
- [ ] Rows outside the transformation range are unchanged
- [ ] Columns outside the transformation range are unchanged
- [ ] Blank separator rows remain at their original positions
- [ ] Cell styles (font, fill, border) on data cells are preserved
- [ ] No formula strings remain in the output data range
- [ ] Merged ranges, filters, panes are intact

## Formula Evaluation Gotchas

1. **Dependency order matters.** If F depends on D, evaluate D first.
2. **Floating-point noise.** Use `round(result, 10)` to clean artifacts like
   `-0.2999999999999972` → `-0.3`.
3. **None values.** Treat `None` cell values as `0.0` in arithmetic.
4. **Integer vs float.** If input values are integers, the result may be an
   integer. Use `float()` consistently for arithmetic, then convert back if
   the output expects integers (e.g., for columns G, H).
5. **Non-formula cells.** If a cell in a "formula column" contains a plain
   number (not a string starting with `=`), use it directly.

## Adaptation to New Variants

When encountering a new task in this family:

1. **Read the task instruction carefully** to identify:
   - The transformation type (sort, filter, append, reconcile, extract, transpose)
   - The source and destination ranges/sheets
   - The selection/alignment rule (numeric order, membership, identity, etc.)
   - The preservation constraints

2. **Map to the pipeline:**
   - DETECT: adapt block detection to the topology (contiguous, style-marked, ID-paired)
   - EVALUATE: identify which columns contain formulas and their dependencies
   - TRANSFORM: implement the specific transformation logic
   - WRITE: determine the output geometry (same range, new sheet, appended)

3. **Test preservation** by checking that untouched regions are identical
   between input and output.

## Reference Script

See `scripts/xlsx_block_sort.py` for a complete, working implementation of
the block-local sorting variant (v01 anchor case).
