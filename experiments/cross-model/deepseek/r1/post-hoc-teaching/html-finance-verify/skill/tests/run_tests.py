#!/usr/bin/env python3
"""Regression runner for html-finance-verify fixtures.

Expectations per fixture:
  OK line,value          - script must exit 0 and write exactly 'line,value'
  AMBIG substring        - script must exit 2 and output must contain substring
  NONE                   - script must exit 2 (no unique wrong metric)

Usage: python3 tests/run_tests.py [--verbose]
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'scripts', 'find_wrong_metric.py')

CASES = [
    ('t0_basic.html', 'OK', '11,60.8'),
    ('t1_subtotal.html', 'OK', '4,260.0'),
    ('t2_ratio_only.html', 'OK', '1,862.0'),
    ('t3_plural.html', 'OK', '210,60.8'),
    ('t4_prior_year.html', 'OK', '2,310.0'),
    ('t8_wrong_total.html', 'OK', '4,260.0'),
    ('t9_tax_rate.html', 'OK', '10,18.0'),
    ('t10_working_capital.html', 'OK', '11,140.0'),
    ('t11_abs_change.html', 'OK', '9,145.0'),
    ('t12_single_cell.html', 'OK', '210,60.8'),
    ('t13_unit_dup_kpi_first.html', 'OK', '1,241000'),
    ('t13b_unit_dup_stmt_first.html', 'OK', '210,241000'),
    ('t14_interrupted_block.html', 'NONE', None),
    ('t15_header_units.html', 'OK', '2,15.0'),
    ('t16_shares_doc_unit.html', 'OK', '4,0.55'),
    ('t17_negative_margins.html', 'OK', '9,-42.0'),
    ('t18_dup_same_scale.html', 'OK', '210,241.0'),
    ('t18b_dup_same_scale_kpi_first.html', 'OK', '1,241.0'),
    ('t19_annotated_labels.html', 'OK', '1,241000'),
    ('t5_consistent.html', 'NONE', None),
    ('t6_eps_underdetermined.html', 'AMBIG', 'Diluted EPS'),
    ('t7_cashflow_underdetermined.html', 'AMBIG', 'Financing'),
]


def run_case(fname, kind, want):
    html = os.path.join(HERE, fname)
    out = os.path.join(tempfile.gettempdir(), '.hw-%s.out' % fname)
    if os.path.exists(out):
        os.remove(out)
    p = subprocess.run([sys.executable, SCRIPT, '--html', html, '--out', out],
                       capture_output=True, text=True)
    text = p.stdout + p.stderr
    got = open(out).read().strip() if os.path.exists(out) else ''
    if kind == 'OK':
        ok = p.returncode == 0 and got == want
    elif kind == 'AMBIG':
        ok = p.returncode == 2 and want in text
    else:  # NONE
        ok = p.returncode == 2 and got == ''
    return ok, p.returncode, got, text


def main():
    verbose = '--verbose' in sys.argv
    fails = 0
    for fname, kind, want in CASES:
        ok, rc, got, text = run_case(fname, kind, want)
        tag = 'PASS' if ok else 'FAIL'
        if not ok:
            fails += 1
        print('%s %s (want %s %r, rc=%d, got=%r)' % (tag, fname, kind, want, rc, got))
        if (not ok or verbose) and text:
            for line in text.splitlines()[-6:]:
                print('    ' + line)
    print('--- %d/%d passed ---' % (len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())