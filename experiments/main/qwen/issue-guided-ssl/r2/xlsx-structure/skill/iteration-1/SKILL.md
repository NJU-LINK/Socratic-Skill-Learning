---
name: xlsx-structure
description: Structural transformations on Excel workbooks with block detection, formula evaluation, and style preservation
---

# XLSX Structure Transformation Skill

This skill handles structural transformations on Excel workbooks where data is organized in variable-length blocks separated by blank rows. The core operations include block detection, formula evaluation in dependency order, sorting/filtering within blocks, and in-place modification that preserves workbook state.

## Core Mechanisms

### 1. Formula Evaluation with Dependency Order

**Why manual evaluation is required**: openpyxl's `load_workbook()` returns formula strings (e.g., `'=B1+C1'`), not computed values. There is no built-in formula evaluator. You must manually evaluate arithmetic expressions.

**The dependency problem**: When column F contains `=D1+E1` and column D contains `=B1+C1`, evaluating F requires D's **evaluated numeric result**, not the formula string. If you evaluate columns independently, F will substitute the string `'=B1+C1'` instead of the numeric value.

**Correct approach — evaluate in dependency order**:
```python
def evaluate_formulas(block_rows, formula_col_indices, col_letter_map):
    """Evaluate formula columns in dependency order, updating in-place."""
    for col_idx in formula_col_indices:  # e.g., [3, 4, 5] for D, E, F
        for row in block_rows:
            val = row[col_idx]
            if is_formula(val):
                result = eval_formula(val, row, col_letter_map)
                if result is not None:
                    row[col_idx] = result  # Update so next column sees numeric value
```

**Formula detection**: A cell is a formula if it's a string starting with `=` or containing cell references with operators (e.g., `"B1+C1"` without the `=` prefix).

**Safe evaluation**: Replace cell references with numeric values, then use Python's `eval()` on a sanitized expression containing only arithmetic operators, digits, parentheses, and decimal points.

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
3. Scan range → detect blocks via blank-row boundaries
4. For each block:
   a. Read all cell values into list-of-lists
   b. Evaluate formula columns in dependency order (e.g., D→E→F)
   c. Stable sort by specified column (descending or ascending)
5. Write sorted values back to cell positions (only .value changes)
6. Save as output file
```

## Parameterization for Reuse

The solver script accepts these parameters:
- `--input`: Input workbook path
- `--output`: Output workbook path
- `--sheet`: Target sheet name
- `--range`: Target range (e.g., A1:H85)
- `--sort-col`: Column to sort by (e.g., D)
- `--desc` / `--asc`: Sort direction
- `--formula-cols`: Comma-separated formula columns in dependency order (e.g., D,E,F)

This allows adaptation to different family members with varying:
- Workbook topologies (different sheets, ranges)
- Transformation semantics (different sort columns, directions)
- Formula structures (different dependency chains)

## Common Pitfalls

1. **Using `data_only=True`**: This prevents reading formula strings. Load normally.
2. **Evaluating formulas out of order**: If F depends on D, evaluate D first.
3. **Checking only one column for blank rows**: Check all columns in the range.
4. **Copying styles instead of modifying in-place**: Styles are position-based; just change `.value`.
5. **Lexical sorting of numeric values**: Convert to float before sorting.
6. **Assuming fixed block sizes**: Detect blocks dynamically from blank-row boundaries.

## Verification Checklist

After solving, verify:
- [ ] Blank rows are preserved at correct positions
- [ ] Each block is sorted correctly by the specified column
- [ ] Formulas are evaluated to numeric values (no formula strings in output)
- [ ] Styles are preserved (check font, alignment, fill on a few cells)
- [ ] Other sheets are unchanged
- [ ] Values outside the target range are unchanged
- [ ] Row heights and column widths are preserved
