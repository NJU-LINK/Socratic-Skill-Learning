---
name: xlsx-structure
description: Transform Excel workbooks by applying structural operations (sorting, filtering, compaction, append, transposition) while preserving workbook state outside the transformation region.
---

# XLSX Structure Transformation Skill

## Overview

This skill handles structural transformations of Excel (.xlsx) workbooks while preserving all workbook state outside the declared transformation region. It supports various operations including block-local sorting, filtering, compaction, header-aligned append, and layout changes.

## Family Invariants

- **Input**: Read from `/app/input.xlsx`
- **Output**: Write to `/app/output.xlsx`
- **Preservation Requirement**: All workbook state outside the declared transformation region must remain intact (sheets, values, styles, filters, merged cells, panes, dimensions)
- **Tool**: Use `openpyxl` for xlsx manipulation

## File Layout

```
skill/xlsx-structure/
├── SKILL.md                      # This documentation
├── reference_v01.py               # Working reference for v01
└── scripts/
    └── xlsx_structure.py          # Reusable machinery (tested)
```

**Critical Note**: The workspace file tools (read/write) and `/app` task_shell are separate filesystems. The scripts cannot be directly imported from /app. You have two options:

**Option 1: Copy script to /app (recommended for solving)**
```bash
# In task_shell, copy the script content using Python
cat > /app/copy_script.py << 'EOF'
import sys
with open('skill/xlsx-structure/scripts/xlsx_structure.py') as f:
    content = f.read()
with open('/app/xlsx_structure.py', 'w') as f:
    f.write(content)
EOF
python3 /app/copy_script.py

# Then import
python3 -c "
import sys
sys.path.insert(0, '/app')
from xlsx_structure import make_evaluator, detect_blocks
# ... use the machinery ...
"
```

**Option 2: Inline the functions you need**
```python
# Copy only the functions you need directly into your solution
```

## Variation Dimensions (per spec.yaml)

### 1. Transformation Semantics
The structural operation to apply:
- **Block-local sorting**: Sort rows within blocks separated by blank rows
- **Predicate-based filtering**: Include/exclude rows based on conditions
- **Style-based filtering**: Select rows/cells by fill color or other formatting
- **Compaction**: Remove blank rows while preserving data
- **Header-aligned append**: Append data aligning columns by header names
- **Sparse-record reconciliation**: Match and merge sparse data ranges
- **Row extraction**: Extract specific rows based on criteria
- **Layout transposition**: Transpose rows to columns or vice versa

### 2. Workbook Topology
Where source and destination data reside:
- Single or multiple sheets
- Contiguous tables or repeated blocks separated by blanks
- Style-marked cells or ranges
- Ordered ID lists paired with sparse tables
- Header-mapped columns

### 3. Selection and Alignment Rule
How rows/cells are selected and matched:
- **Numeric order**: Sort/compare by evaluated numeric values
- **Membership**: Include if in another range/list
- **Exact identity**: Match by header name or ID
- **Fill color**: Select by cell background color (rgb, theme, or indexed)
- **Text predicates**: Match by regex or string patterns, with exclusions
- **Positional correspondence**: Map by relative position

### 4. Output Geometry
The destination specification:
- Target sheet (existing or new)
- Output range (A1 notation)
- Orientation (normal or transposed)
- Append vs insert vs compaction mode

### 5. Preservation Constraints
State that must remain unchanged:
- Input sheets and their names
- Values outside transformation range
- Cell styles (fonts, borders, fills, number formats)
- Workbook-level properties (dimensions, filters, merged ranges, freeze panes)
- Row heights and column widths

## Decision Procedure for Task Variants

When reading a task instruction, extract these parameters:

### Step 1: Identify Transformation Semantics
Look for keywords:
- "sort" → Block-local or global sorting
- "filter", "keep rows where", "exclude" → Predicate-based filtering
- "fill color", "background color", "style", "highlighted" → Style-based filtering
- "compact", "remove blank" → Compaction
- "append", "add to" → Header-aligned append
- "transpose", "pivot" → Layout transposition
- "extract", "copy rows" → Row extraction
- "reconcile", "align IDs" → Sparse-record reconciliation

### Step 2: Identify Workbook Topology
- Source sheet: Explicitly named or "Sheet1" by default
- Destination: Same sheet or "create new sheet named X"
- Multiple sheets: Check `wb.sheetnames` after loading
- Blocks: "separated by blank rows" → use `detect_blocks()`
- Tables: "contiguous table" → process as single block

