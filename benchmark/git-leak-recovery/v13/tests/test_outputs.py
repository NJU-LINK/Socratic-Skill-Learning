import subprocess
from pathlib import Path

REPO = "/app/repo"
SECRET_FILE = "/app/secret.txt"
EXPECTED = "secret[cherry_pick_gone_wrong]"


def test_secret_recovered():
    p = Path(SECRET_FILE)
    assert p.exists(), f"{SECRET_FILE} not found"
    assert p.read_text().strip() == EXPECTED, f"Unexpected secret value"


def test_no_secret_in_reachable_commits():
    result = subprocess.run(
        ["git", "-C", REPO, "log", "--all", "-p", "-S", "secret["],
        capture_output=True, text=True,
    )
    assert not result.stdout.strip(), "Secret found in reachable commits"


def test_no_secret_in_tracked_files():
    result = subprocess.run(
        ["git", "-C", REPO, "grep", "-c", "secret\["],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "Secret found in tracked files"


def test_fsck_clean():
    result = subprocess.run(
        ["git", "-C", REPO, "fsck"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"fsck errors: {result.stderr}"


def test_original_commits_preserved():
    result = subprocess.run(
        ["git", "-C", REPO, "log", "--oneline", "--all"],
        capture_output=True, text=True,
    )
    messages = result.stdout
    expected = [
        "chore: init",
        "feat: add main entry",
        "chore: add env config",
        "docs: set version",
        "feat: add utils module",
        "chore: disable debug",
        "chore: add task tracking",
        "docs: bump version",
        "feat: feature a",
    ]
    for msg in expected:
        assert msg in messages, f"Missing commit: {msg}"
