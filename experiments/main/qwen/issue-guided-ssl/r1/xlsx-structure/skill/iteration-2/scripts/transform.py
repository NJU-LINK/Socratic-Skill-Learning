#!/usr/bin/env python3
"""
General-purpose xlsx structural transformation script.

Implements:
- Recursive-descent formula evaluator (handles +, -, *, /, parentheses, cell refs)
- Dynamic block detection from blank-row separators
- Style-aware row sorting within blocks
- Full workbook preservation outside the target range

Usage:
    python transform.py <input.xlsx> <output.xlsx> [options]

Options:
    --range A1:H85        Target range (default: auto-detect)
    --sheet Sheet1         Target sheet name (default: first sheet)
    --sort-col D           Column to sort by (default: D)
    --sort-order desc      Sort order: desc or asc (default: desc)
    --formula-cols D,E,F   Columns that may contain formulas (default: D,E,F)
"""

import argparse
import copy
import re
import sys
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Border, Alignment, Protection
from openpyxl.utils import get_column_letter, column_index_from_string


# ---------------------------------------------------------------------------
# Recursive-descent formula evaluator
# ---------------------------------------------------------------------------

class TokenError(Exception):
    pass


class ParseError(Exception):
    pass


def tokenize(expr: str):
    """
    Tokenize an arithmetic expression into a list of tokens.
    Token types: 'NUM', 'REF', 'OP', 'LPAREN', 'RPAREN'
    """
    tokens = []
    i = 0
    expr = expr.strip()
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch in '+-*/':
            tokens.append(('OP', ch))
            i += 1
        elif ch == '(':
            tokens.append(('LPAREN', '('))
            i += 1
        elif ch == ')':
            tokens.append(('RPAREN', ')'))
            i += 1
        elif ch.isdigit() or ch == '.':
            # Number literal
            j = i
            has_dot = (ch == '.')
            j += 1
            while j < len(expr) and (expr[j].isdigit() or (expr[j] == '.' and not has_dot)):
                if expr[j] == '.':
                    has_dot = True
                j += 1
            tokens.append(('NUM', expr[i:j]))
            i = j
        elif ch.isalpha():
            # Cell reference: letters followed by digits
            j = i
            while j < len(expr) and expr[j].isalpha():
                j += 1
            while j < len(expr) and expr[j].isdigit():
                j += 1
            tokens.append(('REF', expr[i:j]))
            i = j
        else:
            raise TokenError(f"Unexpected character '{ch}' at position {i} in '{expr}'")
    return tokens


class Parser:
    """
    Recursive-descent parser for arithmetic expressions.
    
    Grammar:
        expression → term (( '+' | '-' ) term)*
        term       → factor (( '*' | '/' ) factor)*
        factor     → NUMBER | CELL_REF | '(' expression ')' | ( '+' | '-' ) factor
    """
    
    def __init__(self, tokens, cell_values):
        self.tokens = tokens
        self.pos = 0
        self.cell_values = cell_values  # dict: (row_num, col_letter) -> numeric value
    
    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None
    
    def consume(self, expected_type=None):
        tok = self.peek()
        if tok is None:
            raise ParseError("Unexpected end of expression")
        if expected_type and tok[0] != expected_type:
            raise ParseError(f"Expected {expected_type}, got {tok[0]} ({tok[1]})")
        self.pos += 1
        return tok
    
    def parse(self):
        result = self.expression()
        if self.pos < len(self.tokens):
            raise ParseError(f"Unexpected token after expression: {self.tokens[self.pos]}")
        return result
    
    def expression(self):
        """expression → term (( '+' | '-' ) term)*"""
        left = self.term()
        while self.peek() and self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.consume()[1]
            right = self.term()
            if op == '+':
                left = left + right
            else:
                left = left - right
        return left
    
    def term(self):
        """term → factor (( '*' | '/' ) factor)*"""
        left = self.factor()
        while self.peek() and self.peek()[0] == 'OP' and self.peek()[1] in ('*', '/'):
            op = self.consume()[1]
            right = self.factor()
            if op == '*':
                left = left * right
            else:
                if right == 0:
                    raise ParseError("Division by zero")
                left = left / right
        return left
    
    def factor(self):
        """factor → NUMBER | CELL_REF | '(' expression ')' | ( '+' | '-' ) factor"""
        tok = self.peek()
        if tok is None:
            raise ParseError("Unexpected end of expression in factor")
        
        if tok[0] == 'NUM':
            self.consume()
            return float(tok[1]) if '.' in tok[1] else int(tok[1])
        
        if tok[0] == 'REF':
            self.consume()
            ref_str = tok[1]
            # Parse cell reference: letters + digits
            match = re.match(r'^([A-Za-z]+)(\d+)$', ref_str)
            if not match:
                raise ParseError(f"Invalid cell reference: {ref_str}")
            col_str = match.group(1).upper()
            row_num = int(match.group(2))
            key = (row_num, col_str)
            if key in self.cell_values:
                val = self.cell_values[key]
                if isinstance(val, (int, float)):
                    return float(val)
                return 0.0
            return 0.0
        
        if tok[0] == 'LPAREN':
            self.consume()
            result = self.expression()
            self.consume('RPAREN')
            return result
        
        if tok[0] == 'OP' and tok[1] in ('+', '-'):
            op = self.consume()[1]
            operand = self.factor()
            return -operand if op == '-' else operand
        
        raise ParseError(f"Unexpected token in factor: {tok}")


