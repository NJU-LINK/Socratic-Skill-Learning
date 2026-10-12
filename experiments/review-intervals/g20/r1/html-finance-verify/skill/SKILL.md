---
name: html-finance-verify
description: Verify internal consistency of HTML financial reports to identify the single incorrect metric by parsing line-numbered financial data, building dependency relationships between metrics, and cross-checking computed values against reported values.
---

# HTML Financial Verification Skill

## Purpose
Identify the single incorrect metric in an HTML financial report by systematically verifying internal consistency across all reported values. The report contains line-numbered financial metrics where one category of values (either dollar amounts OR percentages/ratios) contains exactly one error, while the other category is guaranteed correct.

## Core Methodology

### Step 0: Extract Task Constraints (CRITICAL FIRST STEP)

**Before any verification, parse the task instructions to understand WHERE the error is:**

The task instructions contain **error candidate constraints** that drive the entire verification strategy. These are not just output formatting instructions — they tell you which metrics to check and which to treat as known-good.

**Key constraint categories:**

1. **Error location**: Which category contains the error?
   - **Percentage/ratio errors**: "only one KPI percentage is wrong", "one margin is incorrect", "the error is in a ratio metric"
   - **Dollar value errors**: "one dollar value is wrong", "a line-item total is misstated", "one expense subtotal is incorrect"
   - **Any metric**: "one reported metric is incorrect" (no category restriction)

2. **Known-good category**: Which category is guaranteed correct?
   - "all dollar-denominated values are internally consistent" → dollars are correct, error is in percentages
   - "all KPI percentages are correct" → percentages are correct, error is in dollars

3. **Error count**: "exactly one" → stop after first error found

**Clause-level semantic analysis** (CRITICAL - respect sentence structure):

The task instructions describe relationships between categories and their correctness. You must detect whether each category is described as "correct/consistent" or "wrong/incorrect" **within the same clause**:

```python
import re

def parse_task_constraints(task_text):
    """Extract error candidate constraints using clause-level analysis."""
    task_lower = task_text.lower()
    
    # Keywords indicating correctness vs error
    correct_indicators = ['consistent', 'correct', 'accurate', 'right', 'valid']
    error_indicators = ['wrong', 'incorrect', 'error', 'mistake', 'misstated', 'inaccurate']
    
    # Category keywords
    percentage_terms = ['percentage', 'margin', 'ratio', 'kpi', 'rate']
    dollar_terms = ['dollar', 'line-item', 'subtotal', 'amount']
    
    # Detect semantic relationships using clause-level analysis
    dollar_is_correct = False
    dollar_is_wrong = False
    percentage_is_correct = False
    percentage_is_wrong = False
    
    # Split into clauses by commas, periods, semicolons, and conjunctions
    clauses = re.split(r'[,;.]|\band\b|\bbut\b', task_lower)
    
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        
        # Check if this clause mentions dollar terms (use word boundaries, allow plural with s?)
        has_dollar = any(re.search(r'\b' + re.escape(term) + r's?\b', clause) for term in dollar_terms)
        # Check if this clause mentions percentage terms (use word boundaries, allow plural with s?)
        has_percentage = any(re.search(r'\b' + re.escape(term) + r's?\b', clause) for term in percentage_terms)
        
        # Check if this clause has correct/error indicators (use word boundaries to avoid substring matches like 'correct' in 'incorrect')
        has_correct = any(re.search(r'\b' + re.escape(ind) + r'\b', clause) for ind in correct_indicators)
        has_error = any(re.search(r'\b' + re.escape(ind) + r'\b', clause) for ind in error_indicators)
        
        # Determine relationships within this clause
        if has_dollar and has_correct and not has_error:
            dollar_is_correct = True
        elif has_dollar and has_error and not has_correct:
            dollar_is_wrong = True
        
        if has_percentage and has_correct and not has_error:
            percentage_is_correct = True
        elif has_percentage and has_error and not has_correct:
            percentage_is_wrong = True
    
    # Determine error candidates based on semantic relationships
    if percentage_is_wrong and dollar_is_correct:
        # "dollars are consistent, percentage is wrong"
        error_candidates = ['percentage']
        skip_checks = ['dollar']
    elif dollar_is_wrong and percentage_is_correct:
        # "percentages are correct, dollar value is wrong"
        error_candidates = ['dollar']
        skip_checks = ['percentage']
    elif percentage_is_wrong and not dollar_is_correct:
        # Only percentage error mentioned, dollars not specified
        error_candidates = ['percentage']
        skip_checks = []
    elif dollar_is_wrong and not percentage_is_correct:
        # Only dollar error mentioned, percentages not specified
        error_candidates = ['dollar']
        skip_checks = []
    else:
        # Ambiguous - check everything
        error_candidates = ['dollar', 'percentage']
        skip_checks = []
    
    return error_candidates, skip_checks
```

