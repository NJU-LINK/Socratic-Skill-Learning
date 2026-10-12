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

## Execution Procedure

### Step 0: Execute the Pre-Built Solver (Primary Path)

**Before implementing anything manually, execute the tested solver.** The skill package includes `solve.py`, a complete implementation with constraint-based localization, N-way relationship discovery, and multi-layered fallback logic.

```bash
# Copy solve.py from the skill package to /app and run it
cp /skill/solve.py /app/solve.py
cd /app && python3 solve.py
```

**If solve.py succeeds** (produces `/app/value.txt` with a valid answer), verify the output format matches task requirements and you're done.

**If solve.py fails or is not available**, follow Steps 1-5 below to implement the approach manually.

---

### Step 1: Read Task Instructions

Read `task.yaml` to determine:
- **HTML file path** (e.g., `/app/q2_earnings_report.html`)
- **Output file path** (e.g., `/app/value.txt`)
- **Output format** (e.g., `line_number,value`)
- **Value formatting** (no percent sign, decimal precision, etc.)

### Step 2: Extract All Metrics from HTML

Use `task_shell` (not the `read` tool) to access files inside `/app/`. The `read` tool cannot access paths outside the experiment workspace.

```bash
# Use task_shell to read the HTML file
cat /app/q2_earnings_report.html
```

Then extract every (line_number, metric_name, value) tuple.

**Robust extraction strategy** (handles varied HTML structures):

```python
import re

def extract_metrics(html_content):
    """Extract metrics from HTML tables with line numbers."""
    metrics = []
    
    # Find all table rows
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_content, re.DOTALL)
    
    for row in rows:
        # Extract all table cells
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        
        if len(cells) >= 3:
            # Strip HTML tags from each cell
            cell_texts = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            
            # Check if first cell is a line number (all digits)
            if re.match(r'^\d+$', cell_texts[0]):
                line_num = int(cell_texts[0])
                metric_name = cell_texts[1]
                raw_value = cell_texts[2]
                
                # Parse numeric value
                value = parse_numeric(raw_value)
                is_percentage = '%' in raw_value
                
                if value is not None:
                    metrics.append({
                        'line': line_num,
                        'name': metric_name,
                        'raw_value': raw_value,
                        'value': value,
                        'is_percentage': is_percentage
                    })
    
    return metrics

def parse_numeric(raw):
    """Parse numeric values with various formats."""
    s = raw.strip()
    
    # Handle parenthetical negatives: (123.45) → -123.45
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    
    # Remove formatting characters
    s = s.replace('$', '').replace(',', '').replace('%', '').strip()
    
    # Remove unit suffixes (M, B, K for millions, billions, thousands)
    s = re.sub(r'\s*[MBKmk](?:illion|illion)?\s*$', '', s)
    
    # Handle empty/dash values
    if not s or s in ['—', '-', '–', 'N/A']:
        return None
    
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None
```

### Step 3: Discover All Relationships

Build a comprehensive set of verifiable relationships. Each relationship is a check that should hold if all values are correct.

#### A. Additive Relationships (Income Statement Flow)

Standard financial statement relationships:

