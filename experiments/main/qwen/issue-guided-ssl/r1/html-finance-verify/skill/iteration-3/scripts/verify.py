#!/usr/bin/env python3
"""
HTML Financial Verification — General-Purpose Script

Extracts line-numbered financial values from an HTML earnings/financial report,
discovers cross-check relationships (additive, subtractive, ratio), and
identifies the single metric that is internally inconsistent.

Usage:
    python3 verify.py <html_file> [output_file]

Output format: line_number,value  (the incorrect metric's line and displayed value)

Methodology:
  1. Extract all (line_number, label, value, type) from HTML tables
  2. Discover POTENTIAL cross-check relationships using wide tolerance
  3. Check each potential relationship with tight tolerance
  4. Identify the single value that appears in failing relationships
     while its partner values are "solid" (appear in passing relationships)
"""

import sys
import re
from html.parser import HTMLParser


# ─── Tolerances ──────────────────────────────────────────────────────────────
# Tight: for checking if a relationship holds (accounts for rounding to 1 decimal)
TIGHT_DOLLAR = 0.15
TIGHT_PCT = 0.15

# Wide: for discovering potential relationships (accounts for reporting errors)
WIDE_DOLLAR = 5.0
WIDE_PCT = 3.0


# ─── HTML Parsing ────────────────────────────────────────────────────────────

