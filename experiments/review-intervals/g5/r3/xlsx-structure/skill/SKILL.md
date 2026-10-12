---
name: xlsx-structure
description: Structural transformations on Excel workbooks with block-based data, formula evaluation, and preservation of workbook state
---

# XLSX Structure Transformation Skill

This skill handles structural transformations on Excel workbooks where data is organized in variable-length blocks separated by blank rows, requiring formula evaluation, sorting, and careful preservation of workbook state.

## Core Problem Pattern

Tasks in this family involve:
- **Block-structured data**: Rows form non-empty blocks separated by one or more blank rows
- **Formula evaluation**: Cells contain formulas (as strings like `=B1+C1`) that must be evaluated to numeric values
- **Block-local transformations**: Operations (typically sorting) applied within each block independently
- **Workbook preservation**: All workbook state outside the transformation target must remain intact

## Key Technical Challenges

### 1. Formula Evaluation Without Excel Engine

openpyxl does NOT evaluate formulas. When reading a cell containing `=B1+C1`, openpyxl returns the string `'=B1+C1'` (with the `=` prefix intact). You must implement your own evaluator to compute the result.

**Strategy for row-local formulas:**
1. **Dynamically detect** which columns contain formulas by sampling data rows
2. Build a dictionary mapping column letters to their numeric values for the current row
3. Convert string-numbers (e.g., `'115.6'`) to floats
4. Replace cell references in formula strings with actual values using regex
5. Evaluate the resulting arithmetic expression with `eval()`

**Critical: Evaluation order matters for chained formulas.**
If column F contains `=D1+E1` and column D contains `=B1+C1`, you must evaluate D before F. Use **iterative dependency resolution**: evaluate all formula columns in order, repeating until no values change. This handles arbitrary dependency chains without hardcoding the order.

### 2. Dynamic Column Detection

Do not assume a fixed column layout. Different variants may have formulas in different columns, different numbers of columns, or different data types per column.

**Detection approach:**
- Sample a few data rows (e.g., rows 1, 2, and the first row of a later block)
- A column contains formulas if its sample values are strings starting with `=`
- A column contains numeric data if its sample values can be converted to float
- A column contains text if its values are non-numeric strings

### 3. Block Detection

Do not assume fixed block sizes. Detect block boundaries dynamically:

**Blank-row separators (most common):**
- A blank row is one where all cells in the data range are `None`
- Collect consecutive non-blank rows into blocks
- Preserve exactly one blank row between adjacent blocks in output

**Style-based separators:**
- Blocks may be separated by cells with specific fill colors or borders
- Example: rows with yellow fill mark block boundaries
```python
from openpyxl.styles import PatternFill

def detect_blocks_by_style(ws, start_row, end_row, num_cols, style_predicate):
    blocks = []
    current_block = []
    for row_idx in range(start_row, end_row + 1):
        # Check if first cell matches the style predicate
        cell = ws.cell(row=row_idx, column=1)
        if style_predicate(cell):
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            row_data = [ws.cell(row=row_idx, column=c).value for c in range(1, num_cols + 1)]
            current_block.append(row_data)
    if current_block:
        blocks.append(current_block)
    return blocks

# Example: blocks separated by yellow-filled rows
is_separator = lambda cell: cell.fill and cell.fill.fgColor.rgb == 'FFFFFF00'
blocks = detect_blocks_by_style(ws, 1, 85, 8, is_separator)
```

**Mixed detection:**
- Some variants may use both blank rows and style markers
- Check for blank rows first, then fall back to style-based detection if only one block is found

### 4. Stable Sorting Within Blocks

When sorting rows by a numeric column:
- Use Python's `list.sort(key=..., reverse=True)` which is stable
- Rows with equal sort keys preserve their original relative order
- Sort key must use **evaluated numeric values**, not lexical text order

### 5. Workbook State Preservation

The task typically specifies a target range (e.g., A1:H85) for the transformation. Everything outside this range must be preserved:
- Other columns in the same rows
- Rows beyond the target range
- Cell styles (fonts, fills, number formats, borders)
- Merged cells, filters, panes, row heights, column widths

**Safe approach:**
- Load the workbook with `openpyxl.load_workbook()`
- Read data from the target range
- Process and transform in memory
- Write back **only** to the target range by assigning `cell.value = new_value`
- Save the workbook

