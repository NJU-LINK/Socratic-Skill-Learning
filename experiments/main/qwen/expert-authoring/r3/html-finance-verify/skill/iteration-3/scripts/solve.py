#!/usr/bin/env python3
"""
HTML Finance Report Solver.
Run: python3 solve.py [--html PATH] [--output PATH]
"""
import argparse, re, sys
from html.parser import HTMLParser

# ============================================================================
# HTML Parsing
# ============================================================================
class TableMetricParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._in_td = False
        self._td_attrs = {}
        self._current_row = []
        self._cell_text = ""
    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self._in_td = True
            self._td_attrs = dict(attrs)
            self._cell_text = ""
    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            self._in_td = False
            self._current_row.append((self._td_attrs, self._cell_text.strip()))
            self._td_attrs = {}
        elif tag == "tr" and self._current_row:
            self._process_row(self._current_row)
            self._current_row = []
    def handle_data(self, data):
        if self._in_td:
            self._cell_text += data
    def _process_row(self, cells):
        line_num = None; name = None; value = None
        for attrs, text in cells:
            cls = attrs.get("class", "")
            if line_num is None and "line" in cls:
                digits = re.sub(r"[^\d]", "", text)
                if digits and digits.isdigit() and int(digits) >= 10:
                    line_num = int(digits); continue
            if line_num is None and re.fullmatch(r"\s*\d{2,4}\s*", text):
                line_num = int(text.strip()); continue
            if "num" in cls or "value" in cls or "amount" in cls:
                value = text
            elif name is None and text and not re.fullmatch(r"\$?[\d,.]+\s*%?", text):
                name = text
            elif value is None and re.search(r"[\d]", text):
                value = text
        if line_num is not None and name and value:
            self.rows.append((line_num, name.strip(), value.strip()))

def parse_with_regex(html):
    rows = []
    patterns = [
        r'<td[^>]*class="[^"]*line[^"]*"[^>]*>(\d+)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*class="[^"]*num[^"]*"[^>]*>(.*?)</td>',
        r'<td[^>]*>\s*(\d{2,4})\s*</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>\s*([$\d,.]+%?)\s*</td>',
    ]
    for pat in patterns:
        matches = re.findall(pat, html, re.DOTALL | re.IGNORECASE)
        if matches:
            for m in matches:
                if len(m) == 3:
                    a, b, c = m
                    if a.strip().isdigit():
                        rows.append((int(a.strip()), b.strip(), c.strip()))
            if rows: return rows
    return rows

# ============================================================================
# Value Cleaning
# ============================================================================
def clean_value(raw):
    is_pct = "%" in raw
    cleaned = raw.replace("$","").replace("%","").replace(",","").replace("\u00a0","").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    val = float(cleaned)
    dp = 0
    if "." in cleaned:
        dec = cleaned.split(".")[-1].rstrip("0")
        dp = len(dec) if dec else 0
    return val, is_pct, dp

# ============================================================================
# Metric Name Matching
# ============================================================================
def _has_pattern(metric_name_lower, patterns):
    """
    Flexible name matching with plural, prefix, and suffix handling.
    - Prefix match: 'general and admin' matches 'general and administrative'
    - Suffix match: 'operating expense' matches 'total operating expenses'
    - Exact word: 'revenue' matches 'revenue' (with optional plural s)
    """
    for p in patterns:
        pl = p.lower()
        # Prefix match
        if metric_name_lower.startswith(pl):
            return True
        # Suffix match (with optional plural 's')
        if re.search(r'\b' + re.escape(pl) + r's?$', metric_name_lower):
            return True
        # Exact word match (with optional plural 's')
        if re.search(r'\b' + re.escape(pl) + r's?\b', metric_name_lower):
            return True
    return False

def find_metric_by_patterns(metrics_dict, patterns, exclude_names=None):
    for name, data in metrics_dict.items():
        if exclude_names and name in exclude_names:
            continue
        if _has_pattern(name.lower(), patterns):
            return name, data
    return None, None

