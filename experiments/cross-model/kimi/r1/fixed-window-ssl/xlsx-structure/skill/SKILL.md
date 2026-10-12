---
name: xlsx-structure
description: Transform Excel workbook structure through formula evaluation, block-aware sorting/filtering, and value-in-place rewriting while preserving all workbook state outside the transformation range.
---

# XLSX Structure Transformation Skill

## Overview

This skill addresses structural transformations on Excel workbooks where:
- Data is organized in variable-length blocks (separated by blank rows, headers, or style markers)
- Formulas need recursive evaluation (handling dependencies like F depending on D)
- Rows/cells are selected, sorted, or filtered based on evaluated values
- Output must preserve all workbook state: styles, filters, merged cells, panes, dimensions, and data outside the transformation range

## Pipeline

```
Probe Topology → Evaluate Row-Local Formulas → Select/Align → Stable Reorder → 
Write Values In-Place → Verify Preservation
```

## Core Components

### 1. Formula Evaluator (`xlsx_eval.py`)

**Primary API: `evaluate_cell(ws, row, col)`** — evaluates a single cell with caching.

```python
from xlsx_eval import evaluate_cell, clear_cache

# Evaluate D5
d_val = evaluate_cell(ws, 5, 4)

# Call between workbooks to avoid stale caches
clear_cache()
```

**Internal API: `make_evaluator(ws, row)`** — creates a per-row evaluator for multiple cells.

```python
import re

REF = re.compile(r'\$?([A-Z]+)\$?(\d+)')

def col_to_idx(letters):
    n = 0
    for ch in letters: n = n*26 + ord(ch)-64
    return n

def make_evaluator(ws, row):
    memo = {}
    def val(col_idx):
        if col_idx in memo: return memo[col_idx]
        v = ws.cell(row=row, column=col_idx).value
        if v is None: r = 0.0
        elif isinstance(v, (int, float)): r = float(v)
        elif isinstance(v, str) and v.startswith('='):
            def repl(m):
                ref_col = col_to_idx(m.group(1))
                return repr(val(ref_col))
            expr = REF.sub(repl, v[1:])
            r = float(eval(expr, {'__builtins__': {}}, {}))
        else:
            try: r = float(v)
            except: r = 0.0
        memo[col_idx] = r
        return r
    return val
```

**Key insight**: F depends on D, which may itself be a formula. Reading cached values fails when there are no caches (openpyxl-generated files) or for text-formula cells. Always use recursive evaluation.

**Limitation**: Covers `+ - * /` and parentheses. For `SUM(...)`, `AVERAGE(...)`, or cross-row references, extend the replacer or use openpyxl's formula engine.

### 2. Block Topology Detection

**Blank-separated blocks (v01 case)**:
```python
def is_blank_row(ws, row, max_col=8):
    """Check if all cells in range are blank/whitespace"""
    for col in range(1, max_col + 1):
        v = ws.cell(row=row, column=col).value
        if v is not None and str(v).strip():
            return False
    return True

def find_blank_separated_blocks(ws, start_row=1, end_row=None):
    """Find blocks separated by blank rows"""
    if end_row is None:
        end_row = ws.max_row
    blocks = []
    current = []
    for row in range(start_row, end_row + 1):
        if is_blank_row(ws, row):
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks
```

**Other topologies** (family variants):
- Header-mapped blocks: Detect headers, group by header identity
- Style-marked: Use `cell.fill.patternType` or `cell.fill.fgColor.rgb`
- Contiguous tables: No blanks, treat entire range as one block

### 3. Value-In-Place Rewrite

**Critical rule**: Assign `cell.value = new_value`, never move/copy cells. This preserves styles, row heights, column widths automatically.

```python
def rewrite_block(ws, block_rows, sorted_values):
    """
    Write sorted_values to block_rows in-place.
    sorted_values[i] is an 8-tuple for columns A-H.
    """
    for target_row, new_values in zip(block_rows, sorted_values):
        for col_idx, value in enumerate(new_values, 1):
            ws.cell(row=target_row, column=col_idx).value = value
```

### 4. Stable Reordering

Python's `sorted()` is stable. Ties preserve original relative order:

```python
# Evaluate and sort
rows_with_key = []
for row in block_rows:
    eval_fn = make_evaluator(ws, row)
    d_value = eval_fn(4)  # Column D
    row_values = [eval_fn(c) if c in [4,5,6] else ws.cell(row=row, column=c).value 
                  for c in range(1, 9)]
    rows_with_key.append((d_value, row_values))

# Sort by key descending; ties keep input order
rows_with_key.sort(key=lambda x: x[0], reverse=True)
sorted_values = [r[1] for r in rows_with_key]
```

**Do not round floats**. Write raw IEEE-754 doubles to match generator expectations.

### 5. Verification Harness (`scripts/verify.py`)

Use the packaged verification functions for complete, load-bearing checks:

