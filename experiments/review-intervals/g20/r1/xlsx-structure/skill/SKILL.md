---
name: xlsx-structure
description: Structural transformations on Excel workbooks including block-local sorting, formula evaluation, filtering, and data reorganization while preserving workbook state
---

# XLSX Structure Transformation Skill

This skill handles structural transformations on Excel workbooks, including block-based sorting, formula evaluation, filtering, and data reorganization while preserving all workbook state outside the transformation range.

## Core Concepts

### Workbook Structure
- **Blocks**: Contiguous non-empty rows separated by blank rows (rows where all cells in the data range are empty)
- **Formulas**: Cells containing `=expression` that reference other cells with arithmetic operations
- **Styles**: Cell formatting including fonts, fills, borders, alignments, number formats
- **Workbook state**: Column widths, row heights, merged cells, filters, sheet views/panes

### Transformation Pipeline
1. **Load workbook** preserving all state
2. **Detect structure** (blocks, blank rows, data range)
3. **Evaluate formulas** to numeric values
4. **Apply transformation** (sort, filter, reorganize) within blocks
5. **Write results** preserving styles and workbook state
6. **Save output**

## Detailed Procedures

### 1. Loading and Structure Detection

```python
import openpyxl
from copy import copy

wb = openpyxl.load_workbook(input_path)
ws = wb[sheet_name]

# Detect blank rows in the target range
def is_blank_row(ws, row_idx, col_range):
    """Check if all cells in col_range are empty/None."""
    for col_idx in col_range:
        cell = ws.cell(row=row_idx, column=col_idx)
        if cell.value is not None and str(cell.value).strip() != '':
            return False
    return True

# Find blank rows to identify block boundaries
blank_rows = [r for r in range(start_row, end_row + 1) 
              if is_blank_row(ws, r, range(start_col, end_col + 1))]

# Build blocks as (start_row, end_row) pairs
blocks = []
prev = start_row - 1
for br in blank_rows:
    if br > prev + 1:
        blocks.append((prev + 1, br - 1))
    prev = br
if prev < end_row:
    blocks.append((prev + 1, end_row))
```

### 2. Formula Evaluation (Hybrid Approach)

**Critical**: Always prefer Excel's cached computed values when available. When an xlsx file was last saved by Excel/LibreOffice, each formula cell stores a cached computed value alongside the formula string. Use `data_only=True` to read these cached values.

```python
# Load TWO handles to the same workbook
wb_formulas = openpyxl.load_workbook(input_path)           # has formula strings + styles
wb_data = openpyxl.load_workbook(input_path, data_only=True)  # has cached numeric values

ws_f = wb_formulas[sheet_name]
ws_d = wb_data[sheet_name]

def evaluate_cell(ws_f, ws_d, row, col):
    """Prefer cached value; fall back to manual evaluation."""
    cached = ws_d.cell(row=row, column=col).value
    if cached is not None:
        return cached  # Excel's own computation — trust it
    
    # Fallback: manual evaluation (needed when file was never opened in Excel)
    formula = ws_f.cell(row=row, column=col).value
    if isinstance(formula, str) and formula.startswith('='):
        return evaluate_formula(ws_f, ws_d, formula, row, col)
    return formula

def evaluate_formula(ws_f, ws_d, formula_str, current_row, current_col):
    """Evaluate formula with correct operator precedence using eval()."""
    if not (isinstance(formula_str, str) and formula_str.startswith('=')):
        return formula_str
    
    expr = formula_str[1:]  # Remove '='
    
    # Replace cell references with their numeric values
    import re
    def replace_ref(match):
        col_letter = match.group(1).upper()
        row_num = int(match.group(2))
        col_idx = ord(col_letter) - ord('A') + 1
        
        # Recursively evaluate the referenced cell
        cell_val = evaluate_cell(ws_f, ws_d, row_num, col_idx)
        
        if cell_val is None:
            return '0'
        return str(float(cell_val))
    
    # Replace all cell references (e.g., B1, $B$1, B$1, $B1)
    numeric_expr = re.sub(r'\$?([A-Za-z]+)\$?(\d+)', replace_ref, expr)
    
    # Safe evaluation of arithmetic-only expression
    # Only allow numbers, operators, parentheses, whitespace
    if re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', numeric_expr):
        return eval(numeric_expr)  # Handles operator precedence correctly
    else:
        raise ValueError(f"Unsafe expression: {numeric_expr}")
```

