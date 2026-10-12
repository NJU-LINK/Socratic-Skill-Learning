#!/usr/bin/env python3
"""
Bank Transaction Filter - Entity Resolution via Two-Phase Evidence Propagation

Filters bank transactions to extract only those belonging to a target company,
handling name variants, abbreviations, legal suffix changes, and account-based
evidence propagation.

Usage:
    python3 solve.py <target_company_name> <input_csv> <output_json>

Example:
    python3 solve.py "North West Capital" /app/data/bank_transactions.csv /app/data/output.json
"""

import csv
import json
import re
import sys
from collections import defaultdict


# Generic structural suffixes that don't change entity identity
GENERIC_SUFFIXES = {
    'group', 'holdings', 'inc', 'llc', 'corp', 'corporation',
    'ltd', 'limited', 'co', 'company', 'plc', 'gmbh', 'ag', 'sa', 'nv'
}

# Suffixes that indicate separate legal entities (distinguishing signals)
DISTINGUISHING_SUFFIXES = {
    'advisors', 'advisory', 'partners', 'consulting', 'management',
    'associates', 'solutions', 'services', 'ventures', 'fund', 'trust'
}

# Abbreviation expansions (applied before punctuation removal)
ABBREVIATION_MAP = {
    r'\bcap\.': 'capital',
    r'\bhldgs\.?': 'holdings',
    r'\bn\.w\.': 'north west',
    r'\bnw\.?': 'north west',
    r'\bsw\.': 'south west',
    r'\bne\.': 'north east',
    r'\bse\.': 'south east',
    r'\bintl\.': 'international',
    r'\bmfg\.': 'manufacturing',
    r'\btech\.': 'technology',
    r'\bind\.': 'industries',
    r'\bassoc\.': 'associates',
    r'\bmgmt\.': 'management',
    r'\bins\.': 'insurance',
    r'\bfin\.': 'financial',
}


def normalize_name(name):
    """
    Normalize a company name for comparison.
    
    Steps:
    1. Lowercase
    2. Expand abbreviations (before punctuation removal)
    3. Remove punctuation
    4. Normalize whitespace
    """
    n = name.lower().strip()
    
    # Expand abbreviations before removing punctuation
    for pattern, expansion in ABBREVIATION_MAP.items():
        n = re.sub(pattern, expansion, n)
    
    # Remove punctuation except spaces
    n = re.sub(r'[^\w\s]', '', n)
    
    # Normalize whitespace
    n = re.sub(r'\s+', ' ', n).strip()
    
    return n


def strip_generic_suffixes(name):
    """
    Remove generic legal/structural suffixes that don't change entity identity.
    
    Keeps distinguishing suffixes (Advisors, Partners, etc.) intact.
    """
    tokens = name.split()
    while len(tokens) > 1 and tokens[-1] in GENERIC_SUFFIXES:
        tokens = tokens[:-1]
    return ' '.join(tokens)


def has_distinguishing_suffix(normalized_name):
    """
    Check if a normalized name contains distinguishing suffixes
    that indicate a separate legal entity.
    """
    tokens = set(normalized_name.split())
    return bool(tokens & DISTINGUISHING_SUFFIXES)


def compute_core_tokens(name):
    """
    Compute the core identity tokens of a company name.
    
    Normalizes, strips generic suffixes, returns token set.
    """
    normalized = normalize_name(name)
    core = strip_generic_suffixes(normalized)
    return set(core.split())


