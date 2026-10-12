---
name: xlsx-structure
description: Structural transformations on Excel workbooks including block sorting, formula evaluation, row filtering, and layout manipulation while preserving workbook state
---

# XLSX Structure Transformation Skill

This skill handles structural transformations on Excel workbooks where the task requires manipulating the organization, ordering, or layout of data while preserving workbook state (styles, filters, merged ranges, dimensions, etc.).

## Transformation Range Identification

**CRITICAL FIRST STEP**: Before any transformation, identify the transformation range from the task description. This range defines the boundaries for all operations (block detection, formula evaluation, output writing).

### Explicit Range Specifications
Tasks may explicitly specify the range:
- "Write the transformed range to A1:H85" → columns A-H (1-8), rows 1-85
- "Process the data in B2:F50" → columns B-F (2-6), rows 2-50
- "Transform cells C1:D100" → columns C-D (3-4), rows 1-100

**Parsing pattern**: Look for patterns like `A1:H85`, `B2:F50`, etc. Extract:
- Start column letter → convert to index (A=1, B=2, ..., Z=26, AA=27, ...)
- End column letter → convert to index
- Start row number
- End row number

### Implicit Range Specifications
Tasks may imply the range:
- "Transform the data table" → identify the contiguous block of non-empty cells
- "Process all non-empty rows" → scan for first/last non-empty row
- "Apply to the active range" → use worksheet dimensions or selection

**Detection strategy**:
1. Scan for first non-empty row (top boundary)
2. Scan for last non-empty row (bottom boundary)
3. Scan for first non-empty column (left boundary)
4. Scan for last non-empty column (right boundary)

### Ambiguous Cases
If the range is unclear:
1. Check if the task mentions specific cells or ranges elsewhere
2. Look for structural markers (headers, blank rows, column labels)
3. Use worksheet dimensions as a fallback
4. **Verify**: Ensure you're not modifying cells outside the intended scope

### Implementation
```python
# Example: Parse explicit range "A1:H85"
import re

def parse_range(range_str):
    """Parse range like 'A1:H85' into (start_col, start_row, end_col, end_row)"""
    match = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', range_str)
    if not match:
        raise ValueError(f"Invalid range: {range_str}")
    
    start_col_letter, start_row, end_col_letter, end_row = match.groups()
    start_col = col_letter_to_idx(start_col_letter)
    end_col = col_letter_to_idx(end_col_letter)
    
    return (start_col, int(start_row), end_col, int(end_row))

# Usage
start_col, start_row, end_col, end_row = parse_range('A1:H85')
transform_cols = list(range(start_col, end_col + 1))
```

**Verification**: After identifying the range, verify that:
- All data to be transformed is within the range
- No cells outside the range will be modified
- The range boundaries align with structural features (blank rows, headers)

## Core Mechanisms

### 1. Block Detection and Segmentation

Many xlsx-structure tasks involve data organized in variable-length blocks separated by blank rows. The general pattern:

```python
blocks = []
current_block = []
for row_idx in range(start_row, end_row + 1):
    row_data = read_row(ws, row_idx, cols)
    if is_blank_row(row_data):
        if current_block:
            blocks.append(current_block)
            current_block = []
    else:
        current_block.append((row_idx, row_data))
if current_block:
    blocks.append(current_block)
```

**Key insight**: Detect block boundaries from the workbook structure itself rather than assuming fixed row counts. A row is blank if all cells in the relevant column range are `None` or empty string.

### 2. Formula Evaluation

Excel formulas stored as strings (e.g., `"=B1+C1"`) must be evaluated before use. Common patterns:

- **Arithmetic operations**: Addition, subtraction, multiplication, division
- **Multiple operands**: `=B1+C1+D1`, `=(B1+C1)*0.5`
- **Cross-column dependencies**: Column F may reference column D, which itself contains a formula
- **Row-local evaluation**: Formulas reference cells within the same row

**Critical openpyxl detail**: `openpyxl.load_workbook(path, data_only=True)` returns *cached* numeric values from the last time Excel computed the workbook. These cached values are **stale** after any row rearrangement because they reflect the original layout. Always use the default mode (`data_only=False`) which returns formula strings, then evaluate formulas yourself and write numeric results back.

