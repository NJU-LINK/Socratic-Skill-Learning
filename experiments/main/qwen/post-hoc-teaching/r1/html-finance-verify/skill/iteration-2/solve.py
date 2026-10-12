#!/usr/bin/env python3
"""
HTML Financial Verification - General Solver (v2)

Parses an HTML financial report, extracts line-numbered metrics,
verifies internal consistency using constraint-based single-fault
localization, and identifies the single incorrect metric.

Key improvement over v1: Instead of heuristically assuming "ratio violations
mean the ratio is wrong," this version tests each suspect metric to see if
correcting it would resolve ALL violations. This handles errors in dollar
values (totals, subtotals) as well as percentages.
"""
import re
import os
import sys
from collections import Counter


def find_html_files(directory='/app'):
    """Find all HTML files in the given directory."""
    html_files = []
    for f in sorted(os.listdir(directory)):
        if f.endswith('.html') or f.endswith('.htm'):
            html_files.append(os.path.join(directory, f))
    return html_files


def parse_numeric(raw):
    """Parse various numeric formats to float."""
    s = raw.strip()
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    s = s.replace('$', '').replace(',', '').replace('%', '').strip()
    # Strip trailing unit suffixes like M, B, K
    s = re.sub(r'\s*[MBKmk](?:illion|illion)?\s*$', '', s)
    if not s or s == '—' or s == '-' or s == '–':
        return None
    val = float(s)
    return -val if negative else val


def extract_metrics_from_html(html_content):
    """
    Extract metrics from HTML using a flexible table-row parser.
    Returns list of dicts: {line, name, raw_value, value, is_percentage}
    """
    metrics = []

    # Strategy: Look for table rows with cells
    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    cell_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)

    for row_match in row_pattern.finditer(html_content):
        row_html = row_match.group(1)
        cells = cell_pattern.findall(row_html)

        if len(cells) >= 3:
            cell_texts = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]

            # Check if first cell looks like a line number
            line_text = cell_texts[0]
            if re.match(r'^\d+$', line_text):
                line_num = int(line_text)
                name = cell_texts[1]
                raw_value = cell_texts[2]
                is_pct = '%' in raw_value
                value = parse_numeric(raw_value)

                if value is not None:
                    metrics.append({
                        'line': line_num,
                        'name': name,
                        'raw_value': raw_value,
                        'value': value,
                        'is_percentage': is_pct
                    })

    return metrics


def normalize_name(name):
    """Normalize metric name for matching."""
    return re.sub(r'[^a-z0-9]', '', name.lower())


