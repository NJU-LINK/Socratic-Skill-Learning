import grp
import os
import subprocess


def run(cmd, **kwargs):
    return subprocess.run(cmd, text=True, capture_output=True, check=True, **kwargs)


def run_as(user, command):
    return subprocess.run(
        ["su", "-", user, "-c", command],
        text=True,
        capture_output=True,
    )


def run_as_with_shell(user, command, shell):
    return subprocess.run(
        ["su", "-s", shell, user, "-c", command],
        text=True,
        capture_output=True,
    )


def parse_acl(path):
    lines = run(["getfacl", "-p", path]).stdout.splitlines()
    entries = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        key, perms = parts[0].rsplit(":", 1)
        effective = None
        if len(parts) > 1 and "#effective:" in parts[1]:
            effective = parts[1].split("#effective:", 1)[1].strip()
        entries[key] = {"perms": perms, "effective": effective}
    return entries, lines


def test_shared_directory_metadata_and_acl_text():
    st = os.stat("/srv/shared")
    assert grp.getgrgid(st.st_gid).gr_name == "research"
    assert st.st_mode & 0o2000
    assert oct(st.st_mode & 0o0777) == "0o750"

    entries, _ = parse_acl("/srv/shared")
    assert entries["user:"]["perms"] == "rwx"
    assert entries["user:alice"]["perms"] == "rwx"
    assert entries["user:bob"]["perms"] == "rwx"
    assert entries["group:"]["perms"] == "rwx"
    assert entries["group:research"]["perms"] == "rwx"
    assert entries["mask:"]["perms"] == "r-x"
    assert entries["other:"]["perms"] == "---"
    assert entries["default:user:alice"]["perms"] == "rwx"
    assert entries["default:user:bob"]["perms"] == "rwx"
    assert entries["default:group:research"]["perms"] == "rwx"
    assert entries["default:mask:"]["perms"] == "r-x"
    assert entries["default:other:"]["perms"] == "---"


def test_effective_permissions_are_mask_limited():
    entries, _ = parse_acl("/srv/shared")
    assert entries["user:alice"]["effective"] == "r-x"
    assert entries["user:bob"]["effective"] == "r-x"
    assert entries["group:"]["effective"] == "r-x"
    assert entries["group:research"]["effective"] == "r-x"

    alice_touch = run_as("alice", "touch /srv/shared/alice-root-file")
    assert alice_touch.returncode == 0, alice_touch.stderr

    bob_touch = run_as("bob", "touch /srv/shared/bob-root-file")
    assert bob_touch.returncode != 0


def test_inheritance_and_behavior_for_new_descendants():
    create = run_as(
        "alice",
        "mkdir /srv/shared/project && printf sample >/srv/shared/project/report.txt",
    )
    assert create.returncode == 0, create.stderr

    dir_entries, _ = parse_acl("/srv/shared/project")
    file_entries, _ = parse_acl("/srv/shared/project/report.txt")

    assert dir_entries["user:bob"]["perms"] == "rwx"
    assert dir_entries["user:bob"]["effective"] == "r-x"
    assert dir_entries["group:research"]["perms"] == "rwx"
    assert dir_entries["group:research"]["effective"] == "r-x"
    assert dir_entries["mask:"]["perms"] == "r-x"
    assert dir_entries["default:mask:"]["perms"] == "r-x"

    assert file_entries["user:bob"]["perms"] == "rwx"
    assert file_entries["user:bob"]["effective"] == "r--"
    assert file_entries["group:research"]["perms"] == "rwx"
    assert file_entries["group:research"]["effective"] == "r--"
    assert file_entries["mask:"]["perms"] == "r--"
    assert "default:mask:" not in file_entries

    bob_read = run_as("bob", "cat /srv/shared/project/report.txt")
    assert bob_read.returncode == 0
    assert bob_read.stdout == "sample"

    bob_write = run_as("bob", "printf fail >>/srv/shared/project/report.txt")
    assert bob_write.returncode != 0

    outsider = run_as_with_shell("nobody", "ls /srv/shared", "/bin/bash")
    assert outsider.returncode != 0
