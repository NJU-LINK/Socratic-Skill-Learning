---
name: html-finance-verify
description: >
  Parse an HTML financial report containing an income statement and derived KPI
  metrics, verify internal consistency across all values, identify the single
  incorrect reported metric, and write its line number and reported value to a
  specified output file. Uses violation intersection as the primary algorithm
  with leave-one-out tiebreaking for ambiguous cases.
---

# HTML Finance Verify

## Task Pattern

An HTML document presents a company financial snapshot with:
1. An **income statement** (or similar) table with line-numbered dollar-denominated metrics
2. One or more **KPI sections** with derived metrics (typically percentages)
3. Exactly **one** reported value is incorrect; all others are internally consistent

## Core Algorithm: Violation Intersection

**Key insight**: Since exactly ONE value is wrong, every failing relationship must involve the wrong value. No passing relationship can expose the wrong value. Therefore:

- The wrong value appears in **every** violation's participant set
- Correct values appear in only **some** violations (or none)
- The wrong value = the **intersection** of all violation participant sets

This is provably correct and handles all error types directly.

**When the intersection has multiple candidates** (typically when only one relationship fails), use leave-one-out with max-remaining-applicable-checks as tiebreaker.

## Step-by-Step Method

### Step 1: Extract All Data from HTML

```python
import re
from itertools import combinations

def extract_financial_data(html_path):
    """Extract all line-numbered financial data from an HTML report."""
    with open(html_path) as f:
        html = f.read()
    rows = re.findall(
        r'<td[^>]*class="[^"]*line[^"]*"[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*(.*?)\s*</td>\s*'
        r'<td[^>]*class="[^"]*num[^"]*"[^>]*>\s*(.*?)\s*</td>',
        html, re.DOTALL
    )
    data = []
    for line_num, metric, value in rows:
        clean = value.strip()
        is_pct = '%' in clean
        numeric_str = clean.replace('$', '').replace('%', '').replace(',', '').strip()
        if numeric_str.startswith('(') and numeric_str.endswith(')'):
            numeric_str = '-' + numeric_str[1:-1]
        data.append({
            'line': int(line_num),
            'metric': metric.strip(),
            'raw_value': clean,
            'numeric': float(numeric_str),
            'is_percentage': is_pct
        })
    return data
```

### Step 2: Canonicalize Metric Names (Longest-Match-Wins)

```python
NAME_PATTERNS = {
    'revenue':         ['total revenue', 'net sales', 'revenue', 'sales'],
    'cogs':            ['cost of revenue', 'cost of goods', 'cogs', 'cost of sales'],
    'gross_profit':    ['gross profit'],
    'rd':              ['research and development', 'r&d', 'r and d'],
    'sales_marketing': ['sales and marketing', 'selling general and marketing'],
    'ga':              ['general and admin', 'g&a', 'administrative'],
    'sga':             ['sg&a', 'selling, general', 'selling general and administrative'],
    'total_opex':      ['total operating expense', 'total opex', 'operating expenses'],
    'operating_income':['operating income', 'operating profit', 'ebit'],
    'other_income':    ['other income, net', 'other income', 'interest income', 'non-operating'],
    'other_expense':   ['other expense', 'interest expense'],
    'tax':             ['income tax', 'provision for tax', 'tax expense'],
    'net_income':      ['net income', 'net profit', 'net earnings', 'net loss'],
    'ebitda':          ['ebitda'],
    'gross_margin':    ['gross margin'],
    'operating_margin':['operating margin'],
    'net_margin':      ['net margin', 'profit margin'],
    'ebitda_margin':   ['ebitda margin'],
}

def canonicalize(metric_name):
    """Map a metric name to its canonical category.
    Uses longest-match-wins to avoid substring collisions."""
    name_lower = metric_name.lower()
    best_canonical = name_lower
    best_kw_len = 0
    for canonical, keywords in NAME_PATTERNS.items():
        for kw in keywords:
            if kw in name_lower and len(kw) > best_kw_len:
                best_canonical = canonical
                best_kw_len = len(kw)
    return best_canonical
```

