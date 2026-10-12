---
name: html-finance-verify
description: >
  Verify internal consistency of an HTML financial report to find the single
  incorrect metric. Parse line-numbered financial values from HTML tables,
  classify metrics using keyword matching, discover arithmetic (additive) and
  ratio relationships, compute expected values for each metric from all
  relationships that constrain it, and identify the one value whose reported
  number disagrees with its expected value. Write line_number,value to the
  output file. Handles varied table structures, metric families, numeric
  formats (dollars, percentages, commas, negatives), and relationship types
  (additive identities, margins, per-share, YoY changes, balance sheet ratios).
---

# HTML Finance Verify

## Quick Start

**Run the complete solver:**
```bash
python3 /skill/solve.py
```

This executable script implements the full algorithm and handles all edge cases. The detailed explanation below is for understanding the approach and debugging.

## Task Summary

Given an HTML financial report containing line-numbered metrics, exactly one
reported value is incorrect while all others are internally consistent. Find
the incorrect metric and write `line_number,value` to the specified output file.

## Algorithm Overview

The solver proceeds in six phases:

1. **Parse** the HTML to extract (line_number, metric_name, value) triples
2. **Classify** each metric using keyword matching into financial categories
3. **Discover relationships** — additive subsets among dollar values (tight
   and wide tolerance) and keyword-guided ratio relationships for percentages
4. **Compute expected values** for each metric from every relationship that
   constrains it
5. **Identify the error** using relative consensus clustering: the metric
   whose expected values form a consensus cluster that disagrees with the
   reported value (using relative, not absolute, tolerance)
6. **Output** the line number and displayed value

## Phase 1: HTML Parsing

Find the HTML file in `/app/` (typically named with `earnings`, `report`,
`financial`, or `statement`). Parse all `<table>` elements, skipping `<thead>`
rows. Each `<tbody>` row with ≥3 cells should contain a line number, a metric
name, and a numeric value.

```python
from html.parser import HTMLParser

class TableParser(HTMLParser):
    """Extract table rows from HTML, skipping thead."""
    def __init__(self):
        super().__init__()
        self.tables = []; self.current_table = []
        self.current_row = []; self.current_cell = ""
        self.in_td = False; self.in_table = False; self.in_thead = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table": self.in_table = True; self.current_table = []
        elif tag == "thead": self.in_thead = True
        elif tag == "tbody": self.in_thead = False
        elif tag == "tr" and self.in_table: self.current_row = []
        elif tag in ("td", "th") and self.in_table:
            self.in_td = True; self.current_cell = ""

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td","th") and self.in_td:
            self.in_td = False; self.current_row.append(self.current_cell.strip())
        elif tag == "tr" and self.in_table and self.current_row:
            if not self.in_thead: self.current_table.append(self.current_row)
            self.current_row = []
        elif tag == "table":
            self.in_table = False
            if self.current_table: self.tables.append(self.current_table)
            self.current_table = []
        elif tag == "thead": self.in_thead = False

    def handle_data(self, data):
        if self.in_td: self.current_cell += data
```

For each row, identify:
- **Line number**: a cell matching `^\d{2,4}$`
- **Value**: a cell parseable as a number (may include `$`, `%`, commas)
- **Name**: remaining non-empty cells joined

Track whether the raw value string contains `%` to classify as percentage.

### Value Parsing

```python
def parse_number(s):
    """Parse financial value string to float. Returns None for non-numeric."""
    s = s.strip().replace('$','').replace(',','').replace('%','').strip()
    if s.startswith('(') and s.endswith(')'): s = '-' + s[1:-1]
    s = s.strip()
    if not s or s in ('—', '-', 'N/A', 'nm', 'n/a'): return None
    try:
        return float(s)
    except ValueError:
        return None

def extract_display_value(s):
    """Get numeric part for output (strip $ and %)."""
    s = s.strip().replace('$','').replace(',','').strip()
    if s.endswith('%'): s = s[:-1].strip()
    if s.startswith('(') and s.endswith(')'): s = '-' + s[1:-1]
    return s.strip()
```

