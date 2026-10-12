#!/usr/bin/env python3
"""
Bank Transaction Filter — Entity Resolution Skill

Filters bank transaction CSVs to extract only rows belonging to a specified
target company. Handles:
- Noisy company-name variants (abbreviations, typos, legal-suffix changes)
- Evidence propagation from name aliases to account numbers
- Exclusion of confusable distractor entities (advisors, partners, subsidiaries)

Usage:
    python3 solve.py [--target "Company Name"] [--input path.csv] [--output path.json]

Environment variables (override defaults):
    TARGET_COMPANY, INPUT_CSV, OUTPUT_JSON
"""

import csv
import json
import os
import re
import sys
import argparse
from collections import defaultdict
from difflib import SequenceMatcher


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

DEFAULT_TARGET = "North West Capital"
DEFAULT_INPUT = "/app/data/bank_transactions.csv"
DEFAULT_OUTPUT = "/app/data/output.json"

# Business designations that indicate a SEPARATE legal entity when appended
# to the target name. These are distractors, not variants.
SEPARATE_ENTITY_DESIGNATORS = {
    "advisors", "advisory", "adviser", "advisers",
    "partners", "partner",
    "associates", "associate",
    "consulting", "consultants",
    "management", "managers",
    "brokerage", "broker",
    "ventures", "venture",
}

# Legal suffixes that can be freely added/removed (not separate entities)
LEGAL_SUFFIXES = {
    "group", "llc", "inc", "corp", "corporation", "company", "co",
    "ltd", "limited", "incorporated", "lp", "pllc", "llp",
    "holdings", "hldgs", "hldg",
    "enterprises", "enterprise",
    "services", "svc", "svcs",
}

# Common abbreviation mappings (lowercase, without period)
ABBREVIATION_MAP = {
    "cap": "capital",
    "hldgs": "holdings",
    "hldg": "holdings",
    "co": "company",
    "corp": "corporation",
    "inc": "incorporated",
    "ltd": "limited",
    "svc": "services",
    "svcs": "services",
    "mfg": "manufacturing",
    "intl": "international",
    "natl": "national",
    "mktg": "marketing",
    "dev": "development",
    "tech": "technology",
    "sys": "systems",
    "eng": "engineering",
    "ins": "insurance",
    "sec": "securities",
    "inv": "investment",
    "fin": "financial",
    "grp": "group",
    "ent": "enterprises",
    "entp": "enterprises",
    "bldg": "building",
    "maint": "maintenance",
    "constr": "construction",
}


# ─────────────────────────────────────────────────────────────────────
# Name Normalization and Matching
# ─────────────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize a company name for comparison: lowercase, remove punctuation, collapse spaces."""
    name = name.lower().strip()
    # Remove periods, commas, hyphens, apostrophes (replace with space)
    name = re.sub(r"[.,\-\'\"]", ' ', name)
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def normalize_for_comparison(name: str) -> str:
    """More aggressive normalization: also merge common compound words."""
    name = normalize_name(name)
    # Merge "north west" -> "northwest" style: actually keep them separate
    # but also handle "northwest" -> "north west"
    # Split known compound directions
    for compound, expanded in [
        ("northwest", "north west"),
        ("northeast", "north east"),
        ("southwest", "south west"),
        ("southeast", "south east"),
    ]:
        name = name.replace(compound, expanded)
    return name


def strip_legal_suffixes(words: list) -> list:
    """Remove legal suffixes from a list of words."""
    result = list(words)
    while result and result[-1] in LEGAL_SUFFIXES:
        result.pop()
    return result


def expand_abbreviations(words: list) -> list:
    """Expand common abbreviations in a list of words."""
    expanded = []
    for word in words:
        lookup = word.rstrip('.')
        if lookup in ABBREVIATION_MAP:
            expanded.append(ABBREVIATION_MAP[lookup])
        else:
            expanded.append(word)
    return expanded