### Step 3: Define Structural Relationships

```python
def build_relationships(available_canonicals):
    """Build all structural relationships based on available metrics."""
    relationships = []
    
    # Gross profit = Revenue - COGS
    if all(k in available_canonicals for k in ['revenue', 'cogs', 'gross_profit']):
        relationships.append({
            'name': 'gross_profit_identity',
            'required': ['revenue', 'cogs', 'gross_profit'],
            'check': lambda L: abs(L['revenue'] - L['cogs'] - L['gross_profit']) <= 0.15
        })
    
    # Total opex = sum of component expenses
    opex_component_keys = ['rd', 'sales_marketing', 'ga', 'sga']
    components = [k for k in opex_component_keys if k in available_canonicals]
    if 'total_opex' in available_canonicals and len(components) >= 2:
        relationships.append({
            'name': 'total_opex_identity',
            'required': components + ['total_opex'],
            'check': lambda L, keys=components: abs(sum(L[k] for k in keys) - L['total_opex']) <= 0.15
        })
    
    # Operating income = Gross profit - Total opex
    if all(k in available_canonicals for k in ['gross_profit', 'total_opex', 'operating_income']):
        relationships.append({
            'name': 'operating_income_identity',
            'required': ['gross_profit', 'total_opex', 'operating_income'],
            'check': lambda L: abs(L['gross_profit'] - L['total_opex'] - L['operating_income']) <= 0.15
        })
    
    # Net income = Operating income + Other income - Other expense - Tax
    if 'net_income' in available_canonicals and 'operating_income' in available_canonicals:
        addends = [k for k in ['other_income'] if k in available_canonicals]
        subtrahends = [k for k in ['other_expense', 'tax'] if k in available_canonicals]
        relationships.append({
            'name': 'net_income_identity',
            'required': ['operating_income', 'net_income'] + addends + subtrahends,
            'check': lambda L, a=addends, s=subtrahends: abs(
                L['operating_income'] + sum(L[k] for k in a) - sum(L[k] for k in s) - L['net_income']
            ) <= 0.15
        })
    
    # Percentage relationships
    margin_defs = [
        ('gross_margin', 'gross_profit'),
        ('operating_margin', 'operating_income'),
        ('net_margin', 'net_income'),
        ('ebitda_margin', 'ebitda'),
    ]
    for margin_name, numerator_name in margin_defs:
        if all(k in available_canonicals for k in [numerator_name, 'revenue', margin_name]):
            relationships.append({
                'name': f'{margin_name}_ratio',
                'required': [numerator_name, 'revenue', margin_name],
                'check': lambda L, n=numerator_name, m=margin_name: (
                    abs(round(L[n] / L['revenue'] * 100, 1) - L[m]) <= 0.15
                )
            })
    
    return relationships
```

### Step 4: Generic Discovery for Unknown Relationships

For metrics not covered by structural relationships, discover relationships by trying all possible derivations.

**Important limitation**: Generic discovery only finds relationships that **pass** (are consistent with the data). If a value is wrong, the generic discovery might not find any relationship for it, resulting in no violations. This is acceptable because:
1. Structural relationships cover standard income statement patterns
2. Generic discovery supplements structural relationships for non-standard metrics
3. The violation intersection + tiebreaker handles cases where generic discovery finds no relationship for the wrong value

