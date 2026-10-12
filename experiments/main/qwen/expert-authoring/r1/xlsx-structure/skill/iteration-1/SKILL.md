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

## 1. Workflow Overview

Every task in this family follows the same pipeline:

1. **Parse instructions** – extract the *what*, *where*, and *how* from `task.yaml`.
2. **Inspect the workbook** – discover topology (blocks, sheets, ranges, styles).
3. **Evaluate formulas** – resolve any formula strings/text in the relevant columns
   to numeric values before transformation.
4. **Apply the transformation** – sort, filter, append, transpose, etc.
5. **Write the result** – output to `/app/output.xlsx`, preserving everything the
   instructions say to keep intact.
6. **Self-verify** – reload the output and confirm invariants.

## 2. Reading the Task Definition

The `instruction` field in `task.yaml` is the authoritative spec. Extract:

| Dimension | What to look for |
|---|---|
| **Transformation type** | "sort", "filter", "append", "transpose", "extract", "reconcile" |
| **Source range** | Explicit range like `A1:H85`, or "all data on Sheet1" |
| **Destination** | Same range, new sheet, appended rows, etc. |
| **Block delimiter** | "blank row", "empty row", style change, header row |
| **Sort/filter key** | Column letter + direction (asc/desc) + tie-break rule |
| **Formula columns** | Columns that "may contain formulas or text that represents formulas" |
| **Preservation list** | Sheets, styles, filters, merged ranges, panes, row heights, column widths, data outside range |

## 3. Workbook Inspection

```python
import openpyxl
from copy import copy

wb = openpyxl.load_workbook("/app/input.xlsx")
# List all sheets
print(wb.sheetnames)
# For the target sheet:
ws = wb["Sheet1"]
print(ws.dimensions, ws.min_row, ws.max_row, ws.min_column, ws.max_column)
print("Merged:", list(ws.merged_cells.ranges))
print("Freeze:", ws.freeze_panes)
print("Filter:", ws.auto_filter.ref)
```

### 3.1 Detecting Block Boundaries

Blocks are contiguous groups of non-blank rows separated by one or more blank rows.
A row is **blank** when *every* cell in the relevant column range is `None` or empty.

```python
def detect_blocks(ws, col_range, row_range):
    """Return list of (start_row, end_row) tuples for each non-blank block."""
    blocks = []
    current_start = None
    for r in row_range:
        is_blank = all(
            ws.cell(row=r, column=c).value is None
            for c in col_range
        )
        if is_blank:
            if current_start is not None:
                blocks.append((current_start, r - 1))
                current_start = None
        else:
            if current_start is None:
                current_start = r
    if current_start is not None:
        blocks.append((current_start, row_range[-1]))
    return blocks
```

**Important:** Always detect boundaries from the data rather than assuming fixed
row counts or equal-sized blocks.

## 4. Formula Evaluation

Columns may contain:
- Actual Excel formulas (data_type `'f'` in openpyxl): `=B1+C1`
- Text strings that look like formulas: `"=B1+C1"`
- Plain numeric values
- Empty cells

### 4.1 Evaluation Strategy

Parse the formula string and evaluate using **row-local** cell references only
(references to other columns in the *same* row). Support `+`, `-`, `*`, `/`,
unary `-`, and parentheses.

