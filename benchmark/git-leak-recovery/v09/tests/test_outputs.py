import subprocess
from pathlib import Path


def test_flag_file_exists_and_correct():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == "secret[orphaned_branch_leak]", f"Flag value is incorrect: {text}"


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
    for msg in [
        "chore: initial commit",
        "chore: add gitignore",
        "feat: add dependencies",
        "feat: add main module",
        "feat: add utilities",
        "chore: add test init",
        "feat: add main tests",
        "feat: add util tests",
    ]:
        assert msg in commit_messages, (
            f"Expected commit '{msg}' not found in: {commit_messages}"
        )
    assert "feat: add scratch notes" not in commit_messages, (
        f"Dangling commit 'feat: add scratch notes' should not appear: {commit_messages}"
    )


def test_no_secrets_in_unreachable_objects():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "fsck", "--lost-found"],
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
                assert "secret[" not in obj_result.stdout, (
                    f"Found 'secret[' in dangling {obj_type} {obj_hash}"
                )


def test_lost_found_cleaned():
    lost_found = Path("/app/repo/.git/lost-found")
    assert not lost_found.exists(), ".git/lost-found/ should be removed after cleanup"