def discover_additive_relationships(metrics):
    """
    Discover which metrics are sums/differences of other metrics.
    Returns list of (total_metric, [component_metrics], relation_type) tuples.

    Handles both 2-way and N-way additive relationships.
    """
    by_name = {}
    for m in metrics:
        by_name[normalize_name(m['name'])] = m

    relationships = []
    non_percentage = [m for m in metrics if not m['is_percentage']]

    # ---- Name-based patterns ----
    # These map a total/derived metric to its expected components.
    # Each entry: normalized_total_name -> list of possible component sets
    # (we try each set; if all components exist, we use that set)
    additive_patterns = {
        'grossprofit': [
            # gross profit = revenue - cost of revenue
            # We handle this as a difference: revenue = gross_profit + cost_of_revenue
            # Or: gross_profit + cost_of_revenue = revenue
        ],
        'totaloperatingexpenses': [
            ['researchanddevelopment', 'salesandmarketing', 'generalandadministrative'],
            ['researchanddevelopment', 'salesandmarketing', 'generalandadministrative', 'depreciationandamortization'],
            ['researchanddevelopment', 'sellinggeneralandadministrative'],
            ['rd', 'sm', 'ga'],
        ],
        'operatingincome': [
            # operating_income = gross_profit - total_operating_expenses
        ],
        'totalrevenue': [
            ['productrevenue', 'servicerevenue'],
            ['revenuen', 'productrevenue', 'servicerevenue'],
        ],
        'costofrevenue': [
            ['costofgoods', 'costofproducts', 'costofservices'],
        ],
        'totalcostofrevenue': [
            ['costofgoods', 'costofproducts', 'costofservices'],
        ],
        'incometaxexpense': [
            # income_tax = pretax_income * tax_rate (handled separately)
        ],
        'pretaxincome': [
            ['operatingincome', 'otherincomenet'],
            ['operatingincome', 'otherincome', 'interestincome', 'interestexpense'],
        ],
        'netincome': [
            ['pretaxincome', 'incometaxexpense'],
            ['operatingincome', 'otherincomenet', 'incometaxexpense'],
        ],
    }

    # For difference-based patterns (A = B - C), we encode as: B = A + C
    # i.e., the "total" is the minuend, components are subtrahend + result
    difference_patterns = {
        'revenue': [
            # revenue = gross_profit + cost_of_revenue
            ['grossprofit', 'costofrevenue'],
        ],
        'grossprofit': [
            # gross_profit = revenue - cost_of_revenue
            # encoded as: revenue = gross_profit + cost_of_revenue (handled above)
        ],
        'operatingincome': [
            # operating_income = gross_profit - total_operating_expenses
            # encoded as: gross_profit = operating_income + total_operating_expenses
        ],
    }

    # Check name-based sum patterns
    for total_norm, component_sets in additive_patterns.items():
        if total_norm not in by_name:
            continue
        total_m = by_name[total_norm]
        for comp_names in component_sets:
            components = [by_name[cn] for cn in comp_names if cn in by_name]
            if len(components) == len(comp_names) and len(components) >= 2:
                relationships.append((total_m, components, 'sum'))
                break  # Use first matching component set

    # Check difference-based patterns:
    # For "revenue = gross_profit + cost_of_revenue"
    for total_norm, component_sets in difference_patterns.items():
        if total_norm not in by_name:
            continue
        total_m = by_name[total_norm]
        for comp_names in component_sets:
            components = [by_name[cn] for cn in comp_names if cn in by_name]
            if len(components) == len(comp_names) and len(components) >= 2:
                relationships.append((total_m, components, 'sum'))
                break

    # Also encode: gross_profit = revenue - cost_of_revenue
    # as a check where total=gross_profit, and we check revenue - cost = gross_profit
    if 'grossprofit' in by_name and 'revenue' in by_name and 'costofrevenue' in by_name:
        gp = by_name['grossprofit']
        rev = by_name['revenue']
        cor = by_name['costofrevenue']
        # Check if we already have this relationship
        already_have = any(r[0]['line'] == gp['line'] for r in relationships)
        if not already_have:
            # Encode as: total=gp, components=[rev, cor], type='difference' (rev - cor = gp)
            relationships.append((gp, [rev, cor], 'difference'))

    # Encode: operating_income = gross_profit - total_operating_expenses
    if 'operatingincome' in by_name and 'grossprofit' in by_name and 'totaloperatingexpenses' in by_name:
        oi = by_name['operatingincome']
        gp = by_name['grossprofit']
        toe = by_name['totaloperatingexpenses']
        already_have = any(r[0]['line'] == oi['line'] for r in relationships)
        if not already_have:
            relationships.append((oi, [gp, toe], 'difference'))

    # Encode: net_income = operating_income + other_income - tax
    # Or simpler: net_income = pretax_income - tax
    if 'netincome' in by_name and 'pretaxincome' in by_name and 'incometaxexpense' in by_name:
        ni = by_name['netincome']
        pti = by_name['pretaxincome']
        tax = by_name['incometaxexpense']
        already_have = any(r[0]['line'] == ni['line'] for r in relationships)
        if not already_have:
            relationships.append((ni, [pti, tax], 'difference'))

    # ---- Value-based discovery ----
    # Try to find N-way sums (N=2,3,4) among non-percentage metrics
    # Only for metrics whose names suggest they are totals
    for total_m in non_percentage:
        name_lower = total_m['name'].lower()
        is_total_like = ('total' in name_lower or 'subtotal' in name_lower or
                         'income' in name_lower or 'profit' in name_lower or
                         'expense' in name_lower or 'revenue' in name_lower)
        if not is_total_like:
            continue

        # Skip if we already have a name-based relationship for this metric
        already_have = any(r[0]['line'] == total_m['line'] for r in relationships)
        if already_have:
            continue

        others = [m for m in non_percentage if m['line'] != total_m['line']]

        # Try sums of 2, 3, 4 components
        for n in range(2, min(5, len(others) + 1)):
            found = False
            _try_combinations(others, n, total_m, relationships)
            if any(r[0]['line'] == total_m['line'] for r in relationships):
                found = True
                break

    return relationships