```python
def discover_generic_percentage_relationships(data, structural_relationships):
    """Find percentage relationships not covered by structural checks."""
    covered_pcts = set()
    for r in structural_relationships:
        if r['name'].endswith('_ratio'):
            covered_pcts.add(r['required'][-1])
    
    dollar_items = [(d['canonical'], d['numeric']) for d in data if not d['is_percentage']]
    pct_items = [d for d in data if d['is_percentage'] and d['canonical'] not in covered_pcts]
    
    relationships = []
    for pct in pct_items:
        for num_name, num_val in dollar_items:
            for den_name, den_val in dollar_items:
                if den_val == 0 or num_name == den_name:
                    continue
                expected = round(num_val / den_val * 100, 1)
                if abs(expected - pct['numeric']) <= 0.15:
                    relationships.append({
                        'name': f'generic_pct_{pct["canonical"]}',
                        'required': [num_name, den_name, pct['canonical']],
                        'check': lambda L, n=num_name, d=den_name, p=pct['canonical']: (
                            abs(round(L[n] / L[d] * 100, 1) - L[p]) <= 0.15
                        )
                    })
                    break
            else:
                continue
            break
    
    return relationships

def discover_generic_dollar_relationships(data, structural_relationships):
    """Find additive/subtractive relationships not covered by structural checks.
    
    For each dollar value not covered by structural relationships, try all subsets
    of size 2-4 of other dollar values with all sign combinations. If a subset sums
    to the target, add it as a relationship.
    """
    # Identify which dollar values are covered by structural relationships
    covered = set()
    for r in structural_relationships:
        if not r['name'].endswith('_ratio'):
            # For structural relationships, the "result" is typically the last element
            if r['required']:
                covered.add(r['required'][-1])
    
    dollar_items = [(d['canonical'], d['numeric']) for d in data if not d['is_percentage']]
    relationships = []
    
    for target_name, target_val in dollar_items:
        if target_name in covered:
            continue
        
        others = [(n, v) for n, v in dollar_items if n != target_name]
        found = False
        
        for size in range(2, min(len(others) + 1, 5)):
            if found:
                break
            for combo in combinations(range(len(others)), size):
                if found:
                    break
                combo_names = [others[i][0] for i in combo]
                combo_vals = [others[i][1] for i in combo]
                
                for sign_bits in range(2 ** size):
                    total = sum(
                        combo_vals[j] * (1 if sign_bits & (1 << j) else -1)
                        for j in range(size)
                    )
                    if abs(total - target_val) <= 0.15:
                        captured_names = tuple(combo_names)
                        captured_signs = sign_bits
                        relationships.append({
                            'name': f'generic_dollar_{target_name}',
                            'required': [target_name] + list(captured_names),
                            'check': lambda L, t=target_name, ns=captured_names, 
                                     sb=captured_signs: abs(
                                sum(L[ns[j]] * (1 if sb & (1 << j) else -1) 
                                    for j in range(len(ns))) - L[t]
                            ) <= 0.15
                        })
                        found = True
                        break
    
    return relationships
```

### Step 5: Violation Intersection + Tiebreaker

```python
def find_incorrect_metric(data):
    """
    Violation intersection: the wrong value appears in every failing relationship.
    Tiebreaker: leave-one-out with max-remaining-applicable-checks for ambiguous cases.
    """
    for d in data:
        d['canonical'] = canonicalize(d['metric'])
    
    available = set(d['canonical'] for d in data)
    relationships = build_relationships(available)
    relationships.extend(discover_generic_dollar_relationships(data, relationships))
    relationships.extend(discover_generic_percentage_relationships(data, relationships))
    
    # Check ALL relationships against FULL data
    lookup = {d['canonical']: d['numeric'] for d in data}
    violations = []
    
    for rel in relationships:
        if not all(k in lookup for k in rel['required']):
            continue
        if not rel['check'](lookup):
            violations.append(set(rel['required']))
    
    if not violations:
        # No violations found — use leave-one-out as fallback
        # This handles cases where generic discovery found no relationship for the wrong value
        return _leave_one_out_fallback(data, relationships)
    
    # Intersection of all violation participant sets
    candidates = violations[0].copy()
    for v in violations[1:]:
        candidates = candidates & v
    
    if len(candidates) == 1:
        target = candidates.pop()
        return next(d for d in data if d['canonical'] == target)
    
    # Tiebreaker: leave-one-out with max-remaining-applicable-checks
    def check_consistency(data_items, rels):
        lk = {d['canonical']: d['numeric'] for d in data_items}
        skipped = 0
        for rel in rels:
            if not all(k in lk for k in rel['required']):
                skipped += 1
                continue
            if not rel['check'](lk):
                return False, skipped
        return True, skipped
    
    candidate_data = [d for d in data if d['canonical'] in candidates]
    best = None
    best_remaining = -1
    
    for cand in candidate_data:
        remaining = [d for d in data if d['line'] != cand['line']]
        consistent, skipped = check_consistency(remaining, relationships)
        applicable = len(relationships) - skipped
        if consistent and applicable > best_remaining:
            best = cand
            best_remaining = applicable
    
    return best

def _leave_one_out_fallback(data, relationships):
    """Fallback when no violations are found. Try removing each value and check consistency."""
    def check_consistency(data_items, rels):
        lk = {d['canonical']: d['numeric'] for d in data_items}
        skipped = 0
        for rel in rels:
            if not all(k in lk for k in rel['required']):
                skipped += 1
                continue
            if not rel['check'](lk):
                return False, skipped
        return True, skipped
    
    best = None
    best_remaining = -1
    
    for cand in data:
        remaining = [d for d in data if d['line'] != cand['line']]
        consistent, skipped = check_consistency(remaining, relationships)
        applicable = len(relationships) - skipped
        if consistent and applicable > best_remaining:
            best = cand
            best_remaining = applicable
    
    return best
```