This preserves all workbook state because you never modify cells outside the target range, and assigning values to existing cells preserves their style objects.

### 5b. Cross-Sheet Operations

Some variants may read from one sheet and write to another:

```python
# Read from source sheet
ws_source = wb['SourceSheet']
data = []
for row_idx in range(start_row, end_row + 1):
    row_data = [ws_source.cell(row=row_idx, column=col).value for col in range(start_col, end_col + 1)]
    data.append(row_data)

# Process data...

# Write to destination sheet (may be same or different)
ws_dest = wb['DestSheet']  # or wb.create_sheet('NewSheet') if needed
for row_idx, row_data in enumerate(processed_data, start=start_row):
    for col_idx, value in enumerate(row_data, start=start_col):
        ws_dest.cell(row=row_idx, column=col_idx, value=value)
```

**Important:** When writing to a different sheet, preserve all other sheets unchanged. Only modify the destination sheet.

### 5c. Output Geometry Variations

The output may not always overwrite the input range:

**Append to existing data:**
```python
# Find the next empty row in the destination
next_row = ws_dest.max_row + 1
for row_data in processed_data:
    for col_idx, value in enumerate(row_data, start=start_col):
        ws_dest.cell(row=next_row, column=col_idx, value=value)
    next_row += 1
```

**Insert at specific position:**
```python
# Insert rows at a specific position (shifts existing rows down)
insert_row = 10
ws.insert_rows(insert_row, amount=len(processed_data))
for offset, row_data in enumerate(processed_data):
    for col_idx, value in enumerate(row_data, start=start_col):
        ws.cell(row=insert_row + offset, column=col_idx, value=value)
```

### 6. Floating-Point Precision

Arithmetic on floats can produce noise like `224.89999999999998` instead of `224.9`.

**Mitigation:**
- Round evaluated results to a reasonable precision (e.g., `round(result, 10)`)
- This removes noise while preserving meaningful precision
- Avoid rounding too aggressively (e.g., `round(result, 2)`) which could lose legitimate precision

## General Algorithm

