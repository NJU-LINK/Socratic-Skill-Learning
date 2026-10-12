#!/usr/bin/env python3
"""
Dedicated solver for xlsx-structure v01 tasks.

Block-sort transformation: Sort rows within blank-separated blocks by
evaluated column D in descending order, preserving tie order.

This is a thin specialization of transform.py - all core logic is imported.

Usage:
    python3 solve_v01.py input.xlsx output.xlsx [--verify]
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from transform import (
    BlockSorter,
    transform_workbook,
    verify_sort_output,
)


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 solve_v01.py input.xlsx output.xlsx [--verify]", file=sys.stderr)
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    do_verify = '--verify' in sys.argv
    
    # v01 defaults: sort by column D (4), evaluate D-F (4,5,6), process A1:H85
    transformer = BlockSorter(sort_col=4, descending=True)
    
    transform_workbook(
        input_path, output_path, transformer,
        sheet_name='Sheet1', max_row=85, eval_cols=[4, 5, 6], num_cols=8
    )
    
    print(f"Saved to {output_path}")
    
    if do_verify:
        passed, errors = verify_sort_output(
            input_path, output_path,
            max_row=85, sort_col=4, eval_cols=[4, 5, 6], num_cols=8
        )
        if passed:
            print("Verification PASSED")
        else:
            print("Verification FAILED:", file=sys.stderr)
            for e in errors[:10]:
                print(f"  {e}", file=sys.stderr)
            sys.exit(1)
    
    sys.exit(0)


if __name__ == '__main__':
    main()
