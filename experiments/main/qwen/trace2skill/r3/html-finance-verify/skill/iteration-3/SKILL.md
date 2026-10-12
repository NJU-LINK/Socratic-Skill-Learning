---
name: html-finance-verify
description: General starting point for solving tasks in the html-finance-verify family.
---

# html-finance-verify

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.



## Verification Workflow
1. **Parse HTML & Extract Identifiers**: Extract all semantic line numbers (e.g., parse `<td class="line">210</td>`, do not use physical HTML source line numbers), metric names, and values into Python for programmatic cross-checking.
2. **Verify Dollar Amounts (Sequential Consistency)**: Validate absolute dollar amounts for internal arithmetic consistency (e.g., Revenue - Cost = Gross Profit) before checking derived percentage KPIs. Treat confirmed base values as ground truth.
3. **Recalculate KPIs**: Once dollar amounts are confirmed consistent, independently calculate derived percentage KPIs (e.g., Gross Margin = Gross Profit / Revenue * 100).
4. **Identify Mismatch**: Round calculated percentages to the precision stated in the report and compare to reported values to isolate the incorrect metric.

## Output Formatting
- **Exact Extraction**: Extract the exact semantic line number and the **incorrect reported value** (not the corrected value).
- **Clean Values**: Strip specifically forbidden characters (like '%' or '$') while preserving exact digits (e.g., output `210,60.8`, not `210,60.8%`).
- **Precise Output**: Format the output string precisely as specified (e.g., `line_number,value`).
- **No Trailing Newlines**: Use `echo -n "line_number,value" > /app/value.txt` or equivalent Python file writing to prevent trailing newlines or formatting artifacts.
