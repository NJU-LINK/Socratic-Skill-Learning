---
name: xlsx-structure
description: General starting point for solving tasks in the xlsx-structure family.
---

# xlsx-structure

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Strategies
- **Dynamic Block Boundaries**: Detect block boundaries dynamically from blank rows. Scan the target range row-by-row, treating a row as a block separator only when all cells in the relevant columns are empty. Do not assume fixed block sizes.
- **Topological Formula Evaluation**: Evaluate dependent formulas in topological order. Evaluate dependencies first, store numeric results, then evaluate dependents. Apply `round(result, 10)` to eliminate floating-point artifacts.
- **Position-Anchored Styles**: When reordering or sorting rows, preserve cell styles at fixed grid positions. Save original styles keyed by `(row, column)` position before reordering, then reapply those position-anchored styles after writing new values.

## References
- [Openpyxl Working Patterns](references/openpyxl-patterns.md): Proven patterns for preserving styles, evaluating simple formulas, and stable sorting when manipulating Excel files with openpyxl.
- [Block Sorting and Style Preservation](references/block-sorting-and-styles.md): Read when tasks involve sorting blocks of data, evaluating formulas before sorting, or rearranging rows while preserving cell styles.

