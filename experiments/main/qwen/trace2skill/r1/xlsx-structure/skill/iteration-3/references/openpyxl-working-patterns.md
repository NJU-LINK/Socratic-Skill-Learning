# openpyxl Working Patterns

## Table of Contents
- [Manual Formula Evaluation](#manual-formula-evaluation)
- [Explicit Style Migration on Row Reordering](#explicit-style-migration-on-row-reordering)
- [Stable Block Sorting Strategy](#stable-block-sorting-strategy)

## Manual Formula Evaluation
When openpyxl reads formulas as strings or unevaluated expressions and the task requires their numeric results for sorting or output, evaluate them in dependency order. Build a mapping of column letters to evaluated numeric values, compute results using Python (e.g., regex-based parsing to resolve cell references and `eval()` for simple arithmetic), and write numeric values (not formula strings) back to the cells. This avoids dependency on Excel's calculation engine or stale cached values, and ensures accurate numeric floats for sorting keys.

## Explicit Style Migration on Row Reordering
In openpyxl, cell styles are bound to coordinates, not data. When sorting or moving rows, explicitly snapshot all style properties for each cell in the source row and reapply them to the corresponding cells in the destination row to preserve formatting.

Capture `font`, `fill`, `alignment`, `border`, and `number_format` using `copy()` from the `copy` module for each cell before reordering. Extract both values and styles into an in-memory buffer, sort the buffer, and after writing the sorted data to the new row positions, reassign these captured style objects to the destination cells so styles don't remain in their original row positions.

## Stable Block Sorting Strategy
To sort variable-length data blocks separated by blank rows, first detect block boundaries by scanning for completely empty rows (where all cells are `None`) rather than assuming fixed row counts. Group consecutive non-blank rows into blocks and process each block independently, preserving the blank rows between them.

For each block, evaluate sorting keys to numeric floats first. Then apply Python's built-in stable sort (`list.sort(key=..., reverse=...)`) which guarantees stability, ensuring that rows with identical sort keys retain their original relative order as required by the task.