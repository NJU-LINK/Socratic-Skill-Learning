---
name: xlsx-structure
description: >
  Structural transformations on Excel workbooks: detect block/range topology,
  evaluate row-local formulas, sort/filter/reconcile/transpose data blocks,
  and write results while preserving all workbook metadata outside the
  transformation range.
---

# xlsx-structure

Reusable skill for performing structural transformations on `.xlsx` workbooks
using `openpyxl`. Covers the family of tasks where data is organized in
variable-topology workbook layouts and must be rearranged according to
evaluated numeric or predicate-based rules while preserving all surrounding
workbook state.

## When to Use

- The task asks to read an input `.xlsx`, transform data within a specified
  range or sheet region, and write the result to an output `.xlsx`.
- The transformation involves one or more of: block-local sorting,
  predicate/style-based filtering, header-aligned append, sparse-record
  reconciliation, row extraction, or layout transposition.
- Formulas or formula-text strings in cells must be evaluated to numeric
  values before sorting or writing.
- All workbook metadata (styles, filters, merged ranges, panes, other sheets,
  data outside the transformation range) must be preserved intact.

## Core Architecture

Every task in this family follows the same pipeline:

```
1. LOAD       → openpyxl.load_workbook(input_path, data_only=False)
2. DETECT     → identify topology: blocks, headers, blank separators, ranges
3. EVALUATE   → resolve formula strings to numeric values (dependency order)
4. TRANSFORM  → sort / filter / reconcile / transpose as specified
5. WRITE      → write evaluated values back, preserving cell positions for styles
6. SAVE       → save to output path; everything outside range is untouched
```

## Step-by-Step Procedure

### 1. Load Workbook

```python
import openpyxl
wb = openpyxl.load_workbook(input_path, data_only=False)
ws = wb[sheet_name]  # or wb[wb.sheetnames[0]] for first sheet
```

**Why `data_only=False`:** We need the raw formula strings to evaluate them
ourselves. Using `data_only=True` returns cached values which may be `None`
for programmatically-created files that were never opened in Excel.

### 2. Detect Block Topology

Blocks are contiguous non-blank row groups separated by blank rows. Detect
them dynamically from the data rather than assuming fixed sizes:

```python
def detect_blocks(ws, min_row, max_row, min_col, max_col):
    """Return (blocks, blank_positions) where blocks is a list of lists of
    (row_index, [cell_values]) and blank_positions is a set of blank row indices."""
    blank_positions = set()
    rows_data = []

    for row_idx in range(min_row, max_row + 1):
        vals = []
        all_none = True
        for col_idx in range(min_col, max_col + 1):
            v = ws.cell(row=row_idx, column=col_idx).value
            vals.append(v)
            if v is not None:
                all_none = False
        if all_none:
            blank_positions.add(row_idx)
            rows_data.append((row_idx, None))
        else:
            rows_data.append((row_idx, vals))

    blocks = []
    current = []
    for row_idx, vals in rows_data:
        if vals is None:
            if current:
                blocks.append(current)
                current = []
        else:
            current.append((row_idx, vals))
    if current:
        blocks.append(current)

    return blocks, blank_positions
```

**Key invariant:** Blank row positions are recorded but never moved. The
transformation only rearranges data rows within their block; blank separators
stay at their original positions.

### 3. Evaluate Row-Local Formulas

Formula strings (e.g., `'=B1+C1'`) must be resolved to numeric values. The
critical insight is **dependency order within a row**: if column F references
column D, then D must be evaluated before F.

**RECOMMENDED: Generic topological evaluator** (works for any formula structure):