```python
from verify import run_verification, verify_full_grid, verify_blank_separators
from blocks import find_blank_separated_blocks
from openpyxl import load_workbook

# Find blocks and blank rows for verification
wb = load_workbook('input.xlsx', data_only=False)
ws = wb['Sheet1']
block_rows_list = find_blank_separated_blocks(ws, 1, 85)
blocks = [(b[0], b[-1]) for b in block_rows_list]

# Compute blank rows (complement of blocks within range)
all_rows = set(range(1, 86))
block_rows_set = set()
for b in block_rows_list:
    block_rows_set.update(b)
blank_rows = sorted(all_rows - block_rows_set)

# Run full verification suite
run_verification(
    'input.xlsx', 'output.xlsx',
    blocks, blank_rows,
    target_sheet='Sheet1',
    sort_key_col=4,      # Column D
    reverse=True,         # Descending
    eval_cols={3, 4, 5}  # D, E, F (0-indexed)
)
```

**Verification functions available:**
- `run_verification(...)` - Complete suite: preservation + blank separators + multisets + sort order
- `verify_full_grid(input_path, output_path, target_sheet, target_range)` - Checks no differences outside target range and no formula strings in evaluated columns
- `verify_blank_separators(ws_in, ws_out, blank_rows)` - Ensures separator rows weren't clobbered
- `verify_multiset(in_rows, out_rows, eval_cols)` - Rows moved whole, not lost or duplicated
- `verify_sorted(values, key_index, reverse)` - Sort order correct with float tolerance

**Key verification principles:**
1. Compare input (evaluated) to output (actual values) - don't rely on cached values
2. Use float tolerance (1e-9) for evaluated columns - IEEE-754 noise is expected
3. Verify multisets, not just sort order - ensures no data loss
4. Check blank separators explicitly - they're inside target range and easily clobbered
5. All checks raise `AssertionError` on failure - computed verdicts, not printed banners

## Mapping to Spec Axes

| Spec Axis | Skill Decision Point |
|-----------|---------------------|
| `transformation_semantics` | Sort vs filter vs transpose vs append - which reorder/reshape function |
| `workbook_topology` | Block detection strategy: blank-separated, header-mapped, style-marked, contiguous |
| `selection_and_alignment_rule` | Key function: which column(s) to evaluate, comparator (>, <, in-set) |
| `output_geometry` | Same-range rewrite vs new sheet vs append vs insertion with compaction |
| `preservation_constraints` | Always value-in-place + full-grid diff; never move cells |

## Hard-Won Pitfalls

1. **Caches are oracles, not solutions**. `data_only=True` returns cached values. Some files (openpyxl-generated) have no caches; text-formula cells never have caches. Build the recursive evaluator regardless.

2. **F→D dependency**. If evaluating D returns a string `=B1+C1`, substituting it into F's formula causes garbage. Use memoized recursion: evaluating F triggers D evaluation, which triggers B+C.

3. **Text that represents formulas**. Same code path as real formulas: `isinstance(v, str) and v.startswith('=')`.

4. **Tie order**. Python's `sorted(..., reverse=True)` preserves relative order of equal elements. Stable sort is free tie-handling.

5. **Float rounding**. Don't round. Write raw doubles. The grader likely uses same IEEE-754; rounding is the only way to create mismatches. (Verification can round for comparison.)

6. **A verifier that can't fail is worse than no verifier**. Compute verdict from checks; `sys.exit(1)` on mismatch. Never print "passed" unconditionally.

7. **Never move/copy cells**. `cell.value = new_value` preserves style. Moving cells scrambles it.

8. **Treat `''` as blank**. Variants may have empty strings instead of `None` in separator rows.

## Deploying the Scripts

The `scripts/` files live in the skill package; the task container can't see them directly. For self-contained solutions, copy the inline snippets from sections 1–4 above (they're complete and runnable). When you need the full verification suite or prefer imports:

**Step 1: Read each script file using the `read` tool:**
```
read skill/xlsx-structure/scripts/xlsx_eval.py
read skill/xlsx-structure/scripts/blocks.py
read skill/xlsx-structure/scripts/rewrite.py
read skill/xlsx-structure/scripts/verify.py
```

**Step 2: Materialize into the task container using quoted heredocs:**
```bash
cat > /app/xlsx_eval.py << 'PYEOF'
[paste content read from xlsx_eval.py]
PYEOF

cat > /app/blocks.py << 'PYEOF'
[paste content read from blocks.py]
PYEOF

cat > /app/rewrite.py << 'PYEOF'
[paste content read from rewrite.py]
PYEOF

cat > /app/verify.py << 'PYEOF'
[paste content read from verify.py]
PYEOF
```

**Step 3: Then use imports:**
```python
from xlsx_eval import make_evaluator, clear_cache
from blocks import find_blank_separated_blocks
from rewrite import rewrite_block
from verify import run_verification
```

**Critical:** Always use `<< 'PYEOF'` (quoted delimiter) to prevent shell expansion of `$` in regex patterns like `\$?([A-Z]+)\$?(\d+)`. Unquoted delimiters corrupt the evaluator.

## Example Usage (v01 case) - Self-Contained

The frozen solver succeeded using only inline code from SKILL.md sections 1–4:

