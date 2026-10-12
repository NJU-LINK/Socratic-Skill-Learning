#!/usr/bin/env python3
"""
Bank transaction entity-resolution filter.

Given a target company name, finds all transactions belonging to that entity
across spelling variants, abbreviations, punctuation changes, legal-suffix
changes, and account-number variations.  Excludes separately-named entities
(Advisors, Partners, etc.) even when their names partially overlap the target.
Also detects and excludes near-miss account numbers (differing by 1-2 chars
from a more-frequent legitimate account).

Usage:
    python3 filter_transactions.py "Target Company Name" [input_csv] [output_json]

Defaults:
    input_csv  = /app/data/bank_transactions.csv
    output_json = /app/data/output.json
"""

import csv
import json
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Suffix taxonomy
# ---------------------------------------------------------------------------

# Generic / structural suffixes that may vary freely within the same entity.
# These are stripped before computing core-identity token overlap.
GENERIC_SUFFIXES = {
    "group", "holdings", "hldgs", "inc", "llc", "corp", "ltd", "co",
    "company", "corporation", "limited", "incorporated", "plc", "gmbh",
    "llp", "lp", "trust", "fund", "bank", "financial", "intl",
    "international", "tech", "technologies", "solutions", "systems",
    "industries", "services",
}

# Suffixes that signal a *separately named* entity related to the target.
# Rows whose names contain these tokens in suffix position are excluded
# even when their core tokens match the target.
ENTITY_SUFFIXES = {
    "advisors", "advisory", "partners", "consulting", "consultancy",
    "management", "wealth", "research", "labs", "laboratories",
    "institute", "foundation",
}

# ---------------------------------------------------------------------------
# Abbreviation / contraction dictionary
# ---------------------------------------------------------------------------

ABBREVIATIONS = {
    "cap":   "capital",
    "hldgs": "holdings",
    "co":    "company",
    "corp":  "corporation",
    "inc":   "incorporated",
    "ltd":   "limited",
    "intl":  "international",
    "tech":  "technologies",
    "assoc": "associates",
    "mfg":   "manufacturing",
    "svc":   "services",
    "svcs":  "services",
    "dept":  "department",
    "div":   "division",
    "natl":  "national",
    "nat":   "national",
    "am":    "asset management",
    "nw":    "north west",
    "ne":    "north east",
    "sw":    "south west",
    "se":    "south east",
    "n":     "north",
    "s":     "south",
    "e":     "east",
    "w":     "west",
}

# Compound directional words that should be split for token-level matching.
DIRECTIONAL_COMPOUNDS = {
    "northwest":  "north west",
    "northeast":  "north east",
    "southwest":  "south west",
    "southeast":  "south east",
    "northcentral": "north central",
    "southcentral": "south central",
}

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def normalize(name: str) -> str:
    """Lowercase, strip punctuation (except internal hyphens), collapse spaces."""
    name = name.strip().lower()
    name = re.sub(r"[.,'\"!?;:()]", " ", name)
    name = re.sub(r"\s+", " ", name)
    return name


def expand(name: str) -> str:
    """Expand abbreviations and split directional compounds."""
    # First, split directional compounds BEFORE token-level abbreviation expansion
    for compound, replacement in DIRECTIONAL_COMPOUNDS.items():
        name = re.sub(rf"\b{re.escape(compound)}\b", replacement, name)
    tokens = name.split()
    expanded = []
    for t in tokens:
        if t in ABBREVIATIONS:
            expanded.extend(ABBREVIATIONS[t].split())
        else:
            expanded.append(t)
    return " ".join(expanded)


def strip_generic_suffixes(tokens: list[str]) -> list[str]:
    """Remove trailing generic suffixes from a token list."""
    while tokens and tokens[-1] in GENERIC_SUFFIXES:
        tokens = tokens[:-1]
    return tokens