def get_core_words(normalized_name: str) -> list:
    """Get the core identifying words of a company name (no suffixes, expanded abbreviations)."""
    words = normalized_name.split()
    words = expand_abbreviations(words)
    words = strip_legal_suffixes(words)
    return words


def get_initials_sequence(words: list) -> str:
    """Get initials from a list of words as a string of first letters."""
    return ''.join(w[0] for w in words if w)


def is_separate_entity(company_name: str, target_name: str) -> bool:
    """Check if a company name represents a separate legal entity from the target.
    
    E.g., 'North West Capital Advisors' is separate from 'North West Capital'.
    
    This is a NAME-ONLY check — it does not consider account evidence.
    Use core_name_matches_target() to determine if the underlying name
    (after stripping designators) actually aligns with the target.
    """
    norm_company = normalize_for_comparison(company_name)
    norm_target = normalize_for_comparison(target_name)
    
    company_core = get_core_words(norm_company)
    target_core = get_core_words(norm_target)
    
    if not company_core or not target_core:
        return False
    
    # Check if the company's core words start with the target's core words
    # and have additional designator words
    if len(company_core) > len(target_core):
        prefix_match = all(
            company_core[i] == target_core[i] 
            for i in range(len(target_core))
        )
        if prefix_match:
            suffix_words = company_core[len(target_core):]
            for sw in suffix_words:
                if sw in SEPARATE_ENTITY_DESIGNATORS:
                    return True
    
    return False


def core_name_matches_target(company_name: str, target_name: str) -> bool:
    """Check if the core name (after stripping designators and suffixes) matches target.
    
    This is used to determine whether a 'separate entity' name actually refers
    to the same underlying company — i.e., the name only differs by a designator
    word like 'Advisors' or 'Partners'. If the core words match, the name is
    consistent with the target, and account evidence can override the designator.
    
    Also handles initials-based core matching (e.g., 'N.W. Capital' core matches
    'North West Capital' target).
    """
    norm_company = normalize_for_comparison(company_name)
    norm_target = normalize_for_comparison(target_name)
    
    company_words = norm_company.split()
    target_words = norm_target.split()
    
    # Expand abbreviations on BOTH sides symmetrically
    company_expanded = expand_abbreviations(company_words)
    target_expanded = expand_abbreviations(target_words)
    
    # Strip legal suffixes from both
    company_core = strip_legal_suffixes(company_expanded)
    target_core = strip_legal_suffixes(target_expanded)
    
    # Strip designator words from company side to get the 'underlying' name
    company_core_clean = [w for w in company_core if w not in SEPARATE_ENTITY_DESIGNATORS]
    
    # After removing designators, legal suffixes may no longer be at the end.
    # Strip them again to get the true core.
    company_core_clean = strip_legal_suffixes(company_core_clean)
    
    if not company_core_clean or not target_core:
        return False
    
    # Direct match of cleaned core
    if company_core_clean == target_core:
        return True
    
    # Prefix containment (cleaned core is a prefix of target core or vice versa)
    if (len(company_core_clean) <= len(target_core) and
        company_core_clean == target_core[:len(company_core_clean)]):
        return True
    if (len(target_core) <= len(company_core_clean) and
        target_core == company_core_clean[:len(target_core)]):
        return True
    
    # Check initials-based matching on cleaned core
    for num_initials in range(1, min(len(target_core), len(company_core_clean)) + 1):
        initial_words = company_core_clean[:num_initials]
        is_initials = all(len(w) == 1 for w in initial_words)
        if not is_initials:
            continue
        initials_match = all(
            initial_words[i] == target_core[i][0]
            for i in range(num_initials)
        )
        if not initials_match:
            continue
        remaining_company = company_core_clean[num_initials:]
        remaining_target = target_core[num_initials:]
        if remaining_company == remaining_target:
            return True
        if (len(remaining_company) <= len(remaining_target) and
            remaining_company == remaining_target[:len(remaining_company)]):
            return True
    
    return False


