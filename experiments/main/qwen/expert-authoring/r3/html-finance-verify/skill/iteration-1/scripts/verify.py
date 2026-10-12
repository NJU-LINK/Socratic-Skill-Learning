#!/usr/bin/env python3
"""
HTML Finance Report Verifier

Parses an HTML earnings report, extracts line-numbered metrics,
verifies income-statement arithmetic and KPI calculations,
and reports the single incorrect metric.

Usage:
    python3 verify.py [--html PATH] [--output PATH]

Defaults:
    --html   /app/q2_earnings_report.html
    --output /app/value.txt
"""

import argparse
import re
import sys
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# HTML table parser (works without BeautifulSoup)
# ---------------------------------------------------------------------------

class MetricTableParser(HTMLParser):
    """Extract rows of (line_number, metric_name, value) from HTML tables."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._in_td = False
        self._td_class = None
        self._current_row_cells = []
        self._current_cell_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self._in_td = True
            self._td_class = dict(attrs).get("class", "")
            self._current_cell_text = ""

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            self._in_td = False
            self._current_row_cells.append(
                (self._td_class, self._current_cell_text.strip())
            )
            self._td_class = None
        elif tag == "tr" and self._current_row_cells:
            self._process_row(self._current_row_cells)
            self._current_row_cells = []

    def handle_data(self, data):
        if self._in_td:
            self._current_cell_text += data

    def _process_row(self, cells):
        """Try to extract a (line, name, value) triple from a row's cells."""
        line_num = None
        name = None
        value = None

        for cls, text in cells:
            if "line" in cls and text.isdigit():
                line_num = int(text)
            elif cls and "num" in cls:
                value = text
            elif not cls or "line" not in cls:
                if name is None and text and not text.startswith("$"):
                    name = text

        if line_num is not None and name and value:
            self.rows.append((line_num, name, value))


# ---------------------------------------------------------------------------
# Value cleaning
# ---------------------------------------------------------------------------

def clean_value(raw: str) -> tuple:
    """Return (float_value, is_percentage)."""
    is_pct = "%" in raw
    cleaned = raw.replace("$", "").replace("%", "").replace(",", "").strip()
    # Handle parentheses as negative
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    return float(cleaned), is_pct


# ---------------------------------------------------------------------------
# Known income-statement relationships
# ---------------------------------------------------------------------------

# Each tuple: (result_name_patterns, operand_patterns, operation)
# Patterns are matched case-insensitively against metric names.
INCOME_RELATIONSHIPS = [
    # Gross profit = Revenue - Cost of revenue
    (
        ["gross profit"],
        [("add", ["revenue"]), ("sub", ["cost of revenue", "cost of goods", "cogs"])],
    ),
    # Total operating expenses = sum of R&D, S&M, G&A, and other opex
    (
        ["total operating expenses", "total opex"],
        [
            ("add", [
                "research and development", "r&d", "research & development",
                "sales and marketing", "s&m", "selling",
                "general and administrative", "g&a", "general & administrative",
                "depreciation", "amortization",
            ]),
        ],
    ),
    # Operating income = Gross profit - Total operating expenses
    (
        ["operating income", "operating profit", "ebit"],
        [("add", ["gross profit"]), ("sub", ["total operating expenses", "total opex"])],
    ),
    # Net income = Operating income + Other income - Tax
    (
        ["net income", "net earnings", "net profit"],
        [
            ("add", ["operating income", "other income", "interest income"]),
            ("sub", ["tax", "income tax", "interest expense"]),
        ],
    ),
]


def find_metric(name_patterns: list, metrics: dict) -> tuple:
    """Find a metric whose name matches any of the patterns."""
    for pname in name_patterns:
        for mname, mdata in metrics.items():
            if pname in mname.lower():
                return mname, mdata
    return None, None


def verify_income_statement(metrics: dict) -> list:
    """
    Check income-statement arithmetic.
    Returns list of (metric_name, reported, expected) for mismatches.
    """
    mismatches = []

    for result_pats, operand_groups in INCOME_RELATIONSHIPS:
        result_name, result_data = find_metric(result_pats, metrics)
        if result_data is None:
            continue

        total = 0.0
        all_found = True
        for op, patterns in operand_groups:
            group_total = 0.0
            any_found = False
            for mname, mdata in metrics.items():
                if mname == result_name:
                    continue
                for pat in patterns:
                    if pat in mname.lower():
                        if op == "add":
                            group_total += mdata["value"]
                        elif op == "sub":
                            group_total -= mdata["value"]
                        any_found = True
                        break
            if not any_found:
                all_found = False
                break
            total += group_total

        if not all_found:
            continue

        diff = abs(result_data["value"] - total)
        if diff > 0.05:
            mismatches.append((result_name, result_data["value"], total))

    return mismatches


# ---------------------------------------------------------------------------
# KPI verification
# ---------------------------------------------------------------------------

# Maps KPI name patterns to (numerator_patterns, denominator_patterns, multiply_100)
KPI_DEFINITIONS = [
    (["gross margin"], ["gross profit"], ["revenue"], True),
    (["operating margin"], ["operating income", "operating profit", "ebit"], ["revenue"], True),
    (["net margin", "net profit margin"], ["net income", "net earnings", "net profit"], ["revenue"], True),
    (["ebitda margin"], ["ebitda"], ["revenue"], True),
    (["r&d", "research"], ["research and development", "r&d"], ["revenue"], True),
    (["operating ratio"], ["total operating expenses", "total opex"], ["revenue"], True),
    (["tax rate"], ["tax", "income tax"], ["net income", "income before tax"], True),
]