class TableExtractor(HTMLParser):
    """Extract table rows with cell text and classes."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._current_row = []
        self._current_cell_text = ""
        self._in_cell = False
        self._in_row = False
        self._cell_classes = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'tr':
            self._in_row = True
            self._current_row = []
        elif tag in ('td', 'th'):
            self._in_cell = True
            self._current_cell_text = ""
            self._cell_classes = attrs_dict.get('class', '').split()

    def handle_endtag(self, tag):
        if tag == 'tr' and self._in_row:
            self._in_row = False
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = []
        elif tag in ('td', 'th') and self._in_cell:
            self._in_cell = False
            self._current_row.append({
                'text': self._current_cell_text.strip(),
                'classes': self._cell_classes,
            })

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell_text += data

    def handle_entityref(self, name):
        if self._in_cell:
            self._current_cell_text += f"&{name};"

    def handle_charref(self, name):
        if self._in_cell:
            self._current_cell_text += f"&#{name};"


def parse_numeric(text):
    """
    Parse a numeric value from cell text.
    Returns (float_value, value_type) or (None, None).
    value_type is 'dollar', 'percentage', or 'plain'.
    """
    t = text.strip()
    if not t:
        return None, None

    # Remove commas used as thousands separators
    clean = t.replace(',', '')

    # Percentage detection
    if '%' in clean:
        num_str = clean.replace('%', '').strip()
        negative = False
        if num_str.startswith('(') and num_str.endswith(')'):
            negative = True
            num_str = num_str[1:-1]
        num_str = num_str.replace('$', '').strip()
        try:
            val = float(num_str)
            return (-val if negative else val), 'percentage'
        except ValueError:
            return None, None

    # Dollar detection
    if '$' in clean:
        num_str = clean.replace('$', '').strip()
        negative = False
        if num_str.startswith('(') and num_str.endswith(')'):
            negative = True
            num_str = num_str[1:-1]
        if num_str.startswith('-') or num_str.startswith('−'):
            negative = True
            num_str = num_str.lstrip('-−')
        num_str = num_str.strip()
        try:
            val = float(num_str)
            return (-val if negative else val), 'dollar'
        except ValueError:
            return None, None

    # Parenthetical negative number (accounting convention)
    if clean.startswith('(') and clean.endswith(')'):
        inner = clean[1:-1].strip()
        try:
            return -float(inner), 'plain'
        except ValueError:
            return None, None

    # Leading minus
    if clean.startswith('-') or clean.startswith('−'):
        num_str = clean.lstrip('-−').strip()
        try:
            return -float(num_str), 'plain'
        except ValueError:
            return None, None

    # Plain number
    try:
        return float(clean), 'plain'
    except ValueError:
        return None, None


def extract_metrics(html_content):
    """
    Extract all (line_number, label, value, type) tuples from HTML tables.
    Looks for table rows where one cell contains a line number (integer)
    and another cell contains a numeric financial value.
    """
    parser = TableExtractor()
    parser.feed(html_content)

    metrics = []
    for row in parser.rows:
        line_num = None
        label = None
        value = None
        value_type = None

        for cell in row:
            text = cell['text']
            if not text:
                continue

            # Check if this cell is a line number (pure integer)
            if re.match(r'^\d+$', text.strip()):
                line_num = int(text.strip())
                continue

            # Try to parse as numeric value
            num, vtype = parse_numeric(text)
            if num is not None and vtype in ('dollar', 'percentage'):
                value = num
                value_type = vtype
                continue

            # Otherwise it's a label
            if text and not re.match(r'^[\d\$\%,\.\s\(\)−\-]+$', text):
                label = text

        if line_num is not None and value is not None:
            metrics.append({
                'line': line_num,
                'label': label or '',
                'value': value,
                'type': value_type,
            })

    return metrics


# ─── Cross-Check Engine ─────────────────────────────────────────────────────

def discover_additive_potentials(dollar_metrics, tolerance):
    """
    Discover all potential additive relationships: a OP b ≈ c
    Returns list of dicts with relationship info.
    """
    potentials = []
    n = len(dollar_metrics)
    seen = set()  # Avoid duplicate relationships

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            a_val = dollar_metrics[i]['value']
            b_val = dollar_metrics[j]['value']

            for op, result in [('+', a_val + b_val), ('-', a_val - b_val)]:
                for k in range(n):
                    if k == i or k == j:
                        continue
                    c_val = dollar_metrics[k]['value']
                    diff = abs(result - c_val)
                    if diff < tolerance:
                        # Canonical form to avoid duplicates
                        key = (tuple(sorted([i, j, k])), op)
                        if key not in seen:
                            seen.add(key)
                            potentials.append({
                                'type': 'additive',
                                'indices': (i, j, k),
                                'op': op,
                                'computed': result,
                                'actual': c_val,
                                'diff': diff,
                                'members': {i, j, k},
                            })
    return potentials


def discover_subset_sum_potentials(dollar_metrics, tolerance, max_subset_size=4):
    """
    Discover multi-way subset-sum relationships: sum(subset) ≈ total
    Handles cases like Total OpEx = R&D + S&M + G&A (no intermediate subtotals).
    
    For each candidate 'total' value, checks all subsets of size 2..max_subset_size
    from the remaining values to see if they sum to approximately the total.
    
    Returns list of dicts with relationship info.
    """
    from itertools import combinations
    
    potentials = []
    n = len(dollar_metrics)
    seen = set()
    
    for total_idx in range(n):
        total_val = dollar_metrics[total_idx]['value']
        # Candidate part indices (everything except the total)
        candidate_indices = [i for i in range(n) if i != total_idx]
        
        for size in range(2, min(max_subset_size + 1, len(candidate_indices) + 1)):
            for subset in combinations(candidate_indices, size):
                subset_sum = sum(dollar_metrics[i]['value'] for i in subset)
                diff = abs(subset_sum - total_val)
                if diff < tolerance:
                    members = set(subset) | {total_idx}
                    # Canonical key: sorted part indices + total index
                    key = (tuple(sorted(subset)), total_idx)
                    if key not in seen:
                        seen.add(key)
                        potentials.append({
                            'type': 'subset_sum',
                            'part_indices': tuple(sorted(subset)),
                            'total_index': total_idx,
                            'computed': subset_sum,
                            'actual': total_val,
                            'diff': diff,
                            'members': members,
                        })
    return potentials


def discover_ratio_potentials(dollar_metrics, pct_metrics, tolerance):
    """
    Discover all potential ratio relationships: a / b * 100 ≈ p
    Returns list of dicts with relationship info.
    """
    potentials = []
    seen = set()

    for i, a in enumerate(dollar_metrics):
        for j, b in enumerate(dollar_metrics):
            if i == j or abs(b['value']) < 0.001:
                continue
            ratio = a['value'] / b['value'] * 100.0
            for p, pct in enumerate(pct_metrics):
                diff = abs(ratio - pct['value'])
                if diff < tolerance:
                    key = (i, j, p)
                    if key not in seen:
                        seen.add(key)
                        potentials.append({
                            'type': 'ratio',
                            'dollar_indices': (i, j),
                            'pct_index': p,
                            'computed': ratio,
                            'actual': pct['value'],
                            'diff': diff,
                            'members_dollar': {i, j},
                            'member_pct': p,
                        })
    return potentials


def discover_growth_potentials(dollar_metrics, pct_metrics, tolerance):
    """
    Discover growth relationships: (a - b) / b * 100 ≈ p
    """
    potentials = []
    seen = set()

    for i, a in enumerate(dollar_metrics):
        for j, b in enumerate(dollar_metrics):
            if i == j or abs(b['value']) < 0.001:
                continue
            growth = (a['value'] - b['value']) / b['value'] * 100.0
            for p, pct in enumerate(pct_metrics):
                diff = abs(growth - pct['value'])
                if diff < tolerance:
                    key = ('growth', i, j, p)
                    if key not in seen:
                        seen.add(key)
                        potentials.append({
                            'type': 'growth',
                            'dollar_indices': (i, j),
                            'pct_index': p,
                            'computed': growth,
                            'actual': pct['value'],
                            'diff': diff,
                            'members_dollar': {i, j},
                            'member_pct': p,
                        })
    return potentials


def find_inconsistent_metric(metrics):
    """
    Find the single metric that is internally inconsistent.

    Strategy:
    1. Discover potential relationships using WIDE tolerance
    2. Check each with TIGHT tolerance to find failures
    3. For each value involved in failures, check if it's "solid"
       (appears in passing relationships of the same type)
    4. The value that appears in failures but is NOT solid is the answer
    """
    dollar_metrics = [m for m in metrics if m['type'] == 'dollar']
    pct_metrics = [m for m in metrics if m['type'] == 'percentage']
    plain_metrics = [m for m in metrics if m['type'] == 'plain']

    # Discover potential relationships with wide tolerance
    add_potentials = discover_additive_potentials(dollar_metrics, WIDE_DOLLAR)
    subset_sum_potentials = discover_subset_sum_potentials(dollar_metrics, WIDE_DOLLAR, max_subset_size=4)
    ratio_potentials = discover_ratio_potentials(dollar_metrics, pct_metrics, WIDE_PCT)
    growth_potentials = discover_growth_potentials(dollar_metrics, pct_metrics, WIDE_PCT)

    # Also try plain metrics as percentages if no explicit percentages exist
    if not pct_metrics and plain_metrics:
        ratio_potentials += discover_ratio_potentials(dollar_metrics, plain_metrics, WIDE_PCT)
        growth_potentials += discover_growth_potentials(dollar_metrics, plain_metrics, WIDE_PCT)

    all_potentials = add_potentials + subset_sum_potentials + ratio_potentials + growth_potentials

    # Classify each potential as passing or failing (using tight tolerance)
    passing = []
    failing = []
    for rel in all_potentials:
        if rel['type'] in ('additive', 'subset_sum'):
            if rel['diff'] < TIGHT_DOLLAR:
                passing.append(rel)
            else:
                failing.append(rel)
        else:  # ratio or growth
            if rel['diff'] < TIGHT_PCT:
                passing.append(rel)
            else:
                failing.append(rel)

    print(f"  Potential relationships: {len(all_potentials)}", file=sys.stderr)
    print(f"  Passing (tight): {len(passing)}", file=sys.stderr)
    print(f"  Failing (tight): {len(failing)}", file=sys.stderr)

    if not failing:
        # No failing relationships found with wide tolerance
        # Try wider tolerances
        for wide_d, wide_p in [(10.0, 5.0), (20.0, 10.0), (50.0, 20.0)]:
            add_potentials = discover_additive_potentials(dollar_metrics, wide_d)
            subset_sum_potentials = discover_subset_sum_potentials(dollar_metrics, wide_d, max_subset_size=4)
            ratio_potentials = discover_ratio_potentials(dollar_metrics, pct_metrics, wide_p)
            growth_potentials = discover_growth_potentials(dollar_metrics, pct_metrics, wide_p)
            all_potentials = add_potentials + subset_sum_potentials + ratio_potentials + growth_potentials

            passing = []
            failing = []
            for rel in all_potentials:
                if rel['type'] in ('additive', 'subset_sum'):
                    if rel['diff'] < TIGHT_DOLLAR:
                        passing.append(rel)
                    else:
                        failing.append(rel)
                else:
                    if rel['diff'] < TIGHT_PCT:
                        passing.append(rel)
                    else:
                        failing.append(rel)

            if failing:
                print(f"  Found failures with wider tolerance (d={wide_d}, p={wide_p})", file=sys.stderr)
                break

    if not failing:
        return None

    # For each failing relationship, identify the members
    # The wrong value is the one that appears in failing relationships
    # but is NOT "solid" (not appearing in passing relationships of the same type)

    # Build "solidity" sets: which values appear in passing relationships
    solid_dollar = set()
    solid_pct = set()
    for rel in passing:
        if rel['type'] in ('additive', 'subset_sum'):
            solid_dollar.update(rel['members'])
        else:
            solid_dollar.update(rel['members_dollar'])
            solid_pct.add(rel['member_pct'])

    # For each value in failing relationships, compute a "blame score"
    # Higher score = more likely to be the wrong value
    dollar_blame = {}
    pct_blame = {}

    for rel in failing:
        if rel['type'] in ('additive', 'subset_sum'):
            for idx in rel['members']:
                if idx not in solid_dollar:
                    dollar_blame[idx] = dollar_blame.get(idx, 0) + 1
                else:
                    # This value is solid, so it's not to blame
                    # The other members are more likely to be wrong
                    pass
        else:
            for idx in rel['members_dollar']:
                if idx not in solid_dollar:
                    dollar_blame[idx] = dollar_blame.get(idx, 0) + 1
            if rel['member_pct'] not in solid_pct:
                pct_blame[rel['member_pct']] = pct_blame.get(rel['member_pct'], 0) + 1

    # Also: for failing relationships where ALL members are solid,
    # we need to determine which one is actually wrong.
    # In this case, check if removing each member makes the relationship pass.
    for rel in failing:
        if rel['type'] in ('additive', 'subset_sum'):
            all_solid = all(idx in solid_dollar for idx in rel['members'])
            if all_solid:
                # All members are solid from other relationships
                # The one that appears in the fewest passing relationships is most suspect
                min_pass_count = float('inf')
                suspect = None
                for idx in rel['members']:
                    count = sum(1 for r in passing if r['type'] in ('additive', 'subset_sum') and idx in r.get('members', set()))
                    if count < min_pass_count:
                        min_pass_count = count
                        suspect = idx
                if suspect is not None:
                    dollar_blame[suspect] = dollar_blame.get(suspect, 0) + 1
        else:
            all_solid_dollar = all(idx in solid_dollar for idx in rel['members_dollar'])
            pct_solid = rel['member_pct'] in solid_pct
            if all_solid_dollar and pct_solid:
                # All members are solid — unusual, but handle it
                # The percentage is more likely wrong if it only appears in ratio relationships
                pct_pass_count = sum(1 for r in passing if r['type'] in ('ratio', 'growth') and r.get('member_pct') == rel['member_pct'])
                if pct_pass_count <= 1:
                    pct_blame[rel['member_pct']] = pct_blame.get(rel['member_pct'], 0) + 1

    # Find the value with the highest blame score
    best_metric = None
    best_score = 0

    for idx, score in dollar_blame.items():
        if score > best_score:
            best_score = score
            best_metric = dollar_metrics[idx]

    for idx, score in pct_blame.items():
        if score > best_score:
            best_score = score
            best_metric = pct_metrics[idx]

    # If still no clear answer, try the elimination approach
    if best_metric is None:
        best_metric = find_by_elimination(metrics, dollar_metrics, pct_metrics)

    return best_metric


def find_by_elimination(metrics, dollar_metrics, pct_metrics):
    """
    Fallback: for each candidate, remove it and check if remaining values
    form a fully consistent set using the discover-and-check approach.
    """
    all_candidates = list(enumerate(dollar_metrics)) + [(i, m) for i, m in enumerate(pct_metrics)]

    best_candidate = None
    best_consistency = -1

    for orig_idx, candidate in all_candidates:
        is_pct = candidate['type'] == 'percentage'

        # Build remaining sets
        if is_pct:
            remaining_pcts = [m for i, m in enumerate(pct_metrics) if i != orig_idx]
            remaining_dollars = dollar_metrics
        else:
            remaining_dollars = [m for i, m in enumerate(dollar_metrics) if i != orig_idx]
            remaining_pcts = pct_metrics

        # Discover relationships among remaining values with tight tolerance
        add_rels = discover_additive_potentials(remaining_dollars, TIGHT_DOLLAR)
        ratio_rels = discover_ratio_relationships(remaining_dollars, remaining_pcts, TIGHT_PCT)

        # Count passing relationships
        total_passing = len(add_rels) + len(ratio_rels)

        # Also check: does the candidate violate any relationship among remaining?
        violations = 0
        if is_pct:
            # Check if candidate percentage matches any ratio among remaining dollars
            for i, a in enumerate(remaining_dollars):
                for j, b in enumerate(remaining_dollars):
                    if i == j or abs(b['value']) < 0.001:
                        continue
                    ratio = a['value'] / b['value'] * 100.0
                    if abs(ratio - candidate['value']) < WIDE_PCT:
                        # This ratio is "close" to the candidate
                        if abs(ratio - candidate['value']) >= TIGHT_PCT:
                            violations += 1
        else:
            # Check if candidate dollar value participates in any additive relationship
            for i, a in enumerate(remaining_dollars):
                for j, b in enumerate(remaining_dollars):
                    if i == j:
                        continue
                    # Check candidate + a = b, candidate - a = b, a - candidate = b, etc.
                    c = candidate['value']
                    a_v = a['value']
                    b_v = b['value']
                    if abs(c + a_v - b_v) < WIDE_DOLLAR and abs(c + a_v - b_v) >= TIGHT_DOLLAR:
                        violations += 1
                    if abs(c - a_v - b_v) < WIDE_DOLLAR and abs(c - a_v - b_v) >= TIGHT_DOLLAR:
                        violations += 1
                    if abs(a_v - c - b_v) < WIDE_DOLLAR and abs(a_v - c - b_v) >= TIGHT_DOLLAR:
                        violations += 1

        # Score: more passing relationships + more violations = better candidate
        score = total_passing + violations * 10

        if score > best_consistency:
            best_consistency = score
            best_candidate = candidate

    return best_candidate


def discover_ratio_relationships(dollar_metrics, pct_metrics, tolerance):
    """Discover ratio relationships that pass within given tolerance."""
    results = []
    for i, a in enumerate(dollar_metrics):
        for j, b in enumerate(dollar_metrics):
            if i == j or abs(b['value']) < 0.001:
                continue
            ratio = a['value'] / b['value'] * 100.0
            for p, pct in enumerate(pct_metrics):
                if abs(ratio - pct['value']) < tolerance:
                    results.append({
                        'type': 'ratio',
                        'dollar_indices': (i, j),
                        'pct_index': p,
                    })
    return results


# ─── Output Formatting ──────────────────────────────────────────────────────

def format_value_for_output(original_html_text, value, value_type):
    """
    Format the value to match how it appears in the HTML.
    We try to preserve the exact displayed format.
    """
    # Clean the original text to extract just the number
    clean = original_html_text.replace(',', '').replace(' ', '')
    if value_type == 'percentage':
        clean = clean.replace('%', '').replace('$', '')
    elif value_type == 'dollar':
        clean = clean.replace('$', '')

    # Handle parenthetical negatives
    if clean.startswith('(') and clean.endswith(')'):
        clean = clean[1:-1]

    # Remove leading minus for now
    negative = clean.startswith('-') or clean.startswith('−')
    if negative:
        clean = clean.lstrip('-−')

    try:
        num = float(clean)
        # Determine decimal places from original
        if '.' in clean:
            decimal_places = len(clean.split('.')[1])
        else:
            decimal_places = 0

        formatted = f"{abs(value):.{decimal_places}f}"
        if negative:
            formatted = '-' + formatted
        return formatted
    except (ValueError, IndexError):
        # Fallback: use the value directly
        if value == int(value):
            return str(int(value))
        return f"{value:.1f}"


def extract_raw_values(html_content):
    """
    Extract raw value strings alongside parsed metrics, so we can
    reproduce the exact displayed format.
    """
    parser = TableExtractor()
    parser.feed(html_content)

    metrics = []
    for row in parser.rows:
        line_num = None
        label = None
        value = None
        value_type = None
        raw_value_text = ""

        for cell in row:
            text = cell['text']
            if not text:
                continue

            if re.match(r'^\d+$', text.strip()):
                line_num = int(text.strip())
                continue

            num, vtype = parse_numeric(text)
            if num is not None and vtype in ('dollar', 'percentage'):
                value = num
                value_type = vtype
                raw_value_text = text
                continue

            if text and not re.match(r'^[\d\$\%,\.\s\(\)−\-]+$', text):
                label = text

        if line_num is not None and value is not None:
            metrics.append({
                'line': line_num,
                'label': label or '',
                'value': value,
                'type': value_type,
                'raw': raw_value_text,
            })

    return metrics


# ─── Verification Step ───────────────────────────────────────────────────────

def verify_candidate(candidate, all_metrics):
    """
    Post-identification verification: confirms the candidate wrong value
    actually violates a computable relationship AND that removing it
    produces a fully consistent remaining set.
    
    Returns (is_verified, correct_value) or (False, None).
    
    Checks:
    1. Removing the candidate leaves remaining values mutually consistent
       (all tight-tolerance relationships among remaining values pass)
    2. The candidate violates a relationship not already explained by
       another remaining value (the "already_matched" guard)
    3. Recomputes what the candidate SHOULD be
    """
    remaining = [m for m in all_metrics if m is not candidate]
    remaining_dollars = [m for m in remaining if m['type'] == 'dollar']
    remaining_pcts = [m for m in remaining if m['type'] == 'percentage']
    
    # Check 1: Are all remaining values mutually consistent?
    # Discover tight-tolerance relationships among remaining values
    add_rels = discover_additive_potentials(remaining_dollars, TIGHT_DOLLAR)
    subset_rels = discover_subset_sum_potentials(remaining_dollars, TIGHT_DOLLAR, max_subset_size=4)
    ratio_rels = discover_ratio_potentials(remaining_dollars, remaining_pcts, TIGHT_PCT)
    
    # Count how many tight relationships pass among remaining
    passing_add = len(add_rels)  # All discovered with tight tolerance already pass
    passing_subset = len(subset_rels)
    passing_ratio = len(ratio_rels)
    
    print(f"  Verification: {len(remaining)} remaining metrics", file=sys.stderr)
    print(f"    Passing additive relationships: {passing_add}", file=sys.stderr)
    print(f"    Passing subset-sum relationships: {passing_subset}", file=sys.stderr)
    print(f"    Passing ratio relationships: {passing_ratio}", file=sys.stderr)
    
    # Check 2 & 3: Does the candidate violate a computable relationship?
    # For percentage candidates: find the ratio it should satisfy
    # For dollar candidates: find the additive relationship it should satisfy
    # Key insight: the violated relationship must be one where the OTHER members
    # are "solid" (appear in passing relationships among remaining values)
    
    best_computed = None
    best_diff = float('inf')
    
    # Build solidity sets for remaining values
    solid_remaining_dollar = set()
    solid_remaining_pct = set()
    for rel in add_rels + subset_rels:
        solid_remaining_dollar.update(rel['members'])
    for rel in ratio_rels:
        solid_remaining_dollar.update(rel['members_dollar'])
        solid_remaining_pct.add(rel['member_pct'])
    
    if candidate['type'] == 'percentage':
        # For percentage candidates: check ratio relationships
        for i, a in enumerate(remaining_dollars):
            for j, b in enumerate(remaining_dollars):
                if i == j or abs(b['value']) < 0.001:
                    continue
                ratio = a['value'] / b['value'] * 100.0
                diff = abs(ratio - candidate['value'])
                
                if diff < WIDE_PCT and diff > TIGHT_PCT:
                    # This ratio is close to the candidate but doesn't match tightly
                    # Check: is this ratio already explained by another remaining percentage?
                    already_matched = any(
                        abs(ratio - p['value']) < TIGHT_PCT
                        for p in remaining_pcts
                    )
                    # Check: are the dollar values in this ratio "solid"?
                    # (i.e., they appear in passing relationships among remaining)
                    dollars_solid = i in solid_remaining_dollar and j in solid_remaining_dollar
                    
                    if not already_matched and dollars_solid and diff < best_diff:
                        best_diff = diff
                        best_computed = ratio
                        print(f"    Candidate violates: {a['label']}/{b['label']} = {ratio:.1f}% vs reported {candidate['value']}%", file=sys.stderr)
    
    elif candidate['type'] == 'dollar':
        # For dollar candidates: check additive and subset-sum relationships
        # The violated relationship must have "solid" other members
        
        # Try to find what the candidate should be by checking if it participates
        # in a sum/subtraction with remaining values
        for i, a in enumerate(remaining_dollars):
            for j, b in enumerate(remaining_dollars):
                if i == j:
                    continue
                a_val = a['value']
                b_val = b['value']
                c_val = candidate['value']
                
                # Check: a + b should equal candidate?
                sum_ab = a_val + b_val
                if abs(sum_ab - c_val) < WIDE_DOLLAR and abs(sum_ab - c_val) > TIGHT_DOLLAR:
                    # Check no other remaining value already satisfies this
                    already_matched = any(
                        abs(sum_ab - m['value']) < TIGHT_DOLLAR
                        for k, m in enumerate(remaining_dollars) if k != i and k != j
                    )
                    # Check: are a and b "solid"?
                    dollars_solid = i in solid_remaining_dollar and j in solid_remaining_dollar
                    if not already_matched and dollars_solid and abs(sum_ab - c_val) < best_diff:
                        best_diff = abs(sum_ab - c_val)
                        best_computed = sum_ab
                        print(f"    Candidate violates: {a['label']}+{b['label']} = {sum_ab:.1f} vs reported {c_val}", file=sys.stderr)
                
                # Check: a - b should equal candidate?
                diff_ab = a_val - b_val
                if abs(diff_ab - c_val) < WIDE_DOLLAR and abs(diff_ab - c_val) > TIGHT_DOLLAR:
                    already_matched = any(
                        abs(diff_ab - m['value']) < TIGHT_DOLLAR
                        for k, m in enumerate(remaining_dollars) if k != i and k != j
                    )
                    dollars_solid = i in solid_remaining_dollar and j in solid_remaining_dollar
                    if not already_matched and dollars_solid and abs(diff_ab - c_val) < best_diff:
                        best_diff = abs(diff_ab - c_val)
                        best_computed = diff_ab
                        print(f"    Candidate violates: {a['label']}-{b['label']} = {diff_ab:.1f} vs reported {c_val}", file=sys.stderr)
        
        # Check subset-sum: candidate should be sum of a subset of remaining values
        from itertools import combinations
        for size in range(2, min(5, len(remaining_dollars) + 1)):
            for subset in combinations(enumerate(remaining_dollars), size):
                indices = [s[0] for s in subset]
                items = [s[1] for s in subset]
                subset_sum = sum(m['value'] for m in items)
                diff = abs(subset_sum - candidate['value'])
                if diff < WIDE_DOLLAR and diff > TIGHT_DOLLAR:
                    already_matched = any(
                        abs(subset_sum - m['value']) < TIGHT_DOLLAR
                        for k, m in enumerate(remaining_dollars) if k not in indices
                    )
                    # Check: are all subset members "solid"?
                    dollars_solid = all(idx in solid_remaining_dollar for idx in indices)
                    if not already_matched and dollars_solid and diff < best_diff:
                        best_diff = diff
                        best_computed = subset_sum
                        labels = '+'.join(m['label'] for m in items)
                        print(f"    Candidate violates: {labels} = {subset_sum:.1f} vs reported {candidate['value']}", file=sys.stderr)
        
        # Check: candidate + subset should equal another remaining value (candidate is a part)
        for total_idx, total in enumerate(remaining_dollars):
            for size in range(1, min(4, len(remaining_dollars))):
                others = [(k, m) for k, m in enumerate(remaining_dollars) if k != total_idx]
                for subset in combinations(others, size):
                    indices = [s[0] for s in subset]
                    items = [s[1] for s in subset]
                    subset_sum = sum(m['value'] for m in items)
                    expected_candidate = total['value'] - subset_sum
                    diff = abs(expected_candidate - candidate['value'])
                    if diff < WIDE_DOLLAR and diff > TIGHT_DOLLAR:
                        already_matched = any(
                            abs(expected_candidate - m['value']) < TIGHT_DOLLAR
                            for k, m in enumerate(remaining_dollars) if k != total_idx
                        )
                        # Check: are total and all subset members "solid"?
                        dollars_solid = total_idx in solid_remaining_dollar and all(idx in solid_remaining_dollar for idx in indices)
                        if not already_matched and dollars_solid and diff < best_diff:
                            best_diff = diff
                            best_computed = expected_candidate
                            labels = '+'.join(m['label'] for m in items)
                            print(f"    Candidate violates: {labels}+candidate = {total['label']}: candidate should be {expected_candidate:.1f} vs reported {candidate['value']}", file=sys.stderr)
    
    if best_computed is not None:
        print(f"  ✓ VERIFIED: Candidate should be {best_computed:.1f} but reports {candidate['value']}", file=sys.stderr)
        return True, best_computed
    
    print(f"  ✗ NOT VERIFIED: Could not find a violated relationship", file=sys.stderr)
    return False, None


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 verify.py <html_file> [output_file]", file=sys.stderr)
        sys.exit(1)

    html_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # Step 1: Extract metrics (with raw text for output formatting)
    metrics = extract_raw_values(html_content)
    if not metrics:
        print("ERROR: No metrics extracted from HTML", file=sys.stderr)
        sys.exit(1)

    print(f"Extracted {len(metrics)} metrics:", file=sys.stderr)
    for m in metrics:
        print(f"  Line {m['line']}: {m['label']} = {m['value']} ({m['type']}) [raw: {m['raw']}]", file=sys.stderr)

    # Step 2: Find the inconsistent metric
    dollar_metrics = [m for m in metrics if m['type'] == 'dollar']
    pct_metrics = [m for m in metrics if m['type'] == 'percentage']

    result = find_inconsistent_metric(metrics)

    if result is None:
        print("ERROR: Could not identify the inconsistent metric", file=sys.stderr)
        sys.exit(1)

    # Step 2.5: Verify the candidate
    print(f"\nVerifying candidate: Line {result['line']} {result['label']} = {result['value']} ({result['type']})", file=sys.stderr)
    verified, correct_value = verify_candidate(result, metrics)
    
    if not verified:
        print("Primary candidate failed verification — trying elimination fallback...", file=sys.stderr)
        result = find_by_elimination(metrics, dollar_metrics, pct_metrics)
        if result:
            print(f"\nFallback candidate: Line {result['line']} {result['label']} = {result['value']} ({result['type']})", file=sys.stderr)
            verified, correct_value = verify_candidate(result, metrics)
            if not verified:
                print("WARNING: Fallback candidate also failed verification", file=sys.stderr)
    
    if result is None:
        print("ERROR: Could not identify the inconsistent metric", file=sys.stderr)
        sys.exit(1)

    # Step 3: Format output — use the raw displayed value
    # Extract just the numeric part from the raw text
    raw = result.get('raw', '')
    if result['type'] == 'percentage':
        # Extract the number before %
        match = re.search(r'([\d,]+\.?\d*)', raw.replace(',', ''))
        if match:
            value_str = match.group(1)
        else:
            value_str = f"{result['value']:.1f}"
    elif result['type'] == 'dollar':
        match = re.search(r'([\d,]+\.?\d*)', raw.replace(',', '').replace('$', ''))
        if match:
            value_str = match.group(1)
        else:
            value_str = f"{result['value']:.1f}"
    else:
        value_str = str(result['value'])

    output_line = f"{result['line']},{value_str}"

    print(f"\nResult: {output_line}", file=sys.stderr)
    print(f"Incorrect metric: Line {result['line']}, {result['label']} = {result['value']} ({result['type']})", file=sys.stderr)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(output_line + '\n')
        print(f"Written to {output_file}", file=sys.stderr)
    else:
        print(output_line)


if __name__ == '__main__':
    main()
