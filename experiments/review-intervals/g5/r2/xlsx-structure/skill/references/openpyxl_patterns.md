# openpyxl Patterns for xlsx-structure Tasks

## 1. Dual-Load Pattern

The fundamental pattern for working with formula-containing workbooks:

```python
import openpyxl
from copy import copy

# Load twice with different modes
wb_formulas = openpyxl.load_workbook('input.xlsx', data_only=False)  # For writing/styles
wb_values   = openpyxl.load_workbook('input.xlsx', data_only=True)   # For cached values

ws_f = wb_formulas['Sheet1']
ws_v = wb_values['Sheet1']

# After transformation, save the formula workbook (which has all styles/metadata)
wb_formulas.save('output.xlsx')
```

**Key insight:** `data_only=False` gives you formula strings but preserves all styles
and metadata. `data_only=True` gives you computed values but may lose some style
information. Use the formula workbook for writing, the values workbook for reading
computed results.

## 2. Formula Evaluation with Manual Fallback

```python
import re

def evaluate_formula_manual(ws, row, formula_str):
    """
    Evaluate a simple arithmetic formula like '=B1+C1' or '=D1+E1'.
    Only handles cell references within the same row and basic arithmetic.
    """
    # Remove leading '='
    expr = formula_str[1:]
    
    # Find all cell references (e.g., B1, C1, AA5)
    cell_refs = re.findall(r'([A-Z]+)(\d+)', expr)
    
    # Build a mapping of cell references to their values
    ref_values = {}
    for col_letter, row_num in cell_refs:
        ref_row = int(row_num)
        # Convert column letter to number
        col_num = 0
        for ch in col_letter:
            col_num = col_num * 26 + (ord(ch) - ord('A') + 1)
        
        cell_val = ws.cell(row=ref_row, column=col_num).value
        if isinstance(cell_val, (int, float)):
            ref_values[f'{col_letter}{row_num}'] = cell_val
        elif isinstance(cell_val, str):
            try:
                ref_values[f'{col_letter}{row_num}'] = float(cell_val)
            except ValueError:
                # If the referenced cell is itself a formula, evaluate it first
                if cell_val.startswith('='):
                    ref_values[f'{col_letter}{row_num}'] = evaluate_formula_manual(
                        ws, ref_row, cell_val
                    )
                else:
                    ref_values[f'{col_letter}{row_num}'] = 0.0
    
    # Replace cell references with their values in the expression
    for ref, val in ref_values.items():
        expr = expr.replace(ref, str(val))
    
    # Evaluate the arithmetic expression
    try:
        return eval(expr)  # Safe for simple arithmetic only
    except:
        return None


def get_evaluated_value(ws_values, ws_formulas, row, col):
    """
    Get the numeric value of a cell.
    Tries cached value first, then falls back to manual evaluation.
    """
    # Try cached value (from data_only=True load)
    val_v = ws_values.cell(row=row, column=col).value
    if val_v is not None and isinstance(val_v, (int, float)):
        return val_v
    
    # Try formula workbook value
    val_f = ws_formulas.cell(row=row, column=col).value
    if isinstance(val_f, (int, float)):
        return float(val_f)
    
    if isinstance(val_f, str):
        # Try parsing as number
        try:
            return float(val_f)
        except ValueError:
            pass
        
        # If it's a formula string, evaluate manually
        if val_f.startswith('='):
            return evaluate_formula_manual(ws_formulas, row, val_f)
    
    # Last resort: try cached value as numeric string
    if isinstance(val_v, str):
        try:
            return float(val_v)
        except ValueError:
            pass
    
    return None
```

## 3. Block Detection (Blank-Row Separated)