def _try_combinations(others, n, total_m, relationships):
    """Try all n-combinations of others to see if they sum to total_m."""
    from itertools import combinations
    for combo in combinations(others, n):
        combo_sum = sum(c['value'] for c in combo)
        if abs(combo_sum - total_m['value']) < 0.15:
            relationships.append((total_m, list(combo), 'sum'))
            return True
        # Also check if total = first - sum(rest)
        if n >= 2:
            for i, first in enumerate(combo):
                rest = [c for j, c in enumerate(combo) if j != i]
                rest_sum = sum(c['value'] for c in rest)
                if abs(first['value'] - rest_sum - total_m['value']) < 0.15:
                    # total = first - rest_sum, encode as difference
                    relationships.append((total_m, [first] + rest, 'difference_first_minus_rest'))
                    return True
    return False


def discover_ratio_relationships(metrics):
    """
    Discover ratio/percentage relationships.
    Returns list of (ratio_metric, numerator_metric, denominator_metric).
    """
    by_name = {}
    for m in metrics:
        by_name[normalize_name(m['name'])] = m

    relationships = []
    percentages = [m for m in metrics if m['is_percentage']]
    non_percentages = [m for m in metrics if not m['is_percentage']]

    # Find revenue (common denominator for margins)
    revenue = None
    for m in non_percentages:
        if 'revenue' in m['name'].lower() and 'cost' not in m['name'].lower():
            revenue = m
            break

    if not revenue and non_percentages:
        # Try to find the largest value as potential base
        revenue = max(non_percentages, key=lambda m: abs(m['value']))

    # Find shares outstanding (for EPS)
    shares = None
    for m in non_percentages:
        if 'share' in m['name'].lower() and ('outstanding' in m['name'].lower() or
                                               'diluted' in m['name'].lower() or
                                               'basic' in m['name'].lower()):
            shares = m
            break

    # Known ratio patterns: normalized_ratio_name -> (numerator_norm, denominator_norm)
    ratio_patterns = {
        'grossmargin': ('grossprofit', 'revenue'),
        'operatingmargin': ('operatingincome', 'revenue'),
        'netmargin': ('netincome', 'revenue'),
        'netprofitmargin': ('netincome', 'revenue'),
        'operatingprofitmargin': ('operatingincome', 'revenue'),
        'pretaxmargin': ('pretaxincome', 'revenue'),
        'ebitdamargin': ('ebitda', 'revenue'),
        'rdasofrevenue': ('researchanddevelopment', 'revenue'),
        'salesasofrevenue': ('salesandmarketing', 'revenue'),
        'gaasofrevenue': ('generalandadministrative', 'revenue'),
        'fcrevenue': ('freecashflow', 'revenue'),
    }

    for pct_m in percentages:
        pct_norm = normalize_name(pct_m['name'])

        # Check known patterns
        if pct_norm in ratio_patterns:
            num_name, den_name = ratio_patterns[pct_norm]
            if num_name in by_name and den_name in by_name:
                relationships.append((pct_m, by_name[num_name], by_name[den_name]))
                continue

        # EPS pattern: EPS = net_income / shares
        if 'eps' in pct_norm or 'earningspershare' in pct_norm:
            if shares and 'netincome' in by_name:
                # EPS is usually a dollar value, not percentage - skip if percentage
                pass

        # YoY growth pattern: growth = (current - prior) / |prior| * 100
        if 'growth' in pct_norm or 'change' in pct_norm:
            # Try to find matching current/prior pairs
            pass

        # Generic: pct ≈ some_value / revenue * 100
        if revenue:
            best_match = None
            best_diff = float('inf')
            for num_m in non_percentages:
                if num_m['line'] == revenue['line']:
                    continue
                expected = num_m['value'] / revenue['value'] * 100
                diff = abs(expected - pct_m['value'])
                if diff < best_diff and diff < 2.0:
                    best_diff = diff
                    best_match = num_m
            if best_match and best_diff < 0.5:
                relationships.append((pct_m, best_match, revenue))

    return relationships


