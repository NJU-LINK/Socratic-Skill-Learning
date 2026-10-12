#!/bin/bash
set -euo pipefail

INPUT_CSV="${BANK_TRANSACTIONS_CSV:-/app/data/bank_transactions.csv}"
OUTPUT_JSON="${OUTPUT_JSON:-/app/data/output.json}"

python3 - <<'PY'
import csv
import json
import os
import re
from pathlib import Path

input_csv = Path(os.environ.get("BANK_TRANSACTIONS_CSV", "/app/data/bank_transactions.csv"))
output_json = Path(os.environ.get("OUTPUT_JSON", "/app/data/output.json"))

ACCOUNT_TRANSLATION = str.maketrans({
    "O": "0",
    "o": "0",
    "g": "0",
})

LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "corp",
    "corporation",
    "co",
    "group",
    "holdings",
    "advisors",
}


def normalize_account(value: str) -> str:
    return value.upper().translate(ACCOUNT_TRANSLATION)


def normalize_name(value: str) -> list[str]:
    text = value.lower()
    text = text.replace("n.", "north ")
    text = re.sub(r"\bn\s*\.\s*w\b", "north west", text)
    text = re.sub(r"\bn\s+w\b", "north west", text)
    text = re.sub(r"\bnw\b", "north west", text)
    text = re.sub(r"\bcptl\b", "capital", text)
    text = re.sub(r"\bcap\b", "capital", text)
    words = re.findall(r"[a-z]+", text)
    return [word for word in words if word not in LEGAL_SUFFIXES]


def is_targetish_name(value: str) -> bool:
    words = normalize_name(value)
    joined = " ".join(words)
    return "north west capital" in joined


with input_csv.open(newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))

target_accounts = {
    normalize_account(row["Account Number"])
    for row in rows
    if is_targetish_name(row["Company Name"])
}

filtered_rows = []
for row in rows:
    targetish_name = is_targetish_name(row["Company Name"])
    normalized_account = normalize_account(row["Account Number"])

    if targetish_name or normalized_account in target_accounts:
        filtered_rows.append(row)

filtered_rows.sort(key=lambda row: row["Date"])

output_json.parent.mkdir(parents=True, exist_ok=True)
output_json.write_text(json.dumps(filtered_rows, indent=2), encoding="utf-8")
PY
