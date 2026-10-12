#!/usr/bin/env python3
"""
Financial Analysis Solver — general across the financial-analysis family.

Usage:
    python solve.py \
        --data-dir /app/financials \
        --company "NVIDIA Corporation" \
        --metric gross_margin \
        --threshold 70 \
        --threshold-metric gross_margin \
        --alternate-metric net_margin \
        --output /app/results.csv \
        --columns fiscal_year,gross_margin_pct

The script:
  1. Discovers the correct file(s) by scanning for the target company.
  2. Parses financial data robustly across formats.
  3. Evaluates a threshold condition on the most recent year.
  4. Computes the appropriate metric for all years.
  5. Writes a CSV result.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path


# ── Metric definitions ──────────────────────────────────────────────────
METRIC_FIELDS = {
    "gross_margin": ("gross_profit", "revenue"),
    "operating_margin": ("operating_income", "revenue"),
    "net_margin": ("net_income", "revenue"),
    "return_on_equity": ("net_income", "shareholders_equity"),
}

# Canonical field-name mapping (lowercase variants → canonical)
FIELD_ALIASES = {
    # Revenue
    "revenue": "revenue",
    "total revenue": "revenue",
    "net revenue": "revenue",
    "net revenues": "revenue",
    "sales": "revenue",
    "total sales": "revenue",
    # Gross Profit
    "gross profit": "gross_profit",
    "grossprofit": "gross_profit",
    "gross margin": "gross_profit",  # sometimes labeled as dollar amount
    # Operating Income
    "operating income": "operating_income",
    "operatingincome": "operating_income",
    "operating profit": "operating_income",
    "ebit": "operating_income",
    "income from operations": "operating_income",
    # Net Income
    "net income": "net_income",
    "netincome": "net_income",
    "net earnings": "net_income",
    "profit": "net_income",
    "net profit": "net_income",
    # Shareholders' Equity
    "shareholders equity": "shareholders_equity",
    "shareholder equity": "shareholders_equity",
    "total equity": "shareholders_equity",
    "stockholders equity": "shareholders_equity",
    "equity": "shareholders_equity",
    "total stockholders equity": "shareholders_equity",
    "total shareholders equity": "shareholders_equity",
    # Year
    "year": "year",
    "fiscal year": "year",
    "fiscalyear": "year",
    "fy": "year",
    "period": "year",
}


def normalize_field_name(raw: str) -> str:
    """Normalize a raw field name to canonical form."""
    name = raw.strip().lower()
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if name in FIELD_ALIASES:
        return FIELD_ALIASES[name]
    # Try removing all spaces
    collapsed = name.replace(" ", "")
    if collapsed in FIELD_ALIASES:
        return FIELD_ALIASES[collapsed]
    return name


def parse_number(raw: str) -> float | None:
    """Parse a numeric string, handling currency symbols, commas, and suffixes."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "-" or s == "N/A" or s == "n/a":
        return None
    # Remove currency symbols
    s = re.sub(r"[$€¥£]", "", s)
    # Detect multiplier suffix
    multiplier = 1.0
    if re.search(r"[Tt]$", s):
        multiplier = 1e12
        s = s[:-1]
    elif re.search(r"[Bb]$", s):
        multiplier = 1e9
        s = s[:-1]
    elif re.search(r"[Mm]$", s):
        multiplier = 1e6
        s = s[:-1]
    elif re.search(r"[Kk]$", s):
        multiplier = 1e3
        s = s[:-1]
    # Remove thousands separators (commas in English, dots in some locales)
    # Heuristic: if string has both commas and dots, comma is thousands sep
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # European: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:
            # English: 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        # Could be thousands separator or decimal
        # If multiple commas, it's thousands separator
        if s.count(",") > 1:
            s = s.replace(",", "")
        else:
            # Single comma: if 3 digits after comma, it's thousands
            parts = s.split(",")
            if len(parts[1]) == 3 and len(parts[0]) >= 1:
                s = s.replace(",", "")
            else:
                s = s.replace(",", ".")
    s = s.strip()
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def is_decoration_line(line: str) -> bool:
    """Check if a line is purely decorative (===, ---, ***, etc.)."""
    stripped = line.strip()
    if not stripped:
        return True
    if re.match(r"^[=\-*#]{3,}$", stripped):
        return True
    return False


def is_header_like(tokens: list[str]) -> bool:
    """Check if a list of tokens looks like a header row."""
    alpha_count = sum(1 for t in tokens if re.match(r"^[A-Za-z_ /()]+$", t.strip()))
    return alpha_count >= len(tokens) * 0.6


# ── File Discovery ──────────────────────────────────────────────────────

def discover_files(data_dir: str, company: str) -> list[Path]:
    """Find files in data_dir that contain the target company's financial data."""
    matches = []
    data_path = Path(data_dir)
    for fpath in sorted(data_path.rglob("*")):
        if not fpath.is_file():
            continue
        if fpath.suffix in (".pyc", ".pyo", ".so"):
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Check for company name or ticker (case-insensitive)
        content_lower = content.lower()
        company_lower = company.lower()
        if company_lower in content_lower:
            # Verify it has financial data fields
            has_financial_fields = any(
                kw in content_lower
                for kw in ["revenue", "gross profit", "net income",
                           "operating income", "income", "profit", "equity"]
            )
            if has_financial_fields:
                matches.append(fpath)
    return matches


