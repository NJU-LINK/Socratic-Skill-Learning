---
name: financial-analysis
description: >
  Discover, parse, and analyze financial data files to compute standard
  financial metrics (gross margin, operating margin, net margin, ROE,
  year-over-year growth) with conditional logic, handling varied source
  formats, schemas, and output contracts.
---

# Financial Analysis

## Workflow

```
1. Parse task → extract company, metric, threshold, alternate metric, output schema
2. Discover   → find correct file(s) by content, reject decoys
3. Parse      → extract structured yearly data (format-agnostic)
4. Compute    → evaluate threshold on most-recent year, compute chosen metric for all years
5. Output     → write CSV matching exact column spec, verify
```

---

## Phase 1 — Data Discovery

**Goal**: locate the authoritative source file(s) for the target company.

### Rules
1. `find` or `ls` all files in the data directory (often `/app/financials/`).
2. **Read every file** (they are small) and classify each:

| Signal | Keep | Reject |
|--------|------|--------|
| Contains target company name/ticker | ✅ | |
| Contains financial-statement fields (Revenue, Gross Profit, Net Income, Operating Income, Equity) | ✅ | |
| Different company or ticker | | ❌ |
| Log/cache file (`[INFO]`, `[WARN]`, `[DATA]` prefixes; pre-computed percentages) | | ❌ |
| Product-level or quarterly data (when annual needed) | | ❌ |
| No parseable table structure | | ❌ |

> **Invariant**: identify the file by *content*, never by filename alone.

3. If income-statement and balance-sheet data are in **separate files**, join them on the fiscal-year key before computing.

---

## Phase 2 — Parsing (format-agnostic)

### Detection order
Try parsers in this order; use the first that returns ≥1 row with a year field:

1. **CSV/TSV/delimited** — `csv.DictReader`. Auto-detect delimiter (`,` `\t` `;`).
2. **JSON** — `json.load`; walk nested structure to find the list-of-records array.
3. **HTML table** — `pandas.read_html` if available, else regex `<tr>`/`<td>` extraction.
4. **Decorated/fixed-width text** — find the header row inside decoration (`===`, `---`), then treat the data block below it as CSV.

### Robust header detection
Do **not** assume the header starts with `Year` or any literal string. Instead:

```
For each line L with ≥2 comma-separated tokens:
  If ≥60% of tokens are purely alphabetic (allow spaces/underscores):
    Let L_next = next non-empty, non-decoration line
    If L_next has ≥30% numeric tokens → L is the header; stop.
```

### Robust data-row filtering
Do **not** assume rows start with `FY` or any prefix. Instead:

```
After the header, for each subsequent line:
  Skip if: blank, decoration (===, ---, ***), starts with "NOTES", "NOTE", "-", "*".
  Skip if: no token matches a 4-digit year pattern \d{4}.
  Otherwise: keep as a data row.
```

### Field-name normalization
Lowercase, collapse whitespace/underscores/hyphens, then map via aliases:

```python
FIELD_ALIASES = {
    "revenue": "revenue", "total revenue": "revenue", "net revenue": "revenue",
    "sales": "revenue", "net revenues": "revenue", "total sales": "revenue",
    "gross profit": "gross_profit", "grossprofit": "gross_profit",
    "cost of revenue": "cogs", "cost of goods sold": "cogs", "cogs": "cogs",
    "operating income": "operating_income", "operatingincome": "operating_income",
    "operating profit": "operating_income", "ebit": "operating_income",
    "income from operations": "operating_income",
    "net income": "net_income", "netincome": "net_income",
    "net earnings": "net_income", "net profit": "net_income",
    "shareholders equity": "shareholders_equity", "shareholder equity": "shareholders_equity",
    "total equity": "shareholders_equity", "stockholders equity": "shareholders_equity",
    "equity": "shareholders_equity", "total stockholders equity": "shareholders_equity",
    "year": "year", "fiscal year": "year", "fiscalyear": "year",
    "fy": "year", "period": "year", "date": "year",
}
def normalize(name):
    n = re.sub(r"[_\-]+", " ", name.strip().lower())
    n = re.sub(r"\s+", " ", n).strip()
    return FIELD_ALIASES.get(n, FIELD_ALIASES.get(n.replace(" ", ""), n))
```

