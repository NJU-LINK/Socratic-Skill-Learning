#!/usr/bin/env python3
"""
Bank Transaction Filter - Entity Resolution via Bipartite Graph Propagation

Filters bank transactions to extract only those belonging to a target company.
Uses iterative evidence propagation across a bipartite graph of company names
and account numbers.

Usage:
    python3 filter.py --input <csv> --output <json> --target "Company Name"
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher


# Legal suffixes to strip during normalization
# NOTE: Do NOT include 'capital' - it's often part of the core name
LEGAL_SUFFIXES = {
    'group', 'holdings', 'hldgs', 'corp', 'corporation', 'llc', 'ltd',
    'inc', 'co', 'company',
    'services', 'solutions', 'systems', 'industries', 'technologies',
    'supply', 'trading', 'enterprise', 'enterprises',
}

# Compound directional words to split
DIRECTIONAL_COMPOUNDS = {
    'northwest': ['north', 'west'],
    'northeast': ['north', 'east'],
    'southwest': ['south', 'west'],
    'southeast': ['south', 'east'],
}

# Exclusion keywords that trigger soft-blocking (revocable by propagation)
EXCLUSION_KEYWORDS = {'advisors', 'advisory', 'partners'}

# Common abbreviation mappings
ABBREV_MAP = {
    'n': {'north'},
    'w': {'west'},
    'e': {'east'},
    's': {'south'},
    'nw': {'northwest', 'north', 'west'},
    'ne': {'northeast', 'north', 'east'},
    'sw': {'southwest', 'south', 'west'},
    'se': {'southeast', 'south', 'east'},
    'intl': {'international'},
    'mfg': {'manufacturing'},
    'natl': {'national'},
    'svc': {'service', 'services'},
    'mgmt': {'management'},
    'dev': {'development'},
    'tech': {'technology', 'technologies'},
    'cap': {'capital'},
    'ins': {'insurance'},
    'fin': {'financial', 'finance'},
    'res': {'research'},
    'lab': {'laboratories', 'labs'},
    'mktg': {'marketing'},
    'elec': {'electronics'},
    'comm': {'communications', 'communication'},
    'const': {'construction'},
    'aero': {'aerospace'},
    'ind': {'industrial', 'industries'},
    'ag': {'agriculture', 'agricultural'},
    'pharm': {'pharmaceuticals', 'pharmaceutical'},
    'eng': {'engineering'},
    'sec': {'security'},
    'logis': {'logistics'},
    'retail': {'retail'},
    'food': {'food'},
    'energy': {'energy'},
    'oil': {'oil'},
    'gas': {'gas'},
    'air': {'air', 'airlines'},
    'marine': {'marine'},
    'ship': {'shipping'},
    'inv': {'investment', 'investments'},
}


def normalize_name(name):
    """
    Normalize a company name into a set of tokens for matching.
    
    Steps:
    1. Lowercase
    2. Split on periods to expand initials (N.W. → n, w)
    3. Strip punctuation
    4. Remove legal suffixes
    5. Tokenize on whitespace
    """
    n = name.lower().strip()
    
    # Split on periods to handle initials like "N.W."
    # Replace periods with spaces, then tokenize
    n = n.replace('.', ' ')
    
    # Remove non-alphanumeric except spaces
    n = re.sub(r'[^a-z0-9\s]', '', n)
    
    # Tokenize
    tokens = n.split()
    
    # Split compound directional words
    expanded_tokens = []
    for t in tokens:
        if t in DIRECTIONAL_COMPOUNDS:
            expanded_tokens.extend(DIRECTIONAL_COMPOUNDS[t])
        else:
            expanded_tokens.append(t)
    tokens = expanded_tokens
    
    # Remove legal suffixes from the end
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    
    return set(tokens)


def expand_abbreviations(tokens):
    """
    Expand abbreviation tokens to their possible full forms.
    Returns a set of all possible expanded token sets.
    """
    expanded = set()
    for t in tokens:
        if t in ABBREV_MAP:
            expanded.update(ABBREV_MAP[t])
        else:
            expanded.add(t)
    return expanded


def compute_containment(target_tokens, name_tokens):
    """
    Compute containment similarity: what fraction of target tokens
    appear in the name tokens (after abbreviation expansion).
    
    Returns a score between 0 and 1.
    """
    # Expand abbreviations in name tokens
    name_expanded = expand_abbreviations(name_tokens)
    target_expanded = expand_abbreviations(target_tokens)
    
    if not target_expanded:
        return 0.0
    
    # Containment: fraction of target tokens found in name
    matches = target_expanded & name_expanded
    score = len(matches) / len(target_expanded)
    
    return score


def fuzzy_ratio(target_str, name_str):
    """
    Character-level similarity ratio between normalized strings.
    Catches spelling drift that breaks token-level matching.
    """
    return SequenceMatcher(None, target_str, name_str).ratio()


def has_exclusion_keyword(name, target_name=""):
    """Check if name contains an exclusion keyword NOT present in the target.
    
    If the target itself contains 'Partners' (e.g., 'North West Capital Partners'),
    then 'Partners' is not an exclusion keyword for that target.
    """
    n = name.lower()
    target_lower = target_name.lower()
    for kw in EXCLUSION_KEYWORDS:
        if re.search(r'\b' + kw + r'\b', n):
            # Only exclude if this keyword is NOT part of the target name
            if not re.search(r'\b' + kw + r'\b', target_lower):
                return True
    return False


def build_graph(rows):
    """
    Build a bipartite graph of company names ↔ account numbers.
    
    Returns:
        name_to_accounts: dict mapping company name → set of account numbers
        account_to_names: dict mapping account number → set of company names
    """
    name_to_accounts = defaultdict(set)
    account_to_names = defaultdict(set)
    
    for row in rows:
        name = row['Company Name']
        account = row['Account Number']
        name_to_accounts[name].add(account)
        account_to_names[account].add(name)
    
    return dict(name_to_accounts), dict(account_to_names)


def seed_target_names(unique_names, target_name, threshold=0.6):
    """
    Score each unique company name against the target and classify:
    - TARGET_NAME: high similarity, no exclusion keyword
    - PENDING: high similarity but has exclusion keyword
    - NON_TARGET: low similarity
    
    Returns:
        target_names: set of names classified as TARGET_NAME
        pending_names: set of names classified as PENDING
    """
    target_tokens = normalize_name(target_name)
    
    target_names = set()
    pending_names = set()
    
    # Normalize target for fuzzy comparison
    target_norm_str = ' '.join(sorted(target_tokens))
    
    for name in unique_names:
        name_tokens = normalize_name(name)
        containment_score = compute_containment(target_tokens, name_tokens)
        
        # Also compute fuzzy string ratio on the normalized forms
        name_norm_str = ' '.join(sorted(name_tokens))
        fuzzy_score = fuzzy_ratio(target_norm_str, name_norm_str)
        
        # Seed if token containment OR fuzzy ratio passes threshold
        if containment_score >= threshold or fuzzy_score >= 0.75:
            if has_exclusion_keyword(name, target_name):
                pending_names.add(name)
            else:
                target_names.add(name)
    
    return target_names, pending_names


def propagate(name_to_accounts, account_to_names, target_names, pending_names, row_counts):
    """
    Iteratively propagate evidence until stable.
    
    Rules:
    1. Any account connected to a TARGET_NAME → TARGET_ACCOUNT
    2. Any name connected to a TARGET_ACCOUNT → TARGET_NAME
       (even if previously PENDING)
    3. After propagation, exclude near-miss accounts with weak evidence
    
    Returns:
        target_accounts: set of account numbers belonging to target
        final_target_names: set of all names classified as target
    """
    target_accounts = set()
    all_target_names = set(target_names)
    
    changed = True
    iterations = 0
    max_iterations = 100  # safety limit
    
    while changed and iterations < max_iterations:
        changed = False
        iterations += 1
        
        # Step 1: Mark accounts connected to target names
        for name in all_target_names:
            if name in name_to_accounts:
                for account in name_to_accounts[name]:
                    if account not in target_accounts:
                        target_accounts.add(account)
                        changed = True
        
        # Step 2: Mark names connected to target accounts
        # (including pending names — propagation overrides soft blocks)
        for account in target_accounts:
            if account in account_to_names:
                for name in account_to_names[account]:
                    if name not in all_target_names:
                        all_target_names.add(name)
                        changed = True
    
    # Step 3: Exclude near-miss accounts with weak evidence
    # If an account is very similar (edit distance ≤ 2) to another target account
    # AND has only 1 row, exclude it as a likely data entry error
    accounts_to_remove = set()
    for account in target_accounts:
        row_count = row_counts.get(account, 0)
        if row_count == 1:
            # Check if this account is very similar to another target account
            for other_account in target_accounts:
                if other_account != account:
                    # Compute edit distance
                    if edit_distance(account, other_account) <= 2:
                        accounts_to_remove.add(account)
                        break
    
    target_accounts -= accounts_to_remove
    
    return target_accounts, all_target_names


def edit_distance(s1, s2):
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return edit_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def filter_transactions(input_path, output_path, target_name, threshold=0.6):
    """
    Main entry point: filter transactions for target company.
    """
    # Read CSV
    rows = []
    with open(input_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    
    if not rows:
        print("No rows found in input CSV", file=sys.stderr)
        sys.exit(1)
    
    # Build bipartite graph
    name_to_accounts, account_to_names = build_graph(rows)
    
    # Count rows per account (for near-account detection)
    row_counts = defaultdict(int)
    for row in rows:
        row_counts[row['Account Number']] += 1
    
    # Get unique names
    unique_names = set(name_to_accounts.keys())
    
    # Seed target names
    target_names, pending_names = seed_target_names(unique_names, target_name, threshold=threshold)
    
    print(f"Target name: {target_name}", file=sys.stderr)
    print(f"Unique company names: {len(unique_names)}", file=sys.stderr)
    print(f"Seeded target names ({len(target_names)}): {sorted(target_names)}", file=sys.stderr)
    print(f"Pending names ({len(pending_names)}): {sorted(pending_names)}", file=sys.stderr)
    
    # Propagate
    target_accounts, final_target_names = propagate(
        name_to_accounts, account_to_names, target_names, pending_names, dict(row_counts)
    )
    
    print(f"Target accounts ({len(target_accounts)}): {sorted(target_accounts)}", file=sys.stderr)
    print(f"Final target names ({len(final_target_names)}): {sorted(final_target_names)}", file=sys.stderr)
    
    # Filter rows: include every row whose account is a target account
    result = []
    for row in rows:
        if row['Account Number'] in target_accounts:
            result.append({
                'Company Name': row['Company Name'],
                'Account Number': row['Account Number'],
                'Date': row['Date'],
                'Amount': row['Amount'],
                'Transaction Type': row['Transaction Type'],
                'Description': row['Description'],
            })
    
    # Sort by Date ascending
    result.sort(key=lambda x: x['Date'])
    
    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    
    print(f"Output: {len(result)} transactions written to {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Filter bank transactions for a target company'
    )
    parser.add_argument('--input', required=True, help='Input CSV path')
    parser.add_argument('--output', required=True, help='Output JSON path')
    parser.add_argument('--target', required=True, help='Target company name')
    parser.add_argument('--threshold', type=float, default=0.6,
                        help='Containment similarity threshold (default: 0.6)')
    
    args = parser.parse_args()
    filter_transactions(args.input, args.output, args.target, args.threshold)


if __name__ == '__main__':
    main()
