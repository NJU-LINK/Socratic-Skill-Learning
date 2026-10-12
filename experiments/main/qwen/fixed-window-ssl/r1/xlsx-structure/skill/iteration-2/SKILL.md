---
name: xlsx-structure
description: Structural transformations on Excel workbooks with block-aware operations, formula evaluation, style preservation, and topology-aware data movement
---

# XLSX Structure Transformation Skill

## Overview

This skill handles structural transformations on Excel workbooks where data is organized in blocks, tables, or regions that must be manipulated while preserving workbook integrity. Common operations include block-local sorting, filtering, reordering, and layout changes.

## Core Methodology

### 1. Workbook Analysis Phase

**Detect workbook topology:**
- Identify all sheets and their purposes
- Map data regions: contiguous tables, repeated blocks separated by blanks, style-marked areas
- Determine the transformation scope (which sheets, ranges, columns are affected)
- Identify preservation boundaries (what must remain unchanged)

**Detect block structure (when applicable):**
```python
def is_blank_row(ws, row_idx, cols=range(1, 9)):
    """Check if a row is blank within the specified column range."""
    for c in cols:
        val = ws.cell(row=row_idx, column=c).value
        if val is not None and str(val).strip() != '':
            return False
    return True

def detect_blocks(ws, start_row, end_row, cols=range(1, 9)):
    """Detect nonempty blocks separated by blank rows."""
    blocks = []
    current_block_start = None
    for row_idx in range(start_row, end_row + 1):
        if is_blank_row(ws, row_idx, cols):
            if current_block_start is not None:
                blocks.append((current_block_start, row_idx - 1))
                current_block_start = None
        else:
            if current_block_start is None:
                current_block_start = row_idx
    if current_block_start is not None:
        blocks.append((current_block_start, end_row))
    return blocks
```

### 2. Formula Evaluation Phase

**Dependency-aware evaluation:**
When cells contain formulas that reference other cells in the same row, evaluate in dependency order:
- Identify formula patterns (e.g., `=B1+C1`, `=D1+E1`)
- Build dependency graph: which formulas reference which cells
- Evaluate in topological order (dependencies first)

**Row-level formula evaluation with shared cache:**

The critical insight: evaluate the entire row at once using a local cache, not individual cells reading from the worksheet. This avoids the bug where resolving `=D1+E1` reads D1's raw formula string from the worksheet instead of its evaluated value.

```python
import math

# Safe evaluation namespace for formulas with functions
SAFE_EVAL_NS = {"abs": abs, "round": round, "sqrt": math.sqrt, "min": min, "max": max}

def evaluate_row(ws, row_idx, col_range):
    """Evaluate all formula cells in a row using a local cache.
    
    Handles dependency chains within a row (e.g., D=B+C, F=D+E)
    by resolving formulas against the cache, not the worksheet.
    """
    cache = {}  # col_letter -> raw value, then evaluated float
    
    # First pass: load all raw values from the row into cache
    for col_idx in col_range:
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        cache[col_letter] = ws.cell(row=row_idx, column=col_idx).value
    
    # Recursive resolver that reads from cache, not worksheet
    def resolve(value):
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if not s.startswith('='):
            try:
                return float(s)
            except:
                return 0.0
        # It's a formula — substitute refs from cache, then evaluate
        formula = s[1:]
        def replace_ref(match):
            col = match.group(1).upper()
            return str(resolve(cache.get(col, 0.0)))
        expr = re.sub(r'([A-Za-z]+)\d+', replace_ref, formula)
        try:
            # Use safe namespace for functions like ABS, ROUND, SQRT
            return float(eval(expr, {"__builtins__": {}}, SAFE_EVAL_NS))
        except ZeroDivisionError:
            return 0.0  # Handle division by zero gracefully
        except Exception:
            return 0.0  # Handle other evaluation errors
    
    # Resolve all cached values (recursive resolve handles any order)
    for col_letter in list(cache.keys()):
        cache[col_letter] = resolve(cache[col_letter])
    
    return cache  # col_letter -> evaluated float
```

**Why this works:** When resolving F's formula `=D1+E1`, the `replace_ref` function looks up `cache['D']`. If D was already resolved (is now a float), it uses that directly. If D hasn't been resolved yet (still a formula string like `=B1+C1`), the recursive `resolve()` call parses and evaluates it using the same cache. This handles arbitrary dependency chains within a row without requiring explicit ordering.

