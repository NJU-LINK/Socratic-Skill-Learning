import json
import shlex
import subprocess
from pathlib import Path

import yaml


APP_DIR = Path("/app")
USERS_PATH = APP_DIR / "users.json"
AUDIT_PATH = APP_DIR / "profile_completeness_audit.json"
CMD_PATH = APP_DIR / "cmd.sh"
JQ_ARGS_PATH = APP_DIR / "jq_args.yaml"


def _trim_or_null(value):
    if value is None:
        return None
    trimmed = str(value).strip()
    return trimmed or None


def _expected_audit():
    users = json.loads(USERS_PATH.read_text(encoding="utf-8"))
    required_fields = ["display_name", "team", "phone", "last_login"]
    rows = []

    for user in users:
        if user.get("status") != "active":
            continue

        missing_fields = [
            field for field in required_fields if _trim_or_null(user.get(field)) is None
        ]
        if not missing_fields:
            continue

        rows.append(
            {
                "user_id": user["id"],
                "username": user["username"],
                "missing_fields": missing_fields,
                "missing_field_count": len(missing_fields),
                "completeness_score": round((4 - len(missing_fields)) / 4 * 100),
                "profile": {
                    "email": str(user["email"]).strip(),
                    "display_name": _trim_or_null(user.get("display_name")),
                    "team": _trim_or_null(user.get("team")),
                    "phone": _trim_or_null(user.get("phone")),
                    "last_login": (
                        None
                        if _trim_or_null(user.get("last_login")) is None
                        else _trim_or_null(user.get("last_login"))[:10]
                    ),
                },
            }
        )

    rows.sort(key=lambda row: (-row["missing_field_count"], row["username"]))
    return rows


def test_audit_matches_expected_output():
    actual = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert actual == _expected_audit()


def test_command_file_runs_and_reproduces_output():
    command = CMD_PATH.read_text(encoding="utf-8").strip()
    assert command.startswith("jq ")
    rerun = subprocess.run(
        command,
        shell=True,
        check=True,
        text=True,
        capture_output=True,
    )
    actual = AUDIT_PATH.read_text(encoding="utf-8")
    assert rerun.stdout == actual


def test_jq_args_yaml_reconstructs_command_and_output():
    data = yaml.safe_load(JQ_ARGS_PATH.read_text(encoding="utf-8"))
    assert set(data) == {"filter", "args"}
    assert isinstance(data["filter"], str)
    assert isinstance(data["args"], list)
    assert all(isinstance(arg, str) for arg in data["args"])
    assert all("/app/users.json" not in arg for arg in data["args"])
    assert all("/app/profile_completeness_audit.json" not in arg for arg in data["args"])
    assert all("jq" != arg for arg in data["args"])

    expanded_args = []
    for arg in data["args"]:
        expanded_args.extend(shlex.split(arg))

    cmd = ["jq", *expanded_args, data["filter"], "/app/users.json"]
    rerun = subprocess.run(cmd, check=True, text=True, capture_output=True)
    actual = AUDIT_PATH.read_text(encoding="utf-8")
    assert rerun.stdout == actual


def test_output_is_pretty_printed_with_indent_two():
    actual_text = AUDIT_PATH.read_text(encoding="utf-8")
    parsed = json.loads(actual_text)
    assert actual_text == json.dumps(parsed, indent=2) + "\n"
