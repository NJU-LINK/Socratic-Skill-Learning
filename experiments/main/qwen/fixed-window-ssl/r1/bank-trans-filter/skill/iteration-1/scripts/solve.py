#!/usr/bin/env python3
"""
Entity-resolution script for bank transaction filtering.

Given a CSV of bank transactions and a target company name, this script:
1. Identifies all rows belonging to the target company (handling name variations)
2. Collects all account numbers associated with the target
3. Propagates membership: includes all rows on established accounts
4. Outputs a JSON array of matching transactions sorted by Date

Usage:
    python solve.py <input_csv> <output_json> <target_company_name>

Example:
    python solve.py /app/data/bank_transactions.csv /app/data/output.json "North West Capital"
"""

import csv
import json
import re
import sys
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────

# Legal suffixes that indicate corporate form, NOT entity identity
# These are stripped during normalization because "ABC Corp" and "ABC LLC"
# are the same entity, just different legal forms
LEGAL_SUFFIXES = [
    "group", "holdings", "hldgs", "llc", "inc", "ltd", "corp", "co", "company",
]

# ─── Name normalization ──────────────────────────────────────────────

def normalize_name(name):
    """
    Normalize a company name for fuzzy comparison.
    
    Steps:
    1. Lowercase
    2. Expand generic abbreviation patterns (X.Y.Z. → x y z)
    3. Expand common corporate abbreviations (corp, inc, ltd, hldgs)
    4. Strip punctuation
    5. Strip ONLY legal suffixes (corporate form indicators)
    6. Collapse whitespace
    
    Returns normalized string for comparison.
    """
    s = name.lower().strip()
    
    # Generic abbreviation expansion: single-letter-with-period sequences
    # "N.W." → "n w", "A.B.C." → "a b c"
    s = re.sub(r'\b([a-z])\.', r'\1 ', s)
    
    # Common corporate abbreviation expansions
    s = re.sub(r'\bcorp\.?\b', 'corporation', s)
    s = re.sub(r'\binc\.?\b', 'incorporated', s)
    s = re.sub(r'\bltd\.?\b', 'limited', s)
    s = re.sub(r'\bhldgs\.?\b', 'holdings', s)
    s = re.sub(r'\bcap\.?\b', 'capital', s)
    
    # Strip all punctuation except spaces
    s = re.sub(r'[^\w\s]', '', s)
    
    # Strip ONLY legal suffixes from the end (these indicate corporate form)
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        pattern = r'\b' + suffix + r'\b'
        s = re.sub(pattern, '', s)
    
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    
    return s


def levenshtein(s1, s2):
    """
    Compute Levenshtein (edit) distance between two strings.
    Used for fuzzy matching of normalized company names.
    """
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insert = prev[j + 1] + 1
            delete = curr[j] + 1
            sub = prev[j] + (0 if c1 == c2 else 1)
            curr.append(min(insert, delete, sub))
        prev = curr
    
    return prev[-1]


def token_similarity(candidate_tokens, target_tokens, max_token_distance=1):
    """
    Compare two sets of tokens using per-token Levenshtein distance.
    
    Returns a similarity score: the fraction of target tokens that have
    a close match in the candidate tokens (within max_token_distance edits).
    
    Special handling for single-letter tokens (abbreviations): a single letter
    matches any target token that starts with that letter.
    
    This is more robust than character-level Levenshtein because it handles
    word-level variations and abbreviation patterns better.
    """
    if not target_tokens:
        return 0.0
    
    matches = 0
    for target_token in target_tokens:
        best_distance = float('inf')
        for candidate_token in candidate_tokens:
            # Special case: single-letter abbreviation tokens
            if len(candidate_token) == 1 or len(target_token) == 1:
                # Single letter matches if it's a prefix of the other token
                if len(candidate_token) == 1 and len(target_token) > 1:
                    dist = 0 if candidate_token[0] == target_token[0] else float('inf')
                elif len(target_token) == 1 and len(candidate_token) > 1:
                    dist = 0 if target_token[0] == candidate_token[0] else float('inf')
                else:
                    # Both single letters
                    dist = 0 if candidate_token == target_token else float('inf')
            else:
                dist = levenshtein(candidate_token, target_token)
            best_distance = min(best_distance, dist)
        
        if best_distance <= max_token_distance:
            matches += 1
    
    return matches / len(target_tokens)


def name_matches_target(name, target_normalized, min_similarity=0.85):
    """
    Check if a company name is a variant of the target.
    
    Uses bidirectional token-level comparison after normalization.
    Requires that BOTH:
    1. At least min_similarity fraction of target tokens are covered by candidate
    2. At least min_similarity fraction of candidate tokens are covered by target
    
    This ensures no extra tokens (like "Advisors") in either direction.
    
    Args:
        name: Raw company name from CSV
        target_normalized: Pre-normalized target name
        min_similarity: Minimum fraction of tokens that must match (default 0.85)
    
    Returns:
        True if name is a variant of target, False otherwise
    """
    norm = normalize_name(name)
    
    # Split into tokens
    candidate_tokens = norm.split()
    target_tokens = target_normalized.split()
    
    # Direction 1: what fraction of target tokens are covered by candidate?
    target_coverage = token_similarity(candidate_tokens, target_tokens)
    
    # Direction 2: what fraction of candidate tokens are covered by target?
    candidate_coverage = token_similarity(target_tokens, candidate_tokens)
    
    # Both must be high — this ensures no extra tokens in either direction
    return target_coverage >= min_similarity and candidate_coverage >= min_similarity


# ─── Main algorithm ──────────────────────────────────────────────────

def solve(input_csv, output_json, target_name):
    """
    Main entity-resolution algorithm.
    
    Phase 1: Load all rows from CSV
    Phase 2: Seed discovery - find rows whose name matches target
    Phase 3: Account collection - gather all account numbers from seed rows
    Phase 4: Propagation - include ALL rows on established accounts
    Phase 5: Sort by Date and output as JSON array
    """
    target_norm = normalize_name(target_name)
    
    # Phase 1: Load all rows
    rows = []
    with open(input_csv, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    
    # Phase 2: Seed discovery
    seed_accounts = set()
    seed_row_indices = set()
    
    for i, row in enumerate(rows):
        if name_matches_target(row['Company Name'], target_norm):
            seed_accounts.add(row['Account Number'])
            seed_row_indices.add(i)
    
    # Phase 3 & 4: Account collection and propagation
    # Include all rows on established accounts
    matched_indices = set(seed_row_indices)
    for i, row in enumerate(rows):
        if row['Account Number'] in seed_accounts:
            matched_indices.add(i)
    
    # Phase 5: Collect and sort matched rows
    matched_rows = [rows[i] for i in sorted(matched_indices)]
    matched_rows.sort(key=lambda r: r['Date'])
    
    # Output as JSON array with exact string values
    output_keys = ['Company Name', 'Account Number', 'Date', 'Amount',
                   'Transaction Type', 'Description']
    output = []
    for row in matched_rows:
        output.append({k: row[k] for k in output_keys})
    
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    
    return len(matched_rows)


# ─── Entry point ─────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <input_csv> <output_json> <target_company_name>")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    output_json = sys.argv[2]
    target_name = sys.argv[3]
    
    count = solve(input_csv, output_json, target_name)
    print(f"Matched {count} transactions")
