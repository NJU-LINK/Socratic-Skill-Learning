import gzip
import hashlib
import io
import os
import pathlib
import stat
import subprocess
import tarfile


BUILD_SCRIPT = pathlib.Path("/app/build.sh")
ARCHIVE_PATH = pathlib.Path("/app/project.tar.gz")
WORKSPACE = pathlib.Path("/app/workspace")


def run_build(epoch=None):
    env = os.environ.copy()
    if epoch is None:
        env.pop("SOURCE_DATE_EPOCH", None)
    else:
        env["SOURCE_DATE_EPOCH"] = str(epoch)

    subprocess.run([str(BUILD_SCRIPT)], check=True, env=env)
    return ARCHIVE_PATH.read_bytes()


def tar_members(archive_bytes):
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tf:
        members = tf.getmembers()
        payload = {}
        for member in members:
            if member.isfile():
                payload[member.name] = tf.extractfile(member).read()
        return members, payload


def test_build_script_is_executable_and_reproducible():
    assert BUILD_SCRIPT.exists(), "/app/build.sh was not created"
    assert os.access(BUILD_SCRIPT, os.X_OK), "/app/build.sh is not executable"

    first = run_build(1700000000)
    second = run_build(1700000000)
    third = run_build(1700001234)

    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert hashlib.sha256(first).hexdigest() != hashlib.sha256(third).hexdigest()


def test_archive_layout_metadata_and_content_rules():
    archive_bytes = run_build(1700000000)
    members, payload = tar_members(archive_bytes)

    names = [member.name for member in members]
    assert names == sorted(names)
    assert names[0] == "project"
    assert all(name == "project" or name.startswith("project/") for name in names)

    forbidden_parts = ("/build/", "/.deps/", "/cache/", "/credentials/")
    assert not any(name.endswith(".bak") for name in names)
    assert not any(part in name for name in names for part in forbidden_parts)

    required = {
        "project/appsrc/main.c",
        "project/appsrc/lib/windows_style.py",
        "project/appsrc/scripts/deploy.sh",
        "project/appsrc/notes-link",
        "project/appsrc/external-hosts-link",
        "project/guide/patches/release.patch",
        "project/assets/mixed.dat",
        "project/assets/blob.bin",
        "project/guide/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/deep/final.txt",
    }
    assert required.issubset(set(names))

    by_name = {member.name: member for member in members}

    for member in members:
        assert member.uid == 1000
        assert member.gid == 1000
        assert member.mtime == 1700000000
        if member.isdir():
            assert stat.S_IMODE(member.mode) == 0o755
        elif member.isfile():
            if member.name in {
                "project/appsrc/scripts/deploy.sh",
                "project/tools/helper.sh",
            }:
                assert stat.S_IMODE(member.mode) == 0o755
            else:
                assert stat.S_IMODE(member.mode) == 0o644

    assert by_name["project/appsrc/notes-link"].issym()
    assert by_name["project/appsrc/notes-link"].linkname == "../guide/notes/README.txt"
    assert by_name["project/appsrc/external-hosts-link"].issym()
    assert by_name["project/appsrc/external-hosts-link"].linkname == "/etc/hosts"

    assert payload["project/appsrc/lib/windows_style.py"] == b"import pathlib\nprint(pathlib.Path(__file__).name)\n"
    assert payload["project/guide/notes/README.txt"] == b"Stage 1\nStage 2\n"
    assert b"\r\n" not in payload["project/appsrc/lib/windows_style.py"]
    assert b"\r\n" not in payload["project/guide/notes/README.txt"]

    source_patch = (WORKSPACE / "guide/patches/release.patch").read_bytes()
    assert payload["project/guide/patches/release.patch"] == source_patch
    assert b"\r\n" in payload["project/guide/patches/release.patch"]

    assert payload["project/assets/mixed.dat"] == (WORKSPACE / "assets/mixed.dat").read_bytes()
    assert payload["project/assets/blob.bin"] == (WORKSPACE / "assets/blob.bin").read_bytes()

    long_member = next(name for name in names if "deterministic_archive_validation_filename" in name)
    assert "path" in by_name[long_member].pax_headers


def test_gzip_header_matches_gzip_nine_no_name():
    archive_bytes = run_build(1700000000)
    assert archive_bytes[:3] == b"\x1f\x8b\x08"
    assert archive_bytes[3] == 0
    assert archive_bytes[4:8] == b"\x00\x00\x00\x00"
    assert archive_bytes[8] == 2

    with gzip.GzipFile(fileobj=io.BytesIO(archive_bytes), mode="rb") as gz:
        tar_stream = io.BytesIO(gz.read())

    with tarfile.open(fileobj=tar_stream, mode="r:") as tf:
        assert tf.getmember("project")
