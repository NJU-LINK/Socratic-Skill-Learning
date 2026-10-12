import subprocess
from pathlib import Path

import pytest


def _submodule_git_dir():
    result = subprocess.run(
        ["git", "-C", "/app/repo/lib/secrets", "rev-parse", "--git-dir"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def test_flag_file_exists_and_correct():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == "secret[submodule_leak_found]", f"Flag value is incorrect: {text}"


def test_no_secrets_in_main_repo_commits():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "log", "--all", "-p", "-S", "secret["],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    assert not result.stdout.strip(), (
        f"Found 'secret[' in main repo commit contents: {result.stdout}"
    )


def test_no_secrets_in_submodule_commits():
    submodule_path = "/app/repo/lib/secrets"
    assert Path(submodule_path).exists(), "Submodule directory does not exist"
    result = subprocess.run(
        ["git", "-C", submodule_path, "log", "--all", "-p", "-S", "secret["],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    assert not result.stdout.strip(), (
        f"Found 'secret[' in submodule commit contents: {result.stdout}"
    )


def test_good_commits_preserved_in_main():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "log", "--oneline", "--all"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    commit_messages = result.stdout.strip()
    assert "chore: init" in commit_messages, (
        f"'chore: init' commit not found: {commit_messages}"
    )
    assert "chore: add config" in commit_messages, (
        f"'chore: add config' commit not found: {commit_messages}"
    )
    assert "chore: add secrets submodule" in commit_messages, (
        f"'chore: add secrets submodule' commit not found: {commit_messages}"
    )


def test_good_commits_preserved_in_submodule():
    submodule_path = "/app/repo/lib/secrets"
    assert Path(submodule_path).exists(), "Submodule directory does not exist"
    result = subprocess.run(
        ["git", "-C", submodule_path, "log", "--oneline", "--all"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git log command failed: {result.stderr}"
    commit_messages = result.stdout.strip()
    assert "chore: init lib" in commit_messages, (
        f"'chore: init lib' commit not found: {commit_messages}"
    )


def test_no_secrets_in_unreachable_objects_main():
    result = subprocess.run(
        ["git", "-C", "/app/repo", "fsck", "--lost-found"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git fsck on main repo failed: {result.stderr}"
    for line in result.stdout.splitlines():
        if "dangling" in line:
            parts = line.split()
            obj_hash = parts[-1]
            obj_result = subprocess.run(
                ["git", "-C", "/app/repo", "cat-file", "-p", obj_hash],
                capture_output=True, text=True,
            )
            if obj_result.returncode == 0:
                assert "secret[" not in obj_result.stdout, (
                    f"Found 'secret[' in main repo dangling object {obj_hash}"
                )


def test_no_secrets_in_unreachable_objects_submodule():
    submodule_path = "/app/repo/lib/secrets"
    assert Path(submodule_path).exists(), "Submodule directory does not exist"
    result = subprocess.run(
        ["git", "-C", submodule_path, "fsck", "--lost-found"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Git fsck on submodule failed: {result.stderr}"
    for line in result.stdout.splitlines():
        if "dangling" in line:
            parts = line.split()
            obj_hash = parts[-1]
            obj_result = subprocess.run(
                ["git", "-C", submodule_path, "cat-file", "-p", obj_hash],
                capture_output=True, text=True,
            )
            if obj_result.returncode == 0:
                assert "secret[" not in obj_result.stdout, (
                    f"Found 'secret[' in submodule dangling object {obj_hash}"
                )


def test_lost_found_cleaned():
    main_lost_found = Path("/app/repo/.git/lost-found")
    assert not main_lost_found.exists(), ".git/lost-found/ in main repo should be removed"

    sub_git_dir = _submodule_git_dir()
    if sub_git_dir:
        sub_lost_found = Path(sub_git_dir) / "lost-found"
        assert not sub_lost_found.exists(), (
            f"{sub_lost_found} in submodule should be removed after cleanup"
        )
