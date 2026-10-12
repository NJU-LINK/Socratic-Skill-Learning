---
name: xlsx-structure
description: >
  Perform structural transformations on Excel workbooks — sorting, filtering,
  appending, reconciliation, extraction, and transposition — while preserving
  all unrelated workbook state (styles, sheets, merged ranges, filters, panes,
  dimensions). Handles formula evaluation, dynamic structure detection, and
  style-preserving row/cell movement.
---

# xlsx-structure

## Overview

This skill covers structural transformations on `.xlsx` workbooks using
`openpyxl`. The family of tasks varies along five axes:

| Axis | What varies |
|------|-------------|
| **transformation_semantics** | Block-local sorting, predicate/style-based filtering and compaction, header-aligned append, sparse-record reconciliation, row extraction, layout transposition |
| **workbook_topology** | Single/multiple sheets, contiguous tables, repeated blocks separated by blanks, style-marked cells, ordered ID lists paired with sparse tables, header-mapped columns, sparse source/destination ranges |
| **selection_and_alignment_rule** | Evaluated numeric order, membership in another range, exact header/ID identity, fill color, text predicates with exclusions, source-list order, positional correspondence |
| **output_geometry** | Existing or new destination sheet, range, orientation, append/insertion/compaction boundary |
| **preservation_constraints** | Input sheets, unrelated values, existing styles, dimensions, filters, merged ranges, panes, row heights, column widths |

## General Procedure

### Step 1 — Analyze the task instruction

Read the task to identify the concrete realization of each axis:
- **What transformation** must be applied? (sort, filter, append, reconcile, extract, transpose)
- **What is the topology** of source data? (contiguous block, blank-separated blocks, style-marked regions, header-mapped columns, ID list + sparse table)
- **What selection/alignment rule** determines which rows/cells to pick and where to place them?
- **What is the output geometry** — which sheet, which range, append vs overwrite?
- **What must be preserved** beyond the transformation?

### Step 2 — Detect workbook structure dynamically

**Never hardcode row counts, column positions, or block sizes.** Scan the actual workbook to determine boundaries.

Common detection patterns:
- **Blank-row-separated blocks**: Scan rows; a row where all cells in the data range are `None` is a separator. Accumulate consecutive non-blank rows into a block.
- **Header-mapped columns**: Read the header row, build a `{header_text: column_index}` mapping.
- **Style-marked regions**: Check cell fill colors or font styles to identify region boundaries.
- **Contiguous table**: Find the extent by scanning from a known start until a fully blank row or the sheet boundary.

### Step 3 — Evaluate formulas before transforming

Columns in the transform range may contain:
- **Actual Excel formulas** (`data_type='f'`) — openpyxl reads the formula string
- **Text that looks like formulas** (`data_type='s'`, value starts with `'='`)