### Numeric parsing
```python
def parse_num(raw):
    s = str(raw).strip()
    if not s or s in ("-", "N/A", "n/a", ""): return None
    s = re.sub(r"[$€¥£]", "", s)
    mult = 1.0
    for suf, m in [("T",1e12),("B",1e9),("M",1e6),("K",1e3)]:
        if s.upper().endswith(suf): mult = m; s = s[:-1]; break
    # thousands separator: if both , and . present, the one appearing last is decimal
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."): s = s.replace(".","").replace(",",".")
        else: s = s.replace(",","")
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 2 or (len(parts)==2 and len(parts[1])==3): s = s.replace(",","")
        else: s = s.replace(",",".")
    try: return float(s.strip()) * mult
    except ValueError: return None
```

---

## Phase 3 — Metric Computation

### Formulas

| Metric | Numerator | Denominator |
|--------|-----------|-------------|
| `gross_margin` | Gross Profit | Revenue |
| `operating_margin` | Operating Income | Revenue |
| `net_margin` | Net Income | Revenue |
| `return_on_equity` | Net Income | Shareholders' Equity |
| `year_over_year_growth` | V_t − V_{t−1} | V_{t−1} |

All margins/ROE: `(numerator / denominator) × 100`, rounded to 2 dp.
Expressed as percentage numbers (72.72 = 72.72%), **not** decimals.
YoY growth can be negative; skip the earliest year (no prior period).

### Conditional threshold gate
```
1. Sort years chronologically.
2. Compute primary_metric for the MOST RECENT year.
3. If condition met (e.g., > 70): compute primary_metric for ALL years.
4. If condition NOT met: compute alternate_metric for ALL years instead.
```
> The metric names, threshold value, operator, and alternate metric **vary by task**.
> Always re-read the instruction for the exact values.
> If the task has **no** threshold gate, skip the condition check entirely.

---

## Phase 4 — Output

- Write to the specified path (default `/app/results.csv`).
- Use exact column names from the task instruction (e.g., `fiscal_year,gross_margin_pct`).
- One row per year, sorted chronologically.
- Values: `f"{value:.2f}"` — always 2 decimal places.
- Use `newline=""` in `open()` and `csv.writer` for clean line endings.
- **Verify**: `cat` the output; spot-check at least one row's arithmetic.

---

## Reference Inline Template

Adapt this pattern. Copy the entire template and change only the CONFIG section.
**Do not remove any parser** — the task may use CSV, JSON, HTML, or decorated text.