**Example for v01**: "All of the dollar-denominated statement values are internally consistent, and only one displayed KPI percentage is wrong."
- Clause 1: "all of the dollar-denominated statement values are internally consistent"
  - has_dollar: True, has_correct: True → `dollar_is_correct = True`
- Clause 2: "only one displayed kpi percentage is wrong"
  - has_percentage: True, has_error: True → `percentage_is_wrong = True`
- Result: `error_candidates = ['percentage']`, `skip_checks = ['dollar']` ✓

**Why Step 0 is critical:**
- Task instructions are the **specification**, not decoration
- They tell you WHERE to look and WHAT to ignore
- Checking all relationships uniformly wastes time and may surface false positives
- Clause-level analysis respects sentence structure and avoids false associations
- Constraint-driven verification is efficient and accurate

### Step 1: Parse HTML Structure

Extract all line-numbered metrics from the HTML document:

**Strategy A — Regex on table rows:**
```python
import re
# Match patterns like: <td ...>LINE</td> <td ...>METRIC</td> <td ...>VALUE</td>
pattern = r'<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>'
matches = re.findall(pattern, html_content)
```

**Strategy B — Use BeautifulSoup for robust parsing:**
```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(html_content, 'html.parser')
for row in soup.find_all('tr'):
    cells = row.find_all('td')
    if len(cells) >= 3:
        line_num = cells[0].get_text(strip=True)
        metric = cells[1].get_text(strip=True)
        value = cells[2].get_text(strip=True)
```

**Value cleaning:**
- Remove `$`, `%`, commas, whitespace
- Handle negatives: `(123.4)` → `-123.4`, or `-123.4` → `-123.4`
- Convert to float

### Step 2: Identify Financial Structure and Relationships

Map metric names to their financial relationships. Use keyword matching to classify metrics:

**Income Statement Relationships:**
| Relationship | Formula |
|---|---|
| Gross Profit | Revenue − Cost of Revenue (COGS) |
| Total Operating Expenses | Sum of all operating expense line items (R&D, S&M, G&A, etc.) |
| Operating Income (EBIT) | Gross Profit − Total Operating Expenses |
| EBITDA | Operating Income + Depreciation + Amortization |
| Net Income (before EPS) | Operating Income + Other Income/Expense − Taxes |
| EPS (basic) | Net Income / Basic Shares Outstanding |
| EPS (diluted) | Net Income / Diluted Shares Outstanding |

**Margin/Percentage Relationships:**
| Relationship | Formula |
|---|---|
| Gross Margin | (Gross Profit / Revenue) × 100 |
| Operating Margin | (Operating Income / Revenue) × 100 |
| Net Margin | (Net Income / Revenue) × 100 |
| YoY Revenue Growth | ((Current Revenue − Prior Revenue) / Prior Revenue) × 100 |
| Expense Ratio | (Expense / Revenue) × 100 |

**Balance Sheet Relationships (if present):**
| Relationship | Formula |
|---|---|
| Total Assets | Current Assets + Non-Current Assets |
| Total Liabilities + Equity | Total Liabilities + Total Equity |
| Working Capital | Current Assets − Current Liabilities |

**Cash Flow Relationships (if present):**
| Relationship | Formula |
|---|---|
| Free Cash Flow | Operating Cash Flow − Capital Expenditures |
| Total Cash Flow | Operating + Investing + Financing |

### Step 3: Build Dependency Graph and Cross-Check (Constraint-Driven)

