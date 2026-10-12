#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import json
import re

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


def canonical_tokens(value: str) -> list[str]:
    raw_tokens = re.findall(r"[a-z0-9]+", value.lower())
    expanded: list[str] = []
    for token in raw_tokens:
        if token == "nwcg":
            expanded.extend(["north", "west", "capital", "group"])
        elif token == "northwest":
            expanded.extend(["north", "west"])
        elif token == "nw":
            expanded.extend(["north", "west"])
        elif token == "n":
            expanded.append("north")
        elif token == "w":
            expanded.append("west")
        elif token == "cap":
            expanded.append("capital")
        elif token == "grp":
            expanded.append("group")
        elif token in {"inc", "incorporated", "incoporated"}:
            expanded.append("incorporated")
        else:
            expanded.append(token)
    return expanded


def has_related_entity_token(tokens: set[str]) -> bool:
    blocked_prefixes = ("serv", "partn", "hold")
    return any(token.startswith(prefix) for token in tokens for prefix in blocked_prefixes)


def is_direct_target_name(name: str) -> bool:
    tokens = set(canonical_tokens(name))
    if has_related_entity_token(tokens):
        return False
    return {"north", "west", "capital"}.issubset(tokens)


with open(INPUT_PATH, newline="") as handle:
    rows = list(csv.DictReader(handle))

target_accounts = {
    row["Account Number"]
    for row in rows
    if is_direct_target_name(row["Company Name"])
}

filtered_rows = [
    row
    for row in rows
    if is_direct_target_name(row["Company Name"])
    or row["Account Number"] in target_accounts
]
filtered_rows.sort(key=lambda row: row["Date"])

with open(OUTPUT_PATH, "w") as handle:
    json.dump(
        [{field: row[field] for field in FIELDNAMES} for row in filtered_rows],
        handle,
        indent=2,
    )
PY
