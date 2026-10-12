import subprocess
from pathlib import Path


def test_flag_file_exists_and_correct():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == "secret[accidental_commit_in_history]", f"Secret value is incorrect: {text}"


def test_no_secrets_in_reachable_commits():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "log", "--all", "-p", "-S", "secret["],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    assert not result.stdout.strip(), (
        f"Found 'secret[' in reachable commit contents: {result.stdout}"
    )


def test_no_secrets_in_dangling_objects():
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


def test_tag_v1_0_removed():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "tag", "-l", "v1.0"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "v1.0" not in result.stdout.strip(), (
        "Tag v1.0 should be removed as it referenced a secret-containing commit"
    )


def test_no_original_backup_refs():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "for-each-ref", "--format=%(refname)", "refs/original/"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not result.stdout.strip(), (
        "Backup refs under refs/original/ should be removed: " + result.stdout.strip()
    )


def test_orig_head_removed():
    orig_head = Path("/app/repo/.git/ORIG_HEAD")
    assert not orig_head.exists(), "ORIG_HEAD should be removed"


def test_develop_branch_preserved():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "log", "--oneline", "develop"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    commit_messages = result.stdout.strip()
    assert "Add feature flags" in commit_messages, (
        f"'Add feature flags' commit missing from develop: {commit_messages}"
    )
    assert "Add dev configuration" in commit_messages, (
        f"'Add dev configuration' commit missing from develop: {commit_messages}"
    )


def test_master_commits_preserved():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "log", "--oneline", "master"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    commit_messages = result.stdout.strip()
    preserved = [
        "Initial project setup",
        "Add main application entry point",
        "Add configuration module",
        "Add database module",
        "Update project documentation",
        "Remove sensitive data from working tree",
        "Add data processor",
        "Add test files",
        "Finalize project setup",
    ]
    for msg in preserved:
        assert msg in commit_messages, (
            f"Commit '{msg}' missing from master after cleanup:\n{commit_messages}"
        )


def test_lost_found_cleaned():
    lost_found = Path("/app/repo/.git/lost-found")
    assert not lost_found.exists(), ".git/lost-found/ should be removed after cleanup"
