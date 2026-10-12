#!/usr/bin/env python3
"""
General bank transaction filter solver.

Usage:
    python solve_bank_filter.py <csv_path> <output_path> <target_name>

Or import and call solve() directly.

This script implements the multi-pass evidence-propagation entity resolution
algorithm described in SKILL.md.
"""

import csv
import json
import re
import sys
from pathlib import Path


def canonicalize(name):
    """Canonicalize a company name for fuzzy comparison.
    
    Steps:
    1. Lowercase
    2. Remove common legal suffixes
    3. Strip punctuation (replace with spaces)
    4. Collapse whitespace
    """
    s = name.lower().strip()
    # Remove legal suffixes (order matters: longer suffixes first)
    suffixes = [
        ' corporation', ' incorporated', ' holdings', ' company',
        ' partners', ' hldgs', ' group', ' llc', ' inc', ' ltd',
        ' corp', ' co',
    ]
    for suffix in suffixes:
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    # Strip punctuation
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# Business descriptors that indicate a DIFFERENT entity
# Note: Do NOT include generic corporate suffixes here (holdings, group, etc.)
# Those are stripped by canonicalize() and indicate the SAME entity
ENTITY_DESCRIPTORS = [
    'advisors', 'advisory', 'partners', 'consulting',
    'management', 'services', 'adviser',
    'ventures', 'associates', 'solutions',
]


def has_entity_descriptor(canon_name, target_canon):
    """Check if canon_name adds a business descriptor beyond the target.
    
    Returns True if the name appears to be a different entity type.
    """
    # Remove target tokens from the name to see what's left
    remaining = canon_name
    for token in target_canon.split():
        remaining = remaining.replace(token, '', 1).strip()
    
    if not remaining:
        return False
    
    # Check if remaining text contains entity descriptors
    for desc in ENTITY_DESCRIPTORS:
        if re.search(r'\b' + desc + r'\b', remaining):
            return True
    
    return False


def is_variant(company_name, target_name):
    """Determine if company_name is a variant of target_name.
    
    Key principle: the name must refer to the SAME underlying company.
    - Abbreviations, spelling drift, punctuation, legal suffixes → same entity
    - Adding a business descriptor → different entity
    """
    canon = canonicalize(company_name)
    target_canon = canonicalize(target_name)
    
    if not canon or not target_canon:
        return False
    
    # Check for business descriptors that indicate different entity
    if has_entity_descriptor(canon, target_canon):
        return False
    
    # Exact canonical match
    if canon == target_canon:
        return True
    
    # Token-based matching with abbreviation support
    target_tokens = target_canon.split()
    canon_tokens = canon.split()
    
    if len(canon_tokens) <= len(target_tokens):
        match = True
        for i, ct in enumerate(canon_tokens):
            tt = target_tokens[i]
            if ct == tt:
                continue
            elif len(ct) == 1 and tt.startswith(ct):
                continue  # Single-letter abbreviation
            elif len(ct) <= 3 and tt.startswith(ct) and len(tt) - len(ct) <= 3:
                continue  # Short abbreviation (e.g., "cap" → "capital")
            else:
                match = False
                break
        if match:
            return True
    
    # Prefix match (handles partial names)
    if target_canon.startswith(canon) or canon.startswith(target_canon):
        return True
    
    # Fuzzy match with edit distance (handles typos, word merging, etc.)
    if normalized_edit_distance(canon, target_canon) <= 0.2:
        return True
    
    return False


def normalized_edit_distance(s1, s2):
    """Compute normalized Levenshtein distance (0.0 to 1.0)."""
    if not s1 or not s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    # Create distance matrix
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            dp[i][j] = min(dp[i-1][j] + 1,      # deletion
                          dp[i][j-1] + 1,      # insertion
                          dp[i-1][j-1] + cost) # substitution
    max_len = max(len1, len2)
    return dp[len1][len2] / max_len if max_len > 0 else 0.0


def solve(csv_path, output_path, target_name):
    """Main solver: multi-pass evidence propagation.
    
    Args:
        csv_path: Path to input CSV file
        output_path: Path to write JSON output
        target_name: The target company name to filter for
    """
    # Read CSV
    rows = []
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    
    # Pass 1: Anchor discovery
    anchors = set()
    for i, row in enumerate(rows):
        if is_variant(row['Company Name'], target_name):
            anchors.add(i)
    
    # Pass 2: Account establishment from anchors
    established_accounts = {rows[i]['Account Number'] for i in anchors}
    
    # Pass 2b: Near-miss account rejection
    from collections import Counter
    account_counts = Counter(rows[i]['Account Number'] for i in anchors)
    
    rejected_accounts = set()
    for acc in list(established_accounts):
        for other_acc in established_accounts:
            if acc == other_acc:
                continue
            if len(acc) == len(other_acc):
                diffs = sum(1 for a, b in zip(acc, other_acc) if a != b)
                if diffs == 1 and account_counts[acc] <= 1 and account_counts[other_acc] > 1:
                    rejected_accounts.add(acc)
    
    if rejected_accounts:
        established_accounts -= rejected_accounts
        anchors = {i for i in anchors if rows[i]['Account Number'] not in rejected_accounts}
    
    # Pass 3: Propagation (iterate until stable)
    for round_num in range(10):
        prev = len(anchors)
        for i, row in enumerate(rows):
            if i not in anchors and row['Account Number'] in established_accounts:
                anchors.add(i)
        if len(anchors) == prev:
            break
    
    # Build output
    required_keys = ['Company Name', 'Account Number', 'Date', 'Amount',
                     'Transaction Type', 'Description']
    
    results = []
    for i in anchors:
        row = rows[i]
        result = {}
        for key in required_keys:
            result[key] = row[key]
        results.append(result)
    
    # Sort by Date ascending
    results.sort(key=lambda x: x['Date'])
    
    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    
    return len(results)


def extract_target_from_instruction(instruction):
    """Extract target company name from task instruction.
    
    Handles patterns like:
    - "Keep only the transactions that belong to {TARGET}"
    - "Filter for {TARGET}"
    - "Find all transactions for {TARGET}"
    """
    patterns = [
        r'belong to\s+(.+?)(?:\.\s|$)',
        r'for\s+(.+?)(?:\.\s|$)',
        r'of\s+(.+?)(?:\.\s|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


if __name__ == '__main__':
    if len(sys.argv) == 4:
        csv_path = sys.argv[1]
        output_path = sys.argv[2]
        target_name = sys.argv[3]
    else:
        print("Usage: python solve_bank_filter.py <csv_path> <output_path> <target_name>")
        sys.exit(1)
    
    count = solve(csv_path, output_path, target_name)
    print(f"Wrote {count} matching rows to {output_path}")