## Phase 2: Metric Classification

Classify each metric by keyword matching its name into financial categories.
This drives relationship discovery in Phase 3.

```python
def classify_metric(name):
    n = name.lower()
    cats = set()
    # Income statement items - check specific before general
    if any(w in n for w in ['cost of revenue','cost of goods','cogs','cost of sales']):
        cats.add('cogs')
    elif any(w in n for w in ['revenue','sales','total revenue','net revenue']):
        # Exclude expense categories that contain 'sales'
        if 'cost' not in n and 'marketing' not in n and 'expense' not in n:
            cats.add('revenue')
    if 'gross profit' in n: cats.add('gross_profit')
    if any(w in n for w in ['research','r&d']): cats.add('rd_expense')
    if any(w in n for w in ['sales and marketing','selling','s&m']): cats.add('sm_expense')
    if any(w in n for w in ['general and administrative','g&a']): cats.add('ga_expense')
    if any(w in n for w in ['total operating expense','total opex']): cats.add('total_opex')
    if any(w in n for w in ['operating income','operating profit','ebit']):
        if 'margin' not in n: cats.add('operating_income')
    if any(w in n for w in ['other income','interest income']): cats.add('other_income')
    if any(w in n for w in ['net income','net profit','net earnings']):
        if 'margin' not in n: cats.add('net_income')
    if any(w in n for w in ['income tax','tax provision']): cats.add('tax')
    if any(w in n for w in ['pre-tax','pretax','before tax']): cats.add('pretax_income')
    if 'ebitda' in n and 'margin' not in n: cats.add('ebitda')
    # Per-share
    if any(w in n for w in ['eps','earnings per share']): cats.add('eps')
    if any(w in n for w in ['shares','share count','diluted','basic']):
        if 'price' not in n: cats.add('shares')
    # Margin percentages
    if 'gross margin' in n: cats.add('gross_margin_pct')
    if 'operating margin' in n: cats.add('operating_margin_pct')
    if 'net margin' in n: cats.add('net_margin_pct')
    if 'margin' in n and not cats: cats.add('margin_pct')
    # Growth / YoY
    if any(w in n for w in ['yoy','year-over-year','year over year']): cats.add('yoy_change')
    # Balance sheet items
    if any(w in n for w in ['total current asset']): cats.add('current_assets')
    if any(w in n for w in ['total current liab']): cats.add('current_liabilities')
    if any(w in n for w in ['total asset']): cats.add('total_assets')
    if any(w in n for w in ['total liab','total debt']): cats.add('total_liabilities')
    if any(w in n for w in ['total equity',"stockholders' equity","shareholders' equity"]):
        cats.add('total_equity')
    if any(w in n for w in ['cash','cash equivalent']): cats.add('cash')
    if any(w in n for w in ['inventory']): cats.add('inventory')
    if any(w in n for w in ['receivable']): cats.add('receivables')
    if any(w in n for w in ['payable']): cats.add('payables')
    if any(w in n for w in ['capex','capital expenditure']): cats.add('capex')
    if any(w in n for w in ['operating cash flow','cash from operations']): cats.add('operating_cf')
    if any(w in n for w in ['free cash flow','fcf']): cats.add('fcf')
    if any(w in n for w in ['depreciation','amortization']): cats.add('da')
    if any(w in n for w in ['retained earnings']): cats.add('retained_earnings')
    if any(w in n for w in ['dividend']): cats.add('dividend')
    if any(w in n for w in ['goodwill']): cats.add('goodwill')
    if any(w in n for w in ['working capital']): cats.add('working_capital')
    # Financial ratios
    if any(w in n for w in ['current ratio']): cats.add('current_ratio')
    if any(w in n for w in ['debt-to-equity','debt to equity']): cats.add('debt_to_equity')
    if any(w in n for w in ['return on equity','roe']): cats.add('roe')
    if any(w in n for w in ['return on asset','roa']): cats.add('roa')
    if not cats: cats.add('unknown')
    return cats
```

## Phase 3: Relationship Discovery

