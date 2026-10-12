#!/bin/bash
set -euo pipefail

python3 <<'PY'
import csv
import json
import re
from pathlib import Path

input_path = Path("/app/data/bank_transactions.csv")
output_path = Path("/app/data/output.json")


def normalize_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def is_strong_target_name(name: str) -> bool:
    normalized = normalize_company(name)
    if normalized.startswith("north western capital advisor"):
        return False
    return (
        "north west capital" in normalized
        or "north west cap" in normalized
        or normalized.startswith("nwcg")
    )


with input_path.open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))

target_accounts = {
    row["Account Number"]
    for row in rows
    if is_strong_target_name(row["Company Name"])
}

filtered_rows = [
    row
    for row in rows
    if is_strong_target_name(row["Company Name"]) or row["Account Number"] in target_accounts
]

filtered_rows.sort(key=lambda row: row["Date"])

output_path.write_text(json.dumps(filtered_rows, indent=2), encoding="utf-8")
PY