**Key principles**:
1. **Always prefer cached values**: Excel's cached computation is authoritative. Manual evaluation may produce slightly different results due to IEEE 754 representation differences.
2. **Handle operator precedence**: Use `eval()` after substituting cell references to correctly handle `*`, `/`, and mixed operators (e.g., `=B1+C1*D1` must compute `B1+(C1*D1)`, not `(B1+C1)*D1`).
3. **Recursive evaluation**: When a formula references another formula cell, recursively evaluate it first.
4. **Read before write**: Evaluate all formulas and read all values before writing any results to avoid overwriting cells needed for subsequent evaluations.

### 3. Reading Block Data with Styles

**Sequencing principle**: Read ALL values before ANY writes. This is essential when rearranging rows in-place, as writing sorted row 1 into position 1 would overwrite the original cell, making it unavailable for subsequent formula evaluations.

```python
def read_block_data(ws_f, ws_d, start_row, end_row, col_range, formula_columns):
    """Read all rows in a block with evaluated values and styles."""
    rows = []
    for row_idx in range(start_row, end_row + 1):
        row_values = []
        row_styles = []
        
        for col_idx in col_range:
            cell_f = ws_f.cell(row=row_idx, column=col_idx)
            
            # Evaluate formulas using hybrid approach
            if col_idx in formula_columns:
                val = evaluate_cell(ws_f, ws_d, row_idx, col_idx)
            else:
                val = cell_f.value
            
            row_values.append(val)
            
            # Preserve style from formula workbook
            row_styles.append({
                'font': copy(cell_f.font),
                'fill': copy(cell_f.fill),
                'border': copy(cell_f.border),
                'alignment': copy(cell_f.alignment),
                'number_format': cell_f.number_format,
            })
        
        rows.append((row_values, row_styles))
    
    return rows
```

**Correct workflow**:
```python
# Phase 1: Read all blocks completely
all_block_data = {}
for start, end in blocks:
    rows = read_block_data(ws_f, ws_d, start, end, range(1, 9), formula_columns)
    all_block_data[(start, end)] = rows

# Phase 2: Transform each block in memory
for key in all_block_data:
    all_block_data[key].sort(key=lambda r: r[0][sort_col_idx], reverse=True)

# Phase 3: Write all blocks back
for (start, end), rows in all_block_data.items():
    write_block_data(ws_f, rows, start, range(1, 9))
```

### 4. Applying Transformations

#### Block-Local Sorting

```python
def sort_block(rows, sort_col_idx, descending=True):
    """Sort rows by a column value (stable sort)."""
    # Python's sort is stable, preserving original order for equal values
    rows.sort(key=lambda r: r[0][sort_col_idx] if r[0][sort_col_idx] is not None else 0,
              reverse=descending)
    return rows
```

#### Other Transformations

- **Filtering**: Remove rows matching a predicate
- **Reordering**: Rearrange rows based on external criteria
- **Compaction**: Remove blank rows within a block
- **Extraction**: Select specific rows or columns

### 5. Writing Results

```python
def write_block_data(ws, rows, start_row, col_range):
    """Write row data back to worksheet with styles."""
    for i, (row_values, row_styles) in enumerate(rows):
        target_row = start_row + i
        
        for j, col_idx in enumerate(col_range):
            cell = ws.cell(row=target_row, column=col_idx)
            val = row_values[j]
            style = row_styles[j]
            
            # Write value
            cell.value = val
            
            # Apply style
            cell.font = style['font']
            cell.fill = style['fill']
            cell.border = style['border']
            cell.alignment = style['alignment']
            cell.number_format = style['number_format']
```

### 6. Preservation Checklist