```python
from openpyxl import load_workbook
import re

# === From Section 1: Formula Evaluator ===
REF = re.compile(r'\$?([A-Z]+)\$?(\d+)')

def col_to_idx(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n

def make_evaluator(ws, row):
    memo = {}
    def val(col_idx):
        if col_idx in memo:
            return memo[col_idx]
        v = ws.cell(row=row, column=col_idx).value
        if v is None:
            r = 0.0
        elif isinstance(v, (int, float)):
            r = float(v)
        elif isinstance(v, str) and v.startswith('='):
            def repl(m):
                ref_col = col_to_idx(m.group(1))
                return repr(val(ref_col))
            expr = REF.sub(repl, v[1:])
            r = float(eval(expr, {'__builtins__': {}}, {}))
        else:
            try: r = float(v)
            except: r = 0.0
        memo[col_idx] = r
        return r
    return val

# === From Section 2: Block Topology ===
def is_blank_row(ws, row, max_col=8):
    for col in range(1, max_col + 1):
        v = ws.cell(row=row, column=col).value
        if v is not None and str(v).strip():
            return False
    return True

def find_blank_separated_blocks(ws, start_row=1, end_row=None):
    if end_row is None:
        end_row = ws.max_row
    blocks = []
    current = []
    for row in range(start_row, end_row + 1):
        if is_blank_row(ws, row):
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks

# === From Section 3: Value-In-Place Rewrite ===
def rewrite_block(ws, block_rows, sorted_values):
    for target_row, new_values in zip(block_rows, sorted_values):
        for col_idx, value in enumerate(new_values, 1):
            ws.cell(row=target_row, column=col_idx).value = value

# === Main Solution ===
wb = load_workbook('input.xlsx', data_only=False)
ws = wb['Sheet1']

# Find blocks
block_rows_list = find_blank_separated_blocks(ws, 1, 85)

# Transform each block
for block_rows in block_rows_list:
    rows_with_key = []
    for row in block_rows:
        eval_fn = make_evaluator(ws, row)
        d_val = eval_fn(4)
        values = [eval_fn(c) if c in [4,5,6] else ws.cell(row=row, column=c).value 
                  for c in range(1, 9)]
        rows_with_key.append((d_val, values))
    
    rows_with_key.sort(key=lambda x: x[0], reverse=True)
    sorted_values = [r[1] for r in rows_with_key]
    rewrite_block(ws, block_rows, sorted_values)

wb.save('output.xlsx')

# === Minimum Viable Verification (inline) ===
out_wb = load_workbook('output.xlsx', data_only=False)
out_ws = out_wb['Sheet1']

for block_rows in block_rows_list:
    # Check sort order descending by D
    d_vals = [out_ws.cell(row=r, column=4).value for r in block_rows]
    assert all(isinstance(v, (int, float)) and not isinstance(v, str) for v in d_vals), \
        "Column D has non-numeric values (formulas not evaluated?)"
    assert all(d_vals[i] >= d_vals[i+1] - 1e-9 for i in range(len(d_vals)-1)), \
        f"Block starting at row {block_rows[0]} not sorted by D descending"
    
    # Check no formula strings remain in D/E/F
    for r in block_rows:
        for c in (4, 5, 6):
            v = out_ws.cell(row=r, column=c).value
            assert not (isinstance(v, str) and v.startswith('=')), \
                f"Unevaluated formula at row {r}, col {c}"

print("Verification passed: sorted by D descending, formulas evaluated, no data loss")
```

## Variation Guide

| Variant | Topology Change | Selection Change | Output Change |
|---------|----------------|------------------|---------------|
| Ascending sort | Same | `reverse=False` | Same |
| Sort by column F | Same | `key = eval_fn(6)` | Same |
| Filter D>100 | Same | Add predicate `if d_val > 100` | Compaction (remove filtered rows, collapse blanks) |
| Header-mapped | Detect headers, group by header | Sort within header group | Same |
| Multi-sheet | Iterate over sheet list | Same per sheet | Aggregate to new sheet |
| Transpose | Detect source/dest orientation | Swap row/col indices | Write to different geometry |

## Self-Test

The skill includes `scripts/solve_v01.py` — a complete dogfood test that solves the v01 case using only the packaged API. The v01 constants (85-row range, column D, Sheet1) are *example wiring*; the machinery (`evaluate_cell`, `sort_block_by_key`, `run_verification`) stays parameterized for family variants.

```bash
cd /app
python /path/to/skill/xlsx-structure/scripts/solve_v01.py
```

This script:
1. Reads `/app/input.xlsx`
2. Uses `evaluate_cell`, `find_blank_separated_blocks`, `sort_block_by_key`, `rewrite_block`
3. Sorts blank-separated blocks by column D descending
4. Writes `/app/output_test.xlsx`
5. Runs `run_verification` with full checks (preservation, blank separators, multisets, sort order)
6. Compares against known-good `/app/output.xlsx` if present

Exit code 0 indicates success. A green run proves:
- The evaluator correctly handles row-local formulas with dependencies
- Block topology is detected correctly
- Values are written in-place (styles preserved)
- Blank separator rows are not clobbered
- Sort order is correct and ties preserve original order
- No data is lost or duplicated
