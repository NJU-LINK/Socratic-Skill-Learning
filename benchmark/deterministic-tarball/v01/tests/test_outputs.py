import hashlib
import io
import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path


ARCHIVE_PATH = Path("/app/release.tar.zst")
BUILD_SCRIPT = Path("/app/build.sh")
SOURCE_ROOT = Path("/app/src")


def normalize_name(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    return name.rstrip("/")


def run_build(epoch: int = 1_700_000_000):
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run([str(BUILD_SCRIPT)], check=True, env=env)
    archive_bytes = ARCHIVE_PATH.read_bytes()
    tar_bytes = subprocess.check_output(["zstd", "-dc", str(ARCHIVE_PATH)])
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as bundle:
        members = {
            normalize_name(member.name): member
            for member in bundle.getmembers()
            if normalize_name(member.name)
        }
    return archive_bytes, members


def read_tar_stream() -> bytes:
    return subprocess.check_output(["zstd", "-dc", str(ARCHIVE_PATH)])


def test_build_script_creates_reproducible_release_archive():
    assert BUILD_SCRIPT.exists(), "/app/build.sh was not created"
    assert os.access(BUILD_SCRIPT, os.X_OK), "/app/build.sh is not executable"

    first_archive, _ = run_build()
    second_archive, _ = run_build()

    assert hashlib.sha256(first_archive).digest() == hashlib.sha256(second_archive).digest()


def test_archive_contents_metadata_and_normalization():
    _, members = run_build()

    long_name = (
        "very_long_filename_that_exceeds_two_hundred_characters_"
        "this_is_to_test_edge_cases_in_tar_handling_and_filesystem_limits_"
        "some_systems_have_issues_with_very_long_paths_so_we_need_to_test_this_properly_"
        "end.txt"
    )
    deep_path = "/".join(["deeply", *(["nested"] * 22), "file.txt"])

    included = {
        ".distignore",
        "app/src/main.c",
        "app/src/windows.py",
        "app/src/unix.py",
        "app/src/README",
        "app/src/passwd-link",
        "app/src/file with spaces.txt",
        "app/src/file$special\\!chars.py",
        f"app/src/{long_name}",
        "app/src/mixed.dat",
        "assets/red.png",
        "docs/README.txt",
        "docs/guide.md",
        "tools/build-release.sh",
        deep_path,
    }
    for path in included:
        assert path in members, f"missing {path} from archive"

    excluded_prefixes = (".hg/", "vendor/js/", "scratch/", ".state/", "keys/", "secrets/")
    for name in members:
        assert not name.startswith(excluded_prefixes), f"unexpected excluded path in archive: {name}"
        assert "__pycache__" not in name, f"unexpected cache path in archive: {name}"
        assert not name.endswith((".tmp", ".pyc", ".pyo", ".o", ".class")), f"unexpected generated file in archive: {name}"

    assert members["app/src/README"].issym()
    assert members["app/src/README"].linkname == "../docs/README.txt"
    assert members["app/src/passwd-link"].issym()
    assert members["app/src/passwd-link"].linkname == "/etc/passwd"

    epoch = 1_700_000_000
    for name, member in members.items():
        assert member.uid == 0, f"{name} uid was not normalized"
        assert member.gid == 0, f"{name} gid was not normalized"
        assert int(member.mtime) == epoch, f"{name} mtime was not normalized"

    assert stat.S_IMODE(members["app/src/main.c"].mode) == 0o644
    assert stat.S_IMODE(members["app/src/windows.py"].mode) == 0o644
    assert stat.S_IMODE(members["app/src/unix.py"].mode) == 0o755
    assert stat.S_IMODE(members["tools/build-release.sh"].mode) == 0o755
    assert stat.S_IMODE(members["app/src/readonly.txt"].mode) == 0o644
    assert stat.S_IMODE(members["docs"].mode) == 0o755

    extract_dir = Path("/tmp/test-release-extract")
    if extract_dir.exists():
        subprocess.run(["rm", "-rf", str(extract_dir)], check=True)
    extract_dir.mkdir(parents=True)
    subprocess.run(
        ["bash", "-lc", f'zstd -dc "{ARCHIVE_PATH}" | tar -xf - -C "{extract_dir}"'],
        check=True,
    )

    assert (extract_dir / "app/src/windows.py").read_bytes() == b'import sys\nprint("release build")\n'
    assert (extract_dir / "docs/README.txt").read_bytes() == b"Release Notes\nVersion 1\n"
    assert (extract_dir / "app/src/mixed.dat").read_bytes() == (SOURCE_ROOT / "app/src/mixed.dat").read_bytes()
    assert (extract_dir / "assets/red.png").read_bytes() == Path("/app/src/assets/red.png").read_bytes()
    assert os.path.islink(extract_dir / "app/src/README")
    assert os.readlink(extract_dir / "app/src/README") == "../docs/README.txt"


def test_build_script_uses_required_archive_format_and_compression_flags():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "--format=gnu" in script
    assert re.search(r"zstd(?:\s|\\\n)+-19(?:\s|\\\n)+--long(?:\s|\\\n)+--no-check(?:\s|\\\n)+--single-thread", script)


def test_archive_is_gnu_tar_and_zstd_frame_has_no_checksum():
    run_build()

    tar_bytes = read_tar_stream()
    assert b"././@LongLink" in tar_bytes, "expected GNU tar long-name records"
    assert b"PaxHeaders" not in tar_bytes, "archive should not use pax headers"

    frame_info = subprocess.check_output(["zstd", "-lv", str(ARCHIVE_PATH)], text=True)
    assert re.search(r"Check(?:sum)?:\s+None", frame_info)


def test_build_script_reads_distignore_each_time():
    distignore = SOURCE_ROOT / ".distignore"
    original = distignore.read_text(encoding="utf-8")
    try:
        distignore.write_text(original + "\ndocs/\n", encoding="utf-8")
        _, members = run_build()
        assert "docs" not in members
        assert "docs/README.txt" not in members
        assert "docs/guide.md" not in members
    finally:
        distignore.write_text(original, encoding="utf-8")


def test_build_script_excludes_files_that_become_mode_0600():
    target = SOURCE_ROOT / "docs/guide.md"
    original_mode = stat.S_IMODE(target.stat().st_mode)
    try:
        target.chmod(0o600)
        _, members = run_build()
        assert "docs/guide.md" not in members
    finally:
        target.chmod(original_mode)
