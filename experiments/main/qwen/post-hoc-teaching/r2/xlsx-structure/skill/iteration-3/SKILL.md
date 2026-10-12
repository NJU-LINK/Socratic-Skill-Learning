---
name: xlsx-structure
description: >
  Perform structural transformations on Excel workbooks (.xlsx) using openpyxl.
  Handles block-local sorting, formula evaluation, row rearrangement, filtering,
  appending, and transposition while preserving workbook metadata (styles, filters,
  merged ranges, panes, dimensions). Detects data topology dynamically from the
  workbook rather than assuming fixed layouts.
---

# XLSX Structural Transformation Skill

## Overview

This skill addresses structural transformations of Excel workbooks where the task
requires reading data from an input workbook, applying a structural operation
(sorting, filtering, rearranging, transposing, etc.), and writing the result to
an output workbook while preserving all unrelated workbook state.

## Core Methodology

### 1. Workbook Loading and Preservation

Always load with `openpyxl.load_workbook()` which preserves:
- All sheets and their names
- Cell styles (font, fill, border, alignment, number_format)
- Column widths and row heights
- Merged cell ranges
- Auto-filters
- Sheet views (panes, frozen panes, zoom, active cell, topLeftCell)
- Conditional formatting and data validations

```python
import openpyxl
from copy import copy

wb = openpyxl.load_workbook('input.xlsx')
ws = wb['SheetName']
```

**Key principle**: Only modify cells within the declared transformation range.
Everything outside that range (other sheets, other columns, other rows) must
remain byte-identical after save.

### 2. Dynamic Structure Detection

Never assume fixed row counts or positions. Detect structure from the workbook:

#### Block Detection (blank-row-separated groups)
```python
def find_blocks(ws, min_row, max_row, min_col, max_col):
    """Find contiguous non-blank row groups separated by blank rows."""
    blocks = []
    current = []
    for r in range(min_row, max_row + 1):
        has_data = any(ws.cell(r, c).value is not None
                       for c in range(min_col, max_col + 1))
        if has_data:
            current.append(r)
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)
    return blocks
```

#### Header Detection
Look for the first row with non-empty cells that differ in character from data
rows (e.g., text labels vs. numbers, or bold formatting).

#### Style-Marked Regions
Cells with distinctive fill colors or fonts may mark logical boundaries or
categories. Scan for style transitions to detect region boundaries.

**Detecting fill colors** (for style-based selection or region detection):
```python
from openpyxl.styles import PatternFill

def get_fill_color(cell):
    """Extract fill color as a comparable value.
    Returns None if no fill, or a tuple (type, value) for comparison.
    """
    fill = cell.fill
    if fill.patternType is None:
        return None
    
    fg = fill.fgColor
    if fg.type == 'theme':
        # Theme color with optional tint
        return ('theme', fg.theme, fg.tint)
    elif fg.type == 'rgb':
        # RGB color (includes alpha channel)
        return ('rgb', fg.rgb)
    elif fg.type == 'indexed':
        # Legacy indexed color
        return ('indexed', fg.indexed)
    return None

def find_style_transitions(ws, col, min_row, max_row):
    """Find rows where fill color changes in a specific column.
    Useful for detecting region boundaries marked by color.
    """
    transitions = []
    prev_color = get_fill_color(ws.cell(min_row, col))
    for r in range(min_row + 1, max_row + 1):
        curr_color = get_fill_color(ws.cell(r, col))
        if curr_color != prev_color:
            transitions.append(r)
            prev_color = curr_color
    return transitions

def select_rows_by_fill(ws, col, target_colors, min_row, max_row):
    """Select rows where a specific column has one of the target fill colors.
    
    Args:
        target_colors: list of color tuples from get_fill_color(), or
                      list of RGB strings like ['FFFF00', '00FF00']
    """
    selected = []
    for r in range(min_row, max_row + 1):
        color = get_fill_color(ws.cell(r, col))
        if color is None:
            continue
        # Match by RGB value or full tuple
        if color in target_colors:
            selected.append(r)
        elif color[0] == 'rgb' and color[1] in target_colors:
            selected.append(r)
    return selected
```

### 3. Formula Evaluation

Cells may contain formula strings (e.g., `"=B1+C1"`) rather than computed values.
These must be evaluated before use in sorting or output.

#### Strategy 1: Use `data_only=True` (Preferred)

When workbooks are saved by Excel or other applications, they often cache computed
formula results. Load with `data_only=True` to read these cached values directly:

