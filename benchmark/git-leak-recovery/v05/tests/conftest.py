from pathlib import Path
import subprocess

import pytest


SECRET_PREFIX = b"secret["
REPOSITORY = Path("/app/repo")


def _git_repositories():
    repositories = [REPOSITORY]
    repositories.extend(
        marker.parent
        for marker in REPOSITORY.rglob(".git")
        if marker.parent != REPOSITORY
    )
    return sorted(set(repositories), key=lambda path: str(path))


def _secret_objects(repository):
    inventory = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objecttype)",
        ],
        capture_output=True,
        check=False,
    )
    assert inventory.returncode == 0, (
        f"Unable to enumerate all Git objects in {repository}: "
        f"{inventory.stderr.decode(errors='replace')}"
    )

    leaks = []
    for line in inventory.stdout.decode().splitlines():
        object_id, object_type = line.split(maxsplit=1)
        content = subprocess.run(
            ["git", "-C", str(repository), "cat-file", "-p", object_id],
            capture_output=True,
            check=False,
        )
        assert content.returncode == 0, (
            f"Unable to inspect {object_type} {object_id} in {repository}: "
            f"{content.stderr.decode(errors='replace')}"
        )
        if SECRET_PREFIX in content.stdout:
            leaks.append(f"{object_type} {object_id}")
    return leaks


def _test_no_secret_in_any_git_object():
    repositories = _git_repositories()
    assert repositories, "No Git repository found under /app/repo"
    for repository in repositories:
        leaks = _secret_objects(repository)
        assert not leaks, (
            f"Secret material remains in Git objects under {repository}: "
            + ", ".join(leaks)
        )


def pytest_collection_modifyitems(items):
    if not items:
        return
    items.append(
        pytest.Function.from_parent(
            items[0].parent,
            name="test_no_secret_in_any_git_object",
            callobj=_test_no_secret_in_any_git_object,
        )
    )
