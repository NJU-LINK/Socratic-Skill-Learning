---
name: xlsx-structure
description: >
  Structural transformations on .xlsx workbooks: block-local sorting, filtering,
  compaction, append, reconciliation, extraction, and transposition. Covers formula
  evaluation, style preservation, block/topology detection, and output verification.
---

# xlsx-structure

Structural workbook transformations on `.xlsx` files using **openpyxl**. Read an
input workbook, apply a declared transformation, preserve all untouched state,
and write an output workbook.

## Quick-Start Checklist

```
1. Parse task instruction → extract: sheet, working range, transformation type,
   sort/filter column, sort direction, formula columns, preservation scope
2. Explore data   → ONE brief exploration call (2-3 sample rows + blank-row scan)
3. Run or import   → use scripts/transform_lib.py (do NOT rewrite functions inline)
4. Save & verify   → wb.save(output), then re-read and check correctness
```

## How to Use scripts/transform_lib.py

**Option A — Run directly for block-local sort:**
```bash
# Override defaults via CLI args or edit the __main__ block
python3 scripts/transform_lib.py /app/input.xlsx /app/output.xlsx
```

**Option B — Import as library for other transformations:**
```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))  # or the skill scripts dir
from transform_lib import (
    detect_blocks, evaluate_cell, evaluate_row,
    snapshot_row, write_evaluated_row, clear_row,
    sort_block_rows, verify_no_formulas, verify_sort_order, verify_blank_rows
)
# Then compose these functions for your specific transformation
```

**Option C — Copy and adapt the `solve_block_sort()` function** from the script
for transformations that are not simple block-local sorts. Change the parameters
(sheet, range, sort column, direction) to match the task.

**Important:** Do NOT redefine `detect_blocks`, `evaluate_cell`, `evaluate_row`,
`snapshot_row`, or `write_evaluated_row` inline — these are already correct and
tested in the library. Copying them wastes tokens and risks transcription errors.

## Task Parameter Extraction

The task instruction (in `task.yaml` or the user message) always specifies these
parameters. Extract them **before** exploring the workbook:

| Parameter | How to find it | Example |
|-----------|---------------|---------|
| **Source sheet** | Named explicitly or "Sheet1" default | `Sheet1` |
| **Working range** | Named range like `A1:H85` or "all data" | `A1:H85` |
| **Transformation type** | Verb: "sort", "filter", "append", "extract", "reconcile", "transpose" | block-local sort |
| **Sort/filter column** | Named column letter | Column D |
| **Sort direction** | "ascending" or "descending" | descending |
| **Tie-breaking rule** | "preserve original relative order" = stable sort | stable |
| **Formula columns** | "Columns D–F may contain formulas" | D, E, F |
| **Block definition** | "separated by one blank row" | blank-row delimited |
| **Preservation scope** | "all values outside A1:H85", "every input sheet" | outside working range |

If the working range is stated as a concrete range (e.g. `A1:H85`), use
`range_boundaries("A1:H85")` to get `(min_col, min_row, max_col, max_row)`.
If it says "all data", scan the sheet to find the actual extent.

## Exploration (keep it brief)

Do **one** exploration call to confirm data shape, then proceed to the solution.
Include in a single call:
- Sheet names, dimensions, max_row, max_col
- 2–3 sample rows with `type(v).__name__` and `v!r` per cell
- Blank-row scan over the working range
- Quick check for data beyond the declared range

```python
# Single efficient exploration call
wb = openpyxl.load_workbook('input.xlsx', data_only=False)
ws = wb['Sheet1']
print(f"Sheets: {wb.sheetnames}, dims: {ws.dimensions}")
for r in range(1, 4):
    for c in range(1, 9):
        v = ws.cell(r, c).value
        print(f'  ({r},{c}) {type(v).__name__}: {v!r}')
# Scan blank rows
for r in range(1, MAX_ROW+1):
    if all(ws.cell(r, c).value is None for c in range(1, MAX_COL+1)):
        print(f'  blank: row {r}')
```

**openpyxl value types** (with `data_only=False`):
- **Formula**: `str` like `'=B1+C1'` (the `=` is the first char)
- **Number**: `int` or `float` (never a string)
- **Text**: `str`
- **Empty**: `None`
- A leading `'` in Excel (text-marker) is **NOT** in the openpyxl value

