#!/usr/bin/env python3
"""
Extract bank transactions belonging to a target company using entity resolution.

Usage:
    python3 extract_transactions.py <input_csv> <target_company> <output_json>

Performs fuzzy entity resolution across company names, establishes target
accounts through evidence propagation with a confirmation threshold, and
excludes separately-named entities (Advisors, Advisory, Partners, etc.).

No external dependencies — uses only Python standard library.
"""

import csv
import json
import re
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# 1. Name normalisation helpers
# ---------------------------------------------------------------------------

# Suffixes that indicate a *separate* business entity rather than a
# legal-suffix variation of the target.
SEPARATE_BUSINESS_WORDS = {
    "advisors", "advisory", "partners", "consulting", "consultancy",
    "associates", "ventures", "fund", "management",
}

# Common legal / entity-type suffixes that do NOT indicate a separate entity.
LEGAL_SUFFIXES = {
    "group", "holdings", "hldgs", "ltd", "limited", "inc", "incorporated",
    "corp", "corporation", "llc", "co", "company", "plc", "lp", "llp",
    "pty", "gmbh", "ag", "sa", "bv", "nv",
}

# Common abbreviation expansions (lowercase keys).
ABBREVIATION_MAP = {
    "n.w.":  "north west",
    "n.w":   "north west",
    "nw.":   "north west",
    "nw":    "north west",
    "cap.":  "capital",
    "cap":   "capital",
    "intl.": "international",
    "intl":  "international",
    "mfg.":  "manufacturing",
    "mfg":   "manufacturing",
    "tech.": "tech",
    "mgmt.": "management",
    "svcs.": "services",
    "svcs":  "services",
    "sys.":  "systems",
    "sys":   "systems",
}

# Minimum number of confirmed-alias rows on an account before it is
# considered "established".  Protects against single-occurrence false
# positives where a similarly-named entity appears once by coincidence.
MIN_ROWS_TO_ESTABLISH = 2


def expand_abbreviations(name: str) -> str:
    """Replace known abbreviations with their full forms (case-insensitive)."""
    lower = name.lower()
    for abbr, full in sorted(ABBREVIATION_MAP.items(), key=lambda x: -len(x[0])):
        lower = re.sub(r'\b' + re.escape(abbr) + r'\b', full, lower)
    return lower


def normalise_company_name(name: str) -> str:
    """
    Produce a canonical lowercase token sequence for a company name:
      - lowercase
      - expand abbreviations
      - remove punctuation (except internal hyphens)
      - collapse whitespace
    """
    n = name.lower().strip()
    n = expand_abbreviations(n)
    n = re.sub(r"[^a-z0-9\s-]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def extract_core_words(normalised: str):
    """
    Return core_string (tokens that are not legal suffixes or separate-business
    indicators).
    """
    tokens = normalised.split()
    core = [t for t in tokens
            if t not in LEGAL_SUFFIXES and t not in SEPARATE_BUSINESS_WORDS]
    return " ".join(core)


def has_separate_business_indicator(name: str) -> bool:
    """True if the company name contains a separate-business keyword."""
    tokens = normalise_company_name(name).split()
    return any(t in SEPARATE_BUSINESS_WORDS for t in tokens)


# ---------------------------------------------------------------------------
# 2. Similarity / matching
# ---------------------------------------------------------------------------

def jaccard_similarity(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def is_core_match(name_norm: str, target_core: str,
                  threshold: float = 0.6) -> bool:
    """
    Check whether the core of a normalised name matches the target core.
    Uses Jaccard similarity plus substring containment as fallback.
    """
    name_core = extract_core_words(name_norm)
    if jaccard_similarity(name_core, target_core) >= threshold:
        return True
    if target_core in name_core or name_core in target_core:
        return True
    return False


# ---------------------------------------------------------------------------
# 3. Main resolution logic
# ---------------------------------------------------------------------------

def resolve_target_transactions(rows, target_company: str):
    """
    Given a list of CSV row dicts and the target company name string,
    return (matched_rows, confirmed_aliases, established_accounts).

    Algorithm:
      1. Normalise the target to get target_core.
      2. For each unique company name:
           a) Core words match target core  AND
           b) No separate-business suffix
         → confirmed alias.
      3. Count confirmed-alias rows per account.
      4. Establish accounts with >= MIN_ROWS_TO_ESTABLISH confirmed-alias rows.
      5. Include every row on established accounts whose company name
         does NOT carry a separate-business indicator.
    """
    target_norm = normalise_company_name(target_company)
    target_core = extract_core_words(target_norm)

    unique_names = set(r["Company Name"] for r in rows)

    # --- confirmed aliases ---
    confirmed_aliases = set()
    for name in unique_names:
        name_norm = normalise_company_name(name)
        if not is_core_match(name_norm, target_core):
            continue
        if has_separate_business_indicator(name):
            continue
        confirmed_aliases.add(name)

    # --- established accounts (with confirmation threshold) ---
    acct_confirmed_count = defaultdict(int)
    for r in rows:
        if r["Company Name"] in confirmed_aliases:
            acct_confirmed_count[r["Account Number"]] += 1

    established_accounts = {
        acct for acct, cnt in acct_confirmed_count.items()
        if cnt >= MIN_ROWS_TO_ESTABLISH
    }

    # --- matching rows (with explicit exclusion filter) ---
    result = []
    for r in rows:
        if r["Account Number"] in established_accounts:
            if not has_separate_business_indicator(r["Company Name"]):
                result.append(r)

    return result, confirmed_aliases, established_accounts, acct_confirmed_count


# ---------------------------------------------------------------------------
# 4. Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <input_csv> "
              "<target_company> <output_json>", file=sys.stderr)
        sys.exit(1)

    input_csv, target_company, output_json = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(input_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    matched, aliases, accounts, acct_counts = resolve_target_transactions(
        rows, target_company)

    # Sort by Date ascending (stable sort keeps original order for ties)
    matched.sort(key=lambda r: r["Date"])

    # Write JSON array with exact string values
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(matched, f, indent=2, ensure_ascii=False)

    # Diagnostic summary
    print(f"Target: {target_company!r}", file=sys.stderr)
    target_core = extract_core_words(normalise_company_name(target_company))
    print(f"Target core: {target_core!r}", file=sys.stderr)
    print(f"Confirmed aliases ({len(aliases)}): {sorted(aliases)}",
          file=sys.stderr)
    print(f"Confirmed-alias counts per account:", file=sys.stderr)
    for acct in sorted(acct_counts):
        status = "ESTABLISHED" if acct in accounts else "rejected"
        print(f"  {acct}: {acct_counts[acct]} rows [{status}]",
              file=sys.stderr)
    print(f"Established accounts ({len(accounts)}): {sorted(accounts)}",
          file=sys.stderr)
    print(f"Matched transactions: {len(matched)}", file=sys.stderr)


if __name__ == "__main__":
    main()
