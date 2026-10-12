#!/usr/bin/env python3
"""
Canonical parameterized cross-check for the SORT semantic (identity write-back).

Verifies that the output workbook's span equals the stable-sorted payloads of
the input, keyed by the evaluated sort column. The span, sort column, eval
columns and direction come from the RUN's own spec (--span / --sort-col /
--eval-cols / --asc), never from literals, so the check cannot drift from the
invocation it verifies. Eval columns are normalized (formula text is evaluated
with the pipeline's cell_value before comparison - never compare '=B1+C1'
against 224.9 directly, that is the formula-vs-number trap).

Epistemic label: this uses the same library functions as the pipeline
(detect_blocks / cell_value / expected_row_order), so it is a SHARED-PATH
rederivation: it catches writeback, invocation and normalization drift, but NOT
mapper-spec bugs. Those need hand-derived oracles (scripts/family_probe.py).
For the filter/compact semantic use its own --check plus family_probe.py;
this tool verifies identity write-back semantics only.

Usage:
  python3 scripts/crosscheck.py input.xlsx output.xlsx \\
      --span A1:H85 --sort-col D --eval-cols D:F [--asc] [--sheet Sheet1]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openpyxl import load_workbook

from transform import (cell_value, detect_blocks, eval_col_indices,
                       expected_row_order, parse_span, span_cols, values_equal)

_API_DOC = """\
crosscheck.py contract (python3 crosscheck.py --api prints this):
  verify_order(input_path, output_path, span, sort_col, eval_cols,
               desc=True, sheet=None) -> (bad, blocks, order)
      bad    = [(out_row, col, expected, got), ...]  # empty means PASS
      blocks = [(start_row, end_row), ...]           # detected from input
      order  = per block, input row indices in the stable expected order
  Semantics: identity write-back sort verified through shared-path primitives
  (detect_blocks, cell_value, expected_row_order) with eval columns normalized
  from the run spec. Shared-path label: catches writeback/invocation drift,
  not mapper-spec bugs (use scripts/family_probe.py for those).
"""


def verify_order(input_path, output_path, span, sort_col, eval_cols,
                 desc=True, sheet=None):
    """Compare the output span against stable-sorted input payloads.

    All geometry and normalization are derived from the run spec (span,
    sort_col, eval_cols, desc), never hardcoded. Returns (bad, blocks, order);
    bad is empty iff the cross-check passes.
    """
    ib = load_workbook(input_path, data_only=False)
    ob = load_workbook(output_path, data_only=False)
    iws = ib[sheet] if sheet else ib.active
    ows = ob[sheet] if sheet else ob.active
    min_c, min_r, max_c, max_r = parse_span(span)
    cols = span_cols(min_c, max_c)
    evcols = eval_col_indices(eval_cols)
    blocks, _ = detect_blocks(iws, span)
    order = expected_row_order(iws, blocks, sort_col, desc=desc)
    bad = []
    for (s, e), seq in zip(blocks, order):
        for out_r, in_r in zip(range(s, e + 1), seq):
            for c in cols:
                a = iws.cell(row=in_r, column=c).value
                if isinstance(a, str):
                    a = a.strip()
                if c in evcols and isinstance(a, str) and a.startswith("="):
                    a = cell_value(iws, in_r, c, {})  # normalize eval columns
                b = ows.cell(row=out_r, column=c).value
                if not values_equal(a, b):
                    bad.append((out_r, c, a, b))
    return bad, blocks, order


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="input xlsx (omit with --api)")
    ap.add_argument("output", nargs="?", help="output xlsx (omit with --api)")
    ap.add_argument("--api", action="store_true",
                    help="print this contract and exit")
    ap.add_argument("--span", default="A1:H85")
    ap.add_argument("--sort-col", default="D")
    ap.add_argument("--eval-cols", default="D:F")
    ap.add_argument("--asc", action="store_true", help="ascending instead of descending")
    ap.add_argument("--sheet", default=None)
    args = ap.parse_args(argv)
    if args.api:
        print(_API_DOC)
        return 0
    if not args.input or not args.output:
        ap.error("input and output paths are required (or use --api)")
    bad, blocks, order = verify_order(args.input, args.output, args.span,
                                      args.sort_col, args.eval_cols,
                                      desc=not args.asc, sheet=args.sheet)
    min_c, _, max_c, _ = parse_span(args.span)
    n_cols = len(span_cols(min_c, max_c))
    total_cells = sum((e - s + 1) * n_cols for (s, e) in blocks)
    if bad:
        print("CROSS-CHECK FAILED (%d mismatches), first 10:" % len(bad))
        for (r, c, a, b) in bad[:10]:
            print("  row %d col %d: expected %r got %r" % (r, c, a, b))
        return 1
    print("CROSS-CHECK PASSED (%d blocks, %d span cells; spec: span=%s sort-col=%s "
          "eval-cols=%s)" % (len(blocks), total_cells, args.span,
                              args.sort_col, args.eval_cols))
    return 0


if __name__ == "__main__":
    sys.exit(main())