def initials_match_target(company_norm: str, target_words: list) -> bool:
    """Check if a company name uses initials for part of the target name.
    
    E.g., "N.W. Capital Holdings" matches target "North West Capital"
    because N.W. are initials of "North West" and "Capital" matches.
    
    Abbreviations are expanded symmetrically on BOTH sides so that
    'N.W. Capital Co' correctly matches target 'North West Capital Co'
    (both sides expand 'co' -> 'company').
    """
    company_words = company_norm.split()
    
    # Expand abbreviations on BOTH sides symmetrically
    company_expanded = expand_abbreviations(company_words)
    target_expanded = expand_abbreviations(target_words)
    
    # Strip legal suffixes from both
    company_core = strip_legal_suffixes(company_expanded)
    target_core = strip_legal_suffixes(target_expanded)
    
    if not company_core or not target_core:
        return False
    
    # Strategy: Check if the first K words of company are single-letter initials
    # matching the first K words of target, and the remaining words match
    for num_initials in range(1, min(len(target_core), len(company_core)) + 1):
        # Check if first num_initials words of company are single letters
        initial_words = company_core[:num_initials]
        is_initials = all(len(w) == 1 for w in initial_words)
        
        if not is_initials:
            continue
        
        # Check if initials match first num_initials target words
        initials_match = all(
            initial_words[i] == target_core[i][0]
            for i in range(num_initials)
        )
        
        if not initials_match:
            continue
        
        # Check if remaining company words match remaining target words
        remaining_company = company_core[num_initials:]
        remaining_target = target_core[num_initials:]
        
        if remaining_company == remaining_target:
            return True
        
        # Also allow remaining company to be a subset (fewer words)
        if (len(remaining_company) <= len(remaining_target) and
            remaining_company == remaining_target[:len(remaining_company)]):
            return True
    
    return False


def account_edit_distance(acct1: str, acct2: str) -> int:
    """Compute the edit distance between two account number strings.
    
    Account numbers are identifiers, not numbers. This function is used
    to detect near-miss accounts that may be typos of established target
    accounts (e.g., BUS-41877 vs BUS-41777 differ by 1 character).
    """
    if acct1 == acct2:
        return 0
    # Use simple Levenshtein distance
    m, n = len(acct1), len(acct2)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if acct1[i-1] == acct2[j-1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j-1])
            prev = temp
    return dp[n]


def is_near_miss_account(acct: str, established_accounts: set, max_distance: int = 2) -> bool:
    """Check if an account number is a near-miss (within max_distance edits)
    of any established target account.
    
    Near-miss accounts are likely typos of real target accounts. Per the spec:
    'Account numbers are identifiers, not numbers: preserve them exactly and
    do not treat one-character-near account numbers as equal.'
    
    So if a name-matched row proposes a new account that is a near-miss of an
    established target account, we EXCLUDE it rather than establishing it as
    a new target account.
    """
    if not acct or not established_accounts:
        return False
    for established in established_accounts:
        dist = account_edit_distance(acct, established)
        if 0 < dist <= max_distance:
            return True
    return False


# Generic business terms that are common across many company names.
# Sharing only these words is not enough to establish plausibility.
GENERIC_BUSINESS_TERMS = {
    "capital", "group", "services", "partners", "energy", "light",
    "tech", "technology", "systems", "solutions", "global", "national",
    "international", "corp", "corporation", "inc", "incorporated",
    "ltd", "limited", "co", "company", "holdings", "hldgs",
    "enterprises", "enterprise", "ventures", "fund", "trust",
    "financial", "finance", "bank", "banking", "insurance",
    "real", "estate", "properties", "development", "management",
    "consulting", "advisory", "advisors",
}


