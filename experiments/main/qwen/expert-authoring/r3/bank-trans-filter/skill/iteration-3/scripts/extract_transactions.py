#!/usr/bin/env python3
"""
Extract bank transactions belonging to a target company using entity resolution.

Usage:
    python3 extract_transactions.py <input_csv> <target_company> <output_json>

Performs fuzzy entity resolution across company names, establishes target
accounts through evidence propagation with a confirmation threshold, and
excludes separately-named entities (Advisors, Advisory, Partners, etc.).

Uses a 4-level matching cascade:
  Level 1: Token Jaccard >= 0.6
  Level 2: Substring containment
  Level 3: Compound-word resolution (splits "northwest" -> "north west")
  Level 4: Word-level fuzzy match (Levenshtein edit distance ratio <= 0.45)

No external dependencies -- uses only Python standard library.
"""

import csv
import json
import re
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------

SEPARATE_BUSINESS_WORDS = {
    "advisors", "advisory", "partners", "consulting", "consultancy",
    "associates", "ventures", "fund", "management",
}

LEGAL_SUFFIXES = {
    "group", "holdings", "hldgs", "ltd", "limited", "inc", "incorporated",
    "corp", "corporation", "llc", "co", "company", "plc", "lp", "llp",
    "pty", "gmbh", "ag", "sa", "bv", "nv",
}

# Abbreviation map -- period-free forms (periods are stripped before lookup).
ABBREVIATION_MAP = {
    "n w": "north west", "nw": "north west",
    "cap": "capital",
    "intl": "international",
    "mfg": "manufacturing",
    "svcs": "services",
    "sys": "systems",
    # With-period fallback forms
    "n.w.": "north west", "n. w.": "north west",
    "n.w": "north west", "nw.": "north west",
    "cap.": "capital", "intl.": "international",
    "mfg.": "manufacturing", "svcs.": "services", "sys.": "systems",
}

# Minimum number of confirmed-alias rows on an account before it is
# considered "established".
MIN_ROWS_TO_ESTABLISH = 2


# ---------------------------------------------------------------------------
# 2. Normalisation helpers
# ---------------------------------------------------------------------------

def normalise_company_name(name: str) -> str:
    """
    Produce a canonical lowercase token sequence:
      1. lowercase
      2. strip periods (before abbreviation lookup!)
      3. expand abbreviations
      4. strip remaining punctuation
      5. collapse whitespace
    """
    n = name.lower().strip()
    n = n.replace('.', '')  # strip periods FIRST
    for abbr, full in sorted(ABBREVIATION_MAP.items(),
                             key=lambda x: -len(x[0])):
        n = re.sub(r'\b' + re.escape(abbr) + r'\b', full, n)
    n = re.sub(r"[^a-z0-9\s-]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def extract_core_words(normalised: str) -> str:
    """Return core words (excluding legal suffixes and separate-business words)."""
    tokens = normalised.split()
    core = [t for t in tokens
            if t not in LEGAL_SUFFIXES and t not in SEPARATE_BUSINESS_WORDS]
    return " ".join(core)


def has_separate_business_indicator(name: str) -> bool:
    """True if the company name contains a separate-business keyword."""
    tokens = normalise_company_name(name).split()
    return any(t in SEPARATE_BUSINESS_WORDS for t in tokens)


# ---------------------------------------------------------------------------
# 3. Matching cascade helpers
# ---------------------------------------------------------------------------

def levenshtein(a: str, b: str) -> int:
    """Edit distance between two strings."""
    if len(a) < len(b):
        return levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def try_split_compound(token: str, dict_words: set) -> str:
    """If token is concatenation of 2+ dict words, split it."""
    for i in range(1, len(token)):
        left, right = token[:i], token[i:]
        if left in dict_words and right in dict_words:
            return left + " " + right
        for j in range(i + 1, len(token)):
            mid, right2 = token[i:j], token[j:]
            if (left in dict_words and mid in dict_words
                    and right2 in dict_words):
                return left + " " + mid + " " + right2
    return token


def resolve_compounds(candidate_core: str, target_core: str) -> str:
    """Split compound words using target core words as dictionary."""
    dict_words = set(target_core.split())
    return " ".join(
        try_split_compound(t, dict_words) for t in candidate_core.split()
    )


def word_fuzzy_match(core_a: str, core_b: str,
                     max_edit_ratio: float = 0.45) -> bool:
    """Word-by-word Levenshtein match; requires same word count."""
    wa, wb = core_a.split(), core_b.split()
    if len(wa) != len(wb):
        return False
    for a, b in zip(wa, wb):
        if levenshtein(a, b) / max(len(a), len(b), 1) > max_edit_ratio:
            return False
    return True


def is_core_match(name_core: str, target_core: str,
                  threshold: float = 0.6) -> bool:
    """4-level matching cascade."""
    # Level 1: Token Jaccard
    sa, sb = set(name_core.split()), set(target_core.split())
    if sa and sb and len(sa & sb) / len(sa | sb) >= threshold:
        return True
    # Level 2: Substring containment
    if target_core in name_core or name_core in target_core:
        return True
    # Level 3: Compound-word resolution
    resolved = resolve_compounds(name_core, target_core)
    if resolved != name_core:
        sa2, sb2 = set(resolved.split()), set(target_core.split())
        if sa2 and sb2 and len(sa2 & sb2) / len(sa2 | sb2) >= threshold:
            return True
        if target_core in resolved or resolved in target_core:
            return True
    # Level 4: Word-level fuzzy match (edit distance)
    if word_fuzzy_match(name_core, target_core, max_edit_ratio=0.45):
        return True
    if (resolved != name_core
            and word_fuzzy_match(resolved, target_core, max_edit_ratio=0.45)):
        return True
    return False


# ---------------------------------------------------------------------------
# 4. Main resolution logic
# ---------------------------------------------------------------------------

def resolve_target_transactions(rows, target_company: str):
    """
    Given CSV row dicts and target company name, return
    (matched_rows, confirmed_aliases, established_accounts, acct_counts).
    """
    target_norm = normalise_company_name(target_company)
    target_core = extract_core_words(target_norm)

    unique_names = set(r["Company Name"] for r in rows)

    # --- confirmed aliases ---
    confirmed_aliases = set()
    for name in unique_names:
        if has_separate_business_indicator(name):
            continue
        norm = normalise_company_name(name)
        core = extract_core_words(norm)
        if is_core_match(core, target_core):
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
# 5. Entry point
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

    # Sort by Date ascending
    matched.sort(key=lambda r: r["Date"])

    # Write JSON array with exact string values
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(matched, f, indent=2, ensure_ascii=False)

    # Diagnostic summary
    target_core = extract_core_words(normalise_company_name(target_company))
    print(f"Target: {target_company!r}", file=sys.stderr)
    print(f"Target core: {target_core!r}", file=sys.stderr)
    print(f"Confirmed aliases ({len(aliases)}):", file=sys.stderr)
    for a in sorted(aliases):
        core = extract_core_words(normalise_company_name(a))
        print(f"  {a!r} -> core={core!r}", file=sys.stderr)
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