**Only check metrics that match the error candidate type from Step 0:**

**CRITICAL: Check ALL financial relationships, not just a subset!**

The skill must verify every possible relationship in the income statement:

**Dollar value relationships:**
1. Gross Profit = Revenue − Cost of Revenue (COGS)
2. Total Operating Expenses = R&D + S&M + G&A (+ other operating expenses if present)
3. Operating Income = Gross Profit − Total Operating Expenses
4. Net Income = Operating Income + Other Income/Expense − Taxes

**Percentage relationships:**
5. Gross Margin = (Gross Profit / Revenue) × 100
6. Operating Margin = (Operating Income / Revenue) × 100
7. Net Margin = (Net Income / Revenue) × 100

```python
def verify(data, error_candidates, skip_checks):
    """Cross-check ALL relationships and find the error (constraint-driven)."""
    errors = []
    tol = 0.05  # Adjust based on report precision
    
    # Get key values
    rev_ln, rev = find_by_keyword(data, ['revenue'])
    cogs_ln, cogs = find_by_keyword(data, ['cost of revenue', 'cogs'])
    gp_ln, gp = find_by_keyword(data, ['gross profit'])
    
    # Find operating expense components
    rd_ln, rd = find_by_keyword(data, ['research', 'development', 'r&d'])
    sm_ln, sm = find_by_keyword(data, ['sales and marketing', 'selling', 's&m'])
    ga_ln, ga = find_by_keyword(data, ['general and admin', 'g&a', 'general & admin'])
    
    opex_ln, opex = find_by_keyword(data, ['total operating'])
    oi_ln, oi = find_by_keyword(data, ['operating income'])
    other_ln, other = find_by_keyword(data, ['other income'])
    ni_ln, ni = find_by_keyword(data, ['net income'])
    
    gm_ln, gm = find_by_keyword(data, ['gross margin'])
    om_ln, om = find_by_keyword(data, ['operating margin'])
    nm_ln, nm = find_by_keyword(data, ['net margin'])
    
    # DOLLAR VALUE CHECKS (only if dollars are error candidates)
    if 'dollar' in error_candidates and 'dollar' not in skip_checks:
        # Check 1: Gross Profit = Revenue - COGS
        if gp is not None and rev is not None and cogs is not None:
            calc = rev - cogs
            if abs(gp - calc) >= tol:
                errors.append((gp_ln, gp, f'Gross profit error'))
        
        # Check 2: Total OpEx = sum of components
        if opex is not None and rd is not None and sm is not None and ga is not None:
            calc = rd + sm + ga
            if abs(opex - calc) >= tol:
                errors.append((opex_ln, opex, f'Total OpEx error'))
        
        # Check 3: Operating Income = Gross Profit - Total OpEx
        if oi is not None and gp is not None and opex is not None:
            calc = gp - opex
            if abs(oi - calc) >= tol:
                errors.append((oi_ln, oi, f'Operating income error'))
        
        # Check 4: Net Income = Operating Income + Other Income
        if ni is not None and oi is not None and other is not None:
            calc = oi + other
            if abs(ni - calc) >= tol:
                errors.append((ni_ln, ni, f'Net income error'))
    
    # PERCENTAGE CHECKS (only if percentages are error candidates)
    if 'percentage' in error_candidates and 'percentage' not in skip_checks:
        # Check 5: Gross Margin
        if gm is not None and gp is not None and rev is not None:
            calc = round((gp / rev) * 100, 1)
            if abs(gm - calc) >= tol:
                errors.append((gm_ln, gm, f'Gross margin: {gm}% != {calc}%'))
        
        # Check 6: Operating Margin
        if om is not None and oi is not None and rev is not None:
            calc = round((oi / rev) * 100, 1)
            if abs(om - calc) >= tol:
                errors.append((om_ln, om, f'Operating margin: {om}% != {calc}%'))
        
        # Check 7: Net Margin
        if nm is not None and ni is not None and rev is not None:
            calc = round((ni / rev) * 100, 1)
            if abs(nm - calc) >= tol:
                errors.append((nm_ln, nm, f'Net margin: {nm}% != {calc}%'))
    
    return errors
```