**Implementation approach**:
```python
import re

def col_letter_to_idx(letter):
    """Convert column letter (A, B, ..., Z, AA, ...) to 1-based index"""
    return sum((ord(c) - ord('A') + 1) * (26 ** i) for i, c in enumerate(reversed(letter)))

def evaluate_formula(formula_str, row_data):
    """Evaluate a row-local formula like =B1+C1, =D1-E1*0.5, etc.
    
    Args:
        formula_str: Formula string like "=B1+C1"
        row_data: Dict mapping column indices (integers) to values
    
    Returns:
        Evaluated numeric result, rounded to eliminate IEEE 754 artifacts
    """
    if not isinstance(formula_str, str) or not formula_str.startswith('='):
        return formula_str  # already a literal value
    
    expr = formula_str[1:]  # strip '='
    
    # Replace cell references (e.g. B1, D3) with their numeric values
    def replace_ref(m):
        col_letter, row = m.group(1), m.group(2)
        col_idx = col_letter_to_idx(col_letter)
        return str(float(row_data[col_idx]))
    
    numeric_expr = re.sub(r'([A-Z]+)(\d+)', replace_ref, expr)
    
    # Evaluate using Python arithmetic (only +, -, *, /, parens, literals)
    # Whitelist allowed characters to prevent injection
    allowed = set('0123456789.+-*/() ')
    if not all(c in allowed for c in numeric_expr):
        raise ValueError(f"Unsafe formula: {formula_str}")
    
    result = eval(numeric_expr)  # safe: only digits + operators
    # CRITICAL: Round to eliminate IEEE 754 artifacts
    return round(result, 10)
```

This handles `=B1+C1`, `=D1-E1`, `=B1*C1/2`, `=(B1+C1)*0.5`, etc.

**Critical implementation detail**: The formula evaluator converts column letters (from the formula) to integer indices to match the row_data dictionary keys. This ensures consistency when row_data uses integer column indices (the natural representation when reading from openpyxl).

**Critical pitfall**: IEEE 754 floating-point arithmetic produces artifacts like `-0.2999999999999972` instead of `-0.3`. Always round evaluated results to a sensible precision (10 decimal places is safe for inputs with ≤1 decimal place and simple arithmetic).

**Evaluation order matters**: If column F references column D, evaluate D first, then use the evaluated D value when computing F.

**Check ALL columns in the formula range**: The task may specify "Columns D–F may contain formulas" — this means check columns D, E, AND F, not just D and F. Even if some columns appear to contain only numeric values in the current variant, always check the entire specified range. A different variant may have formulas in any of those columns.

### 3. Stable Sorting with Style Preservation

When sorting "complete rows", the row's identity includes both data and cell-level formatting. The correct pattern:

```python
from copy import copy

# Capture row as a unit (values + styles)
def capture_row(ws, row_idx, cols):
    row_data = {col: ws.cell(row=row_idx, column=col).value for col in cols}
    styles = {
        col: {
            'font': copy(ws.cell(row=row_idx, column=col).font),
            'fill': copy(ws.cell(row=row_idx, column=col).fill),
            'border': copy(ws.cell(row=row_idx, column=col).border),
            'alignment': copy(ws.cell(row=row_idx, column=col).alignment),
            'number_format': ws.cell(row=row_idx, column=col).number_format,
        }
        for col in cols
    }
    return (row_idx, row_data, styles)

# Sort with stable ordering
sorted_block = sorted(
    block,
    key=lambda x: sort_key(x[1]),  # x[1] is row_data
    reverse=True  # or False depending on task
)

# Write back with styles
for target_row, (orig_idx, row_data, styles) in enumerate(sorted_block, start=1):
    for col in cols:
        cell = ws.cell(row=target_row, column=col)
        cell.value = row_data[col]
        cell.font = styles[col]['font']
        cell.fill = styles[col]['fill']
        cell.border = styles[col]['border']
        cell.alignment = styles[col]['alignment']
        cell.number_format = styles[col]['number_format']
```

**Why this matters**: If you only move values without styles, rows with distinct formatting (highlighted rows, colored fills, different number formats) will have their styles scrambled. The task says "sort complete rows" — the row moves as a unit.

### 4. Blank Row Handling

Blank rows serve as separators between blocks. When reconstructing output:

- Preserve blank row positions: exactly one blank row between adjacent blocks
- Preserve blank row styles: blank rows may have their own formatting (e.g., bold headers in column D)
- Capture blank row styles from the original and reuse them

```python
# Capture blank row styles
blank_row_indices = []
for row_idx, row_data, styles in all_rows:
    if is_blank_row(row_data):
        blank_row_indices.append((row_idx, styles))

# When writing output, interleave blocks with blank rows
output_rows = []
for block_idx, block in enumerate(blocks):
    output_rows.extend(block)
    if block_idx < len(blocks) - 1:
        blank_styles = blank_row_indices[block_idx][1]
        blank_data = {col: None for col in cols}
        output_rows.append((blank_data, blank_styles))
```

### 5. Preservation Constraints

Tasks specify what must remain intact outside the transformation range:

