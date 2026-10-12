import os
import subprocess
import re
from pathlib import Path

REPO_DIR = "/app/repo"
SECRET_FILE = "/app/secret.txt"
EXPECTED_SECRET = "secret[stash_leak_cleanup]"


def test_secret_file_exists():
    assert os.path.isfile(SECRET_FILE), f"{SECRET_FILE} not found"


def test_secret_content():
    with open(SECRET_FILE) as f:
        content = f.read().strip()
    assert re.search(r'secret\[[^\]]*\]', content), f"No valid secret pattern in {content}"
    assert content == EXPECTED_SECRET, f"Expected '{EXPECTED_SECRET}', got '{content}'"


def test_no_stash_entries():
    result = subprocess.run(
        ["git", "stash", "list"],
        cwd=REPO_DIR,
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", f"Stash entries still present:\n{result.stdout}"


def test_no_dangling_secret():
    result = subprocess.run(
        ["git", "fsck", "--lost-found"],
        cwd=REPO_DIR,
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "dangling" in line:
            parts = line.split()
            obj_hash = parts[-1]
            obj_result = subprocess.run(
                ["git", "-C", REPO_DIR, "cat-file", "-p", obj_hash],
                capture_output=True, text=True,
            )
            if obj_result.returncode == 0:
                assert "secret[" not in obj_result.stdout, (
                    f"Found 'secret[' in dangling object {obj_hash}"
                )


def test_reflog_cleaned():
    result = subprocess.run(
        ["git", "reflog", "show", "--all"],
        cwd=REPO_DIR,
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        assert "stash" not in line, f"Stash reflog entry still present: {line}"


def test_main_branch_preserved():
    result = subprocess.run(
        ["git", "log", "--oneline", "--all"],
        cwd=REPO_DIR,
        capture_output=True, text=True,
    )
    commits = [l for l in result.stdout.strip().split("\n") if l]
    assert len(commits) == 3, f"Expected 3 commits, got {len(commits)}:\n{result.stdout}"
    messages = result.stdout.strip()
    assert "chore: init" in messages, "Expected 'chore: init' commit"
    assert "feat: add configuration docs" in messages, "Expected 'feat: add configuration docs' commit"
    assert "docs: update readme" in messages, "Expected 'docs: update readme' commit"


def test_lost_found_cleaned():
    lost_found = Path(REPO_DIR) / ".git" / "lost-found"
    assert not lost_found.exists(), ".git/lost-found/ should be removed after cleanup"
