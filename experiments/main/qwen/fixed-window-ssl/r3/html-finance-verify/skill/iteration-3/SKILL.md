---
name: html-finance-verify
description: >
  Parse an HTML financial report containing an income statement and derived KPI
  metrics, verify internal consistency across all values, identify the single
  incorrect reported metric, and write its line number and reported value to a
  specified output file. Includes a complete ready-to-execute solver script with
  multi-strategy HTML extraction for robustness across variant structures.
---

# HTML Finance Verify

## Quick Start: Ready-to-Execute Solver

**Copy this script to `/app/solver.py` and run it.** It implements the full algorithm:
multi-strategy HTML extraction → longest-match-wins canonicalization → structural
relationships → generic discovery → violation intersection → leave-one-out tiebreaker.

```python
#!/usr/bin/env python3
"""
Flexible solver for html-finance-verify tasks.
Multi-strategy HTML extraction + violation intersection + leave-one-out tiebreaker.
"""
import re
from itertools import combinations

# ============================================================
# STEP 1: Flexible HTML Extraction (multi-strategy)
# ============================================================

def extract_financial_data(html_path):
    """Extract financial data using multiple strategies for robustness."""
    with open(html_path) as f:
        html = f.read()
    
    # Strategy 1: Specific class-based pattern (works for v01-like reports)
    rows = re.findall(
        r'<td[^>]*class="[^"]*line[^"]*"[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*(.*?)\s*</td>\s*'
        r'<td[^>]*class="[^"]*num[^"]*"[^>]*>\s*(.*?)\s*</td>',
        html, re.DOTALL
    )
    
    # Strategy 2: General table extraction (fallback for different structures)
    if not rows:
        rows = _extract_general_tables(html)
    
    # Parse extracted rows into data records
    data = []
    for line_num, metric, value in rows:
        clean = value.strip()
        is_pct = '%' in clean
        numeric_str = clean.replace('$', '').replace('%', '').replace(',', '').strip()
        if numeric_str.startswith('(') and numeric_str.endswith(')'):
            numeric_str = '-' + numeric_str[1:-1]
        try:
            data.append({
                'line': int(line_num),
                'metric': _strip_html(metric).strip(),
                'raw_value': clean,
                'numeric': float(numeric_str),
                'is_percentage': is_pct
            })
        except ValueError:
            continue  # skip non-numeric rows
    
    return data

def _strip_html(text):
    """Remove HTML tags from text."""
    return re.sub(r'<[^>]+>', '', text)

def _extract_general_tables(html):
    """
    General table extraction fallback.
    Finds all tables, extracts rows, identifies line-number column by
    looking for cells that contain only integers.
    """
    rows = []
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
    
    for table in tables:
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL)
        for tr in trs:
            # Extract all cell contents (td or th)
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.DOTALL)
            if len(cells) < 3:
                continue
            
            # Find which cell looks like a line number (pure integer)
            line_idx = None
            for i, cell in enumerate(cells):
                stripped = _strip_html(cell).strip()
                if re.match(r'^\d+$', stripped):
                    line_idx = i
                    break
            
            if line_idx is None:
                continue
            
            # The next cell should be the metric name
            # The cell after that should be the value
            if line_idx + 2 >= len(cells):
                continue
            
            line_num = _strip_html(cells[line_idx]).strip()
            metric = _strip_html(cells[line_idx + 1]).strip()
            value = _strip_html(cells[line_idx + 2]).strip()
            
            # Skip header rows (metric name looks like a header)
            if metric.lower() in ('metric', 'line', 'value', 'description', ''):
                continue
            
            # Only include if value looks financial
            if re.search(r'[\d$%]', value):
                rows.append((line_num, metric, value))
    
    return rows

# ============================================================
# STEP 2: Canonicalize metric names (longest-match-wins)
# ============================================================

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
    """Longest-match-wins to avoid substring collisions."""
    name_lower = metric_name.lower()
    best_canonical = name_lower
    best_kw_len = 0
    for canonical, keywords in NAME_PATTERNS.items():
        for kw in keywords:
            if kw in name_lower and len(kw) > best_kw_len:
                best_canonical = canonical
                best_kw_len = len(kw)
    return best_canonical

# ============================================================
# STEP 3: Build structural relationships
# ============================================================

def build_relationships(available):
    rels = []
    if all(k in available for k in ['revenue', 'cogs', 'gross_profit']):
        rels.append({'name': 'gross_profit_identity', 'required': ['revenue', 'cogs', 'gross_profit'],
                     'check': lambda L: abs(L['revenue'] - L['cogs'] - L['gross_profit']) <= 0.15})
    opex_keys = [k for k in ['rd', 'sales_marketing', 'ga', 'sga'] if k in available]
    if 'total_opex' in available and len(opex_keys) >= 2:
        rels.append({'name': 'total_opex_identity', 'required': opex_keys + ['total_opex'],
                     'check': lambda L, keys=opex_keys: abs(sum(L[k] for k in keys) - L['total_opex']) <= 0.15})
    if all(k in available for k in ['gross_profit', 'total_opex', 'operating_income']):
        rels.append({'name': 'operating_income_identity', 'required': ['gross_profit', 'total_opex', 'operating_income'],
                     'check': lambda L: abs(L['gross_profit'] - L['total_opex'] - L['operating_income']) <= 0.15})
    if 'net_income' in available and 'operating_income' in available:
        addends = [k for k in ['other_income'] if k in available]
        subtrahends = [k for k in ['other_expense', 'tax'] if k in available]
        rels.append({'name': 'net_income_identity',
                     'required': ['operating_income', 'net_income'] + addends + subtrahends,
                     'check': lambda L, a=addends, s=subtrahends: abs(
                         L['operating_income'] + sum(L[k] for k in a) - sum(L[k] for k in s) - L['net_income']) <= 0.15})
    for mn, nn in [('gross_margin', 'gross_profit'), ('operating_margin', 'operating_income'),
                   ('net_margin', 'net_income'), ('ebitda_margin', 'ebitda')]:
        if all(k in available for k in [nn, 'revenue', mn]):
            rels.append({'name': f'{mn}_ratio', 'required': [nn, 'revenue', mn],
                         'check': lambda L, n=nn, m=mn: abs(round(L[n] / L['revenue'] * 100, 1) - L[m]) <= 0.15})
    return rels

# ============================================================
# STEP 4: Generic discovery for uncovered metrics
# ============================================================

def discover_generic_percentage_relationships(data, existing):
    covered = {r['required'][-1] for r in existing if r['name'].endswith('_ratio')}
    dollar_items = [(d['canonical'], d['numeric']) for d in data if not d['is_percentage']]
    pct_items = [d for d in data if d['is_percentage'] and d['canonical'] not in covered]
    rels = []
    for pct in pct_items:
        for nn, nv in dollar_items:
            for dn, dv in dollar_items:
                if dv == 0 or nn == dn: continue
                if abs(round(nv / dv * 100, 1) - pct['numeric']) <= 0.15:
                    rels.append({'name': f'generic_pct_{pct["canonical"]}',
                                 'required': [nn, dn, pct['canonical']],
                                 'check': lambda L, n=nn, d=dn, p=pct['canonical']:
                                     abs(round(L[n] / L[d] * 100, 1) - L[p]) <= 0.15})
                    break
            else: continue
            break
    return rels

def discover_generic_dollar_relationships(data, existing):
    covered = {r['required'][-1] for r in existing if not r['name'].endswith('_ratio') and r['required']}
    dollar_items = [(d['canonical'], d['numeric']) for d in data if not d['is_percentage']]
    rels = []
    for tname, tval in dollar_items:
        if tname in covered: continue
        others = [(n, v) for n, v in dollar_items if n != tname]
        found = False
        for size in range(2, min(len(others) + 1, 5)):
            if found: break
            for combo in combinations(range(len(others)), size):
                if found: break
                cnames = [others[i][0] for i in combo]
                cvals = [others[i][1] for i in combo]
                for sb in range(2 ** size):
                    total = sum(cvals[j] * (1 if sb & (1 << j) else -1) for j in range(size))
                    if abs(total - tval) <= 0.15:
                        cn = tuple(cnames)
                        rels.append({'name': f'generic_dollar_{tname}',
                                     'required': [tname] + list(cn),
                                     'check': lambda L, t=tname, ns=cn, s=sb: abs(
                                         sum(L[ns[j]] * (1 if s & (1 << j) else -1) for j in range(len(ns))) - L[t]) <= 0.15})
                        found = True
                        break
    return rels

# ============================================================
# STEP 5: Violation intersection + tiebreaker + fallback
# ============================================================

def check_consistency(data_items, rels):
    lk = {d['canonical']: d['numeric'] for d in data_items}
    skipped = 0
    for rel in rels:
        if not all(k in lk for k in rel['required']):
            skipped += 1; continue
        if not rel['check'](lk):
            return False, skipped
    return True, skipped

def find_incorrect_metric(data):
    for d in data:
        d['canonical'] = canonicalize(d['metric'])
    available = set(d['canonical'] for d in data)
    relationships = build_relationships(available)
    relationships.extend(discover_generic_dollar_relationships(data, relationships))
    relationships.extend(discover_generic_percentage_relationships(data, relationships))
    lookup = {d['canonical']: d['numeric'] for d in data}
    violations = []
    for rel in relationships:
        if not all(k in lookup for k in rel['required']): continue
        if not rel['check'](lookup):
            violations.append(set(rel['required']))
    if not violations:
        best = None; best_rem = -1
        for c in data:
            rem = [d for d in data if d['line'] != c['line']]
            ok, sk = check_consistency(rem, relationships)
            app = len(relationships) - sk
            if ok and app > best_rem: best = c; best_rem = app
        return best
    candidates = violations[0].copy()
    for v in violations[1:]: candidates &= v
    if len(candidates) == 1:
        return next(d for d in data if d['canonical'] == candidates.pop())
    best = None; best_rem = -1
    for c in (d for d in data if d['canonical'] in candidates):
        rem = [d for d in data if d['line'] != c['line']]
        ok, sk = check_consistency(rem, relationships)
        app = len(relationships) - sk
        if ok and app > best_rem: best = c; best_rem = app
    return best

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    import sys
    
    # Determine HTML path (default: /app/q2_earnings_report.html)
    html_path = '/app/q2_earnings_report.html'
    
    # Determine output path from task instructions if available
    output_path = '/app/value.txt'
    try:
        with open('task.yaml') as f:
            task_content = f.read()
        # Look for output file path in task instructions
        m = re.search(r'`(/app/\w+\.txt)`', task_content)
        if m:
            output_path = m.group(1)
    except:
        pass
    
    data = extract_financial_data(html_path)
    if not data:
        print(f"ERROR: No financial data extracted from {html_path}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Extracted {len(data)} metrics")
    
    result = find_incorrect_metric(data)
    if result:
        val = result['raw_value'].replace('%', '').replace('$', '').strip()
        ans = f"{result['line']},{val}"
        with open(output_path, 'w') as f:
            f.write(ans + '\n')
        print(ans)
    else:
        print("ERROR: Could not find incorrect metric", file=sys.stderr)
        sys.exit(1)
```