def name_plausibly_related(company_name: str, target_name: str) -> bool:
    """Check if a company name is plausibly related to the target (relaxed check).
    
    This is used in Pass 2 for rows on established target accounts. The row's
    company name should have at least some relationship to the target — it
    shouldn't be a completely unrelated company that happens to share an account.
    
    Returns True if:
    - The name matches the target (via name_matches_target), OR
    - The name is a separate entity with matching core (override case), OR
    - The name shares at least one DISTINCTIVE word with the target core
      (excluding generic business terms), OR
    - The name has fuzzy similarity > 0.5 with the target
    
    This catches shorter/abbreviated aliases while excluding completely unrelated
    companies that might share an account (account reuse patterns).
    """
    if not company_name or not target_name:
        return False
    
    # Full name match (includes separate entity with matching core)
    if name_matches_target(company_name, target_name):
        return True
    
    # Separate entity with matching core (override case)
    if is_separate_entity(company_name, target_name):
        return core_name_matches_target(company_name, target_name)
    
    norm_company = normalize_for_comparison(company_name)
    norm_target = normalize_for_comparison(target_name)
    
    # Check shared DISTINCTIVE words (excluding generic business terms)
    company_words = set(w for w in norm_company.split() if len(w) > 2)
    target_words = set(w for w in norm_target.split() if len(w) > 2)
    
    # Expand abbreviations for word comparison
    company_expanded = set(expand_abbreviations(norm_company.split()))
    target_expanded = set(expand_abbreviations(norm_target.split()))
    company_expanded = set(w for w in company_expanded if len(w) > 2)
    target_expanded = set(w for w in target_expanded if len(w) > 2)
    
    # Shared words excluding generic terms
    shared_words = (company_words & target_words) - GENERIC_BUSINESS_TERMS
    shared_expanded = (company_expanded & target_expanded) - GENERIC_BUSINESS_TERMS
    
    if shared_words or shared_expanded:
        return True
    
    # If only generic terms are shared, require higher fuzzy threshold
    # to avoid false positives (e.g., "Momentum Capital" vs "North West Capital")
    all_shared = (company_words & target_words) | (company_expanded & target_expanded)
    if all_shared:
        # Only generic terms shared — need strong fuzzy match
        ratio = SequenceMatcher(None, norm_company, norm_target).ratio()
        if ratio >= 0.7:
            return True
    else:
        # No shared words at all — moderate fuzzy threshold
        ratio = SequenceMatcher(None, norm_company, norm_target).ratio()
        if ratio >= 0.5:
            return True
    
    return False


def name_matches_target(company_name: str, target_name: str) -> bool:
    """Determine if a company name is a variant of the target company.
    
    Returns True if the name is a plausible variant (abbreviation, typo, 
    legal-suffix change, partial match) of the target.
    Returns False if it's a separate entity or unrelated.
    """
    if not company_name or not target_name:
        return False
    
    # First check if it's a separate entity
    if is_separate_entity(company_name, target_name):
        return False
    
    norm_company = normalize_for_comparison(company_name)
    norm_target = normalize_for_comparison(target_name)
    
    # Exact match after normalization
    if norm_company == norm_target:
        return True
    
    # Core words match (after expanding abbreviations and stripping legal suffixes)
    company_core = get_core_words(norm_company)
    target_core = get_core_words(norm_target)
    
    if company_core == target_core:
        return True
    
    # One core contains the other
    if (len(company_core) <= len(target_core) and
        company_core == target_core[:len(company_core)]):
        return True
    if (len(target_core) <= len(company_core) and
        target_core == company_core[:len(target_core)]):
        return True
    
    # Check initials-based matching (e.g., "N.W. Capital Holdings" for "North West Capital")
    target_words = norm_target.split()
    if initials_match_target(norm_company, target_words):
        return True
    
    # Fuzzy matching for typos (edit distance based)
    # Compare full normalized names
    ratio = SequenceMatcher(None, norm_company, norm_target).ratio()
    if ratio >= 0.85:
        return True
    
    # Compare core words as strings
    company_core_str = ' '.join(company_core)
    target_core_str = ' '.join(target_core)
    ratio_core = SequenceMatcher(None, company_core_str, target_core_str).ratio()
    if ratio_core >= 0.85:
        return True
    
    return False


# ─────────────────────────────────────────────────────────────────────
# Main Algorithm
# ─────────────────────────────────────────────────────────────────────

