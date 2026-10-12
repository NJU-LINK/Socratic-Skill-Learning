---
name: xlsx-structure
description: Transform Excel workbook structure with block detection, formula evaluation, stable sorting, and preservation of workbook state. Handles block-local sorting, predicate filtering, header-aligned append, sparse-record reconciliation, and layout operations while preserving styles, merged ranges, filters, panes, and out-of-scope data.
---

# xlsx-structure Skill

## Overview

This Skill handles structural transformations on Excel workbooks where data is organized in blocks separated by blank rows. The transformations include:

- **Block-local sorting**: Sort rows within each block by evaluated numeric values
- **Formula evaluation**: Convert text formulas and Excel formulas to numeric values
- **Stable tie preservation**: When sort keys are equal, preserve original relative order
- **Workbook preservation**: Maintain styles, merged cells, filters, freeze panes, row heights, column widths, and out-of-scope data

## Core Invariants

### 1. Block Detection
- Blocks are contiguous non-blank row ranges
- Blank rows (all cells None/empty) separate blocks
- Detection must work dynamically from workbook content, not fixed row counts

### 2. Formula Evaluation
- Support Excel formulas (evaluated via openpyxl with `data_only=False`) and text formulas (strings starting with `=`)
- Handle cross-references (e.g., `=B1+C1`, `=D1+E1`)
- Evaluate recursively when referenced cells contain formulas
- Write numeric results, not formula strings

### 3. Extraction Width (Critical)
- Extract **FULL answer-range width**, not just `max(sort_col, eval_cols)`
- For A1:H85, extract all 8 columns (A through H)
- "Sort complete rows" means all columns travel with the row
- **Failure mode**: extracting only 6 columns and padding with None clears G, H cells

### 4. Stable Sorting (Critical)
- Use **stable sort** with descending key (e.g., `sort(key=lambda r: -r.d_value)`)
- **NEVER** use `sort()` followed by `reverse()` - this flips tie order
- **NEVER** use `reverse=True` with tuple keys containing original index - reverses tie order
- When spec says "preserve original relative order", carry original row index alongside data
- Verify: for adjacent in-block pairs with equal sort key, original indices must be strictly increasing

### 5. Output Geometry
- Write transformed data starting at specified cell
- Insert exactly one blank row between blocks
- Target range must match specified bounds (e.g., A1:H85)

### 6. Preservation Constraints
- Load workbook with `data_only=False` to access formulas
- Edit cells in place within target range
- Save modified workbook to preserve:
  - Cell styles (number format, font, fill, border, alignment)
  - Merged cell ranges
  - Filters and freeze panes
  - Row heights and column widths
  - Out-of-range values (rows/columns outside target, other sheets)

## Core Pipeline

All transformations follow the same pipeline:

```
detect → extract → evaluate → transform → write → preserve
```

### 1. Block Detection
```python
blocks = detect_blocks(sheet, max_row, num_cols)
```

### 2. Row Extraction
```python
for row_idx in block:
    values = extract_row_data(sheet, row_idx, num_cols)
```

### 3. Formula Evaluation
```python
for col in eval_cols:
    values[col - 1] = evaluate_formula(values[col - 1], sheet)
```

### 4. Transformation (pluggable)
```python
# Sorting
rows.sort(key=lambda r: -r['sort_val'])  # stable descending

# Filtering
rows = [r for r in rows if predicate(r['values'])]
```

### 5. Write Back
```python
write_blocks(sheet, blocks_data, start_row=1)
wb.save(output_path)
```

## Modular Transformer Design

Use the `BlockTransformer` abstract base class to implement new transformations:

```python
from abc import ABC, abstractmethod

class BlockTransformer(ABC):
    @abstractmethod
    def transform(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform a list of row dictionaries."""
        pass

class BlockSorter(BlockTransformer):
    def __init__(self, sort_col: int, descending: bool = True):
        self.sort_col = sort_col
        self.descending = descending
    
    def transform(self, rows):
        for row in rows:
            row['sort_val'] = row['values'][self.sort_col - 1]
        key = lambda r: -r['sort_val'] if self.descending else r['sort_val']
        return sorted(rows, key=key)  # Python sort is stable

class BlockFilter(BlockTransformer):
    def __init__(self, predicate: Callable):
        self.predicate = predicate
    
    def transform(self, rows):
        return [r for r in rows if self.predicate(r['values'])]
```

Usage:
```python
transformer = BlockSorter(sort_col=4, descending=True)
transform_workbook(input_path, output_path, transformer, ...)
```

## Formula Evaluation

For text formulas like `=B1+C1`:

```python
import re

def evaluate_formula(formula, sheet):
    if not isinstance(formula, str) or not formula.startswith('='):
        return float(formula) if formula is not None else 0
    
    expr = formula[1:]
    pattern = r'([A-Z]+)(\d+)'
    
    def replace_ref(match):
        col_str, row_num = match.group(1), int(match.group(2))
        col_num = sum((ord(c) - 64) * (26 ** i) 
                     for i, c in enumerate(reversed(col_str)))
        val = sheet.cell(row=row_num, column=col_num).value
        if isinstance(val, str) and val.startswith('='):
            val = evaluate_formula(val, sheet)
        return str(float(val)) if val is not None else '0'
    
    expr = re.sub(pattern, replace_ref, expr)
    return eval(expr)
```

