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

## Quick Start — One-Shot Execution

**Do not reimplement from scratch.** A tested helper library is provided at
`scripts/xlsx_transform.py` (package-relative). Inside the task container it is
mounted at **`/skill/scripts/xlsx_transform.py`**.

> **IMPORTANT path rule:** `task_shell` runs inside an isolated container.
> The *only* way to reach skill resources is via `/skill/`.
> Host-filesystem paths (e.g. `loadedSkill.baseDir`) are **not accessible**
> from `task_shell` — do not try to `cp` from them.

### How to use (single `task_shell` call)

1. **Read `task.yaml`** with the `read` tool to extract parameters.
2. **Run everything in one `task_shell` command** — copy the script, then
   execute the Python template inline.  Do NOT separately inspect or dump
   the workbook data; the script detects topology and verifies the result.

```bash
mkdir -p /app/scripts && cp /skill/scripts/xlsx_transform.py /app/scripts/ && cd /app && python3 << 'PYEOF'
import sys, os
sys.path.insert(0, "/app/scripts")
from xlsx_transform import *

wb = load_workbook("/app/input.xlsx")
ws = wb["Sheet1"]          # <-- adapt sheet name from instruction

# --- topology (auto-detected; no manual inspection needed) ---
blocks    = detect_blocks(ws, col_start=1, col_end=8, row_start=1, row_end=85)
blank_rows = find_blank_rows(ws, col_start=1, col_end=8, row_start=1, row_end=85)
original_sheets = list(wb.sheetnames)
print(f"Blocks: {blocks}")

# --- evaluate formulas (left-to-right) ---
data_rows = [r for s, e in blocks for r in range(s, e + 1)]
evaluate_formulas_in_range(ws, data_rows, ["D", "F"], col_start=1, col_end=8)

# --- sort each block by key column ---
for s, e in blocks:
    sort_block_rows(ws, list(range(s, e + 1)), key_col=4, descending=True,
                    col_start=1, col_end=8)

# --- verify and save ---
errs  = verify_no_formulas(ws, data_rows, ["D", "F"])
errs += verify_sort_order(ws, [list(range(s,e+1)) for s,e in blocks],
                          key_col=4, descending=True)
errs += verify_block_structure(ws, blank_rows, col_start=1, col_end=8)
errs += verify_sheet_preservation(wb, original_sheets)
if errs:
    print("ERRORS:", errs)
else:
    wb.save("/app/output.xlsx")
    print("OK — saved /app/output.xlsx")
PYEOF
```

Adapt these values from the instruction: `col_start`, `col_end`, `row_start`,
`row_end`, `key_col` (column index), `formula_cols` (list of letters),
`descending`, and sheet name.  Everything else is automatic.

> **Do not** add extra tool calls to dump or inspect the data before or after
> running this command. The script prints block structure and verification
> results. If errors are reported, *then* investigate.

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
