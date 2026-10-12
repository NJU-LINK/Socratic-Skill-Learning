#!/usr/bin/env python3
"""
Financial analysis solver — adapts the SKILL.md template.

Usage: edit the CONFIGURATION section for each new task, then run:
    python3 analyze.py
"""
import os, re, json, sys

# ══════════════════════════════════════════════════════════════
# CONFIGURATION — adapt these to the specific task
# ══════════════════════════════════════════════════════════════
DATA_DIR     = "/app/financials"
COMPANY      = "NVIDIA Corporation"
OUTPUT_PATH  = "/app/results.csv"

METRIC_DEFS = {
    "gross_margin":         ("gross_profit", "revenue"),
    "operating_margin":     ("operating_income", "revenue"),
    "net_margin":           ("net_income", "revenue"),
    "return_on_equity":     ("net_income", "total_equity"),
}
YOY_GROWTH_FIELD = "revenue"

PRIMARY_METRIC   = "gross_margin"
THRESHOLD        = 70.0      # or None for no-branch tasks
ALT_METRIC       = "net_margin"  # or None for no-branch tasks

METRIC_COL_NAMES = {
    "gross_margin":      "gross_margin_pct",
    "operating_margin":  "operating_margin_pct",
    "net_margin":        "net_margin_pct",
    "return_on_equity":  "roe_pct",
    "year_over_year_growth": "yoy_growth_pct",
}

# ══════════════════════════════════════════════════════════════
# FIELD-NAME ALIASES
# ══════════════════════════════════════════════════════════════
ALIASES = {
    "year": "fiscal_year", "fy": "fiscal_year", "period": "fiscal_year",
    "fiscal year": "fiscal_year", "fiscal_year": "fiscal_year",
    "revenue": "revenue", "sales": "revenue", "net revenue": "revenue",
    "total revenue": "revenue", "net sales": "revenue", "net_sales": "revenue",
    "grossprofit": "gross_profit", "gross profit": "gross_profit",
    "gross_profit": "gross_profit", "gp": "gross_profit",
    "operatingincome": "operating_income", "operating income": "operating_income",
    "operating_income": "operating_income", "operating profit": "operating_income",
    "op income": "operating_income", "ebit": "operating_income",
    "netincome": "net_income", "net income": "net_income",
    "net_income": "net_income", "net profit": "net_income",
    "net earnings": "net_income", "net_earnings": "net_income",
    "ni": "net_income", "profit after tax": "net_income",
    "totalequity": "total_equity", "total equity": "total_equity",
    "total_equity": "total_equity", "shareholders equity": "total_equity",
    "shareholders_equity": "total_equity", "stockholders_equity": "total_equity",
    "stockholders equity": "total_equity", "equity": "total_equity",
    "net assets": "total_equity", "net_assets": "total_equity",
}
CANONICAL_FIELDS = set(ALIASES.values())

def normalize(name):
    key = name.strip().lower().replace("_", " ")
    return ALIASES.get(key, key.replace(" ", "_"))

def clean_num(val):
    s = val.strip().replace("$","").replace(",","").replace(" ","")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if not s or s.lower() in ("n/a","na","null","-",""):
        return None
    return float(s)

# ══════════════════════════════════════════════════════════════
# PHASE 1 — DISCOVER (relaxed: only PRIMARY fields required)
# ══════════════════════════════════════════════════════════════
def _fields_for_metric(metric_name):
    if metric_name in METRIC_DEFS:
        return set(METRIC_DEFS[metric_name])
    if metric_name == "year_over_year_growth":
        return {YOY_GROWTH_FIELD}
    return set()

def _field_present(content_norm, field):
    if field in content_norm:
        return True
    return any(a in content_norm for a, c in ALIASES.items() if c == field)

def discover():
    files = []
    for root, dirs, fnames in os.walk(DATA_DIR):
        for fn in sorted(fnames):
            files.append(os.path.join(root, fn))
    primary_fields = _fields_for_metric(PRIMARY_METRIC)
    alt_fields = _fields_for_metric(ALT_METRIC) if ALT_METRIC else set()

    for fpath in files:
        try:
            content = open(fpath, "r", errors="replace").read()
        except Exception:
            continue
        if COMPANY.lower() not in content.lower():
            continue
        norm = content.lower().replace("_"," ")
        if not all(_field_present(norm, f) for f in primary_fields):
            continue
        has_alt = all(_field_present(norm, f) for f in alt_fields) if alt_fields else True
        print(f"[SELECT] {fpath} (has_alt={has_alt})", file=sys.stderr)
        return fpath, content
    raise FileNotFoundError("No matching data file found")

