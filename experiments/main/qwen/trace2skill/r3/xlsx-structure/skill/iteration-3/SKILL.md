---
name: xlsx-structure
description: General starting point for solving tasks in the xlsx-structure family.
---

# xlsx-structure

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Openpyxl Row Sorting & Manipulation

Follow these patterns when sorting or reordering rows in openpyxl:

- **Formula Evaluation**: Evaluate interdependent formulas sequentially in dependency order. Replace formula strings with computed numeric values *before* sorting to ensure numeric sorting and avoid unevaluated formulas.
- **Block Sorting**: Detect contiguous non-blank rows to group variable-length data blocks separated by blank rows. Apply a stable sort (e.g., `list.sort(reverse=True)`) on the target numeric column to preserve tie order and maintain blank row separators.
- **Style Preservation**: Explicitly capture and reapply all style properties (`font`, `fill`, `border`, `alignment`, `number_format`, `protection`) from original cells to destination cells when reordering rows, as assigning `cell.value` does not move formatting.

See [references/openpyxl-patterns.md](references/openpyxl-patterns.md) for detailed code snippets and proven patterns.