- **Input sheets**: All sheets other than the target must remain unchanged
- **Values outside range**: Data outside the specified range (e.g., outside A1:H85) must not be modified
- **Workbook state**: Styles, filters, merged ranges, panes, row heights, column widths must be preserved

**Implementation**: Load the workbook, modify only the specified range, then save. openpyxl preserves workbook-level properties automatically.

```python
wb = openpyxl.load_workbook('input.xlsx')
ws = wb['Sheet1']

# Modify only A1:H85
# ... transformation logic ...

wb.save('output.xlsx')  # All other properties preserved
```

## Family Variation Axes

The xlsx-structure family varies along these dimensions:

### 1. Transformation Semantics
- **Block-local sorting**: Sort rows within each block by a computed or specified column
- **Predicate-based filtering**: Select rows matching criteria, compact blocks
- **Header-aligned append**: Add rows aligned to header structure
- **Sparse-record reconciliation**: Match sparse source data to destination structure
- **Row extraction**: Extract specific rows or ranges
- **Layout transposition**: Convert rows to columns or vice versa

### 2. Workbook Topology
- **Single sheet vs. multi-sheet**: Source and destination may be on different sheets
- **Contiguous tables vs. repeated blocks**: Data may be continuous or separated by blanks
- **Style-marked cells**: Selection criteria may be based on cell formatting (fill color, font)
- **Ordered ID lists**: Rows may be selected based on membership in another range

### 3. Selection and Alignment Rules
- **Evaluated numeric order**: Sort by computed formula values, not lexical text
- **Membership predicates**: Select rows based on ID lists or value ranges
- **Exact header/ID identity**: Match on specific column values
- **Fill color or text predicates**: Filter based on cell formatting or text patterns
- **Source-list order**: Preserve order from a reference list
- **Positional correspondence**: Align by row position

### 4. Output Geometry
- **Existing vs. new destination**: Write to existing sheet or create new one
- **Range specification**: Specific range (e.g., A1:H85) or dynamic
- **Orientation**: Rows vs. columns, append vs. insert vs. replace
- **Compaction boundary**: Remove blank rows, merge blocks, or preserve structure

### 5. Preservation Constraints
- **Input sheets**: Which sheets must remain unchanged
- **Unrelated values**: Data outside transformation range
- **Existing styles**: Cell formatting, fonts, fills, borders
- **Dimensions**: Row heights, column widths
- **Filters, merged ranges, panes**: Workbook-level features

## Common Pitfalls and Solutions

### 1. Floating-Point Artifacts
**Problem**: `float("-112.3") + float("112")` produces `-0.2999999999999972`  
**Solution**: Round evaluated formula results: `round(result, 10)`

### 2. Style Scrambling During Sort
**Problem**: Moving values without styles scrambles row-level formatting  
**Solution**: Capture and apply complete row records (values + styles) as units

### 3. Formula Evaluation Order
**Problem**: Column F references column D, but D contains a formula  
**Solution**: Evaluate D first, then use evaluated D value when computing F

### 4. Blank Row Detection
**Problem**: Assuming fixed block sizes instead of detecting from structure  
**Solution**: Scan for blank rows (all cells None or empty) to find block boundaries

### 5. Lexical vs. Numeric Sorting
**Problem**: Sorting "10" before "2" because of string comparison  
**Solution**: Convert to numeric values before sorting: `float(value)`

### 6. Incomplete Style Capture
**Problem**: Capturing only font/fill but missing border/alignment/number_format  
**Solution**: Capture all style attributes: font, fill, border, alignment, number_format

### 7. Column Letter vs Index Mismatch
**Problem**: Formula evaluator expects column letters (from formula text) but row_data uses integer indices (from openpyxl)  
**Solution**: Convert column letters to indices in the formula evaluator using `col_letter_to_idx()` function. Ensure consistent data model throughout the implementation.

### 8. Incomplete Formula Range Checking
**Problem**: Task says "Columns D–F may contain formulas" but only checking D and F, missing potential formulas in E  
**Solution**: Check ALL columns in the specified range (D, E, and F), not just the ones that appear to have formulas in the current variant. Different variants may have formulas in any column within the range.

### 9. Formula Evaluation Corrupts Blank Row Detection
**Problem**: Evaluating formulas BEFORE detecting blocks can corrupt blank row detection. If you add an else branch to coerce non-formula values to float (e.g., `row_data[4] = float(d_val) if d_val else 0.0`), blank rows get numeric values and become invisible to `is_blank_row()`.  
**Solution**: **Always detect blocks FIRST, then evaluate formulas only within blocks.** Never modify blank rows. The correct order is: (1) read all rows, (2) detect blocks and identify blank rows, (3) evaluate formulas only within non-blank blocks. This ordering dependency is critical and must be explicit in the implementation.

