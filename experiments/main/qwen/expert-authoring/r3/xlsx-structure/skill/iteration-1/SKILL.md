---
name: xlsx-structure
description: >
  Perform structural transformations on Excel workbooks (.xlsx) while preserving
  all unrelated workbook state. Covers block-local sorting, predicate/style-based
  filtering and compaction, header-aligned append, sparse-record reconciliation,
  row extraction, and layout transposition across varied workbook topologies.
---

# xlsx-structure

## Overview

This family involves reading an input workbook (`/app/input.xlsx`), applying a
structural transformation to a defined region, and writing the result to
`/app/output.xlsx` while preserving everything outside the transformation scope.

## Required Tooling

- **Python 3** with `openpyxl` (pre-installed).
- Never use `pandas` for this family — it destroys cell-level styles, merged
  ranges, and workbook metadata.

## General Strategy (Apply In Order)

### Phase 1: Inspect & Map

1. **Load the workbook** with `openpyxl.load_workbook('input.xlsx')`.
2. **Enumerate sheets**, merged ranges, auto-filters, freeze panes, column
   widths, and row heights *before* any mutation.
3. **Identify the active region** — the sheet and cell range named in the task.
4. **Identify block boundaries** if the topology uses blank-row-separated
   blocks:
   - A *blank row* is one where **every cell** in the active column span is
     `None` (or empty string).
   - Scan every row in the active range; collect blank-row indices.
   - Blocks are the contiguous non-blank segments between blank rows.
   - Do **not** assume fixed block sizes — detect them dynamically.

### Phase 2: Read & Evaluate

1. **Read each data row** in the active range into a list-of-dicts or
   list-of-tuples. Capture both:
   - **Cell values** (`.value`)
   - **Cell styles** (font, fill, alignment, border, number_format) — use
     `copy(cell)` from `copy` module or manually copy each style attribute.
2. **Evaluate formula cells**:
   - Cells with `data_type == 'f'` contain formula strings (e.g. `=B1+C1`).
   - Cells with `data_type == 's'` whose text starts with `=` or matches an
     arithmetic pattern may be *text-stored formulas*.
   - **Row-local arithmetic**: replace cell references like `B5`, `C5` with
     the numeric values from the same row, then evaluate the expression.
   - Use a safe evaluator (see *Formula Evaluation* section below).
   - Write the **numeric result** to the output — never leave formula strings
     or `=...` text in the answer range.

### Phase 3: Transform

Apply the transformation specified in the task. Common patterns:

#### Block-Local Sorting
- Within each detected block, sort rows by the key column's **evaluated
  numeric value**.
- Respect sort direction (ascending/descending) from the task description.
- Use **stable sort** (`list.sort()` with `key=`, which is stable in Python)
  when the task says "preserve original relative order" for ties.
- Sort the **complete row data** (all columns in the active range), not just
  the key column.

#### Filtering / Compaction
- Keep rows matching a predicate (value threshold, style attribute, text
  match); discard others.
- "Compaction" means removing blank/gap rows and writing results contiguously.

#### Header-Aligned Append
- Read a source range and a destination range.
- Match columns by header name (exact string match).
- Append source rows into destination, mapping columns by header identity.

#### Sparse-Record Reconciliation
- An ID list in one range defines expected records; a sparse table in another
  range provides partial data.
- For each ID, fill available data from the sparse table; leave blanks for
  missing entries.

#### Layout Transposition
- Convert rows to columns (or vice versa), preserving cell values and styles.

### Phase 4: Write Back

1. **Clear the active range** — set all cells in the target region to `None`
   before writing, to remove any stale data.
2. **Write transformed data** row by row, restoring:
   - Evaluated numeric values (not formulas)
   - Original cell styles (font, fill, alignment, border, number_format)
3. **Preserve blank separator rows** exactly as required (typically one blank
   row between blocks).
4. **Do not touch** cells outside the active range.