```python
def discover_additive_relationships(metrics):
    """Discover sum/difference relationships between metrics."""
    relationships = []
    by_name = {normalize_name(m['name']): m for m in metrics}
    non_pct = [m for m in metrics if not m['is_percentage']]
    
    # Common patterns (normalized names)
    patterns = {
        # total = component1 + component2 + ...
        'totaloperatingexpenses': [
            ['researchanddevelopment', 'salesandmarketing', 'generalandadministrative'],
            ['researchanddevelopment', 'sellinggeneralandadministrative'],
        ],
        'totalrevenue': [
            ['productrevenue', 'servicerevenue'],
        ],
        # minuend = subtrahend + result (e.g., revenue = cost + gross_profit)
        'revenue': [['grossprofit', 'costofrevenue']],
    }
    
    # Check name-based patterns
    for total_norm, component_sets in patterns.items():
        if total_norm not in by_name:
            continue
        total_m = by_name[total_norm]
        for comp_names in component_sets:
            components = [by_name[cn] for cn in comp_names if cn in by_name]
            if len(components) == len(comp_names):
                relationships.append((total_m, components, 'sum'))
                break
    
    # Explicit difference relationships
    if all(k in by_name for k in ['grossprofit', 'revenue', 'costofrevenue']):
        relationships.append((by_name['grossprofit'], 
                             [by_name['revenue'], by_name['costofrevenue']], 
                             'difference'))
    
    if all(k in by_name for k in ['operatingincome', 'grossprofit', 'totaloperatingexpenses']):
        relationships.append((by_name['operatingincome'],
                             [by_name['grossprofit'], by_name['totaloperatingexpenses']],
                             'difference'))
    
    if all(k in by_name for k in ['netincome', 'operatingincome', 'otherincomenet']):
        relationships.append((by_name['netincome'],
                             [by_name['operatingincome'], by_name['otherincomenet']],
                             'sum'))
    
    # Value-based discovery: try all N-way combinations (N=2,3,4)
    for total_m in non_pct:
        if any(r[0]['line'] == total_m['line'] for r in relationships):
            continue  # Already have a relationship for this metric
        
        others = [m for m in non_pct if m['line'] != total_m['line']]
        for n in range(2, min(5, len(others) + 1)):
            from itertools import combinations
            for combo in combinations(others, n):
                if abs(sum(c['value'] for c in combo) - total_m['value']) < 0.15:
                    relationships.append((total_m, list(combo), 'sum'))
                    break
    
    return relationships
```

#### B. Ratio/Percentage Relationships (KPIs)

Common margin and rate calculations:

```python
def discover_ratio_relationships(metrics):
    """Discover ratio relationships (percentage = numerator / denominator * 100)."""
    relationships = []
    by_name = {normalize_name(m['name']): m for m in metrics}
    percentages = [m for m in metrics if m['is_percentage']]
    non_pct = [m for m in metrics if not m['is_percentage']]
    
    # Find revenue (common denominator for margins)
    revenue = next((m for m in non_pct if 'revenue' in m['name'].lower() 
                    and 'cost' not in m['name'].lower()), None)
    
    if not revenue and non_pct:
        revenue = max(non_pct, key=lambda m: abs(m['value']))
    
    # Known margin patterns
    margin_patterns = {
        'grossmargin': ('grossprofit', 'revenue'),
        'operatingmargin': ('operatingincome', 'revenue'),
        'netmargin': ('netincome', 'revenue'),
        'netprofitmargin': ('netincome', 'revenue'),
        'pretaxmargin': ('pretaxincome', 'revenue'),
    }
    
    for pct_m in percentages:
        pct_norm = normalize_name(pct_m['name'])
        
        # Check known patterns
        if pct_norm in margin_patterns:
            num_name, den_name = margin_patterns[pct_norm]
            if num_name in by_name and den_name in by_name:
                relationships.append((pct_m, by_name[num_name], by_name[den_name]))
                continue
        
        # Generic: try all non-percentage metrics as numerator
        if revenue:
            for num_m in non_pct:
                if num_m['line'] == revenue['line']:
                    continue
                expected = num_m['value'] / revenue['value'] * 100
                if abs(expected - pct_m['value']) < 0.5:
                    relationships.append((pct_m, num_m, revenue))
                    break
    
    return relationships
```

#### C. Year-over-Year Growth Relationships

For variants with current/prior period data:

```python
def discover_growth_relationships(metrics):
    """Discover YoY growth relationships: growth% = (current - prior) / |prior| * 100."""
    relationships = []
    percentages = [m for m in metrics if m['is_percentage']]
    non_pct = [m for m in metrics if not m['is_percentage']]
    
    # Look for metrics with "growth" or "change" in name
    for pct_m in percentages:
        name_lower = pct_m['name'].lower()
        if 'growth' not in name_lower and 'change' not in name_lower:
            continue
        
        # Try to find current/prior pairs
        # Heuristic: look for metrics with similar names but different periods
        # e.g., "Revenue Q2 2025" and "Revenue Q2 2024"
        for curr_m in non_pct:
            for prior_m in non_pct:
                if curr_m['line'] == prior_m['line']:
                    continue
                # Check if names are similar (same base metric, different period)
                if names_are_similar(curr_m['name'], prior_m['name']):
                    if prior_m['value'] != 0:
                        expected = (curr_m['value'] - prior_m['value']) / abs(prior_m['value']) * 100
                        if abs(expected - pct_m['value']) < 1.0:
                            relationships.append((pct_m, curr_m, prior_m, 'growth'))
    
    return relationships

def names_are_similar(name1, name2):
    """Check if two metric names refer to the same base metric."""
    # Remove period indicators (Q1, Q2, 2024, 2025, etc.)
    base1 = re.sub(r'\b(q[1-4]|fy)?\s*\d{4}\b', '', name1.lower()).strip()
    base2 = re.sub(r'\b(q[1-4]|fy)?\s*\d{4}\b', '', name2.lower()).strip()
    return base1 == base2 and base1 != ''
```

