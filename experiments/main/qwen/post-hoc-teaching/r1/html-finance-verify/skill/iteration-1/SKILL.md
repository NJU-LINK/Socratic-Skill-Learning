---
name: html-finance-verify
description: >
  Verify internal consistency of HTML financial reports containing line-numbered
  metrics. Parse the HTML to extract all reported values with their line numbers,
  identify arithmetic and ratio relationships between metrics, find the single
  incorrect metric by cross-checking all relationships, and output the answer in
  the required format.
---

# HTML Finance Verify

## Task Overview

Given an HTML financial report (e.g., earnings snapshot, income statement, KPI
dashboard) containing line-numbered metrics, find the **single incorrect metric**
by verifying internal consistency of all reported values. Output the line number
and incorrect value.

## General Approach

### Step 1: Parse the HTML and Extract All Metrics

Use Python with `html.parser` or `re` to extract every (line_number, metric_name,
value) tuple from the HTML. Key extraction rules:

- Line numbers appear in dedicated cells/spans (often class `line` or similar)
- Metric names are text labels (e.g., "Revenue", "Gross margin")
- Values are numeric, possibly with `$`, `%`, `,`, or negative signs
- Strip all formatting: remove `$`, `%`, `,`, whitespace before converting to float
- Handle both positive and negative numbers, decimals, and percentages

```python
import re
from html.parser import HTMLParser

def extract_metrics(html_content):
    """Extract all (line_number, metric_name, raw_value_string) from HTML."""
    metrics = []
    # Pattern: find table rows with line number, metric name, and value
    # Adapt regex based on actual HTML structure
    rows = re.findall(
        r'<tr[^>]*>.*?<td[^>]*class="line"[^>]*>(\d+)</td>\s*'
        r'<td[^>]*>([^<]+)</td>\s*'
        r'<td[^>]*class="num"[^>]*>([^<]+)</td>',
        html_content, re.DOTALL
    )
    for line_num, name, raw_val in rows:
        clean_val = raw_val.strip().replace('$', '').replace(',', '').replace('%', '')
        metrics.append({
            'line': int(line_num),
            'name': name.strip(),
            'raw_value': raw_val.strip(),
            'value': float(clean_val)
        })
    return metrics
```

### Step 2: Classify Metrics and Identify Relationships

Financial reports contain several types of metrics with predictable relationships:

#### A. Additive Relationships (Income Statement)

Standard income statement flows:
- **Gross profit** = Revenue − Cost of revenue
- **Total operating expenses** = Sum of all OpEx line items (R&D, S&M, G&A, etc.)
- **Operating income** = Gross profit − Total operating expenses
- **Pretax income** = Operating income + Other income/expense items
- **Net income** = Pretax income − Income tax (or Pretax + Other items)

Detection strategy:
1. Build a map of metric_name → value
2. For each "total" or "subtotal" metric, identify its components by name
3. Verify: total ≈ sum(components) within rounding tolerance (±0.15 for values
   rounded to 1 decimal)

#### B. Ratio/Percentage Relationships (KPIs)

Common margin and per-unit calculations:
- **Gross margin** = Gross profit / Revenue × 100
- **Operating margin** = Operating income / Revenue × 100
- **Net margin** = Net income / Revenue × 100
- **EPS** = Net income / Shares outstanding
- **YoY growth** = (Current − Prior) / |Prior| × 100
- **R&D as % of revenue** = R&D / Revenue × 100

Detection strategy:
1. Identify percentage metrics (those with `%` in raw value or "margin"/"rate"
   in name)
2. Identify the base value (usually Revenue for margins)
3. Compute expected percentage and compare to reported value
4. Use tolerance of ±0.15 percentage points for rounded values

#### C. Cross-Section Relationships

Sometimes metrics span sections:
- A KPI sidebar references income statement values
- Notes reference line items
- Per-share values reference aggregate values

### Step 3: Constraint-Based Single-Fault Localization

**Critical insight**: Don't use heuristics like "if ratio violation, the ratio is wrong." Instead, use constraint satisfaction: for each suspect metric S, test whether S being the ONLY wrong value is consistent with all observed check results.

