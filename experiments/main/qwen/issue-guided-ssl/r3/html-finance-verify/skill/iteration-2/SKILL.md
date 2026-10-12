---
name: html-finance-verify
description: >
  Methodology and tooling for verifying HTML financial reports by extracting
  all line-numbered metrics, separating dollar values from percentages, and
  identifying the single incorrect percentage through systematic cross-checking
  against internally-consistent dollar-denominated values. Works on any HTML
  report structure with line-numbered financial data and one wrong KPI percentage.
---

# HTML Financial Verification Skill

## Family Invariants (what every variant shares)

1. An HTML document containing a financial report with **line-numbered** metrics
2. All dollar-denominated values are **internally consistent** (they satisfy accounting relationships)
3. Exactly **one** displayed percentage/KPI is **incorrect** (fails ratio cross-checks)
4. The answer is the report's own line number and the incorrect value as displayed

## Methodology: Parse → Classify → Cross-Check → Report

### Step 1: Parse — Extract All Line-Numbered Metrics from HTML

- Iterate all `<tr>` rows in the HTML document
- For each row, extract text content of all `<td>` cells
- Identify the **report line number** (an integer typically 1–5 digits, shown in the report — NOT a source file line number)
- Identify the **metric label** (text like "Revenue", "Gross margin")
- Identify the **value** and its type (dollar or percentage)
- Use regex-based extraction; do NOT assume specific CSS class names

### Step 2: Classify — Separate Dollars from Percentages

- **Dollar values**: match patterns like `$842.0`, `$1,234.5M`, `$(50.2)`, `$129.7`
  - Strip `$`, commas, trailing magnitude suffixes (M/B/K)
  - Handle parenthesized negatives: `(50.2)` → `-50.2`
- **Percentage values**: match patterns like `60.8%`, `28.5 %`
  - Extract the numeric part before `%`

### Step 3: Cross-Check — Verify Ratio Relationships

For each percentage `p` with value `v`:
- Try every ordered pair of dollar values `(d_i, d_j)` where `d_j ≠ 0`
- Compute `expected = (d_i / d_j) × 100`
- Round `expected` to 1 decimal place
- If `|v - round(expected, 1)| < tolerance` → this percentage matches a valid ratio ✓
- **The incorrect percentage is the one that matches NO valid ratio**

Also verify dollar-value internal consistency (structure-agnostic):
- For each dollar value, check if it equals the sum/difference of a subset of other dollar values
- Check subsets of size 2 and 3 (covers most financial statement relationships)
- All dollar values should be mutually consistent (per the spec)
- No hardcoded label names — works with any metric naming scheme

### Step 4: Report — Write the Answer

Output format: `line_number,value`
- `line_number`: the report's displayed line number for the incorrect metric
- `value`: the incorrect numeric value as shown (without `%` sign)

## Key Design Principles

- **Never hardcode** specific values, labels, line numbers, or company names
- **Tolerance**: Use 0.15 for rounding differences (values rounded to 1 decimal)
- **Comma handling**: Strip commas from values like `$1,234.5`
- **Negative handling**: Support `(value)` notation and `-` prefix
- **Magnitude suffixes**: Strip M/B/K suffixes (ratios are scale-invariant)
- **Multiple sections**: Parse all tables in the document
- **No external dependencies**: Use only Python stdlib (re, html.parser)
- **Auto-discovery**: Script finds HTML files automatically if no path given
- **Container path**: Script is at `/skill/scripts/verify_report.py` inside the container

## Script

The included `scripts/verify_report.py` implements this methodology generically.

### How to invoke inside the /app container

The skill package is mounted read-only at `/skill/` inside the task container.
To run the verifier:

```bash
python3 /skill/scripts/verify_report.py [html_file_path] [output_file_path]
```

**Defaults:**
- `html_file_path`: auto-discovered (first `.html` file in `/app/`, or `/app/q2_earnings_report.html`)
- `output_file_path`: `/app/value.txt`

**Examples:**
```bash
# Auto-discover HTML and write to /app/value.txt
python3 /skill/scripts/verify_report.py

# Specify HTML file explicitly
python3 /skill/scripts/verify_report.py /app/earnings_report.html

# Specify both input and output
python3 /skill/scripts/verify_report.py /app/report.html /app/value.txt
```

**Important:** The script path is `/skill/scripts/verify_report.py` (inside the container),
NOT the host workspace path. The host workspace path is not accessible from inside `/app/`.

## Common Financial Relationships

See `references/accounting_relationships.md` for the standard ratio relationships
used in financial verification (margins, growth rates, per-share metrics, etc.).
