import pwd
import grp
import stat
import subprocess
from pathlib import Path


PROJECT_ROOT = Path("/srv/shared/projectA")
OUTSIDER = "charlie"


def run(command: str, user: str | None = None) -> subprocess.CompletedProcess[str]:
    if user is None:
        return subprocess.run(command, shell=True, text=True, capture_output=True, check=True)
    return subprocess.run(
        ["runuser", "-u", user, "--", "bash", "-lc", command],
        text=True,
        capture_output=True,
        check=True,
    )


def run_expect_failure(command: str, user: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["runuser", "-u", user, "--", "bash", "-lc", command],
        text=True,
        capture_output=True,
        check=False,
    )


def acl_entries(path: Path) -> set[str]:
    output = run(f"getfacl -cp {path}").stdout
    return {line.strip() for line in output.splitlines() if line.strip() and not line.startswith("#")}


def create_outsider() -> None:
    try:
        pwd.getpwnam(OUTSIDER)
    except KeyError:
        subprocess.run(["useradd", "-m", "-s", "/bin/bash", OUTSIDER], check=True)


def test_project_root_has_expected_group_mode_and_acls():
    st = PROJECT_ROOT.stat()

    assert grp.getgrgid(st.st_gid).gr_name == "research"
    assert stat.S_ISDIR(st.st_mode)
    assert stat.S_IMODE(st.st_mode) == 0o2770

    entries = acl_entries(PROJECT_ROOT)
    assert {"user::rwx", "group::rwx", "mask::rwx", "other::---"}.issubset(entries)
    assert {
        "default:user::rwx",
        "default:group::rwx",
        "default:mask::rwx",
        "default:other::---",
    }.issubset(entries)


def test_nested_tree_inherits_group_and_acl_across_alternating_creators():
    alice_level = PROJECT_ROOT / "reports"
    bob_level = alice_level / "raw"
    alice_file = bob_level / "notes.sh"
    bob_file = bob_level / "metrics.txt"

    run(f"mkdir {alice_level}", user="alice")
    run(f"mkdir {bob_level}", user="bob")
    run(f"printf '#!/bin/bash\necho alice\n' > {alice_file} && chmod 770 {alice_file}", user="alice")
    run(f"printf 'bob data\n' > {bob_file}", user="bob")

    for path in (alice_level, bob_level, alice_file, bob_file):
        assert grp.getgrgid(path.stat().st_gid).gr_name == "research"

    for directory in (alice_level, bob_level):
        entries = acl_entries(directory)
        assert {"group::rwx", "mask::rwx", "other::---"}.issubset(entries)
        assert {
            "default:user::rwx",
            "default:group::rwx",
            "default:mask::rwx",
            "default:other::---",
        }.issubset(entries)

    notes_entries = acl_entries(alice_file)
    assert {"group::rwx", "mask::rwx", "other::---"}.issubset(notes_entries)

    metrics_entries = acl_entries(bob_file)
    assert "other::---" in metrics_entries

    assert run(f"cd {bob_level} && ./notes.sh", user="bob").stdout.strip() == "alice"
    assert run(f"echo 'shared edit' >> {alice_file} && grep -q 'shared edit' {alice_file}", user="bob").returncode == 0
    assert run(f"grep -q 'bob data' {bob_file}", user="alice").returncode == 0
    assert run(f"echo 'alice edit' >> {bob_file} && grep -q 'alice edit' {bob_file}", user="alice").returncode == 0


def test_outsider_cannot_access_project_tree():
    create_outsider()

    for command in (
        f"ls {PROJECT_ROOT}",
        f"test -r {PROJECT_ROOT}/reports/raw/metrics.txt",
        f"test -x {PROJECT_ROOT}/reports/raw/notes.sh",
    ):
        result = run_expect_failure(command, user=OUTSIDER)
        assert result.returncode != 0
