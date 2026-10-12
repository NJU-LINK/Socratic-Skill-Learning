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
2. Explore data   → print types + values for first few rows (use print(), not repr lists)
3. Snapshot styles → copy.copy() every cell's style BEFORE any writes
4. Evaluate        → resolve all formulas/text-numbers to numeric values
5. Transform       → apply the declared operation (sort, filter, append, etc.)
6. Write back      → values + restored styles to destination range
7. Save & verify   → wb.save(output), then re-read and check correctness
```

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

## openpyxl Value Representation

**Critical:** When exploring data, always use `print(f'type={type(v).__name__} value={v!r}')`
rather than printing lists with `repr()` to avoid quote-confusion:

```python
# GOOD — unambiguous type and value
for c in range(1, 9):
    v = ws.cell(r, c).value
    print(f'  col={c} type={type(v).__name__} value={v!r}')

# BAD — repr of a list makes quotes ambiguous
print([ws.cell(r, c).value for c in range(1, 9)])
```

openpyxl with `data_only=False` returns:
- **Formula cells**: string `'=B1+C1'` (the `=` is the first character)
- **Numeric cells**: Python `int` or `float` (not strings)
- **Text cells**: Python `str`
- **Empty cells**: `None`

A leading `'` in Excel (text-marker) is **NOT** included in the openpyxl value.

## Core Workflow

```
1. Open workbook   → openpyxl.load_workbook(input, data_only=False)
2. Detect topology → find blocks, ranges, sheets from actual cell data
3. Snapshot styles → capture per-cell style tuples BEFORE any writes
4. Evaluate values → resolve formulas and text-numbers to numeric results
5. Transform       → apply the declared operation within each scope
6. Write back      → values + styles to destination range
7. Save            → wb.save(output)
8. Verify          → structural and semantic checks on output
```

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

**Robust block detection:**
```python
def detect_blocks(ws, min_r, max_r, min_c, max_c):
    """Return list of (start_row, end_row) tuples for non-blank blocks."""
    blank_rows = []
    for r in range(min_r, max_r + 1):
        if all(ws.cell(r, c).value is None for c in range(min_c, max_c + 1)):
            blank_rows.append(r)

    blocks = []
    start = min_r
    for br in blank_rows:
        if br > start:
            blocks.append((start, br - 1))
        start = br + 1
    if start <= max_r and any(ws.cell(start, c).value is not None
                              for c in range(min_c, max_c + 1)):
        blocks.append((start, max_r))
    return blocks
```

**Important:** Test blank-ness over the *declared working columns* (`min_c..max_c`),
not the full sheet width. Narrow data in a wide sheet would produce false blanks.

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

**Expression evaluator with cell-reference substitution:**
```python
import re

# Pre-compile a pattern to find cell references like A1, AA99, B12
_CELL_REF = re.compile(r'([A-Z]+)(\d+)')

def evaluate_cell(cell_value, ref_values=None):
    """Evaluate a cell to a numeric value.
    ref_values: dict mapping cell references (e.g. 'B1') to numeric values.
    """
    if cell_value is None:
        return None
    if isinstance(cell_value, (int, float)):
        return float(cell_value)
    if isinstance(cell_value, str):
        s = cell_value.strip()
        if s.startswith('='):
            expr = s[1:]
            if ref_values:
                # Replace cell references longest-first to avoid partial matches
                for ref in sorted(ref_values, key=len, reverse=True):
                    expr = expr.replace(ref, str(ref_values[ref]))
            # Remove any remaining unreplaced references (treat as 0)
            expr = _CELL_REF.sub('0', expr)
            return float(eval(expr, {"__builtins__": {}}, {}))
        try:
            return float(s)
        except ValueError:
            return s
    return cell_value
```

**Row-local formula resolution** (common pattern `=B1+C1`, `=D1+E1`):
Evaluate columns left-to-right within each row. When column D depends on B, C,
evaluate B and C first, then D; when F depends on D and E, evaluate D first.