def has_entity_suffix(tokens: list[str]) -> bool:
    """Return True if the last 1-2 tokens indicate a separate entity."""
    if not tokens:
        return False
    # Check last token
    if tokens[-1] in ENTITY_SUFFIXES:
        return True
    # Check last two tokens as a compound
    if len(tokens) >= 2:
        bigram = f"{tokens[-2]} {tokens[-1]}"
        if bigram in ENTITY_SUFFIXES:
            return True
    return False


def core_tokens(name: str) -> list[str]:
    """Return the core identity tokens of a company name."""
    normed = normalize(name)
    expanded = expand(normed)
    toks = expanded.split()
    return strip_generic_suffixes(toks)


def token_overlap_score(query_tokens: list[str], target_tokens: list[str]) -> float:
    """Fraction of *target* tokens present in query_tokens."""
    if not target_tokens:
        return 0.0
    hits = sum(1 for t in target_tokens if t in query_tokens)
    return hits / len(target_tokens)


# ---------------------------------------------------------------------------
# Near-miss account detection
# ---------------------------------------------------------------------------

def edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(
                curr[j] + 1,       # insertion
                prev[j + 1] + 1,   # deletion
                prev[j] + cost,    # substitution
            ))
        prev = curr
    return prev[-1]


def filter_near_miss_accounts(
    accounts: set[str],
    account_row_counts: dict[str, int],
    max_distance: int = 2,
) -> set[str]:
    """Remove near-miss accounts that are likely typos of more-frequent accounts.

    For each pair of established accounts within max_distance edit distance,
    the account with fewer rows is treated as a distractor and removed.
    Ties are broken by keeping the lexicographically first account.
    """
    account_list = sorted(accounts)
    suspicious: set[str] = set()

    for i in range(len(account_list)):
        for j in range(i + 1, len(account_list)):
            a, b = account_list[i], account_list[j]
            if a in suspicious or b in suspicious:
                continue  # already marked
            dist = edit_distance(a, b)
            if dist <= max_distance:
                # Keep the account with more rows; mark the other as suspicious
                count_a = account_row_counts.get(a, 0)
                count_b = account_row_counts.get(b, 0)
                if count_a > count_b:
                    suspicious.add(b)
                elif count_b > count_a:
                    suspicious.add(a)
                else:
                    # Equal counts: keep the one with longer history or
                    # lexicographic order (deterministic tiebreak)
                    suspicious.add(max(a, b))

    return accounts - suspicious


# ---------------------------------------------------------------------------
# Main entity-resolution pipeline
# ---------------------------------------------------------------------------

