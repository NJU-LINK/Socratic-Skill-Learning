#!/usr/bin/env python3
"""
HTML Finance Verify — Robust financial report consistency checker.
Combines named-pattern and generic detection strategies.
"""
import sys
import re
from html.parser import HTMLParser
from decimal import Decimal, ROUND_HALF_UP


class FinancialTableParser(HTMLParser):
    """Parse HTML tables, tracking table boundaries."""
    
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_cell = ""
        self.current_cell_class = ""
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.in_thead = False
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.in_table = True
            self.current_table = []
        elif tag == "thead":
            self.in_thead = True
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.current_cell = ""
            self.current_cell_class = attrs_dict.get("class", "")
            
    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
            self.tables.append(self.current_table)
        elif tag == "thead":
            self.in_thead = False
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if not self.in_thead:
                row = self._process_row(self.current_row)
                if row:
                    self.current_table.append(row)
        elif tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            self.current_row.append({
                "text": self.current_cell.strip(),
                "class": self.current_cell_class
            })
            
    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data
    
    def _process_row(self, cells):
        """Convert raw cells into a structured row dict."""
        if len(cells) < 3:
            return None
        # Find the line number cell
        line_idx = None
        for i, cell in enumerate(cells):
            text = cell["text"]
            cls = cell["class"]
            if "line" in cls or (text.isdigit() and line_idx is None):
                line_idx = i
                break
        if line_idx is None or line_idx + 2 >= len(cells):
            return None
        try:
            line_num = int(cells[line_idx]["text"])
            metric_name = cells[line_idx + 1]["text"]
            raw_value = cells[line_idx + 2]["text"]
            vtype = "percentage" if "%" in raw_value else ("dollar" if "$" in raw_value else "number")
            numeric = parse_numeric(raw_value)
            return {"line": line_num, "metric": metric_name, "numeric": numeric, "raw": raw_value, "type": vtype}
        except (ValueError, IndexError):
            return None


def parse_numeric(s):
    """Strip symbols and convert to float. Handle parenthetical negatives."""
    s = s.strip()
    m = re.match(r'^\((.+)\)$', s)
    if m:
        s = "-" + m.group(1)
    return float(s.replace("$", "").replace("%", "").replace(",", "").strip())


def round_financial(value, decimals):
    """Round using ROUND_HALF_UP to match typical financial reporting."""
    d = Decimal(str(value))
    q = "0" if decimals == 0 else "0." + "0" * decimals
    return float(d.quantize(Decimal(q), rounding=ROUND_HALF_UP))


def tolerance_for_decimals(decimals):
    """Half the unit of the last displayed digit."""
    return 0.5 * (10 ** (-decimals))


def detect_decimal_places(tables):
    """Detect decimal precision from percentage or dollar values."""
    for table in tables:
        for row in table:
            if row["type"] == "percentage":
                raw = row["raw"].replace("%", "").strip()
                if "." in raw:
                    return len(raw.split(".")[-1])
        for row in table:
            if row["type"] == "dollar":
                raw = row["raw"].replace("$", "").replace(",", "").strip()
                if "." in raw:
                    return len(raw.split(".")[-1])
    return 1


def is_leaf_expense(name):
    """Check if metric is a leaf expense item (not a subtotal/aggregate)."""
    name_lower = name.lower()
    exclude = ["total", "sum", "profit", "income", "margin", "revenue", 
               "gross", "operating", "net", "earnings", "other"]
    if any(kw in name_lower for kw in exclude):
        return False
    include = ["research", "development", "sales", "marketing", "administrative",
               "general", "depreciation", "amortization", "expense", "cost"]
    return any(kw in name_lower for kw in include)


