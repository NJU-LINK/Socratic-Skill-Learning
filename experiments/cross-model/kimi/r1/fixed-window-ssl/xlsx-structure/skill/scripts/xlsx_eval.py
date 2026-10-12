"""
Recursive formula evaluator for xlsx-structure transformations.

Handles row-local arithmetic with memoization to resolve dependencies
(e.g., F depends on D, which may itself be a formula).
"""

import re

# Match cell references like A1, $B$2, etc.
REF = re.compile(r'\$?([A-Z]+)\$?(\d+)')

# Global memo cache: {(ws, row, col): value}
_eval_cache = {}


def col_to_idx(letters):
    """Convert column letters (A, B, ..., AA, AB) to 1-based column index."""
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def clear_cache():
    """Clear the global evaluator cache. Call between workbooks."""
    _eval_cache.clear()


def evaluate_cell(ws, row, col):
    """
    Evaluate a single cell, with caching.
    
    Safe to call repeatedly - caches results per (ws, row, col).
    Handles formula dependencies automatically via make_evaluator.
    
    Usage:
        d_val = evaluate_cell(ws, 5, 4)  # Evaluate D5
    """
    key = (id(ws), row, col)
    if key in _eval_cache:
        return _eval_cache[key]
    
    eval_fn = make_evaluator(ws, row)
    result = eval_fn(col)
    _eval_cache[key] = result
    return result


def make_evaluator(ws, row):
    """
    Create an evaluator function for a specific row.
    
    The evaluator handles:
    - None values → 0.0
    - Numeric values → float
    - Formula strings (starting with '=') → recursive evaluation
    - Other strings → attempt float conversion
    
    Usage (simple):
        d_value = evaluate_cell(ws, 5, 4)  # Evaluate D5
    
    Usage (for multiple cells in same row):
        eval_fn = make_evaluator(ws, row=5)
        d_value = eval_fn(4)  # Get evaluated value of D5
        e_value = eval_fn(5)  # Get evaluated value of E5 (memoized)
    """
    memo = {}
    
    def val(col_idx):
        if col_idx in memo:
            return memo[col_idx]
        
        v = ws.cell(row=row, column=col_idx).value
        
        if v is None:
            r = 0.0
        elif isinstance(v, (int, float)):
            r = float(v)
        elif isinstance(v, str) and v.startswith('='):
            # Replace cell references with their evaluated values
            def repl(m):
                col_letters = m.group(1)
                # Note: We ignore the row number in the reference and use
                # the current row being evaluated
                ref_col = col_to_idx(col_letters)
                return repr(val(ref_col))
            
            expr = REF.sub(repl, v[1:])  # Remove leading '='
            # Safe eval: only arithmetic remains after substitution
            r = float(eval(expr, {'__builtins__': {}}, {}))
        else:
            # Try to convert to float (handles numeric strings)
            try:
                r = float(v)
            except (ValueError, TypeError):
                r = 0.0
        
        memo[col_idx] = r
        return r
    
    return val
