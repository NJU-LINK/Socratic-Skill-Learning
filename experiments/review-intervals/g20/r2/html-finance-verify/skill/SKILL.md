---
name: html-finance-verify
description: Verify internal consistency of HTML financial reports and identify the single incorrect metric by cross-checking arithmetic relationships between line items and derived percentages using scored fuzzy matching, a relationship template catalog, root-cause analysis of cascading failures, and robust brute-force percentage fallback with closest-match gap detection for novel relationship types.
---

# HTML Financial Verification Skill

## Purpose

This skill identifies a single incorrect metric in an HTML financial report by verifying internal consistency across all reported values. The report contains dollar-denominated line items and derived KPI percentages; exactly one value is wrong while all others are internally consistent.

## Core Strategy

The verification follows a systematic approach:

1. **Parse the HTML report** to extract all line-numbered metrics with their values
2. **Apply a catalog of relationship templates** with scored fuzzy matching to identify metric roles
3. **Verify dollar-denominated values** for internal consistency using arithmetic relationships
4. **Verify derived percentages** by recalculating from the underlying dollar values
5. **Perform root-cause analysis** to identify the single metric responsible for all failures

## Implementation Pattern

### Step 1: HTML Parsing

Extract all metrics from the HTML report using Python's HTMLParser:

```python
from html.parser import HTMLParser

class FinancialTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metrics = []
        self.in_td = False
        self.current_row = []
        self.current_data = ""
        
    def handle_starttag(self, tag, attrs):
        if tag == 'td':
            self.in_td = True
            self.current_data = ""
        elif tag == 'tr':
            self.current_row = []
            
    def handle_endtag(self, tag):
        if tag == 'td' and self.in_td:
            self.in_td = False
            self.current_row.append(self.current_data.strip())
        elif tag == 'tr':
            if len(self.current_row) >= 3:
                line_text = self.current_row[0]
                name = self.current_row[1]
                value_text = self.current_row[2]
                
                if line_text.isdigit():
                    # Clean numeric value
                    value_clean = value_text.replace('$', '').replace('%', '').replace(',', '').strip()
                    # Handle parenthetical negatives: (123.4) -> -123.4
                    if value_clean.startswith('(') and value_clean.endswith(')'):
                        value_clean = '-' + value_clean[1:-1]
                    try:
                        value = float(value_clean)
                        self.metrics.append({
                            'line': int(line_text),
                            'name': name,
                            'value': value,
                            'raw': value_text,
                            'is_percentage': '%' in value_text,
                            'is_dollar': '$' in value_text
                        })
                    except ValueError:
                        pass
                        
    def handle_data(self, data):
        if self.in_td:
            self.current_data += data
```

### Step 2: Scored Fuzzy Matching

Use scored matching instead of first-match to avoid ambiguous substring matches:

```python
def name_matches_score(metric_name, patterns):
    """
    Return a match score (higher = better match). 0 = no match.
    
    Scoring hierarchy:
    - Exact match: 100
    - All pattern words found in metric name: 50-80 (higher if name is short)
    - Substring match: 1-30 (higher if pattern length is close to name length)
    """
    name_lower = metric_name.lower().strip()
    best = 0
    for pattern in patterns:
        p = pattern.lower().strip()
        # Exact match is best
        if name_lower == p:
            best = max(best, 100)
        # All words match (order-independent)
        elif all(w in name_lower for w in p.split()):
            name_words = len(name_lower.split())
            pattern_words = len(p.split())
            word_ratio = pattern_words / max(name_words, 1)
            best = max(best, 50 + int(word_ratio * 30))
        # Substring match (weakest)
        elif p in name_lower:
            length_ratio = len(p) / max(len(name_lower), 1)
            best = max(best, int(20 * length_ratio))
    return best

def find_metric(metrics, patterns, exclude_lines=None):
    """Find the BEST matching metric by score, not just the first."""
    candidates = []
    for m in metrics:
        if exclude_lines and m['line'] in exclude_lines:
            continue
        score = name_matches_score(m['name'], patterns)
        if score > 0:
            candidates.append((score, m))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]
```