def detect_decimal_places(value: float) -> int:
    """Detect the number of decimal places in a float."""
    s = f"{value}"
    if "." in s:
        return len(s.split(".")[1].rstrip("0")) or 0
    return 0


def verify_kpis(metrics: dict, dollar_metrics: dict) -> list:
    """
    Verify each KPI metric.
    Returns list of (metric_name, line_number, reported_value, expected_value).
    """
    errors = []

    for mname, mdata in metrics.items():
        if not mdata["pct"]:
            continue

        for kpi_pats, num_pats, den_pats, is_pct in KPI_DEFINITIONS:
            if not any(pat in mname.lower() for pat in kpi_pats):
                continue

            # Find numerator
            num_name, num_data = find_metric(num_pats, dollar_metrics)
            if num_data is None:
                continue

            # Find denominator
            den_name, den_data = find_metric(den_pats, dollar_metrics)
            if den_data is None:
                continue

            # Compute expected
            dp = max(detect_decimal_places(mdata["value"]), 1)
            multiplier = 100 if is_pct else 1
            expected = round(num_data["value"] / den_data["value"] * multiplier, dp)
            tolerance = 10 ** (-dp) / 2 + 0.01

            if abs(expected - mdata["value"]) > tolerance:
                errors.append((mname, mdata["line"], mdata["value"], expected))
            break  # matched a KPI definition, stop checking

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Verify HTML finance report")
    parser.add_argument("--html", default="/app/q2_earnings_report.html",
                        help="Path to HTML report")
    parser.add_argument("--output", default="/app/value.txt",
                        help="Output file path")
    args = parser.parse_args()

    # --- Parse HTML ---
    with open(args.html) as f:
        html = f.read()

    p = MetricTableParser()
    p.feed(html)

    if not p.rows:
        # Fallback: regex extraction
        pattern = r'<td class="line">(\d+)</td>\s*<td>(.*?)</td>\s*<td class="num">(.*?)</td>'
        raw_rows = re.findall(pattern, html, re.DOTALL)
        for line_str, name, value in raw_rows:
            p.rows.append((int(line_str), name.strip(), value.strip()))

    if not p.rows:
        print("ERROR: Could not extract any metric rows from HTML.", file=sys.stderr)
        sys.exit(1)

    # --- Build metric dict ---
    metrics = {}
    for line_num, name, raw_value in p.rows:
        val, is_pct = clean_value(raw_value)
        metrics[name] = {
            "line": line_num,
            "value": val,
            "pct": is_pct,
            "raw": raw_value,
        }

    dollar_metrics = {k: v for k, v in metrics.items() if not v["pct"]}
    kpi_metrics = {k: v for k, v in metrics.items() if v["pct"]}

    print(f"Extracted {len(metrics)} metrics ({len(dollar_metrics)} dollar, {len(kpi_metrics)} KPI)")
    for name, m in metrics.items():
        print(f"  Line {m['line']}: {name} = {m['value']}{'%' if m['pct'] else ''}")

    # --- Verify income statement ---
    print("\n=== Income Statement Verification ===")
    is_mismatches = verify_income_statement(metrics)
    if is_mismatches:
        for name, reported, expected in is_mismatches:
            print(f"  WARNING: {name}: reported={reported}, expected={expected}")
    else:
        print("  All income statement relationships verified OK")

    # --- Verify KPIs ---
    print("\n=== KPI Verification ===")
    kpi_errors = verify_kpis(metrics, dollar_metrics)

    if len(kpi_errors) == 1:
        name, line, reported, expected = kpi_errors[0]
        print(f"  ERROR FOUND: {name} at line {line}")
        print(f"    Reported: {reported}")
        print(f"    Expected: {expected}")

        # Format the value: remove trailing zeros but keep at least the precision shown
        val_str = str(reported)
        if "." in val_str:
            val_str = val_str.rstrip("0").rstrip(".")
            # But if original had decimal places, keep them
            raw_clean = reported
            if int(reported) != reported:
                val_str = str(reported)

        with open(args.output, "w") as f:
            f.write(f"{line},{val_str}\n")
        print(f"\n  Written to {args.output}: {line},{val_str}")

    elif len(kpi_errors) == 0:
        print("  All KPIs verified OK — no error found!")
        print("  WARNING: The task guarantees exactly one error. Re-check KPI definitions.")
        # Try a broader check: any KPI whose value doesn't match simple ratio calcs
        print("\n  Attempting brute-force ratio check against all dollar metrics...")
        rev_name, rev_data = find_metric(["revenue"], dollar_metrics)
        if rev_data:
            for mname, mdata in kpi_metrics.items():
                for dname, ddata in dollar_metrics.items():
                    if dname == rev_name:
                        continue
                    ratio = round(ddata["value"] / rev_data["value"] * 100, 1)
                    if abs(ratio - mdata["value"]) <= 0.06:
                        print(f"    {mname} ≈ {dname}/Revenue = {ratio}% (reported {mdata['value']}%) ✓")
                    # Check if there's a NEAR match that's slightly off
                    elif abs(ratio - mdata["value"]) <= 2.0:
                        print(f"    {mname} ≈ {dname}/Revenue = {ratio}% (reported {mdata['value']}%) — CLOSE MISMATCH")
        sys.exit(1)

    else:
        print(f"  WARNING: {len(kpi_errors)} KPI errors found (expected 1):")
        for name, line, reported, expected in kpi_errors:
            print(f"    Line {line}: {name} reported={reported} expected={expected}")
        sys.exit(1)


if __name__ == "__main__":
    main()
