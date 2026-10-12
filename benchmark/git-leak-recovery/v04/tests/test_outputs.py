import subprocess
from pathlib import Path


def test_flag_file_exists_and_correct():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == "secret[stashed_away]", f"Flag value is incorrect: {text}"


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
    assert "chore: initial commit 8a1f3c9b" in commit_messages, (
        f"'initial commit' not found: {commit_messages}"
    )
    assert "docs: update readme" in commit_messages, (
        f"'update readme' commit not found: {commit_messages}"
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


def test_reachable_files_untouched():
    readme = Path("/app/repo/README.md")
    assert readme.exists(), "README.md was removed"
    content = readme.read_text()
    assert "Welcome to the team!" in content, "README.md content changed"


def test_feature_branch_exists():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "branch", "--list"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git branch command failed: {result.stderr}"
    branches = result.stdout.strip()
    assert "feature" in branches, (
        f"feature branch missing. Existing branches: {branches}"
    )


def test_lost_found_cleaned():
    lost_found = Path("/app/repo/.git/lost-found")
    assert not lost_found.exists(), ".git/lost-found/ should be removed after cleanup"