```python
import openpyxl

# Load normally for structure, styles, and formula strings
wb = openpyxl.load_workbook('input.xlsx')
ws = wb['Sheet1']

# Load with data_only=True for cached formula values
wb_data = openpyxl.load_workbook('input.xlsx', data_only=True)
ws_data = wb_data['Sheet1']

# Build cell value lookup: start with raw values from normal load
cell_lookup = {}
for r in range(min_row, max_row + 1):
    for c in range(min_col, max_col + 1):
        cell_lookup[(c, r)] = ws.cell(r, c).value

# Layer cached values on top (overrides formula strings with numeric results)
any_cached = False
for r in range(min_row, max_row + 1):
    for c in range(min_col, max_col + 1):
        cached = ws_data.cell(r, c).value
        if cached is not None:
            cell_lookup[(c, r)] = cached
            any_cached = True

# If any formula cells still have string values, evaluate them in dependency order
# This handles both the "no cached values" case and partial caching
for c in sorted(formula_cols):  # formula_cols detected earlier
    for r in range(min_row, max_row + 1):
        val = cell_lookup.get((c, r))
        if isinstance(val, str) and val.startswith('='):
            evaluated = eval_formula(val, cell_lookup)
            cell_lookup[(c, r)] = evaluated

# Validate: all formula columns should have numeric values now
for c in formula_cols:
    for r in range(min_row, max_row + 1):
        val = cell_lookup.get((c, r))
        if isinstance(val, str) and val.startswith('='):
            raise ValueError(
                f"Formula at ({c},{r}) could not be evaluated: {val}. "
                f"Consider data_only=True or a more capable formula parser."
            )

# Now cell_lookup contains evaluated numeric values for all cells
# Use cell_lookup[(col, row)] for sorting and output
```

**When to use**: Always try `data_only=True` first. It's more reliable and handles
complex formulas, Excel functions, and edge cases that custom evaluators miss.

**Limitation**: Programmatically-created workbooks (e.g., by openpyxl) may not have
cached values. In that case, `data_only=True` returns `None` for formula cells, and
you must fall back to custom evaluation.

#### Strategy 2: Custom Formula Evaluator (Fallback)

When cached values are unavailable, use a custom evaluator. The evaluator must handle
Excel-specific syntax that differs from Python:

```python
import re
from openpyxl.utils import column_index_from_string

def eval_formula(val, cell_lookup):
    """Evaluate a formula string using a cell value lookup dict {(col, row): value}.
    
    Supports simple arithmetic formulas with cell references.
    Handles Excel-specific syntax: ^ (power), % (percentage).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip()
    if not s.startswith('='):
        try:
            return float(s)
        except (ValueError, TypeError):
            return val
    
    expr = s[1:]  # strip leading '='
    
    # CRITICAL: Convert Excel power operator (^) to Python (**)
    # Python's ^ is bitwise XOR, not exponentiation!
    expr = expr.replace('^', '**')
    
    # Handle percentage: convert "10%" to "(10/100)"
    expr = re.sub(r'(\d+(?:\.\d+)?)%', r'(\1/100)', expr)
    
    def replace_ref(match):
        col_letters = match.group(1).upper()
        row_num = int(match.group(2))
        try:
            col_idx = column_index_from_string(col_letters)
        except ValueError:
            return match.group(0)  # not a valid cell ref, leave as-is
        v = cell_lookup.get((col_idx, row_num))
        if v is None:
            v = 0
        if isinstance(v, str):
            try:
                v = float(v)
            except (ValueError, TypeError):
                v = 0
        return str(v)
    
    # Use negative lookaround to avoid matching function names like IF, SUM, etc.
    expr = re.sub(r'(?<![A-Za-z])([A-Za-z]+)(\d+)(?!\w)', replace_ref, expr)
    try:
        return eval(expr)
    except Exception:
        return val
```

**Critical pitfall**: Excel's `^` operator means exponentiation (power), but Python's
`^` is bitwise XOR. `=A1^2` with A1=5 should give 25, but without conversion,
Python evaluates `5^2 = 7`. Always convert `^` to `**` before `eval()`.

**Dependency ordering**: When formula F depends on formula D, evaluate D first
and inject its result into the lookup before evaluating F. Build a dependency
order if formulas chain further.

**Detecting formula columns**: Scan the data range to identify which columns contain
formulas:

```python
formula_cols = set()
for r in range(min_row, max_row + 1):
    for c in range(min_col, max_col + 1):
        val = ws.cell(r, c).value
        if isinstance(val, str) and val.startswith('='):
            formula_cols.add(c)
```

### 4. Row Manipulation with Style Preservation

When rearranging rows (sorting, filtering, transposing), carry the complete cell
state — value AND style — as a unit:

