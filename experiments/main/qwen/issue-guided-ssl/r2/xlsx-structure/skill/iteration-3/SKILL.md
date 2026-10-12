---
name: xlsx-structure
description: Structural transformations on Excel workbooks with block detection, formula evaluation, and style preservation
---

# XLSX Structure Transformation Skill

This skill handles structural transformations on Excel workbooks. The core mechanisms (formula evaluation, style preservation, blank row detection) are shared across all transformation types. The transformation logic varies by task.

## Quick Start

**Execute the solver script directly:**
```bash
python3 /skill/scripts/solve.py
```

This uses sensible defaults for the v01 block-sort task. For custom parameters:
```bash
python3 /skill/scripts/solve.py \
  --input /app/input.xlsx \
  --output /app/output.xlsx \
  --sheet Sheet1 \
  --range A1:H85 \
  --sort-col D \
  --desc \
  --formula-cols D,E,F
```

Or use auto-detection for formula columns:
```bash
python3 /skill/scripts/solve.py --auto-formula-cols
```

## Transformation Type Detection

The spec.yaml describes multiple transformation types. **Identify the type from the task instruction:**

### 1. Block-Local Sorting (v01)
**Keywords**: "sort", "within each block", "by column X", "descending/ascending"
**Pattern**: Detect blocks separated by blank rows, sort rows within each block by a column's evaluated value
**Implementation**: Use `solve.py` with `--sort-col` and `--desc`/`--asc`

### 2. Predicate/Style-Based Filtering and Compaction
**Keywords**: "filter", "where", "matching", "color", "style", "compact", "remove"
**Pattern**: Select rows matching a condition (value predicate, fill color, text pattern), write compacted result
**Implementation**:
```python
# Read blocks
blocks = detect_blocks(ws, min_row, max_row, min_col, max_col)

# Filter rows
filtered_rows = []
for start, end in blocks:
    for r in range(start, end + 1):
        row_data = [ws.cell(row=r, column=c).value for c in range(min_col, max_col+1)]
        if matches_predicate(row_data, predicate):  # Implement predicate logic
            filtered_rows.append(row_data)

# Write compacted result (no blank rows between)
for i, row_data in enumerate(filtered_rows):
    for j, val in enumerate(row_data):
        ws.cell(row=output_start_row + i, column=min_col + j + 1).value = val
```

### 3. Header-Aligned Append
**Keywords**: "append", "to the end", "below", "matching headers"
**Pattern**: Append rows to existing data, aligning columns by header names
**Implementation**:
```python
# Find header row and build column mapping
headers = {ws.cell(row=header_row, column=c).value: c for c in range(1, max_col+1)}

# Append new rows aligned to headers
for new_row in new_data:
    for col_name, value in new_row.items():
        if col_name in headers:
            ws.cell(row=append_row, column=headers[col_name]).value = value
    append_row += 1
```

### 4. Sparse-Record Reconciliation
**Keywords**: "reconcile", "sparse", "ID list", "match", "fill in"
**Pattern**: Match sparse source data to an ID list, fill in missing values
**Implementation**:
```python
# Read ID list
ids = [ws.cell(row=r, column=id_col).value for r in range(id_start, id_end+1)]

# Build lookup from sparse source
source_lookup = {}
for r in range(source_start, source_end+1):
    id_val = ws.cell(row=r, column=source_id_col).value
    if id_val:
        source_lookup[id_val] = [ws.cell(row=r, column=c).value for c in source_cols]

# Reconcile: for each ID, fill in from source or leave blank
for i, id_val in enumerate(ids):
    if id_val in source_lookup:
        for j, val in enumerate(source_lookup[id_val]):
            ws.cell(row=dest_start + i, column=dest_cols[j]).value = val
```

### 5. Row Extraction
**Keywords**: "extract", "copy", "rows where", "select"
**Pattern**: Extract rows matching criteria to a destination range/sheet
**Implementation**:
```python
# Read source blocks
blocks = detect_blocks(ws, min_row, max_row, min_col, max_col)

# Extract matching rows
extracted = []
for start, end in blocks:
    for r in range(start, end + 1):
        row_data = [ws.cell(row=r, column=c).value for c in range(min_col, max_col+1)]
        if matches_criteria(row_data):
            extracted.append(row_data)

# Write to destination
dest_ws = wb[dest_sheet] if dest_sheet else ws
for i, row_data in enumerate(extracted):
    for j, val in enumerate(row_data):
        dest_ws.cell(row=dest_start + i, column=dest_col + j).value = val
```

