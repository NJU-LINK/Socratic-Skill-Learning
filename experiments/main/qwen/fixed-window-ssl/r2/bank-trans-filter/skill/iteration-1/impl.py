#!/usr/bin/env python3
"""
Reference implementation for bank-trans-filter skill.
Extracts transactions belonging to a target company from a CSV file.
"""

import csv
import json
import re
from difflib import SequenceMatcher
from typing import List, Tuple, Set

# === CONFIGURATION ===
SCORE_THRESHOLD = 0.55

# === ABBREVIATION DICTIONARY ===
ABBREVIATIONS = {
    'co': 'company', 'corp': 'corporation', 'inc': 'incorporated',
    'ltd': 'limited', 'llc': 'limited liability company',
    'grp': 'group', 'hldgs': 'holdings', 'adv': 'advisors',
    'mfg': 'manufacturing', 'svc': 'service', 'svcs': 'services',
    'tech': 'technology', 'intl': 'international', 'natl': 'national',
    'cptl': 'capital', 'cap': 'capital',
}

# === LEGAL SUFFIXES (variation-tolerant) ===
LEGAL_SUFFIXES = {
    'group', 'groups', 'holdings', 'hldgs', 'inc', 'incorporated',
    'ltd', 'limited', 'llc', 'co', 'company', 'corp', 'corporation',
    'plc', 'ag', 'gmbh', 'sa', 'pty'
}

# === DIFFERENTIATING SUFFIXES (change entity type) ===
DIFFERENTIATING_SUFFIXES = {
    'advisors', 'advisory', 'partners', 'consultants', 'consulting',
    'associates', 'agents', 'brokers'
}

def tokenize(name: str) -> List[str]:
    """Tokenize a company name into lowercase words, removing punctuation."""
    cleaned = re.sub(r'[.,;:\'\"()-]', ' ', name)
    tokens = [t.lower() for t in cleaned.split() if t]
    return tokens

def expand_abbreviations(tokens: List[str]) -> List[str]:
    """Expand common abbreviations in token list."""
    return [ABBREVIATIONS.get(t, t) for t in tokens]

def token_similarity(t1: str, t2: str) -> float:
    """Compute similarity between two tokens using multiple methods."""
    if t1 == t2:
        return 1.0
    
    # Abbreviation match
    t1_exp = ABBREVIATIONS.get(t1, t1)
    t2_exp = ABBREVIATIONS.get(t2, t2)
    if t1_exp == t2 or t1 == t2_exp or t1_exp == t2_exp:
        return 0.95
    
    # Initialism: single letter matches first letter of target token
    if len(t1) == 1 and len(t2) > 1:
        if t1 == t2[0]:
            return 0.85
    if len(t2) == 1 and len(t1) > 1:
        if t2 == t1[0]:
            return 0.85
    
    # Sequence similarity
    seq_sim = SequenceMatcher(None, t1, t2).ratio()
    
    # Character overlap
    chars1 = set(t1)
    chars2 = set(t2)
    if chars1 and chars2:
        overlap = len(chars1 & chars2) / max(len(chars1), len(chars2))
    else:
        overlap = 0.0
    
    # Substring containment
    if t1 in t2 or t2 in t1:
        containment = min(len(t1), len(t2)) / max(len(t1), len(t2))
    else:
        containment = 0.0
    
    return max(seq_sim, overlap * 0.9, containment * 0.95)

def split_compound_target_guided(token: str, target_tokens: List[str]) -> List[str]:
    """
    Check if a compound token can be decomposed into multiple target tokens.
    Uses target tokens to guide the split, not arbitrary length cutoffs.
    """
    # Try all split positions
    for i in range(2, len(token) - 1):
        left, right = token[:i], token[i:]
        # Check if left/right are good fuzzy matches for any target tokens
        left_match = any(token_similarity(left, tt) > 0.7 for tt in target_tokens)
        right_match = any(token_similarity(right, tt) > 0.7 for tt in target_tokens)
        if left_match and right_match:
            return [left, right]
    
    # Check if token contains a target token as substring
    for tt in target_tokens:
        if tt in token and len(token) > len(tt) + 1:
            remainder = token.replace(tt, '', 1)
            if any(token_similarity(remainder, tt2) > 0.7 for tt2 in target_tokens if tt2 != tt):
                return [tt, remainder]
    
    return [token]