def evaluate_formula(formula_text: str, cell_values: dict):
    """
    Evaluate a formula string (e.g., '=B1+C1*D1') to a numeric value.
    
    Args:
        formula_text: The formula string (with or without leading '=')
        cell_values: Dict mapping (row_num, col_letter) -> numeric value
    
    Returns:
        The evaluated numeric result, or the original value if not a formula.
    """
    if not isinstance(formula_text, str):
        return formula_text
    
    text = formula_text.strip()
    if not text.startswith('='):
        # Not a formula; try to parse as number
        try:
            return float(text) if '.' in text else int(text)
        except (ValueError, TypeError):
            return formula_text
    
    expr = text[1:]  # Remove leading '='
    tokens = tokenize(expr)
    parser = Parser(tokens, cell_values)
    result = parser.parse()
    return result


# ---------------------------------------------------------------------------
# Block detection
# ---------------------------------------------------------------------------

def is_blank_row(cell_data, row_num, min_col, max_col):
    """Check if a row is blank (all cells None)."""
    for col in range(min_col, max_col + 1):
        if (row_num, col) in cell_data and cell_data[(row_num, col)]['value'] is not None:
            return False
    return True


def detect_blocks(cell_data, min_row, max_row, min_col, max_col):
    """
    Detect blocks of contiguous non-blank rows separated by blank rows.
    
    Returns:
        List of lists, where each inner list contains row numbers in one block.
    """
    blocks = []
    current_block = []
    
    for row_num in range(min_row, max_row + 1):
        if is_blank_row(cell_data, row_num, min_col, max_col):
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(row_num)
    
    if current_block:
        blocks.append(current_block)
    
    return blocks


# ---------------------------------------------------------------------------
# Cell data capture and write-back
# ---------------------------------------------------------------------------

def capture_cell(ws, row, col):
    """Capture value and all style attributes from a cell."""
    cell = ws.cell(row=row, column=col)
    return {
        'value': cell.value,
        'font': copy.copy(cell.font),
        'fill': copy.copy(cell.fill),
        'border': copy.copy(cell.border),
        'alignment': copy.copy(cell.alignment),
        'number_format': cell.number_format,
        'protection': copy.copy(cell.protection),
    }


def write_cell(ws, row, col, data):
    """Write value and style attributes to a cell."""
    cell = ws.cell(row=row, column=col)
    cell.value = data['value']
    cell.font = data['font']
    cell.fill = data['fill']
    cell.border = data['border']
    cell.alignment = data['alignment']
    cell.number_format = data['number_format']
    cell.protection = data['protection']


def reset_cell(ws, row, col):
    """Reset a cell to default (blank) state."""
    cell = ws.cell(row=row, column=col)
    cell.value = None
    cell.font = Font()
    cell.fill = PatternFill()
    cell.border = Border()
    cell.alignment = Alignment()
    cell.protection = Protection()
    cell.number_format = 'General'


# ---------------------------------------------------------------------------
# Main transformation
# ---------------------------------------------------------------------------

def parse_range(range_str):
    """Parse a range string like 'A1:H85' into (min_row, min_col, max_row, max_col)."""
    match = re.match(r'^([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)$', range_str)
    if not match:
        raise ValueError(f"Invalid range: {range_str}")
    min_col = column_index_from_string(match.group(1))
    min_row = int(match.group(2))
    max_col = column_index_from_string(match.group(3))
    max_row = int(match.group(4))
    return min_row, min_col, max_row, max_col