def solve(target_company: str, input_csv: str, output_json: str):
    """Main solver function."""
    
    # Read CSV
    rows = []
    with open(input_csv, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    
    if not rows:
        print("No rows found in input CSV", file=sys.stderr)
        with open(output_json, 'w') as f:
            json.dump([], f)
        return
    
    # Identify column names
    col_names = list(rows[0].keys())
    company_col = None
    account_col = None
    date_col = None
    
    for col in col_names:
        cl = col.lower().strip()
        if 'company' in cl:
            company_col = col
        elif 'account' in cl:
            account_col = col
        elif 'date' in cl:
            date_col = col
    
    # Fallback: if company_col not found by 'company', try 'name'
    if company_col is None:
        for col in col_names:
            if 'name' in col.lower():
                company_col = col
                break
    
    if company_col is None:
        company_col = col_names[0]
    if account_col is None and len(col_names) > 1:
        account_col = col_names[1]
    if date_col is None and len(col_names) > 2:
        date_col = col_names[2]
    
    print(f"Target company: {target_company}", file=sys.stderr)
    print(f"Company column: {company_col}", file=sys.stderr)
    print(f"Account column: {account_col}", file=sys.stderr)
    print(f"Date column: {date_col}", file=sys.stderr)
    
    # ── Pass 1: Anchor Discovery ──
    # Find rows whose company name matches the target
    anchor_rows = []
    anchor_accounts = set()
    
    for i, row in enumerate(rows):
        company_name = row.get(company_col, '')
        if name_matches_target(company_name, target_company):
            anchor_rows.append(i)
            if account_col:
                acct = row.get(account_col, '').strip()
                if acct:
                    anchor_accounts.add(acct)
    
    print(f"Pass 1: Found {len(anchor_rows)} anchor rows", file=sys.stderr)
    print(f"Pass 1: Candidate accounts: {sorted(anchor_accounts)}", file=sys.stderr)
    
    # Debug: print matched company names
    matched_names = set()
    for i in anchor_rows:
        matched_names.add(rows[i].get(company_col, ''))
    print(f"Pass 1: Matched names: {sorted(matched_names)}", file=sys.stderr)
    
    # ── Pass 1.5: Near-Miss Account Filtering ──
    # Check if any candidate accounts are near-misses (1-2 char edit distance)
    # of other candidate accounts. If so, the near-miss is likely a typo and
    # should be excluded rather than established as a separate target account.
    #
    # Strategy: Accounts with multiple anchor rows are strongly established.
    # Accounts with only one anchor row that are near-misses of established
    # accounts are excluded.
    established_accounts = set()
    excluded_near_miss_accounts = set()
    
    # First pass: identify strongly established accounts (multiple anchors)
    account_anchor_counts = {}
    for i in anchor_rows:
        acct = rows[i].get(account_col, '').strip() if account_col else ''
        if acct:
            account_anchor_counts[acct] = account_anchor_counts.get(acct, 0) + 1
    
    for acct, count in account_anchor_counts.items():
        if count >= 2:
            established_accounts.add(acct)
    
    print(f"Pass 1.5: Strongly established accounts (≥2 anchors): {sorted(established_accounts)}", file=sys.stderr)
    
    # Second pass: for single-anchor accounts, check if they're near-misses
    for acct in anchor_accounts:
        if acct in established_accounts:
            continue
        if is_near_miss_account(acct, established_accounts, max_distance=2):
            excluded_near_miss_accounts.add(acct)
            print(f"Pass 1.5: Excluded near-miss account: {acct}", file=sys.stderr)
        else:
            # Not a near-miss — establish it
            established_accounts.add(acct)
    
    print(f"Pass 1.5: Final established accounts: {sorted(established_accounts)}", file=sys.stderr)
    
    # Remove anchor rows on excluded near-miss accounts
    anchor_rows = [i for i in anchor_rows 
                   if rows[i].get(account_col, '').strip() not in excluded_near_miss_accounts]
    
    print(f"Pass 1.5: After filtering, {len(anchor_rows)} anchor rows remain", file=sys.stderr)
    
    # ── Pass 2: Evidence Propagation (context-aware) ──
    # Include all rows on established accounts.
    #
    # The separate-entity check is NOT a hard gate here. Per the spec:
    # "Advisors, partners, or other separately named entities must remain
    #  excluded UNLESS the rows provide consistent evidence that they are
    #  the target itself."
    #
    # Being on an established target account IS consistent evidence.
    # So when a row has a separate-entity designator BUT is on a target
    # account AND its core name (after stripping designators) matches the
    # target, we include it — the account evidence overrides.
    included_indices = set(anchor_rows)
    
    for i, row in enumerate(rows):
        if i in included_indices:
            continue
        if account_col:
            acct = row.get(account_col, '').strip()
            if acct and acct in established_accounts:
                company_name = row.get(company_col, '')
                if is_separate_entity(company_name, target_company):
                    # Context-dependent override: if the core name (after
                    # stripping designators) matches the target AND we're on
                    # an established target account, this is "consistent evidence"
                    if core_name_matches_target(company_name, target_company):
                        included_indices.add(i)
                        print(f"Pass 2: Included (account override): {company_name} ({acct})", file=sys.stderr)
                    # else: core doesn't match target → truly different entity, exclude
                elif name_plausibly_related(company_name, target_company):
                    # Row is on an established target account AND has a plausible
                    # name relationship to the target (shorter alias, abbreviation, etc.)
                    included_indices.add(i)
                # else: completely unrelated company on target account → exclude
                # (handles account reuse patterns per spec)
    
    print(f"Pass 2: After propagation, {len(included_indices)} rows included", file=sys.stderr)
    
    # ── Pass 3: Distractor Sanity Check ──
    # For rows NOT on established accounts, apply the hard separate-entity filter.
    # For rows on established accounts, they were already vetted in Pass 2.
    # This pass catches any rows that slipped through via name-only matching
    # but are actually separate entities on non-target accounts.
    final_indices = set()
    for i in included_indices:
        row = rows[i]
        company_name = row.get(company_col, '')
        acct = row.get(account_col, '').strip() if account_col else ''
        
        if acct in established_accounts:
            # On an established target account — already vetted in Pass 2
            final_indices.add(i)
        elif is_separate_entity(company_name, target_company):
            # Not on a target account AND has a designator → exclude
            print(f"Pass 3: Excluded distractor: {company_name} ({acct})", file=sys.stderr)
        else:
            final_indices.add(i)
    
    print(f"Pass 3: After filtering, {len(final_indices)} rows included", file=sys.stderr)
    
    # ── Debug: Print all unique company names in the result ──
    result_companies = set()
    result_accounts = set()
    for i in final_indices:
        result_companies.add(rows[i].get(company_col, ''))
        if account_col:
            result_accounts.add(rows[i].get(account_col, ''))
    print(f"Result company names: {sorted(result_companies)}", file=sys.stderr)
    print(f"Result accounts: {sorted(result_accounts)}", file=sys.stderr)
    print(f"Excluded near-miss accounts: {sorted(excluded_near_miss_accounts)}", file=sys.stderr)
    
    # ── Output ──
    result = []
    for i in sorted(final_indices):
        row = rows[i]
        # Preserve all values as strings
        result.append({k: str(v) for k, v in row.items()})
    
    # Sort by date ascending
    if date_col:
        result.sort(key=lambda r: r.get(date_col, ''))
    
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"Wrote {len(result)} rows to {output_json}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Bank Transaction Filter")
    parser.add_argument('--target', default=os.environ.get('TARGET_COMPANY', DEFAULT_TARGET),
                        help='Target company name')
    parser.add_argument('--input', default=os.environ.get('INPUT_CSV', DEFAULT_INPUT),
                        help='Input CSV path')
    parser.add_argument('--output', default=os.environ.get('OUTPUT_JSON', DEFAULT_OUTPUT),
                        help='Output JSON path')
    args = parser.parse_args()
    
    solve(args.target, args.input, args.output)


if __name__ == '__main__':
    main()
