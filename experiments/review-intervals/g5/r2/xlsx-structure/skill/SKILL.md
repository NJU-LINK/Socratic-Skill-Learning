---
name: xlsx-structure
description: >
  Perform structural transformations on Excel workbooks using openpyxl: block-local
  sorting, predicate-based filtering and compaction, header-aligned append, sparse-record
  reconciliation, row extraction, and layout transposition. The skill covers the full
  lifecycle — topology detection, formula evaluation, row-level manipulation with style
  preservation, output geometry, and workbook-state preservation — for any task that
  reshapes data within or across sheets of an .xlsx file.
---

# xlsx-structure

This skill applies to any task that requires reading an input workbook, performing a
structural transformation on its data, and writing an output workbook while preserving
everything outside the transformation scope.

## Quick Start: Minimal Exploration Pattern

**Goal:** Minimize tool calls by combining exploration and solution.

**When to use:** When the task description is clear and you can infer most parameters from context.

**Pattern:**
```python
# Single script: explore + solve + verify
import openpyxl
from copy import copy

# Load workbook
wb_formulas = openpyxl.load_workbook('input.xlsx', data_only=False)
wb_values = openpyxl.load_workbook('input.xlsx', data_only=True)
ws_f = wb_formulas['Sheet1']
ws_v = wb_values['Sheet1']

# Quick exploration (print key info)
print(f"Sheets: {wb_formulas.sheetnames}")
print(f"Dimensions: {ws_f.dimensions}")
print(f"Merged cells: {ws_f.merged_cells.ranges}")
print(f"Auto filter: {ws_f.auto_filter.ref}")
print(f"Freeze panes: {ws_f.freeze_panes}")

# Sample a few rows to understand structure
for r in [1, 2, 8, 9]:
    vals = [ws_f.cell(row=r, column=c).value for c in range(1, 9)]
    print(f"Row {r}: {vals}")

# Check cached values for formula columns
for r in [1, 2]:
    d = ws_v.cell(row=r, column=4).value
    f = ws_v.cell(row=r, column=6).value
    print(f"Row {r} cached: D={d}, F={f}")

# ... then proceed with solution ...
```

**Key principle:** Do exploration in the SAME script as the solution, not in separate calls.
This saves 2-3 tool calls per task.

## 1. Task Analysis Framework

Before writing any code, extract these five dimensions from the task description:

| Dimension | Question to answer | Examples |
|---|---|---|
| **Transformation semantics** | What operation? | Sort within blocks, filter rows, append to existing data, reconcile IDs, extract rows, transpose layout |
| **Workbook topology** | Where is the data? | Single sheet contiguous table, multiple sheets, blocks separated by blank rows, sparse ranges, style-marked regions, header-mapped columns |
| **Selection & alignment rule** | How to select/order? | Evaluated numeric value descending, membership in another range, exact header/ID match, fill color predicate, text predicate with exclusions, positional correspondence |
| **Output geometry** | Where to write? | Same range on same sheet, new sheet, appended below existing data, inserted at a position, transposed orientation |
| **Preservation constraints** | What must not change? | Other sheets, values outside the target range, cell styles, column widths, row heights, merged ranges, auto-filters, freeze panes, sheet views |

## 2. General Procedure

### 2.1 Load the workbook (dual-load pattern)

```python
import openpyxl
from copy import copy

# Load twice: once for formulas/styles (writing), once for cached values (reading)
wb_formulas = openpyxl.load_workbook(input_path, data_only=False)
wb_values   = openpyxl.load_workbook(input_path, data_only=True)

ws_f = wb_formulas[sheet_name]
ws_v = wb_values[sheet_name]
```

**Why dual-load:** `data_only=False` preserves formulas and styles needed for writing.
`data_only=True` gives cached computed values for formula cells. If cached values are
missing (common with openpyxl-generated files), fall back to manual evaluation (see §2.3).

### 2.2 Detect topology

Scan the target range to discover the structure:

- **Blank-row-separated blocks:** Iterate rows; a row is blank if all cells in the
  relevant columns are `None` or empty string. Group contiguous non-blank rows into blocks.
- **Header-mapped tables:** Find the header row, map column names to indices.
- **Style-marked regions:** Check cell fill colors or fonts to identify section boundaries.
- **Sparse ranges:** Identify which cells contain data vs. are empty.