```python
import csv, json, re, os
from collections import defaultdict

# ── CONFIG (fill from task instruction — change ONLY these) ──────
DATA_DIR       = "/app/financials"          # from task
COMPANY        = "NVIDIA Corporation"       # from task
PRIMARY_METRIC = "gross_margin"             # metric name from the table above
ALT_METRIC     = "net_margin"               # alternate metric (if threshold not met)
THRESHOLD      = 70                         # threshold value; set None if no gate
THRESHOLD_OP   = ">"                        # one of: >, >=, <, <=, ==
OUTPUT_PATH    = "/app/results.csv"         # from task
YEAR_COL       = "fiscal_year"              # output column name for year
VALUE_COL      = "gross_margin_pct"         # output column name (primary metric)
ALT_VALUE_COL  = "net_margin_pct"           # output column name (alternate metric)
ROUNDING       = 2                          # decimal places
YOY_FIELD      = "revenue"                  # field for YoY growth (if metric is YoY)

# ── FIELD ALIASES ────────────────────────────────────────────────
ALIASES = {
    "revenue":"revenue","total revenue":"revenue","net revenue":"revenue",
    "sales":"revenue","net revenues":"revenue","total sales":"revenue",
    "gross profit":"gross_profit","grossprofit":"gross_profit",
    "cost of revenue":"cogs","cost of goods sold":"cogs","cogs":"cogs",
    "operating income":"operating_income","operatingincome":"operating_income",
    "operating profit":"operating_income","ebit":"operating_income",
    "income from operations":"operating_income",
    "net income":"net_income","netincome":"net_income",
    "net earnings":"net_income","net profit":"net_income",
    "shareholders equity":"shareholders_equity","shareholder equity":"shareholders_equity",
    "total equity":"shareholders_equity","stockholders equity":"shareholders_equity",
    "equity":"shareholders_equity","total stockholders equity":"shareholders_equity",
    "year":"year","fiscal year":"year","fiscalyear":"year","fy":"year","period":"year",
}
def norm(name):
    n = re.sub(r"[_\-]+"," ",name.strip().lower())
    n = re.sub(r"\s+"," ",n).strip()
    return ALIASES.get(n, ALIASES.get(n.replace(" ",""), n))

def parse_num(raw):
    if raw is None: return None
    s = str(raw).strip()
    if not s or s in ("-","N/A","n/a"): return None
    s = re.sub(r"[$€¥£]","",s)
    mult = 1.0
    for suf,m in [("T",1e12),("B",1e9),("M",1e6),("K",1e3)]:
        if s.upper().endswith(suf): mult=m; s=s[:-1]; break
    if "," in s and "." in s:
        if s.rfind(",")>s.rfind("."): s=s.replace(".","").replace(",",".")
        else: s=s.replace(",","")
    elif "," in s:
        parts=s.split(",")
        if len(parts)>2 or (len(parts)==2 and len(parts[1])==3): s=s.replace(",","")
        else: s=s.replace(",",".")
    try: return float(s.strip())*mult
    except: return None

# ── DISCOVERY (rejects log/cache files automatically) ────────────
def find_files(data_dir, company):
    found = []
    for root,_,files in os.walk(data_dir):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            try:
                txt = open(fp, encoding="utf-8", errors="replace").read()
            except: continue
            if company.lower() in txt.lower():
                low = txt.lower()
                if any(k in low for k in ["revenue","gross profit","net income","operating income","equity"]):
                    # Reject log/cache files: count [INFO]/[WARN]/[DATA] prefixed lines
                    log_lines = sum(1 for l in txt.splitlines()
                                    if re.match(r"^\[(INFO|WARN|DATA|ERROR|DEBUG)\]", l.strip()))
                    if log_lines > 2: continue
                    found.append((fp, txt))
    return found

# ── HEADER DETECTION ─────────────────────────────────────────────
def is_deco_line(s):
    t = s.strip()
    return (not t) or bool(re.match(r"^[=\-*#~]{3,}$", t))

def find_header_and_delim(text):
    """Return (header_index, delimiter, header_tokens) or None."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if is_deco_line(line): continue
        for delim in [",", "\t", ";"]:
            tokens = [t.strip() for t in line.split(delim)]
            if len(tokens) < 2: continue
            alpha = sum(1 for t in tokens if re.match(r"^[A-Za-z_ /()\-]+$", t))
            if alpha < len(tokens)*0.6: continue
            for j in range(i+1, len(lines)):
                if is_deco_line(lines[j]): continue
                nt = [t.strip() for t in lines[j].split(delim)]
                if not nt: continue
                nums = sum(1 for t in nt if re.match(r"^[\d.,$€¥£\-]+$", t))
                if nums >= len(nt)*0.3:
                    return i, delim, tokens
                break
    return None

# ── PARSERS (all three needed — do NOT remove any) ───────────────
def parse_delimited(text, header_idx, delim, headers):
    lines = text.splitlines()
    reader = csv.DictReader(lines[header_idx:], delimiter=delim)
    rows = []
    for row in reader:
        parsed = {}
        for k,v in row.items():
            if k is None: continue
            parsed[norm(k)] = v.strip() if v else ""
        yr = parsed.get("year","")
        if yr and not re.search(r"\d{4}", yr): continue
        if any(parsed.values()): rows.append(parsed)
    return rows

def parse_json(text):
    """Handles flat arrays, nested objects with array values, and arrays of objects."""
    try: data = json.loads(text)
    except: return []
    items = data if isinstance(data, list) else []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                items = v; break
    return [{norm(k):val for k,val in it.items()} for it in items if isinstance(it,dict)]

def parse_html(text):
    """Handles HTML tables, including those with merged headers or extra whitespace."""
    try:
        import pandas as pd
        dfs = pd.read_html(text)
        if dfs:
            df = dfs[0]; df.columns = [norm(str(c)) for c in df.columns]
            return df.to_dict("records")
    except: pass
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.DOTALL|re.IGNORECASE)
    if not rows_html: return []
    result, hdr = [], None
    for row in rows_html:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL|re.IGNORECASE)
        cells = [re.sub(r"<[^>]+>","",c).strip() for c in cells]
        if not cells: continue
        if hdr is None: hdr = [norm(c) for c in cells]
        else: result.append(dict(zip(hdr, cells)))
    return result

def parse_file(text):
    """Try all parsers, return first that yields rows with a year field."""
    hdr_info = find_header_and_delim(text)
    if hdr_info:
        idx, delim, headers = hdr_info
        rows = parse_delimited(text, idx, delim, headers)
        if rows: return rows
    rows = parse_json(text)
    if rows: return rows
    rows = parse_html(text)
    if rows: return rows
    return []

# ── EXTRACT & MERGE YEARLY DATA (supports multi-file joins) ─────
FIELDS = ["revenue","gross_profit","operating_income","net_income","shareholders_equity"]

def extract(rows):
    """Extract yearly records; merge duplicates by year (for multi-file joins)."""
    by_year = defaultdict(dict)
    for r in rows:
        yr = r.get("year","")
        if not yr or not re.search(r"\d{4}", str(yr)): continue
        yr = str(yr).strip()
        rec = by_year[yr]
        rec["year"] = yr
        for f in FIELDS:
            val = parse_num(r.get(f,""))
            if val is not None and f not in rec:
                rec[f] = val
    data = list(by_year.values())
    data.sort(key=lambda d: int(re.search(r"(\d{4})",d["year"]).group(1)))
    return data

# ── METRICS ──────────────────────────────────────────────────────
METRIC_DEF = {
    "gross_margin":      ("gross_profit",      "revenue"),
    "operating_margin":  ("operating_income",  "revenue"),
    "net_margin":        ("net_income",        "revenue"),
    "return_on_equity":  ("net_income",        "shareholders_equity"),
}
def calc(rec, metric):
    if metric in METRIC_DEF:
        num_f, den_f = METRIC_DEF[metric]
        n, d = rec.get(num_f), rec.get(den_f)
        if n is None or d is None or d == 0: return 0.0
        return round(n/d*100, ROUNDING)
    return None  # YoY handled separately

def calc_yoy(data, field):
    """Return list of (year, growth_pct) for consecutive years."""
    out = []
    for i in range(1, len(data)):
        prev = data[i-1].get(field); curr = data[i].get(field)
        if prev and curr and prev != 0:
            out.append((data[i]["year"], round((curr-prev)/prev*100, ROUNDING)))
    return out

# ── MAIN ─────────────────────────────────────────────────────────
files = find_files(DATA_DIR, COMPANY)
assert files, f"No file found for {COMPANY} in {DATA_DIR}"

all_rows = []
for fp, txt in files:
    all_rows.extend(parse_file(txt))
assert all_rows, "No data parsed"

data = extract(all_rows)
assert data, "No yearly data extracted"

# Determine which metric to compute
if THRESHOLD is not None:
    ops = {">":lambda a,b:a>b, ">=":lambda a,b:a>=b,
           "<":lambda a,b:a<b, "<=":lambda a,b:a<=b, "==":lambda a,b:a==b}
    recent_val = calc(data[-1], PRIMARY_METRIC)
    cond_met = ops[THRESHOLD_OP](recent_val, THRESHOLD)
    chosen_metric = PRIMARY_METRIC if cond_met else ALT_METRIC
    chosen_col    = VALUE_COL      if cond_met else ALT_VALUE_COL
else:
    chosen_metric = PRIMARY_METRIC
    chosen_col    = VALUE_COL

# Write output
os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
with open(OUTPUT_PATH, "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow([YEAR_COL, chosen_col])
    if chosen_metric == "year_over_year_growth":
        for yr, val in calc_yoy(data, YOY_FIELD):
            w.writerow([yr, f"{val:.{ROUNDING}f}"])
    else:
        for rec in data:
            v = calc(rec, chosen_metric)
            if v is not None:
                w.writerow([rec["year"], f"{v:.{ROUNDING}f}"])

# Verify
print(open(OUTPUT_PATH).read())
```

---

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Picking a title line as header (`"FINANCIAL DATA SUMMARY"`) | Require next content line to have numeric tokens |
| Using `startswith('FY')` to find data rows | Use generic: keep row if it contains a `\d{4}` token |
| Using a cache/log file as source | Template's `find_files` auto-rejects files with `[INFO]`/`[WARN]` lines |
| Wrong company | Verify exact company name or ticker in file content |
| Decimal vs percentage | If task says "72.72 means 72.72%", multiply by 100 |
| `\r\n` line endings in CSV | Always use `open(path, "w", newline="")` + `lineterminator="\n"` |
| Hardcoded delimiter | Auto-detect: try `,` then `\t` then `;` |
| Ignoring the conditional gate | Check threshold on most-recent year first; set `THRESHOLD=None` if no gate |
| Stripping JSON/HTML parsers | **Keep all three parsers** — data format varies across tasks |
| Multi-file data not joined | `extract()` merges records by year key across files |
| YoY growth returns zeros | Use `calc_yoy()` not `calc()` for `year_over_year_growth` |