def generate_checks(tables, decimals):
    """
    Generate verifiable relationship checks using both named-pattern and generic detection.
    """
    checks = []
    
    all_rows = []
    for table in tables:
        all_rows.extend(table)
    
    # === Named-pattern checks ===
    
    # Build metric map (lowercase keys)
    metric_map = {}
    for row in all_rows:
        metric_map[row["metric"].lower().strip()] = row
    
    # Gross profit = Revenue - Cost of revenue
    if all(k in metric_map for k in ["revenue", "cost of revenue", "gross profit"]):
        r = metric_map["revenue"]
        c = metric_map["cost of revenue"]
        g = metric_map["gross profit"]
        checks.append((round_financial(r["numeric"] - c["numeric"], decimals), g["numeric"],
                      [r["line"], c["line"], g["line"]], "Gross profit = Revenue - COGS"))
    
    # Total opex = sum of leaf expenses
    for table in tables:
        for i, row in enumerate(table):
            if row["type"] == "dollar" and "total" in row["metric"].lower():
                leaf_items = [r for r in table[:i] if r["type"] == "dollar" and is_leaf_expense(r["metric"])]
                if leaf_items:
                    expected = sum(r["numeric"] for r in leaf_items)
                    involved = [r["line"] for r in leaf_items] + [row["line"]]
                    checks.append((round_financial(expected, decimals), row["numeric"], involved,
                                  f"Total = sum(leaf items): {row['metric']}"))
    
    # Operating income = Gross profit - Total opex
    if all(k in metric_map for k in ["gross profit", "operating income"]):
        gp = metric_map["gross profit"]
        oi = metric_map["operating income"]
        total_opex = None
        for row in all_rows:
            if "total operating expense" in row["metric"].lower() and row["type"] == "dollar":
                total_opex = row
                break
        if total_opex:
            expected = gp["numeric"] - total_opex["numeric"]
            checks.append((round_financial(expected, decimals), oi["numeric"],
                          [gp["line"], total_opex["line"], oi["line"]],
                          "Operating income = Gross profit - Total opex"))
    
    # Net income = Operating income + Other items
    if "net income" in metric_map and "operating income" in metric_map:
        ni = metric_map["net income"]
        oi = metric_map["operating income"]
        others = [r for r in all_rows if "other" in r["metric"].lower().strip() and r["line"] != ni["line"]]
        if others:
            expected = oi["numeric"] + sum(r["numeric"] for r in others)
            involved = [oi["line"]] + [r["line"] for r in others] + [ni["line"]]
            checks.append((round_financial(expected, decimals), ni["numeric"], involved,
                          "Net income = Operating income + Other items"))
    
    # Margin checks
    if "revenue" in metric_map:
        rev = metric_map["revenue"]
        if "gross margin" in metric_map and "gross profit" in metric_map:
            gm = metric_map["gross margin"]
            gp = metric_map["gross profit"]
            expected = (gp["numeric"] / rev["numeric"]) * 100
            checks.append((round_financial(expected, decimals), gm["numeric"],
                          [gp["line"], rev["line"], gm["line"]], "Gross margin = Gross profit / Revenue"))
        if "operating margin" in metric_map and "operating income" in metric_map:
            om = metric_map["operating margin"]
            oi = metric_map["operating income"]
            expected = (oi["numeric"] / rev["numeric"]) * 100
            checks.append((round_financial(expected, decimals), om["numeric"],
                          [oi["line"], rev["line"], om["line"]], "Operating margin = Operating income / Revenue"))
        if "net margin" in metric_map and "net income" in metric_map:
            nm = metric_map["net margin"]
            ni = metric_map["net income"]
            expected = (ni["numeric"] / rev["numeric"]) * 100
            checks.append((round_financial(expected, decimals), nm["numeric"],
                          [ni["line"], rev["line"], nm["line"]], "Net margin = Net income / Revenue"))
    
    # === Generic ratio detection (fallback for unfamiliar metric names) ===
    pcts = [r for r in all_rows if r["type"] == "percentage"]
    dollars = [r for r in all_rows if r["type"] == "dollar"]
    
    for pct in pcts:
        # Check if this percentage already has a named-pattern check
        already_checked = any(pct["line"] in involved for _, _, involved, _ in checks)
        if already_checked:
            continue
        
        # Find best matching dollar pair
        best_match = None
        best_diff = float('inf')
        dollars_sorted = sorted(dollars, key=lambda d: abs(d["numeric"]), reverse=True)
        
        for d2 in dollars_sorted[:3]:  # Try top 3 as denominator
            for d1 in dollars:
                if d1["line"] == d2["line"] or d2["numeric"] == 0:
                    continue
                expected_pct = (d1["numeric"] / d2["numeric"]) * 100
                rounded_pct = round_financial(expected_pct, decimals)
                diff = abs(rounded_pct - pct["numeric"])
                if diff < best_diff:
                    best_diff = diff
                    best_match = (rounded_pct, pct["numeric"], [d1["line"], d2["line"], pct["line"]],
                                 f"Ratio: {pct['metric']} = {d1['metric']}/{d2['metric']}")
        if best_match:
            checks.append(best_match)
    
    return checks