# ══════════════════════════════════════════════════════════════
# PHASE 2 — PARSE
# ══════════════════════════════════════════════════════════════
def parse(content):
    stripped = content.strip()
    if stripped.startswith(("{","[")):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return [{normalize(k): v for k, v in r.items()} for r in data]
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return [{normalize(k): val for k, val in r.items()} for r in v]
        except json.JSONDecodeError:
            pass

    lines = content.splitlines()
    header_idx = None
    header = None
    found_sep = ","
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or set(s) <= {"=","-","*"," ","#"}:
            continue
        if s.startswith("#") or s.lower().startswith("note"):
            continue
        for sep in [",", "\t"]:
            parts = [p.strip() for p in s.split(sep)]
            if len(parts) < 2:
                continue
            normed = [normalize(p) for p in parts]
            if sum(1 for n in normed if n in CANONICAL_FIELDS) >= 2:
                header_idx = i
                header = normed
                found_sep = sep
                break
        if header_idx is not None:
            break

    if header_idx is None:
        raise ValueError("No CSV header found")

    records = []
    for line in lines[header_idx+1:]:
        s = line.strip()
        if not s or set(s) <= {"=","-","*"," ","#"}:
            continue
        if s.startswith("#") or s.lower().startswith("note"):
            continue
        parts = [p.strip() for p in s.split(found_sep)]
        if len(parts) != len(header):
            continue
        row = dict(zip(header, parts))
        fy = row.get("fiscal_year", "")
        if not re.search(r"\d{4}", fy):
            break
        records.append(row)
    return records

# ══════════════════════════════════════════════════════════════
# PHASE 3 — COMPUTE
# ══════════════════════════════════════════════════════════════
def compute(records, metric_name):
    if metric_name == "year_over_year_growth":
        results = []
        prev = None
        for r in records:
            fy = r.get("fiscal_year", "")
            cur = clean_num(r.get(YOY_GROWTH_FIELD, ""))
            if prev is not None and prev != 0 and cur is not None:
                val = round(((cur - prev) / abs(prev)) * 100, 2)
            else:
                val = None
            results.append((fy, val))
            prev = cur
        return results
    num_f, den_f = METRIC_DEFS[metric_name]
    results = []
    for r in records:
        num = clean_num(r.get(num_f, ""))
        den = clean_num(r.get(den_f, ""))
        fy = r.get("fiscal_year", "")
        if num is not None and den is not None and den != 0:
            val = round((num / den) * 100, 2)
        else:
            val = None
        results.append((fy, val))
    return results

# ══════════════════════════════════════════════════════════════
# PHASE 4 — SORT, BRANCH, OUTPUT
# ══════════════════════════════════════════════════════════════
def main():
    fpath, content = discover()
    records = parse(content)
    print(f"[PARSED] {len(records)} records", file=sys.stderr)

    # Sort records by year number (handles any input order)
    def year_num(fy):
        m = re.search(r'(\d{4})', str(fy))
        return int(m.group(1)) if m else 0
    records.sort(key=lambda r: year_num(r.get('fiscal_year', '')))

    # Compute primary metric
    check = compute(records, PRIMARY_METRIC)

    # Branch: check most recent year against threshold
    metric = PRIMARY_METRIC
    if THRESHOLD is not None and ALT_METRIC is not None:
        most_recent_val = check[-1][1]
        exceeds = most_recent_val is not None and most_recent_val > THRESHOLD
        print(f"[CHECK] {PRIMARY_METRIC} latest = {most_recent_val} > {THRESHOLD}? {exceeds}",
              file=sys.stderr)
        if not exceeds:
            metric = ALT_METRIC

    results = check if metric == PRIMARY_METRIC else compute(records, metric)
    col = METRIC_COL_NAMES.get(metric, f"{metric}_pct")

    # Write with guaranteed \n line endings (NO csv.writer!)
    rows = ["fiscal_year," + col]
    for fy, val in results:
        rows.append(f"{fy},{val}")
    with open(OUTPUT_PATH, "w") as f:
        f.write("\n".join(rows) + "\n")

    print(f"[OUTPUT] {OUTPUT_PATH}", file=sys.stderr)
    print(open(OUTPUT_PATH).read())

if __name__ == "__main__":
    main()
