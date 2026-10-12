import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
from pathlib import Path


APP_DIR = Path("/app")
SRC_DIR = APP_DIR / "src"
META_PATH = SRC_DIR / ".release-meta.json"
ARCHIVE_PATH = APP_DIR / "release.tar.zst"


def run_build(epoch=None):
    env = os.environ.copy()
    if epoch is None:
        env.pop("SOURCE_DATE_EPOCH", None)
    else:
        env["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(["/app/build.sh"], check=True, env=env)
    return ARCHIVE_PATH.read_bytes()


def load_manifest():
    return json.loads(META_PATH.read_text())["files"]


def extract_archive_bytes(archive_bytes):
    decompressed = subprocess.run(
        ["zstd", "-d", "-c"],
        input=archive_bytes,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    return tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:")


def decompress_archive_bytes(archive_bytes):
    return subprocess.run(
        ["zstd", "-d", "-c"],
        input=archive_bytes,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout


def member_name(rel_path):
    return f"./{rel_path}"


def normalize_member_name(name):
    if name == "./":
        return "."
    return name.rstrip("/")


def expected_member_names(manifest):
    expected = {"."}

    for rel_path in manifest:
        expected.add(member_name(rel_path))

        parent = Path(rel_path).parent
        while str(parent) != ".":
            expected.add(member_name(parent.as_posix()))
            parent = parent.parent

    return expected


def raw_tar_headers(tar_bytes):
    headers = []

    for offset in range(0, len(tar_bytes), 512):
        block = tar_bytes[offset : offset + 512]
        if len(block) < 512 or block == b"\0" * 512:
            continue

        name = block[:100].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        prefix = block[345:500].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        if prefix:
            name = f"{prefix}/{name}"

        headers.append(
            {
                "name": name,
                "typeflag": block[156:157],
                "magic": block[257:263],
                "version": block[263:265],
            }
        )

    return headers


def recompress_with_required_zstd(tar_bytes):
    return subprocess.run(
        ["zstd", "-19", "--long", "--no-check", "--single-thread", "-c"],
        input=tar_bytes,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout


def source_path_for(rel_path):
    candidate = SRC_DIR / rel_path
    if candidate.exists() or candidate.is_symlink():
        return candidate

    escaped = SRC_DIR / rel_path.replace("!", r"\!")
    if escaped.exists() or escaped.is_symlink():
        return escaped

    raise FileNotFoundError(rel_path)


def test_build_script_is_executable():
    mode = Path("/app/build.sh").stat().st_mode
    assert mode & stat.S_IXUSR


def test_reproducible_for_same_epoch_and_changes_for_different_epoch():
    first = run_build(946684800)
    second = run_build(946684800)
    third = run_build(946684801)

    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert first != third


def test_default_epoch_falls_back_to_946684800():
    archive_bytes = run_build()

    with extract_archive_bytes(archive_bytes) as tar:
        assert tar.getmember(member_name("docs/README.txt")).mtime == 946684800


def test_manifest_drives_archive_contents_modes_and_metadata():
    manifest = load_manifest()
    archive_bytes = run_build(946684800)

    with extract_archive_bytes(archive_bytes) as tar:
        ordered_names = [normalize_member_name(member.name) for member in tar.getmembers()]
        assert ordered_names == sorted(ordered_names)

        members = {normalize_member_name(member.name): member for member in tar.getmembers()}
        assert set(members) == expected_member_names(manifest)

        for rel_path, meta in manifest.items():
            member = members[member_name(rel_path)]
            assert member.uid == 0
            assert member.gid == 0
            assert member.mtime == 946684800

            if meta["kind"] == "symlink":
                assert member.issym()
                assert member.linkname == os.readlink(source_path_for(rel_path))
            else:
                assert member.isfile()
                assert stat.S_IMODE(member.mode) == int(meta["mode"], 8)

        assert stat.S_IMODE(members[member_name("tools/run")].mode) == 0o755
        assert stat.S_IMODE(members[member_name("scripts/no_shebang")].mode) == 0o755
        assert stat.S_IMODE(members[member_name("assets/template.cgi")].mode) == 0o644
        assert stat.S_IMODE(members[member_name("tools/bin/helper.bin")].mode) == 0o755
        assert stat.S_IMODE(members["./src"].mode) == 0o755
        assert stat.S_IMODE(members["./tools/bin"].mode) == 0o755


def test_only_manifest_text_files_get_crlf_normalized():
    manifest = load_manifest()
    archive_bytes = run_build(946684800)

    with extract_archive_bytes(archive_bytes) as tar:
        for rel_path, meta in manifest.items():
            member = tar.getmember(member_name(rel_path))

            if meta["kind"] == "symlink":
                continue

            archived = tar.extractfile(member).read()
            source = source_path_for(rel_path).read_bytes()

            if meta["kind"] == "text":
                assert b"\r" not in archived
                assert archived == source.replace(b"\r\n", b"\n")
            else:
                assert archived == source


def test_archive_uses_gnu_tar_headers_for_long_paths():
    archive_bytes = run_build(946684800)
    headers = raw_tar_headers(decompress_archive_bytes(archive_bytes))

    assert any(
        header["name"] == "././@LongLink"
        and header["typeflag"] == b"L"
        and header["magic"] == b"ustar "
        and header["version"] == b" \x00"
        for header in headers
    )


def test_archive_uses_required_zstd_settings():
    archive_bytes = run_build(946684800)
    tar_bytes = decompress_archive_bytes(archive_bytes)

    assert archive_bytes == recompress_with_required_zstd(tar_bytes)
