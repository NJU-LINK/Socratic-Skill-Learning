import json
import subprocess
from pathlib import Path

import yaml


USERS_PATH = Path("/app/users.json")
OUTPUT_PATH = Path("/app/status_dashboard.json")
CMD_PATH = Path("/app/cmd.sh")
JQ_ARGS_PATH = Path("/app/jq_args.yaml")


def expected_dashboard(users, min_count=150):
    grouped = {}
    for user in users:
        status = user.get("status")
        if status is None:
            continue
        grouped.setdefault(status, []).append(user)

    result = []
    for status in sorted(grouped):
        members = grouped[status]
        if len(members) < min_count:
            continue
        latest = max(members, key=lambda user: user["last_login"])
        result.append(
            {
                "status": status,
                "user_count": len(members),
                "average_role_count": sum(len(user["roles"]) for user in members)
                / len(members),
                "most_recent_user": {
                    "user_id": latest["id"],
                    "username": latest["username"],
                    "email": latest["email"],
                    "last_login": latest["last_login"].split("T", 1)[0],
                    "primary_role": latest["roles"][0] if latest["roles"] else None,
                },
            }
        )
    return result


def test_output_matches_expected_transformation():
    users = json.loads(USERS_PATH.read_text())
    actual = json.loads(OUTPUT_PATH.read_text())
    assert actual == expected_dashboard(users)


def test_output_is_sorted_and_complete():
    users = json.loads(USERS_PATH.read_text())
    actual = json.loads(OUTPUT_PATH.read_text())

    qualifying_statuses = sorted(
        {
            user["status"]
            for user in users
            if sum(1 for candidate in users if candidate["status"] == user["status"]) >= 150
        }
    )

    assert [entry["status"] for entry in actual] == qualifying_statuses


def test_output_uses_two_space_pretty_printing():
    parsed = json.loads(OUTPUT_PATH.read_text())
    expected_text = json.dumps(parsed, indent=2) + "\n"
    assert OUTPUT_PATH.read_text() == expected_text


def test_cmd_and_jq_args_reproduce_output():
    output_text = OUTPUT_PATH.read_text()
    actual = json.loads(output_text)
    jq_args = yaml.safe_load(JQ_ARGS_PATH.read_text())

    assert set(jq_args) == {"filter", "args"}
    assert isinstance(jq_args["filter"], str) and jq_args["filter"].strip()
    assert jq_args["args"] == ["--argjson min_count 150"]

    reproduced = subprocess.run(
        ["/bin/bash", "-lc", 'jq $(yq -r ".args[]" /app/jq_args.yaml) "$(yq -r ".filter" /app/jq_args.yaml)" /app/users.json'],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(reproduced.stdout) == actual

    subprocess.run(["/bin/bash", str(CMD_PATH)], check=True)
    assert OUTPUT_PATH.read_text() == output_text

    cmd_text = CMD_PATH.read_text()
    assert cmd_text.startswith("#!/bin/bash\n")
    assert "jq --argjson min_count 150" in cmd_text
    assert "/app/users.json > /app/status_dashboard.json" in cmd_text