### 6. Layout Transposition
**Keywords**: "transpose", "rotate", "pivot", "rows to columns"
**Pattern**: Transpose data orientation (rows↔columns)
**Implementation**:
```python
# Read source range
source_data = []
for r in range(src_start_row, src_end_row+1):
    row = [ws.cell(row=r, column=c).value for c in range(src_start_col, src_end_col+1)]
    source_data.append(row)

# Transpose
transposed = list(zip(*source_data))

# Write transposed data
for i, row in enumerate(transposed):
    for j, val in enumerate(row):
        ws.cell(row=dest_start_row + i, column=dest_start_col + j).value = val
```

## Core Mechanisms (Shared Across All Types)

### 1. Formula Evaluation with Dependency Order

**Why manual evaluation is required**: openpyxl's `load_workbook()` returns formula strings (e.g., `'=B1+C1'`), not computed values. There is no built-in formula evaluator. You must manually evaluate arithmetic expressions.

**The dependency problem**: When column F contains `=D1+E1` and column D contains `=B1+C1`, evaluating F requires D's **evaluated numeric result**, not the formula string. If you evaluate columns independently, F will substitute the string `'=B1+C1'` instead of the numeric value.

**Correct approach — evaluate in dependency order**:
```python
def evaluate_formulas(block_rows, formula_col_indices, col_letter_map, round_precision=10):
    """Evaluate formula columns in dependency order, updating in-place."""
    for col_idx in formula_col_indices:  # e.g., [3, 4, 5] for D, E, F
        for row in block_rows:
            val = row[col_idx]
            if is_formula(val):
                result = eval_formula(val, row, col_letter_map, round_precision)
                if result is not None:
                    row[col_idx] = result  # Update so next column sees numeric value
```

**Floating point precision**: Formula results are rounded to 10 decimal places by default to avoid artifacts like `1.599999999999994` instead of `1.6`. Adjust with `--round-precision`.

**Formula detection**: A cell is a formula if it's a string starting with `=` or containing cell references with operators (e.g., `"B1+C1"` without the `=` prefix).

**Auto-detection**: Use `--auto-formula-cols` to scan the data and automatically detect which columns contain formulas, rather than specifying them manually.

**Safe evaluation**: Replace cell references with numeric values, then use Python's `eval()` on a sanitized expression containing only arithmetic operators, digits, parentheses, and decimal points.

**Multi-character columns**: The solver supports columns beyond Z (AA, AB, etc.) via `column_index_from_string()`.

### 2. Style Preservation via In-Place Modification

**Why in-place modification preserves styles**: In openpyxl, style properties (`font`, `fill`, `alignment`, `border`, `number_format`) are attributes of the **cell object at a position** (e.g., A1), not of the data it contains. When you assign only to `cell.value`, all style properties remain untouched at their positions.

**Correct pattern**:
```python
wb = openpyxl.load_workbook('input.xlsx')  # NOT data_only=True
ws = wb[sheet_name]

# For each cell in the target range, only overwrite .value:
for i, row_data in enumerate(sorted_block):
    for j, val in enumerate(row_data):
        ws.cell(row=start_row + i, column=j + 1).value = val
        # Style properties are NOT touched — they stay at their positions
```

**What this preserves automatically**:
- Other sheets (untouched)
- Values outside the target range (we only write within the specified range)
- Styles, filters, merged ranges, panes (properties of positions)
- Row heights and column widths (properties of rows/columns, not cells)

**Critical**: Do NOT use `data_only=True` when loading, as this prevents reading formula strings.

### 3. Blank Row Detection

**Definition**: A blank row separator has **all cells None** across the relevant column range (e.g., A through H). Don't just check one column — a row could have data only in another column.

**Correct implementation**:
```python
def is_blank_row(ws, row_num, min_col, max_col):
    """A row is blank if every cell in the column range is None."""
    for c in range(min_col, max_col + 1):
        if ws.cell(row=row_num, column=c).value is not None:
            return False
    return True
```

**Edge cases**:
- A cell with value `0` is NOT blank (only `None` means empty)
- A cell with a formula string `'=B8+C8'` is NOT blank (the formula string is a value)
- Check all columns in the range, not just column A

## Block Detection Algorithm