### 10. Transformation Range Misidentification
**Problem**: Incorrectly parsing or inferring the transformation range leads to either missing data (range too small) or modifying cells that should be preserved (range too large).  
**Solution**: 
- For explicit ranges like "A1:H85", parse systematically: extract column letters and row numbers, convert to indices
- For implicit ranges, scan the worksheet to find boundaries (first/last non-empty row/column)
- **Verify boundaries**: Check that all data to be transformed is within the range and no cells outside will be modified
- When in doubt, check the task description for additional context or structural markers
- **Test**: After implementation, verify that cells just outside the range boundaries are unchanged

## Verification Checklist

Before declaring a solution complete:

1. **Transformation range**: Correctly identified from task description, boundaries verified
2. **Block structure**: Correct number of blocks, correct row counts per block
3. **Sorting order**: Each block sorted by specified criterion (descending/ascending)
4. **Stable sort**: Ties preserve original relative order
5. **Formula evaluation**: All formulas evaluated, no formula strings remain
6. **Floating-point precision**: No artifacts like `-0.2999999999999972`
7. **Blank row positions**: Exactly one blank row between adjacent blocks
8. **Style preservation**: Cell formatting moves with data during sorting
9. **Blank row styles**: Blank rows retain their original formatting
10. **Preservation constraints**: Data outside transformation range unchanged
11. **Workbook state**: Column widths, row heights, filters, merged ranges preserved
12. **Range boundaries**: No cells modified outside the specified transformation range

## Example: Block Sorting Task

**Task**: Sort rows within each block by evaluated column D (descending), preserve original order for ties. Columns D–F may contain formulas.

**Solution pattern**:
```python
# 1. Define ranges
cols = list(range(1, 9))  # A-H (columns 1-8)

# 2. Read all rows with styles (using integer column indices)
all_rows = [capture_row(ws, r, cols) for r in range(1, 86)]

# 3. Detect blocks FIRST (before any formula evaluation modifies row_data)
# CRITICAL: Must detect blocks before evaluating formulas to preserve blank row detection
blocks = []
blank_rows_info = []
current_block = []
for row_idx, row_data, styles in all_rows:
    if is_blank_row(row_data, cols):
        if current_block:
            blocks.append(current_block)
            current_block = []
        blank_rows_info.append((row_idx, row_data, styles))
    else:
        current_block.append((row_idx, row_data, styles))
if current_block:
    blocks.append(current_block)

# 4. Evaluate formulas ONLY within blocks (never touch blank rows)
# CRITICAL: Evaluating formulas before detecting blocks can corrupt blank row detection
for block in blocks:
    for row_idx, row_data, styles in block:
        # Evaluate D first (depends on B, C)
        if isinstance(row_data[4], str) and row_data[4].startswith('='):
            row_data[4] = evaluate_formula(row_data[4], row_data)
        # Then E (if formula exists)
        if isinstance(row_data[5], str) and row_data[5].startswith('='):
            row_data[5] = evaluate_formula(row_data[5], row_data)
        # Then F (depends on D, E - uses evaluated values)
        if isinstance(row_data[6], str) and row_data[6].startswith('='):
            row_data[6] = evaluate_formula(row_data[6], row_data)

# 5. Sort each block by column D (index 4)
for block in blocks:
    block.sort(key=lambda x: float(x[1][4]), reverse=True)

# 6. Write back with blank row separators
write_blocks_to_sheet(ws, blocks, blank_rows_info, cols)

# 7. Save
wb.save('output.xlsx')
```

**Key points**:
- **Detect blocks BEFORE evaluating formulas**: If you evaluate formulas first and accidentally modify blank rows (e.g., by adding an else branch to coerce values to float), blank rows become invisible to `is_blank_row()` and block detection fails silently
- Use integer column indices consistently (1-based, matching openpyxl)
- Check ALL columns in the formula range, not just the ones that appear to have formulas
- Evaluate in dependency order (D before F when F references D)
- The formula evaluator converts column letters to indices automatically
- **Never modify blank rows**: They serve as block separators and must remain unchanged

## Generalization Strategy

When encountering a new xlsx-structure task:

1. **Identify transformation type**: Sorting, filtering, extraction, transposition, etc.
2. **Map workbook topology**: Single/multi-sheet, contiguous/blocked, style-marked
3. **Determine selection rule**: Numeric order, membership, exact match, predicate
4. **Specify output geometry**: Destination sheet, range, orientation, append/insert
5. **List preservation constraints**: What must remain unchanged
6. **Apply appropriate mechanisms**: Use the patterns above for each aspect
7. **Verify comprehensively**: Check all items in the verification checklist

The key is to decompose the task into these orthogonal dimensions and apply the corresponding mechanism for each.
