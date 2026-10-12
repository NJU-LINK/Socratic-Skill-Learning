#!/bin/bash

python3 - <<'PY'
import csv
import json
import re
from collections import Counter, defaultdict

INPUT_PATH = "/app/data/bank_transactions.csv"
OUTPUT_PATH = "/app/data/output.json"
FIELDNAMES = [
    "Company Name",
    "Account Number",
    "Date",
    "Amount",
    "Transaction Type",
    "Description",
]
IGNORED_TOKENS = {"group", "holdings", "hldgs"}
DISTRACTOR_TOKENS = {"advisor", "advisory", "advisors", "partner", "partners"}


def normalize_company(name: str) -> str:
    normalized = name.lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    tokens = [token for token in normalized.split() if token not in IGNORED_TOKENS]
    return " ".join(tokens)


def is_target_alias(name: str) -> bool:
    tokens = set(normalize_company(name).split())
    if tokens & DISTRACTOR_TOKENS:
        return False
    long_form = {"north", "west"}.issubset(tokens) and ({"capital"} <= tokens or {"cap"} <= tokens)
    short_form = {"n", "w"}.issubset(tokens) and ({"capital"} <= tokens or {"cap"} <= tokens)
    return long_form or short_form


with open(INPUT_PATH, newline="") as handle:
    rows = list(csv.DictReader(handle))

alias_account_counts = defaultdict(Counter)
for row in rows:
    if is_target_alias(row["Company Name"]):
        alias_account_counts[normalize_company(row["Company Name"])][row["Account Number"]] += 1

target_accounts = set()
for account_counts in alias_account_counts.values():
    max_count = max(account_counts.values())
    for account, count in account_counts.items():
        # A single confirmed alias row is enough unless the same alias is more strongly tied to another account.
        if len(account_counts) == 1 or count == max_count:
            target_accounts.add(account)

filtered_rows = [row for row in rows if row["Account Number"] in target_accounts]
filtered_rows.sort(key=lambda row: row["Date"])

with open(OUTPUT_PATH, "w") as handle:
    json.dump([{field: row[field] for field in FIELDNAMES} for row in filtered_rows], handle, indent=2)
PY
