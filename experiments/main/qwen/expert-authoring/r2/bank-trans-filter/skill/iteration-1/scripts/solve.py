#!/usr/bin/env python3
"""
Bank Transaction Filter — Entity Resolution

Filters a CSV of bank transactions to keep only rows belonging to a target
company, handling name variants, account typos, and distractor entities.

Usage:
    python3 solve.py [--target "North West Capital"]
                     [--input  /app/data/bank_transactions.csv]
                     [--output /app/data/output.json]
"""

import argparse
import csv
import json
import re
import string
import sys
from difflib import SequenceMatcher


# ── Configuration ──────────────────────────────────────────────────────

# Suffixes that signal a SEPARATE entity (subsidiary, partner, advisor)
# even when the core name overlaps the target.
DISQUALIFYING_SUFFIXES = [
    "advisors", "advisor", "advisory",
    "partners", "partner",
]

# Generic legal / structural suffixes to strip during normalization.
# These do NOT signal a separate entity — they are just structural words.
STRUCTURAL_SUFFIXES = {
    "llc", "inc", "corp", "corporation", "ltd", "limited",
    "company", "co", "group", "holdings", "hldgs", "holding",
    "services", "service", "solutions", "systems",
    "industries", "technologies", "technology", "tech",
    "consulting", "consultancy",
    # Note: "advisors", "advisory", "partners" are NOT here because
    # they are checked separately as disqualifying suffixes.
}


# ── Normalization helpers ──────────────────────────────────────────────

def strip_punctuation(s: str) -> str:
    """Remove all punctuation characters from a string."""
    return s.translate(str.maketrans("", "", string.punctuation))


def tokenize_name(name: str) -> set[str]:
    """
    Normalize a company name and return its core tokens with structural
    suffixes removed.
    """
    lower = name.strip().lower()
    no_punct = strip_punctuation(lower)
    tokens = no_punct.split()
    # Remove structural suffixes (but NOT disqualifying ones — those are
    # checked separately against the original name).
    core = {t for t in tokens if t not in STRUCTURAL_SUFFIXES}
    return core if core else set(tokens)  # fallback if all tokens removed


def has_disqualifying_suffix(name: str) -> bool:
    """
    Return True if the original (un-normalized) name ends with a suffix
    that signals a separate entity.
    """
    lower = name.strip().lower()
    # Check the last word (after stripping punctuation from the end).
    last_word = re.split(r'\s+', lower.rstrip(string.punctuation))[-1]
    last_word_clean = last_word.strip(string.punctuation)
    return last_word_clean in DISQUALIFYING_SUFFIXES


def get_initials(name: str) -> list[str]:
    """
    Extract single-letter initials from a name's core tokens.
    'North West Capital' → ['n', 'w', 'c']
    """
    tokens = tokenize_name(name)
    return sorted([t[0] for t in tokens if len(t) >= 2])


# ── Similarity scoring ────────────────────────────────────────────────

def token_overlap_score(name_core: set[str], target_core: set[str]) -> float:
    """
    Fraction of the name's core tokens that appear in the target's core.
    Returns a score in [0, 1].
    """
    if not name_core:
        return 0.0
    return len(name_core & target_core) / len(name_core)


def sequence_similarity(name_a: str, name_b: str) -> float:
    """
    SequenceMatcher ratio on lowercased, punctuation-stripped names
    (with structural suffixes removed).
    """
    a = " ".join(sorted(tokenize_name(name_a)))
    b = " ".join(sorted(tokenize_name(name_b)))
    return SequenceMatcher(None, a, b).ratio()


def abbreviation_match(name: str, target: str) -> float:
    """
    Check if a name uses initial-style abbreviation of the target.
    e.g., "N.W. Capital Holdings" vs "North West Capital"
    Returns a bonus score (0.0 or 1.0).
    """
    target_initials = set(get_initials(target))
    if not target_initials:
        return 0.0
    name_lower = name.strip().lower()
    no_punct = strip_punctuation(name_lower)
    tokens = no_punct.split()
    # Find single/double-char tokens that could be initials
    name_initials = {t for t in tokens if len(t) <= 2 and t.isalpha()}
    # Check if all target initials are present
    if target_initials and target_initials.issubset(name_initials):
        return 1.0
    # Partial match: if most initials match
    overlap = len(target_initials & name_initials)
    if overlap >= len(target_initials) - 1 and len(target_initials) >= 2:
        return 0.8
    return 0.0


def compute_match_score(company_name: str, target_name: str) -> float:
    """
    Compute the best match score between a company name and the target.
    Combines token overlap, sequence similarity, and abbreviation detection.
    """
    name_core = tokenize_name(company_name)
    target_core = tokenize_name(target_name)

    t_overlap = token_overlap_score(name_core, target_core)
    seq_sim = sequence_similarity(company_name, target_name)
    abbr = abbreviation_match(company_name, target_name)

    # Take the maximum of the three signals.
    # If abbreviation match is high, it overrides.
    return max(t_overlap, seq_sim, abbr)