Use `data_only=False` so formulas are readable as source text; evaluate them
manually to maintain control over precision and ordering.

## Decision Rules by Dimension

### 1. Workbook Topology (`workbook_topology`)

Detect the data layout from the workbook itself—**never assume fixed sizes**.

| Topology pattern           | Detection rule                                                           |
|----------------------------|--------------------------------------------------------------------------|
| Blocks separated by blanks | Scan all rows in working range; a row is blank if every cell in columns min\_col–max\_col is `None`. Maximal runs of non-blank rows between blank rows are blocks. |
| Contiguous single table    | One block spanning the full data range, no internal blanks.              |
| Multi-sheet source/target  | Iterate `wb.sheetnames`; each sheet may hold an independent scope.       |
| Style-marked regions       | Inspect cell fill/font to identify headers or category boundaries.       |
| ID-list paired with table  | One range holds an ordered key list; another holds sparse records keyed by matching column. |

**Block detection rule:** A row is blank if every cell in the declared working
columns (`min_c..max_c`) is `None`. Maximal runs of consecutive non-blank rows
form blocks. Use `detect_blocks()` from the library. Test blank-ness over the
working columns only, not the full sheet width, to avoid false blanks.

### 2. Value Evaluation

Columns may contain formulas (`=expr`), text that encodes arithmetic, or plain
numbers. All must resolve to concrete values before transformation.

**Evaluation priority:**
1. If cell value is a string starting with `=`, strip the `=`, substitute known
   cell references with their already-evaluated values, then `eval()` the
   arithmetic expression in a restricted namespace.
2. If cell value is numeric (`int`/`float`), use directly.
3. If cell value is a numeric-looking string (possibly with leading `-` or
   decimal point), parse with `float()`.
4. Otherwise treat as opaque text.

Use `evaluate_cell()` and `evaluate_row()` from the library. They handle:
- Formula strings (`=B1+C1`) via reference substitution and safe `eval()`
- Unreplaced cell references zeroed out by regex
- Numeric strings parsed via `float()`
- Row-local left-to-right evaluation (D depends on B,C; F depends on D,E)

### 3. Selection & Alignment (`selection_and_alignment_rule`)

| Rule                        | Implementation                                           |
|-----------------------------|----------------------------------------------------------|
| Numeric sort (asc/desc)     | Evaluate sort-column values; `sorted(block, key=..., reverse=...)` |
| Stable tie-breaking         | Python `sorted()` is stable; tag with `(key, original_index)` for explicit control |
| Membership in another range | Build a `set()` from the reference range; filter rows whose key is in the set |
| Header/ID identity          | Map source headers → destination headers by exact string match |
| Fill color / style predicate| Test `cell.fill.fgColor.rgb` or `cell.font.color.rgb` against target |
| Source-list order           | Iterate the ordered key list; for each key, look up the matching source row |
| Positional correspondence   | Align by row index within block (no key matching needed) |

**Descending sort with stable ties:** Use `sort_block_rows()` from the library,
or tag with `(key, original_index)` for explicit control:
```python
indexed = [(key, orig_idx, row_data) for orig_idx, (key, row_data) in enumerate(block)]
indexed.sort(key=lambda x: (-x[0], x[1]))  # descending, stable on orig_idx
```

### 4. Transformation Patterns (`transformation_semantics`)

All patterns share the same skeleton: **detect scope → evaluate → apply logic → write back.**

#### Block-local sort
Within each detected block, sort complete rows by the evaluated value of a
designated column. Blank separator rows stay in place. All columns move as a unit.

Use `solve_block_sort()` from the library directly:
```python
from transform_lib import solve_block_sort
solve_block_sort(input_path, output_path,
                 sheet_name="Sheet1", work_range="A1:H85",
                 sort_col="D", descending=True)
```
Or run `python3 scripts/transform_lib.py` directly (edit `__main__` params as needed).

#### Predicate / style-based filter & compaction
Keep rows matching a condition; compact survivors to the top of the destination.
```python
kept = [row for row in block if predicate(row)]
# Clear entire destination range, then write kept rows at top
for i, row in enumerate(kept):
    write_row(ws, dest_start + i, row)
for i in range(len(kept), total_rows):
    clear_row(ws, dest_start + i, min_col, max_col)
```