**Supported operators:** The `eval()` approach handles `+`, `-`, `*`, `/`, `**` (power), parentheses, and negative numbers. Functions like `ABS`, `ROUND`, `SQRT`, `MIN`, `MAX` are available via the `SAFE_EVAL_NS` namespace passed to `eval()`.

**Critical:** Never read formula cell values from the worksheet during evaluation — always use a row-local cache. Reading from the worksheet returns raw formula strings, breaking dependency chains.

### 3. Style Preservation

**Read complete cell state:**
```python
from copy import copy

def read_cell_full(cell):
    """Read cell value and all style attributes."""
    return {
        'value': cell.value,
        'font': copy(cell.font),
        'fill': copy(cell.fill),
        'border': copy(cell.border),
        'alignment': copy(cell.alignment),
        'number_format': cell.number_format,
        'protection': copy(cell.protection),
    }

def write_cell_full(cell, data):
    """Write cell value and all style attributes."""
    cell.value = data['value']
    cell.font = data['font']
    cell.fill = data['fill']
    cell.border = data['border']
    cell.alignment = data['alignment']
    cell.number_format = data['number_format']
    cell.protection = data['protection']
```

**Critical:** Always use `copy()` on style objects. Direct assignment shares mutable objects, causing later mutations to affect multiple cells.

### 4. Transformation Execution

**Block-local operations:**
For each block, operate within its row range to preserve blank separator rows:
```python
for block_start, block_end in blocks:
    # Read all rows in block with full style
    rows_data = []
    for row_idx in range(block_start, block_end + 1):
        row_cells = []
        for col_idx in range(1, num_cols + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            row_cells.append(read_cell_full(cell))
        rows_data.append(row_cells)
    
    # Evaluate formulas if needed
    # Apply transformation (sort, filter, reorder, etc.)
    # Write back to same row positions
    for local_idx, row_cells in enumerate(transformed_rows):
        target_row = block_start + local_idx
        for col_idx in range(1, num_cols + 1):
            cell = ws.cell(row=target_row, column=col_idx)
            write_cell_full(cell, row_cells[col_idx - 1])
```

**Stable sorting:**
When sorting by a key, preserve original order for equal values:
```python
indexed_rows = [(sort_key[i], i, rows_data[i]) for i in range(len(rows_data))]
indexed_rows.sort(key=lambda x: (-x[0], x[1]))  # descending by key, then by original index
```

### 5. Preservation Verification

**After transformation, verify:**
- Blank separator rows remain blank
- Values outside transformation range are unchanged
- Column dimensions, row heights preserved
- Styles (font, fill, border, alignment) intact
- Merged cells, filters, panes unchanged
- Other sheets unaffected

```python
# Verify blank rows
for blank_row in blank_row_indices:
    assert all(ws.cell(row=blank_row, column=c).value is None for c in range(1, num_cols + 1))

# Verify values outside range
for r in range(1, ws.max_row + 1):
    for c in range(1, ws.max_column + 1):
        if (r, c) not in transformation_range:
            assert ws_in.cell(row=r, column=c).value == ws_out.cell(row=r, column=c).value
```

## Common Transformation Patterns

> **Style Preservation Invariant (applies to ALL patterns below):**
> Every transformation that moves data between cells — sort, filter, append, reconcile, extract, transpose — MUST use `read_cell_full`/`write_cell_full` for every cell it touches. Copying only `value`, or only `font`+`alignment`, silently drops `fill`, `border`, `number_format`, and `protection`. This is the single most common source of silent failures in this family. When adding a new transformation pattern, verify it uses the full read/write pair for every cell.

### Block-Local Sorting
Sort rows within each block by a column's evaluated value:
- Detect blocks
- For each block: read rows → evaluate formulas → stable sort → write back
- Preserve blank separators

### Predicate-Based Filtering
Select rows matching criteria and compact into output range:
- Identify selection predicate (numeric threshold, text match, style match)
- Collect matching rows with full style
- Write to destination range, maintaining row integrity