**Sanity checks**: Dollar-value relationships can still be checked as assertions to verify parsing correctness, but they should never produce the final answer if the task says dollars are correct.

### Step 4: Handle Format Variations

| Format | Handling |
|---|---|
| Currency `$1,234.5` | Remove `$` and `,` → `1234.5` |
| Percentage `60.8%` | Remove `%` → `60.8` |
| Parenthetical negative `(50.0)` | Convert to `-50.0` |
| Thousands (in millions) | Note the unit; values may be in millions |
| Rounded figures | Use appropriate tolerance |

### Step 5: Output

Write to the specified output file (check task instructions for exact path):
```
line_number,value
```

- `line_number`: Integer, the line number shown next to the incorrect metric
- `value`: The incorrect numeric value as displayed, without `%` or `$` signs
- No trailing newline issues; match exact format specified

## General-Purpose Verification Script

```python
#!/usr/bin/env python3
"""
General HTML financial verification script with constraint-driven verification.
"""
import re
import sys

def parse_task_constraints(task_text):
    """Extract error candidate constraints using clause-level analysis."""
    task_lower = task_text.lower()
    
    # Keywords indicating correctness vs error
    correct_indicators = ['consistent', 'correct', 'accurate', 'right', 'valid']
    error_indicators = ['wrong', 'incorrect', 'error', 'mistake', 'misstated', 'inaccurate']
    
    # Category keywords
    percentage_terms = ['percentage', 'margin', 'ratio', 'kpi', 'rate']
    dollar_terms = ['dollar', 'line-item', 'subtotal', 'amount']
    
    # Detect semantic relationships using clause-level analysis
    dollar_is_correct = False
    dollar_is_wrong = False
    percentage_is_correct = False
    percentage_is_wrong = False
    
    # Split into clauses by commas, periods, semicolons, and conjunctions
    clauses = re.split(r'[,;.]|\band\b|\bbut\b', task_lower)
    
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        
        # Check if this clause mentions dollar terms (use word boundaries, allow plural with s?)
        has_dollar = any(re.search(r'\b' + re.escape(term) + r's?\b', clause) for term in dollar_terms)
        # Check if this clause mentions percentage terms (use word boundaries, allow plural with s?)
        has_percentage = any(re.search(r'\b' + re.escape(term) + r's?\b', clause) for term in percentage_terms)
        
        # Check if this clause has correct/error indicators (use word boundaries to avoid substring matches like 'correct' in 'incorrect')
        has_correct = any(re.search(r'\b' + re.escape(ind) + r'\b', clause) for ind in correct_indicators)
        has_error = any(re.search(r'\b' + re.escape(ind) + r'\b', clause) for ind in error_indicators)
        
        # Determine relationships within this clause
        if has_dollar and has_correct and not has_error:
            dollar_is_correct = True
        elif has_dollar and has_error and not has_correct:
            dollar_is_wrong = True
        
        if has_percentage and has_correct and not has_error:
            percentage_is_correct = True
        elif has_percentage and has_error and not has_correct:
            percentage_is_wrong = True
    
    # Determine error candidates
    if percentage_is_wrong and dollar_is_correct:
        error_candidates = ['percentage']
        skip_checks = ['dollar']
    elif dollar_is_wrong and percentage_is_correct:
        error_candidates = ['dollar']
        skip_checks = ['percentage']
    elif percentage_is_wrong and not dollar_is_correct:
        error_candidates = ['percentage']
        skip_checks = []
    elif dollar_is_wrong and not percentage_is_correct:
        error_candidates = ['dollar']
        skip_checks = []
    else:
        error_candidates = ['dollar', 'percentage']
        skip_checks = []
    
    return error_candidates, skip_checks

def parse_html(html_path):
    """Extract line-numbered metrics from HTML."""
    with open(html_path) as f:
        html = f.read()
    
    pattern = r'<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>'
    matches = re.findall(pattern, html)
    
    data = {}
    for line_str, metric, raw_val in matches:
        line_num = int(line_str)
        metric = metric.strip()
        clean = raw_val.strip().replace('$', '').replace(',', '').replace('%', '')
        if clean.startswith('(') and clean.endswith(')'):
            clean = '-' + clean[1:-1]
        numeric = float(clean)
        data[line_num] = {'metric': metric, 'raw': raw_val.strip(), 'value': numeric}
    return data

def find_by_keyword(data, keywords):
    """Find a metric by keyword matching."""
    for ln, info in data.items():
        name_lower = info['metric'].lower()
        if any(kw.lower() in name_lower for kw in keywords):
            return ln, info['value']
    return None, None

def verify(data, error_candidates, skip_checks):
    """Cross-check ALL relationships and find the error (constraint-driven)."""
    errors = []
    tol = 0.05
    
    rev_ln, rev = find_by_keyword(data, ['revenue'])
    cogs_ln, cogs = find_by_keyword(data, ['cost of revenue', 'cogs'])
    gp_ln, gp = find_by_keyword(data, ['gross profit'])
    
    # Find operating expense components
    rd_ln, rd = find_by_keyword(data, ['research', 'development', 'r&d'])
    sm_ln, sm = find_by_keyword(data, ['sales and marketing', 'selling', 's&m'])
    ga_ln, ga = find_by_keyword(data, ['general and admin', 'g&a', 'general & admin'])
    
    opex_ln, opex = find_by_keyword(data, ['total operating'])
    oi_ln, oi = find_by_keyword(data, ['operating income'])
    other_ln, other = find_by_keyword(data, ['other income'])
    ni_ln, ni = find_by_keyword(data, ['net income'])
    
    gm_ln, gm = find_by_keyword(data, ['gross margin'])
    om_ln, om = find_by_keyword(data, ['operating margin'])
    nm_ln, nm = find_by_keyword(data, ['net margin'])
    
    # DOLLAR CHECKS (only if dollars are error candidates)
    if 'dollar' in error_candidates and 'dollar' not in skip_checks:
        # Check 1: Gross Profit = Revenue - COGS
        if gp is not None and rev is not None and cogs is not None:
            calc = rev - cogs
            if abs(gp - calc) >= tol:
                errors.append((gp_ln, gp, f'Gross profit error'))
        
        # Check 2: Total OpEx = sum of components
        if opex is not None and rd is not None and sm is not None and ga is not None:
            calc = rd + sm + ga
            if abs(opex - calc) >= tol:
                errors.append((opex_ln, opex, f'Total OpEx error'))
        
        # Check 3: Operating Income = Gross Profit - Total OpEx
        if oi is not None and gp is not None and opex is not None:
            calc = gp - opex
            if abs(oi - calc) >= tol:
                errors.append((oi_ln, oi, f'Operating income error'))
        
        # Check 4: Net Income = Operating Income + Other Income
        if ni is not None and oi is not None and other is not None:
            calc = oi + other
            if abs(ni - calc) >= tol:
                errors.append((ni_ln, ni, f'Net income error'))
    
    # PERCENTAGE CHECKS (only if percentages are error candidates)
    if 'percentage' in error_candidates and 'percentage' not in skip_checks:
        # Check 5: Gross Margin
        if gm is not None and gp is not None and rev is not None:
            calc = round((gp / rev) * 100, 1)
            if abs(gm - calc) >= tol:
                errors.append((gm_ln, gm, f'Gross margin: {gm}% != {calc}%'))
        
        # Check 6: Operating Margin
        if om is not None and oi is not None and rev is not None:
            calc = round((oi / rev) * 100, 1)
            if abs(om - calc) >= tol:
                errors.append((om_ln, om, f'Operating margin: {om}% != {calc}%'))
        
        # Check 7: Net Margin
        if nm is not None and ni is not None and rev is not None:
            calc = round((ni / rev) * 100, 1)
            if abs(nm - calc) >= tol:
                errors.append((nm_ln, nm, f'Net margin: {nm}% != {calc}%'))
    
    return errors

def main():
    html_path = sys.argv[1] if len(sys.argv) > 1 else '/app/q2_earnings_report.html'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/value.txt'
    task_text = sys.argv[3] if len(sys.argv) > 3 else ''
    
    # Step 0: Parse task constraints
    error_candidates, skip_checks = parse_task_constraints(task_text)
    print(f"Error candidates: {error_candidates}")
    print(f"Skip checks: {skip_checks}")
    
    # Step 1: Parse HTML
    data = parse_html(html_path)
    print(f"\nParsed {len(data)} metrics")
    
    # Step 3: Verify with constraints
    errors = verify(data, error_candidates, skip_checks)
    if errors:
        ln, val, msg = errors[0]
        print(f"\nERROR: Line {ln}, value={val}: {msg}")
        with open(output_path, 'w') as f:
            f.write(f"{ln},{val}")
        print(f"Answer written to {output_path}: {ln},{val}")
    else:
        print("\nNo errors found in error candidate categories!")

if __name__ == '__main__':
    main()
```

