---
name: html-finance-verify
description: General starting point for solving tasks in the html-finance-verify family.
---

# html-finance-verify

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Verification Workflow

1. **Programmatic Cross-Checking**: Write a Python script to extract base values and derived metrics from the HTML document. Recompute subtotals, totals, and ratios (e.g., Gross Profit = Revenue - Cost of Revenue, Margin = Profit / Revenue) to systematically isolate inconsistencies and avoid manual calculation errors.
2. **Target the Incorrect Value**: Identify the metric that fails its cross-check. Extract the *reported incorrect* value exactly as displayed in the document, NOT the mathematically corrected value.
3. **Strict Output Formatting**: Carefully parse output constraints. Strip formatting characters (e.g., `%`, `$`, `,`) if required, and use explicit structural identifiers (like HTML line numbers) to pinpoint the metric. Verify the final output matches the prompt's exact format (e.g., `line_number,value`) before finishing.