```python
def detect_blank_row_separated_blocks(ws, start_row, end_row, col_start, col_end):
    """
    Detect blocks of non-blank rows separated by blank rows.
    Returns list of (start_row, end_row) tuples.
    """
    blocks = []
    current_start = None
    
    for row_idx in range(start_row, end_row + 1):
        has_data = False
        for col_idx in range(col_start, col_end + 1):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val is not None and str(val).strip() != '':
                has_data = True
                break
        
        if has_data:
            if current_start is None:
                current_start = row_idx
        else:
            if current_start is not None:
                blocks.append((current_start, row_idx - 1))
                current_start = None
    
    # Handle last block extending to end_row
    if current_start is not None:
        blocks.append((current_start, end_row))
    
    return blocks
```

## 4. Row Collection with Style Preservation

```python
def collect_row_with_styles(ws, row_idx, col_start, col_end):
    """
    Collect all cell values and styles for a row.
    Returns a dict with 'values' and 'styles' lists.
    """
    row_data = {
        'values': [],
        'styles': [],
    }
    for col_idx in range(col_start, col_end + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        row_data['values'].append(cell.value)
        row_data['styles'].append({
            'font': copy(cell.font),
            'fill': copy(cell.fill),
            'border': copy(cell.border),
            'alignment': copy(cell.alignment),
            'number_format': cell.number_format,
        })
    return row_data


def write_row_with_styles(ws, row_idx, row_data, col_start, col_end):
    """
    Write cell values and styles to a row.
    """
    for i, col_idx in enumerate(range(col_start, col_end + 1)):
        cell = ws.cell(row=row_idx, column=col_idx)
        cell.value = row_data['values'][i]
        style = row_data['styles'][i]
        cell.font = style['font']
        cell.fill = style['fill']
        cell.border = style['border']
        cell.alignment = style['alignment']
        cell.number_format = style['number_format']
```

## 5. Sorting Within Blocks

```python
def sort_blocks_by_column(ws, ws_values, blocks, sort_col, col_start, col_end,
                          descending=True, use_evaluated=True):
    """
    Sort rows within each block by the value in sort_col.
    Uses stable sort to preserve original order for ties.
    """
    for start, end in blocks:
        # Collect all rows in this block
        rows = []
        for row_idx in range(start, end + 1):
            row_data = collect_row_with_styles(ws, row_idx, col_start, col_end)
            
            # Get sort key
            if use_evaluated:
                sort_val = get_evaluated_value(ws_values, ws, row_idx, sort_col)
            else:
                sort_val = ws.cell(row=row_idx, column=sort_col).value
            
            row_data['sort_key'] = float(sort_val) if sort_val is not None else float('-inf')
            rows.append(row_data)
        
        # Sort (stable sort preserves original order for ties)
        rows.sort(key=lambda r: r['sort_key'], reverse=descending)
        
        # Write back
        for offset, row_data in enumerate(rows):
            write_row_with_styles(ws, start + offset, row_data, col_start, col_end)
```

## 6. Preservation Verification

```python
def verify_preservation(ws_in, ws_out, target_range, col_start, col_end,
                        row_start, row_end):
    """
    Verify that everything outside the target range is preserved.
    """
    mismatches = []
    
    # Check columns outside the range (for rows within range)
    for r in range(row_start, row_end + 1):
        for c in range(1, ws_in.max_column + 1):
            if c < col_start or c > col_end:
                v_in = ws_in.cell(row=r, column=c).value
                v_out = ws_out.cell(row=r, column=c).value
                if v_in != v_out:
                    mismatches.append((r, c, v_in, v_out))
    
    # Check rows outside the range
    for r in range(1, ws_in.max_row + 1):
        if r < row_start or r > row_end:
            for c in range(1, ws_in.max_column + 1):
                v_in = ws_in.cell(row=r, column=c).value
                v_out = ws_out.cell(row=r, column=c).value
                if v_in != v_out:
                    mismatches.append((r, c, v_in, v_out))
    
    return mismatches


def verify_workbook_metadata(wb_in, wb_out):
    """
    Verify that workbook-level metadata is preserved.
    """
    issues = []
    
    # Check sheet names
    if wb_in.sheetnames != wb_out.sheetnames:
        issues.append(f"Sheet names differ: {wb_in.sheetnames} vs {wb_out.sheetnames}")
    
    for sname in wb_in.sheetnames:
        ws_in = wb_in[sname]
        ws_out = wb_out[sname]
        
        # Check column widths
        for col_letter in set(list(ws_in.column_dimensions.keys()) + 
                              list(ws_out.column_dimensions.keys())):
            cd_in = ws_in.column_dimensions.get(col_letter)
            cd_out = ws_out.column_dimensions.get(col_letter)
            w_in = cd_in.width if cd_in else None
            w_out = cd_out.width if cd_out else None
            if w_in != w_out:
                issues.append(f"Col {col_letter} width: {w_in} vs {w_out}")
        
        # Check merged cells
        if ws_in.merged_cells.ranges != ws_out.merged_cells.ranges:
            issues.append(f"Merged cells differ")
        
        # Check freeze panes
        if ws_in.freeze_panes != ws_out.freeze_panes:
            issues.append(f"Freeze panes differ: {ws_in.freeze_panes} vs {ws_out.freeze_panes}")
    
    return issues
```