```python
def evaluate_row(ws, row, min_col, max_col):
    """Evaluate all cells in a row left-to-right, returning (values, ref_values)."""
    from openpyxl.utils import get_column_letter
    ref_values = {}
    values = []
    for c in range(min_col, max_col + 1):
        cell_val = ws.cell(row, c).value
        val = evaluate_cell(cell_val, ref_values)
        ref = f"{get_column_letter(c)}{row}"
        ref_values[ref] = val if isinstance(val, (int, float)) else 0
        values.append(val)
    return values, ref_values
```

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

**Descending sort with stable ties:**
```python
# tag each row with its original index for stable ordering
indexed = [(evaluated_key, original_index, row_data)
           for original_index, (evaluated_key, row_data) in enumerate(block)]
indexed.sort(key=lambda x: (-x[0], x[1]))
sorted_block = [row_data for _, _, row_data in indexed]
```

### 4. Transformation Patterns (`transformation_semantics`)

All patterns share the same skeleton: **detect scope → evaluate → apply logic → write back.**

#### Block-local sort
Within each detected block, sort complete rows by the evaluated value of a
designated column. Blank separator rows stay in place. All columns move as a unit.

```python
for b_start, b_end in blocks:
    block_rows = list(range(b_start, b_end + 1))
    evaluated = []
    for idx, r in enumerate(block_rows):
        values, refs = evaluate_row(ws, r, min_col, max_col)
        sort_key = refs.get(f"{sort_col_letter}{r}", 0.0)
        evaluated.append((sort_key, idx, values, r))
    if descending:
        evaluated.sort(key=lambda x: (-x[0], x[1]))
    else:
        evaluated.sort(key=lambda x: (x[0], x[1]))
    # Write back: evaluated[i] goes to block_rows[i]
    for new_pos, (_, _, values, orig_row) in enumerate(evaluated):
        target_row = block_rows[new_pos]
        write_evaluated_row(ws, target_row, values, snapshots[orig_row], min_col)
```

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
Write them back alongside new values.

```python
import copy

def snapshot_cell(cell):
    return {
        'value': cell.value,
        'font': copy.copy(cell.font),
        'fill': copy.copy(cell.fill),
        'border': copy.copy(cell.border),
        'alignment': copy.copy(cell.alignment),
        'number_format': cell.number_format,
        'protection': copy.copy(cell.protection),
    }

def restore_cell(cell, snap):
    cell.value = snap['value']
    cell.font = snap['font']
    cell.fill = snap['fill']
    cell.border = snap['border']
    cell.alignment = snap['alignment']
    cell.number_format = snap['number_format']
    cell.protection = snap['protection']
```

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

Run these checks on the output workbook **before** finishing:

```python
def verify(output_path, input_path, sheet_name, min_r, max_r, min_c, max_c):
    out_wb = openpyxl.load_workbook(output_path)
    in_wb  = openpyxl.load_workbook(input_path)
    out_ws = out_wb[sheet_name]
    in_ws  = in_wb[sheet_name]

    # 1. Sheet list unchanged
    assert out_wb.sheetnames == in_wb.sheetnames

    # 2. Non-transformed cells identical (spot-check a few outside the range)
    for r in [max_r + 1, max_r + 2]:
        for c in range(min_c, max_c + 1):
            assert out_ws.cell(r, c).value == in_ws.cell(r, c).value

    # 3. Block structure intact (same blank rows, same block sizes)
    # 4. Sort order correct (monotonic in sort column within each block)
    # 5. No unevaluated formulas remain in the answer range
    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            v = out_ws.cell(r, c).value
            if isinstance(v, str) and v.startswith('='):
                print(f"WARNING: Unevaluated formula at row {r}, col {c}")

    # 6. Styles match expected (font, fill, alignment preserved)
    out_wb.close()
    in_wb.close()
```

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
