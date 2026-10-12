---
name: html-finance-verify
description: General starting point for solving tasks in the html-finance-verify family.
---

# html-finance-verify

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Best Practices

- **Programmatic Verification**: Write a Python script to extract values and systematically recompute all arithmetic (subtotals, totals) and ratio (margins, percentages) relationships. Compare computed values against reported values to definitively identify the inconsistent metric and avoid manual calculation errors.
- **Line Identifiers vs. File Lines**: When an HTML report contains explicit line identifiers (e.g., `<td class="line">210</td>`), use the explicit identifier as the "line number" in your answer, not the text editor's physical file line number.
- **Exact Value Extraction**: Output the exact numeric representation of the *reported* (incorrect) value as it appears in the source document, not the mathematically corrected one. Strip `$` or `%` symbols if instructed, and strictly follow formatting constraints.
- **File Read-Back**: Read back the output file immediately after writing to ensure no trailing newlines or extra characters violate the parser.