#### Header-aligned append
Match source columns to destination columns by header name; append below existing data.
```python
src_headers = [ws.cell(header_row, c).value for c in src_cols]
dst_headers = [ws.cell(header_row, c).value for c in dst_cols]
col_map = {src_headers.index(h): dst_headers.index(h) for h in src_headers if h in dst_headers}
dest_row = last_data_row + 1
for src_row in source_rows:
    for src_ci, dst_ci in col_map.items():
        ws.cell(dest_row, dst_cols[dst_ci]).value = src_row[src_ci]
    dest_row += 1
```

#### Sparse-record reconciliation
Two ranges share a key column; merge values from sparse source into destination.
```python
# Build lookup from key → source row data
source_map = {}
for row in source_rows:
    key = row[key_col]
    source_map[key] = row
# Update destination rows where key matches
for dest_row in dest_rows:
    key = dest_row[key_col]
    if key in source_map:
        for col in value_cols:
            if source_map[key][col] is not None:
                dest_row[col] = source_map[key][col]
```

#### Row extraction
Select rows meeting a criterion; write to a destination range or sheet.
```python
extracted = [row for row in all_rows if criterion(row)]
for i, row in enumerate(extracted):
    write_row(dest_ws, dest_start + i, row)
```

#### Layout transposition
Swap rows and columns in the output.
```python
for r_idx, row in enumerate(source_rows):
    for c_idx, val in enumerate(row):
        dest_ws.cell(min_col + c_idx, min_row + r_idx).value = val
```

### 5. Style Preservation (`preservation_constraints`)

**Golden rule:** Capture ALL cell style attributes BEFORE any write operation.
Use `snapshot_row()` and `write_evaluated_row()` from the library—they handle
font, fill, border, alignment, number_format, and protection via `copy.copy()`.

**Key principle for sort operations:** Styles travel WITH the row. Snapshot each
source row's styles, then when a row moves to a new position, restore that row's
snapshot to the target position.

**Preservation checklist:**
- [ ] Input sheets untouched by the transformation remain byte-identical
- [ ] Cells outside the declared output range are not modified
- [ ] Column widths and row heights in the working range are unchanged
- [ ] Merged ranges, auto-filters, freeze panes, and data validations survive
- [ ] Cell styles (font, fill, border, alignment, number format) move with data

## Verification

Run these checks on the output workbook **before** finishing. Use the library's
`verify_no_formulas()`, `verify_sort_order()`, and `verify_blank_rows()` functions,
plus these manual checks:

1. **Sheet list unchanged** — `out_wb.sheetnames == in_wb.sheetnames`
2. **Non-transformed cells identical** — spot-check cells outside the working range
3. **No unevaluated formulas** — `verify_no_formulas(ws, min_r, max_r, min_c, max_c)`
4. **Sort order correct** — `verify_sort_order(ws, blocks, sort_col_idx, descending)`
5. **Blank rows intact** — `verify_blank_rows(ws, blocks, min_r, max_r, min_c, max_c)`
6. **Styles preserved** — check `font.bold` and `alignment.horizontal` on a few cells

## Common Pitfalls

| Pitfall | Prevention |
|---------|------------|
| Assuming fixed block sizes | Always detect blocks from data; never hard-code row counts |
| Lexicographic sort on formula strings | Evaluate formulas to numbers before sorting |
| Losing cell styles on rewrite | Snapshot-then-restore pattern for every written cell |
| Corrupting separator rows | Only write to non-blank block positions; never touch blank rows |
| Modifying cells outside working range | Restrict writes to the declared output range coordinates |
| Floating-point comparison surprises | Use `sorted()` with a numeric key; accept IEEE 754 precision |
| Forgetting to copy styles for ALL columns | Iterate every column in the working range, not just the sort column |
| `data_only=True` hides formulas | Use `data_only=False`; evaluate formulas manually |
| `repr()` confusion on cell values | Use `print(f'type={type(v).__name__} value={v!r}')` per-cell |
| Partial cell-reference replacement | Sort references longest-first; remove unreplaced refs with regex |

## Reference Implementation

See `scripts/transform_lib.py` for reusable building-block functions (block
detection, cell evaluation, style snapshot/restore, row writing) that can be
composed for any transformation type. Import and adapt these rather than
writing from scratch.
