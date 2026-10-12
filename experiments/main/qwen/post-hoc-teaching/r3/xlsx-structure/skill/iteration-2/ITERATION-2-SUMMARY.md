# Iteration 2 Summary: Style Preservation Audit & Pattern Expansion

## Overview
Iteration 2 focused on expanding the skill to cover more transformation types and selection rules from the spec, while ensuring consistent style preservation across all data-moving functions.

## Key Changes

### 1. Style Preservation Fixes (Teacher Feedback)
Fixed three functions that violated the "style follows data" principle:

#### filter_compact()
- **Before**: Only copied values, losing styles when filtering rows
- **After**: Added `preserve_styles=True` parameter (default True)
- **Implementation**: Uses `capture_row()`/`write_row()` when preserving styles

#### transpose_range()
- **Before**: Only copied values AND had aliasing bug when source/destination overlap
- **After**: Captures ALL cells into memory BEFORE writing (fixes both issues)
- **Implementation**: Two-phase approach: capture entire range, then write transposed
- **Key insight**: Same "capture first, write second" principle as sorting

#### reconcile_by_id()
- **Before**: Only copied values during ID-based reconciliation
- **After**: Added `preserve_source_style=False` parameter
- **Implementation**: Uses `copy_cell_style()` when style preservation enabled
- **Note**: Also updated `build_id_map()` to support `capture_styles=True`

### 2. New Transformation Patterns

#### Membership-Based Filtering
- **Function**: `filter_by_membership()`
- **Purpose**: Select rows where a column's value exists in a reference set
- **Spec coverage**: Implements "membership in another range" selection rule
- **Features**: 
  - Uses set for O(1) lookup
  - Optional style preservation
  - Returns matched row indices for further processing

#### Source-List Ordered Rearrangement
- **Function**: `reorder_by_source_list()`
- **Purpose**: Reorder rows to match the order specified in a source list
- **Spec coverage**: Implements "source-list order" selection rule
- **Features**:
  - Captures all rows first to avoid aliasing
  - Handles missing IDs gracefully
  - Clears unused rows in data range

### 3. New Pitfalls (18-19)

#### Pitfall #18: Range Aliasing in Transpose
- **Issue**: In-place cell-by-cell transposition reads stale values when ranges overlap
- **Solution**: Always capture entire source range before writing any destination cells
- **Principle**: Same "capture first, write second" as sorting

#### Pitfall #19: Audit All Data-Moving Functions
- **Meta-lesson**: When you fix a style-preservation bug in one function, audit ALL others
- **Method**: Grep for `.value` assignments without corresponding style copies
- **Universal rule**: Any function that MOVES data MUST capture styles alongside values

### 4. Enhanced Decision Framework
Updated the Transformation Type → Pattern Mapping table to include:
- Membership-based filtering → `filter_by_membership()`
- Source-list ordered rearrangement → `reorder_by_source_list()`
- Added "preserve styles" notes to existing patterns

## Coverage Matrix

| spec.yaml Axis | Iteration 1 | Iteration 2 |
|----------------|-------------|-------------|
| **transformation_semantics** | Block sorting, filtering, append, transpose | + Sparse reconciliation, row extraction, membership filtering, source-list reordering |
| **workbook_topology** | Single sheet, blocks | + Multi-sheet, sparse, style-marked regions |
| **selection_and_alignment_rule** | Numeric order, text predicates | + ID identity, fill color, membership, source-list order, positional |
| **output_geometry** | Same range, append | + Cross-sheet, sparse destination |
| **preservation_constraints** | Styles, dimensions, filters | + Cross-sheet preservation, theme colors, style preservation in all patterns |

## Pattern Count Summary

| Category | Iteration 1 | Iteration 2 | Total |
|----------|-------------|-------------|-------|
| **Transformation Types** | 6 | +2 | 8 |
| **Selection Rules** | 7 | +2 | 9 |
| **Key Functions** | 16 | +2 | 18 |
| **Pitfalls** | 17 | +2 | 19 |
| **Verification Items** | 14 | 0 | 14 |

## Style Preservation Audit Results

All data-moving functions now properly handle styles:

| Function | Style Preservation | Implementation |
|----------|-------------------|----------------|
| `sort_blocks()` | ✓ | `capture_row()`/`write_row()` |
| `filter_compact()` | ✓ | `preserve_styles=True` parameter |
| `transpose_range()` | ✓ | Capture all cells first, then write |
| `reconcile_by_id()` | ✓ | `preserve_source_style` parameter |
| `extract_rows()` | ✓ | `preserve_styles=True` parameter |
| `filter_by_membership()` | ✓ | `preserve_styles=True` parameter |
| `reorder_by_source_list()` | ✓ | `preserve_styles=True` parameter |

## Generalization Achievement

The skill now provides:
1. **Complete pattern library** for all spec-declared transformation types
2. **Consistent style preservation** across all data-moving functions
3. **Systematic classification** via enhanced decision framework
4. **Comprehensive pitfalls** including meta-lessons about auditing
5. **Verification checklist** ensuring correctness across variants

## Meta-Lesson Learned

When you fix a bug in one function, **audit ALL other functions for the same pattern**. The "style follows data" principle was fixed in `sort_blocks()` during iteration 1, but the same violation existed in three other functions added during iteration 2. A systematic grep for `.value` assignments without style copies would have caught all of them immediately.

This is a general software engineering principle: **consistency audits** are essential when expanding a codebase. Don't just fix the reported bug—search for the same bug pattern everywhere.
