---
name: financial-analysis
description: General starting point for solving tasks in the financial-analysis family.
---

# financial-analysis

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Data Discovery

- **Inspect file contents, not just names:** In directories with mixed file types and decoys, read the contents, headers, or metadata of all files to identify the target entity and schema. Do not assume `.csv` files contain the target data; it may be embedded in `.dat` or `.txt` files.
- **Extract embedded tabular data programmatically:** When financial data is embedded in text files with decorative headers or footers, use Python to read line-by-line, identify the header row, and parse comma-separated data while ignoring non-tabular lines and borders.

## Financial Calculations & Verification

- **Conditional metrics:** If a task requires conditional computation based on a threshold (e.g., 'if most recent year's metric > X%'), first calculate the trigger metric for the latest fiscal year. Branch the logic to compute either the primary or fallback metric for all years.
- **Percentage scaling and rounding:** Always multiply ratios by 100 for percentage scale (e.g., 72.72 instead of 0.7272) and round to the specified decimal places (e.g., `round(value * 100, 2)`) before writing to output. Strictly use required output column names.
- **Output Verification:** After writing the result file, read it back (e.g., via shell command) to verify column headers, expected periods, and numeric formatting against the task's schema before finishing.