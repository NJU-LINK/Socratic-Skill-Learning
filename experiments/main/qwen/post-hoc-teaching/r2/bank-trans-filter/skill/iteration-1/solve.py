#!/usr/bin/env python3
"""
Bank Transaction Filter - Entity Resolution Skill (v2)

Two-tier confidence anchoring:
  - STRONG matches (compact containment) can establish accounts
  - WEAK matches (edit distance only) ride along on established accounts
  - Excluded entities (advisors, partners, etc.) are always rejected

This prevents false-positive anchor detection from cascading through
account propagation.
"""

import csv
import json
import re
import sys
from collections import defaultdict


# ── Abbreviation dictionary ──────────────────────────────────────────────
ABBREV = {
    # Directional / geographic
    'nw': ['north', 'west'],
    'ne': ['north', 'east'],
    'sw': ['south', 'west'],
    'se': ['south', 'east'],
    'n': ['north'], 's': ['south'], 'e': ['east'], 'w': ['west'],
    # Financial / corporate
    'cap': ['capital'],
    'hldgs': ['holdings'],
    'fin': ['financial'],
    'inv': ['investment'],
    'ins': ['insurance'],
    'sec': ['securities'],
    'mtg': ['mortgage'],
    'amgt': ['asset', 'management'],
    # Corporate entity types
    'co': ['company'],
    'corp': ['corporation'],
    'inc': ['incorporated'],
    'ltd': ['limited'],
    # Operational
    'svc': ['service'], 'svcs': ['services'],
    'mgmt': ['management'], 'mgt': ['management'],
    'intl': ['international'],
    'natl': ['national'],
    'mfg': ['manufacturing'],
    'dist': ['distribution'],
    'dev': ['development'],
    'tech': ['technology'],
    'sys': ['systems'],
    'eng': ['engineering'],
    'assoc': ['associates'],
    'props': ['properties'],
    'res': ['resources'],
    'gen': ['general'],
    'std': ['standard'],
    'constr': ['construction'],
    'elec': ['electronics'],
    'pharm': ['pharmaceuticals'],
    'aero': ['aerospace'],
    'agr': ['agriculture'],
    'comm': ['communications'],
    'ener': ['energy'],
    'log': ['logistics'],
    'grp': ['group'],
    'intl': ['international'],
}

# ── Legal suffixes ────────────────────────────────────────────────────────
LEGAL_SUFFIXES = {
    'group', 'holdings', 'hldgs', 'llc', 'inc', 'ltd', 'corp', 'co',
    'company', 'corporation', 'incorporated', 'limited', 'plc', 'lp',
    'llp', 'pc', 'pa', 'na', 'trust', 'fund', 'enterprises',
    'ventures', 'solutions', 'services', 'systems', 'industries',
    'technologies', 'international',
}

# ── Exclusion words ──────────────────────────────────────────────────────
EXCLUSION_WORDS = {
    'advisors', 'advisory', 'adviser', 'advisers',
    'partners', 'partnership',
    'subsidiary', 'subsidiaries',
    'affiliate', 'affiliates',
    'division', 'branch',
}