```python
import re

def eval_formula(formula_str, row, ws):
    """Evaluate a simple row-local formula string.
    
    Handles patterns like =B1+C1, =D5+E5, =B2*2+C2, etc.
    Returns a float/int result, or None if unparseable.
    """
    if formula_str is None:
        return None
    s = str(formula_str).strip()
    if s.startswith("="):
        s = s[1:]
    elif s.replace(".", "").replace("-", "").isdigit():
        return float(s)
    else:
        # Try as plain number
        try:
            return float(s)
        except (ValueError, TypeError):
            pass

    # Replace cell references (e.g., B1, AA5) with their numeric values
    def replace_ref(match):
        col_letters = match.group(1)
        ref_row = int(match.group(2))
        col_idx = openpyxl.utils.column_index_from_string(col_letters)
        val = ws.cell(row=ref_row, column=col_idx).value
        if val is None:
            return "0"
        # If the referenced cell itself is a formula, evaluate it first
        if isinstance(val, str) and val.strip().startswith("="):
            val = eval_formula(val, ref_row, ws)
        return str(val) if val is not None else "0"

    expr = re.sub(r'([A-Za-z]+)(\d+)', replace_ref, s)
    # Remove spaces, then evaluate safely
    expr = expr.replace(" ", "")
    try:
        return float(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        return None
```

### 4.2 Writing Evaluated Values

After evaluation, write the **numeric result** back to the cell, replacing the
formula string. The task explicitly says: "do not leave formula strings or
unevaluated formulas in the answer range."

```python
for r in data_rows:
    for col_letter in formula_columns:
        c = openpyxl.utils.column_index_from_string(col_letter)
        cell = ws.cell(row=r, column=c)
        val = cell.value
        if isinstance(val, str) and val.strip().startswith("="):
            result = eval_formula(val, r, ws)
            if result is not None:
                cell.value = result
```

**Order matters:** If column F references column D (`=D1+E1`), evaluate D first,
then F. Process formula columns left-to-right within each row.

## 5. Transformation Patterns

### 5.1 Block-Local Sorting

The most common pattern. Within each detected block:
1. Evaluate all formula columns first.
2. Sort rows by the specified key column's evaluated value.
3. Use **stable sort** when instructed to "preserve original relative order" for ties.

```python
def sort_block(ws, block_rows, key_col, descending=True, col_range=None):
    """Sort rows within a block by key_col value. Stable sort."""
    col_range = col_range or range(ws.min_column, ws.max_column + 1)
    
    # Snapshot row data + styles
    row_data = []
    for r in block_rows:
        cells = {}
        for c in col_range:
            cell = ws.cell(row=r, column=c)
            cells[c] = {
                "value": cell.value,
                "font": copy(cell.font),
                "fill": copy(cell.fill),
                "border": copy(cell.border),
                "alignment": copy(cell.alignment),
                "number_format": cell.number_format,
            }
        row_data.append(cells)
    
    # Build sort keys (use evaluated numeric value of key_col)
    indexed = list(enumerate(row_data))
    indexed.sort(
        key=lambda pair: (
            -(pair[1][key_col]["value"] or 0) if descending
            else (pair[1][key_col]["value"] or 0)
        ),
        # Python's sort is stable, so original order is preserved for ties
    )
    
    # Write back in sorted order
    for new_idx, (orig_idx, cells) in enumerate(indexed):
        target_row = block_rows[new_idx]
        for c in col_range:
            cell = ws.cell(row=target_row, column=c)
            cell.value = cells[c]["value"]
            cell.font = cells[c]["font"]
            cell.fill = cells[c]["fill"]
            cell.border = cells[c]["border"]
            cell.alignment = cells[c]["alignment"]
            cell.number_format = cells[c]["number_format"]
```

**Key decisions:**
- Sort key must be the **evaluated numeric value**, not the formula string.
- `None` or 0 values: treat as 0 for sorting unless instructions say otherwise.
- Descending with stable sort: Python's `list.sort()` is stable; use `reverse=True`
  or negate the key.

### 5.2 Predicate/Style-Based Filtering and Compaction

Select rows matching a condition, remove non-matching rows, and compact (close
gaps so no blank rows remain between kept rows).

**Selection criteria examples:**
- Text predicate: `cell.value == "ACTIVE"` or `"error" in str(cell.value).lower()`
- Fill color: `cell.fill.fgColor.rgb == "00FF0000"` (red fill)
- Numeric threshold: `float(cell.value) > 100`
- Exclusion: `cell.value not in exclusion_set`