**Style-based selection (filtering by fill color):**
```python
def get_fill_color(cell):
    """Extract fill color as RGB tuple or None."""
    fill = cell.fill
    if fill.patternType is None:
        return None
    # fgColor is the foreground fill color
    color = fill.fgColor
    if color.type == 'rgb' and color.rgb and color.rgb != '00000000':
        # RGB format: AARRGGBB or RRGGBB
        rgb = color.rgb
        if len(rgb) == 8:  # AARRGGBB
            return (int(rgb[2:4], 16), int(rgb[4:6], 16), int(rgb[6:8], 16))
        elif len(rgb) == 6:  # RRGGBB
            return (int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16))
    return None

def filter_by_fill_color(ws, row_range, target_color, col_idx=1):
    """Select rows where column col_idx has the target fill color."""
    matching_rows = []
    for row_idx in row_range:
        cell = ws.cell(row=row_idx, column=col_idx)
        color = get_fill_color(cell)
        if color == target_color:
            # Read entire row with styles
            row_data = [read_cell_full(ws.cell(row=row_idx, column=c)) 
                       for c in range(1, ws.max_column + 1)]
            matching_rows.append(row_data)
    return matching_rows
```

### Header-Aligned Append
Append data to existing table, aligning by column headers:
- Read source data and destination headers
- Map source columns to destination columns by header name
- Append rows to destination, preserving existing data

```python
def append_by_header_alignment(src_ws, dst_ws, src_range, dst_start_row):
    """Append source rows to destination, aligning columns by header names.
    Uses read_cell_full/write_cell_full to preserve all styles."""
    # Read destination headers
    dst_headers = {}
    for col_idx in range(1, dst_ws.max_column + 1):
        header = dst_ws.cell(row=1, column=col_idx).value
        if header:
            dst_headers[str(header).strip()] = col_idx
    
    # Read source headers and build mapping
    src_headers = {}
    for col_idx in range(1, src_ws.max_column + 1):
        header = src_ws.cell(row=1, column=col_idx).value
        if header:
            src_headers[str(header).strip()] = col_idx
    
    # Map source columns to destination columns
    col_mapping = {}
    for src_name, src_col in src_headers.items():
        if src_name in dst_headers:
            col_mapping[src_col] = dst_headers[src_name]
    
    # Append source rows to destination with full style preservation
    dst_row = dst_start_row
    for src_row in range(2, src_ws.max_row + 1):  # Skip header row
        for src_col, dst_col in col_mapping.items():
            src_cell = src_ws.cell(row=src_row, column=src_col)
            dst_cell = dst_ws.cell(row=dst_row, column=dst_col)
            # Use read_cell_full/write_cell_full to preserve ALL styles
            cell_data = read_cell_full(src_cell)
            write_cell_full(dst_cell, cell_data)
        dst_row += 1
```

### Sparse Record Reconciliation
Match ordered ID lists with sparse data tables:
- Read ID list and sparse data
- For each ID, find corresponding data row
- Write consolidated output with complete records

```python
def reconcile_ids_with_sparse_data(id_ws, data_ws, id_col, data_id_col, output_ws):
    """Match an ordered ID list with sparse data, writing consolidated output.
    Uses read_cell_full/write_cell_full to preserve all styles."""
    # Read ID list (ordered)
    ids = []
    for row_idx in range(1, id_ws.max_row + 1):
        id_val = id_ws.cell(row=row_idx, column=id_col).value
        if id_val is not None:
            ids.append(id_val)
    
    # Build data lookup by ID with FULL STYLE preservation
    data_lookup = {}
    for row_idx in range(1, data_ws.max_row + 1):
        row_id = data_ws.cell(row=row_idx, column=data_id_col).value
        if row_id is not None:
            # Read entire row with styles using read_cell_full
            row_data = []
            for col_idx in range(1, data_ws.max_column + 1):
                cell = data_ws.cell(row=row_idx, column=col_idx)
                row_data.append(read_cell_full(cell))
            data_lookup[row_id] = row_data
    
    # Write consolidated output in ID order with full style preservation
    output_row = 1
    for id_val in ids:
        if id_val in data_lookup:
            row_data = data_lookup[id_val]
            # Write each cell with full style using write_cell_full
            for col_idx, cell_data in enumerate(row_data, 1):
                output_cell = output_ws.cell(row=output_row, column=col_idx)
                write_cell_full(output_cell, cell_data)
        else:
            # ID not found in data - write ID only or handle as needed
            output_ws.cell(row=output_row, column=data_id_col).value = id_val
        output_row += 1
```