def compute_name_score(candidate_name: str, target_tokens: List[str]) -> Tuple[float, bool]:
    """
    Score how well candidate matches target.
    Returns (score, has_differentiating_suffix).
    """
    raw_tokens = tokenize(candidate_name)
    candidate_tokens = expand_abbreviations(raw_tokens)
    
    if not candidate_tokens:
        return 0.0, False
    
    # Check for differentiating suffix
    has_differentiating = any(t in DIFFERENTIATING_SUFFIXES for t in candidate_tokens)
    
    # Build candidate variants (including compound splits)
    all_candidate_variants = list(candidate_tokens)
    for token in candidate_tokens:
        split_tokens = split_compound_target_guided(token, target_tokens)
        all_candidate_variants.extend(split_tokens)
    
    # Compute target coverage: for each target token, find best matching candidate token
    target_coverages = []
    for target_tok in target_tokens:
        best_match = 0.0
        for cand_tok in all_candidate_variants:
            sim = token_similarity(target_tok, cand_tok)
            best_match = max(best_match, sim)
        target_coverages.append(best_match)
    
    target_coverage = min(target_coverages) if target_coverages else 0.0
    
    # Compute candidate fit: what fraction of candidate tokens are matched?
    non_suffix_tokens = [t for t in candidate_tokens if t not in LEGAL_SUFFIXES]
    if non_suffix_tokens:
        matched = 0
        for cand_tok in non_suffix_tokens:
            best_match = 0.0
            for target_tok in target_tokens:
                sim = token_similarity(cand_tok, target_tok)
                best_match = max(best_match, sim)
            if best_match >= 0.5:
                matched += 1
        candidate_fit = matched / len(non_suffix_tokens)
    else:
        candidate_fit = 1.0
    
    # Final score: weighted combination
    score = 0.7 * target_coverage + 0.3 * candidate_fit
    return score, has_differentiating

def filter_transactions(csv_path: str, target_name: str, output_path: str):
    """
    Main function: filter transactions and write output.
    
    Args:
        csv_path: Path to input CSV file
        target_name: Name of target company (e.g., "North West Capital")
        output_path: Path to write output JSON file
    """
    # Read all data
    rows = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    
    # Tokenize target name
    target_tokens = tokenize(target_name)
    
    # Score all rows
    row_data = []
    for i, row in enumerate(rows):
        score, has_diff = compute_name_score(row['Company Name'], target_tokens)
        row_data.append({
            'idx': i,
            'row': row,
            'score': score,
            'has_diff_suffix': has_diff
        })
    
    # Identify initial anchors (high score, no differentiating suffix)
    known_target_accounts = set()
    target_indices = set()
    
    for rd in row_data:
        if rd['score'] >= SCORE_THRESHOLD and not rd['has_diff_suffix']:
            known_target_accounts.add(rd['row']['Account Number'])
            target_indices.add(rd['idx'])
    
    # Fixpoint propagation
    changed = True
    while changed:
        changed = False
        
        for rd in row_data:
            if rd['idx'] in target_indices:
                continue
            
            account = rd['row']['Account Number']
            
            # If account is already known target
            if account in known_target_accounts:
                if not rd['has_diff_suffix']:
                    # Clean case: include
                    target_indices.add(rd['idx'])
                    changed = True
                else:
                    # Has differentiating suffix: include only if name has strong coverage
                    if rd['score'] >= 0.7:  # Strong name coverage threshold
                        target_indices.add(rd['idx'])
                        changed = True
            # If high score and no differentiating suffix: anchor
            elif rd['score'] >= SCORE_THRESHOLD and not rd['has_diff_suffix']:
                known_target_accounts.add(account)
                target_indices.add(rd['idx'])
                changed = True
    
    # Collect and sort
    final_rows = [row_data[i]['row'] for i in target_indices]
    final_rows.sort(key=lambda r: r['Date'])
    
    # Write output
    output = []
    for row in final_rows:
        output.append({
            'Company Name': row['Company Name'],
            'Account Number': row['Account Number'],
            'Date': row['Date'],
            'Amount': row['Amount'],
            'Transaction Type': row['Transaction Type'],
            'Description': row['Description']
        })
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    return len(output)

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 4:
        print("Usage: python impl.py <csv_path> <target_name> <output_path>")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    target_name = sys.argv[2]
    output_path = sys.argv[3]
    
    count = filter_transactions(csv_path, target_name, output_path)
    print(f"Extracted {count} transactions to {output_path}")
