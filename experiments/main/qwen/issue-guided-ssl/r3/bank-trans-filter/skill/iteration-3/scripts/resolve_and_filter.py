#!/usr/bin/env python3
"""
Entity Resolution and Transaction Filtering Script

This script implements an anchor-and-propagate algorithm to filter
bank transactions belonging to a target company.

Algorithm:
  Phase 1: Anchor discovery via high-confidence name matching to the target.
           Extract their account numbers.
  Phase 1.5: Near-account distractor detection (edit distance <= 2).
  Phase 2: Propagate by exact account matching only.
  Prune:   Exclude distractor entities throughout.

Usage:
    python resolve_and_filter.py <csv_path> <target_entity> <output_path>
"""

import csv
import json
import re
import sys
from collections import defaultdict
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


def _edit_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _cluster_near_accounts(accounts: Set[str], threshold: int) -> List[Set[str]]:
    """
    Cluster accounts that are near-misses of each other using union-find.
    Returns a list of clusters, where each cluster is a set of accounts.
    """
    # Union-Find data structure
    parent = {acc: acc for acc in accounts}
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    # Union accounts that are near-misses
    accounts_list = list(accounts)
    for i in range(len(accounts_list)):
        for j in range(i + 1, len(accounts_list)):
            acc_a, acc_b = accounts_list[i], accounts_list[j]
            if _edit_distance(acc_a, acc_b) <= threshold:
                union(acc_a, acc_b)
    
    # Group accounts by their root
    clusters = defaultdict(set)
    for acc in accounts:
        clusters[find(acc)].add(acc)
    
    return list(clusters.values())


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
    near_account_threshold: int = 2
) -> List[Dict]:
    """
    Anchor-and-propagate entity resolution algorithm:

    Phase 1 — Anchor discovery:
      Normalize all names, find rows with similarity >= anchor_threshold
      to the target. Count rows per candidate account.

    Phase 1.5 — Near-account distractor detection:
      If candidate accounts are near-misses (edit distance <= threshold),
      keep only the account with more rows. This excludes corrupted
      or typo account numbers.

    Phase 2 — Exact account propagation:
      Include any row whose account exactly matches a surviving account.
      NO name-similarity expansion of the account set.

    Distractor pruning is applied throughout all phases.
    """

    # Read CSV
    transactions = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            transactions.append(row)

    # Phase 1: Find anchor rows and count per account
    account_row_counts: Dict[str, int] = defaultdict(int)

    for row in transactions:
        company_name = row['Company Name']

        # Skip distractors (check against original target string)
        if is_distractor(company_name, target_entity):
            continue

        normalized = normalize_name(company_name)
        target_normalized = normalize_name(target_entity)
        similarity = compute_similarity(normalized, target_normalized)

        if similarity >= anchor_threshold:
            account_row_counts[row['Account Number']] += 1

    # Phase 1.5: Near-account distractor detection using clustering
    # Cluster accounts that are near-misses (edit distance <= threshold)
    # Then keep only the account with the most rows in each cluster
    known_accounts = set(account_row_counts.keys())
    clusters = _cluster_near_accounts(known_accounts, near_account_threshold)
    
    # For each cluster, keep only the account with the most rows
    surviving_accounts = set()
    for cluster in clusters:
        if len(cluster) == 1:
            # Single account, no near-misses
            surviving_accounts.add(cluster.pop())
        else:
            # Multiple near-miss accounts, keep the one with most rows
            best_account = max(cluster, key=lambda acc: account_row_counts[acc])
            surviving_accounts.add(best_account)
    
    known_accounts = surviving_accounts

    # Phase 2: Propagate by exact account matching only
    result = []
    for row in transactions:
        company_name = row['Company Name']

        # Skip distractors
        if is_distractor(company_name, target_entity):
            continue

        # Include if account exactly matches a known account
        if row['Account Number'] in known_accounts:
            result.append(row)

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
