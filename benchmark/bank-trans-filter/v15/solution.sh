#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import json
import re
from pathlib import Path

OUTPUT_PATH = Path("/app/data/output.json")
FIELDNAMES = [
    "Company Name",
    "Account Number",
    "Date",
    "Amount",
    "Transaction Type",
    "Description",
]


def candidate_input_paths() -> list[Path]:
    script_dir = Path.cwd()
    return [
        Path("/app/data/bank_transactions.csv"),
        script_dir / "input" / "data" / "bank_transactions.csv",
        script_dir.parent / "input" / "data" / "bank_transactions.csv",
    ]


def normalize_tokens(name: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return {token for token in cleaned.split() if token}


def account_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(lch != rch for lch, rch in zip(left, right))


def has_strong_target_name(name: str) -> bool:
    tokens = normalize_tokens(name)
    return "nwcg" in tokens or {"north", "west", "capital"}.issubset(tokens)


def has_account_support_name(name: str) -> bool:
    tokens = normalize_tokens(name)
    return "nwcg" in tokens or {"north", "west", "capital"}.issubset(tokens)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def choose_input_path() -> Path:
    best_path = None
    best_score = -1
    for path in candidate_input_paths():
        if not path.exists():
            continue
        rows = load_rows(path)
        score = sum(has_strong_target_name(row["Company Name"]) for row in rows)
        if score > best_score:
            best_score = score
            best_path = path
    if best_path is None:
        raise FileNotFoundError("Could not locate bank_transactions.csv")
    return best_path


rows = load_rows(choose_input_path())

trusted_accounts = {
    row["Account Number"] for row in rows if has_strong_target_name(row["Company Name"])
}

selected_rows = []
for row in rows:
    company_name = row["Company Name"]
    account_number = row["Account Number"]

    include = False
    if has_strong_target_name(company_name):
        include = True
    elif account_number in trusted_accounts and has_account_support_name(company_name):
        include = True
    elif any(
        account_distance(account_number, trusted_account) == 1
        for trusted_account in trusted_accounts
    ) and has_account_support_name(company_name):
        include = True

    if include:
        selected_rows.append({field: row[field] for field in FIELDNAMES})

selected_rows.sort(key=lambda row: row["Date"])
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(json.dumps(selected_rows, indent=2), encoding="utf-8")
PY