### Row Extraction
Extract specific rows based on criteria and write to a new location:
```python
def extract_rows_by_predicate(ws, row_range, predicate, output_ws, output_start_row):
    """Extract rows matching predicate and write to output."""
    output_row = output_start_row
    for row_idx in row_range:
        # Evaluate predicate (e.g., check a cell value, style, etc.)
        if predicate(ws, row_idx):
            # Copy entire row with styles
            for col_idx in range(1, ws.max_column + 1):
                src_cell = ws.cell(row=row_idx, column=col_idx)
                dst_cell = output_ws.cell(row=output_row, column=col_idx)
                cell_data = read_cell_full(src_cell)
                write_cell_full(dst_cell, cell_data)
            output_row += 1
    return output_row - output_start_row  # Number of rows extracted
```

### Layout Transposition
Convert rows to columns or vice versa:
```python
def transpose_range(src_ws, src_range, dst_ws, dst_start_cell):
    """Transpose a rectangular range (rows become columns)."""
    start_row, end_row, start_col, end_col = src_range
    dst_row, dst_col = dst_start_cell
    
    for src_r in range(start_row, end_row + 1):
        for src_c in range(start_col, end_col + 1):
            src_cell = src_ws.cell(row=src_r, column=src_c)
            # Transpose: (row, col) -> (col, row)
            out_r = dst_row + (src_c - start_col)
            out_c = dst_col + (src_r - start_row)
            dst_cell = dst_ws.cell(row=out_r, column=out_c)
            cell_data = read_cell_full(src_cell)
            write_cell_full(dst_cell, cell_data)
```

## Implementation Checklist

- [ ] Load workbook with `data_only=False` to access formulas
- [ ] Detect transformation scope and block structure
- [ ] Identify formula dependencies and evaluation order
- [ ] Read all affected cells with complete style information using `copy()`
- [ ] Evaluate formulas in dependency order
- [ ] Apply transformation (sort/filter/reorder) within block boundaries
- [ ] Write back values and styles to destination cells
- [ ] Verify blank rows, preservation constraints, and style integrity
- [ ] Save to output file

## Failure Modes to Avoid

1. **Formula evaluation order:** Evaluating F before D when F depends on D
2. **Style sharing:** Assigning `cell.font = other.font` without `copy()`
3. **Block boundary drift:** Sorting across blank rows, misaligning blocks
4. **Formula strings in output:** Writing `=B1+C1` instead of evaluated numeric value
5. **Lexical vs numeric sort:** Sorting "115.6" as string instead of float
6. **Partial row movement:** Moving only some columns, breaking row integrity
7. **Overwriting preservation zone:** Modifying cells outside transformation range
8. **Partial style copy:** Copying only font+alignment but dropping fill, border, number_format, protection — always use `read_cell_full`/`write_cell_full`
9. **Worksheet reads during formula eval:** Reading formula cells from the worksheet instead of a row-local cache breaks dependency chains

## OpenPyXL Best Practices

- Use `openpyxl.load_workbook(path, data_only=False)` to read formulas
- Use `openpyxl.utils.column_index_from_string('A')` for column letter to index conversion
- Access cell styles: `cell.font`, `cell.fill`, `cell.border`, `cell.alignment`, `cell.number_format`, `cell.protection`
- Check merged cells: `ws.merged_cells.ranges`
- Check auto filters: `ws.auto_filter.ref`
- Column dimensions: `ws.column_dimensions[col_letter].width`
- Row dimensions: `ws.row_dimensions[row_idx].height`

## Adaptation to New Variants

When encountering a new xlsx-structure task:
1. Parse the task description to identify transformation type
2. Determine workbook topology (single/multi-sheet, blocks/tables/sparse)
3. Identify selection/alignment rules (numeric order, header matching, style predicates)
4. Determine output geometry (destination sheet, range, append/insert mode)
5. Identify preservation constraints (what must remain unchanged)
6. Apply the appropriate transformation pattern from this skill
7. Verify all preservation constraints after transformation
