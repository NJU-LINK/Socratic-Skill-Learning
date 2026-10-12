---
name: financial-analysis
description: General starting point for solving tasks in the financial-analysis family.
---

# financial-analysis

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Workflow Guidelines

### Data Discovery
- When a directory contains multiple, ambiguously named, or decoy files, read the contents of all candidate files to identify the correct source. Use internal metadata (e.g., 'Company:', 'Ticker:') and match against the requested entity name rather than relying on filenames alone.

### Calculation, Scaling & Conditional Logic
- Use Python for financial metric calculations to ensure exact floating-point arithmetic.
- **Percentage Formatting**: When metrics must be expressed as percentages, explicitly multiply the ratio by 100 and apply rounding (e.g., `round(value, 2)`) to the required decimal places before evaluating conditions or serialization.
- **Conditional Metric Selection**: If output depends on a threshold condition for the most recent period, calculate and evaluate the condition precisely on the latest year first to ensure the correct branch is taken.

### Output Generation
- Strictly adhere to the output contract (e.g., CSV schema). Use Python's `csv` module to serialize the final output with exact column names, correct value formats, specified rounding rules, and no extra columns.