**Usage:**
```bash
python3 /app/solver.py
cat /app/value.txt
```

## Algorithm Overview

### 1. Multi-Strategy HTML Extraction

**Critical for variant robustness**: Different variants may use different HTML structures, class names, or table layouts.

- **Strategy 1**: Specific class-based pattern (fast, works for v01-like reports with `class="line"` and `class="num"`)
- **Strategy 2**: General table extraction fallback (finds all `<table>` → `<tr>` → `<td>` patterns, identifies line-number column by looking for pure integers)

The fallback handles variants that:
- Use different class names (e.g., `class="row-num"`, `class="amount"`)
- Have no CSS classes at all
- Use different table layouts
- Mix `<td>` and `<th>` elements

### 2. Core: Violation Intersection

Since exactly ONE value is wrong, every failing relationship must involve it. The wrong value = intersection of all violation participant sets.

**Why this works**: A correct value can't cause a violation (all correct values satisfy all relationships among themselves). So the wrong value appears in every violation's participant set.

### 3. Tiebreaker: Leave-One-Out with Max-Remaining-Applicable

When the intersection has multiple candidates (e.g., only one relationship fails), remove each candidate and count how many checks remain applicable. The true error (a leaf value like a percentage) participates in few relationships, so removing it leaves many checks applicable. A foundational value (like Revenue) participates in many, so removing it skips many checks.