```python
import re

def eval_formula(formula_str, local_vals):
    """Evaluate a row-local arithmetic formula string.
    local_vals: dict mapping column letters to numeric values.
    Returns numeric result."""
    if not isinstance(formula_str, str) or not formula_str.startswith('='):
        if formula_str is None:
            return 0.0
        return float(formula_str)

    expr = formula_str[1:]  # strip '='

    def replace_ref(match):
        col = match.group(1)
        return str(local_vals.get(col, 0.0))

    expr = re.sub(r'([A-Z]+)\d+', replace_ref, expr)
    result = float(eval(expr))
    return round(result, 10)  # remove floating-point noise


def evaluate_row_generic(vals, min_col_idx=0):
    """Auto-detect formulas and resolve dependencies topologically.
    Works for ANY column layout — no hardcoded assumptions.

    Algorithm:
      1. Raw numeric values → local map immediately.
      2. Formula cells → extract column references as dependencies.
      3. Iteratively evaluate formulas whose deps are all satisfied.
      4. Repeat until all resolved or circular dependency detected.
    """
    local = {}
    for i, v in enumerate(vals):
        col_letter = chr(ord('A') + i + min_col_idx)
        if v is not None and not (isinstance(v, str) and v.startswith('=')):
            if isinstance(v, (int, float)):
                local[col_letter] = float(v)
        elif v is None:
            local[col_letter] = 0.0  # None referenced by formulas = 0
        # Text values (non-formula strings) are NOT added to local map

    formula_cells = []
    for i, v in enumerate(vals):
        col_letter = chr(ord('A') + i + min_col_idx)
        if isinstance(v, str) and v.startswith('='):
            refs = set(re.findall(r'([A-Z]+)\d+', v[1:]))
            formula_cells.append((i, col_letter, v, refs))

    evaluated = dict(local)
    remaining = list(formula_cells)
    max_iter = len(remaining) * 2
    while remaining and max_iter > 0:
        max_iter -= 1
        for item in list(remaining):
            i, col_letter, formula_str, refs = item
            if all(ref in evaluated for ref in refs):
                evaluated[col_letter] = eval_formula(formula_str, evaluated)
                remaining.remove(item)

    # Only replace cells that were originally formula strings
    result = list(vals)
    formula_indices = {item[0] for item in formula_cells}
    for i in formula_indices:
        col_letter = chr(ord('A') + i + min_col_idx)
        if col_letter in evaluated:
            result[i] = evaluated[col_letter]
    return result
```

**Why generic over hardcoded:** The v01 anchor case has D=B+C, F=D+E, but
variants may have different formula structures (e.g., D=B*C, G=D-E, or longer
chains). The generic evaluator handles all of these without modification.

### 4. Transform (Sort / Filter / Reconcile / Transpose)

**Block-local sorting** (the v01 anchor case):

```python
for block in blocks:
    evaluated = [(row_idx, orig_vals, ev_vals) for row_idx, orig_vals, ev_vals in
                 [(ri, ov, evaluate_row(ov, ...)) for ri, ov in block]]
    # Stable sort by sort key (e.g., evaluated column D)
    evaluated.sort(key=lambda x: x[2][sort_col_index], reverse=descending)
```

Python's `sorted()` and `list.sort()` are **stable by default**, which
satisfies "preserve original relative order for ties."

### Selection and Alignment Rule Variants

The spec declares these selection patterns as in-family:

| Rule | Implementation |
|------|---------------|
| Evaluated numeric order | `sorted(block, key=lambda r: r.eval_D, reverse=True)` |
| Membership in another range | `if id_val in membership_set: keep(row)` |
| Exact header/ID identity | `if row[header_col] == target_id: match` |
| Fill color | `if cell.fill.fgColor.rgb == target_color: keep` |
| Text predicates | `if predicate(cell.value): keep` (e.g., startswith, contains) |
| Source-list order | Iterate source list; for each ID, find matching row |
| Positional correspondence | `dst[i] = src[i]` (same index in both ranges) |

**Membership-based selection example:**
```python
def filter_by_membership(blocks, id_col_idx, membership_set):
    """Keep only rows whose ID is in the membership set."""
    filtered = []
    for block in blocks:
        kept = [(ri, vals, ev) for ri, vals, ev in block 
                if ev[id_col_idx] in membership_set]
        if kept:
            filtered.append(kept)
    return filtered
```

**Source-list order alignment:**
```python
def align_to_source_list(src_blocks, id_list, id_col_idx=0):
    """Reorder src rows to match the order in id_list."""
    # Build lookup: id -> row data
    lookup = {}
    for block in src_blocks:
        for ri, vals, ev in block:
            lookup[ev[id_col_idx]] = (ri, vals, ev)
    # Return rows in id_list order
    result = []
    for target_id in id_list:
        if target_id in lookup:
            result.append(lookup[target_id])
    return result
```

**Other transformation patterns** (from spec dimensions):

**Predicate-based filtering and compaction:**
```python
def filter_blocks(blocks, predicate_fn):
    """Keep only rows matching predicate, compact within each block.
    predicate_fn: function(row_vals) -> bool
    """
    filtered = []
    for block in blocks:
        kept = [(ri, vals, ev) for ri, vals, ev in block if predicate_fn(ev)]
        if kept:
            filtered.append(kept)
    return filtered

# Example: keep rows where evaluated D > 0
filtered = filter_blocks(evaluated_blocks, lambda ev: ev[3] > 0)
```