### Step 3: Identify Selection Rule
- "sort by column X" → Numeric order via formula evaluation
- "where column Y > 5" → Predicate filter
- "cells with red background" → Fill color selection (use `enumerate_fill_signatures` first!)
- "matching header" → Exact identity
- "contains text" → Text predicate with regex

### Step 4: Identify Output Geometry
- Target range: Explicit (A1:H85) or implicit (preserve input dimensions)
- "append to end" → Write after existing data
- "insert at row N" → Shift existing data down
- "transpose to Sheet2" → Use transpose helper

### Step 5: Identify Preservation Requirements
- "preserve styles" → Position-attached by default (don't move styles with rows)
- "preserve row heights/column widths" → Check dimensions match
- "preserve merged cells" → Check merged ranges identical

## Core Machinery (scripts/xlsx_structure.py)

Since the workspace and /app are separate, copy the machinery you need:

**Copy the script using Python:**
```bash
cat > /app/copy_script.py << 'ENDOFSCRIPT'
import sys
# Read from workspace and write to /app
with open('skill/xlsx-structure/scripts/xlsx_structure.py') as f:
    content = f.read()
with open('/app/xlsx_structure.py', 'w') as f:
    f.write(content)
    print(f"Copied {len(content)} bytes")
ENDOFSCRIPT
python3 /app/copy_script.py
```

Then import:
```python
import sys
sys.path.insert(0, '/app')
from xlsx_structure import (
    make_evaluator,
    capture_all_cell_values,
    detect_blocks,
    fill_signature,
    enumerate_fill_signatures,
    select_rows_by_fill_signature,
    write_value,
    compact_rows,
    align_by_headers,
    filter_rows_by_predicate,
    filter_rows_by_text_predicate,
    transpose_range,
    reconcile_sparse_records,
    verify_preservation,
    assert_no_formula_strings,
)
```

### Formula Evaluation

**Critical**: The evaluator raises on failure, not returns 0. Silent 0 corrupts sort keys.

```python
cell_values = capture_all_cell_values(ws)
eval_cell = make_evaluator(cell_values)
value = eval_cell('D5')  # Evaluates formula at D5, returns float
```

Features:
- Word-boundary regex: `(?<![A-Za-z0-9_$])\$?([A-Z]{1,3})\$?(\d{1,7})(?![A-Za-z0-9_(])`
- Handles `$B$1` absolute references
- Rejects function names like LOG10 (not LOG + 10)
- Memoization to avoid O(2^depth) re-evaluation
- Explicit cycle detection
- `repr()` substitution for safety

### Block Detection

```python
blocks = detect_blocks(ws, min_row=1, max_row=85, max_col=8)
# Returns: [[1,2,3,4,5,6,7], [9,10,11,12,13,14,15,16,17], ...]
```

### Style-Based Selection (Fill Color)

**Critical**: Excel has three color types (rgb, theme, indexed). A naive `rgb` check silently fails on theme/indexed colors.

```python
# Step 1: Enumerate distinct fills in the region
rows = range(2, 100)
signatures = enumerate_fill_signatures(ws, rows, col=1)
for sig, count in signatures.items():
    print(f"{sig}: {count} rows")
# Output: ('rgb', 'FFFF0000'): 5 rows, ('theme', 6, 0.0): 3 rows

# Step 2: Match instruction to actual signature
red_sig = ('rgb', 'FFFF0000')
selected = select_rows_by_fill_signature(ws, rows, col=1, target_signature=red_sig)
```

The `fill_signature()` function returns:
- `('rgb', 'FFFF0000')` for RGB colors
- `('theme', 6, 0.0)` for theme colors
- `('indexed', 5)` for indexed colors
- `None` for no fill

### Text Predicate Filtering (Regex)

```python
# Keep rows where column A contains "ERROR"
import re
error_rows = filter_rows_by_text_predicate(
    ws, rows=range(2, 100), col=1, pattern=r'ERROR'
)

# Exclude rows where column B matches pattern
excluded = filter_rows_by_text_predicate(
    ws, rows=range(2, 100), col=2, pattern=r'^TEST', exclude=True
)
```

### Universal Formula Evaluation on Write

The `write_value()` function is the choke point for all writes. **Never use direct `.value =` assignment.**

```python
# CORRECT: Use write_value
write_value(cell, value, eval_cell, addr)

# WRONG: Direct assignment bypasses formula evaluation
cell.value = value  # Don't do this!
```

**Post-write assertion** (run after every transformation):
```python
assert_no_formula_strings(ws, min_row, max_row, min_col, max_col)
```

### Stable Sorting

Python's `sorted()` is stable. Use `key=` function:

```python
rows_with_keys = [
    (row_num, row_data, eval_cell(f'D{row_num}'))
    for row_num, row_data in rows
]
rows_with_keys.sort(key=lambda x: x[2], reverse=True)
sorted_rows = [(rn, rd) for rn, rd, _ in rows_with_keys]
# Ties automatically preserve original order
```

### Compaction

```python
last_row = compact_rows(
    ws, min_row=2, max_row=100, max_col=8, eval_cell=eval_cell
)
```

### Header-Aligned Append

```python
next_row = align_by_headers(
    source_ws, source_rows=[2,3,4], 
    target_ws, target_start_row=10,
    eval_cell=eval_cell
)
```

### Layout Transposition

**Critical**: Uses capture-before-write to prevent aliasing bugs when target overlaps source.

```python
# Transpose A1:D10 to Sheet2 starting at A1
ws2 = wb.create_sheet("Sheet2")
output_rows, output_cols = transpose_range(
    ws1, min_row=1, max_row=10, min_col=1, max_col=4,
    target_ws=ws2, target_start_row=1, target_start_col=1,
    eval_cell=eval_cell
)
# Original 10 rows x 4 cols becomes 4 rows x 10 cols
```

**Same-sheet transpose** (adversarial case):
```python
# This would corrupt without capture-first
transpose_range(
    ws, 1, 3, 1, 3,
    target_ws=ws, target_start_row=5, target_start_col=1,
    eval_cell=eval_cell
)
```

### Sparse-Record Reconciliation

**Critical**: Reports unmatched IDs and duplicates. Normalizes string IDs by default.

```python
next_row, report = reconcile_sparse_records(
    id_list_ws, id_col=1,
    data_ws, data_col=1,
    output_ws, output_row_start=1,
    eval_cell=eval_cell,
    strict_types=False  # Normalizes '1001' vs 1001
)

# Check report
print(f"Written: {report['written']}")
print(f"Unmatched: {report['unmatched']}")  # IDs in list but not in data
print(f"Duplicates in data: {report['duplicates_in_data']}")
print(f"Duplicates in list: {report['duplicates_in_list']}")
```

### Predicate Filtering

```python
def my_predicate(row_num, ws):
    return eval_cell(f'D{row_num}') > 100

selected = filter_rows_by_predicate(ws, rows, my_predicate)
```

## Multi-Sheet Handling

Always check sheet names after loading:

```python
wb = load_workbook('/app/input.xlsx')
print(f"Sheets: {wb.sheetnames}")

# Get source sheet
source_sheet = wb['SourceSheet']  # or wb[wb.sheetnames[0]] for first sheet

# Create or get target sheet
if 'TargetSheet' not in wb.sheetnames:
    target_sheet = wb.create_sheet('TargetSheet')
else:
    target_sheet = wb['TargetSheet']
```

## Style Preservation Policy

### Decision Rule

The task instruction says: "Preserve... existing styles, filters, merged ranges, panes, row heights, and column widths."

These are **position-attached** artifacts. Default policy:

1. **Write values only** (do not move styles with rows)
2. **Detect non-uniformity** to alert when the assumption might be wrong
3. **Only move styles** if the task explicitly says "rows carry their formatting"

### Implementation

```python
# Position-attached (default): clear values only
for row_num in range(min_row, max_row + 1):
    for col in range(min_col, max_col + 1):
        ws.cell(row=row_num, column=col).value = None

# Then write new values (styles at positions preserved)
write_value(ws.cell(row=row, column=col), new_value, eval_cell, addr)
```

### Merged Cells Hazard

Writing to any non-anchor cell of a merged range raises:
```
AttributeError: 'MergedCell' object attribute 'value' is read-only
```

Always write to the anchor cell:
```python
anchor = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
write_value(anchor, new_value, eval_cell, addr)
```

## Verification

```python
verify_preservation(
    input_path='/app/input.xlsx',
    output_path='/app/output.xlsx',
    sheet_name='Sheet1',
    transform_region=(1, 85, 1, 8)  # (min_row, max_row, min_col, max_col)
)
```

Checks:
- Sheets, freeze panes, auto filter, merged cells preserved
- Dimensions unchanged
- Row heights and column widths preserved
- Values outside transform region identical

### Numeric Comparison Notes

- openpyxl serializes integral floats (230.0) as `230` and reads them back as `int`
- Compare values numerically (`==`), never by type or string representation
- Floating point arithmetic produces small errors (`-0.2999999999999972`); this is expected IEEE-754 behavior

## Error Handling

Common errors and solutions:

**KeyError: 'Sheet1'**
```python
# Sheet doesn't exist - check available sheets
print(wb.sheetnames)
# Use correct sheet name
ws = wb[wb.sheetnames[0]]  # First sheet
```

**ValueError: circular reference**
```python
# Formula has circular reference - check input data
# The evaluator raises this for formulas like =A1 where A1 refers to itself
```

**AttributeError: 'MergedCell' object attribute 'value' is read-only**
```python
# Writing to non-anchor cell of merged range
# Write to anchor only:
anchor = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
```

## Known Limitations

openpyxl's load/save round-trip preserves values, styles, merges, panes, filters, and dimensions, but may drop or mangle:
- Charts (`ws._charts`)
- Images (`ws._images`)
- Pivot caches
- VBA macros (needs `keep_vba=True`)

Check for these before transforming if the task implies they exist.

## Debugging Tips

1. **Silent sort failures**: The evaluator raising on unparseable formulas is correct. Silent 0 would corrupt sort keys.

2. **Theme colors missed**: Always use `enumerate_fill_signatures()` before selecting by color. Don't guess RGB values.

3. **Styles lost**: Default is position-attached. Only move styles if explicitly required.

4. **Merged cell errors**: Check for merged ranges that overlap your transform region. Write only to anchor cells.

5. **Formulas not evaluated**: Use `write_value()` for all writes and call `assert_no_formula_strings()` after.

6. **Wrong sheet**: Check `wb.sheetnames` - don't assume Sheet1 exists.

7. **Transpose corruption**: Ensure capture-before-write pattern is used. Test same-sheet transposes.

8. **Missing IDs in reconcile**: Check `report['unmatched']` - IDs may be text vs numeric.

## Testing Your Code

Always test helpers against a probe workbook:

```python
from openpyxl import Workbook
from openpyxl.styles import PatternFill
from openpyxl.styles.colors import Color

wb = Workbook()
ws = wb.active
ws.append(["name", "val"])
ws.append(["a", 10])
ws.append([None, None])  # blank
ws.append(["b", "=A2+5"])  # formula

# RGB color
ws["A2"].fill = PatternFill("solid", fgColor="FFFF0000")

# Theme color
c = Color(theme=6)
ws["A3"].fill = PatternFill("solid", fgColor=c)

wb.save("/app/probe.xlsx")

# Now test your helpers - import from the ACTUAL file
import sys
sys.path.insert(0, '/app')
from xlsx_structure import fill_signature, enumerate_fill_signatures
from openpyxl import load_workbook

wb = load_workbook("/app/probe.xlsx")
# ... test code ...
```

**Critical**: Import from the actual `/app/xlsx_structure.py` file, not retyped copies.

## Quick Reference: Common Patterns

**Block-local sort:**
```python
blocks = detect_blocks(ws, 1, 85, 8)
for block in blocks:
    rows_with_keys = [(r, eval_cell(f'D{r}')) for r in block]
    rows_with_keys.sort(key=lambda x: x[1], reverse=True)
    # write sorted...
```

**Filter by value:**
```python
selected = [r for r in rows if eval_cell(f'D{r}') > 100]
```

**Filter by text:**
```python
selected = filter_rows_by_text_predicate(ws, rows, col=1, pattern=r'ERROR')
```

**Filter by color:**
```python
sigs = enumerate_fill_signatures(ws, rows, col=1)
# inspect sigs, pick target_sig
selected = select_rows_by_fill_signature(ws, rows, col=1, target_sig)
```

**Transpose:**
```python
output_rows, output_cols = transpose_range(
    ws, 1, 10, 1, 5, target_ws, 1, 1, eval_cell
)
```

**Reconcile sparse records:**
```python
next_row, report = reconcile_sparse_records(
    id_list_ws, 1, data_ws, 1, output_ws, 1, eval_cell
)
```

## Policy Enforcement Checklist

Before submitting a solution, verify:

- [ ] All writes use `write_value()` (no direct `.value =`)
- [ ] `assert_no_formula_strings()` called after transformation
- [ ] `verify_preservation()` checks pass
- [ ] Same-sheet operations use capture-before-write pattern
- [ ] Text/numeric ID mismatches handled (use `strict_types=False`)
- [ ] Unmatched IDs reported (check reconcile report)
- [ ] Sheet existence verified before access