def find_wrong_value(checks, decimals):
    """Intersection algorithm with passing-check filtering."""
    tol = tolerance_for_decimals(decimals)
    failing = []
    passing_lines = set()
    
    for expected, reported, involved, desc in checks:
        diff = abs(expected - reported)
        if diff > tol:
            print(f"  FAIL: {desc} | expected={expected} reported={reported} diff={diff:.4f}")
            failing.append((set(involved), desc))
        else:
            print(f"  OK:   {desc} | expected={expected} reported={reported}")
            passing_lines.update(involved)
    
    if not failing:
        print("All checks passed — no inconsistency found.")
        return None
    
    # Candidates must be in ALL failing checks
    candidates = failing[0][0].copy()
    for s, _ in failing[1:]:
        candidates &= s
    
    # Eliminate candidates that appear in any passing check
    candidates -= passing_lines
    
    print(f"\nFailing sets: {[s for s,_ in failing]}")
    print(f"Passing lines: {passing_lines}")
    print(f"Candidates after filtering: {candidates}")
    
    if len(candidates) == 1:
        return candidates.pop()
    elif len(candidates) > 1:
        # Pick the one appearing in most failing checks
        counts = {}
        for s, _ in failing:
            for v in s:
                if v in candidates:
                    counts[v] = counts.get(v, 0) + 1
        return max(counts, key=counts.get)
    else:
        # Fallback: use original intersection
        candidates = failing[0][0].copy()
        for s, _ in failing[1:]:
            candidates &= s
        return candidates.pop() if candidates else None


def format_output(wrong_row):
    """
    Format the wrong value for output.
    
    Default behavior: strip common symbols and handle parenthetical negatives.
    
    IMPORTANT: Before using this function, read the task instruction carefully.
    The instruction may specify:
    - Whether to include or strip currency/percentage symbols
    - Whether to preserve commas
    - Specific numeric format requirements
    
    Adapt this function based on the actual task requirements.
    """
    raw = wrong_row["raw"].strip()
    
    # Default: strip common symbols
    value = raw.replace("%", "").replace("$", "").replace(",", "").strip()
    
    # Handle parenthetical negatives: (45.2) → -45.2
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    
    return value


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 verify.py <html_file> <output_file>")
        sys.exit(1)
    
    html_file = sys.argv[1]
    output_file = sys.argv[2]
    
    with open(html_file) as f:
        html_content = f.read()
    
    parser = FinancialTableParser()
    parser.feed(html_content)
    tables = parser.tables
    
    all_rows = []
    for t in tables:
        all_rows.extend(t)
    
    print(f"Parsed {len(all_rows)} metrics from {len(tables)} tables:")
    for row in all_rows:
        print(f"  Line {row['line']}: {row['metric']} = {row['raw']} ({row['type']}, {row['numeric']})")
    
    decimals = detect_decimal_places(tables)
    print(f"\nDecimal places: {decimals}")
    
    checks = generate_checks(tables, decimals)
    print(f"\nRunning {len(checks)} checks:")
    wrong_line = find_wrong_value(checks, decimals)
    
    if wrong_line is not None:
        wrong_row = next(r for r in all_rows if r["line"] == wrong_line)
        reported_value = format_output(wrong_row)
        print(f"\nWrong: Line {wrong_line}, value {reported_value}")
        with open(output_file, "w") as f:
            f.write(f"{wrong_line},{reported_value}")
        print(f"Written to {output_file}: {wrong_line},{reported_value}")
    else:
        print("ERROR: Could not identify the wrong value.")
        sys.exit(1)


if __name__ == "__main__":
    main()
