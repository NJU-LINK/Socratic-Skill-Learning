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

Read an input workbook (`/app/input.xlsx`), apply a structural transformation
to a defined region, and write the result to `/app/output.xlsx` while
preserving everything outside the transformation scope.

## Required Tooling

- **Python 3** with `openpyxl` (pre-installed).
- **Never use `pandas`** — it destroys cell-level styles, merged ranges, and
  workbook metadata.

## Phase 0: Parse Task Parameters

Extract these from the task description before touching the workbook:

| Parameter | Where to find it | Example |
|-----------|-----------------|---------|
| Active sheet | Named in task | `Sheet1` |
| Active range | Cell-range reference | `A1:H85` → rows 1-85, cols A-H |
| Transformation type | Verb phrase | "sort … by column D descending" |
| Sort key column | Named column letter | `D` |
| Sort direction | "ascending" / "descending" | descending |
| Tie-breaking rule | "preserve original order" → stable sort | stable |
| Formula columns | "Columns D–F may contain formulas" | D, E, F |
| Output destination | "Write … to A1:H85 on Sheet1" | same range, same sheet |
| Preservation scope | "Preserve every input sheet …" | everything outside active range |

Parse the active range into `min_row, max_row, min_col, max_col` using
`openpyxl.utils.column_index_from_string`.

## Phase 1: Inspect & Map

1. **Load**: `openpyxl.load_workbook('input.xlsx')`.
2. **Snapshot metadata** before any mutation:
   - `wb.sheetnames` — all sheets must survive
   - `ws.column_dimensions` — column widths (column-level, survive cell writes)
   - `ws.row_dimensions` — row heights (reapply after writing if set)
   - `ws.merged_cells.ranges` — avoid writing into merged interiors
   - `ws.auto_filter.ref`, `ws.freeze_panes`
3. **Detect block boundaries** (if topology uses blank-row-separated blocks):
   - A **blank row** = every cell in `[min_col, max_col]` is `None`.
   - Scan every row in `[min_row, max_row]`; collect blank-row indices.
   - **Blocks** = contiguous non-blank segments between blank rows.
   - **Never assume fixed block sizes** — always detect dynamically.

## Phase 2: Read & Evaluate Formulas

### 2a. Read rows with styles

For each row in the active range, capture per-cell:
- `value`, `data_type`
- `copy(cell.font)`, `copy(cell.fill)`, `copy(cell.alignment)`,
  `copy(cell.border)`, `cell.number_format`

### 2b. Evaluate all formula columns generically

**Do not hardcode column letters.** Instead:

1. **Detect formula columns**: scan each column in the active range; if any
   data row has `data_type == 'f'` or a string value starting with `=`, mark
   that column as a formula column.
2. **Evaluate in dependency order**: repeat until no column changes:
   - For each formula cell, substitute already-known numeric values for
     same-row cell references, then `eval()` the arithmetic.
   - **Always `round(result, 10)`** to eliminate IEEE 754 artifacts
     (e.g., `112.1 + 112.8` → `224.89999999999998` → round to `224.9`).
3. **Overwrite** the cell's stored value with the numeric result and mark
   `data_type = 'n'` so downstream columns see the number.

### Formula evaluator

```python
import re

def eval_formula(formula_str, row_values):
    """Evaluate a row-local arithmetic formula string.

    row_values: dict {column_letter: numeric_value} for already-resolved cells.
    Returns a float/int, or None if evaluation fails.
    """
    if not isinstance(formula_str, str):
        return formula_str
    s = formula_str.strip()
    if s.startswith('='):
        s = s[1:]
    # Replace cell refs (e.g. B5, AA12) with numeric values
    s = re.sub(r'([A-Z]+)\d+',
               lambda m: str(row_values.get(m.group(1), 0)), s)
    # Safety: allow only arithmetic tokens
    if re.match(r'^[\d+\-*/().\s]+$', s):
        try:
            result = eval(s)
            # CRITICAL: round to kill floating-point artifacts
            return round(result, 10) if isinstance(result, float) else result
        except Exception:
            return None
    return None
```