**Auto-detecting formula columns** (when the task doesn't specify which columns contain formulas):
```python
# Scan the transform range for cells whose value is a string starting with '='
formula_cols = set()
for r in range(min_row, max_row + 1):
    for c in range(min_col, max_col + 1):
        val = ws.cell(r, c).value
        if isinstance(val, str) and val.startswith('='):
            formula_cols.add(c)

# Sort by column index to get dependency order
# (earlier columns typically depend only on plain values;
# later columns may reference earlier formula columns)
formula_col_indices = sorted(formula_cols)
```

**Evaluation procedure:**
1. Build a `row_values` dict mapping column letters to their numeric values for each row.
2. Identify formula dependencies between columns (e.g., `=D1+E1` depends on D).
3. Evaluate columns in **dependency order**: columns that reference only plain-value columns first, then columns that reference other formula columns. For simple row-local arithmetic, sorting formula columns by index (left-to-right) usually gives correct dependency order.
4. Use safe `eval()` with restricted builtins for simple arithmetic (`+`, `-`, `*`, `/`).
5. **Round float results to 10 decimal places** to eliminate IEEE 754 noise (e.g., `1.5999999999999994` → `1.6`) while preserving legitimate precision.

```python
import re

def eval_formula(formula_str, row_values):
    """Evaluate a formula string using row_values dict (col_letter -> numeric value)."""
    if not isinstance(formula_str, str) or not formula_str.startswith('='):
        return formula_str
    expr = formula_str[1:]
    def sub(m):
        col = m.group(1).upper()
        val = row_values.get(col, 0)
        return str(val if val is not None else 0)
    expr = re.sub(r'([A-Z])\d+', sub, expr)
    result = eval(expr, {"__builtins__": {}}, {})
    if isinstance(result, float):
        result = round(result, 10)
    return result
```

### Step 4 — Apply the transformation

Use the selection/alignment rule from the task instruction. The core pattern is:
1. **Read** source data with styles (using `capture_cell`)
2. **Transform** according to the task (sort, filter, reconcile, transpose, etc.)
3. **Write** back with styles (using `apply_cell`)

**For sorting** (block-local or global):
- Python's `list.sort(key=..., reverse=...)` is **stable** — equal keys preserve original order.
- Sort by the evaluated numeric values, not by formula strings or lexical text.

**For filtering/compaction**:
- Apply the predicate to each row's relevant column(s).
- Collect matching rows into a list.
- Write them contiguously to the output range (removing gaps/blank rows).
- Example: `filtered = [row for row in rows if row[sort_col]['value'] > threshold]`

**For appending**:
- Find the last used row in the destination range: `last_row = max(r for r in range(...) if not is_blank_row(ws, r, ...))`
- Write new rows starting at `last_row + 1`, aligned by header mapping.
- Preserve styles from source rows when writing.

**For reconciliation** (sparse source + ID list):
- Build a lookup dict from the sparse table: `{id_value: row_data}`
- Iterate through the ID list in order.
- For each ID, look up the corresponding row and write it to the output.
- Handle missing IDs gracefully (write blank row or skip, per task spec).

**For transposition**:
- Read source range as a 2D array of captured cells: `grid = [[capture_cell(ws.cell(r, c)) for c in cols] for r in rows]`
- Write transposed: `apply_cell(ws.target(dest_col, dest_row), grid[src_row][src_col])`
- Swap row/column indices: `dest_row = src_col_offset`, `dest_col = src_row_offset`

### Step 5 — Write back with style preservation

When moving rows/cells, **styles must travel with the data**. openpyxl does not move styles automatically.

**Correct approach:**
1. For each source cell, capture value AND all style attributes:
   - `font`, `fill`, `border`, `alignment`, `number_format`, `protection`
   - Use `copy()` from the `copy` module for each style object.
2. After determining the target position for each cell, set both value and styles into the existing cell at that position.
3. **Never move or swap Cell objects** — copy properties into existing worksheet positions.

```python
from copy import copy

def capture_cell(cell):
    return {
        'value': cell.value,
        'font': copy(cell.font),
        'fill': copy(cell.fill),
        'border': copy(cell.border),
        'alignment': copy(cell.alignment),
        'number_format': cell.number_format,
        'protection': copy(cell.protection),
    }

def apply_cell(target_cell, captured):
    target_cell.value = captured['value']
    target_cell.font = captured['font']
    target_cell.fill = captured['fill']
    target_cell.border = captured['border']
    target_cell.alignment = captured['alignment']
    target_cell.number_format = captured['number_format']
    target_cell.protection = captured['protection']
```

### Step 6 — Preserve everything outside the transform

The following must remain untouched:
- All other sheets in the workbook
- All values outside the declared transform range
- Row heights, column widths
- Merged cell ranges
- Auto-filters
- Frozen panes
- Existing cell styles in non-transform areas

**Implementation**: Load with `openpyxl.load_workbook(path)` (not `data_only=True`), modify only the target range, and save. Do not create a new workbook — modify the loaded one in place.

## Reference Implementation

See `scripts/sort_blocks.py` for a parameterized implementation of the
blank-row-block descending-sort transformation (the v01 anchor case).

> **Execution note**: The `scripts/` directory is available via the `read` tool (package-relative path), but **NOT** as a filesystem path inside the task container at `/app`. To use a script:
> 1. Read its contents using the `read` tool with the package-relative path (e.g., `xlsx-structure/scripts/sort_blocks.py`)
> 2. Either execute the code inline via `task_shell` using a heredoc or Python `-c`, or
> 3. Write the script content to a file inside the container first (e.g., `cat > /app/solve.py << 'EOF' ... EOF`), then execute it
>
> Do **not** attempt to run `python3 /path/to/host/workspace/skill/...` from inside the container — that path does not exist there.

## Common Pitfalls

1. **Formula dependency order**: If column F references column D, evaluate D first. Using the unevaluated formula string in D will crash or produce garbage.
2. **Floating-point noise**: IEEE 754 arithmetic produces artifacts like `1.5999999999999994`. Round to 10 decimals after evaluation.
3. **Hardcoded block sizes**: Always detect block boundaries from the data.
4. **Checking only column A for blank rows**: A row might have `None` in A but data in other columns. Check all columns in the data range.
5. **Moving Cell objects instead of copying properties**: This corrupts the worksheet. Always copy style attributes into existing cells.
6. **Using `data_only=True`**: Programmatically created files often have no cached values — you get `None` instead of the computed result. Evaluate formulas manually.
7. **Lexicographic sort of numeric values**: `"9" > "10"` lexicographically. Always convert to numeric before sorting.