def normalize_name(name):
    """Lowercase, remove punctuation, collapse whitespace."""
    n = name.lower().strip()
    n = re.sub(r'[.,;:\'\"()\-/&]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def expand_abbrevs(tokens):
    """Expand known abbreviations in a token list."""
    result = []
    for t in tokens:
        if t in ABBREV:
            result.extend(ABBREV[t])
        else:
            result.append(t)
    return result


def has_exclusion(name):
    """Check if name contains words indicating a different entity."""
    tokens = normalize_name(name).split()
    tokens = expand_abbrevs(tokens)
    return any(t in EXCLUSION_WORDS for t in tokens)


def get_core_tokens(name):
    """Get core identity tokens with legal suffixes removed."""
    tokens = normalize_name(name).split()
    tokens = expand_abbrevs(tokens)
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return tokens


def compact(tokens):
    """Join tokens into a compact string (no spaces)."""
    return ''.join(tokens)


def levenshtein(s1, s2):
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
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


def name_matches_target(company_name, target_name):
    """
    Two-tier match: returns 'strong', 'weak', or None.

    STRONG: target's compact core is contained in company's compact core.
            This is a high-confidence match that can establish accounts.

    WEAK: edit distance is within threshold, but containment failed.
          This is a lower-confidence match that can only ride along on
          already-established accounts.

    None: no match or excluded entity.
    """
    # Step 1: Exclusion check — always reject
    if has_exclusion(company_name):
        return None

    target_core = get_core_tokens(target_name)
    company_core = get_core_tokens(company_name)

    if not target_core or not company_core:
        return None

    target_compact = compact(target_core)
    company_compact = compact(company_core)

    # Step 2: STRONG — containment check
    # Target's full core is present in company name after normalization.
    # This handles: abbreviations, space variations, legal suffixes.
    if target_compact in company_compact:
        return 'strong'

    # Step 3: Pre-filter for edit distance — require token overlap
    # If the company shares fewer than 50% of target's core tokens,
    # it's probably a different entity even if compact strings are similar.
    target_token_set = set(target_core)
    company_token_set = set(company_core)
    if target_token_set:
        overlap = len(target_token_set & company_token_set) / len(target_token_set)
        if overlap < 0.5:
            return None

    # Step 4: WEAK — edit distance fallback for typos
    max_dist = max(2, len(target_compact) // 6)
    dist = levenshtein(target_compact, company_compact)
    if dist <= max_dist:
        return 'weak'

    return None


def solve(target_name, input_file='/app/data/bank_transactions.csv',
          output_file='/app/data/output.json'):
    """
    Two-pass solver with confidence-tiered anchoring.

    Pass 1: Strong matches establish accounts.
    Pass 2: Weak matches are included only on already-established accounts.
    Fallback: If no strong matches found, weak matches can establish accounts.
    """
    # Read input
    with open(input_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # Determine output keys
    output_keys = ['Company Name', 'Account Number', 'Date', 'Amount',
                   'Transaction Type', 'Description']
    if fieldnames:
        output_keys = [k for k in output_keys if k in fieldnames]
        if not output_keys:
            output_keys = list(fieldnames)

    # Pre-compute match tiers for all rows
    match_tiers = []
    for i, row in enumerate(rows):
        company = row.get('Company Name', '')
        tier = name_matches_target(company, target_name)
        match_tiers.append(tier)

    # ── Pass 1: Strong matches establish accounts ──
    strong_accounts = set()
    strong_indices = set()

    for i, row in enumerate(rows):
        if match_tiers[i] == 'strong':
            strong_indices.add(i)
            strong_accounts.add(row.get('Account Number', ''))

    # Include all rows on strong-established accounts
    result_indices = set(strong_indices)
    for i, row in enumerate(rows):
        acct = row.get('Account Number', '')
        if acct and acct in strong_accounts:
            result_indices.add(i)

    # ── Pass 2: Weak matches ride along on established accounts ──
    for i, row in enumerate(rows):
        if i not in result_indices:
            if match_tiers[i] == 'weak':
                acct = row.get('Account Number', '')
                if acct and acct in strong_accounts:
                    result_indices.add(i)

    # ── Fallback: If no strong matches, promote weak to strong ──
    if not strong_accounts:
        weak_accounts = set()
        for i, row in enumerate(rows):
            if match_tiers[i] == 'weak':
                weak_accounts.add(row.get('Account Number', ''))
                result_indices.add(i)

        # Propagate from weak-established accounts
        for i, row in enumerate(rows):
            acct = row.get('Account Number', '')
            if acct and acct in weak_accounts:
                result_indices.add(i)

    # ── Build output ──
    result = []
    for i in sorted(result_indices):
        row = rows[i]
        obj = {}
        for key in output_keys:
            obj[key] = row.get(key, '')
        result.append(obj)

    # Sort by Date ascending
    result.sort(key=lambda x: x.get('Date', ''))

    # Write output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)

    return len(result)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        import os
        target = os.environ.get('TARGET_NAME', '')
        if not target:
            print("Usage: python3 solve.py <target_company_name> [input_csv] [output_json]")
            sys.exit(1)
    else:
        target = sys.argv[1]

    input_file = sys.argv[2] if len(sys.argv) > 2 else '/app/data/bank_transactions.csv'
    output_file = sys.argv[3] if len(sys.argv) > 3 else '/app/data/output.json'

    count = solve(target, input_file, output_file)
    print(f"Written {count} transactions to {output_file}")
