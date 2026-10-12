---
name: xlsx-structure
description: >
  Structural transformations on .xlsx workbooks: block-local sorting, filtering,
  compaction, append, reconciliation, extraction, and transposition. Covers formula
  evaluation, style preservation, block/topology detection, and output verification.
---

# xlsx-structure

Structural workbook transformations on `.xlsx` files using **openpyxl**. The agent
reads an input workbook, applies a block- or range-aware transformation, preserves
all untouched state, and writes an output workbook.

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

Detect the data layout from the workbook itself—never assume fixed sizes.

| Topology pattern           | Detection rule                                                           |
|----------------------------|--------------------------------------------------------------------------|
| Blocks separated by blanks | Scan all rows in working range; a row is blank if every cell in columns A–max\_col is `None`. Maximal runs of non-blank rows between blank rows are blocks. |
| Contiguous single table    | One block spanning the full data range, no internal blanks.              |
| Multi-sheet source/target  | Iterate `wb.sheetnames`; each sheet may hold an independent scope.       |
| Style-marked regions       | Inspect cell fill/font to identify headers or category boundaries.       |
| ID-list paired with table  | One range holds an ordered key list; another holds sparse records keyed by matching column. |

**Robust block detection:**
```python
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
```

Adapt the blank-test column range (`min_c..max_c`) to the declared working
columns, not the full sheet width, to avoid false blanks from narrow data.

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

**Safe expression evaluator:**
```python
import re

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
            return float(eval(expr, {"__builtins__": {}}, {}))
        try:
            return float(s)
        except ValueError:
            return s
    return cell_value
```

**Row-local formula resolution** (common pattern `=B1+C1`, `=D1+E1`):
Evaluate left-to-right within each row. When column D depends on columns B, C,
evaluate B and C first, then D; when F depends on D and E, evaluate D first.

### 3. Selection & Alignment (`selection_and_alignment_rule`)

| Rule                        | Implementation                                           |
|-----------------------------|----------------------------------------------------------|
| Numeric sort (asc/desc)     | Evaluate sort-column values; `sorted(block, key=..., reverse=...)` |
| Stable tie-breaking         | Python `sorted()` is stable; original input order is preserved for equal keys |
| Membership in another range | Build a `set()` from the reference range; filter rows whose key is in the set |
| Header/ID identity          | Map source headers → destination headers by exact string match |
| Fill color / style predicate| Test `cell.fill.start_color.rgb` or `cell.font.color.rgb` against target |
| Source-list order           | Iterate the ordered key list; for each key, look up the matching source row |
| Positional correspondence   | Align by row index within block (no key matching needed) |

**Descending sort with stable ties (the v01 pattern):**
```python
# tag each row with its original index for stable ordering
indexed = [(evaluate_cell(row[sort_col_idx]), i, row) for i, row in enumerate(block)]
indexed.sort(key=lambda x: (-x[0] if isinstance(x[0], (int, float)) else 0, x[1]))
sorted_block = [row for _, _, row in indexed]
```

### 4. Transformation Patterns (`transformation_semantics`)

**Block-local sort** — Within each detected block, sort complete rows by the
evaluated value of a designated column. Blank separator rows stay in place.
All columns move together as a unit.

**Predicate / style-based filter** — Keep rows matching a value predicate or
cell style; compact surviving rows to the top of the destination range.

**Header-aligned append** — Match source columns to destination columns by
header name; append source rows below existing destination data.

**Sparse-record reconciliation** — Two ranges share a key column; merge values
from the sparse source into the destination where keys match.

**Row extraction** — Select rows meeting a criterion and write them to a
destination range or sheet.

**Layout transposition** — Swap rows and columns in the output.

Each pattern shares the same skeleton: detect scope → evaluate values → apply
logic → write back.

### 5. Style Preservation (`preservation_constraints`)

**Golden rule:** Capture ALL cell style attributes BEFORE any write operation.
Write them back alongside new values.

```python
STYLE_ATTRS = ('font', 'fill', 'border', 'alignment', 'number_format', 'protection')

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

**Preservation checklist:**
- [ ] Input sheets untouched by the transformation remain byte-identical
- [ ] Cells outside the declared output range are not modified
- [ ] Column widths and row heights in the working range are unchanged
- [ ] Merged ranges, auto-filters, freeze panes, and data validations survive
- [ ] Cell styles (font, fill, border, alignment, number format) move with data

## Verification

Run these checks on the output workbook before submitting:

```python
def verify(output_path, input_path, blocks_info):
    out_wb = openpyxl.load_workbook(output_path)
    in_wb  = openpyxl.load_workbook(input_path)
    out_ws = out_wb[sheet_name]
    in_ws  = in_wb[sheet_name]

    # 1. Sheet list unchanged
    assert out_wb.sheetnames == in_wb.sheetnames

    # 2. Non-transformed cells identical
    for r in preserved_rows:
        for c in preserved_cols:
            assert out_ws.cell(r, c).value == in_ws.cell(r, c).value

    # 3. Block structure intact (same blank rows, same block sizes)
    # 4. Sort order correct (monotonic in sort column within each block)
    # 5. No unevaluated formulas remain in the answer range
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

## Reference Implementation

See `scripts/solve_block_sort.py` for a complete worked example demonstrating:
block detection, row-local formula evaluation, stable descending sort, full
style preservation, and self-verification. Adapt its structure to the specific
transformation semantics declared in the task.