**Compaction pattern:**
```python
kept_rows = [r for r in data_rows if predicate(ws, r)]
# Snapshot kept rows, then write them contiguously starting at first data row
for new_idx, orig_row in enumerate(kept_rows):
    target_row = first_data_row + new_idx
    # copy data+styles from orig_row to target_row
```

### 5.3 Header-Aligned Append

Read a header row to determine column mapping, then append new records from
another source, aligning by header name rather than column position.

```python
# Build header map: header_name -> column_index
headers = {}
for c in col_range:
    h = ws.cell(row=header_row, column=c).value
    if h: headers[str(h).strip()] = c

# For each source record, write to the matching column
for src_row in source_rows:
    dest_row = next_available_row
    for src_col, header_name in source_headers.items():
        dest_col = headers.get(header_name)
        if dest_col:
            ws.cell(row=dest_row, column=dest_col).value = src_ws.cell(
                row=src_row, column=src_col).value
```

### 5.4 Sparse-Record Reconciliation

Match records by ID across sheets or ranges. Fill in missing/blank values in the
destination from a reference source.

```python
# Build lookup: id -> {col: value} from reference
ref_lookup = {}
for r in ref_rows:
    rec_id = ref_ws.cell(row=r, column=id_col).value
    ref_lookup[rec_id] = {c: ref_ws.cell(row=r, column=c).value for c in data_cols}

# Fill blanks in destination
for r in dest_rows:
    rec_id = dest_ws.cell(row=r, column=id_col).value
    if rec_id in ref_lookup:
        for c in data_cols:
            if dest_ws.cell(row=r, column=c).value is None:
                dest_ws.cell(row=r, column=c).value = ref_lookup[rec_id][c]
```

### 5.5 Row Extraction

Copy rows matching criteria to a destination range or new sheet, leaving the
source unchanged.

### 5.6 Layout Transposition

Convert rows to columns or vice versa. The key is maintaining header alignment:
if the source has headers in row 1, the transposed output should have them in
column A (or as instructed).

## 6. Preservation Strategy

The default posture is **preserve everything not explicitly transformed**.

### 6.1 What to Preserve

| Element | How |
|---|---|
| Other sheets | Do not touch them at all |
| Styles (font, fill, border, alignment) | `copy()` each style attribute when moving cells |
| Data outside target range | Do not write outside the declared output range |
| Merged cells | Avoid modifying merged regions; if the range contains merges, unmerge and re-merge after transformation |
| Column widths | Set via `ws.column_dimensions[col].width` |
| Row heights | Set via `ws.row_dimensions[row].height` |
| Freeze panes | Read `ws.freeze_panes` before modification and restore after |
| Auto filters | Read `ws.auto_filter.ref` before and restore after |
| Number formats | Copy `cell.number_format` for each moved cell |

### 6.2 Safe Write Pattern

```python
# 1. Before any modification, snapshot everything in the target range
snapshot = {}
for r in target_rows:
    for c in target_cols:
        cell = ws.cell(row=r, column=c)
        snapshot[(r, c)] = {
            "value": cell.value,
            "font": copy(cell.font),
            "fill": copy(cell.fill),
            "border": copy(cell.border),
            "alignment": copy(cell.alignment),
            "number_format": cell.number_format,
        }

# 2. Apply transformation to the snapshot data

# 3. Clear the target range, then write transformed data back
for r in target_rows:
    for c in target_cols:
        cell = ws.cell(row=r, column=c)
        cell.value = None  # clear first

# 4. Write transformed data with styles
for (r, c), data in transformed.items():
    cell = ws.cell(row=r, column=c)
    cell.value = data["value"]
    cell.font = data["font"]
    cell.fill = data["fill"]
    cell.border = data["border"]
    cell.alignment = data["alignment"]
    cell.number_format = data["number_format"]
```

### 6.3 Blank Row Handling

