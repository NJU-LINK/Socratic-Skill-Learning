"""
Block topology detection strategies for xlsx-structure transformations.
"""


def is_blank_row(ws, row, max_col=8):
    """
    Check if all cells in columns 1-max_col are blank or whitespace-only.
    
    Treats None, empty strings, and whitespace-only strings as blank.
    """
    for col in range(1, max_col + 1):
        v = ws.cell(row=row, column=col).value
        if v is not None:
            if isinstance(v, str) and v.strip() == '':
                continue  # Whitespace-only is blank
            return False
    return True


def find_blank_separated_blocks(ws, start_row=1, end_row=None, max_col=8):
    """
    Find contiguous non-blank row blocks separated by blank rows.
    
    Args:
        ws: openpyxl worksheet
        start_row: First row to check (1-based)
        end_row: Last row to check (inclusive); if None, uses ws.max_row
        max_col: Columns to check for blankness
    
    Returns:
        List of blocks, where each block is a list of row numbers
        Example: [[1,2,3], [5,6,7]] for rows 1-3 and 5-7 with blank at row 4
    """
    if end_row is None:
        end_row = ws.max_row
    
    blocks = []
    current_block = []
    
    for row in range(start_row, end_row + 1):
        if is_blank_row(ws, row, max_col):
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(row)
    
    # Don't forget the last block
    if current_block:
        blocks.append(current_block)
    
    return blocks


def collapse_consecutive_blanks(ws, blocks, start_row=1, end_row=85):
    """
    Ensure exactly one blank row between adjacent blocks.
    
    If variant requires exactly one separator, use this after finding blocks.
    Currently a placeholder - v01 keeps input blank structure.
    """
    # For future expansion: insert or delete blank rows as needed
    return blocks


def find_header_blocks(ws, header_col=1, start_row=1, end_row=None):
    """
    Find blocks separated by header rows (where header_col has a specific pattern).
    
    Placeholder for header-mapped topology variant.
    """
    raise NotImplementedError("Header-mapped block detection not yet implemented")


def find_style_blocks(ws, style_predicate, start_row=1, end_row=None):
    """
    Find blocks where cells match a style predicate.
    
    Placeholder for style-marked topology variant.
    
    Args:
        style_predicate: function(cell) -> bool, True if cell marks block boundary
    """
    raise NotImplementedError("Style-marked block detection not yet implemented")
