#!/usr/bin/env python3
"""
Bank Transaction Filter - Entity Resolution Skill (v5)

Key improvements over v4:
  - Dotted abbreviation pre-processing: "N.W." → "nw" before general normalization,
    allowing removal of aggressive single-letter expansions (n→north, w→west, etc.)
    that caused false positives when standalone letters don't mean directions
  - Evidence-proportional near-miss reconciliation
  - Evidence-strength ordering for account establishment
  - Two-tier confidence: strong (containment) vs weak (edit distance)
  - Exclusion words for advisors, partners, subsidiaries
"""

import csv
import json
import re
import sys
from collections import defaultdict

# ── Abbreviation dictionary ──────────────────────────────────────────────
# Only multi-letter abbreviations. Single-letter dotted abbreviations
# (like "N.W.") are handled by pre-processing in normalize_name().
ABBREV = {
    # Directional (multi-letter only)
    'nw': ['north', 'west'],
    'ne': ['north', 'east'],
    'sw': ['south', 'west'],
    'se': ['south', 'east'],
    # Financial / corporate
    'cap': ['capital'],
    'hldgs': ['holdings'],
    'hldg': ['holding'],
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
    'ptys': ['properties'],
    'mktg': ['marketing'],
    'acct': ['accounting'],
    'ins': ['insurance'],
    're': ['real', 'estate'],
}