#### D. Per-Share Relationships

For variants with EPS or per-share metrics:

```python
def discover_pershare_relationships(metrics):
    """Discover per-share relationships: EPS = net_income / shares_outstanding."""
    relationships = []
    by_name = {normalize_name(m['name']): m for m in metrics}
    
    # Look for EPS metric
    eps_metric = None
    for m in metrics:
        if 'eps' in m['name'].lower() or 'earningspershare' in normalize_name(m['name']):
            eps_metric = m
            break
    
    if not eps_metric:
        return relationships
    
    # Find net income and shares outstanding
    net_income = by_name.get('netincome')
    shares = None
    for m in metrics:
        if 'share' in m['name'].lower() and not m['is_percentage']:
            if 'outstanding' in m['name'].lower() or 'diluted' in m['name'].lower():
                shares = m
                break
    
    if net_income and shares and shares['value'] != 0:
        # EPS is usually in dollars, not percentage
        expected = net_income['value'] / shares['value']
        if abs(expected - eps_metric['value']) < 0.01:
            relationships.append((eps_metric, net_income, shares, 'pershare'))
    
    return relationships
```

#### E. Unit Conversion Relationships

For variants with mixed units (thousands, millions, billions):

```python
def discover_unit_relationships(metrics):
    """Discover unit conversion relationships (e.g., $1,234K = $1.234M)."""
    relationships = []
    
    # Look for metrics with unit suffixes in raw_value
    for m in metrics:
        raw = m['raw_value'].upper()
        if 'K' in raw or 'M' in raw or 'B' in raw:
            # This metric has a unit suffix
            # Try to find an equivalent metric without suffix
            for other in metrics:
                if other['line'] == m['line']:
                    continue
                # Check if values match after unit conversion
                if 'K' in raw and abs(m['value'] * 1000 - other['value']) < 1:
                    relationships.append((m, other, 'unit_k'))
                elif 'M' in raw and abs(m['value'] * 1_000_000 - other['value']) < 1000:
                    relationships.append((m, other, 'unit_m'))
                elif 'B' in raw and abs(m['value'] * 1_000_000_000 - other['value']) < 1_000_000:
                    relationships.append((m, other, 'unit_b'))
    
    return relationships
```

### Step 4: Build All Checks and Apply Constraint-Based Localization

Convert all relationships into verifiable checks, then find the single metric whose correction resolves all violations.

