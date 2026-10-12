---
name: html-finance-verify
description: >
  Find the single incorrect metric in an HTML financial report by discovering
  internal consistency relationships among all reported values and identifying
  the one value that cannot participate in any valid relationship. Works across
  varied report structures, metric families (margins, growth rates, per-share
  values, totals), and error types (wrong dollar amounts, wrong percentages).
---

# HTML Financial Verification

## Task Family

Given an HTML financial report containing line-numbered metrics (dollar values
and/or percentages), exactly one reported value is incorrect. All other values
are internally consistent. Find the incorrect metric and report its line number
and value.

The error is always discoverable from **internal consistency** — no external
knowledge (market data, industry benchmarks, prior-period figures not in the
report) is needed.

## Core Algorithm

The solver operates in four phases. The key insight is that verification is
**bidirectional**: a value is "verified" if it participates in ANY valid
relationship — either as the computed result or as an input component.

### Phase 1: Generic HTML Parsing

Extract every (line_number, metric_name, numeric_value, is_percentage) tuple
from the HTML. Do not assume specific metric names, table positions, or column
orders. Use an HTML parser (stdlib `html.parser` or `beautifulsoup4`) — never
regex HTML.

**Parsing strategy:**
- Find all `<table>` elements, iterate over `<tr>` rows
- For each row with ≥3 cells, identify:
  - **Line number cell**: contains a pure integer (typically 2-4 digits)
  - **Value cell**: matches a numeric pattern (optional `$`, digits with commas/decimals, optional `%` or parentheses for negatives)
  - **Metric name cell**: the remaining text cell
- Handle negative values in parentheses: `(123.4)` → `-123.4`
- Strip `$`, `,`, `%` before converting to float

### Phase 2: Detect Rounding Precision

Examine the reported values to determine the implicit rounding precision.
For percentages, count decimal places in the raw string (e.g., `28.5%` → 1dp).
This determines the tolerance for matching: `tolerance = 0.5 × 10^(-precision)`.

For example, a value reported as `28.5%` could come from any true value in
[28.45%, 28.55%). Use this interval check, not exact equality.

### Phase 3: Discover All Valid Relationships

For every subset of values, check whether any relationship holds. Record each
valid relationship as a set of participating indices. Check these relationship
types in order of likelihood:

1. **Additive total**: `V = sum(subset)` — e.g., Total OpEx = R&D + S&M + G&A
   - Use `itertools.combinations` with max subset size 6 (financial statements
     rarely sum more than 5-6 items into a total)
   - Tolerance: 0.01 for dollar values

2. **Difference**: `V = A - B` — e.g., Gross Profit = Revenue - COGS
   - Check all ordered pairs
   - Tolerance: 0.01 for dollar values

3. **Simple ratio (percentage)**: `V ≈ A / B × 100` — e.g., Margin = Profit / Revenue × 100
   - Check all ordered pairs of dollar values
   - Tolerance: half the last displayed decimal place

4. **Direct ratio (per-share, multiples)**: `V ≈ A / B` — e.g., EPS = Net Income / Shares
   - Check all ordered pairs of values (dollar or count)
   - Tolerance: half the last displayed decimal place
   - This handles per-share values, unit economics, and other non-percentage ratios

5. **Growth rate**: `V ≈ (A - B) / B × 100` — e.g., YoY growth = (current - prior) / prior × 100
   - Check all ordered pairs
   - Same percentage tolerance

6. **Complementary percentages**: `V = 100 - other_pct` — e.g., cost ratio = 100 - margin

7. **Percentage-derived dollar**: `V = dollar × pct / 100` — e.g., tax expense = pre-tax income × tax rate
   - Only check for dollar values not yet verified

**Critical: mark ALL participants as verified.** When you find that
`line_170 = line_140 + line_150 + line_160`, add indices 140, 150, 160, AND
170 to the verified set. Leaf values (atomic inputs like individual expense
items) are verified by participating as components, even though they cannot be
derived from other values.

### Phase 4: Identify the Error