def gather_all_checks(metrics):
    """
    Build all verifiable relationships as check tuples.
    Each check: (description, all_participant_lines, result_line, passes_bool)
    
    - all_participant_lines: set of ALL lines involved (inputs + result)
    - result_line: the line of the "derived" metric (total or ratio)
    
    This distinction between result and inputs is critical for error localization.
    """
    checks = []

    # Additive checks
    additive_rels = discover_additive_relationships(metrics)
    for total_m, components, rel_type in additive_rels:
        all_participants = {total_m['line']} | {c['line'] for c in components}
        result_line = total_m['line']

        if rel_type == 'sum':
            expected = sum(c['value'] for c in components)
            passes = abs(expected - total_m['value']) <= 0.15
            desc = f"SUM: {' + '.join(c['name'] for c in components)} = {total_m['name']} (expected {expected:.2f}, got {total_m['value']:.2f})"
        elif rel_type == 'difference':
            # total = components[0] - components[1]
            expected = components[0]['value'] - components[1]['value']
            passes = abs(expected - total_m['value']) <= 0.15
            desc = f"DIFF: {components[0]['name']} - {components[1]['name']} = {total_m['name']} (expected {expected:.2f}, got {total_m['value']:.2f})"
        elif rel_type == 'difference_first_minus_rest':
            # total = components[0] - sum(components[1:])
            rest_sum = sum(c['value'] for c in components[1:])
            expected = components[0]['value'] - rest_sum
            passes = abs(expected - total_m['value']) <= 0.15
            desc = f"DIFF: {components[0]['name']} - sum(rest) = {total_m['name']} (expected {expected:.2f}, got {total_m['value']:.2f})"
        else:
            continue

        checks.append((desc, all_participants, result_line, passes))

    # Ratio checks
    ratio_rels = discover_ratio_relationships(metrics)
    for ratio_m, num_m, den_m in ratio_rels:
        if den_m['value'] == 0:
            continue
        all_participants = {ratio_m['line'], num_m['line'], den_m['line']}
        result_line = ratio_m['line']
        expected = num_m['value'] / den_m['value'] * 100
        passes = abs(expected - ratio_m['value']) <= 0.15
        desc = f"RATIO: {num_m['name']} / {den_m['name']} * 100 = {ratio_m['name']} (expected {expected:.2f}%, got {ratio_m['value']:.2f}%)"
        checks.append((desc, all_participants, result_line, passes))

    return checks