**Header-aligned append:**
```python
def header_aligned_append(src_ws, dst_ws, src_range, dst_start_row):
    """Append src rows to dst, aligning columns by header name.
    src_range: (min_row, max_row, min_col, max_col)
    """
    # Read source headers
    src_headers = [src_ws.cell(row=src_range[0], column=c).value 
                   for c in range(src_range[2], src_range[3]+1)]
    # Read destination headers
    dst_headers = [dst_ws.cell(row=dst_start_row-1, column=c).value 
                   for c in range(1, dst_ws.max_column+1)]
    # Build column mapping: src_col_idx -> dst_col_idx
    col_map = {}
    for si, sh in enumerate(src_headers):
        if sh in dst_headers:
            col_map[si] = dst_headers.index(sh) + 1
    # Append rows
    for r in range(src_range[0]+1, src_range[1]+1):
        for si, di in col_map.items():
            dst_ws.cell(row=dst_start_row, column=di).value = \
                src_ws.cell(row=r, column=src_range[2]+si).value
        dst_start_row += 1
```

**Sparse-record reconciliation:**
```python
def reconcile_sparse(src_blocks, dst_ws, dst_range, id_col_idx=0):
    """Merge src records into dst by matching ID column.
    src_blocks: list of blocks with (row_idx, vals, ev_vals)
    dst_range: (min_row, max_row, min_col, max_col)
    """
    # Build dst lookup: id -> row_idx
    dst_lookup = {}
    for r in range(dst_range[0], dst_range[1]+1):
        id_val = dst_ws.cell(row=r, column=dst_range[2]+id_col_idx).value
        if id_val is not None:
            dst_lookup[id_val] = r
    # Merge src into dst
    for block in src_blocks:
        for _, _, ev_vals in block:
            src_id = ev_vals[id_col_idx]
            if src_id in dst_lookup:
                dst_row = dst_lookup[src_id]
                for col_idx, val in enumerate(ev_vals):
                    dst_ws.cell(row=dst_row, column=dst_range[2]+col_idx).value = val
```

**Row extraction:**
```python
def extract_rows(blocks, predicate_fn, dst_ws, dst_start_row, dst_col=1):
    """Extract rows matching predicate to destination range.
    predicate_fn: function(ev_vals) -> bool
    """
    target_row = dst_start_row
    for block in blocks:
        for _, _, ev_vals in block:
            if predicate_fn(ev_vals):
                for col_idx, val in enumerate(ev_vals):
                    dst_ws.cell(row=target_row, column=dst_col+col_idx).value = val
                target_row += 1
    return target_row - 1  # last written row
```

**Layout transposition:**
```python
def transpose_range(src_ws, src_range, dst_ws, dst_start_row, dst_col=1):
    """Transpose src range (rows become columns, columns become rows)."""
    min_r, max_r, min_c, max_c = src_range
    for r in range(min_r, max_r+1):
        for c in range(min_c, max_c+1):
            val = src_ws.cell(row=r, column=c).value
            # Transpose: (r, c) -> (dst_start_row + (c - min_c), dst_col + (r - min_r))
            dst_ws.cell(row=dst_start_row + (c - min_c), 
                       column=dst_col + (r - min_r)).value = val
```

### 5. Write Back (Preserving Styles)

The safest preservation strategy: **modify only `.value` on existing cells.**
openpyxl stores styles per cell position, so changing only the value leaves
font, fill, border, alignment, and number_format intact.

```python
# Collect data row positions (non-blank) in original order
data_positions = [r for r, v in rows_data if v is not None]

# Flatten sorted/transformed rows
all_output_rows = []
for block in sorted_blocks:
    for _, _, ev_vals in block:
        all_output_rows.append(ev_vals)

# Write values only — styles remain on their cell positions
for i, pos in enumerate(data_positions):
    for col_idx, value in enumerate(all_output_rows[i]):
        ws.cell(row=pos, column=min_col + col_idx).value = value
```

### 6. Save

```python
wb.save(output_path)
```

Everything outside the transformation range (other sheets, rows beyond the
range, columns beyond the range, merged cells, filters, panes, row heights,
column widths) is automatically preserved because we never touched it.

### Output Geometry Variants

The spec declares these output patterns as in-family:

| Geometry | Approach |
|----------|----------|
| In-place (same range) | Write back to original positions; styles preserved |
| New sheet | `wb.create_sheet('Output')`; write to new sheet |
| Append below | Find last used row in dest; write starting there |
| Insert at position | Shift existing rows down; write into gap |
| Compaction | Write only matching rows; clear remaining cells |

**Writing to a new sheet:**
```python
dst_ws = wb.create_sheet('Transformed')
# Write data to new sheet
for row_idx, vals in enumerate(output_rows, start=1):
    for col_idx, val in enumerate(vals, start=1):
        dst_ws.cell(row=row_idx, column=col_idx).value = val
# Original sheet is untouched
```

**Appending below existing data:**
```python
# Find last used row in destination
last_row = dst_ws.max_row
# Append starting from last_row + 1
for i, vals in enumerate(new_rows):
    for col_idx, val in enumerate(vals):
        dst_ws.cell(row=last_row + 1 + i, column=1 + col_idx).value = val
```