# ============================================================================
# Income Statement Verification
# ============================================================================
# Format: (result_patterns, add_patterns, sub_patterns)
# sub_patterns checked FIRST to prevent "Revenue" matching "Cost of revenue"
INCOME_CHECKS = [
    (["gross profit"],
     ["revenue", "total revenue", "net revenue"],
     ["cost of revenue", "cost of goods", "cogs", "cost of sales"]),
    (["total operating expense", "total opex"],
     ["research and development", "r&d",
      "sales and marketing", "s&m",
      "general and admin", "g&a", "general & admin",
      "depreciation", "amortization"],
     []),
    (["operating income", "operating profit"],
     ["gross profit"],
     ["total operating expense", "total opex"]),
    (["net income", "net earnings", "net profit"],
     ["operating income", "other income", "interest income",
      "income before tax", "pre-tax income"],
     ["income tax", "tax expense"]),
]

def verify_income_statement(metrics):
    mismatches = []
    dollar = {k: v for k, v in metrics.items() if not v["pct"]}

    for result_pats, add_pats, sub_pats in INCOME_CHECKS:
        rname, rdata = find_metric_by_patterns(dollar, result_pats)
        if rdata is None: continue

        total = 0.0
        sub_names = set()

        # First: identify subtract metrics
        if sub_pats:
            for mname in dollar:
                if mname == rname: continue
                if _has_pattern(mname.lower(), sub_pats):
                    total -= dollar[mname]["value"]
                    sub_names.add(mname)

        # Then: add metrics (excluding subtracted ones and result)
        add_found = False
        for mname in dollar:
            if mname == rname or mname in sub_names: continue
            if _has_pattern(mname.lower(), add_pats):
                total += dollar[mname]["value"]
                add_found = True

        if add_found or sub_names:
            diff = abs(rdata["value"] - total)
            if diff > 0.05:
                mismatches.append((rname, rdata["value"], total, diff))
    return mismatches

# ============================================================================
# KPI Verification
# ============================================================================
NAMED_KPI_FORMULAS = [
    (["gross margin"], ["gross profit"], ["revenue", "total revenue", "net revenue"]),
    (["operating margin"], ["operating income", "operating profit", "ebit"],
     ["revenue", "total revenue", "net revenue"]),
    (["net margin", "net profit margin"], ["net income", "net earnings", "net profit"],
     ["revenue", "total revenue", "net revenue"]),
    (["ebitda margin"], ["ebitda"], ["revenue", "total revenue", "net revenue"]),
    (["r&d", "research"], ["research and development", "r&d", "research expense"],
     ["revenue", "total revenue", "net revenue"]),
    (["selling", "sales and marketing", "s&m"],
     ["sales and marketing", "s&m", "selling expense"],
     ["revenue", "total revenue", "net revenue"]),
    (["general and admin", "g&a", "administrative"],
     ["general and admin", "g&a", "administrative expense"],
     ["revenue", "total revenue", "net revenue"]),
    (["operating ratio"], ["total operating expense", "total opex"],
     ["revenue", "total revenue", "net revenue"]),
    (["tax rate", "effective tax"], ["income tax", "tax expense", "tax"],
     ["income before tax", "pre-tax income", "ebt", "net income"]),
]

def detect_report_precision(kpi_metrics):
    dp_counts = {}
    for m in kpi_metrics:
        dp = m["dp"]; dp_counts[dp] = dp_counts.get(dp, 0) + 1
    return max(dp_counts, key=dp_counts.get) if dp_counts else 1

def tolerance_for_dp(dp):
    return 0.5 * (10 ** (-dp)) + 0.01

def verify_kpi_named(kpi_data, dollar_metrics, dp, tol):
    for kpi_pats, num_pats, den_pats in NAMED_KPI_FORMULAS:
        if not _has_pattern(kpi_data["name"].lower(), kpi_pats): continue
        num_name, num_data = find_metric_by_patterns(dollar_metrics, num_pats)
        den_name, den_data = find_metric_by_patterns(dollar_metrics, den_pats)
        if num_data and den_data and den_data["value"] != 0:
            expected = round(num_data["value"] / den_data["value"] * 100, dp)
            is_match = abs(expected - kpi_data["value"]) <= tol
            return expected, is_match, num_name, den_name
    return None, None, None, None

