#!/usr/bin/env python3
"""
Entity Resolution and Transaction Filtering Script

This script implements a graph-based entity resolution algorithm to filter
bank transactions belonging to a target company.

Algorithm (two-pass anchor-and-propagate):
  Pass 1: Find anchor rows via high-confidence name matching to the target.
          Extract their account numbers.
  Pass 2: Propagate by exact account matching only.
          Optionally discover new accounts via strong name similarity (>=0.8)
          to any known name variant, then re-propagate.
  Prune:   Exclude distractor entities throughout.

Usage:
    python resolve_and_filter.py <csv_path> <target_entity> <output_path>
"""

import csv
import json
import re
import sys
from difflib import SequenceMatcher
from typing import Dict, List, Set


def normalize_name(name: str) -> str:
    """
    Normalize company name for comparison:
    - Lowercase
    - Remove punctuation
    - Expand common abbreviations (NW, N.W., Cap, Hldgs)
    - Remove legal suffixes (Group, Holdings, Inc, LLC, etc.)
    - Collapse whitespace
    """
    normalized = name.lower()
    normalized = re.sub(r'[.,\-\'"]', '', normalized)

    # Expand abbreviations
    normalized = re.sub(r'\bnw\b', 'north west', normalized)
    normalized = re.sub(r'\bn\.w\.\b', 'north west', normalized)
    normalized = re.sub(r'\bcap\b', 'capital', normalized)
    normalized = re.sub(r'\bhldgs\b', 'holdings', normalized)

    # Remove legal suffixes and entity-type words
    suffixes = [
        r'\bincorporated\b', r'\binc\b', r'\bllc\b', r'\bcorp\b',
        r'\bcorporation\b', r'\bltd\b', r'\blimited\b', r'\bgroup\b',
        r'\bcompany\b', r'\bco\b', r'\bpartners\b', r'\bservices\b',
        r'\bsystems\b', r'\bholdings\b', r'\badvisory\b', r'\badvisors\b'
    ]
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized)

    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def compute_similarity(name1: str, name2: str) -> float:
    """
    Compute similarity using token Jaccard and sequence matcher.
    Returns the maximum of both.
    """
    tokens1 = set(name1.split())
    tokens2 = set(name2.split())
    if tokens1 and tokens2:
        jaccard = len(tokens1 & tokens2) / len(tokens1 | tokens2)
    else:
        jaccard = 0.0

    seq_ratio = SequenceMatcher(None, name1, name2).ratio()
    return max(jaccard, seq_ratio)


def _target_core_tokens(target_entity: str) -> Set[str]:
    """
    Extract the core tokens from the original target string (before
    normalization strips suffixes). Used to determine whether an
    indicator word is part of the target's own identity.
    """
    return set(target_entity.lower().split())


def is_distractor(name: str, target_entity: str) -> bool:
    """
    Check if a name variant is likely a distractor (separate entity).

    Distractors have suffixes like "Advisors", "Partners", "Advisory"
    that indicate a different legal entity from the target.

    IMPORTANT: We check indicator words against the ORIGINAL target
    string (before normalization strips suffixes), so that a target
    like "Apex Partners LLC" is not incorrectly flagged as a distractor.
    """
    name_lower = name.lower()
    target_lower = target_entity.lower()

    # Check for distractor indicators
    distractor_indicators = [
        'advisors', 'advisory', 'partners', 'associates',
        'consulting', 'advisers', 'consultants'
    ]

    for indicator in distractor_indicators:
        if indicator in name_lower and indicator not in target_lower:
            return True

    return False


def find_target_transactions(
    csv_path: str,
    target_entity: str,
    anchor_threshold: float = 0.7,
    discovery_threshold: float = 0.8
) -> List[Dict]:
    """
    Two-pass entity resolution algorithm:

    Pass 1 — Anchor discovery:
      Normalize all names, find rows with similarity >= anchor_threshold
      to the target. Extract their account numbers as known_accounts.

    Pass 2 — Propagation and controlled discovery:
      Iterate until fixed point:
        a) Propagate: include any row whose account exactly matches
           a known account. Add its normalized name to known_names.
        b) Discover: for remaining rows, check if name is highly
           similar (>= discovery_threshold) to any known name. If so,
           add its account to known_accounts and include the row.

    Distractor pruning is applied throughout both passes.
    """

    # Read CSV
    transactions = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            transactions.append(row)

    # Phase 1: Find anchor rows (high-confidence name matches to target)
    known_accounts: Set[str] = set()
    known_names: Set[str] = set()
    included_rows: Set[int] = set()

    for row in transactions:
        company_name = row['Company Name']

        # Skip distractors (check against original target string)
        if is_distractor(company_name, target_entity):
            continue

        normalized = normalize_name(company_name)
        target_normalized = normalize_name(target_entity)
        similarity = compute_similarity(normalized, target_normalized)

        if similarity >= anchor_threshold:
            included_rows.add(id(row))
            known_accounts.add(row['Account Number'])
            known_names.add(normalized)

    # Phase 2: Propagation and controlled discovery (iterate to fixed point)
    changed = True
    while changed:
        changed = False

        # (a) Propagate by exact account matching only
        for row in transactions:
            if id(row) in included_rows:
                continue

            company_name = row['Company Name']
            if is_distractor(company_name, target_entity):
                continue

            if row['Account Number'] in known_accounts:
                included_rows.add(id(row))
                known_names.add(normalize_name(company_name))
                changed = True

        # (b) Discovery pass: find new accounts via strong name match
        #     to any known name variant (threshold >= 0.8)
        for row in transactions:
            if id(row) in included_rows:
                continue

            company_name = row['Company Name']
            if is_distractor(company_name, target_entity):
                continue

            normalized = normalize_name(company_name)
            for known_name in known_names:
                if compute_similarity(normalized, known_name) >= discovery_threshold:
                    known_accounts.add(row['Account Number'])
                    included_rows.add(id(row))
                    known_names.add(normalized)
                    changed = True
                    break

    # Collect final results
    result = [row for row in transactions if id(row) in included_rows]

    # Sort by date ascending
    result.sort(key=lambda r: r['Date'])

    return result


def main():
    if len(sys.argv) != 4:
        print("Usage: python resolve_and_filter.py <csv_path> <target_entity> <output_path>")
        sys.exit(1)

    csv_path = sys.argv[1]
    target_entity = sys.argv[2]
    output_path = sys.argv[3]

    result = find_target_transactions(csv_path, target_entity)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)

    print(f"Found {len(result)} transactions for '{target_entity}'")
    print(f"Output written to {output_path}")


if __name__ == '__main__':
    main()