### Additive Relationships (Dollar Values)

Try all subsets of dollar-valued metrics to find sums:

```python
import itertools

dollar_lines = [l for l, ... in metrics if not is_percentage]

for target_line in dollar_lines:
    target = val_map[target_line]
    candidates = [l for l in dollar_lines if l != target_line]
    for size in range(2, min(len(candidates)+1, 7)):
        for subset in itertools.combinations(candidates, size):
            if abs(sum(val_map[l] for l in subset) - target) < 0.15:
                relations.append(('sum', list(subset), target_line))
```

Tolerance 0.15 handles rounding to 1 decimal place.

### Wide-Tolerance Additive Discovery (Fallback)

When the error is in a **non-hub dollar value** (e.g., R&D expense), the tight
additive relationships involving it won't be discovered because the sum doesn't
hold. Run a second pass with **wide tolerance** (5% of the target value) to find
approximate relationships. **Limit to subsets of size 2-3** to reduce noise.

```python
for target_line in dollar_lines:
    target = val_map[target_line]
    wide_tol = abs(target) * 0.05  # 5% relative tolerance
    candidates = [l for l in dollar_lines if l != target_line]
    for size in range(2, min(4, len(candidates)+1)):  # Only size 2-3
        for subset in itertools.combinations(candidates, size):
            s = sum(val_map[l] for l in subset)
            diff = abs(s - target)
            if 0.15 < diff <= wide_tol:  # wide but not tight
                wide_relations.append(('sum_wide', list(subset), target_line))
```

These wide relationships are used only in Phase 4 expected-value computation
as additional evidence, not in Phase 3 tight relationship tracking.

### Ratio Relationships (Percentages)

Use keyword-based templates to match percentage metrics to their
numerator/denominator pairs:

```python
ratio_templates = [
    # (percentage_category, [numerator_categories], [denominator_categories])
    ('gross_margin_pct',      ['gross_profit'],              ['revenue']),
    ('operating_margin_pct',  ['operating_income'],          ['revenue']),
    ('net_margin_pct',        ['net_income'],                ['revenue']),
    ('ebitda_margin_pct',     ['ebitda'],                    ['revenue']),
    ('margin_pct',            ['gross_profit','operating_income',
                               'net_income','ebitda'],       ['revenue']),
    ('eps',                   ['net_income'],                ['shares']),
    ('current_ratio',         ['current_assets'],            ['current_liabilities']),
    ('debt_to_equity',        ['total_liabilities'],         ['total_equity']),
    ('roe',                   ['net_income'],                ['total_equity']),
    ('roa',                   ['net_income'],                ['total_assets']),
]
```

For each template, find matching lines and check if the ratio holds within
a discovery tolerance of ~2.0 (wide, to catch the erroneous value too).

For percentages: `expected = numerator / denominator * 100`
For non-percentage ratios (EPS, current_ratio, etc.): `expected = numerator / denominator`

### Fallback for Unmatched Percentages

If a percentage metric has no keyword match, try all dollar/dollar pairs and
pick the closest match within tolerance 1.5.

## Phase 4: Expected Value Computation

**Critical**: Store tight and wide expected values in **separate dictionaries**.
Mixing them dilutes consensus fractions and prevents detection of dollar-value errors.

```python
expected_tight = {l: [] for l in all_lines}
expected_wide = {l: [] for l in all_lines}
```

For each metric line L, compute what its value SHOULD be from every
relationship involving it:

**Tight sum relationships:**
- If L is the target: `expected_tight[L].append(sum(parts))`
- If L is a part: `expected_tight[L].append(target - sum(other_parts))`

**Tight ratio relationships (num/den = pct):**
- If L is pct: `expected_tight[L].append(num / den * 100)`
- If L is num: `expected_tight[L].append(pct * den / 100)`
- If L is den: `expected_tight[L].append(num / (pct / 100))`

**Wide sum relationships** (stored separately):
- If L is the target: `expected_wide[L].append(sum(parts))`
- If L is a part: `expected_wide[L].append(target - sum(other_parts))`

