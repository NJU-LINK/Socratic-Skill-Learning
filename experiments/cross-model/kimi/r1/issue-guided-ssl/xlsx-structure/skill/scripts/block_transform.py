#!/usr/bin/env python3
"""
Legacy wrapper for backward compatibility.

This script is now a thin wrapper around transform.py.
All functionality has been consolidated into the modular transform.py.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import and re-export from the canonical module
from transform import (
    col_letter_to_num,
    evaluate_formula,
    detect_blocks,
    extract_row_data,
    process_block,
    write_blocks,
    cells_equal,
    BlockSorter,
    BlockFilter,
    BlockTransformer,
    transform_workbook,
    verify_output_full,
    verify_sort_output,
    verify_filter_output,
    test_negative_control,
    main as transform_main,
)

if __name__ == '__main__':
    sys.exit(transform_main())
