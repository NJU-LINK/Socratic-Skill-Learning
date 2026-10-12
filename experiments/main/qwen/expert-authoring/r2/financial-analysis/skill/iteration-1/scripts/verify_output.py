#!/usr/bin/env python3
"""
Verify a financial-analysis results CSV against common output contracts.

Usage:
    python3 verify_output.py /app/results.csv [--expected-columns col1,col2]

Checks performed:
  1. File exists and is valid CSV
  2. Column names match expectation (if --expected-columns provided)
  3. No null / empty values
  4. Metric values are in a plausible percentage range (not raw decimals)
  5. No trailing blank lines or encoding issues
"""

import sys
import csv
import argparse


def verify(path: str, expected_columns: list[str] | None = None) -> bool:
    errors: list[str] = []

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
    if raw.endswith('\n\n'):
        errors.append("File has trailing blank lines")

    # Parse CSV
    try:
        reader = csv.DictReader(raw.strip().splitlines())
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    except Exception as e:
        print(f"FAIL: Could not parse CSV: {e}")
        return False

    # 2. Column check
    if expected_columns:
        if fieldnames != expected_columns:
            errors.append(
                f"Column mismatch: expected {expected_columns}, got {fieldnames}"
            )

    if len(fieldnames) < 2:
        errors.append(f"Expected at least 2 columns, got {len(fieldnames)}")

    if len(rows) == 0:
        errors.append("No data rows in output")

    # 3. Null / empty check
    for i, row in enumerate(rows):
        for col in fieldnames:
            val = row.get(col, '')
            if val is None or val.strip() == '':
                errors.append(f"Row {i+1}, column '{col}' is empty or null")

    # 4. Metric range check (skip year-like columns)
    year_keywords = {'year', 'fy', 'period', 'fiscal_year'}
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
            errors.append(
                f"Column '{col}' has |value| > 500% — check for unit errors"
            )

    # 5. Report
    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("PASS: All checks passed")
        # Pretty-print the table
        print('\t'.join(fieldnames))
        for row in rows:
            print('\t'.join(row.get(c, '') for c in fieldnames))
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to results CSV")
    parser.add_argument(
        "--expected-columns",
        help="Comma-separated expected column names",
        default=None,
    )
    args = parser.parse_args()

    cols = args.expected_columns.split(",") if args.expected_columns else None
    ok = verify(args.path, cols)
    sys.exit(0 if ok else 1)
