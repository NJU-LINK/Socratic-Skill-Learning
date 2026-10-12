#!/bin/bash

set -euo pipefail

python3 - <<'PY'
import csv
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

INPUT_PATH = Path("/app/data/bank_transactions.csv")
OUTPUT_PATH = Path("/app/data/output.json")
TARGET_NAME = "North West Capital Group Incorporated"
TARGET_TOKENS = {"north", "west", "capital", "group", "incorporated", "nwcg"}
DISTRACTOR_TOKENS = {"advisors", "advisory", "services", "partners", "llc"}
ACCOUNT_CONFUSIONS = str.maketrans({"O": "0", "Q": "0", "D": "0", "G": "0", "I": "1", "L": "1"})


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def tokenize_name(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def normalize_account(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper()).translate(ACCOUNT_CONFUSIONS)


def is_target_name(value: str) -> bool:
    normalized = normalize_name(value)
    if "nwcg" in normalized:
        return True

    target = normalize_name(TARGET_NAME)
    similarity = SequenceMatcher(None, normalized, target).ratio()
    return similarity >= 0.82 and "group" in normalized


def has_conflicting_name(value: str) -> bool:
    tokens = tokenize_name(value)
    if not tokens or is_target_name(value):
        return False

    if tokens & DISTRACTOR_TOKENS and "group" not in tokens and "nwcg" not in tokens:
        return True

    return not bool(tokens & TARGET_TOKENS)


def has_supportive_name(value: str) -> bool:
    if is_target_name(value):
        return True

    tokens = tokenize_name(value)
    if not tokens or tokens & DISTRACTOR_TOKENS:
        return False

    return len(tokens & {"north", "west", "capital", "nwcg", "group"}) >= 2


with INPUT_PATH.open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))

anchor_rows = [row for row in rows if is_target_name(row["Company Name"])]
trusted_accounts = {row["Account Number"] for row in anchor_rows}
trusted_account_keys = {normalize_account(row["Account Number"]) for row in anchor_rows}

changed = True
while changed:
    changed = False
    for row in rows:
        account = row["Account Number"]
        account_key = normalize_account(account)
        if account in trusted_accounts or account_key not in trusted_account_keys:
            continue
        if has_supportive_name(row["Company Name"]):
            trusted_accounts.add(account)
            changed = True

filtered_rows = [
    row
    for row in rows
    if row["Account Number"] in trusted_accounts and not has_conflicting_name(row["Company Name"])
]
filtered_rows.sort(key=lambda row: row["Date"])

with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
    json.dump(filtered_rows, handle, indent=2)
PY