def find_incorrect_metric(metrics):
    """
    Find the single incorrect metric using constraint-based single-fault localization.
    
    Key insight: If metric S is the ONLY wrong value, then:
    - ALL checks involving S must FAIL (because S's wrong value propagates)
    - ALL checks NOT involving S must PASS (they're independent of S)
    
    This distinguishes the error from metrics that merely participate in a
    failing check as inputs. For example, if Gross margin is wrong, Revenue
    participates in the failing ratio check but also participates in PASSING
    additive checks — proving Revenue is correct.
    
    Algorithm:
    1. Gather all verifiable relationships (checks)
    2. For each metric S, classify checks as:
       - involving S and passing
       - involving S and failing
       - not involving S and passing
       - not involving S and failing
    3. S is the error if:
       - No checks NOT involving S fail (all independent checks pass)
       - At least one check involving S fails
       - No checks involving S pass (if S is wrong, all its checks should fail)
    4. Fallback: use softer criteria
    """
    checks = gather_all_checks(metrics)

    failing = [(desc, parts, result, p) for desc, parts, result, p in checks if not p]
    passing = [(desc, parts, result, p) for desc, parts, result, p in checks if p]

    if not failing:
        # No violations found with standard patterns - try exhaustive search
        return exhaustive_search(metrics)

    # Debug output
    print(f"\n  All checks ({len(checks)} total, {len(failing)} failing):", file=sys.stderr)
    for desc, parts, result, p in checks:
        status = "✓" if p else "✗ FAIL"
        print(f"    {status}: {desc}", file=sys.stderr)

    # Collect all lines involved in any check
    all_lines_in_checks = set()
    for _, parts, _, _ in checks:
        all_lines_in_checks.update(parts)

    # For each candidate line, classify checks
    candidates = []
    for suspect_line in sorted(all_lines_in_checks):
        involving_pass = [(d, p, r) for d, p, r, _ in passing if suspect_line in p]
        involving_fail = [(d, p, r) for d, p, r, _ in failing if suspect_line in p]
        unrelated_pass = [(d, p, r) for d, p, r, _ in passing if suspect_line not in p]
        unrelated_fail = [(d, p, r) for d, p, r, _ in failing if suspect_line not in p]

        candidates.append({
            'line': suspect_line,
            'involving_pass': len(involving_pass),
            'involving_fail': len(involving_fail),
            'unrelated_pass': len(unrelated_pass),
            'unrelated_fail': len(unrelated_fail),
        })

    print(f"\n  Candidate analysis:", file=sys.stderr)
    for c in candidates:
        if c['involving_fail'] > 0 or c['unrelated_fail'] > 0:
            print(f"    Line {c['line']}: "
                  f"involving(pass={c['involving_pass']}, fail={c['involving_fail']}), "
                  f"unrelated(pass={c['unrelated_pass']}, fail={c['unrelated_fail']})",
                  file=sys.stderr)

    # Strict single-fault localization:
    # S is the error if:
    # 1. No unrelated failures (all checks not involving S pass)
    # 2. At least one involving failure exists
    # 3. No involving passes (all checks involving S fail)
    for c in candidates:
        if (c['unrelated_fail'] == 0 and
            c['involving_fail'] > 0 and
            c['involving_pass'] == 0):
            for m in metrics:
                if m['line'] == c['line']:
                    print(f"\n  → Single-fault (strict): Line {c['line']} ({m['name']}) "
                          f"— all {c['involving_fail']} involving check(s) fail, "
                          f"no involving checks pass", file=sys.stderr)
                    return m

    # Relaxed: allow involving passes (for cases where the error metric
    # is an input to a check whose result is also computed correctly by coincidence)
    for c in candidates:
        if (c['unrelated_fail'] == 0 and
            c['involving_fail'] > 0):
            for m in metrics:
                if m['line'] == c['line']:
                    print(f"\n  → Single-fault (relaxed): Line {c['line']} ({m['name']}) "
                          f"— no unrelated failures, {c['involving_fail']} involving failure(s)",
                          file=sys.stderr)
                    return m

    # Fallback: metric involved in most failures (with fewest involving passes)
    print(f"\n  No single-fault found. Using weighted vote.", file=sys.stderr)
    # Score = involving_fail - involving_pass (higher = more likely error)
    # Only consider candidates with no unrelated failures
    valid = [c for c in candidates if c['unrelated_fail'] == 0 and c['involving_fail'] > 0]
    if valid:
        best = max(valid, key=lambda c: c['involving_fail'] - c['involving_pass'])
        for m in metrics:
            if m['line'] == best['line']:
                print(f"  → Weighted vote: Line {best['line']} ({m['name']})", file=sys.stderr)
                return m

    # Last resort: most failures overall
    counts = Counter()
    for _, parts, _, _ in failing:
        for line in parts:
            counts[line] += 1
    most_common_line = counts.most_common(1)[0][0]
    for m in metrics:
        if m['line'] == most_common_line:
            print(f"  → Majority vote: Line {most_common_line} ({m['name']})", file=sys.stderr)
            return m

    return None


