---
name: xlsx-structure
description: >
  Structural transformations on Excel workbooks: block-local sorting by evaluated
  formula values, predicate/style-based filtering and compaction, header-aligned
  append, sparse-record reconciliation, row extraction, and layout transposition.
  Handles formula evaluation, style preservation, dynamic block detection, and
  multi-sheet workbook integrity.
---

# xlsx-structure Skill

## When to Apply

This skill applies to tasks requiring structural transformations on `.xlsx` workbooks
where the operation involves:
- Sorting rows within variable-length blocks separated by blank rows
- Evaluating formulas (arithmetic expressions with cell references) to numeric values
- Preserving workbook state (styles, dimensions, filters, merged ranges, panes, other sheets)
- Detecting block boundaries dynamically from the data rather than assuming fixed sizes

## Architecture

The transformation pipeline has five stages:

1. **Load & Read** — Open workbook with `openpyxl.load_workbook()`, read all cell values
   and style attributes from the target range on the target sheet.

2. **Block Detection** — Scan rows in the target range; a row is "blank" when all cells
   in the column span are `None`. Blocks are maximal runs of consecutive non-blank rows.
   Blank rows between blocks are preserved as separators.

3. **Formula Evaluation** — For cells in formula columns (D–F by default), parse and
   evaluate arithmetic expressions using a recursive-descent parser that handles:
   - Operator precedence: `+`, `-`, `*`, `/`
   - Parentheses
   - Cell references (any column letter(s) + row number, e.g., `B1`, `AA42`)
   - Number literals (integer and decimal)
   - Unary `+` and `-`
   
   Evaluation proceeds in **alphabetical column order** (D → E → F) so that forward
   references within a row resolve correctly. Evaluated numeric results replace the
   formula strings in the output.

4. **Block-Local Sorting** — Within each block, sort rows by the evaluated value of
   the designated sort column (column D by default) in descending order. Python's
   `sorted()` is stable, so ties preserve original relative order.

5. **Style-Aware Write-Back** — Write sorted rows back to their target positions,
   carrying all style attributes (font, fill, border, alignment, number_format,
   protection) via `copy.copy()`. Blank separator rows are never written to — they
   remain at their original positions with their original styles and values intact.

## Preservation Constraints

- Only data cells within blocks are modified; blank separator rows are never touched
- All other sheets remain untouched
- Column widths, row heights, freeze panes, auto-filters, and merged ranges outside
  the target range are preserved by loading the full workbook and only writing to
  data cells within blocks
- Styles within the target range travel with their data rows during sorting

## Script Interface

```
python scripts/transform.py <input.xlsx> <output.xlsx> [options]

Options:
  --range A1:H85       Target range (default: auto-detect from data)
  --sheet Sheet1        Target sheet name (default: first sheet)
  --sort-col D          Column to sort by (default: D)
  --sort-order desc     Sort order: desc or asc (default: desc)
  --formula-cols D,E,F  Columns that may contain formulas (default: D,E,F)
```

## Dependencies

- Python 3.8+
- openpyxl (no other dependencies)
