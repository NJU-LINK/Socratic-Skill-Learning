# Openpyxl Working Patterns

Proven patterns for manipulating Excel files with openpyxl.

## Preserve Workbook Styles via In-place Updates
To preserve formatting (styles, widths, merged cells) while transforming data, update only the `.value` attribute of existing cells. Do not clear ranges or create new cell objects.
```python
for r in range(min_row, max_row + 1):
    for c in range(min_col, max_col + 1):
        ws.cell(row=r, column=c).value = new_value
```

## Evaluate Simple Formulas via Regex
When openpyxl cannot evaluate formulas natively, parse simple arithmetic formulas (e.g., `=B1+C1`) using regex, substitute cell references with numeric values, and use `eval()`. Ensure dependencies are resolved in order (e.g., process columns sequentially) by storing results in a lookup dictionary.
```python
import re
expr = "=B1+C1"
refs = re.findall(r'([A-Z]+)(\d+)', expr)
# map refs to column indices, retrieve values, replace in string, then eval()
```

## Stable Descending Sort for Data Blocks
To sort blocks of rows by a numeric column descending while preserving original order for ties (stable sort), use a tuple key that negates the sort value and includes the original row index.
```python
# x[1] is numeric value, x[2] is original positional index
block_data.sort(key=lambda x: (-x[1], x[2]))
```