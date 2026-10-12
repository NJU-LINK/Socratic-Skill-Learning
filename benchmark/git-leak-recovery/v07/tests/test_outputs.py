import subprocess
from pathlib import Path


def test_flag_file_exists_and_correct():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == "secret[merge_abort_leak_99]", f"Flag value is incorrect: {text}"


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
    assert "Add main changes" in commit_messages, (
        f"'Add main changes' not found: {commit_messages}"
    )


def test_orig_head_removed():
    resolved = subprocess.run(
        ["git", "-C", "/app/repo", "rev-parse", "--verify", "--quiet", "ORIG_HEAD"],
        capture_output=True,
    )
    assert resolved.returncode != 0, "ORIG_HEAD pseudo-ref should have been deleted"
    assert not Path("/app/repo/.git/ORIG_HEAD").exists(), (
        ".git/ORIG_HEAD file should have been removed"
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
