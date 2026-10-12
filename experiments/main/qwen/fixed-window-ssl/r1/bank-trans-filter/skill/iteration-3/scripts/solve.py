#!/usr/bin/env python3
"""
Entity-resolution script for bank transaction filtering.
"""

import csv
import json
import re
import sys

LEGAL_SUFFIXES = [
    "group", "holdings", "hldgs", "llc", "inc", "ltd", "corp", "co", "company",
]

def normalize_name(name):
    s = name.lower().strip()
    s = re.sub(r'\b([a-z])\.', r'\1 ', s)
    s = re.sub(r'\bcorp\.?\b', 'corporation', s)
    s = re.sub(r'\binc\.?\b', 'incorporated', s)
    s = re.sub(r'\bltd\.?\b', 'limited', s)
    s = re.sub(r'\bhldgs\.?\b', 'holdings', s)
    s = re.sub(r'\bcap\.?\b', 'capital', s)
    s = re.sub(r'[^\w\s]', '', s)
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        pattern = r'\b' + suffix + r'\b'
        s = re.sub(pattern, '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def levenshtein(s1, s2):
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
    if not target_tokens:
        return 0.0
    matches = 0
    for target_token in target_tokens:
        best_distance = float('inf')
        for candidate_token in candidate_tokens:
            if len(candidate_token) == 1 or len(target_token) == 1:
                if len(candidate_token) == 1 and len(target_token) > 1:
                    dist = 0 if candidate_token[0] == target_token[0] else float('inf')
                elif len(target_token) == 1 and len(candidate_token) > 1:
                    dist = 0 if target_token[0] == candidate_token[0] else float('inf')
                else:
                    dist = 0 if candidate_token == target_token else float('inf')
            else:
                dist = levenshtein(candidate_token, target_token)
            best_distance = min(best_distance, dist)
        if best_distance <= max_token_distance:
            matches += 1
    return matches / len(target_tokens)

def name_matches_target(name, target_normalized, min_similarity=0.85):
    norm = normalize_name(name)
    candidate_tokens = norm.split()
    target_tokens = target_normalized.split()
    target_coverage = token_similarity(candidate_tokens, target_tokens)
    candidate_coverage = token_similarity(target_tokens, candidate_tokens)
    return target_coverage >= min_similarity and candidate_coverage >= min_similarity

def is_near_account(acc1, acc2, max_distance=1):
    return levenshtein(acc1, acc2) <= max_distance

def solve(input_csv, output_json, target_name):
    target_norm = normalize_name(target_name)
    
    rows = []
    with open(input_csv, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    
    # Phase 1: Seed discovery
    seed_accounts = set()
    seed_row_indices = set()
    for i, row in enumerate(rows):
        if name_matches_target(row['Company Name'], target_norm):
            seed_accounts.add(row['Account Number'])
            seed_row_indices.add(i)
    
    # Phase 2: Count evidence per account
    account_evidence = {}
    for acc in seed_accounts:
        account_evidence[acc] = sum(1 for r in rows if r['Account Number'] == acc)
    
    # Phase 3: Near-account resolution - keep account with more evidence
    established_accounts = set()
    for acc in sorted(seed_accounts, key=lambda a: account_evidence[a], reverse=True):
        is_near_to_established = False
        for est_acc in established_accounts:
            if is_near_account(acc, est_acc):
                is_near_to_established = True
                break
        if not is_near_to_established:
            established_accounts.add(acc)
    
    # Phase 4: Propagation
    matched_indices = set()
    for i, row in enumerate(rows):
        if row['Account Number'] in established_accounts:
            matched_indices.add(i)
    
    matched_rows = [rows[i] for i in sorted(matched_indices)]
    matched_rows.sort(key=lambda r: r['Date'])
    
    output_keys = ['Company Name', 'Account Number', 'Date', 'Amount',
                   'Transaction Type', 'Description']
    output = [{k: row[k] for k in output_keys} for row in matched_rows]
    
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    
    return len(matched_rows)

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <input_csv> <output_json> <target_company_name>")
        sys.exit(1)
    count = solve(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"Matched {count} transactions")