```python
def gather_all_checks(metrics):
    """Build all verifiable checks from discovered relationships."""
    checks = []
    
    # Additive checks
    for total_m, components, rel_type in discover_additive_relationships(metrics):
        participants = {total_m['line']} | {c['line'] for c in components}
        
        if rel_type == 'sum':
            expected = sum(c['value'] for c in components)
        elif rel_type == 'difference':
            expected = components[0]['value'] - components[1]['value']
        else:
            continue
        
        passes = abs(expected - total_m['value']) <= 0.15
        checks.append({
            'participants': participants,
            'passes': passes,
            'description': f"{rel_type.upper()}: {total_m['name']}"
        })
    
    # Ratio checks
    for ratio_m, num_m, den_m in discover_ratio_relationships(metrics):
        if den_m['value'] == 0:
            continue
        participants = {ratio_m['line'], num_m['line'], den_m['line']}
        expected = num_m['value'] / den_m['value'] * 100
        passes = abs(expected - ratio_m['value']) <= 0.15
        checks.append({
            'participants': participants,
            'passes': passes,
            'description': f"RATIO: {ratio_m['name']}"
        })
    
    # Growth checks
    for pct_m, curr_m, prior_m, rel_type in discover_growth_relationships(metrics):
        participants = {pct_m['line'], curr_m['line'], prior_m['line']}
        if prior_m['value'] != 0:
            expected = (curr_m['value'] - prior_m['value']) / abs(prior_m['value']) * 100
            passes = abs(expected - pct_m['value']) <= 0.5
            checks.append({
                'participants': participants,
                'passes': passes,
                'description': f"GROWTH: {pct_m['name']}"
            })
    
    return checks

def find_incorrect_metric(metrics, checks):
    """
    Constraint-based single-fault localization.
    
    If metric S is the ONLY wrong value:
    - ALL checks involving S must FAIL (S's wrong value propagates)
    - ALL checks NOT involving S must PASS (they're independent)
    """
    failing = [c for c in checks if not c['passes']]
    passing = [c for c in checks if c['passes']]
    
    if not failing:
        return None  # No violations found
    
    # For each candidate line, classify checks
    all_lines = set()
    for check in checks:
        all_lines.update(check['participants'])
    
    for suspect_line in sorted(all_lines):
        involving_pass = sum(1 for c in passing if suspect_line in c['participants'])
        involving_fail = sum(1 for c in failing if suspect_line in c['participants'])
        unrelated_fail = sum(1 for c in failing if suspect_line not in c['participants'])
        
        # Strict: no unrelated failures, all involving checks fail
        if unrelated_fail == 0 and involving_fail > 0 and involving_pass == 0:
            return next(m for m in metrics if m['line'] == suspect_line)
    
    # Relaxed: allow involving passes
    for suspect_line in sorted(all_lines):
        involving_fail = sum(1 for c in failing if suspect_line in c['participants'])
        unrelated_fail = sum(1 for c in failing if suspect_line not in c['participants'])
        
        if unrelated_fail == 0 and involving_fail > 0:
            return next(m for m in metrics if m['line'] == suspect_line)
    
    # Fallback: metric involved in most failures
    from collections import Counter
    counts = Counter()
    for check in failing:
        for line in check['participants']:
            counts[line] += 1
    
    most_common = counts.most_common(1)[0][0]
    return next(m for m in metrics if m['line'] == most_common)
```

### Step 5: Output the Answer

Format the output according to task instructions:

```python
def format_output(error_metric):
    """Format the output value — preserve the value as shown in the report."""
    raw = error_metric['raw_value']
    
    # Remove formatting characters but preserve the numeric representation
    clean = raw.strip()
    clean = clean.replace('$', '').replace(',', '').replace('%', '')
    clean = re.sub(r'\s*[MBKmk](?:illion)?\s*$', '', clean)
    
    # Handle parenthetical negatives: (45.2) → 45.2 (strip parens, don't add minus)
    # The task says output the value "as shown" — keep the numeric digits as-is
    if clean.startswith('(') and clean.endswith(')'):
        clean = clean[1:-1]
    
    return clean

# Write output
output_line = f"{error_metric['line']},{format_output(error_metric)}"
with open(output_path, 'w') as f:
    f.write(output_line)
```

## Key Principles

1. **Internal consistency only**: The error is always discoverable from relationships within the report. No external knowledge needed.

2. **Exactly one error**: There is always exactly one incorrect metric.

3. **Constraint satisfaction over heuristics**: Don't assume "ratio violation → ratio is wrong." Use constraint-based localization to find the unique metric whose correction resolves all violations.

4. **Report the wrong value**: Output the value as displayed, not the corrected value.

5. **Read task instructions**: Always check task.yaml for output file path, format, and value formatting requirements.

## Tolerance and Rounding

- Dollar values: ±0.15 tolerance (accounts for rounding in chained calculations)
- Percentages: ±0.15 percentage points for 1-decimal precision, ±0.6 for 0-decimal
- Growth rates: ±0.5 percentage points
- Always round computed values to the same precision as reported values before comparing

## Common Pitfalls

- **Using heuristics for error localization**: "Ratio violation means ratio is wrong" breaks when dollar values are the error. Use constraint satisfaction.

- **Forgetting to check PASSING checks**: If a metric participates in both passing and failing checks, the passing checks prove it's correct. Only metrics with ALL failing checks (and no passing checks) can be the error.

- **Missing N-way additive relationships**: Real income statements have 3+ component sums (e.g., Total OpEx = R&D + S&M + G&A). Check combinations up to 4-way.

- **Ignoring task instructions**: Output format, file path, and value formatting vary by variant. Always read task.yaml.

- **Incomplete relationship discovery**: Cover all relationship types: additive, ratio, growth, per-share, unit conversion.