**Key theorem**: If S is the only wrong metric, then:
- ALL checks involving S must FAIL (S's wrong value propagates to every check it participates in)
- ALL checks NOT involving S must PASS (they're independent of S)

This distinguishes the error from metrics that merely participate in a failing check as inputs. For example, if Gross margin is wrong, Revenue participates in the failing ratio check but also participates in PASSING additive checks — proving Revenue is correct.

```python
def find_incorrect_metric(metrics):
    """
    Constraint-based single-fault localization.
    
    For each candidate S:
    - involving_pass: checks involving S that pass
    - involving_fail: checks involving S that fail
    - unrelated_pass: checks NOT involving S that pass
    - unrelated_fail: checks NOT involving S that fail
    
    S is the error if:
    1. unrelated_fail == 0 (all independent checks pass)
    2. involving_fail > 0 (at least one check involving S fails)
    3. involving_pass == 0 (all checks involving S fail)
    """
    checks = gather_all_checks(metrics)  # Each check: (desc, participants, result_line, passes)
    
    failing = [c for c in checks if not c.passes]
    passing = [c for c in checks if c.passes]
    
    if not failing:
        return exhaustive_search(metrics)
    
    # Collect all lines involved in any check
    all_lines = set()
    for check in checks:
        all_lines.update(check.participants)
    
    # For each candidate, classify checks
    for suspect_line in sorted(all_lines):
        involving_pass = sum(1 for c in passing if suspect_line in c.participants)
        involving_fail = sum(1 for c in failing if suspect_line in c.participants)
        unrelated_fail = sum(1 for c in failing if suspect_line not in c.participants)
        
        # Strict single-fault: no unrelated failures, all involving checks fail
        if unrelated_fail == 0 and involving_fail > 0 and involving_pass == 0:
            return find_metric_by_line(metrics, suspect_line)
    
    # Relaxed: allow involving passes (for edge cases)
    for suspect_line in sorted(all_lines):
        involving_fail = sum(1 for c in failing if suspect_line in c.participants)
        unrelated_fail = sum(1 for c in failing if suspect_line not in c.participants)
        
        if unrelated_fail == 0 and involving_fail > 0:
            return find_metric_by_line(metrics, suspect_line)
    
    # Fallback: weighted vote
    return fallback_localization(metrics, checks)
```

### Step 4: Why Constraint Satisfaction Beats Heuristics

**Common mistake**: Assuming "ratio violation → ratio metric is wrong" or "additive violation → total is wrong."

**Why this fails**: Consider a variant where "Total operating expenses" is reported as $285.6 instead of $280.6. This causes:
1. Additive check: R&D + S&M + G&A vs Total OpEx → FAILS
2. Additive check: Gross profit − Total OpEx vs Operating income → FAILS (propagation)
3. Ratio check: Operating margin → might FAIL if Operating income also wrong

A heuristic solver sees ratio violations and returns the margin percentage — but the root cause is the dollar value "Total operating expenses."

**Constraint satisfaction handles this correctly**:
- If Total OpEx is wrong, ALL checks involving it fail (both additive checks)
- If Operating margin is wrong, only the ratio check fails, but the additive checks pass
- The algorithm identifies Total OpEx as the unique metric where all involving checks fail and no unrelated checks fail

**Key principle**: The error metric is the one whose wrong value explains ALL failures without causing any independent checks to fail.

### Step 5: Output the Answer

Read the task instructions carefully for the exact output format. Common patterns:

- `line_number,value` → e.g., `210,60.8`
- Value is the **incorrect value as shown** (not the corrected value)
- No percent sign, no dollar sign, no commas in the output value
- Write to the specified file (e.g., `/app/value.txt`)

```python
# Example output
with open('/app/value.txt', 'w') as f:
    f.write(f"{error_line},{error_value}")
```

## Robust Parsing Strategies

### Handling Varied HTML Structures

The HTML may use different structures across variants:

1. **Tables with `<td>` cells**: Most common. Extract by column position.
2. **Definition lists (`<dl>`, `<dt>`, `<dd>`)**: Map dt→name, dd→value.
3. **Nested `<div>` or `<span>` layouts**: Use class names and text content.
4. **Line numbers in different formats**: May be in `<td>`, `<span>`, or as
   text prefixes.

**Universal approach**: Use BeautifulSoup if available, otherwise regex.
Always extract: (a) line number, (b) metric name, (c) numeric value.

### Handling Varied Numeric Formats

- `$1,234.5` → 1234.5
- `(45.2)` → -45.2 (parenthetical negatives)
- `60.8%` → 60.8
- `$842.0M` → 842.0 (strip unit suffixes)
- `1,234` → 1234.0

```python
def parse_numeric(raw):
    """Parse various numeric formats to float."""
    s = raw.strip()
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    s = s.replace('$', '').replace(',', '').replace('%', '').strip()
    # Strip trailing unit suffixes like M, B, K
    s = re.sub(r'[MBKmk]$', '', s)
    val = float(s)
    return -val if negative else val
```

## Relationship Discovery (General)

When the report structure is unfamiliar, discover relationships automatically:

1. **Name-based heuristics**:
   - Names containing "total" or "subtotal" are sums of nearby items
   - Names containing "margin" are ratios (numerator / denominator)
   - Names containing "growth" or "change" are (new - old) / |old|
   - Names containing "per share" or "EPS" divide by share count

2. **Positional heuristics**:
   - In income statements, items flow top-to-bottom with subtotals
   - Revenue is typically the base for margin calculations
   - Operating items sit between gross profit and operating income

3. **Value-based heuristics**:
   - If value_A + value_B ≈ value_C, then C is likely a total of A and B
   - If value_A / value_B ≈ value_C / 100, then C is likely a margin

## Tolerance and Rounding

- For dollar values rounded to 1 decimal: tolerance ±0.05 (but use ±0.15 to be
  safe with chained rounding)
- For percentages rounded to 1 decimal: tolerance ±0.15 percentage points
- For percentages rounded to 0 decimals: tolerance ±0.6 percentage points
- Always round the computed expected value to the same precision as the reported
  value before comparing

## Complete Workflow Script

```python
#!/usr/bin/env python3
"""
General HTML financial verification script.
Adapt the HTML parsing and relationship identification to the specific report.
"""
import re
import sys
from html.parser import HTMLParser

def main():
    # 1. Read the HTML file
    html_path = find_html_file()  # Look for .html files in /app/
    with open(html_path) as f:
        html = f.read()
    
    # 2. Extract all metrics
    metrics = extract_metrics(html)
    
    # 3. Build name→metric map
    by_name = {}
    for m in metrics:
        key = m['name'].lower().strip()
        by_name[key] = m
    
    # 4. Check all relationships
    all_violations = []
    
    # 4a. Additive checks
    # Identify which metrics are totals of others
    additive_groups = discover_additive_groups(metrics, by_name)
    for total_key, component_keys in additive_groups:
        if total_key in by_name:
            expected = sum(by_name[ck]['value'] for ck in component_keys if ck in by_name)
            actual = by_name[total_key]['value']
            if abs(expected - actual) > 0.15:
                all_violations.append(('additive', total_key, expected, actual, component_keys))
    
    # 4b. Ratio checks  
    ratio_groups = discover_ratio_groups(metrics, by_name)
    for ratio_key, num_key, den_key in ratio_groups:
        if ratio_key in by_name and num_key in by_name and den_key in by_name:
            expected = by_name[num_key]['value'] / by_name[den_key]['value'] * 100
            actual = by_name[ratio_key]['value']
            if abs(expected - actual) > 0.15:
                all_violations.append(('ratio', ratio_key, expected, actual, [num_key, den_key]))
    
    # 5. Find the error
    error_metric = identify_error_metric(all_violations, by_name)
    
    # 6. Output
    output_path = get_output_path()  # From task instructions
    with open(output_path, 'w') as f:
        f.write(f"{error_metric['line']},{format_value(error_metric['value'])}")

if __name__ == '__main__':
    main()
```

## Key Principles

1. **Internal consistency only**: The error is always discoverable from
   relationships within the report. No external knowledge needed.
2. **Exactly one error**: There is always exactly one incorrect metric.
3. **Cross-check everything**: Verify all possible relationships; the error
   metric will be the one that breaks consistency.
4. **Report the wrong value**: Output the value as displayed, not the corrected value.
5. **Respect formatting**: Follow the exact output format specified in the task.

## Common Pitfalls

- **Using heuristics for error localization**: "Ratio violation means ratio is wrong" breaks when dollar values are the error. Use constraint satisfaction instead.
- **Forgetting to check PASSING checks**: If a metric participates in both passing and failing checks, the passing checks prove it's correct. Only metrics with ALL failing checks (and no passing checks) can be the error.
- Forgetting to handle rounding when comparing computed vs. reported percentages
- Missing additive relationships when component names don't exactly match expectations
- Not considering that the "total" might be correct while a component is wrong
- Including formatting characters ($, %, commas) in the output value
- **Only checking pairs in additive discovery**: Real income statements have 3+ component sums (e.g., Total OpEx = R&D + S&M + G&A). Must check N-way combinations.