**Why separation matters**: A dollar line might have 3 tight expected values
(all correct, all agreeing) and 20 wide expected values (mostly spurious).
If mixed, consensus cluster contains only 3/23 values → frac=0.13 → filtered out
→ error missed. With separation, tight consensus gives frac=3/3=1.0 → detected.

## Phase 5: Error Identification (Relative Consensus Clustering)

**Critical**: Use *relative* tolerance, not absolute. Financial values span
orders of magnitude — a spread of 1.0 is negligible for Revenue ($1,200M) but
significant for a margin (60.8%).

### Step 1: Consensus Clustering

For each line, find the largest cluster of expected values that agree within
a relative tolerance:

```python
def find_consensus(expected_values, rel_tol=0.005):
    """Find the largest cluster of agreeing expected values.
    rel_tol: relative tolerance (e.g., 0.005 = 0.5%)."""
    if not expected_values:
        return None, 0, 0
    vals = sorted(expected_values)
    best_cluster = []
    for pivot in vals:
        cluster = [v for v in vals
                   if abs(v - pivot) / max(abs(pivot), 0.001) <= rel_tol]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster
    consensus = sorted(best_cluster)[len(best_cluster)//2]  # median
    consensus_frac = len(best_cluster) / len(vals)
    return consensus, consensus_frac, len(best_cluster)
```

### Step 2: Score Each Line

For each line, compute consensus from **tight expected values only**:

```python
candidates = []
for line in all_lines:
    # Primary: consensus from tight relationships only
    if expected_tight[line]:
        consensus, frac, count = find_consensus(expected_tight[line])
        tight_count = len(expected_tight[line])
    else:
        # No tight relations — try wide as last resort
        if not expected_wide[line]:
            continue
        consensus, frac, count = find_consensus(expected_wide[line])
        if consensus is None:
            continue
        frac *= 0.5  # penalize wide-only consensus
        tight_count = 0
    
    if consensus is None:
        continue
    
    diff = abs(consensus - reported[line])
    rel_diff = diff / max(abs(reported[line]), 0.001)

    # The error has: high consensus fraction + high relative diff
    if frac >= 0.5 and rel_diff > 0.005:  # >0.5% relative error
        # Score: consensus strength × disagreement magnitude × tight constraint count
        score = frac * rel_diff * max(tight_count, 1)
        candidates.append((score, rel_diff, line, consensus, frac, tight_count))
```

### Step 3: Select the Error

Sort candidates by score descending. The top candidate is the error.

**Disambiguation rule**: When multiple candidates pass the consensus check,
prefer the one with:
1. Higher consensus fraction (more expected values agree)
2. More constraining relationships (higher count)
3. Higher relative difference from consensus

A hub value with 3 consistent expected values disagreeing with reported is
more likely the error than a leaf value with 1 expected value disagreeing.

### Why Absolute Tolerance Fails (and Relative Works)

**Failure scenario**: Revenue reported as $1,200M (true: $1,253.5M). Three
margins give expected revenue: [1254.2, 1253.5, 1253.1].
- Absolute range = 1.05 → fails `exp_range < 0.5` threshold
- Relative range = 0.084% → passes `rel_tol = 0.5%` threshold ✓

**v01 scenario**: Gross margin reported as 60.8% (true: 61.8%).
- Line 210 expected: [61.81] → consensus=61.81, rel_diff=1.66% → IS the error ✓
- Line 110 (Revenue) expected: [842.0, 842.0, 842.0, 855.9, 841.4, 842.3]
  - Consensus cluster: [842.0, 842.0, 842.0, 841.4, 842.3] (5/6)
  - Consensus=842.0 matches reported → NOT the error ✓

### Fallback Strategies

If no clear error is found via consensus clustering:
1. **Wide-tolerance additive**: Use expected values from wide-tolerance
   relationships (Phase 3 supplement) to find candidates
2. **Violation counting**: Count violated tight relationships per line;
   among lines with violations, prefer those with fewest total relationships
3. **Brute-force leave-one-out**: For each line, check if removing it makes
   all tight relationships consistent

