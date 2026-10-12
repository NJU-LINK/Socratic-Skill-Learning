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


def is_near_match_account(acc1: str, acc2: str) -> bool:
    """Check if two account numbers differ by exactly one character.
    
    Account numbers are identifiers, not numbers. One-character-near
    accounts should not be treated as equal.
    """
    if len(acc1) != len(acc2):
        return False
    diff_count = sum(1 for a, b in zip(acc1, acc2) if a != b)
    return diff_count == 1


# Functional suffixes indicate different business lines and should be excluded
# unless there's consistent account evidence they are the target.
# Structural suffixes (Group, Holdings, LLC, Inc, Corp, Ltd, Co, Company)
# indicate the same entity with different legal forms and should be included.
EXCLUDED_SUFFIXES = {'advisors', 'advisory', 'partners'}


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
    
    # Step 1: Find anchor rows using exclusion-based suffix discrimination
    # A row is an anchor if:
    #   (a) its normalized name fuzzy-matches the target (token overlap >= 0.6), AND
    #   (b) its suffix is NOT a functional/excluded suffix, AND
    #   (c) its account number is NOT a one-character-near match from an established account
    # Structural suffixes (Group, Holdings, LLC, Inc, etc.) are included.
    # Functional suffixes (Advisors, Advisory, Partners) are excluded.
    # Account numbers are identifiers: do not treat one-character-near accounts as equal.
    anchor_accounts: Set[str] = set()
    
    for trans in transactions:
        norm = normalize_name(trans['Company Name'])
        _, suffix = extract_suffix(trans['Company Name'])
        norm_suffix = normalize_suffix(suffix)
        account_num = trans['Account Number']
        
        # Check if name fuzzy-matches target
        if name_matches_target(norm, target_normalized):
            # Check if suffix is NOT excluded (functional)
            if norm_suffix not in EXCLUDED_SUFFIXES:
                # Check if account is NOT a near-match from an established account
                is_near_match = any(is_near_match_account(account_num, established)
                                   for established in anchor_accounts)
                if not is_near_match:
                    anchor_accounts.add(account_num)
    
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