def exhaustive_search(metrics):
    """
    Fallback: if standard relationship discovery finds no violations,
    try all possible additive and ratio combinations more aggressively.
    """
    non_pct = [m for m in metrics if not m['is_percentage']]
    pct = [m for m in metrics if m['is_percentage']]

    # Find revenue
    revenue = None
    for m in non_pct:
        if 'revenue' in m['name'].lower() and 'cost' not in m['name'].lower():
            revenue = m
            break

    if not revenue and non_pct:
        revenue = max(non_pct, key=lambda m: abs(m['value']))

    # Check all percentage metrics against all possible numerators
    if revenue:
        for p in pct:
            for n in non_pct:
                if n['line'] == revenue['line']:
                    continue
                expected = n['value'] / revenue['value'] * 100
                if abs(expected - p['value']) > 0.15 and abs(expected - p['value']) < 5.0:
                    return p

    # Check all additive triples
    from itertools import combinations
    for m1, m2, m3 in combinations(non_pct, 3):
        # Check if m1 + m2 = m3
        if abs(m1['value'] + m2['value'] - m3['value']) > 0.15:
            if abs(m1['value'] + m2['value'] - m3['value']) < 2.0:
                # Close but not exact - one of these might be wrong
                # Return the one that's "most derived" (total-like)
                for candidate in [m3, m1, m2]:
                    if 'total' in candidate['name'].lower() or 'margin' in candidate['name'].lower():
                        return candidate

    return None


def format_output_value(value, raw_value=None):
    """Format the value for output, preserving original representation."""
    if raw_value:
        clean = raw_value.strip().replace('$', '').replace(',', '').replace('%', '')
        clean = re.sub(r'\s*[MBKmk](?:illion)?\s*$', '', clean)
        if clean.startswith('(') and clean.endswith(')'):
            clean = clean[1:-1]
        try:
            float(clean)
            return clean
        except ValueError:
            pass
    return str(value)


def main():
    # Find HTML file
    html_files = find_html_files('/app')
    if not html_files:
        print("ERROR: No HTML files found in /app/", file=sys.stderr)
        sys.exit(1)

    html_path = html_files[0]
    print(f"Processing: {html_path}", file=sys.stderr)

    with open(html_path) as f:
        html_content = f.read()

    # Extract metrics
    metrics = extract_metrics_from_html(html_content)
    print(f"Found {len(metrics)} metrics:", file=sys.stderr)
    for m in metrics:
        print(f"  Line {m['line']}: {m['name']} = {m['raw_value']} ({m['value']})"
              f" {'[pct]' if m['is_percentage'] else ''}", file=sys.stderr)

    # Find the error using constraint-based localization
    error = find_incorrect_metric(metrics)

    if error is None:
        print("ERROR: Could not identify the incorrect metric", file=sys.stderr)
        sys.exit(1)

    # Format output
    output_value = format_output_value(error['value'], error.get('raw_value'))
    output_line = f"{error['line']},{output_value}"

    print(f"\nResult: {output_line}", file=sys.stderr)
    print(f"  Metric: {error['name']}", file=sys.stderr)
    print(f"  Reported value: {error['raw_value']}", file=sys.stderr)

    # Write output
    output_path = '/app/value.txt'
    with open(output_path, 'w') as f:
        f.write(output_line)

    print(f"Written to {output_path}", file=sys.stderr)


if __name__ == '__main__':
    main()