Before saving, verify:
- [ ] All sheets preserved (don't delete or reorder sheets)
- [ ] Values outside transformation range unchanged
- [ ] Column widths preserved
- [ ] Row heights preserved
- [ ] Merged cells preserved
- [ ] Filters preserved
- [ ] Sheet views/panes preserved
- [ ] Cell styles (fonts, fills, borders) preserved

```python
# These are automatically preserved by openpyxl when you don't modify them
# Just ensure you only write to the target range
wb.save(output_path)
```

## Reasoning About Transformation Types

The read-transform-write pipeline is invariant, but the **transform phase** varies based on the transformation semantics. Here's how to reason about different transformation types:

### Classification Framework

Ask: **What changes and what stays the same?**

1. **Row-level transformations** (sort, filter, reorder):
   - **What changes**: Row order or presence
   - **What stays the same**: Cell values, styles, column structure
   - **Pipeline impact**: Read all rows → transform in memory → write back (possibly fewer rows)
   - **Key consideration**: If row count changes, you must handle the "gap" (e.g., clear cells below compacted data)

2. **Cell-level transformations** (formula evaluation, value mapping):
   - **What changes**: Individual cell values
   - **What stays the same**: Row structure, order, styles
   - **Pipeline impact**: Read → transform each cell → write back in place
   - **Key consideration**: Formulas must be evaluated before sorting if sort key depends on formula result

3. **Structural transformations** (transpose, reshape):
   - **What changes**: Row/column orientation
   - **What stays the same**: Data values (possibly reordered)
   - **Pipeline impact**: Read → reorganize dimensions → write to different geometry
   - **Key consideration**: Styles may need to be transposed too (row heights ↔ column widths)

### Handling Row Count Changes

When the transformation changes the number of rows (filtering, compaction):

**Principle**: The output range must match the transformation result exactly.

- **Filtering** (removing rows): After writing filtered data, clear cells in the original range that are now beyond the new data boundary
  ```python
  # After writing filtered rows
  for row_idx in range(new_end + 1, original_end + 1):
      for col_idx in col_range:
          ws.cell(row=row_idx, column=col_idx).value = None
  ```

- **Compaction** (removing blanks within blocks): Similar to filtering, but blanks are removed within blocks rather than entire rows being removed

- **Appending/Inserting**: Write new data at the target position, shifting existing data if needed

### Reasoning About Workbook Topology

Different topologies affect where you read from and write to:

1. **Single sheet, contiguous range** (v01):
   - Read from range → transform → write back to same range
   - Simplest case, well-covered by the example workflow

2. **Multiple sheets**:
   - Read from source sheet(s) → transform → write to destination sheet(s)
   - **Key principle**: Always use the correct worksheet object for each operation
   - **Style handling**: Copy styles from source, not destination

3. **Repeated blocks separated by blanks** (v01):
   - Detect block boundaries from blank rows
   - Apply transformation within each block independently
   - Preserve blank row separators

4. **Sparse data with ID-based alignment**:
   - Read ID list and data separately
   - Match by ID, preserving ID list order
   - Handle missing IDs gracefully (skip or mark as missing)

5. **Header-mapped columns**:
   - Don't assume fixed column positions
   - Read headers first, build column index map
   - Use map to access columns by name rather than position

### Decision Tree for Transform Phase

```
What does the task ask you to do?
├─ Reorder rows? → Sort within blocks or globally
├─ Remove rows? → Filter by predicate, then clear gap
├─ Remove blanks? → Compact within blocks
├─ Change orientation? → Transpose rows ↔ columns
├─ Match by ID? → Build ID index, align by key
├─ Copy/move data? → Read from source, write to destination
└─ Evaluate formulas? → Hybrid cached/manual evaluation
```

**Combining transformations**: If the task requires multiple operations (e.g., "filter then sort"), apply them in sequence during the transform phase. Order matters: filter first (reduces data), then sort (reorders filtered data).

## Workflow Decision Guide

When approaching a new xlsx-structure task:

### Step 1: Parse the Task Description
Identify:
- **Source**: Where is the input data? (sheet name, range, structure)
- **Transformation**: What operation(s) to perform? (sort, filter, compact, etc.)
- **Destination**: Where should output go? (same range, different sheet, append?)
- **Preservation**: What must remain unchanged? (other sheets, styles, values outside range)

### Step 2: Explore the Workbook
```python
# Always start by exploring the workbook structure
wb = openpyxl.load_workbook(input_path)
print("Sheets:", wb.sheetnames)

ws = wb[sheet_name]
print(f"Dimensions: {ws.dimensions}")
print(f"Max row: {ws.max_row}, Max col: {ws.max_column}")

# Look at the data structure
for row_idx in range(1, min(20, ws.max_row + 1)):
    vals = [ws.cell(row=row_idx, column=c).value for c in range(1, min(9, ws.max_column + 1))]
    print(f"Row {row_idx}: {vals}")

# Check for formulas, styles, merged cells, etc.
```

### Step 3: Identify Structure
- Are there blocks separated by blank rows?
- Are there headers?
- Are there formulas that need evaluation?
- Are there styles that carry meaning (e.g., colored cells)?

### Step 4: Choose Approach
Based on the task description:

| Task Description Keywords | Approach |
|---------------------------|----------|
| "sort", "order by", "descending", "ascending" | Block sorting (Pattern 1) |
| "remove blanks", "compact", "dense" | Compaction within blocks |
| "copy to another sheet", "move data" | Cross-sheet read/write |
| "filter", "where", "if", "condition" | Predicate-based row selection |
| "color", "style", "format", "highlighted" | Style-based selection (requires careful Color object handling) |
| "match by ID", "align", "lookup" | ID-based alignment |
| "append", "add to end", "insert at" | Range append/insert |
| "transpose", "rotate", "pivot" | Transpose rows ↔ columns |
| "sparse", "gaps", "missing" | Sparse data handling |

**Multiple approaches**: Many tasks require combining approaches. For example:
- "Sort filtered data" → Filter + Sort
- "Copy matching rows to another sheet" → ID match + Cross-sheet
- "Compact and sort" → Compact + Sort

### Step 5: Implement Read-Transform-Write
Always follow the three-phase approach:
1. **Read**: Load all data with evaluated formulas and styles
2. **Transform**: Apply transformations in memory
3. **Write**: Write results back preserving styles

### Step 6: Verify
Check:
- Transformation applied correctly
- Formulas evaluated to numeric values
- Styles preserved
- Workbook state preserved (column widths, etc.)
- Values outside transformation range unchanged

## Example Workflow

```python
# 1. Load TWO handles: one for formulas+styles, one for cached values
wb_formulas = openpyxl.load_workbook('input.xlsx')
wb_data = openpyxl.load_workbook('input.xlsx', data_only=True)
ws_f = wb_formulas['Sheet1']
ws_d = wb_data['Sheet1']

# 2. Detect blocks
blank_rows = find_blank_rows(ws_f, 1, 85, range(1, 9))
blocks = build_blocks(blank_rows, 1, 85)

# 3. Phase 1: Read all blocks completely (with evaluated values)
all_block_data = {}
for start, end in blocks:
    rows = read_block_data(ws_f, ws_d, start, end, range(1, 9), formula_columns=[4, 6])
    all_block_data[(start, end)] = rows

# 4. Phase 2: Transform each block in memory
for key in all_block_data:
    all_block_data[key].sort(key=lambda r: r[0][3], reverse=True)  # Sort by column D

# 5. Phase 3: Write all blocks back
for (start, end), rows in all_block_data.items():
    write_block_data(ws_f, rows, start, range(1, 9))

# 6. Save
wb_formulas.save('output.xlsx')
```

## Key Principles

- **Always prefer Excel's cached values when available**: Use `data_only=True` to read cached computed values. Fall back to manual evaluation only when cached values are unavailable.
- **Handle operator precedence correctly**: Use `eval()` after substituting cell references to correctly handle mixed operators.
- **Read-then-write sequencing**: Always read all values before writing any results when rearranging rows in-place.
- **Preserve workbook state**: Don't modify anything outside the transformation range.
- **Use stable sort**: Preserve original order for equal values.
- **Copy styles explicitly**: Use `copy()` to avoid shared references.
- **Detect structure from data**: Don't assume fixed block sizes or positions.
- **Handle formulas and text**: Both formula cells and text-that-looks-like-formulas need evaluation.

## Edge Cases and Gotchas

1. **Floating point precision**: When reading cached values and writing them back, openpyxl may slightly change the float representation (e.g., `1.5999999999999943` becomes `1.599999999999994`). This is a fundamental limitation of xlsx float handling. For most use cases, values within 1e-10 tolerance are acceptable.

2. **Formula text vs formula cells**: Some cells may contain text that looks like a formula (e.g., "=B1+C1" stored as text). Handle both cases:
   ```python
   if isinstance(val, str) and val.startswith('='):
       # It's a formula, evaluate it
   ```

3. **Circular references**: Formulas that reference each other circularly. Detect and handle gracefully.

4. **Empty cells in formulas**: Treat empty cells as 0 in arithmetic operations.

5. **Mixed data types**: Columns may contain both numbers and text. Handle type conversions carefully.

6. **Style preservation**: Always copy styles using `copy()` to avoid shared references.

7. **Blank row detection**: A blank row has ALL cells empty in the data range, not just some cells.

8. **Cached value availability**: When an xlsx file was never opened in Excel/LibreOffice, formula cells may not have cached values (`data_only` returns `None`). Always fall back to manual evaluation in this case.

9. **Read-then-write sequencing**: When rearranging rows in-place, read all values before writing any results to avoid overwriting cells needed for subsequent formula evaluations.

10. **Color objects in styles**: When checking cell colors (e.g., for style-based selection), remember that `Color` objects have multiple modes:
    - **RGB mode**: `color.rgb = 'FFFF0000'`, `color.type = 'rgb'`
    - **Theme mode**: `color.theme = 4`, `color.tint = 0.6`, `color.type = 'theme'`
    - **Indexed mode**: `color.indexed = 64`, `color.type = 'indexed'`
    
    Always check `color.type` before accessing `color.rgb`, as theme-based colors are very common and `color.rgb` may be `'00000000'` or `None` for theme colors.