```python
import openpyxl
import re

def to_float(val):
    """Convert cell value to float, handling strings and None."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        if val == '':
            return 0.0
        try:
            return float(val)
        except:
            return 0.0
    return 0.0

def evaluate_formula(formula_str, row_vals):
    """
    Evaluate a formula string given a dict of column values.
    Handles basic arithmetic: +, -, *, /, parentheses, unary minus.
    Cell references like B1, AA15 are replaced with their numeric values.
    """
    if not isinstance(formula_str, str):
        return to_float(formula_str)
    
    formula_str = formula_str.strip()
    if not formula_str.startswith('='):
        return to_float(formula_str)
    
    expr = formula_str[1:]  # Remove '='
    
    def replace_ref(match):
        col_letter = match.group(1).upper()
        return str(row_vals.get(col_letter, 0))
    
    # Replace cell references: one or more letters followed by digits
    # Handles multi-letter columns like AA, AB, etc.
    expr = re.sub(r'([A-Z]+)\d+', replace_ref, expr)
    
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        return round(float(result), 10)
    except:
        return 0.0

def detect_formula_columns(data, num_cols, sample_indices=None):
    """
    Detect which columns contain formulas by sampling data rows.
    Returns a list of column indices (0-based) that contain formulas.
    """
    if sample_indices is None:
        # Sample first row, second row, and a row from a later block
        sample_indices = [0, 1]
        # Find a row from a later block (after first blank row)
        for i, row in enumerate(data):
            if all(v is None for v in row):
                if i + 1 < len(data):
                    sample_indices.append(i + 1)
                break
    
    formula_cols = []
    for col_idx in range(num_cols):
        is_formula = False
        for si in sample_indices:
            if si < len(data):
                val = data[si][col_idx]
                if isinstance(val, str) and val.startswith('='):
                    is_formula = True
                    break
        if is_formula:
            formula_cols.append(col_idx)
    
    return formula_cols

def evaluate_row(row_data, formula_cols, num_cols):
    """
    Evaluate all formulas in a row using iterative dependency resolution.
    Returns a list of numeric values for all columns.
    Column 0 (typically text) is preserved as-is.
    """
    row_vals = {}
    
    # Initialize non-formula columns with their float values
    for col_idx in range(num_cols):
        if col_idx not in formula_cols:
            col_letter = col_to_letter(col_idx)
            row_vals[col_letter] = to_float(row_data[col_idx])
    
    # Iterative evaluation: repeat until no values change
    # This handles arbitrary dependency chains (e.g., D=B+C, F=D+E)
    for _ in range(10):  # Max iterations to prevent infinite loops
        changed = False
        for col_idx in formula_cols:
            col_letter = col_to_letter(col_idx)
            old_val = row_vals.get(col_letter)
            new_val = evaluate_formula(row_data[col_idx], row_vals)
            row_vals[col_letter] = new_val
            if old_val != new_val:
                changed = True
        if not changed:
            break
    
    # Build result: preserve column 0 as text, rest as floats
    result = [row_data[0]]  # Column A (text)
    for col_idx in range(1, num_cols):
        col_letter = col_to_letter(col_idx)
        result.append(row_vals.get(col_letter, 0.0))
    
    return result

def col_to_letter(col_idx):
    """Convert 0-based column index to Excel column letter(s)."""
    result = ''
    while col_idx >= 0:
        result = chr(65 + (col_idx % 26)) + result
        col_idx = col_idx // 26 - 1
    return result

# === Main algorithm ===

# Load workbook
wb = openpyxl.load_workbook('input.xlsx')
ws = wb['Sheet1']

# Parse target range from task description
# Example: "A1:H85" -> start_row=1, end_row=85, start_col=1, end_col=8
TARGET_RANGE = "A1:H85"  # Adjust per task
start_row, end_row = 1, 85
start_col, end_col = 1, 8
num_cols = end_col - start_col + 1

# Read target range
data = []
for row_idx in range(start_row, end_row + 1):
    row_data = [ws.cell(row=row_idx, column=col).value for col in range(start_col, end_col + 1)]
    data.append(row_data)

# Detect formula columns dynamically
formula_cols = detect_formula_columns(data, num_cols)

# Process rows: evaluate formulas
processed_rows = []
for row_data in data:
    if all(v is None for v in row_data):
        processed_rows.append(None)  # Blank row marker
        continue
    processed_rows.append(evaluate_row(row_data, formula_cols, num_cols))

# Split into blocks
blocks = []
current_block = []
for row in processed_rows:
    if row is None:
        if current_block:
            blocks.append(current_block)
            current_block = []
    else:
        current_block.append(row)
if current_block:
    blocks.append(current_block)

# Transform each block (e.g., sort by a specific column)
# The sort column and direction come from the task description
SORT_COL_IDX = 3  # 0-based index within the data range (column D = index 3)
SORT_DESCENDING = True

for block in blocks:
    block.sort(key=lambda row: row[SORT_COL_IDX], reverse=SORT_DESCENDING)

# Write back to worksheet
output_row = start_row
for block_idx, block in enumerate(blocks):
    for row_data in block:
        for col_idx, value in enumerate(row_data):
            ws.cell(row=output_row, column=start_col + col_idx, value=value)
        output_row += 1
    
    # Blank row between blocks (not after last block)
    if block_idx < len(blocks) - 1:
        for col_idx in range(num_cols):
            ws.cell(row=output_row, column=start_col + col_idx, value=None)
        output_row += 1

# Save
wb.save('output.xlsx')
```

## Transformation Types

The spec describes several transformation semantics. Here are concrete patterns for each:

### 1. Block-Local Sorting (v01 pattern)
```python
# Sort each block by a column, preserving blank row separators
for block in blocks:
    block.sort(key=lambda row: row[SORT_COL_IDX], reverse=SORT_DESCENDING)
```

### 2. Predicate-Based Filtering
```python
# Keep only rows matching a condition within each block
filtered_blocks = []
for block in blocks:
    filtered = [row for row in block if ROW_PREDICATE(row)]
    if filtered:  # Only keep non-empty blocks
        filtered_blocks.append(filtered)
blocks = filtered_blocks
```