```python
def detect_blank_row_separated_blocks(ws, start_row, end_row, col_range):
    """Returns list of (start_row, end_row) tuples for each block."""
    blocks = []
    current_start = None
    for row_idx in range(start_row, end_row + 1):
        has_data = any(
            ws.cell(row=row_idx, column=c).value not in (None, '')
            for c in col_range
        )
        if has_data:
            if current_start is None:
                current_start = row_idx
        else:
            if current_start is not None:
                blocks.append((current_start, row_idx - 1))
                current_start = None
    if current_start is not None:
        blocks.append((current_start, end_row))
    return blocks
```

### 2.3 Evaluate formulas — decision tree

**CRITICAL DECISION: Use cached values directly when they exist.**

When `data_only=True` returns non-None numeric values for formula cells, **use those
values directly** — do NOT re-compute them. Cached values are the ground truth from
Excel and preserve exact floating-point representation. Re-computing can introduce
subtle differences (e.g., `224.89999999999998 + 114.5 = 339.39999999999998` but the
cached value is `339.4`).

**Only fall back to manual evaluation when cached values are None** (common with
openpyxl-generated workbooks that don't compute cached values).

```python
def get_evaluated_value(ws_values, ws_formulas, row, col):
    """Get the numeric value of a cell, handling formulas.
    
    PREFERRED: Use cached values directly (they're the ground truth).
    FALLBACK: Manual evaluation only when cached values are None.
    """
    # PREFERRED: Try cached value first (from data_only=True load)
    val_v = ws_values.cell(row=row, column=col).value
    if val_v is not None and isinstance(val_v, (int, float)):
        return val_v  # Use directly — do NOT re-compute

    # FALLBACK: Cached value is None, need manual evaluation
    val_f = ws_formulas.cell(row=row, column=col).value
    if isinstance(val_f, (int, float)):
        return float(val_f)
    if isinstance(val_f, str):
        # Try parsing as number
        try:
            return float(val_f)
        except ValueError:
            pass
        # If it's a formula string, parse and evaluate manually
        if val_f.startswith('='):
            return evaluate_formula_manual(ws_formulas, row, val_f)

    # Last resort: try cached value as numeric string
    if isinstance(val_v, str):
        try:
            return float(val_v)
        except ValueError:
            pass
    return None
```

**Manual formula evaluation** (only when cached values are None):
- Parse the expression: extract cell references (e.g., `B1`, `C1`)
- Look up referenced cell values in the same row (or absolute references)
- Evaluate the arithmetic expression
- **Dependency order matters:** If column F references column D, evaluate D first,
  then use the evaluated D value when computing F.

**For writing output:** When the task requires replacing formulas with evaluated values,
write the cached values directly (preserving their int/float types). Do NOT re-compute
unless the task explicitly requires re-evaluation from source cells.

### 2.4 Collect row data with styles

When moving rows (for sorting, filtering, etc.), carry the complete row including styles:

```python
def collect_row(ws, row_idx, col_range):
    """Collect cell values and styles for a row."""
    row_data = {
        'values': [],
        'styles': [],
    }
    for col in col_range:
        cell = ws.cell(row=row_idx, column=col)
        row_data['values'].append(cell.value)
        row_data['styles'].append({
            'font': copy(cell.font),
            'fill': copy(cell.fill),
            'border': copy(cell.border),
            'alignment': copy(cell.alignment),
            'number_format': cell.number_format,
        })
    return row_data
```

### 2.5 Perform the transformation

Adapt to the specific transformation semantics:

- **Sort:** Sort rows within each block by the alignment rule (e.g., evaluated D descending).
  Use Python's stable sort (`list.sort()` or `sorted()`) to preserve original order for ties.
- **Filter:** Select rows matching the predicate, compact them to the output range.
- **Append:** Write new rows after existing data in the destination range.
- **Reconcile:** Match source IDs to destination positions, fill in missing values.
- **Extract:** Copy selected rows to a new location.
- **Transpose:** Swap rows and columns.

### 2.6 Write output with style preservation

```python
def write_row(ws, row_idx, row_data, col_range):
    """Write cell values and styles to a row."""
    for i, col in enumerate(col_range):
        cell = ws.cell(row=row_idx, column=col)
        cell.value = row_data['values'][i]
        style = row_data['styles'][i]
        cell.font = style['font']
        cell.fill = style['fill']
        cell.border = style['border']
        cell.alignment = style['alignment']
        cell.number_format = style['number_format']
```

**For formula columns (D–F or similar):** Write the *evaluated numeric value*, not the
formula string. The task typically requires replacing formulas with their computed results.

### 2.7 Save and verify

```python
wb_formulas.save(output_path)
```

After saving, do **one comprehensive verification** (not multiple separate scripts):
1. Blank rows are in the correct positions (for block-based layouts)
2. Sort/filter order is correct within each block (if applicable)
3. Values outside the transformation range are unchanged
4. Column widths, row heights, merged cells, filters, and panes are preserved
5. Cell types are correct (numeric cells should be numeric, not strings)
6. No formula strings remain in the output range

**Efficiency note:** Combine all verification checks into a single script to avoid
wasting tool calls on redundant verification loops.

## 3. Preservation Checklist

Before saving, verify that the following are unchanged from the input:

- [ ] All sheets other than the target sheet
- [ ] All values outside the target range (columns beyond the range, rows beyond the range)
- [ ] Column widths for all columns
- [ ] Row heights for all rows (if custom heights exist)
- [ ] Merged cell ranges
- [ ] Auto-filter settings
- [ ] Freeze pane settings
- [ ] Sheet view settings (zoom, selection, top-left cell)
- [ ] Cell styles (font, fill, border, alignment, number_format) for cells outside the transformation

## 4. Common Pitfalls

### 4.1 Formula evaluation
- **Cached values may be None:** If the workbook was created by openpyxl or a library
  that doesn't compute cached values, `data_only=True` returns `None` for formula cells.
  Always have a manual evaluation fallback.
- **Dependency chains:** When column F references column D, and both are formulas,
  evaluate D first, then use the evaluated result for F.
- **Text-formula cells:** Some cells store formula text as strings (e.g., `"=B1+C1"`
  stored as a string, not as a formula). Handle both cases.

### 4.2 Type fidelity
- Cells that look like numbers may be stored as strings. Check `type(cell.value)`
  to distinguish. When writing output, preserve the original type unless the task
  specifically requires conversion (e.g., replacing formulas with numeric results).
- `0` (int), `0.0` (float), and `'0'` (str) are different. The task may care about
  which type is written.

### 4.3 Blank row detection
- A blank row has ALL relevant cells as `None` or empty string. A row with a single
  space or zero is NOT blank.
- Some workbooks have "partially blank" rows (e.g., only column A has data). Define
  "blank" based on the task's relevant column range.

### 4.4 Style preservation during row moves
- When sorting or reordering rows, the styles must move with the data, not stay at
  the original positions. Collect styles per-row, then write them to the new positions.
- `copy()` is needed for style objects; direct assignment shares references.

### 4.5 Floating-point comparison
- Evaluated formula results may have floating-point artifacts (e.g., `224.89999999999998`
  instead of `224.9`). When comparing for sort order, use the raw float values.
  When writing, consider rounding if the task requires it.
- **Do NOT re-compute formula values when cached values exist.** The cached values
  are the ground truth. Re-computing `D + E` in Python may give slightly different
  results from the cached `F` value due to floating-point arithmetic.

### 4.6 Blank row preservation
- Blank rows within the target range often have styles (e.g., column D may be bold
  even on blank rows). **Do not modify blank rows at all** — leave their values and
  styles untouched.
- When detecting blocks, blank rows serve as separators. After transformation, ensure
  exactly one blank row between adjacent blocks (as specified by the task).

## 5. Adaptation Guide

When facing a new member of this family:

1. **Read the task description carefully** and extract the five dimensions (§1).
2. **Inspect the input workbook** to understand the actual topology — don't assume
   it matches v01 exactly.
3. **Identify which columns contain formulas** and what they reference.
4. **Determine the output range** — it may differ from the input range.
5. **Check for cross-sheet references** — the transformation may involve multiple sheets.
6. **Adapt the block detection** if the topology uses style markers, headers, or
   sparse ranges instead of blank-row separators.
7. **Adapt the transformation** to the specific semantics (sort, filter, append, etc.).
8. **Verify preservation** of everything outside the transformation scope.

## 6. Efficiency Guidelines

- **Do one comprehensive verification**, not multiple separate scripts. Combine all
  checks (sort order, preservation, formula removal, type fidelity) into a single
  verification pass.
- **Don't second-guess cached values.** If `data_only=True` returns numeric values,
  use them directly. Don't waste tool calls re-computing and comparing.
- **Write the solution once.** If the logic is correct, don't rewrite it multiple
  times due to floating-point anxiety. The cached values are the ground truth.
- **Combine exploration and solution** in a single script when possible. Print key
  info (sheet names, dimensions, sample rows, cached values) at the start of your
  solution script, then proceed with the transformation. This saves 2-3 tool calls.

## 7. Common Transformation Patterns

Different tasks in this family share common patterns. Identify which pattern applies
to your task and adapt the template accordingly.

### Pattern A: Block-Local Sort (v01 pattern)
**When:** Rows form blocks separated by blank rows; sort within each block by a column.

**Key steps:**
1. Detect blocks from blank-row separators
2. For each block, collect rows with styles and evaluated values
3. Sort by the alignment rule (e.g., column D descending, stable sort)
4. Write sorted rows back with evaluated values for formula columns
5. Preserve blank rows as-is

**Critical details:**
- Use cached values for formula columns (D, F) — don't re-compute
- Blank rows have styles too — don't modify them
- Stable sort preserves original order for ties

### Pattern B: Predicate-Based Filter & Compact
**When:** Select rows matching a condition, compact them to a contiguous range.

**Key steps:**
1. Identify the predicate (e.g., fill color, text match, numeric threshold)
2. Scan the source range, collect matching rows with styles
3. Write matching rows to the destination range (contiguous, no gaps)
4. Clear or preserve non-matching rows as specified

**Critical details:**
- Predicate may involve cell styles (fill color, font) — check `cell.fill`, `cell.font`
- Destination range may be different from source range
- May need to preserve non-matching rows elsewhere

### Pattern C: Header-Aligned Append
**When:** Append new rows to an existing table, aligning columns by header names.

**Key steps:**
1. Find the header row in the destination table
2. Map header names to column indices
3. For each new row, align values to the correct columns based on headers
4. Append below existing data

**Critical details:**
- Headers may not be in the same order as source data
- Some destination columns may not have matching source columns (leave blank or use default)
- Preserve existing data and styles above the append point

### Pattern D: Sparse-Record Reconciliation
**When:** Match source IDs to destination positions, fill in missing values.

**Key steps:**
1. Identify the ID column in both source and destination
2. Build a mapping: ID → source row data
3. For each destination row, look up the matching source row by ID
4. Fill in missing values from source to destination

**Critical details:**
- IDs may be in different orders
- Some destination rows may not have matching source rows (leave as-is)
- Some source rows may not have matching destination rows (ignore or append)

### Pattern E: Row Extraction
**When:** Copy selected rows to a new location (different sheet or range).

**Key steps:**
1. Identify which rows to extract (by predicate, position, or ID list)
2. Collect row data with styles
3. Write to the destination range/sheet
4. Preserve source data as-is (unless task says to delete)

**Critical details:**
- Destination may be a new sheet (create it) or an existing sheet
- May need to preserve or clear the destination area first
- Styles should be copied, not referenced

### Pattern F: Layout Transposition
**When:** Swap rows and columns (rotate the data 90 degrees).

**Key steps:**
1. Read the source range into a 2D array
2. Transpose the array (rows become columns, columns become rows)
3. Write the transposed array to the destination range
4. Handle styles carefully — they may not transpose cleanly

**Critical details:**
- Transposing styles is complex — cell A1's style goes to the transposed position
- May need to adjust column widths and row heights
- Formulas may need to be re-evaluated after transposition

## 8. Verification Checklist

Before declaring the task complete, verify:

- [ ] **Transformation correctness:** Sort order, filter results, append alignment, etc.
- [ ] **Formula evaluation:** No formula strings remain in the output range
- [ ] **Blank row preservation:** Blank rows are in the correct positions (for block-based layouts)
- [ ] **Style preservation:** Cell styles (font, fill, border, alignment) are preserved
- [ ] **Column widths:** All column widths match the input
- [ ] **Row heights:** Custom row heights are preserved (if any)
- [ ] **Values outside target range:** No changes to cells outside the transformation scope
- [ ] **Sheet preservation:** All sheets are present, other sheets unchanged
- [ ] **Workbook metadata:** Merged cells, auto-filters, freeze panes preserved

**Efficiency tip:** Combine all these checks into a single verification script at the end
of your solution, not separate scripts for each check.
