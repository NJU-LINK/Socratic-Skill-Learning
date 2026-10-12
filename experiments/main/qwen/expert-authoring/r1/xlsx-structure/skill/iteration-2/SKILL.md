---
name: xlsx-structure
description: >
  Perform structural transformations on Excel (.xlsx) workbooks using openpyxl.
  Covers block-local sorting, predicate- or style-based filtering and compaction,
  header-aligned append, sparse-record reconciliation, row extraction, and layout
  transposition. Handles formula evaluation, multi-sheet preservation, and
  style/formatting retention.
---

# xlsx-structure

## Quick Start — Execute the Helper Script

**Do not reimplement from scratch.** The skill provides a tested helper library at
`scripts/xlsx_transform.py`. Import its functions and compose them for your solution.

```python
# Copy the script to /app so it is importable, then:
import sys; sys.path.insert(0, "/app/scripts")
from xlsx_transform import (
    load_workbook, detect_blocks, find_blank_rows,
    evaluate_formulas_in_range, is_formula,
    snapshot_range, write_snapshot, sort_block_rows,
    verify_no_formulas, verify_sort_order, verify_block_structure,
    verify_sheet_preservation,
)
```

### Execution Template

1. **Read `task.yaml`** — extract transformation type, target range, sort key,
   formula columns, preservation requirements.
2. **Copy script to /app:** `cp /skill/scripts/xlsx_transform.py /app/scripts/`
   (create `/app/scripts/` if needed).
3. **Adapt and run** the template below, substituting values from the instruction:

```python
import sys, os
os.makedirs("/app/scripts", exist_ok=True)
# (copy script first via task_shell, then:)
sys.path.insert(0, "/app/scripts")
from xlsx_transform import *

wb = load_workbook("/app/input.xlsx")
ws = wb["Sheet1"]  # or whatever sheet the instruction names

# Detect topology
blocks = detect_blocks(ws, col_start=1, col_end=8, row_start=1, row_end=85)
blank_rows = find_blank_rows(ws, col_start=1, col_end=8, row_start=1, row_end=85)
original_sheets = list(wb.sheetnames)

# Evaluate formulas (columns D and F, left-to-right)
all_data_rows = []
for s, e in blocks:
    all_data_rows.extend(range(s, e + 1))
evaluate_formulas_in_range(ws, all_data_rows, ["D", "F"], col_start=1, col_end=8)

# Sort each block by the key column (D = column 4), descending, stable
for s, e in blocks:
    sort_block_rows(ws, list(range(s, e + 1)), key_col=4, descending=True,
                    col_start=1, col_end=8)

# Verify
errs = verify_no_formulas(ws, all_data_rows, ["D", "F"])
errs += verify_sort_order(ws, [list(range(s,e+1)) for s,e in blocks], key_col=4, descending=True)
errs += verify_block_structure(ws, blank_rows, col_start=1, col_end=8)
errs += verify_sheet_preservation(wb, original_sheets)
if errs:
    print("ERRORS:", errs)
else:
    wb.save("/app/output.xlsx")
    print("OK — saved /app/output.xlsx")
```

Adapt `col_start`, `col_end`, `row_start`, `row_end`, `key_col`, `formula_cols`,
`descending`, and sheet name(s) from the instruction.

## Decision Rules

| Situation | Action |
|---|---|
| Instruction says "sort by column X descending" | `sort_block_rows(ws, rows, key_col=col_index_of_X, descending=True)` |
| "preserve original relative order" for ties | Built-in — Python's `sort()` is stable |
| Formula column references another formula column | `evaluate_formulas_in_range` processes columns left-to-right automatically |
| Block boundaries not given | `detect_blocks` scans for all-blank rows in the column range |
| "retain exactly one blank row between blocks" | `sort_block_rows` only reorders within block row lists; blank rows untouched |
| "preserve styles" | `snapshot_range` / `sort_block_rows` / `write_snapshot` all `copy()` font, fill, border, alignment, number_format |
| Output range = input range | In-place via `sort_block_rows` (snapshots first) |
| Output range is new sheet/range | `snapshot_range` from source → `write_snapshot` to destination |
| "do not leave formula strings" | `evaluate_formulas_in_range` replaces formulas with numeric results |
| Unclear if column has formulas | `is_formula(val)` checks `isinstance(val, str) and val.strip().startswith("=")` |
| Other transformation (filter, append, transpose) | Use `snapshot_range`/`write_snapshot` primitives; see Patterns below |

## Transformation Patterns Beyond Sorting

The helper script provides the building blocks. Compose them for non-sort tasks:

**Filtering / Compaction:** Snapshot kept rows with `snapshot_range`, remap row
keys to contiguous targets, write with `write_snapshot`.

**Header-Aligned Append:** Read header row to build `{name: col_index}` map.
For each source record, write to matching destination columns.

**Sparse Reconciliation:** Build `{id: {col: val}}` lookup from reference.
Iterate destination rows; fill `None` cells from lookup.

**Row Extraction:** `snapshot_range` from source rows → `write_snapshot` to
destination range/sheet.

**Transposition:** Snapshot source, iterate `(r, c)` → write to `(c, r)` in
destination. Preserve header alignment.

## Preservation Checklist

The default posture is **preserve everything not explicitly transformed**.

- **Other sheets:** Never modify them.
- **Styles:** All helper functions `copy()` font, fill, border, alignment, number_format.
- **Data outside target range:** Scope all writes to the declared output range.
- **Column widths / row heights:** Stored on `ws.column_dimensions` / `ws.row_dimensions`;
  survive row reordering since they're keyed by letter/number.
- **Merged cells, freeze panes, auto filters:** Snapshot before, restore after if
  the target range overlaps them.

## Common Pitfalls

1. **Lexical vs numeric sort** — Always `evaluate_formulas_in_range` *before*
   sorting. Formula strings sort lexically; numbers sort numerically.
2. **Evaluation order** — `evaluate_formulas_in_range` processes columns
   left-to-right. If F references D, D is evaluated first.
3. **None/zero handling** — `sort_block_rows` treats `None` as `0`.
4. **Block boundary detection** — Always use `detect_blocks`; never assume fixed
   block sizes.
5. **openpyxl data_only mode** — Do *not* use it. Load normally; the script
   parses formulas itself.
6. **Floating-point precision** — IEEE 754 may produce `224.89999999999998`
   instead of `224.9`. Do not round unless instructed. Tests compare with
   tolerance.
7. **Row heights / column widths** — Not per-cell; they live on
   `ws.row_dimensions` / `ws.column_dimensions` and survive reordering.
