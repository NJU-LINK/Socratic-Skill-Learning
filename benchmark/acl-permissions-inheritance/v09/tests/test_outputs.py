import grp
import stat
import subprocess
from pathlib import Path


SHARED_DIR = Path("/srv/shared")


def run(command: str, *, user: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    if user is None:
        argv = ["bash", "-lc", command]
    else:
        argv = ["runuser", "-u", user, "--", "bash", "-lc", command]
    return subprocess.run(argv, text=True, capture_output=True, check=check)


def get_acl_lines(path: Path) -> list[str]:
    return run(f"getfacl -cp {path}").stdout.splitlines()


def normalize_acl_lines(lines: list[str]) -> set[str]:
    return {
        normalized
        for line in lines
        for normalized in [line.split("\t", 1)[0].rstrip()]
        if normalized
    }


def assert_exact_acl(path: Path, expected_lines: set[str]) -> None:
    acl = get_acl_lines(path)
    acl_lines = normalize_acl_lines(acl)
    assert acl_lines == expected_lines, (
        f"unexpected ACL for {path}:\n"
        f"missing: {sorted(expected_lines - acl_lines)}\n"
        f"extra: {sorted(acl_lines - expected_lines)}\n"
        f"actual ACL: {acl}"
    )


def assert_file_acl_policy(path: Path) -> None:
    acl = get_acl_lines(path)
    acl_lines = normalize_acl_lines(acl)
    expected_entries = {
        "user::rw-",
        "user:alice:rwx",
        "user:bob:rwx",
        "other::---",
    }
    allowed_group_entries = {"group::rw-", "group::rwx"}
    allowed_dave_entries = {"user:dave:r--", "user:dave:r-x"}

    missing = expected_entries - acl_lines
    assert not missing, f"missing file ACL entries for {path}: {sorted(missing)}\nactual ACL: {acl}"
    assert acl_lines & allowed_group_entries, (
        f"missing valid owning-group entry for {path}; expected one of {sorted(allowed_group_entries)}\n"
        f"actual ACL: {acl}"
    )
    assert acl_lines & allowed_dave_entries, (
        f"missing valid dave entry for {path}; expected one of {sorted(allowed_dave_entries)}\n"
        f"actual ACL: {acl}"
    )

    extras = {
        line
        for line in acl_lines
        if not line.startswith("mask::")
        and line not in expected_entries
        and line not in allowed_group_entries
        and line not in allowed_dave_entries
    }
    assert not extras, f"unexpected extra file ACL entries for {path}: {sorted(extras)}\nactual ACL: {acl}"

    mask_lines = [line for line in acl_lines if line.startswith("mask::")]
    assert len(mask_lines) == 1, f"expected exactly one mask entry for {path}, got: {acl}"
    assert mask_lines[0] in {"mask::rw-", "mask::rwx"}, (
        f"unexpected mask entry for {path}: {mask_lines[0]}\nactual ACL: {acl}"
    )


def test_shared_directory_metadata_and_acl_entries() -> None:
    assert SHARED_DIR.is_dir(), "/srv/shared must exist"

    st = SHARED_DIR.stat()
    assert stat.S_IMODE(st.st_mode) == 0o2770
    assert grp.getgrgid(st.st_gid).gr_name == "research"

    assert_exact_acl(
        SHARED_DIR,
        {
        "user::rwx",
        "user:alice:rwx",
        "user:bob:rwx",
        "user:dave:r-x",
        "group::rwx",
        "mask::rwx",
        "other::---",
        "default:user::rwx",
        "default:user:alice:rwx",
        "default:user:bob:rwx",
        "default:user:dave:r-x",
        "default:group::rwx",
        "default:mask::rwx",
        "default:other::---",
        },
    )


def test_inherited_permissions_allow_collaboration_and_read_only_auditing() -> None:
    project_dir = SHARED_DIR / "project-alpha"
    notes_file = project_dir / "notes.txt"
    nested_dir = project_dir / "results"
    nested_file = nested_dir / "summary.txt"

    run(f"rm -rf {project_dir}")
    run(
        "umask 0002 && "
        f"mkdir {project_dir} && "
        f"printf 'alpha\n' > {notes_file}",
        user="alice",
    )
    run(
        "umask 0002 && "
        f"printf 'beta\n' >> {notes_file} && "
        f"mkdir {nested_dir} && "
        f"printf 'gamma\n' > {nested_file}",
        user="bob",
    )

    assert_exact_acl(
        project_dir,
        {
            "user::rwx",
            "user:alice:rwx",
            "user:bob:rwx",
            "user:dave:r-x",
            "group::rwx",
            "mask::rwx",
            "other::---",
            "default:user::rwx",
            "default:user:alice:rwx",
            "default:user:bob:rwx",
            "default:user:dave:r-x",
            "default:group::rwx",
            "default:mask::rwx",
            "default:other::---",
        },
    )
    assert_file_acl_policy(notes_file)
    assert_exact_acl(
        nested_dir,
        {
            "user::rwx",
            "user:alice:rwx",
            "user:bob:rwx",
            "user:dave:r-x",
            "group::rwx",
            "mask::rwx",
            "other::---",
            "default:user::rwx",
            "default:user:alice:rwx",
            "default:user:bob:rwx",
            "default:user:dave:r-x",
            "default:group::rwx",
            "default:mask::rwx",
            "default:other::---",
        },
    )
    assert_file_acl_policy(nested_file)

    assert run(f"test -r {project_dir} && test -x {project_dir}", user="dave").returncode == 0
    assert run(f"test ! -w {project_dir}", user="dave").returncode == 0
    assert run(f"test -r {notes_file}", user="dave").returncode == 0
    assert run(f"test ! -w {notes_file}", user="dave").returncode == 0
    assert run(f"test ! -x {notes_file}", user="dave").returncode == 0
    assert run(f"cat {notes_file}", user="dave").stdout == "alpha\nbeta\n"
    assert run(f"printf 'delta\n' >> {nested_file}", user="alice").returncode == 0
    assert run(f"printf 'epsilon\n' >> {nested_file}", user="bob").returncode == 0
    assert run(f"test -r {nested_dir} && test -x {nested_dir}", user="dave").returncode == 0
    assert run(f"cat {nested_file}", user="dave").stdout == "gamma\ndelta\nepsilon\n"

    assert run(f"printf 'nope\n' >> {notes_file}", user="dave", check=False).returncode != 0
    assert run(f"touch {project_dir}/dave.txt", user="dave", check=False).returncode != 0
    assert run(f"chmod u+w {notes_file}", user="dave", check=False).returncode != 0


def test_unrelated_user_is_denied_access() -> None:
    run("id -u mallory >/dev/null 2>&1 || useradd -m -s /bin/bash mallory")
    assert run("test ! -r /srv/shared", user="mallory").returncode == 0
    assert run("test ! -w /srv/shared", user="mallory").returncode == 0
    assert run("test ! -x /srv/shared", user="mallory").returncode == 0
    denied = run("ls /srv/shared", user="mallory", check=False)
    assert denied.returncode != 0