def resolve_and_filter(target_name: str, input_csv: str, output_json: str):
    # Read all rows
    with open(input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Compute target core tokens
    tgt_core = core_tokens(target_name)
    if not tgt_core:
        print(f"ERROR: Could not extract any core tokens from target '{target_name}'",
              file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Phase 1: Identify target aliases via strong name match
    # ------------------------------------------------------------------
    name_to_rows: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        name_to_rows[row["Company Name"]].append(row)

    target_aliases: set[str] = set()
    for company_name in name_to_rows:
        ct = core_tokens(company_name)
        expanded_name = expand(normalize(company_name))
        expanded_tokens = expanded_name.split()

        overlap = token_overlap_score(ct, tgt_core)
        is_entity = has_entity_suffix(expanded_tokens)

        # Strong match: ALL target core tokens present, no entity suffix
        if overlap >= 1.0 and not is_entity:
            target_aliases.add(company_name)

    # ------------------------------------------------------------------
    # Phase 2: Establish accounts from anchor rows
    # ------------------------------------------------------------------
    raw_accounts: set[str] = set()
    account_row_counts: dict[str, int] = defaultdict(int)
    for alias in target_aliases:
        for row in name_to_rows[alias]:
            acct = row["Account Number"]
            raw_accounts.add(acct)
            account_row_counts[acct] += 1

    # Phase 2b: Filter near-miss accounts (distractor detection)
    # Account numbers are identifiers — near-miss accounts (edit distance ≤ 2)
    # where one has far fewer rows are likely typos / planted distractors.
    established_accounts = filter_near_miss_accounts(
        raw_accounts, account_row_counts, max_distance=2
    )

    removed = raw_accounts - established_accounts
    if removed:
        print(f"Near-miss accounts removed ({len(removed)}): "
              f"{sorted(removed)}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Phase 3: Propagate – include rows on established accounts whose
    #           name is a partial match (handles shorter aliases that
    #           didn't pass Phase 1 on their own).
    #           Iterate until stable.
    # ------------------------------------------------------------------
    included_names: set[str] = set(target_aliases)
    changed = True
    while changed:
        changed = False
        for company_name, comp_rows in name_to_rows.items():
            if company_name in included_names:
                continue
            ct = core_tokens(company_name)
            expanded_name = expand(normalize(company_name))
            expanded_tokens = expanded_name.split()
            is_entity = has_entity_suffix(expanded_tokens)
            if is_entity:
                continue

            # Check if any row of this company is on an established account
            on_established = any(
                r["Account Number"] in established_accounts for r in comp_rows
            )
            if on_established:
                overlap = token_overlap_score(ct, tgt_core)
                # Weaker threshold for propagation – at least half of target
                # core tokens, or at least 1 token if target has only 1.
                threshold = 0.5 if len(tgt_core) > 1 else 1.0
                if overlap >= threshold:
                    included_names.add(company_name)
                    for r in comp_rows:
                        acct = r["Account Number"]
                        if acct not in established_accounts:
                            # Before adding, check it's not a near-miss of
                            # an existing established account
                            is_near_miss = False
                            for est in established_accounts:
                                if edit_distance(acct, est) <= 2:
                                    is_near_miss = True
                                    break
                            if not is_near_miss:
                                established_accounts.add(acct)
                                changed = True

    # ------------------------------------------------------------------
    # Phase 4: Collect all included rows
    # ------------------------------------------------------------------
    included_rows = []
    for row in rows:
        cn = row["Company Name"]
        acct = row["Account Number"]
        if cn in included_names:
            # Only include if the account is an established one
            # (filter out rows on near-miss distractor accounts)
            if acct in established_accounts:
                included_rows.append(row)
            # If name matches but account is a near-miss distractor, skip
        elif acct in established_accounts:
            # Row is on an established account but company name wasn't
            # included via alias/propagation.  Include only if name
            # partially matches and has no entity suffix.
            ct = core_tokens(cn)
            expanded_name = expand(normalize(cn))
            expanded_tokens = expanded_name.split()
            if has_entity_suffix(expanded_tokens):
                continue
            overlap = token_overlap_score(ct, tgt_core)
            if overlap >= 0.5:
                included_rows.append(row)

    # ------------------------------------------------------------------
    # Sort by Date ascending (string sort works for YYYY-MM-DD)
    # ------------------------------------------------------------------
    included_rows.sort(key=lambda r: r["Date"])

    # ------------------------------------------------------------------
    # Write output JSON – all values as strings, exact from CSV
    # ------------------------------------------------------------------
    output_keys = [
        "Company Name", "Account Number", "Date",
        "Amount", "Transaction Type", "Description",
    ]
    output = [{k: row[k] for k in output_keys} for row in included_rows]

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Summary to stderr
    print(f"Target: '{target_name}' → core tokens: {tgt_core}", file=sys.stderr)
    print(f"Aliases found ({len(target_aliases)}): "
          f"{sorted(target_aliases)}", file=sys.stderr)
    print(f"Raw accounts before near-miss filter: "
          f"{sorted(raw_accounts)}", file=sys.stderr)
    print(f"Established accounts ({len(established_accounts)}): "
          f"{sorted(established_accounts)}", file=sys.stderr)
    print(f"Included names ({len(included_names)}): "
          f"{sorted(included_names)}", file=sys.stderr)
    print(f"Output rows: {len(output)}", file=sys.stderr)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "North West Capital"
    csv_path = sys.argv[2] if len(sys.argv) > 2 else "/app/data/bank_transactions.csv"
    json_path = sys.argv[3] if len(sys.argv) > 3 else "/app/data/output.json"
    resolve_and_filter(target, csv_path, json_path)
