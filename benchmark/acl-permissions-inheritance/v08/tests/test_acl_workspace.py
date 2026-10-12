import grp
import subprocess
from pathlib import Path


SHARED_DIR = Path("/srv/shared")


def run(cmd: list[str], *, check: bool = True, user: str | None = None) -> subprocess.CompletedProcess[str]:
    if user is not None:
        cmd = ["runuser", "-u", user, "--", *cmd]
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def test_shared_directory_base_properties():
    stat_result = SHARED_DIR.stat()
    assert stat_result.st_mode & 0o7777 == 0o2770
    assert stat_result.st_gid == grp.getgrnam("research").gr_gid


def test_top_level_acl_policy():
    acl = run(["getfacl", "-cp", str(SHARED_DIR)]).stdout
    assert "user::rwx" in acl
    assert "user:carol:rwx" in acl
    assert "user:mallory:---" in acl
    assert "group::rwx" in acl
    assert "mask::rwx" in acl
    assert "other::---" in acl
    assert "default:user:carol:rwx" in acl
    assert "default:user:mallory:---" in acl
    assert "default:group::rwx" in acl
    assert "default:mask::rwx" in acl
    assert "default:other::---" in acl


def test_collaborators_can_create_and_access_inherited_content():
    team_dir = SHARED_DIR / "alice-area"
    team_file = team_dir / "notes.txt"

    run(["mkdir", str(team_dir)], user="alice")
    run(["bash", "-lc", f"printf 'from alice' > {team_file}"], user="alice")

    team_dir_stat = team_dir.stat()
    assert team_dir_stat.st_mode & 0o2000 == 0o2000
    assert team_dir_stat.st_gid == grp.getgrnam("research").gr_gid

    dir_acl = run(["getfacl", "-cp", str(team_dir)]).stdout
    file_acl = run(["getfacl", "-cp", str(team_file)]).stdout

    assert "group::rwx" in dir_acl
    assert "user:carol:rwx" in dir_acl
    assert "user:mallory:---" in dir_acl
    assert "default:user:carol:rwx" in dir_acl
    assert "default:user:mallory:---" in dir_acl

    assert "group::rwx" in file_acl
    assert "user:carol:rwx" in file_acl
    assert "user:mallory:---" in file_acl
    assert "mask::rw-" in file_acl
    assert "mask::rwx" in dir_acl

    for user in ["alice", "bob", "carol"]:
        cat_result = run(["cat", str(team_file)], user=user)
        assert cat_result.stdout == "from alice"

    denied_dir = run(["ls", str(team_dir)], user="mallory", check=False)
    denied_file = run(["cat", str(team_file)], user="mallory", check=False)
    assert denied_dir.returncode != 0
    assert denied_file.returncode != 0


def test_group_and_named_acl_access_both_propagate_for_later_descendants():
    project_dir = SHARED_DIR / "carol-project"
    nested_dir = project_dir / "nested"
    nested_file = nested_dir / "report.txt"

    run(["mkdir", str(project_dir)], user="carol")
    run(["mkdir", str(nested_dir)], user="carol")
    run(["bash", "-lc", f"printf 'cross-check' > {nested_file}"], user="carol")

    project_gid = str(project_dir.stat().st_gid)
    research_gid = subprocess.run(["getent", "group", "research"], text=True, capture_output=True, check=True).stdout.split(":")[2]
    assert project_gid == research_gid
    assert str(nested_dir.stat().st_gid) == research_gid
    assert str(nested_file.stat().st_gid) == research_gid

    nested_acl = run(["getfacl", "-cp", str(nested_dir)]).stdout
    assert "user:carol:rwx" in nested_acl
    assert "user:mallory:---" in nested_acl
    assert "default:user:carol:rwx" in nested_acl
    assert "default:user:mallory:---" in nested_acl

    for user in ["alice", "bob", "carol"]:
        list_result = run(["ls", str(project_dir)], user=user)
        assert "nested" in list_result.stdout.split()
        cat_result = run(["cat", str(nested_file)], user=user)
        assert cat_result.stdout == "cross-check"

    denied = run(["bash", "-lc", f"cd {project_dir}"], user="mallory", check=False)
    assert denied.returncode != 0
