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

## Execution Strategy: One Script, One Tool Call

Write a **single Python script** (saved to `/app/solve.py` then run, or passed
via heredoc) that performs all phases in one `task_shell` call:

1. Parse task parameters from the task description (Phase 0).
2. Load workbook, inspect metadata, read rows (Phase 1–2).
3. Evaluate formulas (Phase 2b).
4. Transform (Phase 3).
5. Write back (Phase 4).
6. Save and verify inline (Phase 5–6).

**Why one script?** Separate inspection calls waste tool-call budget on large
data dumps. A single script can print concise summaries (block counts, sample
values) while doing all work. Use `task_shell` once to write-and-run, and once
more for `ls -la output.xlsx` if desired.

### Inspection output discipline

When printing data for debugging inside the script:
- Print only **column A value + sort-key column value** per row, not all 8+ columns.
- For styles, print only `bold` and `alignment.horizontal` — **never dump full
  border objects** (they produce hundreds of lines of uninformative output).
- Print metadata as a compact summary: sheet count, column-width keys, merged
  range count, freeze pane.

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
- `copy.copy(cell.font)`, `copy.copy(cell.fill)`,
  `copy.copy(cell.alignment)`, `copy.copy(cell.border)`,
  `cell.number_format`

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
import re, copy
from openpyxl.utils import get_column_letter

def eval_formula(formula_str, row_values):
    """Evaluate a row-local arithmetic formula string."""
    if not isinstance(formula_str, str):
        return formula_str
    s = formula_str.strip()
    if s.startswith('='):
        s = s[1:]
    s = re.sub(r'([A-Z]+)\d+',
               lambda m: str(row_values.get(m.group(1), 0)), s)
    if re.match(r'^[\d+\-*/().\s]+$', s):
        try:
            result = eval(s)
            return round(result, 10) if isinstance(result, float) else result
        except Exception:
            return None
    return None

def evaluate_row(row_cells, min_col, max_col):
    """Evaluate all formula cells in a row, resolving dependencies."""
    col_letters = {c: get_column_letter(c) for c in range(min_col, max_col + 1)}
    resolved = {}
    for c, cl in col_letters.items():
        v = row_cells[c]['value']
        if isinstance(v, (int, float)):
            resolved[cl] = v
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

For sorting:
```python
key_col_idx = column_index_from_string(sort_key_letter)
block.sort(key=lambda idx: -float(all_rows[idx][key_col_idx]['value']))
```

## Phase 4: Write Back

1. **Clear** the active range (`cell.value = None` for all cells).
2. **Build output order**: for block-based topologies, concatenate sorted
   blocks with blank-row indices interleaved. Verify
   `len(output_order) == max_row - min_row + 1`.
3. **Write** rows in output order, restoring evaluated values and
   `copy.copy()`-ed styles.
4. **Never touch** cells outside the active range.

## Phase 5: Preserve Workbook State

openpyxl preserves these on save automatically **if you do not modify them**:
- Other sheets, merged ranges, auto-filters, freeze panes, sheet views.
- `column_dimensions` (column-level — survives cell rewrites).
- `row_dimensions` — reapply heights if you cleared them.

## Phase 6: Inline Verification

After saving inside the same script, reload and print compact checks:

```python
wb2 = openpyxl.load_workbook('output.xlsx')
ws2 = wb2['Sheet1']
# 1. Sheet count
assert wb2.sheetnames == orig_sheets, f"Sheet mismatch: {wb2.sheetnames}"
# 2. No formula strings
for r in range(min_row, max_row+1):
    for c in range(min_col, max_col+1):
        v = ws2.cell(r, c).value
        assert not (isinstance(v, str) and v.startswith('=')), \
            f"Formula at {get_column_letter(c)}{r}: {v}"
# 3. Column dimensions
for k, v in orig_col_dims.items():
    assert abs(ws2.column_dimensions[k].width - v) < 0.01, f"Width {k}"
print("All inline checks passed.")
```

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Using pandas | Use openpyxl only |
| Hardcoded block sizes | Detect blank rows dynamically |
| Formula strings left in output | Evaluate and write numbers |
| Lexicographic sort on numeric column | `float()` the sort key |
| Missing `copy.copy()` on styles | Copy font/fill/alignment/border/number_format per cell |
| Touching cells outside active range | Restrict writes to parsed range |
| Floating-point artifacts (`-0.299…` vs `-0.3`) | **Always `round(result, 10)`** after eval |
| Evaluating chained formulas in wrong order | Iterate until stable (loop until no changes) |
| Hardcoding formula column letters | Detect formula columns from `data_type` |
| Dumping full border objects in debug output | Print only `bold`, `alignment.horizontal` |
| Multiple separate inspection tool calls | Combine into one script |

## Decision Rules

1. **"blocks" / "separated by blank rows"** → dynamic blank-row detection.
2. **"formulas" / "evaluated values"** → generic formula evaluation (Phase 2b).
3. **"preserve original order" for ties** → stable sort.
4. **Named output range** → write only there; clear first.
5. **"preserve styles/filters/merged ranges"** → verify in Phase 6; `copy.copy()`.
6. **Mixed formula and numeric columns** → detect per-column; evaluate all
   formula columns, pass numeric columns through.