```python
def capture_row(ws, row_num, min_col, max_col):
    """Capture all cell data for a row."""
    cells = []
    for c in range(min_col, max_col + 1):
        src = ws.cell(row_num, c)
        cells.append({
            'value': src.value,
            'font': copy(src.font),
            'fill': copy(src.fill),
            'border': copy(src.border),
            'alignment': copy(src.alignment),
            'number_format': src.number_format,
        })
    return cells

def write_row(ws, row_num, cells_data, min_col=1):
    """Write captured cell data to a row starting at min_col."""
    for i, cd in enumerate(cells_data):
        dest = ws.cell(row_num, min_col + i)
        dest.value = cd['value']
        dest.font = cd['font']
        dest.fill = cd['fill']
        dest.border = cd['border']
        dest.alignment = cd['alignment']
        dest.number_format = cd['number_format']
```

### 5. Transformation Patterns

#### Block-Local Sorting
Sort rows within each detected block by a sort key (evaluated numeric value,
text, etc.) while preserving block boundaries:

```python
for block_rows in blocks:
    # Collect rows with sort keys
    rows = []
    for r in block_rows:
        cells = capture_row(ws, r, min_col, max_col)
        sort_key = compute_sort_key(r)  # e.g., evaluated column D
        rows.append((sort_key, cells))
    
    # Stable sort (descending or ascending as specified)
    rows.sort(key=lambda x: x[0], reverse=True)
    
    # Write back to same positions
    for i, dest_row in enumerate(block_rows):
        write_row(ws, dest_row, rows[i][1], min_col)
```

#### Predicate-Based Filtering/Compaction
Select rows matching a predicate and compact them into a contiguous output range:

```python
selected = []
for r in data_rows:
    if matches_predicate(ws, r):
        selected.append(capture_row(ws, r, min_col, max_col))

for i, row_data in enumerate(selected):
    write_row(ws, output_start_row + i, row_data, min_col)
```

**Style-based filtering** (select rows by fill color):
```python
# Select rows where column A has yellow fill
yellow_rows = select_rows_by_fill(ws, 1, [('rgb', '00FFFF00')], min_row, max_row)

# Or select rows matching multiple colors
target_colors = [('rgb', '00FFFF00'), ('rgb', '00FF0000')]  # yellow or red
selected_rows = select_rows_by_fill(ws, 1, target_colors, min_row, max_row)

# Compact selected rows to output range
for i, r in enumerate(selected_rows):
    cells = capture_row(ws, r, min_col, max_col)
    write_row(ws, output_start_row + i, cells, min_col)
```

**Text predicate with exclusions**:
```python
def matches_text_predicate(ws, row, include_patterns, exclude_patterns):
    """Match rows where column A text matches include patterns but not exclude."""
    text = str(ws.cell(row, 1).value or '').upper()
    if not any(p in text for p in include_patterns):
        return False
    if any(p in text for p in exclude_patterns):
        return False
    return True

# Example: select rows containing "REPORT" but not "DRAFT"
selected = []
for r in data_rows:
    if matches_text_predicate(ws, r, ['REPORT'], ['DRAFT', 'TEMPLATE']):
        selected.append(capture_row(ws, r, min_col, max_col))
```

#### Header-Aligned Append
Match source columns to destination by header name, then append rows:

```python
# Build header mapping
src_headers = {ws.cell(header_row, c).value: c for c in range(...)}
dst_headers = {ws_out.cell(header_row, c).value: c for c in range(...)}
col_map = {src_headers[h]: dst_headers[h] for h in src_headers if h in dst_headers}

# Copy rows with column remapping
for src_row in source_rows:
    for src_col, dst_col in col_map.items():
        ws_out.cell(dst_row, dst_col).value = ws.cell(src_row, src_col).value
```

#### Layout Transposition
Swap rows and columns for a data region:

```python
for r_idx, r in enumerate(source_rows):
    for c_idx, c in enumerate(source_cols):
        ws_out.cell(dest_col_start + r_idx, dest_row_start + c_idx).value = \
            ws.cell(r, c).value
```

### 6. Output Geometry

- **Same-sheet in-place**: Write back to the same range (common for sorting)
- **Different sheet**: Create or target a specific sheet by name
- **Appended**: Write after the last used row in the destination
- **New range**: Write to a specified absolute range

Always determine the output range from the task specification, not by assumption.

#### Multi-Sheet Operations

When tasks involve reading from or writing to multiple sheets:

```python
# Read from multiple source sheets
source_data = {}
for sheet_name in ['Sheet1', 'Sheet2']:
    ws = wb[sheet_name]
    source_data[sheet_name] = []
    for r in range(min_row, max_row + 1):
        row_data = [ws.cell(r, c).value for c in range(min_col, max_col + 1)]
        source_data[sheet_name].append(row_data)

# Write to a different destination sheet
ws_dest = wb['OutputSheet']
for i, row_data in enumerate(combined_data):
    for j, value in enumerate(row_data):
        ws_dest.cell(output_start_row + i, output_start_col + j).value = value

# Copy styles from source to destination
def copy_cell_style(src_cell, dst_cell):
    """Copy all style attributes from source to destination cell."""
    dst_cell.font = copy(src_cell.font)
    dst_cell.fill = copy(src_cell.fill)
    dst_cell.border = copy(src_cell.border)
    dst_cell.alignment = copy(src_cell.alignment)
    dst_cell.number_format = src_cell.number_format

# Example: copy styles when writing to new sheet
for i, src_row in enumerate(source_rows):
    for j, src_col in enumerate(source_cols):
        src_cell = ws_source.cell(src_row, src_col)
        dst_cell = ws_dest.cell(dest_row + i, dest_col + j)
        dst_cell.value = src_cell.value
        copy_cell_style(src_cell, dst_cell)
```

### 7. Preservation Checklist

Before saving, verify:
- [ ] All non-target sheets are untouched
- [ ] All cells outside the transformation range are unchanged
- [ ] Column widths and row heights are preserved
- [ ] Merged cell ranges are preserved
- [ ] Auto-filters are preserved
- [ ] Sheet views (panes, zoom, selection) are preserved
- [ ] Cell styles in the output range match the intended result

## Implementation Pattern

```python
import openpyxl
from copy import copy
import re

def solve(input_path, output_path):
    # Load normally for structure and styles
    wb = openpyxl.load_workbook(input_path)
    ws = wb['TargetSheet']
    
    # Load with data_only=True for cached formula values
    wb_data = openpyxl.load_workbook(input_path, data_only=True)
    ws_data = wb_data['TargetSheet']
    
    # 1. Detect structure (blocks, headers, data range)
    # 2. Build cell value lookup:
    #    - Prefer cached values from ws_data when available
    #    - Fall back to custom evaluation for None values
    # 3. For each transformation unit (block, group, etc.):
    #    a. Capture row data (values + styles)
    #    b. Evaluate formulas as needed
    #    c. Apply transformation (sort, filter, remap, etc.)
    #    d. Write results back
    # 4. Save
    wb.save(output_path)
```

## Common Pitfalls

1. **Formula strings vs. values**: openpyxl reads formula strings, not computed
   values. Always evaluate before using in comparisons or output.
2. **Excel `^` is power, Python `^` is XOR**: `=A1^2` with A1=5 should give 25,
   but Python evaluates `5^2 = 7` (bitwise XOR). Always convert `^` to `**`
   before `eval()`. This is a silent correctness bug — no exception, just wrong results.
3. **Floating point precision**: Arithmetic on floats may produce results like
   `224.89999999999998` instead of `224.9`. This is expected; do not round
   unless the task specifies it.
4. **Stable sort**: When sort keys are equal, preserve original row order.
   Python's `sort()` is stable, so just avoid adding secondary keys unless needed.
5. **Blank row detection**: A row is blank only if ALL cells in the relevant
   column range are None. Don't check just column A.
6. **Style copying**: Use `copy()` on style objects to avoid shared references.
7. **Column indexing**: openpyxl uses 1-based column indices. `cell(r, c)` where
   c=1 is column A.
8. **Multi-letter columns**: `ord(letter) - ord('A') + 1` only works for single-letter
   columns A–Z. For columns AA and beyond (AA=27, AB=28, …, XFD=16384), use
   `openpyxl.utils.column_index_from_string()` which correctly implements bijective
   base-26 decoding.
9. **`data_only=True` for cached values**: When workbooks are saved by Excel, they
   often cache computed formula results. Load with `data_only=True` to read these
   directly — more reliable than custom evaluation. Fall back to custom evaluation
   only when cached values are `None` (programmatically-created workbooks).
10. **Column offset in write_row**: When writing to a range that doesn't start at
    column A, use `min_col + i` not `i + 1` for the column index. The template
    code includes this parameter.
11. **Fill color comparison**: Fill colors can be RGB, theme-based, or indexed.
    When comparing colors, normalize to a common representation. Theme colors
    with different tints are different colors. RGB colors include alpha channel
    (e.g., '00FFFF00' not 'FFFF00').
12. **Multi-sheet style preservation**: When copying cells between sheets, styles
    are not automatically preserved. Use `copy()` on font, fill, border, alignment
    objects. The destination sheet's default styles will apply otherwise.
13. **Text predicate case sensitivity**: Excel text matching is often case-insensitive.
    Convert to uppercase before comparison: `text.upper().startswith('PREFIX')`.