**Why scored matching matters:** Without scoring, a pattern like `'sales'` in a revenue pattern list would match "Sales and marketing" (an expense) before "Revenue" if the expense table appears first in the HTML. Scored matching ensures "Revenue" (exact match, score 100) beats "Sales and marketing" (weak substring match, score ~6).

### Step 3: Relationship Template Catalog

Define templates for common financial relationships. Each template specifies the result metric and the operation to verify it:

```python
TEMPLATES = [
    # Income statement arithmetic
    {'id': 'gp', 'result': ['gross profit'], 'op': 'sub',
     'operands': [['revenue', 'total revenue', 'net revenue', 'net sales'],
                  ['cost of revenue', 'cogs', 'cost of goods sold', 'cost of sales']]},
    {'id': 'opex', 'result': ['total operating expenses', 'total opex'],
     'op': 'sum_expenses'},
    {'id': 'oi', 'result': ['operating income', 'operating profit'],
     'op': 'sub', 'operands': [['gross profit'],
                                ['total operating expenses', 'total opex']]},
    {'id': 'ni_add', 'result': ['net income', 'net profit', 'net earnings'],
     'op': 'add', 'operands': [['operating income', 'operating profit'],
                                ['other income', 'non-operating income']]},
    
    # Margin percentages
    {'id': 'gm', 'result': ['gross margin', 'gross profit margin'],
     'op': 'pct', 'num': ['gross profit'],
     'denom': ['revenue', 'total revenue', 'net revenue', 'net sales']},
    {'id': 'om', 'result': ['operating margin', 'operating profit margin'],
     'op': 'pct', 'num': ['operating income', 'operating profit'],
     'denom': ['revenue', 'total revenue', 'net revenue', 'net sales']},
    {'id': 'nm', 'result': ['net margin', 'net profit margin', 'profit margin'],
     'op': 'pct', 'num': ['net income', 'net profit'],
     'denom': ['revenue', 'total revenue', 'net revenue', 'net sales']},
    
    # Per-share values
    {'id': 'eps', 'result': ['earnings per share', 'eps', 'diluted eps'],
     'op': 'div', 'num': ['net income', 'net profit'],
     'denom': ['shares outstanding', 'diluted shares', 'weighted average shares']},
    
    # Year-over-year growth
    {'id': 'rg', 'result': ['revenue growth', 'sales growth'],
     'op': 'yoy_pct', 'current': ['revenue', 'total revenue'],
     'prior': ['prior revenue', 'prior year revenue', 'previous revenue']},
]
```

### Step 4: Expense Component Detection

Detect operating expense line items by exclusion, not by positive role matching:

```python
KNOWN_NON_EXPENSE = [
    ['revenue', 'total revenue', 'net revenue', 'net sales'],
    ['cost of revenue', 'cogs', 'cost of goods sold', 'cost of sales'],
    ['gross profit'],
    ['total operating expenses', 'total opex'],
    ['operating income', 'operating profit', 'operating loss'],
    ['net income', 'net profit', 'net earnings'],
    ['other income', 'other expense', 'non-operating'],
    ['margin', 'gross margin', 'operating margin', 'net margin'],
    ['earnings per share', 'eps'],
    ['growth', 'yoy'],
    ['ratio'],
]

def is_known_non_expense(name):
    """Check if a metric name matches any known non-expense pattern."""
    for patterns in KNOWN_NON_EXPENSE:
        if name_matches_score(name, patterns) > 0:
            return True
    return False

def detect_expense_components(metrics):
    """
    Detect operating expense line items.
    A metric is an expense component if:
    - It's dollar-denominated (not a percentage)
    - Its name does NOT match any known non-expense pattern
    - It contains expense-related keywords
    """
    expense_keywords = [
        'research', 'development', 'r&d',
        'sales', 'marketing', 's&m',
        'general', 'administrative', 'g&a',
        'selling', 'depreciation', 'amortization',
        'compensation', 'benefits', 'rent', 'lease',
        'professional', 'legal', 'engineering', 'support'
    ]
    
    components = []
    for m in metrics:
        if m['is_percentage']:
            continue
        if is_known_non_expense(m['name']):
            continue
        name_lower = m['name'].lower()
        if any(kw in name_lower for kw in expense_keywords):
            components.append(m)
    
    return components
```