## Adaptation to Spec Variation Dimensions

### report_structure_and_metric_relationships (freeform)
- **Table structure**: May use `<table>`, CSS grid, `<div>` layouts — adapt parsing strategy
- **Section names**: "Income Statement", "Profit & Loss", "Condensed P&L" — match by keywords
- **Metric families**: May include EBITDA, free cash flow, working capital — add to relationship map
- **Line numbering**: May be dense (101, 102, 103) or sparse (100, 200, 300) — don't assume gaps
- **Arithmetic relations**: May use multiplication (EPS), division (ratios), or compound formulas

### error_type_and_discoverability (freeform)
- **Totals**: Sum of components ≠ reported total
- **Subtotals**: Sub-group sum ≠ reported subtotal
- **Margins**: Numerator/denominator calculation wrong
- **YoY changes**: ((new-old)/old)*100 computed incorrectly
- **Per-share**: Net income / shares computed incorrectly
- **Unit conversions**: e.g., reported in thousands but calculated in millions
- **Rounded figures**: Error may be in rounding direction or precision

### output_format_constraints (freeform)
- **Target file**: Read task instructions carefully for output path
- **Numeric precision**: May require 2 decimal places, no decimals, etc.
- **Comma/whitespace**: Output value may need commas or no commas
- **Signs**: Negative values may need minus sign
- **Percentages**: Remove % sign from output value

