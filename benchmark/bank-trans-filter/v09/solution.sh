#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import json
import re
from collections import defaultdict, deque

INPUT_PATH = "/app/data/bank_transactions.csv"
OUTPUT_PATH = "/app/data/output.json"

TARGET_TOKENS = {"north", "west", "capital"}
ANCHOR_PATTERNS = [
    re.compile(r"\bnorth\s*w\.?\s*cap\.?\b"),
    re.compile(r"\bnw\s*capital\s*group\b"),
    re.compile(r"\bnorth\s*west\s*capital\b"),
]
DISTRACTOR_PATTERNS = [
    re.compile(r"\bnorthwind\b"),
    re.compile(r"\bnorthwest\s+capital\s+services\b"),
    re.compile(r"\bwest\s+capital\s+partners\b"),
    re.compile(r"\bnwc\s+advisory\b"),
]


def normalize_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def is_anchor_name(name: str) -> bool:
    lowered = name.lower()
    if any(pattern.search(lowered) for pattern in DISTRACTOR_PATTERNS):
        return False
    if any(pattern.search(lowered) for pattern in ANCHOR_PATTERNS):
        return True
    return TARGET_TOKENS.issubset(normalize_tokens(name))


with open(INPUT_PATH, newline="") as f:
    rows = list(csv.DictReader(f))

account_to_rows: dict[str, list[int]] = defaultdict(list)
name_to_rows: dict[str, list[int]] = defaultdict(list)

for idx, row in enumerate(rows):
    account_to_rows[row["Account Number"]].append(idx)
    name_to_rows[row["Company Name"]].append(idx)

seed_accounts = set()
seed_names = set()
for row in rows:
    if is_anchor_name(row["Company Name"]):
        seed_accounts.add(row["Account Number"])
        seed_names.add(row["Company Name"])

queue = deque([("account", account) for account in sorted(seed_accounts)] + [("name", name) for name in sorted(seed_names)])
seen_accounts = set(seed_accounts)
seen_names = set(seed_names)
included_row_indexes = set()

while queue:
    kind, value = queue.popleft()
    row_indexes = account_to_rows[value] if kind == "account" else name_to_rows[value]
    for idx in row_indexes:
        if idx in included_row_indexes:
            continue
        included_row_indexes.add(idx)
        row = rows[idx]
        account = row["Account Number"]
        name = row["Company Name"]
        if account not in seen_accounts:
            seen_accounts.add(account)
            queue.append(("account", account))
        if name not in seen_names:
            seen_names.add(name)
            queue.append(("name", name))

output_rows = [rows[idx] for idx in sorted(included_row_indexes, key=lambda idx: rows[idx]["Date"])]

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output_rows, f, indent=2)
    f.write("\n")
PY
