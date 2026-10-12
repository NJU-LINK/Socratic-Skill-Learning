import grp
import pwd
import re
import subprocess
from pathlib import Path


SHARED = Path("/srv/shared")


def run(cmd, *, check=True, user=None):
    if user is not None:
        cmd = ["runuser", "-u", user, "--", *cmd]
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def getfacl(path):
    return run(["getfacl", "-cp", str(path)]).stdout


def extract_acl_line(acl_text, prefix):
    for line in acl_text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"Missing ACL entry: {prefix}\n{acl_text}")


def assert_effective(line, expected=None):
    match = re.search(r"#effective:([rwx-]+)$", line)
    if expected is None:
        assert match is None, f"Unexpected effective permission marker: {line}"
        return
    assert match, f"Missing effective permission marker: {line}"
    assert match.group(1) == expected, line


def test_shared_directory_metadata_and_acl_entries():
    st = SHARED.stat()
    assert oct(st.st_mode & 0o7777) == "0o2770"
    assert grp.getgrgid(st.st_gid).gr_name == "research"

    acl_text = getfacl(SHARED)
    assert extract_acl_line(acl_text, "user::rwx") == "user::rwx"
    assert extract_acl_line(acl_text, "group::rwx") == "group::rwx"
    alice_line = extract_acl_line(acl_text, "user:alice:rwx")
    assert_effective(alice_line, None)
    reviewer_line = extract_acl_line(acl_text, "user:reviewer:r-x")
    assert_effective(reviewer_line, None)
    assert extract_acl_line(acl_text, "mask::rwx") == "mask::rwx"
    assert extract_acl_line(acl_text, "other::---") == "other::---"


def test_default_acl_preserves_collaborator_write_access():
    acl_text = getfacl(SHARED)
    assert extract_acl_line(acl_text, "default:user::rwx") == "default:user::rwx"
    assert extract_acl_line(acl_text, "default:group::rwx") == "default:group::rwx"
    alice_line = extract_acl_line(acl_text, "default:user:alice:rwx")
    assert_effective(alice_line, None)
    reviewer_line = extract_acl_line(acl_text, "default:user:reviewer:r-x")
    assert_effective(reviewer_line, None)
    assert extract_acl_line(acl_text, "default:mask::rwx") == "default:mask::rwx"
    assert extract_acl_line(acl_text, "default:other::---") == "default:other::---"


def test_non_owner_group_collaborator_can_write_and_inherit_group():
    collab_dir = SHARED / "collab-space"
    collab_file = collab_dir / "group-notes.txt"

    run(["mkdir", str(collab_dir)], user="collaborator")
    run(["bash", "-lc", f"printf 'first\n' > {collab_file}"], user="collaborator")

    dir_stat = collab_dir.stat()
    file_stat = collab_file.stat()
    assert grp.getgrgid(dir_stat.st_gid).gr_name == "research"
    assert grp.getgrgid(file_stat.st_gid).gr_name == "research"
    assert pwd.getpwuid(file_stat.st_uid).pw_name == "collaborator"

    dir_acl = getfacl(collab_dir)
    file_acl = getfacl(collab_file)
    assert extract_acl_line(dir_acl, "group::rwx") == "group::rwx"
    assert extract_acl_line(dir_acl, "mask::rwx") == "mask::rwx"
    file_group_acl = extract_acl_line(file_acl, "group::rwx")
    assert file_group_acl in {"group::rwx", "group::rwx\t#effective:rw-"}
    assert extract_acl_line(file_acl, "mask::rw-") == "mask::rw-"
    reviewer_line = extract_acl_line(file_acl, "user:reviewer:r-x")
    assert_effective(reviewer_line, "r--")

    alice_append = run(["bash", "-lc", f"printf 'alice\n' >> {collab_file}"], user="alice")
    assert alice_append.returncode == 0
    second_append = run(["bash", "-lc", f"printf 'second\n' >> {collab_file}"], user="collaborator")
    assert second_append.returncode == 0
    assert collab_file.read_text() == "first\nalice\nsecond\n"


def test_reviewer_is_read_only_on_directories_and_files():
    review_dir = SHARED / "review-target"
    review_file = review_dir / "notes.txt"
    run(["mkdir", str(review_dir)], user="alice")
    run(["bash", "-lc", f"printf 'draft\n' > {review_file}"], user="alice")

    dir_acl = getfacl(review_dir)
    file_acl = getfacl(review_file)
    assert extract_acl_line(dir_acl, "user:reviewer:r-x") == "user:reviewer:r-x"
    reviewer_file = extract_acl_line(file_acl, "user:reviewer:r-x")
    assert_effective(reviewer_file, "r--")

    read_result = run(["cat", str(review_file)], user="reviewer")
    assert read_result.stdout == "draft\n"

    append_attempt = run(
        ["bash", "-lc", f"printf 'review\n' >> {review_file}"],
        user="reviewer",
        check=False,
    )
    assert append_attempt.returncode != 0
    assert review_file.read_text() == "draft\n"

    create_attempt = run(["mkdir", str(review_dir / "blocked")], user="reviewer", check=False)
    assert create_attempt.returncode != 0

    rename_attempt = run(
        ["mv", str(review_file), str(review_dir / "notes-renamed.txt")],
        user="reviewer",
        check=False,
    )
    assert rename_attempt.returncode != 0
    assert review_file.exists()


def test_others_are_denied():
    denied = run(["ls", str(SHARED)], user="nobody", check=False)
    assert denied.returncode != 0
