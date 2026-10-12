#!/bin/bash

set -euo pipefail

python3 <<'PY'
import csv
import json
import re
from pathlib import Path


INPUT_PATH = Path("/app/data/bank_transactions.csv")
OUTPUT_PATH = Path("/app/data/output.json")
TARGET_TOKENS = ["north", "west", "capital"]
LEGAL_TOKENS = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "incoporated",
    "limited",
    "ltd",
    "llc",
    "pty",
}
OPTIONAL_TARGET_TOKENS = {"group", "grp", "gp"}
ACCOUNT_TRANSLATION = str.maketrans({
    "B": "8",
    "G": "0",
    "I": "1",
    "L": "1",
    "O": "0",
    "Q": "0",
    "S": "5",
    "Z": "2",
})


def tokenize_name(name: str) -> list[str]:
    return [letters_only(part) for part in re.split(r"[^A-Za-z0-9]+", name) if letters_only(part)]


def letters_only(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalpha())


def edit_distance(left: str, right: str) -> int:
    row = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        next_row = [i]
        for j, right_char in enumerate(right, start=1):
            next_row.append(
                min(
                    row[j] + 1,
                    next_row[-1] + 1,
                    row[j - 1] + (left_char != right_char),
                )
            )
        row = next_row
    return row[-1]


def skeleton(token: str) -> str:
    token = letters_only(token)
    if not token:
        return ""
    return token[0] + "".join(ch for ch in token[1:] if ch not in "aeiou")


TARGET_SKELETONS = [skeleton(token) for token in TARGET_TOKENS]
TARGET_INITIALISMS = {
    "".join(token[0] for token in TARGET_TOKENS),
    "".join(token[0] for token in TARGET_TOKENS) + "g",
}


def normalize_account(account: str) -> str:
    account = account.upper()
    if "-" not in account:
        return account.translate(ACCOUNT_TRANSLATION)
    prefix, suffix = account.split("-", 1)
    return f"{prefix}-{suffix.translate(ACCOUNT_TRANSLATION)}"


def substantive_tokens(name: str) -> list[str]:
    return [token for token in tokenize_name(name) if token not in LEGAL_TOKENS]


def is_target_name(name: str) -> bool:
    tokens = substantive_tokens(name)
    if not tokens:
        return False

    if len(tokens) == 1:
        short = skeleton(tokens[0])
        return any(edit_distance(short, candidate) <= 1 for candidate in TARGET_INITIALISMS)

    filtered = [token for token in tokens if token not in OPTIONAL_TARGET_TOKENS]
    if len(filtered) != len(TARGET_TOKENS):
        return False

    return all(
        edit_distance(skeleton(found), expected) <= 1
        for found, expected in zip(filtered, TARGET_SKELETONS)
    )


def is_related_non_target(name: str) -> bool:
    tokens = substantive_tokens(name)
    if not tokens:
        return False

    filtered = [token for token in tokens if token not in OPTIONAL_TARGET_TOKENS]
    target_like = sum(
        any(edit_distance(skeleton(token), expected) <= 1 for token in filtered)
        for expected in TARGET_SKELETONS
    )
    return target_like == len(TARGET_TOKENS) and not is_target_name(name)


with INPUT_PATH.open(newline="") as handle:
    rows = list(csv.DictReader(handle))

anchor_rows = [row for row in rows if is_target_name(row["Company Name"]) and not is_related_non_target(row["Company Name"])]
target_accounts = {normalize_account(row["Account Number"]) for row in anchor_rows}

selected_rows = []
for row in rows:
    if is_related_non_target(row["Company Name"]):
        continue
    if is_target_name(row["Company Name"]) or normalize_account(row["Account Number"]) in target_accounts:
        selected_rows.append(
            {
                "Company Name": row["Company Name"],
                "Account Number": row["Account Number"],
                "Date": row["Date"],
                "Amount": row["Amount"],
                "Transaction Type": row["Transaction Type"],
                "Description": row["Description"],
            }
        )

selected_rows.sort(key=lambda row: row["Date"])

with OUTPUT_PATH.open("w") as handle:
    json.dump(selected_rows, handle, indent=2)
PY