### Step 6: Output the Answer

```python
def write_answer(violation, output_path='/app/value.txt'):
    value_str = violation['raw_value'].replace('%', '').replace('$', '').strip()
    with open(output_path, 'w') as f:
        f.write(f"{violation['line']},{value_str}\n")
```

## Why Violation Intersection is Provably Correct

**Proof sketch**:
1. Exactly one value is wrong; all others are internally consistent
2. A correct value cannot cause a relationship to fail
3. Therefore, every failing relationship must involve the wrong value
4. The wrong value appears in every violation's participant set
5. The intersection of all violation sets contains the wrong value
6. If the intersection has exactly one element → that's the answer
7. If the intersection has multiple elements → use tiebreaker

**Tiebreaker correctness**: When only one relationship fails, the intersection contains all participants. The tiebreaker removes each candidate and counts remaining applicable checks. The true error (a leaf value) participates in few relationships, so removing it leaves many checks applicable. A foundational value participates in many relationships, so removing it skips many checks.

## Fallback for Non-Standard Structures

When generic discovery finds no relationship for the wrong value (resulting in zero violations), the leave-one-out fallback identifies the value whose removal leaves the most applicable checks. This handles non-standard income statement structures where structural relationships don't cover all metrics.

## Variation Handling

| Dimension | What varies | Invariant approach |
|-----------|-------------|-------------------|
| Report structure | Table layout, section names, line numbering density | Parse all tables generically via regex; match by metric semantics |
| Metric relationships | Which arithmetic/ratio relation exposes the error | Violation intersection finds the root cause directly |
| Error type | Totals, subtotals, margins, YoY changes, per-share, unit conversions | Violation intersection + tiebreaker + fallback handles all types |
| Output format | Target file, numeric precision, comma/whitespace handling | Read task instructions for exact format; strip `%` and `$` from values |

## Rounding and Tolerance

- Dollar values in millions: typically 1 decimal place → tolerance 0.15
- Percentages rounded to 1 decimal place → tolerance 0.15
- Use tolerance 0.15 for rounded values and 0.01 for exact values

## Robustness Checklist

1. **Parse generically** — don't hardcode line numbers, metric positions, or table structures
2. **Longest-match canonicalization** — prevents substring collisions
3. **Violation intersection as primary** — provably correct, handles standard patterns
4. **Generic discovery as supplement** — for non-standard metrics (percentages and dollar values)
5. **Leave-one-out fallback** — for cases where generic discovery finds no relationship for the wrong value
6. **Tiebreaker with max-remaining-applicable** — when intersection has multiple candidates
7. **Report the value as shown** — preserve original formatting, strip only `%`
8. **Handle edge cases** — parentheses for negatives, commas in thousands, missing metrics
