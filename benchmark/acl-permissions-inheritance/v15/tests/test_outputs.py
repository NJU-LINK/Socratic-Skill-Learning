import os
import stat
import subprocess
from pathlib import Path


def run(cmd, *, user=None, check=True):
    if user:
        cmd = ["runuser", "-u", user, "--", *cmd]
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def acl_text(path):
    return run(["getfacl", "-cp", path]).stdout


def test_workspace_layout_and_modes():
    shared = Path("/srv/shared")
    bin_dir = shared / "bin"
    drop_dir = shared / "drop"

    assert shared.is_dir()
    assert bin_dir.is_dir()
    assert drop_dir.is_dir()

    for path in (bin_dir, drop_dir):
        st = path.stat()
        assert st.st_mode & stat.S_ISGID


def test_group_ownership_and_acl_entries():
    research_gid = int(run(["getent", "group", "research"]).stdout.split(":")[2])

    for path in ("/srv/shared/bin", "/srv/shared/drop"):
        st = os.stat(path)
        assert st.st_gid == research_gid

    bin_acl = acl_text("/srv/shared/bin")
    assert "user:alice:rwx" in bin_acl
    assert "user:bob:rwx" in bin_acl
    assert "default:user:alice:rwx" in bin_acl
    assert "default:user:bob:rwx" in bin_acl
    assert "other::---" in bin_acl
    assert "default:other::---" in bin_acl

    drop_acl = acl_text("/srv/shared/drop")
    assert "user:alice:rwx" in drop_acl
    assert "user:bob:r-x" in drop_acl
    assert "default:user:alice:rwx" in drop_acl
    assert "default:user:bob:r-x" in drop_acl
    assert "group::---" in drop_acl
    assert "default:group::---" in drop_acl
    assert "other::---" in drop_acl
    assert "default:other::---" in drop_acl


def test_bin_collaboration_inherits_to_descendants():
    run(["mkdir", "-p", "/srv/shared/bin/tools"], user="alice")
    run(["bash", "-lc", "printf '#!/bin/sh\necho hi\n' > /srv/shared/bin/tools/hello.sh"], user="alice")
    run(["chmod", "+x", "/srv/shared/bin/tools/hello.sh"], user="alice")

    result = run(["bash", "-lc", "printf 'from bob\n' >> /srv/shared/bin/tools/hello.sh"], user="bob")
    assert result.returncode == 0

    file_acl = acl_text("/srv/shared/bin/tools/hello.sh")
    dir_acl = acl_text("/srv/shared/bin/tools")
    assert "user:alice:rwx" in dir_acl
    assert "user:bob:rwx" in dir_acl
    assert "default:user:alice:rwx" in dir_acl
    assert "default:user:bob:rwx" in dir_acl
    assert "user:alice:rwx" in file_acl
    assert "user:bob:rwx" in file_acl


def test_drop_area_enforces_handoff_permissions():
    run(["mkdir", "-p", "/srv/shared/drop/inbox"], user="alice")
    run(["bash", "-lc", "printf 'sample payload\n' > /srv/shared/drop/inbox/note.txt"], user="alice")

    read_result = run(["bash", "-lc", "cat /srv/shared/drop/inbox/note.txt"], user="bob")
    assert read_result.stdout == "sample payload\n"

    dir_acl = acl_text("/srv/shared/drop/inbox")
    file_acl = acl_text("/srv/shared/drop/inbox/note.txt")
    assert "user:alice:rwx" in dir_acl
    assert "user:bob:r-x" in dir_acl
    assert "default:user:alice:rwx" in dir_acl
    assert "default:user:bob:r-x" in dir_acl
    assert "user:alice:rw-" in file_acl or "user:alice:rwx" in file_acl
    assert "#effective:r--" in file_acl
    assert "user:bob:r-x" in file_acl or "user:bob:r--" in file_acl

    edit_attempt = run(
        ["bash", "-lc", "printf 'tamper\n' >> /srv/shared/drop/inbox/note.txt"],
        user="bob",
        check=False,
    )
    assert edit_attempt.returncode != 0

    delete_attempt = run(["rm", "/srv/shared/drop/inbox/note.txt"], user="bob", check=False)
    assert delete_attempt.returncode != 0


def test_outsider_cannot_access_either_subtree():
    for path in ("/srv/shared/bin", "/srv/shared/drop"):
        result = run(["ls", path], user="mallory", check=False)
        assert result.returncode != 0