**Generic evaluation loop** (handles any chain depth):

```python
from openpyxl.utils import get_column_letter

def evaluate_row(row_cells, min_col, max_col):
    """Evaluate all formula cells in a row, resolving dependencies."""
    col_letters = {c: get_column_letter(c) for c in range(min_col, max_col + 1)}
    # Seed with known numeric values
    resolved = {}
    for c, cl in col_letters.items():
        v = row_cells[c]['value']
        if isinstance(v, (int, float)):
            resolved[cl] = v
    # Iterate until stable
    changed = True
    while changed:
        changed = False
        for c, cl in col_letters.items():
            cell = row_cells[c]
            if cl in resolved:
                continue
            is_formula = (cell['data_type'] == 'f' or
                          (isinstance(cell['value'], str) and
                           cell['value'].startswith('=')))
            if is_formula:
                result = eval_formula(cell['value'], resolved)
                if result is not None:
                    resolved[cl] = result
                    cell['value'] = result
                    cell['data_type'] = 'n'
                    changed = True
```

## Phase 3: Transform

Apply the transformation the task specifies:

| Transformation | Key logic |
|---------------|-----------|
| **Block-local sort** | Sort each block's rows by the key column's evaluated numeric value. Use `list.sort(key=…)` (stable). Negate for descending. |
| **Filter / compact** | Keep rows matching predicate; remove gaps. |
| **Header-aligned append** | Map source→dest columns by header name; append rows. |
| **Sparse reconciliation** | For each ID in reference list, look up data in sparse table; blank if missing. |
| **Transposition** | Swap rows↔columns; preserve cell values and styles. |

For sorting, the key function should convert to float:
```python
block.sort(key=lambda idx: -float(rows[idx][key_col]['value']))
```

## Phase 4: Write Back

1. **Clear** the active range (`cell.value = None` for all cells).
2. **Write** transformed rows sequentially, restoring evaluated values and
   `copy()`-ed styles.
3. **Preserve blank separator rows** exactly (typically one between blocks).
4. **Never touch** cells outside the active range.

## Phase 5: Preserve Workbook State

openpyxl preserves these on save automatically **if you do not modify them**:
- Other sheets, merged ranges, auto-filters, freeze panes, sheet views.
- `column_dimensions` (column-level — survives cell rewrites).
- `row_dimensions` — reapply heights if you cleared them.

## Phase 6: Verify

After saving, reload and check:
1. Sheet count unchanged.
2. Active range: correct row count per block, correct total.
3. Spot-check values: numeric (not formulas), sort order correct.
4. Spot-check styles: font bold/fill/alignment match input on moved rows.
5. Column widths, merged ranges, filters, panes intact.
6. No formula strings (`isinstance(v, str) and v.startswith('=')`) in
   active range.

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Using pandas | Use openpyxl only |
| Hardcoded block sizes | Detect blank rows dynamically |
| Formula strings left in output | Evaluate and write numbers |
| Lexicographic sort on numeric column | `float()` the sort key |
| Missing `copy()` on styles | Copy font/fill/alignment/border/number_format per cell |
| Touching cells outside active range | Restrict writes to parsed range |
| Floating-point artifacts (`-0.299…` vs `-0.3`) | **Always `round(result, 10)`** after eval |
| Evaluating chained formulas in wrong order | Iterate until stable (loop until no changes) |
| Hardcoding formula column letters | Detect formula columns from `data_type` |

## Decision Rules

1. **"blocks" / "separated by blank rows"** → dynamic blank-row detection.
2. **"formulas" / "evaluated values"** → generic formula evaluation (Phase 2b).
3. **"preserve original order" for ties** → stable sort.
4. **Named output range** → write only there; clear first.
5. **"preserve styles/filters/merged ranges"** → verify in Phase 6; `copy()` pattern.
6. **Mixed formula and numeric columns** → detect per-column; evaluate all formula
   columns, pass numeric columns through.