**Compaction (removing gaps):**
```python
# Write only matching rows, then clear remaining cells in range
write_row = range_start
for row_idx, vals in enumerate(source_rows):
    if should_keep(vals):
        for col_idx, val in enumerate(vals):
            ws.cell(row=write_row, column=min_col + col_idx).value = val
        write_row += 1
# Clear remaining cells in the original range
for r in range(write_row, range_end + 1):
    for c in range(min_col, max_col + 1):
        ws.cell(row=r, column=c).value = None
```

## Preservation Checklist

Before saving, verify:
- [ ] All sheets present in input are present in output
- [ ] Rows outside the transformation range are unchanged
- [ ] Columns outside the transformation range are unchanged
- [ ] Blank separator rows remain at their original positions
- [ ] Cell styles (font, fill, border) on data cells are preserved
- [ ] No formula strings remain in the output data range
- [ ] Merged ranges, filters, panes are intact

## Formula Evaluation Gotchas

1. **Dependency order matters.** If F depends on D, evaluate D first.
2. **Floating-point noise.** Use `round(result, 10)` to clean artifacts like
   `-0.2999999999999972` → `-0.3`.
3. **None values.** Treat `None` cell values as `0.0` in arithmetic.
4. **Integer vs float.** If input values are integers, the result may be an
   integer. Use `float()` consistently for arithmetic, then convert back if
   the output expects integers (e.g., for columns G, H).
5. **Non-formula cells.** If a cell in a "formula column" contains a plain
   number (not a string starting with `=`), use it directly.

## Adaptation to New Variants

When encountering a new task in this family:

1. **Read the task instruction carefully** to identify:
   - The transformation type (sort, filter, append, reconcile, extract, transpose)
   - The source and destination ranges/sheets
   - The selection/alignment rule (numeric order, membership, identity, etc.)
   - The preservation constraints

2. **Map to the pipeline:**
   - DETECT: adapt block detection to the topology (contiguous, style-marked, ID-paired)
   - EVALUATE: identify which columns contain formulas and their dependencies
   - TRANSFORM: implement the specific transformation logic
   - WRITE: determine the output geometry (same range, new sheet, appended)

3. **Test preservation** by checking that untouched regions are identical
   between input and output.

### Workbook Topology Variants

The spec declares these topology patterns as in-family:

| Topology | Detection Strategy |
|----------|-------------------|
| Blank-separated blocks | Scan for rows where all cells in range are None |
| Style-marked cells | Check `cell.fill.fgColor.rgb` or `cell.font.bold` |
| Header-mapped columns | First row contains header strings; match by name |
| Ordered ID lists | Column A (or specified) contains unique IDs |
| Sparse source/dest | Non-contiguous data; use dict-based lookup by ID |
| Multi-sheet | Iterate `wb.sheetnames`; process each as needed |

**Style-based block detection example:**
```python
def detect_blocks_by_fill(ws, min_row, max_row, min_col, max_col, target_color=None):
    """Detect blocks where rows have a specific fill color."""
    blocks = []
    current = []
    for r in range(min_row, max_row + 1):
        cell = ws.cell(row=r, column=min_col)
        fill_match = True
        if target_color is not None:
            fill_match = (cell.fill.fgColor.rgb == target_color)
        if fill_match:
            vals = [ws.cell(row=r, column=c).value for c in range(min_col, max_col+1)]
            current.append((r, vals))
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)
    return blocks
```

## Reference Script

See `scripts/xlsx_block_sort.py` for a complete, working implementation of
the block-local sorting variant (v01 anchor case). It includes both:
- `evaluate_row_generic()`: Auto-detects formulas, resolves dependencies
  topologically. Works for any column layout. **Use this for new variants.**
- `evaluate_row_v01()`: Hardcoded for the v01 anchor case. Faster but
  layout-specific.

## Skill Resource Paths

When executing inside the isolated task container at `/app`:
- The skill package is mounted read-only at `/skill/`
- SKILL.md is at `/skill/SKILL.md`
- Scripts are at `/skill/scripts/`
- You can run scripts directly: `python3 /skill/scripts/xlsx_block_sort.py`

If the mount path is not accessible, copy the relevant code from the SKILL.md
patterns into a script written inside `/app/`.

## openpyxl Style Comparison Quirk

When comparing styles between input and output workbooks, `cell.font == cell.font`
may return `False` even when all visible attributes are identical. This is an
openpyxl internal representation issue (object identity vs value equality).
To verify style preservation, compare individual attributes:
```python
assert cell_in.font.name == cell_out.font.name
assert cell_in.font.bold == cell_out.font.bold
assert cell_in.font.size == cell_out.font.size
# etc.
```
This does NOT indicate that styles were lost — the load/save cycle preserves
all style attributes correctly.