When blocks are separated by blank rows and the transformation reorders rows
*within* blocks:
- Blank rows must remain in their original positions.
- The number of rows per block must not change.
- Exactly one blank row between adjacent blocks.

## 7. Output and Verification

```python
wb.save("/app/output.xlsx")
```

### 7.1 Self-Verification Checklist

After saving, reload and verify:

```python
wb2 = openpyxl.load_workbook("/app/output.xlsx")
ws2 = wb2["Sheet1"]

# 1. Same number of sheets
assert len(wb2.sheetnames) == len(original_sheetnames)

# 2. Block structure preserved (same blank rows)
# 3. No formula strings in answer range (all evaluated to numbers)
for r in answer_rows:
    for c in formula_cols:
        val = ws2.cell(row=r, column=c).value
        assert not (isinstance(val, str) and val.startswith("=")), \
            f"Unevaluated formula at {openpyxl.utils.get_column_letter(c)}{r}"

# 4. Sort order correct within each block
for block in blocks:
    values = [ws2.cell(row=r, column=key_col).value for r in block]
    assert values == sorted(values, reverse=True), "Sort order violated"

# 5. Data outside range unchanged
# 6. Styles preserved (spot-check font, fill on a few cells)
```

## 8. Floating-Point Precision

IEEE 754 arithmetic can produce values like `224.89999999999998` instead of
`224.9`. **Do not round** unless the instructions explicitly say to. Tests
should compare with tolerance (e.g., `pytest.approx`). When sorting, the tiny
differences are irrelevant because `224.89999999999998` and `224.9` will sort
identically relative to other distinct values.

## 9. Common Pitfalls

1. **Lexical vs numeric sort** – Formula strings like `"=B1+C1"` sort lexically.
   Always evaluate to numbers before sorting.
2. **Stable sort requirement** – Use Python's built-in `sort()` which is stable.
   Do not use `random.shuffle` or unstable algorithms.
3. **Evaluation order** – If F references D, evaluate D first. Process columns
   left-to-right.
4. **None/zero handling** – `None` cell values should typically be treated as `0`
   for arithmetic and sorting. Check the task instructions.
5. **Block boundary detection** – Always detect from data; never assume fixed
   block sizes.
6. **Style loss during row movement** – Always `copy()` style objects; do not
   assign the same object to multiple cells.
7. **Data outside the target range** – Do not accidentally clear or overwrite it.
   Scope all writes to the declared output range.
8. **openpyxl data_only mode** – Loading with `data_only=True` gives cached
   formula values but loses the formulas. For evaluation, load normally and
   parse formulas yourself.
9. **Formula cells with data_type 'f'** – openpyxl stores Excel formulas with
   `data_type='f'` and the value as a string like `'=B1+C1'`. Always check
   `isinstance(val, str) and val.strip().startswith('=')` regardless of
   data_type.
10. **Row heights and column widths** – These are stored on `ws.row_dimensions`
    and `ws.column_dimensions`, not on individual cells. They survive row
    reordering automatically since they are keyed by row number / column letter.

## 10. Decision Rules

| Situation | Rule |
|---|---|
| Instruction says "sort by column X descending" | Evaluate X to numeric, stable sort descending within each block |
| Instruction says "preserve relative order" for ties | Use stable sort (Python default) |
| Formula column references another formula column | Evaluate referenced column first (left-to-right) |
| Block boundaries not specified | Detect by scanning for all-blank rows in the relevant column range |
| Task says "retain exactly one blank row between blocks" | Keep blank rows at their detected positions; do not add or remove |
| Instruction says "preserve styles" | `copy()` every style attribute when moving cell data |
| Output range same as input range | Transform in-place after snapshot |
| Output range is a new sheet/range | Copy data + styles to destination; leave source untouched |
| Task says "do not leave formula strings" | Replace every formula/text-formula with its evaluated numeric value |
| Unclear whether a column has formulas | Check `isinstance(val, str) and val.strip().startswith("=")` |