def char_similarity(s1, s2):
    """
    Character bigram Dice coefficient for measuring string similarity.
    Returns 0.0 to 1.0, where 1.0 means identical strings.
    
    Useful for detecting typos and spelling variations in company names.
    For very short tokens (< 3 chars), falls back to exact match.
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    # For very short tokens, exact match only
    if len(s1) < 3 or len(s2) < 3:
        return 1.0 if s1 == s2 else 0.0
    # Compute character bigrams
    bigrams1 = set(s1[i:i+2] for i in range(len(s1)-1))
    bigrams2 = set(s2[i:i+2] for i in range(len(s2)-1))
    # Dice coefficient: 2 * |intersection| / (|set1| + |set2|)
    return 2.0 * len(bigrams1 & bigrams2) / (len(bigrams1) + len(bigrams2))


def is_name_variant_exact(name, target_core_tokens, min_coverage=0.8):
    """
    Check if a company name is an exact variant of the target (no typos).
    
    Uses token-set intersection for fast, precise matching.
    """
    normalized = normalize_name(name)
    if has_distinguishing_suffix(normalized):
        return False
    
    core = strip_generic_suffixes(normalized)
    core_tokens = set(core.split())
    
    if not core_tokens:
        return False
    
    overlap = core_tokens & target_core_tokens
    coverage = len(overlap) / len(target_core_tokens)
    
    return coverage >= min_coverage


def is_name_variant_fuzzy(name, target_core_tokens, 
                           min_coverage=0.8, token_threshold=0.55):
    """
    Check if a company name is a plausible variant of the target,
    tolerating typos via character-level similarity.
    
    For each target token, finds the best-matching variant token using
    character bigram similarity. Coverage = fraction of target tokens
    that have at least one variant token above token_threshold similarity.
    
    Args:
        name: The company name to check
        target_core_tokens: Set of core tokens from the target name
        min_coverage: Minimum fraction of target tokens that must match
        token_threshold: Minimum similarity for a token to be considered a match
    
    Returns:
        True if the name is a plausible variant (with typos allowed)
    """
    normalized = normalize_name(name)
    if has_distinguishing_suffix(normalized):
        return False
    
    core = strip_generic_suffixes(normalized)
    core_tokens = set(core.split())
    
    if not core_tokens or not target_core_tokens:
        return False
    
    # For each target token, find the best matching variant token
    matched_targets = 0
    for t_tok in target_core_tokens:
        best_sim = max(
            (char_similarity(v_tok, t_tok) for v_tok in core_tokens),
            default=0.0
        )
        if best_sim >= token_threshold:
            matched_targets += 1
    
    coverage = matched_targets / len(target_core_tokens)
    return coverage >= min_coverage


def is_name_variant(name, target_core_tokens, min_coverage=0.8):
    """
    Check if a company name is a plausible variant of the target.
    
    Two-layer matching strategy:
    1. Exact token-set intersection (fast, precise)
    2. Character-bigram similarity fallback (handles typos and spelling drift)
    
    Args:
        name: The company name to check
        target_core_tokens: Set of core tokens from the target name
        min_coverage: Minimum fraction of target tokens that must be present
    
    Returns:
        True if the name is a plausible variant
    """
    # Try exact matching first (fast path)
    if is_name_variant_exact(name, target_core_tokens, min_coverage):
        return True
    # Fall back to fuzzy matching for spelling drift
    return is_name_variant_fuzzy(name, target_core_tokens, min_coverage)


def solve(target_name, input_path, output_path):
    """
    Main solver: two-phase evidence propagation.
    
    Phase A: Anchor discovery via name matching
    Phase B: Account-based propagation
    """
    # Read CSV
    rows = []
    with open(input_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    
    # Compute target core tokens
    target_core_tokens = compute_core_tokens(target_name)
    
    # Phase A: Find anchor rows by name matching
    target_accounts = set()
    matched_indices = set()
    
    for i, row in enumerate(rows):
        company = row['Company Name']
        if is_name_variant(company, target_core_tokens):
            matched_indices.add(i)
            target_accounts.add(row['Account Number'])
    
    # Phase B: Propagate by account
    changed = True
    while changed:
        changed = False
        for i, row in enumerate(rows):
            if i not in matched_indices and row['Account Number'] in target_accounts:
                company = row['Company Name']
                normalized = normalize_name(company)
                
                # Don't include rows with distinguishing suffixes
                if not has_distinguishing_suffix(normalized):
                    matched_indices.add(i)
                    changed = True
    
    # Collect results
    results = []
    for i in sorted(matched_indices):
        row = rows[i]
        result = {}
        for key in fieldnames:
            result[key] = row[key]
        results.append(result)
    
    # Sort by Date ascending
    results.sort(key=lambda x: x.get('Date', ''))
    
    # Write output
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    return len(results)


def main():
    if len(sys.argv) == 4:
        target_name = sys.argv[1]
        input_path = sys.argv[2]
        output_path = sys.argv[3]
    elif len(sys.argv) == 1:
        # Default for v01 task
        target_name = "North West Capital"
        input_path = "/app/data/bank_transactions.csv"
        output_path = "/app/data/output.json"
    else:
        print(f"Usage: {sys.argv[0]} [target_company_name input_csv output_json]")
        sys.exit(1)
    
    count = solve(target_name, input_path, output_path)
    print(f"Found {count} matching transactions -> {output_path}")


if __name__ == '__main__':
    main()
