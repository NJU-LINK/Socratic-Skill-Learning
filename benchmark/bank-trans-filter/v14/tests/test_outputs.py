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
EXPECTED_KEYS = [
    "Company Name",
    "Account Number",
    "Date",
    "Amount",
    "Transaction Type",
    "Description",
]


def letters_only(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalpha())


def tokenize_name(name: str) -> list[str]:
    return [letters_only(part) for part in re.split(r"[^A-Za-z0-9]+", name) if letters_only(part)]


def skeleton(token: str) -> str:
    token = letters_only(token)
    if not token:
        return ""
    return token[0] + "".join(ch for ch in token[1:] if ch not in "aeiou")


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


TARGET_SKELETONS = [skeleton(token) for token in TARGET_TOKENS]
TARGET_INITIALISMS = {
    "".join(token[0] for token in TARGET_TOKENS),
    "".join(token[0] for token in TARGET_TOKENS) + "g",
}


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


def normalize_account(account: str) -> str:
    account = account.upper()
    if "-" not in account:
        return account.translate(ACCOUNT_TRANSLATION)
    prefix, suffix = account.split("-", 1)
    return f"{prefix}-{suffix.translate(ACCOUNT_TRANSLATION)}"


def load_rows() -> list[dict[str, str]]:
    with INPUT_PATH.open(newline="") as handle:
        return list(csv.DictReader(handle))


def expected_output() -> list[dict[str, str]]:
    rows = load_rows()
    anchor_rows = [row for row in rows if is_target_name(row["Company Name"]) and not is_related_non_target(row["Company Name"])]
    target_accounts = {normalize_account(row["Account Number"]) for row in anchor_rows}

    expected = []
    for row in rows:
        if is_related_non_target(row["Company Name"]):
            continue
        if is_target_name(row["Company Name"]) or normalize_account(row["Account Number"]) in target_accounts:
            expected.append({key: row[key] for key in EXPECTED_KEYS})

    expected.sort(key=lambda row: row["Date"])
    return expected


def load_output() -> list[dict[str, str]]:
    assert OUTPUT_PATH.exists(), f"missing output file: {OUTPUT_PATH}"
    with OUTPUT_PATH.open() as handle:
        return json.load(handle)


def test_output_matches_csv_derived_expectation():
    output = load_output()
    assert output == expected_output()


def test_output_is_sorted_and_preserves_exact_csv_rows():
    rows = load_rows()
    csv_rows = [{key: row[key] for key in EXPECTED_KEYS} for row in rows]
    output = load_output()

    assert [list(item.keys()) for item in output] == [EXPECTED_KEYS] * len(output)
    assert output == sorted(output, key=lambda row: row["Date"])

    for item in output:
        assert item in csv_rows
        assert all(isinstance(item[key], str) for key in EXPECTED_KEYS)


def test_account_linking_and_distractor_exclusion():
    output = load_output()
    output_pairs = {(row["Company Name"], row["Account Number"], row["Date"]) for row in output}

    # These rows must be included only if account-link evidence is used.
    assert ("NWC Gp Inc", "BUS-300O1", "2024-03-01") in output_pairs
    assert ("NWCG Inc. Pty. Ltd.", "BUS-30g01", "2024-02-02") in output_pairs

    # These related entities share the stem but belong to separate accounts.
    assert ("North West Capital Partners", "BUS-30007", "2024-01-25") not in output_pairs
    assert ("North West Capital Holdings", "BUS-30017", "2024-01-26") not in output_pairs
    assert ("North West Capital Services", "BUS-30002", "2024-02-05") not in output_pairs