## Debugging Checklist
- [ ] **Step 0 completed**: Task constraints parsed using clause-level analysis?
- [ ] All values parsed correctly from HTML?
- [ ] Currency symbols, commas, and percentage signs properly stripped?
- [ ] Negative values in parentheses handled?
- [ ] Metric relationships correctly identified from names?
- [ ] **ALL financial relationships checked** (not just a subset)?
  - Dollar checks: Gross Profit, Total OpEx, Operating Income, Net Income
  - Percentage checks: Gross Margin, Operating Margin, Net Margin
- [ ] Tolerance appropriate for the displayed precision?
- [ ] Only checking metrics in the error candidate category?
- [ ] Exactly ONE error found (as task specifies)?
- [ ] Output format matches requirements exactly (line_number,value)?
- [ ] No trailing whitespace or newline issues in output file?

## Example Walkthrough (v01)

**Task instruction**: "All of the dollar-denominated statement values are internally consistent, and only one displayed KPI percentage is wrong."

**Step 0**: Parse constraints using clause-level analysis
- Clause 1: "all of the dollar-denominated statement values are internally consistent"
  - has_dollar: True, has_correct: True → `dollar_is_correct = True`
- Clause 2: "only one displayed kpi percentage is wrong"
  - has_percentage: True, has_error: True → `percentage_is_wrong = True`
- Result: `error_candidates = ['percentage']`, `skip_checks = ['dollar']`

**Given data**:
- Line 110: Revenue = $842.0
- Line 120: COGS = $321.6
- Line 130: Gross Profit = $520.4
- Line 210: Gross Margin = 60.8%

**Verification** (only percentage checks):
1. Gross Profit = 842.0 - 321.6 = 520.4 ✓ (sanity check only, not an error candidate)
2. Gross Margin = (520.4 / 842.0) × 100 = 61.8%
3. Reported: 60.8% ≠ 61.8% ✗ **ERROR FOUND**
4. Answer: `210,60.8`

**Key insight**: The clause-level analysis correctly identifies that dollars are consistent (clause 1) and percentages contain the error (clause 2). We only report the percentage error because that's what the task constraints specify.