The error is the single value that appears in **no** valid relationship.
- If exactly one value is unverifiable → that's the answer
- If zero values are unverifiable → all values are consistent (check for
  precision/tolerance issues)
- If multiple values are unverifiable → the report may have a more complex
  structure; re-examine relationship types or parsing

## Output Format

Write `line_number,value` to the specified output file (typically `/app/value.txt`).
- `line_number`: the integer shown in the report next to the incorrect metric
- `value`: the incorrect numeric value **as displayed** (without `%` or `$` signs)
- **Preserve the original decimal representation from the HTML** — do not convert through float and back to string
  - `60.80%` → output `60.80` (not `60.8`)
  - `60.0%` → output `60.0` (not `60`)
  - `$1,234.5` → output `1234.5`
  - `(50.0)` → output `-50.0`

**Implementation:** Use the raw string extracted during parsing. Strip `$`, `,`, `%`, and handle parentheses for negatives. Do not use `float()` → `str()` conversion, which loses trailing zeros.

## Robustness Considerations

### Variant: Different report structures
- Multiple tables, sidebar panels, different column orders
- Solution: parse ALL tables generically; identify cells by content pattern, not position

### Variant: Different metric families
- YoY changes, per-share values, unit conversions, subtotals
- Solution: the relationship discovery phase checks ratio and growth patterns
  in addition to additive patterns

### Variant: Error is a dollar value, not a percentage
- The algorithm doesn't assume which type is wrong; it finds the value that
  can't participate in any relationship regardless of type

### Variant: Different rounding precision
- Detect precision from the data itself; use interval-based tolerance

### Variant: Large number of values
- Subset enumeration is bounded by max subset size (6) and is fast for
  typical financial reports (10-20 values)

## Operational Instructions

**Before running the solver:**
1. Read `task.yaml` from the host workspace (not inside `/app/`) to determine:
   - The output file path (typically `/app/value.txt`)
   - Any specific formatting requirements

2. **Get solve.py into /app/** — the skill directory is outside the container, so you cannot run it directly. Two options:
   - **Option A (recommended):** Read `solve.py` with the `read` tool, then write it into `/app/solve.py` using `task_shell` with a heredoc:
     ```bash
     cat > /app/solve.py << 'PYEOF'
     <paste solve.py content here>
     PYEOF
     python3 /app/solve.py
     ```
   - **Option B:** If the skill is mounted at `/skill` inside the container, run `python3 /skill/solve.py` directly.

3. The solver auto-discovers the HTML file in `/app/` and writes the answer to `/app/value.txt`.

**If the solver reports multiple unverifiable values:**
- Re-examine the HTML for additional relationship types not covered
- Check if some values use different units (thousands vs millions)
- Verify the parsing captured all tables and metrics correctly

## Reference Implementation

See `solve.py` in this skill directory for a complete Python implementation
using only stdlib (`html.parser`, `itertools`). The script:
1. Auto-discovers HTML files in `/app/`
2. Parses all tables generically
3. Finds all additive, difference, ratio, growth, complement, and per-share relationships
4. Marks all participants as verified
5. Reports the single unverifiable value
6. Writes `line_number,value` to `/app/value.txt`

## Worked Example (v01)

Report: Ridgeway Robotics Q2 earnings with 10 dollar values and 3 KPI percentages.

Relationships discovered:
- Revenue (842.0) = COGS (321.6) + Gross Profit (520.4) ✓
- Total OpEx (280.6) = R&D (129.7) + S&M (96.8) + G&A (54.1) ✓
- Operating Income (239.8) = Gross Profit (520.4) - Total OpEx (280.6) ✓
- Net Income (251.0) = Operating Income (239.8) + Other Income (11.2) ✓
- Operating Margin (28.5%) = Operating Income (239.8) / Revenue (842.0) × 100 ✓
- Net Margin (29.8%) = Net Income (251.0) / Revenue (842.0) × 100 ✓

Gross Margin (60.8%) cannot be derived from any pair:
- 520.4 / 842.0 × 100 = 61.8%, not 60.8%

Answer: `210,60.8`