def verify_kpi_bruteforce(kpi_data, dollar_metrics, dp, tol):
    for num_name, num_data in dollar_metrics.items():
        for den_name, den_data in dollar_metrics.items():
            if num_name == den_name or den_data["value"] == 0: continue
            expected = round(num_data["value"] / den_data["value"] * 100, dp)
            if abs(expected - kpi_data["value"]) <= tol:
                return True, expected, num_name, den_name
    return False, None, None, None

# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="/app/q2_earnings_report.html")
    parser.add_argument("--output", default="/app/value.txt")
    args = parser.parse_args()

    with open(args.html) as f:
        html = f.read()

    hp = TableMetricParser()
    hp.feed(html)
    raw_rows = hp.rows
    if not raw_rows:
        raw_rows = parse_with_regex(html)
    if not raw_rows:
        print("ERROR: Could not extract any metric rows.", file=sys.stderr)
        sys.exit(1)

    metrics = {}
    for line_num, name, raw_value in raw_rows:
        val, is_pct, dp = clean_value(raw_value)
        metrics[name] = {"line": line_num, "value": val, "pct": is_pct, "dp": dp, "raw": raw_value, "name": name}

    dollar_metrics = {k: v for k, v in metrics.items() if not v["pct"]}
    kpi_metrics_list = [v for v in metrics.values() if v["pct"]]

    print(f"Extracted {len(metrics)} metrics: {len(dollar_metrics)} dollar, {len(kpi_metrics_list)} KPI\n")
    for name, m in metrics.items():
        suffix = "%" if m["pct"] else ""
        print(f"  Line {m['line']:>4d}: {name:40s} = {m['value']:>12.4f}{suffix}")

    print("\n=== Income Statement Verification ===")
    is_mm = verify_income_statement(metrics)
    if is_mm:
        for rname, reported, expected, diff in is_mm:
            print(f"  WARNING: {rname}: reported={reported}, expected={expected}, diff={diff:.4f}")
    else:
        print("  All income statement relationships verified OK")

    dp = detect_report_precision(kpi_metrics_list)
    tol = tolerance_for_dp(dp)
    print(f"\n  Detected precision: {dp} dp, tolerance: +/-{tol:.4f}")

    print("\n=== KPI Verification ===")
    errors = []
    for kpi in kpi_metrics_list:
        expected, is_match, num_name, den_name = verify_kpi_named(kpi, dollar_metrics, dp, tol)
        if is_match is not None:
            status = "OK" if is_match else "MISMATCH"
            print(f"  {kpi['name']:30s}: expected={expected}%, reported={kpi['value']}% ({num_name}/{den_name}) -> {status}")
            if not is_match: errors.append(kpi)
        else:
            found, bf_exp, bf_num, bf_den = verify_kpi_bruteforce(kpi, dollar_metrics, dp, tol)
            if found:
                print(f"  {kpi['name']:30s}: expected={bf_exp}%, reported={kpi['value']}% ({bf_num}/{bf_den}) -> OK [brute-force]")
            else:
                print(f"  {kpi['name']:30s}: reported={kpi['value']}% -> NO MATCH [brute-force]")
                errors.append(kpi)

    print(f"\n=== Results: {len(errors)} error(s) ===")
    if len(errors) == 1:
        err = errors[0]
        line = err["line"]; val = err["value"]
        val_str = f"{val}"
        if "." in val_str:
            val_str = val_str.rstrip("0").rstrip(".")
            if err["dp"] > 0 and "." not in val_str:
                val_str = f"{val:.{err['dp']}f}"
        print(f"  ERROR: {err['name']} at line {line}")
        print(f"  Output: {line},{val_str}")
        with open(args.output, "w") as f:
            f.write(f"{line},{val_str}\n")
        print(f"  Written to {args.output}")
    elif len(errors) == 0:
        print("  WARNING: No errors found. Check formulas and precision.")
        sys.exit(1)
    else:
        print(f"  WARNING: {len(errors)} errors found (expected 1):")
        for err in errors:
            print(f"    Line {err['line']}: {err['name']} = {err['value']}%")
        sys.exit(1)

if __name__ == "__main__":
    main()