### 3. Row Extraction
```python
# Extract specific rows from each block (e.g., first row, max row)
extracted_blocks = []
for block in blocks:
    extracted = [block[EXTRACTION_INDEX]]  # e.g., block[0] for first row
    extracted_blocks.append(extracted)
blocks = extracted_blocks
```

### 4. Layout Transposition
```python
# Transpose each block (rows become columns)
transposed_blocks = []
for block in blocks:
    if not block:
        continue
    num_rows = len(block)
    num_cols = len(block[0])
    transposed = []
    for col_idx in range(num_cols):
        new_row = [block[row_idx][col_idx] for row_idx in range(num_rows)]
        transposed.append(new_row)
    transposed_blocks.append(transposed)
blocks = transposed_blocks
```

### 5. Sparse-Record Reconciliation
```python
# Match rows from one range to another by ID, filling in missing data
# Example: ID list in column A, sparse data in columns B-D
id_to_data = {}
for row in data_rows:
    id_val = row[ID_COL]
    if id_val not in id_to_data:
        id_to_data[id_val] = []
    id_to_data[id_val].append(row)

# Reconcile: for each ID, merge sparse records
reconciled = []
for id_val in id_list:
    records = id_to_data.get(id_val, [])
    merged = merge_records(records)  # Custom merge logic
    reconciled.append(merged)
```

### 6. Header-Aligned Append
```python
# Append data to existing table, aligning by column headers
header_row = ws.cell(row=HEADER_ROW, column=1).value
header_map = {header: idx for idx, header in enumerate(header_row)}

for new_row in new_data:
    target_row = get_next_empty_row()
    for col_name, value in new_row.items():
        if col_name in header_map:
            col_idx = header_map[col_name] + 1
            ws.cell(row=target_row, column=col_idx, value=value)
```

## Adaptation Guidelines

When applying this skill to a new task:

1. **Parse the target range** from the task description (e.g., "A1:H85")
2. **Detect formula columns dynamically** — don't assume which columns contain formulas
3. **Identify the transformation type**: sorting, filtering, extraction, transposition, reconciliation, or append
4. **Identify the sort/selection key**: Which column(s) determine the transformation? Convert from Excel column letter to 0-based index
5. **Determine sort direction**: Ascending or descending (for sorting)
6. **Determine output geometry**: Same range, different sheet, append, insert?
7. **Verify preservation constraints**: What must remain unchanged outside the target range?

## Common Variations

- **Different formula patterns**: Formulas may reference different columns, use different operators (`*`, `/`, `-`), or include parentheses
- **Different formula columns**: Formulas may appear in any columns, not just D and F
- **Multiple formula dependencies**: A formula may reference another formula column, requiring iterative resolution
- **Different transformations**: Filtering, row extraction, transposition, compaction instead of sorting
- **Different sort criteria**: Ascending instead of descending, multiple sort keys, text-based sorting
- **Different block separators**: Multiple blank rows, or style-based block detection (e.g., fill color)
- **Different target ranges**: Not always A1:H85; could be any rectangular region
- **Multi-sheet workbooks**: Source and destination may be on different sheets
- **Text predicates**: Filtering based on text content rather than numeric values

## Edge Cases to Handle

- **Zero values**: Cells with value `0` or `'0'` should evaluate to `0.0`, not be treated as blank
- **Negative values**: Formulas may produce negative results; ensure sorting handles negatives correctly
- **Empty formula results**: If a formula evaluates to an error, treat it as `0.0`
- **String-numbers**: Cells may store numbers as text strings (e.g., `'115.6'`); always convert to float
- **Quoted text**: Column A may contain text with quotes or special characters; preserve as-is
- **Trailing blank rows**: The data range may have trailing blank rows beyond the last block

## Verification Checklist

After generating output, verify:
- [ ] All formulas evaluated to numeric values (no formula strings remain)
- [ ] Transformation applied correctly within each block
- [ ] Block boundaries preserved (blank rows in correct positions)
- [ ] Stable sort maintained original order for equal keys
- [ ] No floating-point noise in output values (check repr() of key values)
- [ ] Styles preserved (check a few cells' formatting)
- [ ] Data outside target range unchanged
- [ ] All sheets preserved (if multiple sheets exist)
- [ ] Correct number of data rows (count should match input)
- [ ] Sort column values are non-increasing (or non-decreasing) within each block
