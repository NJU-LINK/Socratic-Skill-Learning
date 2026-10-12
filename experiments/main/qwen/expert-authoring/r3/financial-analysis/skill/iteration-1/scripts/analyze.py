#!/usr/bin/env python3
"""
Generic financial analysis solver.

Usage:
    python analyze.py --data-dir /app/financials \
                      --company "NVIDIA Corporation" \
                      --metric gross_margin \
                      --output /app/results.csv

Supports conditional branching via --threshold and --alt-metric flags.
"""
import argparse
import csv
import json
import glob
import os
import re
import sys


# ── Metric Definitions ──────────────────────────────────────────────
METRICS = {
    "gross_margin": {
        "numerator": "gross_profit",
        "denominator": "revenue",
        "label": "gross_margin_pct",
    },
    "operating_margin": {
        "numerator": "operating_income",
        "denominator": "revenue",
        "label": "operating_margin_pct",
    },
    "net_margin": {
        "numerator": "net_income",
        "denominator": "revenue",
        "label": "net_margin_pct",
    },
    "return_on_equity": {
        "numerator": "net_income",
        "denominator": "total_equity",
        "label": "roe_pct",
    },
    "year_over_year_growth": {
        "field": "revenue",  # can be overridden
        "label": "yoy_growth_pct",
    },
}

# ── Field Name Aliases ──────────────────────────────────────────────
ALIASES = {
    "year": "fiscal_year",
    "fy": "fiscal_year",
    "period": "fiscal_year",
    "fiscal year": "fiscal_year",
    "fiscal_year": "fiscal_year",
    "revenue": "revenue",
    "sales": "revenue",
    "net_revenue": "revenue",
    "total_revenue": "revenue",
    "netsales": "revenue",
    "net sales": "revenue",
    "grossprofit": "gross_profit",
    "gross profit": "gross_profit",
    "gp": "gross_profit",
    "operatingincome": "operating_income",
    "operating income": "operating_income",
    "operating profit": "operating_income",
    "opincome": "operating_income",
    "ebit": "operating_income",
    "netincome": "net_income",
    "net income": "net_income",
    "net profit": "net_income",
    "netearnings": "net_income",
    "ni": "net_income",
    "profit after tax": "net_income",
    "totalequity": "total_equity",
    "total equity": "total_equity",
    "shareholders_equity": "total_equity",
    "shareholdersequity": "total_equity",
    "stockholders_equity": "total_equity",
    "stockholdersequity": "total_equity",
    "equity": "total_equity",
    "net assets": "total_equity",
    "netassets": "total_equity",
}


def normalize_field(name: str) -> str:
    """Normalize a field name to canonical form."""
    key = name.strip().lower().replace("_", " ").replace("  ", " ")
    return ALIASES.get(key, key.replace(" ", "_"))