# ── Parsers ─────────────────────────────────────────────────────────────

def parse_csv_content(text: str) -> list[dict]:
    """Parse CSV-like content into list of dicts.

    Uses improved header detection: finds a line with ≥2 comma-separated
    alpha tokens where the next content line contains numeric data.
    """
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        tokens = [t.strip() for t in line.split(",")]
        if len(tokens) < 2:
            continue
        if not is_header_like(tokens):
            continue
        # Verify the next non-empty line has numeric data
        for j in range(i + 1, len(lines)):
            next_tokens = [t.strip() for t in lines[j].split(",")]
            if not next_tokens or all(t == "" for t in next_tokens):
                continue
            numeric_count = sum(
                1 for t in next_tokens if re.match(r"^[\d.,$€¥£\-]+$", t.strip())
            )
            if numeric_count >= len(next_tokens) * 0.3:
                header_idx = i
            break  # found next content line; stop inner loop
        if header_idx is not None:
            break
    if header_idx is None:
        return []
    reader = csv.DictReader(lines[header_idx:])
    rows = []
    for row in reader:
        parsed = {}
        for k, v in row.items():
            if k is None:
                continue
            canon = normalize_field_name(k)
            parsed[canon] = v.strip() if v else ""
        # Skip trailing non-data rows (notes, decorations, etc.)
        year_val = parsed.get("year", "")
        if year_val and not re.search(r"\d{4}", year_val):
            continue
        if any(parsed.values()):
            rows.append(parsed)
    return rows


def parse_fixed_width(text: str) -> list[dict]:
    """Parse fixed-width / decorated text with a CSV data section."""
    lines = text.splitlines()
    # Find a header row followed by data rows with commas
    for i, line in enumerate(lines):
        if is_decoration_line(line):
            continue
        tokens = [t.strip() for t in line.split(",")]
        if is_header_like(tokens) and len(tokens) >= 2:
            # Try to parse from here as CSV
            return parse_csv_content("\n".join(lines[i:]))
    return []


def parse_json_content(text: str) -> list[dict]:
    """Parse JSON content into list of dicts."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    # Handle various JSON structures
    if isinstance(data, list):
        return [
            {normalize_field_name(k): v for k, v in item.items()}
            for item in data if isinstance(item, dict)
        ]
    elif isinstance(data, dict):
        # Look for a list value
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return [
                    {normalize_field_name(k): val for k, val in item.items()}
                    for item in v
                ]
    return []


def parse_html_content(text: str) -> list[dict]:
    """Parse HTML table content."""
    try:
        import pandas as pd
        dfs = pd.read_html(text)
        if dfs:
            df = dfs[0]
            df.columns = [normalize_field_name(c) for c in df.columns]
            return df.to_dict("records")
    except ImportError:
        pass
    # Fallback: extract table rows with regex
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.DOTALL | re.IGNORECASE)
    if not rows:
        return []
    result = []
    headers = None
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if not cells:
            continue
        if headers is None:
            headers = [normalize_field_name(c) for c in cells]
        else:
            result.append(dict(zip(headers, cells)))
    return result


def parse_file(filepath: Path) -> list[dict]:
    """Auto-detect format and parse a file."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    ext = filepath.suffix.lower()

    # Try format-specific parsers first based on extension
    if ext == ".json":
        rows = parse_json_content(content)
        if rows:
            return rows
    elif ext in (".html", ".htm"):
        rows = parse_html_content(content)
        if rows:
            return rows
    elif ext == ".csv":
        rows = parse_csv_content(content)
        if rows:
            return rows

    # Fallback: try all parsers
    for parser in [parse_csv_content, parse_fixed_width, parse_json_content]:
        rows = parser(content)
        if rows:
            return rows
    return []


# ── Core Logic ──────────────────────────────────────────────────────────

def extract_yearly_data(rows: list[dict]) -> list[dict]:
    """
    Extract and normalize yearly financial data from parsed rows.
    Returns list of dicts with canonical keys: year, revenue, gross_profit, etc.
    """
    results = []
    for row in rows:
        year = row.get("year", "")
        if not year:
            continue
        # Try to extract a year-like pattern
        year_match = re.search(r"(\d{4})", str(year))
        if not year_match:
            continue
        parsed_row = {"year": str(year).strip()}
        for field in ["revenue", "gross_profit", "operating_income",
                       "net_income", "shareholders_equity"]:
            raw = row.get(field, "")
            val = parse_number(raw)
            parsed_row[field] = val
        results.append(parsed_row)
    return results


