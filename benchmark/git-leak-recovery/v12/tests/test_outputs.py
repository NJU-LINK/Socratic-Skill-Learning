import subprocess
from pathlib import Path


SECRET_VALUE = "secret[replaced_but_not_gone]"

EXPECTED_COMMITS = [
    "chore: init project",
    "feat: add feature specification",
    "chore: add app configuration",
    "feat: add helper library",
    "docs: update feature status",
    "chore: add logging config",
    "test: add helper tests",
]


def test_flag_file_exists_and_correct():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == SECRET_VALUE, f"Flag value is incorrect: {text}"


def test_no_secrets_in_commits():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "log", "--all", "-p", "-S", "secret["],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    assert not result.stdout.strip(), (
        f"Found 'secret[' in commit contents: {result.stdout}"
    )


def test_good_commits_preserved():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "log", "--oneline", "--all"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    commit_messages = result.stdout.strip()
    for msg in EXPECTED_COMMITS:
        assert msg in commit_messages, (
            f"Missing commit: {msg}\nFull log: {commit_messages}"
        )


def test_no_replace_refs():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "replace", "-l"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git replace command failed: {result.stderr}"
    assert not result.stdout.strip(), (
        f"Replace refs still exist: {result.stdout}"
    )


def test_no_secrets_in_unreachable_objects():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "fsck"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git fsck command failed: {result.stderr}"

    for line in result.stdout.splitlines():
        if "dangling" in line:
            parts = line.split()
            obj_type = parts[1]
            obj_hash = parts[-1]
            obj_result = subprocess.run(
                ["git", "-C", "/app/repo", "cat-file", "-p", obj_hash],
                capture_output=True, text=True,
            )
            if obj_result.returncode == 0:
                assert SECRET_VALUE not in obj_result.stdout, (
                    f"Found secret in dangling {obj_type} {obj_hash}"
                )


def test_lost_found_cleaned():
    lost_found = Path("/app/repo/.git/lost-found")
    assert not lost_found.exists(), ".git/lost-found/ should be removed after cleanup"
