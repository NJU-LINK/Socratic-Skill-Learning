# Block Sorting and Style Preservation

## Table of Contents
- [Block-Aware Stable Sorting](#block-aware-stable-sorting)
- [Cell-Level Style Preservation](#cell-level-style-preservation)
- [Floating Point Noise Cleanup](#floating-point-noise-cleanup)

## Block-Aware Stable Sorting
For block-local sorting tasks where formulas must be evaluated:
1. Detect block boundaries by scanning for fully-blank rows within the target range. Group consecutive non-blank rows into blocks.
2. Evaluate row-local formulas to numeric values before sorting (e.g., parse simple arithmetic like `=Bn+Cn`).
3. Sort each block using a stable sort keyed on the evaluated numeric column (e.g., `block.sort(key=lambda r: -evaluated_value)`).
4. Write evaluated numeric values back to output cells as numbers, not formula strings.

## Cell-Level Style Preservation
When rearranging rows within a range while preserving workbook styles:
1. Capture `font`, `fill`, `alignment`, `number_format`, and `border` using `copy()` from openpyxl for each cell in the source range.
2. Store these styles per-row.
3. When writing sorted rows back, apply the copied styles to destination cells (e.g., `cell.font = style['font']`). This ensures row-specific styles move with the data.

## Floating Point Noise Cleanup
When evaluating simple arithmetic formulas on inputs with limited decimal precision:
- Apply `round(result, 10)` to eliminate floating point representation artifacts (e.g., `1.599999999999994` → `1.6`).
- This preserves meaningful precision while avoiding spurious digits that fail exact-comparison tests.
