import hashlib
import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest


def run(command, *, env=None):
    subprocess.run(command, check=True, env=env)


def require_build_script():
    build_script = Path("/app/build.sh")
    assert build_script.exists(), "/app/build.sh was not created"
    assert os.access(build_script, os.X_OK), "/app/build.sh is not executable"


def build_archive(epoch: int):
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    run(["bash", "/app/build.sh"], env=env)
    archive_path = Path("/app/site.tar")
    assert archive_path.exists(), "/app/site.tar was not created"
    return archive_path.read_bytes()


def open_members(archive_bytes: bytes):
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as tf:
        ordered_members = tf.getmembers()
        member_names = [member.name.removeprefix("./") for member in ordered_members]
        members = {member.name.removeprefix("./"): member for member in ordered_members}
        contents = {}
        for name, member in members.items():
            if member.isfile():
                extracted = tf.extractfile(member)
                assert extracted is not None
                contents[name] = extracted.read()
        return member_names, members, contents


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def built_archives():
    require_build_script()

    archive_a = build_archive(946684800)
    archive_b = build_archive(946684800)
    archive_c = build_archive(946684801)
    member_names, members, contents = open_members(archive_a)
    return archive_a, archive_b, archive_c, member_names, members, contents


def test_archive_is_reproducible_and_epoch_driven(built_archives):
    archive_a, archive_b, archive_c, _, _, _ = built_archives
    assert sha256(archive_a) == sha256(archive_b)
    assert sha256(archive_a) != sha256(archive_c)


def test_archive_order_exclusions_and_directory_metadata(built_archives):
    _, _, _, member_names, members, _ = built_archives
    assert member_names == sorted(member_names)

    excluded = [
        "drafts",
        "drafts/posts/launch-plan.md",
        "preview-cache",
        "preview-cache/pages/home.html",
        "public/assets/js/site.js.map",
        ".cache",
        ".cache/cache.txt",
        ".config",
        ".config/site/dev.json",
        ".secrets",
        ".secrets/secret.txt",
        "public/broken-preview",
        "public/drafts-link",
        "public/blog/2026/launch/site-style",
    ]
    for name in excluded:
        assert name not in members

    required_dirs = [
        "public",
        "public/assets",
        "public/assets/css",
        "public/assets/js",
        "public/blog",
        "cgi-bin",
        ".well-known",
        ".well-known/acme-challenge",
    ]
    for name in required_dirs:
        assert name in members
        assert members[name].isdir()
        assert stat.S_IMODE(members[name].mode) == 0o755
        assert members[name].uid == 0
        assert members[name].gid == 0
        assert members[name].mtime == 946684800


def test_text_normalization_and_binary_preservation(built_archives):
    _, _, _, _, _, contents = built_archives
    assert contents["public/index.html"] == b"<!doctype html>\n<html>\n<body>\n<h1>Seed2Family</h1>\n</body>\n</html>\n"
    assert contents["public/assets/css/site.css"] == b"body {\n  background: #f6f7fb;\n}\n"
    assert contents["public/assets/js/site.js"] == b'window.site = {"theme":"aurora"};\n'
    assert contents["themes/aurora/theme.json"] == b'{\n  "name": "aurora",\n  "version": 3\n}\n'
    assert b"\r" not in contents["public/index.html"]
    assert b"\r" not in contents["public/assets/css/site.css"]
    assert b"\r" not in contents["public/assets/js/site.js"]
    assert b"\r" not in contents["themes/aurora/theme.json"]

    assert contents["cgi-bin/health-check"].startswith(b"#!/usr/bin/env bash\r\n")
    assert b"\r\n" in contents["cgi-bin/health-check"]
    assert contents["public/assets/img/logo.bin"] == b"PNG\x00\x01\x02\n"


def test_regular_file_metadata(built_archives):
    _, _, _, _, members, _ = built_archives
    regular_0644 = [
        "public/index.html",
        "public/robots.txt",
        "public/assets/css/site.css",
        "public/assets/js/site.js",
        "themes/aurora/theme.json",
        "public/assets/img/logo.bin",
        "public/downloads/package.txt",
        "public/assets/js/file with spaces.js",
        "public/assets/js/file$special!chars.js",
        "public/blog/2026/launch/post.html",
        ".well-known/acme-challenge/site-token",
    ]
    for name in regular_0644:
        assert name in members
        assert members[name].isfile()
        assert stat.S_IMODE(members[name].mode) == 0o644
        assert members[name].uid == 0
        assert members[name].gid == 0
        assert members[name].mtime == 946684800

    cgi_execs = ["cgi-bin/health-check", "cgi-bin/status.py"]
    for name in cgi_execs:
        assert name in members
        assert members[name].isfile()
        assert stat.S_IMODE(members[name].mode) == 0o755
        assert members[name].mtime == 946684800


def test_symlinks_and_path_edge_cases(built_archives):
    _, _, _, _, members, _ = built_archives
    symlinks = {
        "public/blog/home-link": "../index.html",
        "public/hosts-link": "/etc/hosts",
        "public/assets/theme-link.json": "../../themes/aurora/theme.json",
        ".well-known/index-link": "../public/index.html",
    }
    for name, target in symlinks.items():
        assert name in members
        assert members[name].issym()
        assert members[name].linkname == target
        assert members[name].uid == 0
        assert members[name].gid == 0
        assert members[name].mtime == 946684800

    long_name = (
        "public/launch_notes_with_a_name_that_pushes_the_ustar_limits_without_crossing_them_"
        "for_reproducible_archiving_checks_and_path_sorting_expectations_"
        "inside_the_public_tree_documentation_reference_page.html"
    )
    deep_name = (
        "public/deep/level-1/level-2/level-3/level-4/level-5/level-6/level-7/level-8/"
        "level-9/level-10/level-11/level-12/level-13/level-14/level-15/level-16/level-17/"
        "level-18/final.html"
    )
    assert long_name in members
    assert deep_name in members