def compute_metric(year_data: dict, metric: str) -> float | None:
    """Compute a financial metric for a single year's data."""
    if metric == "year_over_year_growth":
        return None  # Handled separately
    fields = METRIC_FIELDS.get(metric)
    if not fields:
        return None
    num_field, den_field = fields
    num = year_data.get(num_field)
    den = year_data.get(den_field)
    if num is None or den is None or den == 0:
        return 0.0
    return round(num / den * 100, 2)


def compute_yoy_growth(data: list[dict], value_field: str) -> list[tuple[str, float]]:
    """Compute year-over-year growth for a sorted list of yearly data."""
    results = []
    for i in range(1, len(data)):
        prev_val = data[i - 1].get(value_field)
        curr_val = data[i].get(value_field)
        if prev_val and curr_val and prev_val != 0:
            growth = round((curr_val - prev_val) / prev_val * 100, 2)
            results.append((data[i]["year"], growth))
    return results


def main():
    parser = argparse.ArgumentParser(description="Financial Analysis Solver")
    parser.add_argument("--data-dir", required=True, help="Directory containing financial data files")
    parser.add_argument("--company", required=True, help="Target company name or ticker")
    parser.add_argument("--metric", required=True, choices=list(METRIC_FIELDS.keys()) + ["year_over_year_growth"],
                        help="Primary metric to compute")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Threshold for conditional gate (e.g., 70)")
    parser.add_argument("--threshold-metric", default=None,
                        help="Metric to check threshold against (defaults to --metric)")
    parser.add_argument("--alternate-metric", default=None,
                        help="Metric to compute if threshold is NOT met")
    parser.add_argument("--threshold-operator", default="gt", choices=["gt", "gte", "lt", "lte", "eq"],
                        help="Comparison operator for threshold")
    parser.add_argument("--output", required=True, help="Output CSV file path")
    parser.add_argument("--columns", default="fiscal_year,gross_margin_pct",
                        help="Comma-separated column names for output CSV")
    parser.add_argument("--yoy-field", default="revenue",
                        help="Field to compute YoY growth on (default: revenue)")
    parser.add_argument("--no-condition", action="store_true",
                        help="Skip threshold gate; always compute the primary metric")
    args = parser.parse_args()

    # Discover files
    files = discover_files(args.data_dir, args.company)
    if not files:
        print(f"ERROR: No files found for company '{args.company}' in {args.data_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(files)} matching file(s): {[f.name for f in files]}")

    # Parse all matching files and merge data
    all_data = []
    for f in files:
        rows = parse_file(f)
        yearly = extract_yearly_data(rows)
        all_data.extend(yearly)
    if not all_data:
        print("ERROR: No financial data extracted", file=sys.stderr)
        sys.exit(1)

    # Sort by year
    def year_sort_key(d):
        m = re.search(r"(\d{4})", d["year"])
        return int(m.group(1)) if m else 0
    all_data.sort(key=year_sort_key)
    print(f"Extracted {len(all_data)} year(s) of data")
    for d in all_data:
        print(f"  {d['year']}: {d}")

    # Determine which metric to compute
    threshold_metric = args.threshold_metric or args.metric
    if args.no_condition or args.threshold is None:
        chosen_metric = args.metric
    else:
        # Evaluate threshold on most recent year
        most_recent = all_data[-1]
        check_value = compute_metric(most_recent, threshold_metric)
        print(f"Most recent year ({most_recent['year']}): {threshold_metric} = {check_value}%")
        op = args.threshold_operator
        threshold = args.threshold
        condition_met = False
        if op == "gt":
            condition_met = check_value is not None and check_value > threshold
        elif op == "gte":
            condition_met = check_value is not None and check_value >= threshold
        elif op == "lt":
            condition_met = check_value is not None and check_value < threshold
        elif op == "lte":
            condition_met = check_value is not None and check_value <= threshold
        elif op == "eq":
            condition_met = check_value is not None and check_value == threshold
        print(f"Threshold {op} {threshold}: {'MET' if condition_met else 'NOT MET'}")
        if condition_met:
            chosen_metric = args.metric
        elif args.alternate_metric:
            chosen_metric = args.alternate_metric
        else:
            chosen_metric = args.metric

    print(f"Computing: {chosen_metric} for all years")

    # Compute metric
    col_names = [c.strip() for c in args.columns.split(",")]
    year_col = col_names[0] if col_names else "fiscal_year"
    value_col = col_names[1] if len(col_names) > 1 else f"{chosen_metric}_pct"

    output_rows = []
    if chosen_metric == "year_over_year_growth":
        growth_data = compute_yoy_growth(all_data, args.yoy_field)
        for year, value in growth_data:
            output_rows.append({year_col: year, value_col: f"{value:.2f}"})
    else:
        for d in all_data:
            val = compute_metric(d, chosen_metric)
            if val is not None:
                output_rows.append({year_col: d["year"], value_col: f"{val:.2f}"})

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[year_col, value_col])
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"\nWrote {len(output_rows)} rows to {args.output}")
    # Print result for verification
    with open(args.output) as f:
        print(f.read())


if __name__ == "__main__":
    main()
