#!/usr/bin/env python3
"""
Entity resolution through evidence propagation for bank transaction filtering.

Two-pass algorithm:
1. Anchor establishment: Find rows with strong name matches to target
2. Account-based propagation: Include all rows on established target accounts

Key principles:
- Legal suffix discrimination: "Group" ≠ "Advisors" ≠ "Holdings" ≠ "Partners"
- Strict account matching: Never fuzzy-match account numbers
- Abbreviation handling: "Cap." → "Capital", "N.W." → "North West"
"""

import csv
import json
import re
import sys
from typing import Set, Tuple
from collections import Counter


def normalize_name(name: str) -> str:
    """Normalize company name for comparison."""
    normalized = name.lower()
    # Expand common abbreviations
    normalized = normalized.replace('cap.', 'capital')
    normalized = normalized.replace('n.w.', 'north west')
    normalized = normalized.replace('nw ', 'north west ')
    normalized = normalized.replace('northwest', 'north west')
    # Remove punctuation except spaces
    normalized = re.sub(r'[^\w\s]', '', normalized)
    # Normalize whitespace
    normalized = ' '.join(normalized.split())
    return normalized


def extract_suffix(name: str) -> Tuple[str, str]:
    """Extract the legal suffix from a company name.
    
    Returns: (base_name, suffix)
    """
    normalized = normalize_name(name)
    
    suffixes = [
        'group', 'advisors', 'advisory', 'holdings', 'hldgs',
        'partners', 'llc', 'inc', 'ltd', 'corp', 'co', 'company'
    ]
    
    words = normalized.split()
    if not words:
        return normalized, ''
    
    for suffix_len in range(2, 0, -1):
        if len(words) >= suffix_len:
            potential_suffix = ' '.join(words[-suffix_len:])
            if potential_suffix in suffixes:
                base = ' '.join(words[:-suffix_len])
                return base, potential_suffix
    
    return normalized, ''


def normalize_suffix(suffix: str) -> str:
    """Normalize suffix for comparison."""
    equiv = {
        'hldgs': 'holdings',
        'co': 'company',
    }
    return equiv.get(suffix, suffix)


def name_matches_target(candidate_norm: str, target_norm: str, threshold: float = 0.6) -> bool:
    """Check if candidate name matches target using token overlap.
    
    Splits both names into word tokens and computes the fraction of target
    tokens present in the candidate. Accepts if overlap >= threshold.
    
    This handles:
    - Spelling drift (typos in one word still allow partial match)
    - Unexpanded abbreviations (if 'cap' wasn't expanded to 'capital')
    - Word order variations
    
    The suffix-based anchor filtering (in solve()) remains the precision layer;
    this fuzzy matching only broadens the candidate pool.
    """
    target_tokens = set(target_norm.split())
    candidate_tokens = set(candidate_norm.split())
    if not target_tokens:
        return False
    overlap = len(target_tokens & candidate_tokens)
    return (overlap / len(target_tokens)) >= threshold


def solve(input_csv: str, output_json: str, target_company: str):
    """Main solution: two-pass evidence propagation."""
    
    # Read all transactions
    transactions = []
    with open(input_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            transactions.append(row)
    
    target_normalized = normalize_name(target_company)
    
    # Step 1: Find all rows whose normalized name fuzzy-matches the target
    candidate_rows = []
    for trans in transactions:
        norm = normalize_name(trans['Company Name'])
        if name_matches_target(norm, target_normalized):
            candidate_rows.append(trans)
    
    # Step 2: Determine the target entity's suffix from candidates
    suffix_counts = Counter()
    for trans in candidate_rows:
        _, suffix = extract_suffix(trans['Company Name'])
        suffix_counts[normalize_suffix(suffix)] += 1
    
    target_suffix = suffix_counts.most_common(1)[0][0] if suffix_counts else ''
    
    # Step 3: Find anchor rows (name matches target AND suffix matches)
    anchor_accounts: Set[str] = set()
    
    for trans in transactions:
        norm = normalize_name(trans['Company Name'])
        _, suffix = extract_suffix(trans['Company Name'])
        norm_suffix = normalize_suffix(suffix)
        
        if name_matches_target(norm, target_normalized) and norm_suffix == target_suffix:
            anchor_accounts.add(trans['Account Number'])
        elif norm == target_normalized:
            anchor_accounts.add(trans['Account Number'])
    
    # Step 4: Propagate through accounts
    matched_transactions = []
    
    for trans in transactions:
        if trans['Account Number'] in anchor_accounts:
            matched_transactions.append(trans)
    
    # Sort by date
    matched_transactions.sort(key=lambda x: x['Date'])
    
    # Write output
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(matched_transactions, f, indent=2)
    
    return len(matched_transactions)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <input_csv> <output_json> <target_company>")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    output_json = sys.argv[2]
    target_company = sys.argv[3]
    
    count = solve(input_csv, output_json, target_company)
    print(f"Matched {count} transactions")