**Why exclusion-based detection:** A metric like "Sales and marketing" contains "sales" which could match revenue patterns. By explicitly excluding known non-expense lines (revenue, gross profit, operating income, etc.), we correctly classify "Sales and marketing" as an expense component.

### Step 5: Template Checking with Involved-Line Tracking

Each template check tracks which metrics (by line number) participate in the check. This enables root-cause analysis when multiple checks fail:

```python
def check_template(template, metrics):
    """
    Returns (matched, involved_lines: set[int], failing_line: int|None,
             failing_metric: dict|None, reported, calculated)
    """
    op = template['op']
    
    if op in ('sub', 'add'):
        result_m = find_metric(metrics, template['result'])
        if not result_m:
            return False, set(), None, None, 0, 0
        op1 = find_metric(metrics, template['operands'][0])
        op2 = find_metric(metrics, template['operands'][1])
        if not op1 or not op2:
            return False, set(), None, None, 0, 0
        
        involved = {result_m['line'], op1['line'], op2['line']}
        calculated = op1['value'] - op2['value'] if op == 'sub' else op1['value'] + op2['value']
        
        if abs(calculated - result_m['value']) >= 0.5:
            return True, involved, result_m['line'], result_m, result_m['value'], calculated
        return True, involved, None, None, result_m['value'], calculated
    
    elif op == 'sum_expenses':
        result_m = find_metric(metrics, template['result'])
        if not result_m:
            return False, set(), None, None, 0, 0
        components = detect_expense_components(metrics)
        if len(components) < 2:
            return False, set(), None, None, 0, 0
        
        involved = {result_m['line']} | {c['line'] for c in components}
        calculated = sum(c['value'] for c in components)
        
        if abs(calculated - result_m['value']) >= 0.5:
            return True, involved, result_m['line'], result_m, result_m['value'], calculated
        return True, involved, None, None, result_m['value'], calculated
    
    elif op == 'pct':
        result_m = find_metric(metrics, template['result'])
        if not result_m:
            return False, set(), None, None, 0, 0
        num_m = find_metric(metrics, template['num'])
        denom_m = find_metric(metrics, template['denom'])
        if not num_m or not denom_m or denom_m['value'] == 0:
            return False, set(), None, None, 0, 0
        
        involved = {result_m['line'], num_m['line'], denom_m['line']}
        calculated = (num_m['value'] / denom_m['value']) * 100
        
        if abs(calculated - result_m['value']) >= 0.15:
            return True, involved, result_m['line'], result_m, result_m['value'], calculated
        return True, involved, None, None, result_m['value'], calculated
    
    # Similar for 'div' and 'yoy_pct'...
    
    return False, set(), None, None, 0, 0
```

### Step 6: Root-Cause Analysis

When multiple template checks fail, identify the single metric that participates in ALL failures:

```python
def find_root_cause(metrics, failures):
    """
    Given failures [(involved_lines, failing_line, failing_metric, ...)],
    find the single metric that is the root cause of all failures.
    
    Strategy:
    1. Intersect all involved-line sets → metrics in every failing check
    2. Among those, prefer metrics that are the RESULT of a failing check
    3. If no intersection, use frequency analysis
    """
    if not failures:
        return None
    
    all_sets = [f[0] for f in failures]
    
    # Intersection: metrics present in ALL failing checks
    intersection = all_sets[0].copy()
    for s in all_sets[1:]:
        intersection &= s
    
    result_lines = {f[1] for f in failures}
    
    if intersection:
        # Prefer metrics that are results of failing checks
        root_candidates = [ln for ln in intersection if ln in result_lines]
        if root_candidates:
            from collections import Counter
            result_counts = Counter(f[1] for f in failures)
            root_candidates.sort(key=lambda ln: -result_counts.get(ln, 0))
            root_line = root_candidates[0]
        else:
            from collections import Counter
            freq = Counter()
            for involved, _, _, _, _ in failures:
                for ln in involved:
                    freq[ln] += 1
            root_line = max(intersection, key=lambda ln: freq[ln])
    else:
        # No single metric in all failures — use frequency
        from collections import Counter
        freq = Counter()
        for involved, _, _, _, _ in failures:
            for ln in involved:
                freq[ln] += 1
        root_line = freq.most_common(1)[0][0]
    
    return next((m for m in metrics if m['line'] == root_line), None)
```

**Why root-cause analysis matters:** When a dollar value is wrong, it can cascade to multiple percentage checks. For example, if Gross Profit is wrong:
- Gross margin check fails (uses Gross Profit)
- Operating income check fails (uses Gross Profit)
- Net income check fails (uses Operating Income which uses Gross Profit)

Without root-cause analysis, the script would report the first failure. With it, the script identifies that Gross Profit appears in ALL failing checks and is therefore the root cause.

### Step 7: Robust Brute-Force Percentage Fallback

When the template catalog doesn't cover the variant's relationship type, fall back to a relationship-agnostic check. The robust version handles edge cases where the wrong percentage accidentally matches an unrelated pair:

```python
def brute_force_percentage_check_robust(metrics):
    """
    Robust brute-force that handles edge cases:
    - 0 unmatched (all match some pair): use closest-match with gap detection
    - 1 unmatched: return it
    - 2+ unmatched: use closest-match approach
    
    For each percentage, computes:
    - min_diff: minimum distance to any dollar pair
    - match_count: number of pairs within tolerance (0.15)
    
    The error is the percentage with the largest min_diff (when gap is clear).
    """
    dollars = [m for m in metrics if m['is_dollar'] and not m['is_percentage']]
    pcts = [m for m in metrics if m['is_percentage']]
    
    if not dollars or not pcts:
        return None
    
    # For each percentage, find min distance and match count
    pct_info = []
    for pct in pcts:
        min_diff = float('inf')
        match_count = 0
        for i, num in enumerate(dollars):
            for j, denom in enumerate(dollars):
                if i == j or denom['value'] == 0:
                    continue
                calc = (num['value'] / denom['value']) * 100
                diff = abs(calc - pct['value'])
                if diff < 0.15:
                    match_count += 1
                if diff < min_diff:
                    min_diff = diff
        pct_info.append({
            'metric': pct,
            'min_diff': min_diff,
            'match_count': match_count
        })
    
    # Count unmatched (0 matches within tolerance)
    unmatched = [p for p in pct_info if p['match_count'] == 0]
    
    if len(unmatched) == 1:
        # Exactly one unmatched - it's the error
        return unmatched[0]['metric']
    elif len(unmatched) == 0 or len(unmatched) >= 2:
        # All match some pair OR multiple unmatched
        # Use closest-match approach: error has largest min_diff
        pct_info.sort(key=lambda x: -x['min_diff'])
        
        # Check if there's a clear gap between top candidate and rest
        if len(pct_info) >= 2:
            gap = pct_info[0]['min_diff'] - pct_info[1]['min_diff']
            if gap > 0.3:  # Clear gap
                return pct_info[0]['metric']
        
        # No clear gap - ambiguous, but return best candidate
        return pct_info[0]['metric']
    
    return None
```

**Why the robust version matters:** The binary approach ("matches a pair or doesn't") has a false negative problem: if the wrong percentage accidentally equals some unrelated dollar ratio, it won't be flagged. The robust version computes the minimum distance to ANY pair for each percentage, then identifies the error as the percentage with the largest minimum distance. This works even when the wrong percentage accidentally matches an unrelated pair, because the correct percentages will have much smaller minimum distances (matching their intended relationships).

