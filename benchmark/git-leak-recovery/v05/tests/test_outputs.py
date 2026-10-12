import subprocess
from pathlib import Path


def test_flag_file_exists_and_correct():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == "secret[amended_and_forgotten]", f"Flag value is incorrect: {text}"


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
    assert "Initial commit" in commit_messages, (
        f"'Initial commit' not found: {commit_messages}"
    )
    assert "Add feature module" in commit_messages, (
        f"'Add feature module' not found: {commit_messages}"
    )
    assert "Add config" in commit_messages, (
        f"'Add config' not found: {commit_messages}"
    )
    assert "Add data and scratch notes" in commit_messages, (
        f"'Add data and scratch notes' not found: {commit_messages}"
    )
    assert "Add notes" in commit_messages, (
        f"'Add notes' not found: {commit_messages}"
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


def test_innocent_files_untouched():
    readme = Path("/app/repo/README.md")
    assert readme.exists(), "README.md was removed"
    assert readme.read_text().strip() == "# Project", "README.md content changed"

    feature = Path("/app/repo/feature.py")
    assert feature.exists(), "feature.py was removed"
    assert feature.read_text().strip() == "def feature(): pass", "feature.py content changed"

    config = Path("/app/repo/config.json")
    assert config.exists(), "config.json was removed"
    assert config.read_text().strip() == '{"version": 1}', "config.json content changed"

    data = Path("/app/repo/data.csv")
    assert data.exists(), "data.csv was removed"

    notes = Path("/app/repo/notes.md")
    assert notes.exists(), "notes.md was removed"
    assert notes.read_text().strip() == "// TODO items", "notes.md content changed"
