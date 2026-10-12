import grp
import stat
import subprocess
import uuid
from pathlib import Path


SHARED = Path("/srv/shared")
REVIEW = SHARED / "review"


def run(command: str, check: bool = True, user: str | None = None) -> subprocess.CompletedProcess[str]:
    if user is None:
        argv = ["bash", "-lc", command]
    else:
        argv = ["runuser", "-u", user, "--", "bash", "-lc", command]
    return subprocess.run(argv, text=True, capture_output=True, check=check)


def unique_path(parent: Path, prefix: str) -> Path:
    return parent / f"{prefix}-{uuid.uuid4().hex}"


def test_shared_workspace_basics():
    st = SHARED.stat()

    assert SHARED.is_dir()
    assert grp.getgrgid(st.st_gid).gr_name == "research"
    assert st.st_mode & stat.S_ISGID


def test_shared_workspace_allows_alice_and_bob_but_not_mallory():
    alice_file = unique_path(SHARED, "alice-root-file")

    run(f"> {alice_file}", user="alice")
    run(f"echo alice > {alice_file}", user="alice")
    run(f"echo bob >> {alice_file}", user="bob")
    result = run(f"cat {alice_file}", user="bob")
    denied = run("ls /srv/shared", user="mallory", check=False)

    assert "alice" in result.stdout
    assert "bob" in result.stdout
    assert denied.returncode != 0


def test_root_descendants_remain_broadly_shared_and_keep_group():
    root_dir = unique_path(SHARED, "root-dir")
    nested_file = root_dir / "note.txt"

    run(f"mkdir {root_dir}", user="alice")
    run(f"echo hello > {nested_file}", user="alice")
    run(f"echo world >> {nested_file}", user="bob")

    root_dir_stat = root_dir.stat()
    nested_file_stat = nested_file.stat()
    contents = run(f"cat {nested_file}", user="bob")

    assert grp.getgrgid(root_dir_stat.st_gid).gr_name == "research"
    assert grp.getgrgid(nested_file_stat.st_gid).gr_name == "research"
    assert root_dir_stat.st_mode & stat.S_ISGID
    assert "hello" in contents.stdout
    assert "world" in contents.stdout


def test_review_area_denies_bob_and_mallory_but_allows_alice():
    review_file = unique_path(REVIEW, "review-file")

    run(f"echo secret > {review_file}", user="alice")
    bob_denied = run(f"ls {REVIEW}", user="bob", check=False)
    bob_file_denied = run(f"cat {review_file}", user="bob", check=False)
    mallory_denied = run(f"ls {REVIEW}", user="mallory", check=False)

    assert bob_denied.returncode != 0
    assert bob_file_denied.returncode != 0
    assert mallory_denied.returncode != 0


def test_review_descendants_keep_restrictive_policy_and_group():
    review_dir = unique_path(REVIEW, "review-dir")
    nested_file = review_dir / "private.txt"

    run(f"mkdir {review_dir}", user="alice")
    run(f"echo secret > {nested_file}", user="alice")

    review_dir_stat = review_dir.stat()
    nested_file_stat = nested_file.stat()
    alice_read = run(f"cat {nested_file}", user="alice")
    bob_dir_denied = run(f"ls {review_dir}", user="bob", check=False)
    bob_file_denied = run(f"cat {nested_file}", user="bob", check=False)

    assert grp.getgrgid(review_dir_stat.st_gid).gr_name == "research"
    assert grp.getgrgid(nested_file_stat.st_gid).gr_name == "research"
    assert review_dir_stat.st_mode & stat.S_ISGID
    assert alice_read.stdout.strip() == "secret"
    assert bob_dir_denied.returncode != 0
    assert bob_file_denied.returncode != 0


def test_review_acl_contains_explicit_bob_deny_on_directory_and_defaults():
    acl = run("getfacl -cp /srv/shared/review").stdout.splitlines()

    assert "user:bob:---" in acl
    assert "default:user:bob:---" in acl
    assert "group::rwx" in acl
    assert "default:group::rwx" in acl
