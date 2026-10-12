#!/usr/bin/env python3
"""
Verify a financial-analysis results CSV (stdlib only — no pandas needed).

Usage examples:
    python3 scripts/verify_output.py /app/results.csv
    python3 scripts/verify_output.py /app/results.csv --expected-columns fiscal_year,gross_margin_pct
    python3 scripts/verify_output.py /app/results.csv --expected-columns year,net_margin_pct --min-rows 3
"""

import sys
import csv
import argparse
import re


def verify(path, expected_columns=None, min_rows=1):
    errors = []
    warnings = []

    # 1. File exists and is readable
    try:
        with open(path, newline='', encoding='utf-8') as f:
            raw = f.read()
    except FileNotFoundError:
        print(f"FAIL: {path} not found")
        return False
    except Exception as e:
        print(f"FAIL: Could not read {path}: {e}")
        return False

    # Check for BOM
    if raw.startswith('\ufeff'):
        errors.append("File has UTF-8 BOM — should be plain UTF-8")

    # Check trailing blank lines
    stripped = raw.rstrip('\n')
    trailing_newlines = len(raw) - len(stripped) - 1
    if trailing_newlines > 1:
        warnings.append(f"File has {trailing_newlines} trailing blank lines")

    # Parse CSV
    try:
        reader = csv.DictReader(raw.strip().splitlines())
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    except Exception as e:
        print(f"FAIL: Could not parse CSV: {e}")
        return False

    # 2. Column check
    if expected_columns is not None:
        if fieldnames != expected_columns:
            errors.append(
                f"Column mismatch: expected {expected_columns}, got {list(fieldnames)}"
            )

    if len(fieldnames) < 2:
        errors.append(f"Expected at least 2 columns, got {len(fieldnames)}")

    if len(rows) < min_rows:
        errors.append(f"Expected at least {min_rows} data rows, got {len(rows)}")

    # 3. Null / empty check
    for i, row in enumerate(rows):
        for col in fieldnames:
            val = row.get(col, '')
            if val is None or val.strip() == '':
                errors.append(f"Row {i+1}, column '{col}' is empty or null")

    # 4. Metric range check (skip year-like columns)
    year_keywords = {'year', 'fy', 'period', 'fiscal_year', 'date'}
    metric_cols = [c for c in fieldnames
                   if not any(kw in c.lower() for kw in year_keywords)]

    for col in metric_cols:
        values = []
        for row in rows:
            try:
                values.append(float(row[col]))
            except (ValueError, TypeError):
                errors.append(f"Column '{col}' has non-numeric value: {row.get(col)}")
                continue

        if not values:
            continue

        max_abs = max(abs(v) for v in values)
        # Check if values look like decimals instead of percentages
        if 0 < max_abs < 1.0:
            errors.append(
                f"Column '{col}' max |value| is {max_abs:.4f} — "
                f"likely raw decimals instead of percentage numbers"
            )
        # Check plausible range
        if max_abs > 500:
            warnings.append(
                f"Column '{col}' has |value| > 500% — verify this is intentional"
            )

    # 5. Duplicate year check
    year_cols = [c for c in fieldnames
                 if any(kw in c.lower() for kw in year_keywords)]
    for col in year_cols:
        year_vals = [row.get(col, '') for row in rows]
        if len(year_vals) != len(set(year_vals)):
            dupes = [v for v in year_vals if year_vals.count(v) > 1]
            errors.append(f"Duplicate values in '{col}': {set(dupes)}")

    # 6. Report
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  ⚠ {w}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  ✗ {e}")
        return False
    else:
        print("PASS: All checks passed")
        print(f"  Columns: {fieldnames}")
        print(f"  Rows: {len(rows)}")
        for row in rows:
            print(f"    {dict(row)}")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate a financial-analysis results CSV (stdlib only)."
    )
    parser.add_argument("path", help="Path to results CSV (e.g. /app/results.csv)")
    parser.add_argument(
        "--expected-columns",
        help="Comma-separated expected column names (e.g. fiscal_year,gross_margin_pct)",
        default=None,
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=1,
        help="Minimum number of data rows expected (default: 1)",
    )
    args = parser.parse_args()

    cols = args.expected_columns.split(",") if args.expected_columns else None
    ok = verify(args.path, cols, args.min_rows)
    sys.exit(0 if ok else 1)