def transform(input_path, output_path, sheet_name=None, range_str=None,
              sort_col='D', sort_order='desc', formula_cols=None):
    """
    Main transformation pipeline.
    
    1. Load workbook
    2. Read all cell data from target range
    3. Detect blocks
    4. Evaluate formulas in formula columns
    5. Sort each block by sort column
    6. Write back sorted data with styles
    7. Save workbook
    """
    if formula_cols is None:
        formula_cols = ['D', 'E', 'F']
    
    # Load workbook
    wb = load_workbook(input_path)
    if sheet_name is None:
        ws = wb.active
    else:
        ws = wb[sheet_name]
    
    # Parse range
    if range_str is None:
        # Auto-detect: use ws.dimensions or scan for data
        min_row, min_col, max_row, max_col = 1, 1, ws.max_row, ws.max_column
    else:
        min_row, min_col, max_row, max_col = parse_range(range_str)
    
    sort_col_idx = column_index_from_string(sort_col)
    formula_col_indices = [column_index_from_string(c) for c in formula_cols]
    
    # Step 1: Capture all cell data
    cell_data = {}
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            cell_data[(row, col)] = capture_cell(ws, row, col)
    
    # Step 2: Detect blocks
    blocks = detect_blocks(cell_data, min_row, max_row, min_col, max_col)
    
    # Step 3: Build cell_values map from raw numeric values
    cell_values = {}
    for (row, col), data in cell_data.items():
        col_letter = get_column_letter(col)
        val = data['value']
        if isinstance(val, (int, float)):
            cell_values[(row, col_letter)] = val
    
    # Step 4: Evaluate formulas in formula columns (alphabetical order)
    for col_idx in sorted(formula_col_indices):
        col_letter = get_column_letter(col_idx)
        for row in range(min_row, max_row + 1):
            key = (row, col_idx)
            if key not in cell_data:
                continue
            val = cell_data[key]['value']
            if isinstance(val, str) and val.strip().startswith('='):
                evaluated = evaluate_formula(val, cell_values)
                cell_data[key]['value'] = evaluated
                # Update cell_values so later columns can reference this
                cell_values[(row, col_letter)] = evaluated
    
    # Step 5: Sort each block by sort column
    for block in blocks:
        def sort_key(row_num):
            val = cell_data[(row_num, sort_col_idx)]['value']
            if isinstance(val, (int, float)):
                return -val if sort_order == 'desc' else val
            return float('inf') if sort_order == 'desc' else float('-inf')
        
        block_sorted = sorted(block, key=sort_key)
        block[:] = block_sorted
    
    # Step 6: Write back sorted data
    # Blank separator rows are NOT touched — they stay at their original positions
    # with their original styles intact. Only data rows within blocks are rewritten.
    output_row = min_row
    for block in blocks:
        for sorted_row_num in block:
            for col in range(min_col, max_col + 1):
                src_data = cell_data[(sorted_row_num, col)]
                write_cell(ws, output_row, col, src_data)
            output_row += 1
        
        # Skip blank separator rows between blocks (don't touch them)
        if block != blocks[-1]:
            output_row += 1
    
    # Clear any remaining rows in the target range that weren't written.
    # These are rows beyond the last block that were originally blank.
    # Don't touch them — they're already blank with correct styles.
    # (No action needed — they're already in their original state)
    
    # Save
    wb.save(output_path)
    return blocks


def main():
    parser = argparse.ArgumentParser(description='XLSX structural transformation')
    parser.add_argument('input', help='Input xlsx file path')
    parser.add_argument('output', help='Output xlsx file path')
    parser.add_argument('--range', dest='range_str', default='A1:H85',
                        help='Target range (default: A1:H85)')
    parser.add_argument('--sheet', default=None,
                        help='Target sheet name (default: first sheet)')
    parser.add_argument('--sort-col', default='D',
                        help='Column to sort by (default: D)')
    parser.add_argument('--sort-order', default='desc', choices=['asc', 'desc'],
                        help='Sort order (default: desc)')
    parser.add_argument('--formula-cols', default='D,E,F',
                        help='Comma-separated formula columns (default: D,E,F)')
    
    args = parser.parse_args()
    formula_cols = [c.strip() for c in args.formula_cols.split(',')]
    
    blocks = transform(
        args.input, args.output,
        sheet_name=args.sheet,
        range_str=args.range_str,
        sort_col=args.sort_col,
        sort_order=args.sort_order,
        formula_cols=formula_cols,
    )
    
    print(f"Transformation complete. {len(blocks)} blocks processed.")
    for i, block in enumerate(blocks):
        print(f"  Block {i+1}: {len(block)} rows")


if __name__ == '__main__':
    main()
