# Iteration 2 Summary: xlsx-structure Skill Improvements

## Overview
Iteration 2 addressed critical correctness bugs and structural gaps identified through Teacher feedback and careful analysis of the spec's variation dimensions.

## Critical Fixes

### 1. Excel `^` vs Python `^` Operator Bug (Silent Correctness Issue)
**Problem**: Excel's `^` operator means exponentiation (power), but Python's `^` is bitwise XOR.
- `=A1^2` with A1=5 should give 25 (power)
- Without fix: Python evaluates `5^2 = 7` (XOR) — silent wrong result, no error

**Fix**: Added `expr.replace('^', '**')` in the formula evaluator to convert Excel power syntax to Python.

**Impact**: Prevents silent data corruption in any workbook using power operations.

### 2. `data_only=True` Strategy (Preferred Evaluation Method)
**Problem**: Custom formula evaluation is error-prone and limited. Excel-saved workbooks often cache computed values.

**Fix**: Added Strategy 1 that loads with `data_only=True` to read cached values directly, with fallback to custom evaluation only when cached values are unavailable.

**Impact**: More reliable formula evaluation, handles complex Excel functions automatically.

### 3. Three-Layer `cell_lookup` Construction (Structural Gap Fix)
**Problem**: The Strategy 1 template referenced `cell_lookup` without defining it, causing `NameError` on the fallback path.

**Fix**: Implemented complete three-layer construction:
1. **Layer 1**: Raw values from normal workbook load (including formula strings)
2. **Layer 2**: Cached values from `data_only=True` layered on top (overrides formulas with numeric results)
3. **Layer 3**: Custom evaluation with dependency ordering when no cached values exist

**Key insight**: Dependency ordering matters — when F depends on D which depends on B,C, must evaluate D before F. The `sorted(formula_cols)` loop ensures left-to-right evaluation.

**Impact**: Makes the fallback path actually runnable, not just conceptually described.

### 4. Post-Evaluation Validation (Silent Failure Prevention)
**Problem**: Unevaluated formula strings silently corrupt sort keys and output values.

**Fix**: Added validation pass after building `cell_lookup` that raises `ValueError` if any formula columns still contain formula strings.

**Impact**: Converts silent failures into loud, diagnosable errors.

### 5. `write_row` Column Offset Bug
**Problem**: Template used `i + 1` (hardcoded to column A) instead of `min_col + i`.

**Fix**: Changed to `min_col + i` to respect actual column range.

**Impact**: Correct behavior when writing to ranges that don't start at column A.

### 6. Percentage Handling
**Problem**: Excel percentages like `10%` not handled by custom evaluator.

**Fix**: Added regex to convert `10%` to `(10/100)` before evaluation.

**Impact**: Supports percentage operations in formulas.

## Additional Improvements

### Multi-Letter Column Support (from iteration 1 Teacher feedback)
- Fixed `ord(letter) - ord('A') + 1` crash on columns AA and beyond
- Uses `openpyxl.utils.column_index_from_string()` for correct bijective base-26 decoding
- Handles columns A through XFD (1-16384)

### Regex Function Name Avoidance (from iteration 1 Teacher feedback)
- Negative lookaround `(?<![A-Za-z])([A-Za-z]+)(\d+)(?!\w)` prevents matching function names like IF, SUM
- Gracefully leaves unrecognized tokens in place

### Formula Column Detection
- Added code to dynamically identify which columns contain formulas
- Enables targeted evaluation and validation

## Verification Results

### Edge Case Tests (All Passed ✓)
- Power operator: `=A1^2` → 25 (not 7)
- Multi-letter columns: `=AA1*2` → 20
- Percentage: `=A1*10%` → 0.5
- Comparison: `=A1>B1` → True
- Unary minus: `=-A1+B1` → -2

### v01 Solution (12/12 tests passed ✓)
- All 9 blocks sorted by column D descending
- No formula strings remain in output
- Blank rows preserved
- Styles preserved (bold, alignment)
- Data outside A1:H85 unchanged
- F = D + E relationship holds

### Three-Layer cell_lookup Tests
- **Cached path** (any_cached=True): Uses data_only=True values ✓
- **Fallback path** (any_cached=False): Evaluates in dependency order (D before F) ✓
- **Validation**: Raises error if formulas remain unevaluated ✓

## Spec Coverage

The skill now addresses all five spec axes:

1. **transformation_semantics**: Block sorting, filtering, appending, transposition patterns
2. **workbook_topology**: Dynamic block detection, style-marked regions, multi-sheet support
3. **selection_and_alignment_rule**: Evaluated numeric order, header alignment, predicate matching
4. **output_geometry**: Same-sheet, different sheet, appended, new range options
5. **preservation_constraints**: Complete checklist for styles, dimensions, filters, merged ranges, panes

## Common Pitfalls Documented (10 total)

1. Formula strings vs. values
2. **Excel `^` is power, Python `^` is XOR** (NEW)
3. Floating point precision
4. Stable sort
5. Blank row detection
6. Style copying
7. Column indexing
8. Multi-letter columns
9. **`data_only=True` for cached values** (NEW)
10. **Column offset in write_row** (NEW)

## Files Modified

- `skill/xlsx-structure/SKILL.md`: 395 lines (was 275), comprehensive improvements
- Removed: `CHANGES.md` (iteration 1 only, superseded by this summary)

## Conclusion

Iteration 2 transformed the skill from a working v01 solution into a robust, general-purpose xlsx transformation toolkit that:
- Handles silent correctness bugs (power operator)
- Provides reliable formula evaluation (data_only + fallback)
- Makes all code paths actually runnable (cell_lookup construction)
- Converts silent failures into loud errors (validation)
- Documents pitfalls comprehensively (10 items)

The skill is ready for deployment across the xlsx-structure family.
