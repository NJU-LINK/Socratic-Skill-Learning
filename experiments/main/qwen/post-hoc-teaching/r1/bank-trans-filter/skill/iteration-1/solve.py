#!/usr/bin/env python3
"""
Bank Transaction Filter - Entity Resolution Solver

Filters bank transaction CSV rows to retain only those belonging to a target
company, handling abbreviation variants, legal-suffix variations, spelling
drift, and account-number-based identity propagation.

Usage:
    python3 solve.py --target "North West Capital" \
                     --input /app/data/bank_transactions.csv \
                     --output /app/data/output.json
"""

import argparse
import csv
import json
import re
import sys


###############################################################################
# Configuration
###############################################################################

# Legal suffixes: indicate the SAME legal entity in different form.
# These are stripped when comparing company names.
LEGAL_SUFFIXES = {
    'holdings', 'hldgs',
    'group', 'grp',
    'incorporated', 'inc',
    'corporation', 'corp',
    'limited', 'ltd',
    'company', 'co',
    'plc', 'llc', 'llp',
    'gmbh', 'ag', 'sa',
    'pty', 'pte',
    'enterprises', 'ventures',
}

# Entity-type indicators: signal a DIFFERENT organization, not a suffix variant.
# If a company name has these as extra words beyond the target, it's separate.
ENTITY_TYPE_INDICATORS = {
    'advisors', 'advisory', 'adviser', 'advisers',
    'partners', 'partner',
    'consulting', 'consultants',
    'services', 'solutions',
    'technologies', 'tech',
    'management', 'mgmt',
    'brokerage', 'broker',
    'trust', 'bank',
    'fund', 'funds',
    'energy', 'oil', 'gas',
    'airlines', 'shipping',
    'manufacturing', 'mfg',
    'construction', 'engineering',
    'pharmaceuticals', 'medical',
    'insurance',
    'real', 'estate',
    'food', 'beverage',
    'retail', 'wholesale',
    'logistics', 'delivery',
    'software', 'hardware',
    'media', 'entertainment',
    'aerospace', 'defense',
    'agriculture',
    'telecom', 'communications',
}

# Minimum common prefix length for token similarity matching
MIN_PREFIX_LEN = 3


###############################################################################
# Normalization helpers
###############################################################################