### 4. Canonicalization: Longest-Match-Wins

**Critical**: "Cost of revenue" must match `cogs`, not `revenue`. Using longest-match-wins prevents substring collisions where shorter keywords steal matches from longer, more specific ones.

### 5. Generic Discovery

For metrics not covered by structural relationships:
- **Percentages**: try all (numerator, denominator) pairs of dollar values
- **Dollar values**: try all signed subsets of size 2-4 of other dollar values

Generic discovery only finds relationships that **pass**. If the wrong value has no discoverable relationship, the leave-one-out fallback handles it.

## Variation Handling

| Dimension | What varies | How the solver handles it |
|-----------|-------------|---------------------------|
| Report structure | Table layout, class names, section names, line numbering | Multi-strategy HTML extraction; semantic keyword matching |
| Metric relationships | Which relation exposes the error | Structural + generic discovery; violation intersection finds root cause |
| Error type | Totals, subtotals, margins, per-share, unit conversions | Violation intersection + tiebreaker + fallback |
| Output format | Target file, numeric precision | Reads task.yaml for output path; strips `%` and `$` from values |

## Rounding and Tolerance

- Dollar values (millions, 1 decimal): tolerance 0.15
- Percentages (rounded to 1 decimal): tolerance 0.15
- Incorrect values typically differ by a meaningful amount (e.g., 1 full percentage point)

## Robustness Checklist

1. **Use the ready-to-execute script** — don't re-implement from abstract descriptions
2. **Multi-strategy HTML extraction** — handles both class-based and general table structures
3. **Longest-match canonicalization** — prevents "Cost of revenue" → 'revenue' collision
4. **Violation intersection as primary** — provably correct for root-cause identification
5. **Generic discovery as supplement** — for non-standard metrics (both percentages and dollars)
6. **Leave-one-out fallback** — when generic discovery finds no relationship for the wrong value
7. **Max-remaining-applicable tiebreaker** — when intersection has multiple candidates
8. **Report the value as shown** — preserve original formatting, strip only `%`
9. **Handle edge cases** — parentheses for negatives, commas in thousands, missing metrics
10. **Configurable output path** — reads task.yaml to determine target file