# ── Legal suffixes ────────────────────────────────────────────────────────
LEGAL_SUFFIXES = {
    # Legal structure indicators — NOT core identity words
    'group', 'holdings', 'hldgs', 'llc', 'inc', 'ltd', 'corp', 'co', 'company',
    'corporation', 'incorporated', 'limited', 'plc', 'lp', 'llp', 'pc', 'pa',
    'na', 'trust', 'fund', 'enterprises', 'ventures',
    # Note: 'solutions', 'services', 'systems', 'industries', 'technologies',
    # 'international', 'partners', 'capital', 'investments', 'management' are
    # NOT included because they can be core identity words, not just legal suffixes.
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
    """
    Normalize a company name for comparison.
    
    Key step: dotted single-letter abbreviations are joined BEFORE general
    punctuation removal. This allows "N.W." → "nw" (then expanded to
    "north west") while leaving standalone "N" untouched (not expanded).
    """
    n = name.lower().strip()
    # Pre-process: join dotted single-letter abbreviations
    # "n.w." → "nw", "n.w" → "nw", "u.s.a." → "usa"
    n = re.sub(r'(?:^|(?<=\s))([a-z](?:\.[a-z])+)\.?',
               lambda m: m.group(1).replace('.', ''), n)
    # Remove remaining punctuation
    n = re.sub(r'[.,;:\'\"()\-/&]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def expand_abbrevs(tokens):
    result = []
    for t in tokens:
        if t in ABBREV:
            result.extend(ABBREV[t])
        else:
            result.append(t)
    return result


def has_exclusion(name):
    tokens = normalize_name(name).split()
    tokens = expand_abbrevs(tokens)
    return any(t in EXCLUSION_WORDS for t in tokens)


def get_core_tokens(name):
    tokens = normalize_name(name).split()
    tokens = expand_abbrevs(tokens)
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return tokens


def compact(tokens):
    return ''.join(tokens)


def levenshtein(s1, s2):
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
    
    STRONG: target compact is contained in company compact AND the company
            has no extra core tokens beyond the target's core tokens.
    WEAK: edit distance within threshold, OR containment succeeded but
          the company has extra core tokens (suggesting a subsidiary or
          separately named entity).
    None: no match or excluded entity.
    """
    if has_exclusion(company_name):
        return None

    target_core = get_core_tokens(target_name)
    company_core = get_core_tokens(company_name)

    if not target_core or not company_core:
        return None

    target_compact = compact(target_core)
    company_compact = compact(company_core)

    # STRONG: containment check with extra-core-token guard
    if target_compact in company_compact:
        # If the company has more core tokens than the target, the extra
        # tokens suggest a different entity (e.g., a subsidiary like
        # "North West Capital Management" vs target "North West Capital").
        # Downgrade to weak — let evidence-proportional reconciliation decide.
        extra_tokens = len(company_core) - len(target_core)
        if extra_tokens > 0:
            return 'weak'
        return 'strong'

    # Pre-filter: require >= 50% token overlap for edit distance
    target_token_set = set(target_core)
    company_token_set = set(company_core)
    if target_token_set:
        overlap = len(target_token_set & company_token_set) / len(target_token_set)
        if overlap < 0.5:
            return None

    # WEAK: edit distance fallback
    max_dist = max(2, len(target_compact) // 6)
    dist = levenshtein(target_compact, company_compact)
    if dist <= max_dist:
        return 'weak'

    return None


def should_reject_near_miss(new_acct, new_count, established_accounts, established_counts):
    """
    Reconcile conflicting evidence across name and account dimensions.
    
    Reject a near-miss account only if its evidence is weak relative to
    the established account it's near to.
    """
    for est_acct, est_count in zip(established_accounts, established_counts):
        dist = levenshtein(new_acct, est_acct)
        if dist <= 2:
            if new_count < max(2, est_count * 0.5):
                return True
    return False


def solve(target_name, input_file='/app/data/bank_transactions.csv',
          output_file='/app/data/output.json'):
    with open(input_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    output_keys = ['Company Name', 'Account Number', 'Date', 'Amount',
                   'Transaction Type', 'Description']
    if fieldnames:
        output_keys = [k for k in output_keys if k in fieldnames]
        if not output_keys:
            output_keys = list(fieldnames)

    # Pre-compute match tiers
    match_tiers = []
    for i, row in enumerate(rows):
        company = row.get('Company Name', '')
        tier = name_matches_target(company, target_name)
        match_tiers.append(tier)

    # Collect strong matches grouped by account
    strong_by_acct = defaultdict(list)
    for i, row in enumerate(rows):
        if match_tiers[i] == 'strong':
            acct = row.get('Account Number', '')
            strong_by_acct[acct].append(i)

    # Establish accounts in order of evidence strength (most rows first)
    sorted_accts = sorted(strong_by_acct.keys(),
                          key=lambda a: len(strong_by_acct[a]), reverse=True)

    strong_accounts = []
    strong_accounts_set = set()
    strong_indices = set()

    for acct in sorted_accts:
        candidate_count = len(strong_by_acct[acct])
        if strong_accounts:
            established_counts = [len(strong_by_acct[a]) for a in strong_accounts]
            if should_reject_near_miss(acct, candidate_count, strong_accounts, established_counts):
                continue
        strong_accounts.append(acct)
        strong_accounts_set.add(acct)
        strong_indices.update(strong_by_acct[acct])

    # Include all rows on established accounts
    result_indices = set(strong_indices)
    for i, row in enumerate(rows):
        acct = row.get('Account Number', '')
        if acct and acct in strong_accounts_set:
            result_indices.add(i)

    # Pass 2: Weak matches ride along on established accounts
    for i, row in enumerate(rows):
        if i not in result_indices:
            if match_tiers[i] == 'weak':
                acct = row.get('Account Number', '')
                if acct and acct in strong_accounts_set:
                    result_indices.add(i)

    # Fallback: If no strong matches, promote weak to strong
    if not strong_accounts:
        weak_by_acct = defaultdict(list)
        for i, row in enumerate(rows):
            if match_tiers[i] == 'weak':
                acct = row.get('Account Number', '')
                weak_by_acct[acct].append(i)

        sorted_weak_accts = sorted(weak_by_acct.keys(),
                                   key=lambda a: len(weak_by_acct[a]), reverse=True)
        weak_accounts = []
        weak_accounts_set = set()
        for acct in sorted_weak_accts:
            candidate_count = len(weak_by_acct[acct])
            if weak_accounts:
                established_counts = [len(weak_by_acct[a]) for a in weak_accounts]
                if should_reject_near_miss(acct, candidate_count, weak_accounts, established_counts):
                    continue
            weak_accounts.append(acct)
            weak_accounts_set.add(acct)
            result_indices.update(weak_by_acct[acct])

        for i, row in enumerate(rows):
            acct = row.get('Account Number', '')
            if acct and acct in weak_accounts_set:
                result_indices.add(i)

    # Build output
    result = []
    for i in sorted(result_indices):
        row = rows[i]
        obj = {}
        for key in output_keys:
            obj[key] = row.get(key, '')
        result.append(obj)

    result.sort(key=lambda x: x.get('Date', ''))

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
