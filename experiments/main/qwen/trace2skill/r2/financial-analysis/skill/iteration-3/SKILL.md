---
name: financial-analysis
description: General starting point for solving tasks in the financial-analysis family.
---

# financial-analysis

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.



## Data Discovery
- Do not rely on file extensions or names to find the correct financial file.
- List the directory and read the contents of each candidate file to identify the correct source.
- Match file content against the target entity name and required schema/fields to filter out decoys (e.g., data for other companies, backups, or cache logs).

## Data Extraction and Calculation
- For non-standard or ASCII-formatted data files, extract tabular rows directly into a Python list of tuples to avoid fragile regex parsing.
- Use a Python script to parse extracted data, evaluate conditional logic, compute metrics, and write formatted CSV output.
- For conditional financial tasks, compute the condition metric for the most recent year first to determine the logic branch.
- Apply the correct formula across all years. Scale percentage results correctly (multiply by 100, e.g., `72.72` not `0.7272`) and round to the exact specified decimal places.
- Write to the output CSV using the `csv` module and the exact requested column headers.