```python
def detect_blocks(ws, min_row, max_row, min_col, max_col):
    """Detect contiguous non-blank row blocks within [min_row, max_row]."""
    blocks = []
    block_start = None
    for r in range(min_row, max_row + 1):
        blank = is_blank_row(ws, r, min_col, max_col)
        if not blank:
            if block_start is None:
                block_start = r
        else:
            if block_start is not None:
                blocks.append((block_start, r - 1))
                block_start = None
    if block_start is not None:
        blocks.append((block_start, max_row))
    return blocks
```

## Stable Sorting Within Blocks

**Requirement**: Sort rows by a column's evaluated numeric value while preserving original order for ties (stable sort).

**Implementation**:
```python
def stable_sort_block(block_rows, sort_col_idx, descending=True):
    """Stable sort rows by numeric value in sort_col_idx."""
    indexed = list(enumerate(block_rows))
    if descending:
        indexed.sort(key=lambda x: (-to_numeric(x[1][sort_col_idx]), x[0]))
    else:
        indexed.sort(key=lambda x: (to_numeric(x[1][sort_col_idx]), x[0]))
    return [row for _, row in indexed]
```

Using `enumerate` and including the original index in the sort key makes the stability explicit and robust, even though Python's sort is stable by default.

## Overall Pipeline

```
1. Load workbook (NOT data_only)
2. Parse target range (e.g., A1:H85)
3. Identify transformation type from task instruction
4. For block-sort:
   a. Scan range → detect blocks via blank-row boundaries
   b. For each block:
      - Read all cell values into list-of-lists
      - Evaluate formula columns in dependency order (e.g., D→E→F)
      - Stable sort by specified column (descending or ascending)
   c. Write sorted values back to cell positions (only .value changes)
5. For other transformation types:
   - Apply the appropriate pattern from the "Transformation Type Detection" section
   - Reuse core mechanisms (formula evaluation, style preservation, blank row detection)
6. Save as output file
```

## Parameterization for Reuse

The solver script accepts these parameters:
- `--input`: Input workbook path (default: /app/input.xlsx)
- `--output`: Output workbook path (default: /app/output.xlsx)
- `--sheet`: Target sheet name (default: Sheet1)
- `--range`: Target range (default: A1:H85)
- `--sort-col`: Column to sort by (default: D)
- `--desc` / `--asc`: Sort direction (default: descending)
- `--formula-cols`: Comma-separated formula columns in dependency order (e.g., D,E,F)
- `--auto-formula-cols`: Auto-detect formula columns by scanning data
- `--round-precision`: Decimal precision for rounding formula results (default: 10)

This allows adaptation to different family members with varying:
- Workbook topologies (different sheets, ranges)
- Transformation semantics (different sort columns, directions)
- Formula structures (different dependency chains)
- Precision requirements

## Common Pitfalls

1. **Using `data_only=True`**: This prevents reading formula strings. Load normally.
2. **Evaluating formulas out of order**: If F depends on D, evaluate D first.
3. **Checking only one column for blank rows**: Check all columns in the range.
4. **Copying styles instead of modifying in-place**: Styles are position-based; just change `.value`.
5. **Lexical sorting of numeric values**: Convert to float before sorting.
6. **Assuming fixed block sizes**: Detect blocks dynamically from blank-row boundaries.
7. **Floating point precision artifacts**: Round formula results to avoid values like `1.599999999999994`.
8. **Hardcoding formula columns**: Use `--auto-formula-cols` to detect them dynamically.
9. **Assuming block-sort for all variants**: Check the task instruction for the transformation type.

## Verification Checklist

After solving, verify:
- [ ] Blank rows are preserved at correct positions (for block-sort)
- [ ] Each block is sorted correctly by the specified column (for block-sort)
- [ ] Formulas are evaluated to numeric values (no formula strings in output)
- [ ] Floating point precision is clean (no excessive decimal places)
- [ ] Styles are preserved (check font, alignment, fill on a few cells)
- [ ] Other sheets are unchanged
- [ ] Values outside the target range are unchanged
- [ ] Row heights and column widths are preserved
- [ ] Transformation matches the task instruction (sorting, filtering, appending, etc.)

## Script Location

The solver script is at: `/skill/scripts/solve.py`

Execute it directly rather than writing inline code. The script handles all core mechanisms and is parameterized for different variants. For non-block-sort transformations, adapt the code patterns from the "Transformation Type Detection" section.