def normalize_name(name):
    """Lowercase, replace punctuation with spaces, collapse whitespace."""
    name = name.lower().strip()
    name = re.sub(r'[.\-_,;:\'\"/\\()]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def strip_legal_suffix(normalized_name, legal_suffixes):
    """Remove trailing legal suffixes iteratively (keep at least 1 word)."""
    words = normalized_name.split()
    while len(words) > 1 and words[-1] in legal_suffixes:
        words.pop()
    return ' '.join(words)


def build_abbreviation_map(target_words):
    """
    Build a context-dependent abbreviation map from the target name words.

    Generates mappings for:
    - Single-letter initials (n -> north)
    - Dotted initials (n. -> north)
    - Multi-letter fused initials (nw -> north west)
    - Dotted multi-letter initials (n.w. -> north west)
    - Truncations of 3-4 characters (cap -> capital, hldg -> holdings)
    - Fused spelling variants (northwest -> north west)
    """
    abbrev_map = {}

    # Per-word abbreviations
    for word in target_words:
        if len(word) == 0:
            continue
        # Single letter
        abbrev_map[word[0]] = word
        abbrev_map[word[0] + '.'] = word
        # Truncations (3 and 4 chars)
        for length in range(3, min(len(word), 5)):
            trunc = word[:length]
            abbrev_map[trunc] = word
            abbrev_map[trunc + '.'] = word

    # Multi-word abbreviations
    if len(target_words) >= 2:
        # Fused initials: "nw" -> "north west"
        initials = ''.join(w[0] for w in target_words)
        abbrev_map[initials] = ' '.join(target_words)

        # Dotted initials: "n.w." -> "north west"
        dotted = '.'.join(w[0] for w in target_words) + '.'
        abbrev_map[dotted] = ' '.join(target_words)

        # Uppercase initials: "NW" -> "north west"
        abbrev_map[initials.upper()] = ' '.join(target_words)

        # Fused spelling: "northwest" -> "north west"
        combined = ''.join(target_words[:2])
        abbrev_map[combined] = ' '.join(target_words[:2])

        # Also try all words fused
        if len(target_words) > 2:
            all_fused = ''.join(target_words)
            abbrev_map[all_fused] = ' '.join(target_words)

    return abbrev_map


def expand_abbreviations(normalized_name, abbrev_map):
    """Expand abbreviation tokens in a normalized name using the map."""
    words = normalized_name.split()
    expanded = []
    for word in words:
        if word in abbrev_map:
            expanded.append(abbrev_map[word])
        else:
            expanded.append(word)
    return ' '.join(expanded)


###############################################################################
# Token similarity
###############################################################################

def tokens_share_prefix(token_a, token_b, min_prefix=MIN_PREFIX_LEN):
    """Check if two tokens share a common prefix of at least min_prefix chars."""
    if len(token_a) < min_prefix or len(token_b) < min_prefix:
        return False
    common = 0
    for ca, cb in zip(token_a, token_b):
        if ca == cb:
            common += 1
        else:
            break
    return common >= min_prefix


def tokens_match_via_prefix(tokens_a, tokens_b, min_prefix=MIN_PREFIX_LEN):
    """
    Check if two token lists match when each pair is either equal or shares
    a common prefix of at least min_prefix characters.

    Handles truncation-based abbreviations at any length:
    - "cap" <-> "capital" (common prefix "cap", 3 chars)
    - "trade" <-> "trading" (common prefix "trad", 4 chars)
    - "intl" <-> "international" (common prefix "int", 3 chars)
    - "assoc" <-> "associates" (common prefix "assoc", 5 chars)
    """
    if len(tokens_a) != len(tokens_b):
        return False
    matches = 0
    for a, b in zip(tokens_a, tokens_b):
        if a == b:
            matches += 1
        elif tokens_share_prefix(a, b, min_prefix):
            matches += 1
    return matches == len(tokens_a)


###############################################################################
# Matching logic
###############################################################################

def is_name_match(company_name, target_name, legal_suffixes):
    """
    Check if a company name is a genuine variant of the target name.

    Pipeline:
    1. Normalize both names
    2. Try direct match
    3. Try match after stripping legal suffixes
    4. Try match after expanding abbreviations
    5. Try match after both stripping suffixes and expanding abbreviations
    6. Fallback: prefix-based token similarity (handles unseen truncations)
    """
    norm_company = normalize_name(company_name)
    norm_target = normalize_name(target_name)

    # Direct match
    if norm_company == norm_target:
        return True

    # After stripping legal suffixes
    company_stripped = strip_legal_suffix(norm_company, legal_suffixes)
    target_stripped = strip_legal_suffix(norm_target, legal_suffixes)

    if company_stripped == target_stripped:
        return True

    # Build abbreviation map from target
    target_words = norm_target.split()
    abbrev_map = build_abbreviation_map(target_words)

    # Expand abbreviations in company name
    company_expanded = expand_abbreviations(norm_company, abbrev_map)
    company_expanded_stripped = strip_legal_suffix(company_expanded, legal_suffixes)

    if company_expanded == target_stripped:
        return True
    if company_expanded_stripped == target_stripped:
        return True

    # Expand after stripping
    company_expanded2 = expand_abbreviations(company_stripped, abbrev_map)
    if company_expanded2 == target_stripped:
        return True

    # Also try: expand target abbreviations (in case target itself has abbrevs)
    target_expanded = expand_abbreviations(norm_target, abbrev_map)
    target_expanded_stripped = strip_legal_suffix(target_expanded, legal_suffixes)

    if norm_company == target_expanded_stripped:
        return True
    company_stripped2 = strip_legal_suffix(norm_company, legal_suffixes)
    if company_stripped2 == target_expanded_stripped:
        return True

    # Prefix-similarity fallback: handles truncation-based abbreviations at
    # any length without enumerating them. The entity-type-indicator guard
    # in the caller prevents false positives from this broader matching.
    final_company_tokens = strip_legal_suffix(
        expand_abbreviations(norm_company, abbrev_map), legal_suffixes
    ).split()
    final_target_tokens = target_stripped.split()
    if tokens_match_via_prefix(final_company_tokens, final_target_tokens):
        return True

    return False


def has_entity_type_indicator(company_name, target_name, legal_suffixes):
    """
    Check if the company name contains entity-type indicator words that
    signal a separate organization (not just a legal-suffix variant).
    """
    norm_company = normalize_name(company_name)
    norm_target = normalize_name(target_name)

    company_words = set(norm_company.split())
    target_words = set(norm_target.split())

    # Extra words in company name that are not in target and not legal suffixes
    extra_words = company_words - target_words - legal_suffixes

    # Check if any extra word is an entity-type indicator
    for word in extra_words:
        if word in ENTITY_TYPE_INDICATORS:
            return True

    return False


###############################################################################
# Contradiction guard for account propagation
###############################################################################

def name_contradicts_target(company_name, target_name, legal_suffixes,
                            entity_type_indicators, abbrev_map=None):
    """
    Return True if the name clearly belongs to a DIFFERENT entity.
    Conservative: only reject when there's strong evidence.

    Used during account-number propagation to avoid including rows that
    belong to unrelated entities that happen to share an account number
    (account reuse, data-entry errors, etc.).
    """
    norm = normalize_name(company_name)
    target_norm = normalize_name(target_name)

    # Expand abbreviations if map provided
    if abbrev_map:
        norm = expand_abbreviations(norm, abbrev_map)

    company_words = set(strip_legal_suffix(norm, legal_suffixes).split())
    target_words = set(strip_legal_suffix(target_norm, legal_suffixes).split())

    # Check 1: Entity-type indicators in extra words -> contradiction
    extra = company_words - target_words - legal_suffixes
    if extra & entity_type_indicators:
        return True

    # Check 2: No word in company name shares even a prefix with any target
    # word (after abbreviation expansion). This catches completely unrelated
    # names while allowing short aliases and partial matches.
    if company_words:
        has_any_prefix_match = False
        for cw in company_words:
            for tw in target_words:
                if tokens_share_prefix(cw, tw):
                    has_any_prefix_match = True
                    break
            if has_any_prefix_match:
                break

        if not has_any_prefix_match:
            return True

    return False


###############################################################################
# Main solver
###############################################################################

def solve(target_name, csv_path, output_path):
    """
    Main solution pipeline:
    1. Read CSV
    2. Iteratively: match rows by name + propagate through accounts
       until no new rows are discovered
    3. Sort by date and write JSON output
    """
    # Read CSV
    rows = []
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Build abbreviation map for contradiction guard
    target_norm = normalize_name(target_name)
    target_words = target_norm.split()
    abbrev_map = build_abbreviation_map(target_words)

    matched_rows = []
    target_accounts = set()
    matched_ids = set()

    # Iterate until stable (handles chained evidence: name -> account -> name -> account)
    prev_count = -1
    while len(matched_ids) > prev_count:
        prev_count = len(matched_ids)

        # Phase 1: Find rows matching by name
        for i, row in enumerate(rows):
            if i in matched_ids:
                continue
            name = row['Company Name']
            if is_name_match(name, target_name, LEGAL_SUFFIXES) and \
               not has_entity_type_indicator(name, target_name, LEGAL_SUFFIXES):
                matched_rows.append(row)
                target_accounts.add(row['Account Number'])
                matched_ids.add(i)

        # Phase 2: Guarded account propagation
        for i, row in enumerate(rows):
            if i in matched_ids:
                continue
            if row['Account Number'] in target_accounts:
                # Check that the name doesn't contradict the target
                if not name_contradicts_target(
                    row['Company Name'], target_name,
                    LEGAL_SUFFIXES, ENTITY_TYPE_INDICATORS, abbrev_map
                ):
                    matched_rows.append(row)
                    target_accounts.add(row['Account Number'])
                    matched_ids.add(i)

    # Sort by date ascending
    matched_rows.sort(key=lambda r: r['Date'])

    # Format output - preserve exact CSV values as strings
    output_keys = ['Company Name', 'Account Number', 'Date', 'Amount',
                   'Transaction Type', 'Description']
    output = []
    for row in matched_rows:
        output.append({key: row[key] for key in output_keys})

    # Write JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(output)} rows to {output_path}")
    print(f"Target accounts: {sorted(target_accounts)}")
    return output


def extract_target_from_instruction(instruction_text):
    """
    Extract the target company name from the task instruction.
    Looks for pattern: 'belong to <TARGET>.'
    """
    m = re.search(r'belong to\s+(.+?)\.', instruction_text)
    if m:
        return m.group(1).strip()
    return None


###############################################################################
# CLI
###############################################################################

def main():
    parser = argparse.ArgumentParser(
        description='Filter bank transactions for a target company')
    parser.add_argument('--target', required=True,
                        help='Target company name')
    parser.add_argument('--input', default='/app/data/bank_transactions.csv',
                        help='Input CSV file path')
    parser.add_argument('--output', default='/app/data/output.json',
                        help='Output JSON file path')
    parser.add_argument('--instruction', default=None,
                        help='Task instruction text (alternative to --target)')

    args = parser.parse_args()

    target = args.target
    if args.instruction and not args.target:
        target = extract_target_from_instruction(args.instruction)
        if not target:
            print("ERROR: Could not extract target from instruction",
                  file=sys.stderr)
            sys.exit(1)

    solve(target, args.input, args.output)


if __name__ == '__main__':
    main()