def clean_numeric(val: str) -> float:
    """Parse a numeric string, handling $, commas, and parentheses."""
    s = val.strip().replace("$", "").replace(",", "").replace(" ", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if not s or s == "-" or s.lower() in ("n/a", "na", "null", ""):
        return None
    return float(s)


# ── Phase 1: Discovery ──────────────────────────────────────────────
def discover_file(data_dir: str, company: str, required_canonical: list) -> str:
    """Find the correct data file by content inspection."""
    candidates = []
    for root, dirs, files in os.walk(data_dir):
        for fname in sorted(files):
            candidates.append(os.path.join(root, fname))

    for fpath in candidates:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        # Check company name (case-insensitive)
        if company and company.lower() not in content.lower():
            continue

        # Check required fields are present somewhere in the file
        content_norm = content.lower().replace("_", " ").replace("-", " ")
        has_all = True
        for field in required_canonical:
            # The field or its aliases should appear in the content
            found = False
            for alias, canon in ALIASES.items():
                if canon == field and alias in content_norm:
                    found = True
                    break
            if field in content_norm:
                found = True
            if not found:
                has_all = False
                break

        if has_all:
            print(f"[SELECT] {fpath}", file=sys.stderr)
            return fpath

    raise FileNotFoundError(
        f"No file in {data_dir} matches company='{company}' "
        f"and required fields {required_canonical}"
    )


# ── Phase 2: Parsing ────────────────────────────────────────────────
def parse_file(fpath: str) -> list:
    """
    Auto-detect format and parse into list of dicts with canonical keys.
    """
    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # Try JSON first
    stripped = raw.strip()
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return [_normalize_row(r) for r in data]
            elif isinstance(data, dict):
                # Look for a list-valued key
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        return [_normalize_row(r) for r in v]
        except json.JSONDecodeError:
            pass

    # Try HTML table
    if "<table" in raw.lower():
        return _parse_html_table(raw)

    # Fall back to CSV-in-text (handles banners, fixed-width wrappers)
    return _parse_csv_in_text(raw)


def _normalize_row(row: dict) -> dict:
    """Normalize keys of a dict to canonical field names."""
    out = {}
    for k, v in row.items():
        canon = normalize_field(k)
        out[canon] = v
    return out


def _parse_csv_in_text(raw: str) -> list:
    """Find the CSV header row and parse data lines, skipping decoration."""
    lines = raw.splitlines()
    header_idx = None
    header_raw = None

    for i, line in enumerate(lines):
        s = line.strip()
        if not s or set(s) <= {"=", "-", "*", " ", "#"}:
            continue
        if s.startswith("#") or s.lower().startswith("note"):
            continue
        # Try as CSV header
        parts = [p.strip() for p in s.split(",")]
        if len(parts) < 2:
            parts = [p.strip() for p in s.split("\t")]
        if len(parts) < 2:
            continue
        normalized = [normalize_field(p) for p in parts]
        # A header must have at least 2 recognized canonical fields
        known = [n for n in normalized if n in {
            "fiscal_year", "revenue", "gross_profit", "operating_income",
            "net_income", "total_equity"
        }]
        if len(known) >= 2:
            header_idx = i
            header_raw = normalized
            break

    if header_idx is None:
        raise ValueError("Could not locate CSV header row in file")

    records = []
    sep = "," if "," in lines[header_idx] else "\t"
    for line in lines[header_idx + 1:]:
        s = line.strip()
        if not s or set(s) <= {"=", "-", "*", " ", "#"}:
            continue
        if s.startswith("#") or s.lower().startswith("note"):
            continue
        parts = [p.strip() for p in s.split(sep)]
        if len(parts) != len(header_raw):
            continue
        row = {}
        for h, v in zip(header_raw, parts):
            row[h] = v
        # Must have a year-like field
        fy = row.get("fiscal_year", "")
        if not re.search(r"\d{4}", fy):
            break
        records.append(row)

    return records


def _parse_html_table(raw: str) -> list:
    """Minimal HTML table parser."""
    from html.parser import HTMLParser

    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.current_row = []
            self.current_cell = ""
            self.in_cell = False

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.current_row = []
            elif tag in ("td", "th"):
                self.in_cell = True
                self.current_cell = ""

        def handle_endtag(self, tag):
            if tag in ("td", "th"):
                self.in_cell = False
                self.current_row.append(self.current_cell.strip())
            elif tag == "tr":
                if self.current_row:
                    self.rows.append(self.current_row)

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data

    parser = TableParser()
    parser.feed(raw)
    rows = parser.rows
    if not rows:
        return []

    header_raw = [normalize_field(h) for h in rows[0]]
    records = []
    for row in rows[1:]:
        if len(row) != len(header_raw):
            continue
        records.append(dict(zip(header_raw, row)))
    return records


# ── Phase 3: Computation ────────────────────────────────────────────
def compute_metric(records: list, metric_name: str, rounding: int = 2) -> list:
    """Compute the requested metric for each record."""
    spec = METRICS[metric_name]

    if metric_name == "year_over_year_growth":
        field = spec["field"]
        results = []
        for i, r in enumerate(records):
            val = clean_numeric(r.get(field, ""))
            if i == 0:
                results.append({"fiscal_year": r["fiscal_year"], "value": None})
            else:
                prev_val = clean_numeric(records[i - 1].get(field, ""))
                if prev_val and prev_val != 0 and val is not None:
                    growth = ((val - prev_val) / abs(prev_val)) * 100
                    results.append({
                        "fiscal_year": r["fiscal_year"],
                        "value": round(growth, rounding),
                    })
                else:
                    results.append({"fiscal_year": r["fiscal_year"], "value": None})
        return results

    # Standard ratio metrics
    num_field = spec["numerator"]
    den_field = spec["denominator"]
    results = []
    for r in records:
        num = clean_numeric(r.get(num_field, ""))
        den = clean_numeric(r.get(den_field, ""))
        if num is not None and den is not None and den != 0:
            val = round((num / den) * 100, rounding)
        else:
            val = None
        results.append({"fiscal_year": r["fiscal_year"], "value": val})
    return results


def check_threshold(results: list, threshold: float) -> bool:
    """Check if the most recent year's value exceeds threshold."""
    if not results:
        return False
    last_val = results[-1]["value"]
    if last_val is None:
        return False
    return last_val > threshold


# ── Phase 4: Output ─────────────────────────────────────────────────
def write_output(path: str, results: list, col_name: str):
    """Write results to CSV."""
    with open(path, "w", newline="") as f:
        f.write(f"fiscal_year,{col_name}\n")
        for r in results:
            val = r["value"] if r["value"] is not None else "N/A"
            f.write(f"{r['fiscal_year']},{val}\n")


# ── Main ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Financial analysis solver")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--metric", required=True, choices=METRICS.keys())
    parser.add_argument("--output", default="/app/results.csv")
    parser.add_argument("--rounding", type=int, default=2)
    parser.add_argument("--threshold", type=float, default=None,
                        help="If set, check most recent year against this value")
    parser.add_argument("--alt-metric", default=None, choices=METRICS.keys(),
                        help="Metric to compute if threshold is NOT exceeded")
    parser.add_argument("--threshold-col", default=None,
                        help="Column name for threshold check metric")
    args = parser.parse_args()

    # Determine required fields
    spec = METRICS[args.metric]
    required = set()
    required.add("fiscal_year")
    if "numerator" in spec:
        required.add(spec["numerator"])
        required.add(spec["denominator"])
    if "field" in spec:
        required.add(spec["field"])
    if args.alt_metric:
        alt_spec = METRICS[args.alt_metric]
        if "numerator" in alt_spec:
            required.add(alt_spec["numerator"])
            required.add(alt_spec["denominator"])

    # Phase 1: Discover
    fpath = discover_file(args.data_dir, args.company, list(required))

    # Phase 2: Parse
    records = parse_file(fpath)
    print(f"[PARSED] {len(records)} records from {fpath}", file=sys.stderr)

    # Phase 3: Compute
    metric = args.metric
    col_name = METRICS[metric]["label"]

    if args.threshold is not None:
        # First compute the threshold-check metric
        check_results = compute_metric(records, metric, args.rounding)
        exceeds = check_threshold(check_results, args.threshold)
        print(
            f"[CHECK] Most recent {col_name} = {check_results[-1]['value']} "
            f"{'>' if exceeds else '<='} {args.threshold}",
            file=sys.stderr,
        )
        if not exceeds and args.alt_metric:
            metric = args.alt_metric
            col_name = METRICS[metric]["label"]
            print(f"[BRANCH] Switching to {metric}", file=sys.stderr)

    results = compute_metric(records, metric, args.rounding)

    # Phase 4: Output
    write_output(args.output, results, col_name)
    print(f"[OUTPUT] {args.output}", file=sys.stderr)
    with open(args.output, "r") as f:
        print(f.read())


if __name__ == "__main__":
    main()
