import os
import subprocess
import re

REPO_DIR = "/app/repo"
SECRET_FILE = "/app/secret.txt"
EXPECTED_SECRET = "secret[split_git_recovery]"


def test_secret_file_exists():
    assert os.path.isfile(SECRET_FILE), f"{SECRET_FILE} not found"


def test_secret_content():
    with open(SECRET_FILE) as f:
        content = f.read().strip()
    assert re.search(r'secret\[[^\]]*\]', content), f"No valid secret pattern found in {content}"
    assert content == EXPECTED_SECRET, f"Expected '{EXPECTED_SECRET}', got '{content}'"


def test_no_dangling_objects():
    result = subprocess.run(
        ["git", "fsck"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    assert "dangling" not in result.stdout, f"Dangling objects still present:\n{result.stdout}"
    assert "dangling" not in result.stderr, f"Dangling objects still present:\n{result.stderr}"


def test_repo_structure_preserved():
    result = subprocess.run(
        ["git", "log", "--oneline", "--all"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    commits = result.stdout.strip().split("\n")
    assert len(commits) == 2, f"Expected 2 commits, got {len(commits)}"


def test_readme_untouched():
    readme_path = os.path.join(REPO_DIR, "README.md")
    with open(readme_path) as f:
        content = f.read().strip()
    assert "demo project" in content
    assert "some changes" in content