## Verification Checklist

Before committing output, verify:

1. **Full Grid Match**: Recompute expected grid from input (same evaluation logic) and compare cell-by-cell
2. **Tie Order**: For every adjacent in-block pair with equal evaluated sort key, original indices strictly increase
3. **Separators**: Exactly one blank row between blocks, last block ends at range boundary
4. **Formula Evaluation**: No `=` strings remain in evaluated columns
5. **Preservation**: Out-of-scope state unchanged (other sheets, rows > max_row, cols > max_col)

### Verification Code Requirements

Every check must exist as executable code in `verify_output`:

```python
def verify_output(input_path, output_path, ...):
    # 1. Build expected grid independently from input
    expected = build_expected_grid(input_path, ...)
    
    # 2. Compare cell-by-cell with tolerance for floats
    for row_idx, col_idx in target_range:
        actual = sheet_out.cell(row=row_idx, column=col_idx).value
        expected_val = expected[row_idx-1][col_idx-1]
        assert cells_equal(actual, expected_val)
    
    # 3. Test negative control (corrupted output should fail)
    assert not verify_output(input_path, corrupted_output_path, ...)
```

**Negative control**: Corrupt one cell in a copy of output, verify the checker flags it. A verifier that cannot fail is not evidence.

## Common Failure Modes

- **Truncated extraction**: Using `max(sort_col, eval_cols)` instead of full answer-range width clears columns beyond sort/eval range
- **Flipped ties**: Using `sort(); reverse()` instead of `sort(key=lambda r: -r.key)`
- **Tuple reverse bug**: Using `reverse=True` with tuple `(sort_val, orig_idx)` reverses tie order
- **Formula text**: Writing formula strings instead of evaluated values
- **Row reference drift**: Formulas evaluated against current row instead of original row
- **Lost preservation**: Creating new workbook instead of editing in place
- **Blind verifier**: Verifier that only checks structure but not actual cell values
- **Circular formula reference**: Formulas like `=A1` where A1 contains `=A1` cause `RecursionError` at depth 10 (explicit, not silent)

## Extending for New Transformations

To add a new transformation type:

1. **Create a new BlockTransformer subclass:**
```python
class BlockExtractor(BlockTransformer):
    """Extract rows matching a pattern."""
    def __init__(self, pattern: str, col: int):
        self.pattern = pattern
        self.col = col
    
    def transform(self, rows):
        return [r for r in rows 
                if self.pattern in str(r['values'][self.col - 1])]
```

2. **Add to the transform argument choices:**
```python
parser.add_argument('--transform', choices=['block-sort', 'block-filter', 'block-extract'])
```

3. **Implement specific verification:**
```python
def verify_extract_output(input_path, output_path, pattern, col):
    # Recompute expected independently
    # Compare cell-by-cell
    pass
```

## Variation Dimensions

Per spec.yaml, family members vary across:

- `transformation_semantics`: sort, filter, append, reconcile, extract, transpose
- `workbook_topology`: single/multi-sheet, contiguous/repeated blocks, style-marked cells
- `selection_and_alignment_rule`: numeric order, membership, header identity, fill color, text predicates
- `output_geometry`: target sheet, range, orientation, append/insert/compaction
- `preservation_constraints`: specific elements that must remain intact

The core pipeline (detect → evaluate → transform → write → preserve) applies across all variants.

## Quick Start

For the common block-sort task (like v01):

```bash
python3 /skill/scripts/transform.py input.xlsx output.xlsx --verify
```

Or use the dedicated v01 solver:

```bash
python3 /skill/scripts/solve_v01.py input.xlsx output.xlsx
```

## Script Reference

- `scripts/transform.py`: Modular transformation framework with BlockTransformer base class, tail clearing, and generic verification. Usage:
  ```bash
  python3 transform.py input.xlsx output.xlsx --verify --test-negative-control
  python3 transform.py input.xlsx output.xlsx --transform block-filter --verify
  ```
- `scripts/solve_v01.py`: Dedicated solver for block-sort tasks (v01 pattern)
- `scripts/block_transform.py`: Thin wrapper importing from transform.py (backward compatibility)

## Honest Verification Dispositions

A transformation is only "verified" when independently executed and diffed:

- **block-sort**: VERIFIED on v01 task with 9 blocks, 77 rows, tie order preserved
- **block-filter**: VERIFIED on synthetic test with 2 blocks, compaction and tail clearing confirmed
- **block-extract**: BOUNDED - extension point documented but not independently tested
- **append/reconcile/transpose**: BOUNDED - not yet implemented

Rule: A `BlockTransformer` subclass is not "supported" until executed and diffed once.

## Compaction Safety

For transforms that remove rows (filter, extract), the write phase must clear the tail:

```python
def write_blocks(sheet, blocks_data, start_row, max_row, num_cols):
    # ... write transformed data ...
    
    # Clear separator rows explicitly
    if block_idx < len(blocks_data) - 1:
        for c in range(1, num_cols + 1):
            sheet.cell(row=output_row, column=c).value = None
        output_row += 1
    
    # Clear tail below written extent
    for r in range(last_written + 1, max_row + 1):
        for c in range(1, num_cols + 1):
            sheet.cell(row=r, column=c).value = None
```

**Failure mode**: Without tail clearing, stale source rows remain below the compaction boundary.