## 7. Complete Workflow Template

```python
import openpyxl
from copy import copy

def solve_xlsx_structure(input_path, output_path, task_spec):
    """
    Generic workflow for xlsx-structure tasks.
    task_spec is a dict describing the transformation.
    """
    # 1. Load workbooks
    wb_formulas = openpyxl.load_workbook(input_path, data_only=False)
    wb_values = openpyxl.load_workbook(input_path, data_only=True)
    
    ws_f = wb_formulas[task_spec['sheet_name']]
    ws_v = wb_values[task_spec['sheet_name']]
    
    # 2. Detect topology
    blocks = detect_blank_row_separated_blocks(
        ws_f,
        task_spec['row_start'], task_spec['row_end'],
        task_spec['col_start'], task_spec['col_end']
    )
    
    # 3. Collect row data with evaluated values
    block_data = []
    for start, end in blocks:
        rows = []
        for row_idx in range(start, end + 1):
            row_data = collect_row_with_styles(ws_f, row_idx,
                                                task_spec['col_start'],
                                                task_spec['col_end'])
            # Add evaluated values for formula columns
            for col in task_spec.get('formula_columns', []):
                row_data[f'eval_{col}'] = get_evaluated_value(ws_v, ws_f, row_idx, col)
            rows.append(row_data)
        block_data.append(rows)
    
    # 4. Perform transformation (e.g., sort)
    if task_spec['transformation'] == 'sort':
        for rows in block_data:
            sort_key = task_spec['sort_key']  # e.g., 'eval_4' for column D
            rows.sort(key=lambda r: r.get(sort_key, float('-inf')),
                      reverse=task_spec.get('descending', True))
    
    # 5. Write output
    for block_idx, (start, end) in enumerate(blocks):
        sorted_rows = block_data[block_idx]
        for offset, row_data in enumerate(sorted_rows):
            row_idx = start + offset
            for i, col_idx in enumerate(range(task_spec['col_start'],
                                               task_spec['col_end'] + 1)):
                cell = ws_f.cell(row=row_idx, column=col_idx)
                
                # For formula columns, write evaluated values
                if col_idx in task_spec.get('formula_columns', []):
                    cell.value = row_data.get(f'eval_{col_idx}')
                else:
                    cell.value = row_data['values'][i]
                
                # Apply styles
                style = row_data['styles'][i]
                cell.font = style['font']
                cell.fill = style['fill']
                cell.border = style['border']
                cell.alignment = style['alignment']
                cell.number_format = style['number_format']
    
    # 6. Save
    wb_formulas.save(output_path)
    
    # 7. Verify
    wb_check = openpyxl.load_workbook(output_path, data_only=False)
    ws_check = wb_check[task_spec['sheet_name']]
    mismatches = verify_preservation(ws_f, ws_check,
                                      task_spec['target_range'],
                                      task_spec['col_start'], task_spec['col_end'],
                                      task_spec['row_start'], task_spec['row_end'])
    if mismatches:
        print(f"WARNING: {len(mismatches)} preservation mismatches found")
    
    return output_path
```
