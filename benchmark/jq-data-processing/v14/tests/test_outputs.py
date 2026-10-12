import json
import shlex
import subprocess
from pathlib import Path

import yaml


USERS_PATH = Path("/app/users.json")
OUTPUT_PATH = Path("/app/review_queue.json")
CMD_PATH = Path("/app/cmd.sh")
JQ_ARGS_PATH = Path("/app/jq_args.yaml")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def expected_queue(users):
    items = []
    for user in users:
        if user["status"] not in {"pending", "inactive"}:
            continue
        normalized_username = user["username"].lower()
        if normalized_username.endswith("_tmp") or normalized_username.endswith("_banned"):
            continue
        roles = user["roles"]
        items.append(
            {
                "account": {
                    "user_id": user["id"],
                    "username": normalized_username,
                    "email": user["email"],
                    "status": user["status"],
                },
                "access": {
                    "role_count": len(roles),
                    "primary_role": roles[0] if roles else "none",
                },
            }
        )
    return sorted(items, key=lambda item: (-item["access"]["role_count"], item["account"]["username"]))


def test_review_queue_matches_required_transformation():
    users = load_json(USERS_PATH)
    actual = load_json(OUTPUT_PATH)
    assert actual == expected_queue(users)


def test_output_contains_nested_schema_and_fallback_cases():
    actual = load_json(OUTPUT_PATH)
    assert isinstance(actual, list)
    assert actual, "review queue should not be empty"

    fallback_items = [item for item in actual if item["access"]["primary_role"] == "none"]
    assert fallback_items, "expected at least one user with empty roles to exercise fallback"

    for item in actual:
        assert set(item) == {"account", "access"}
        assert set(item["account"]) == {"user_id", "username", "email", "status"}
        assert set(item["access"]) == {"role_count", "primary_role"}
        assert item["account"]["username"] == item["account"]["username"].lower()
        assert item["account"]["status"] in {"pending", "inactive"}
        assert not item["account"]["username"].endswith("_tmp")
        assert not item["account"]["username"].endswith("_banned")
        assert isinstance(item["access"]["role_count"], int)
        assert isinstance(item["access"]["primary_role"], str)


def test_saved_command_and_jq_args_reconstruct_output():
    cmd_text = CMD_PATH.read_text(encoding="utf-8")
    assert "jq --indent 2" in cmd_text
    assert "/app/users.json > /app/review_queue.json" in cmd_text

    jq_args = yaml.safe_load(JQ_ARGS_PATH.read_text(encoding="utf-8"))
    assert list(jq_args) == ["filter", "args"]
    assert jq_args["args"] == ["--indent 2"]
    assert isinstance(jq_args["filter"], str)
    assert "ascii_downcase" in jq_args["filter"]

    command = (
        f"jq $(yq -r '.args[]' {shlex.quote(str(JQ_ARGS_PATH))}) "
        f"{shlex.quote(jq_args['filter'])} {shlex.quote(str(USERS_PATH))}"
    )
    reconstructed = subprocess.run(
        ["bash", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert reconstructed.stdout == OUTPUT_PATH.read_text(encoding="utf-8")
