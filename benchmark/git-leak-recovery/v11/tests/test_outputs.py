import subprocess
from pathlib import Path


REPO = "/app/repo"


def test_secret_recovered():
    flag_path = Path("/app/secret.txt")
    assert flag_path.exists(), "secret.txt was not created"
    text = flag_path.read_text().strip()
    assert text == "secret[orphan_tag_secret]", f"Wrong secret value: {text}"


def test_tag_deleted():
    result = subprocess.run(
        ["git", "-C", REPO, "tag", "-l"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "v1.0rc" not in result.stdout.strip(), "Tag v1.0rc should be deleted"


def test_backup_refs_removed():
    orig = Path(REPO) / ".git" / "ORIG_HEAD"
    fetch = Path(REPO) / ".git" / "FETCH_HEAD"
    assert not orig.exists(), "ORIG_HEAD should be removed"
    assert not fetch.exists(), "FETCH_HEAD should be removed"


def test_no_secret_in_any_object():
    result = subprocess.run(
        ["git", "-C", REPO, "log", "--all", "-p", "-S", "secret["],
        capture_output=True, text=True,
    )
    assert not result.stdout.strip(), "Secret still found in git history"


def test_no_secret_in_unreachable_objects():
    result = subprocess.run(
        ["git", "-C", REPO, "fsck", "--no-dangling"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"git fsck found errors: {result.stdout}"

    result = subprocess.run(
        ["git", "-C", REPO, "fsck", "--lost-found"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "dangling" in line:
            parts = line.split()
            obj_hash = parts[-1]
            obj_result = subprocess.run(
                ["git", "-C", REPO, "cat-file", "-p", obj_hash],
                capture_output=True, text=True,
            )
            if obj_result.returncode == 0:
                assert "secret[" not in obj_result.stdout, (
                    f"Secret found in dangling object {obj_hash}"
                )


def test_good_commits_preserved():
    result = subprocess.run(
        ["git", "-C", REPO, "log", "--oneline", "--all"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    messages = result.stdout.strip()
    assert "chore: init project" in messages, "main branch commits missing"
    assert "feat: add feature_x" in messages, "feature-x branch commits missing"