# ── Account edit distance ─────────────────────────────────────────────

def account_edit_distance(a: str, b: str) -> int:
    """Simple Levenshtein distance for account number strings."""
    if a == b:
        return 0
    len_a, len_b = len(a), len(b)
    if abs(len_a - len_b) > 3:
        return max(len_a, len_b)  # too different
    # Standard DP
    dp = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, len_b + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[len_b]


# ── Main algorithm ────────────────────────────────────────────────────

def solve(target_name: str, input_path: str, output_path: str) -> None:
    # Read CSV
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Read {len(rows)} rows from {input_path}")
    print(f"Target entity: '{target_name}'")
    print()

    # ── Pass 1: Score every unique company name against the target ──

    unique_names = sorted(set(r["Company Name"] for r in rows))
    name_scores = {}
    for name in unique_names:
        score = compute_match_score(name, target_name)
        disqualified = has_disqualifying_suffix(name)
        name_scores[name] = (score, disqualified)

    # Threshold for "strong match"
    MATCH_THRESHOLD = 0.70

    strong_names = {
        name for name, (score, disq) in name_scores.items()
        if score >= MATCH_THRESHOLD and not disq
    }

    print("=== Name match scores ===")
    for name in sorted(unique_names, key=lambda n: -name_scores[n][0]):
        score, disq = name_scores[name]
        if score > 0.3 or disq:
            marker = "✓ STRONG" if name in strong_names else (
                "✗ DISQUALIFIED" if disq else "  weak"
            )
            print(f"  {score:.2f}  {marker:16s}  {name}")
    print()

    # ── Pass 2: Establish target accounts ──

    target_accounts = set()
    for r in rows:
        if r["Company Name"] in strong_names:
            target_accounts.add(r["Account Number"])

    print(f"=== Established target accounts ({len(target_accounts)}) ===")
    for acct in sorted(target_accounts):
        # Show which names use this account
        names_on_acct = sorted(set(
            r["Company Name"] for r in rows if r["Account Number"] == acct
        ))
        print(f"  {acct}: {names_on_acct}")
    print()

    # ── Pass 3: Include rows ──

    included = []
    excluded = []

    for r in rows:
        name = r["Company Name"]
        acct = r["Account Number"]
        score, disqualified = name_scores[name]
        name_core = tokenize_name(name)
        target_core = tokenize_name(target_name)

        # Rule 1: Strong name match, no disqualifying suffix
        if name in strong_names:
            included.append(r)
            continue

        # Rule 2: Account in target_accounts AND name has some overlap
        #         AND no disqualifying suffix
        if acct in target_accounts and not disqualified:
            overlap = len(name_core & target_core)
            if overlap >= 1:
                included.append(r)
                continue

        # Rule 3: Account typo recovery — strong name match with near-miss
        #         account (edit distance ≤ 2 from a target account)
        if score >= MATCH_THRESHOLD and not disqualified:
            for ta in target_accounts:
                if account_edit_distance(acct, ta) <= 2:
                    # Check that this account is not used by a different entity
                    other_names = set(
                        r2["Company Name"] for r2 in rows
                        if r2["Account Number"] == acct
                        and r2["Company Name"] != name
                    )
                    other_are_target = all(
                        n in strong_names for n in other_names
                    )
                    if not other_names or other_are_target:
                        included.append(r)
                        print(f"  [typo-recovery] {name} / {acct} "
                              f"(near {ta})")
                        break
            else:
                excluded.append(r)
            continue

        excluded.append(r)

    # ── Sort and write output ──

    included.sort(key=lambda r: r["Date"])

    print()
    print(f"=== Results ===")
    print(f"  Included: {len(included)} rows")
    print(f"  Excluded: {len(excluded)} rows")

    # Print included entity summary
    inc_names = sorted(set(r["Company Name"] for r in included))
    inc_accts = sorted(set(r["Account Number"] for r in included))
    print(f"  Entities included: {inc_names}")
    print(f"  Accounts included: {inc_accts}")

    # Sanity: print excluded names that had any non-trivial score
    excl_suspicious = [
        r for r in excluded
        if name_scores[r["Company Name"]][0] > 0.3
        or name_scores[r["Company Name"]][1]
    ]
    if excl_suspicious:
        print(f"\n  Excluded with notable scores:")
        for r in excl_suspicious:
            score, disq = name_scores[r["Company Name"]]
            print(f"    {r['Company Name']} ({r['Account Number']}) "
                  f"score={score:.2f} disq={disq}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(included, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {output_path}")


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bank Transaction Filter")
    parser.add_argument(
        "--target",
        default="North West Capital",
        help="Target company name to filter for",
    )
    parser.add_argument(
        "--input",
        default="/app/data/bank_transactions.csv",
        help="Path to input CSV",
    )
    parser.add_argument(
        "--output",
        default="/app/data/output.json",
        help="Path to output JSON",
    )
    args = parser.parse_args()
    solve(args.target, args.input, args.output)