### Step 8: Output the Answer

```python
def format_value(metric):
    """Format the metric value for output (remove % sign, preserve original format)."""
    raw = metric['raw']
    value_str = raw.replace('%', '').replace('$', '').replace(',', '').strip()
    if value_str.startswith('(') and value_str.endswith(')'):
        value_str = '-' + value_str[1:-1]
    return value_str

# Try template-based verification first
root, failures, matched = verify_report(metrics)

if root:
    value_str = format_value(root)
    answer = f"{root['line']},{value_str}"
    with open(output_file, 'w') as f:
        f.write(answer)
else:
    # Templates found nothing — fall back to brute-force
    error_pct = brute_force_percentage_check(metrics)
    if error_pct:
        value_str = format_value(error_pct)
        answer = f"{error_pct['line']},{value_str}"
        with open(output_file, 'w') as f:
            f.write(answer)
```

## Handling Variations

### Report Structure Variations

- **Different table layouts**: Parse all `<table>` elements and extract line-numbered rows regardless of position
- **Different section names**: Use metric names (not section headers) to identify relationships
- **Different metric families**: The template catalog covers income statements, margins, per-share values, YoY growth, and common ratios
- **Line numbering density**: Line numbers may be non-sequential (e.g., 110, 120, 130...) - use the actual line numbers, not row indices
- **Reordered tables**: Scored matching ensures correct metric identification regardless of document order

### Error Type Variations

The incorrect metric may be:
- **A subtotal** (e.g., Total Operating Expenses)
- **A margin percentage** (e.g., Gross Margin, Operating Margin)
- **A year-over-year change**
- **A per-share value**
- **A rounded figure** (tolerances handle rounding)
- **A dollar value that cascades** to multiple percentage failures (root-cause analysis handles this)

### Output Format Variations

- **Target file**: May vary (check task instructions for exact path)
- **Numeric precision**: Report the value exactly as shown in the HTML (preserve decimals, don't add/remove precision)
- **Formatting**: Handle commas, negative signs (parenthetical notation), and other formatting in the output

## Robustness Considerations

1. **Scored matching over first-match**: Prevents ambiguous substring matches (e.g., "sales" matching "Sales and marketing" instead of "Revenue")
2. **Exclusion-based expense detection**: Correctly classifies expense components by excluding known non-expense lines
3. **Root-cause analysis**: Identifies the single metric responsible for all cascading failures
4. **Floating-point tolerance**: Use tolerance of 0.5 for dollar values and 0.15 for percentages to handle rounding
5. **Case-insensitive matching**: Metric names may vary in capitalization
6. **Whitespace handling**: Strip whitespace from parsed values
7. **Multiple tables**: Check all tables in the document, not just the first
8. **Parenthetical negatives**: Handle accounting notation where (123.4) means -123.4

## Key Insights

1. **Dollar values are the foundation**: The task states all dollar-denominated values are internally consistent, so use them as the ground truth for verifying percentages
2. **Single error assumption**: Exactly one metric is wrong, so root-cause analysis identifies it even when multiple checks fail
3. **Preserve original formatting**: Output the value exactly as displayed in the report (just remove the % sign)
4. **Root-cause analysis is critical**: Without it, cascading errors from a wrong dollar value would report the wrong metric
5. **Scored matching is critical**: Without it, variants with reordered tables or ambiguous metric names will fail silently
6. **Template extensibility**: Adding a new relationship type = adding a template to the catalog, not rewriting code
7. **Brute-force fallback closes coverage gaps**: When the template catalog doesn't cover a variant's relationship type, the robust brute-force check catches any percentage error regardless of metric names or relationships. The closest-match approach with gap detection handles edge cases where the wrong percentage accidentally matches an unrelated pair. This makes the skill robust to completely novel metric families.
