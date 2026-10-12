import hashlib
import json
import os
import subprocess
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import yaml


OUTPUT_PATH = "/app/monthly_login_rollup.json"
INPUT_PATH = "/app/users.json"
CMD_PATH = "/app/cmd.sh"
YAML_PATH = "/app/jq_args.yaml"
HASH_PATH = "/app/.auto_gen_key.dat"
SECRET_KEY = "terminal-bench-2025-secret-seed"


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def round_half_up(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expected_rollup():
    users = load_json(INPUT_PATH)
    grouped = defaultdict(list)

    for user in users:
        if user["status"] != "active":
            continue

        grouped[user["last_login"][:7]].append(
            {
                "username": user["username"],
                "primary_role": user["roles"][0] if user["roles"] else None,
                "role_count": len(user["roles"]),
            }
        )

    rollup = []
    for month in sorted(grouped, reverse=True):
        monthly_users = grouped[month]
        role_total = sum(user["role_count"] for user in monthly_users)
        top_users = sorted(
            monthly_users,
            key=lambda user: (-user["role_count"], user["username"]),
        )[:3]
        rollup.append(
            {
                "login_month": month,
                "active_user_count": len(monthly_users),
                "avg_role_count": round_half_up(role_total / len(monthly_users)),
                "top_users": top_users,
            }
        )

    return rollup


def test_output_matches_expected_rollup():
    assert os.path.exists(OUTPUT_PATH), f"Missing output file: {OUTPUT_PATH}"
    assert load_json(OUTPUT_PATH) == expected_rollup()


def test_output_is_pretty_printed_with_two_space_indent():
    parsed = load_json(OUTPUT_PATH)
    with open(OUTPUT_PATH, "r", encoding="utf-8") as handle:
        raw = handle.read()

    assert raw == json.dumps(parsed, indent=2) + "\n"


def test_months_and_top_users_follow_required_ordering():
    rollup = load_json(OUTPUT_PATH)
    months = [entry["login_month"] for entry in rollup]
    assert months == sorted(months, reverse=True)

    for entry in rollup:
        top_users = entry["top_users"]
        assert len(top_users) <= 3
        assert top_users == sorted(
            top_users,
            key=lambda user: (-user["role_count"], user["username"]),
        )


def test_cmd_sh_recreates_identical_output():
    assert os.path.exists(CMD_PATH), f"Missing command file: {CMD_PATH}"

    with open(CMD_PATH, "r", encoding="utf-8") as handle:
        command_text = handle.read()

    assert "jq" in command_text
    assert "/app/users.json" in command_text
    assert "/app/monthly_login_rollup.json" in command_text
    for forbidden in ("python", "ruby", "perl", "node", "java"):
        assert forbidden not in command_text

    with open(OUTPUT_PATH, "r", encoding="utf-8") as handle:
        original = handle.read()

    subprocess.run(["bash", CMD_PATH], check=True)

    with open(OUTPUT_PATH, "r", encoding="utf-8") as handle:
        regenerated = handle.read()

    assert regenerated == original


def test_jq_args_yaml_has_required_shape_and_recreates_output():
    assert os.path.exists(YAML_PATH), f"Missing YAML file: {YAML_PATH}"

    with open(YAML_PATH, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert set(data) == {"filter", "args"}
    assert isinstance(data["filter"], str)
    assert isinstance(data["args"], list)
    assert data["args"] == ["--indent 2"]

    result = subprocess.run(
        'jq $(yq -r ".args[]" /app/jq_args.yaml) "$(yq -r ".filter" /app/jq_args.yaml)" /app/users.json',
        shell=True,
        check=True,
        capture_output=True,
        text=True,
    )

    with open(OUTPUT_PATH, "r", encoding="utf-8") as handle:
        actual = handle.read()

    assert result.stdout == actual


def test_input_file_was_not_modified():
    assert os.path.exists(HASH_PATH), f"Missing hash file: {HASH_PATH}"

    with open(INPUT_PATH, "rb") as handle:
        content = handle.read()
    current_hash = hashlib.sha256(content + SECRET_KEY.encode("utf-8")).hexdigest()

    with open(HASH_PATH, "r", encoding="utf-8") as handle:
        original_hash = handle.read().strip()

    assert current_hash == original_hash