## Phase 6: Output

Read the task instructions to determine:
- Output file path (default: `/app/value.txt`)
- Format (default: `line_number,value`)
- Whether to include `%`, `$`, commas, etc.

The `value` is the **incorrect value as displayed** in the report.

```python
with open(output_file, 'w') as f:
    f.write(f"{error_line},{error_display}\n")
```

## Handling Variants

### Report Structure Variations
- Tables may have different column orders
- Multiple tables or sections (Income Statement, Balance Sheet, Cash Flow)
- Different section names and metric families
- Line numbers may use different numbering schemes

### Error Type Variations
- Error may be in a dollar value (not just a percentage)
- May involve YoY calculations, per-share values, growth rates
- May involve unit conversions (thousands vs millions)
- Rounding to different decimal places

### Output Format Variations
- Output file path may differ
- May need different precision
- May or may not include `%`, `$`, commas
- Read task instructions carefully

## Key Principles

1. **Internal consistency only**: Error is always discoverable from
   relationships among reported values, never requiring external data.
2. **Exactly one error**: One incorrect metric; all others are consistent.
3. **Rounding tolerance**: Use ~0.15 for 1-decimal-place additive checks.
4. **Report the displayed value**: Output the wrong value as shown, not corrected.
5. **Keyword-guided ratios**: Avoid spurious ratio relationships by using
   metric name classification to identify meaningful numerator/denominator pairs.
6. **Relative tolerance, not absolute**: Financial values span orders of
   magnitude. A spread of 1.0 is negligible for Revenue ($1,200M) but
   significant for a margin (60.8%). Always use relative (percentage-based)
   tolerance for consensus clustering.
7. **Consensus clustering for disambiguation**: When multiple candidates
   could be the error, use the agreement pattern of expected values (consensus
   fraction × relative difference × constraint count) to identify the true error.
8. **Hub vs. leaf awareness**: Hub metrics (Revenue, Net Income) participate
   in many relationships; errors there produce multiple consistent expected
   values. Leaf metrics (individual expenses) participate in fewer; use
   wide-tolerance discovery to catch errors in leaf values.

## Complete Solver Template

```python
#!/usr/bin/env python3
"""HTML Finance Verify - General Solver"""
import re, sys, glob, itertools
from html.parser import HTMLParser

# 1. Find HTML file
html_files = glob.glob('/app/*.html')
html_file = html_files[0]
output_file = '/app/value.txt'

# 2. Parse HTML (TableParser class as above)
# 3. Extract metrics with line numbers, names, values
# 4. Classify metrics using keyword matching
# 5. Discover relationships:
#    a. Tight additive (tolerance 0.15)
#    b. Wide additive (tolerance 5% of target) for fallback
#    c. Keyword-guided ratio relationships
#    d. Fallback brute-force ratios for unmatched percentages
# 6. Compute expected values for each line from all relationships
# 7. Identify error using relative consensus clustering:
#    a. find_consensus(expected_values, rel_tol=0.005)
#    b. Score = consensus_frac * rel_diff * count
#    c. Pick highest-scoring candidate
# 8. Write output: line_number,displayed_value

# See phases 1-6 above for implementation details.
```

## Debugging Tips

1. **No relationships found**: Check value parsing; ensure line numbers are
   being extracted correctly
2. **Too many spurious ratios**: Tighten keyword matching; verify classification
3. **Multiple candidates pass consensus**: Use consensus fraction × rel_diff ×
   count scoring to disambiguate; hub metrics with more constraints win ties
4. **Error not found with tight tolerance**: Check wide-tolerance additive
   discovery; check for unit mismatches (thousands vs millions)
5. **Hub-value error missed**: Verify relative consensus clustering is used
   (not absolute range); the expected values from different ratios may have
   absolute spread > 0.5 but relative spread < 0.5%
6. **Leaf-value error missed**: Verify wide-tolerance additive pass is running;
   tight tolerance won't discover relationships involving the erroneous leaf
7. **Always print intermediate results**: metrics, classifications,
   relationships, expected values, consensus clusters, and scoring