### Phase 5: Preserve Workbook State

Before writing output, verify these are intact:
- **All sheets** — other sheets must be unchanged.
- **Column widths** — stored in `ws.column_dimensions`; these survive cell
  rewrites automatically since they are column-level, not cell-level.
- **Row heights** — stored in `ws.row_dimensions`; reapply if needed.
- **Merged ranges** — `ws.merged_cells.ranges`; avoid writing into merged
  interior cells.
- **Auto-filters** — `ws.auto_filter.ref`.
- **Freeze panes** — `ws.freeze_panes`.
- **Sheet views / selection** — preserved by openpyxl on save.

### Phase 6: Verify

After saving `/app/output.xlsx`, reload and check:
1. Correct number of sheets.
2. Active range has expected row/column count.
3. Spot-check 2-3 rows: values are numeric (not formulas), sort order is
   correct, styles match input.
4. Cells outside the active range are untouched.
5. Column widths and other metadata are preserved.

## Formula Evaluation

For row-local arithmetic formulas (the most common case in this family):

```python
import re

def eval_row_formula(formula_str, row_values):
    """
    Evaluate a simple arithmetic formula with cell references.
    row_values: dict mapping column letter (e.g. 'B') to numeric value.
    """
    if not isinstance(formula_str, str):
        return formula_str  # already numeric

    s = formula_str.lstrip('=')

    # Replace cell references like B5, C12 with their numeric values
    def replacer(match):
        col_letter = match.group(1)
        return str(row_values.get(col_letter, 0))

    s = re.sub(r'([A-Z]+)\d+', replacer, s)

    # Safe eval: only allow digits, +, -, *, /, (, ), ., spaces
    if re.match(r'^[\d+\-*/().\s]+$', s):
        return eval(s)
    return None  # cannot evaluate
```

**Important**: When evaluating chained formulas (e.g., `F = D + E` where
`D = B + C`), evaluate in dependency order — compute D first, then use D's
result when computing F.

## Style Preservation Pattern

```python
from copy import copy

def copy_cell_style(src_cell, dst_cell):
    """Copy all style attributes from src to dst cell."""
    dst_cell.font = copy(src_cell.font)
    dst_cell.fill = copy(src_cell.fill)
    dst_cell.alignment = copy(src_cell.alignment)
    dst_cell.border = copy(src_cell.border)
    dst_cell.number_format = src_cell.number_format
```

When sorting/filtering rows, store style snapshots alongside values so they
travel with the row during transformation.

## Common Pitfalls

| Pitfall | Consequence | Fix |
|---------|------------|-----|
| Using pandas to read/write | Destroys styles, merges, metadata | Use openpyxl only |
| Assuming fixed block sizes | Fails on variable-length blocks | Detect blank rows dynamically |
| Leaving formula strings in output | Tests expect numeric values | Evaluate and write numbers |
| Lexicographic sort on numeric column | Wrong order (e.g., "9" > "10") | Convert to float before sorting |
| Not copying styles when moving rows | Output loses formatting | Use `copy()` for each style attr |
| Modifying cells outside active range | Breaks preservation constraint | Only touch declared region |
| Forgetting chained formula evaluation | Wrong numeric results | Evaluate dependencies first |

## Decision Rules

1. **If the task mentions "blocks" or "separated by blank rows"** → use
   dynamic blank-row detection (Phase 1 step 4).
2. **If the task mentions formulas or "evaluated values"** → apply formula
   evaluation (Phase 2) before any transformation.
3. **If the task says "preserve original order" for ties** → use stable sort.
4. **If the task names a specific output range** → write only to that range;
   clear it first.
5. **If the task says "preserve styles/filters/merged ranges"** → verify
   each in Phase 6; use `copy()` pattern for styles.
6. **If columns contain mixed formulas and plain numbers** → handle both:
   evaluate formula cells, pass through numeric cells unchanged.
