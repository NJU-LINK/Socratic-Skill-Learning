import hashlib
import os
import pathlib
import stat
import subprocess
import tarfile


ROOT = pathlib.Path("/app")
SRC = ROOT / "src"
PAYLOAD = ROOT / "release.tar.zst"
META = ROOT / "release-meta.tar.zst"


def run(cmd, *, env=None):
    subprocess.run(cmd, check=True, text=True, env=env)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assert_lf_normalized(path: pathlib.Path) -> None:
    data = path.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")


def extract_tar_zst(archive: pathlib.Path, dest: pathlib.Path) -> None:
    tree = dest / "tree"
    tree.mkdir()
    run(["tar", "--zstd", "-xf", str(archive), "-C", str(tree)])


def read_tar_headers(archive: pathlib.Path, dest: pathlib.Path):
    dest.mkdir()
    tar_path = dest / f"{archive.name}.tar"
    run(["zstd", "-d", "-q", "-o", str(tar_path), str(archive)])
    with tarfile.open(tar_path, "r:") as tf:
        return tf.getmembers()


def manifest_map(manifest_path: pathlib.Path):
    entries = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        entries[rel] = digest
    return entries


def build(epoch: str):
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = epoch
    run(["/app/build.sh"], env=env)
    return PAYLOAD.read_bytes(), META.read_bytes()


def test_build_script_creates_reproducible_dual_archives(tmp_path):
    first_payload, first_meta = build("946684800")
    second_payload, second_meta = build("946684800")

    assert first_payload == second_payload
    assert first_meta == second_meta

    third_payload, third_meta = build("946684801")
    assert third_payload != first_payload
    assert third_meta != first_meta


def test_payload_exclusions_and_normalization(tmp_path):
    build("946684800")
    extract_tar_zst(PAYLOAD, tmp_path)
    tree = tmp_path / "tree"

    assert not (tree / ".git").exists()
    assert not (tree / "node_modules").exists()
    assert not (tree / "tmp").exists()
    assert not (tree / ".cache").exists()
    assert not (tree / "reports" / "generated-checksums.sha256").exists()
    assert not (tree / "src" / "main.o").exists()
    assert not (tree / "src" / "__pycache__").exists()
    assert not (tree / "keys" / "private.key").exists()
    assert not (tree / "secrets" / "db.conf").exists()

    assert_lf_normalized(tree / "src" / "windows.py")
    assert_lf_normalized(tree / "docs" / "README.txt")
    assert_lf_normalized(tree / "generated" / "build-note.txt")

    mixed_data = (tree / "src" / "mixed.dat").read_bytes()
    assert b"\x00\x01\x02\x03" in mixed_data

    assert (tree / "assets" / "red.png").read_bytes() == (SRC / "assets" / "red.png").read_bytes()

    readme_link = tree / "src" / "README"
    passwd_link = tree / "src" / "passwd-link"
    assert readme_link.is_symlink()
    assert passwd_link.is_symlink()
    assert os.readlink(readme_link) == "../docs/README.txt"
    assert os.readlink(passwd_link) == "/etc/passwd"

    assert stat.S_IMODE((tree / "build.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((tree / "src" / "unix.py").stat().st_mode) == 0o755
    assert stat.S_IMODE((tree / "src" / "main.c").stat().st_mode) == 0o644
    assert stat.S_IMODE((tree / "docs" / "index.md").stat().st_mode) == 0o644
    assert stat.S_IMODE((tree / "generated" / "build-note.txt").stat().st_mode) == 0o644
    assert stat.S_IMODE((tree / "src" / "readonly.txt").stat().st_mode) == 0o644

    for dirpath, _, _ in os.walk(tree):
        dirpath = pathlib.Path(dirpath)
        if dirpath != tree:
            assert stat.S_IMODE(dirpath.stat().st_mode) == 0o755


def test_metadata_archive_matches_payload_contents(tmp_path):
    build("946684800")

    payload_dir = tmp_path / "payload"
    meta_dir = tmp_path / "meta"
    payload_dir.mkdir()
    meta_dir.mkdir()
    extract_tar_zst(PAYLOAD, payload_dir)
    extract_tar_zst(META, meta_dir)

    manifest_path = meta_dir / "tree" / "MANIFEST.txt"
    build_info_path = meta_dir / "tree" / "BUILD-INFO.txt"
    manifest = manifest_map(manifest_path)

    assert sorted(manifest) == list(manifest)
    assert set((meta_dir / "tree").iterdir()) == {manifest_path, build_info_path}

    payload_tree = payload_dir / "tree"
    payload_entries = []
    for path in sorted(payload_tree.rglob("*")):
        rel = path.relative_to(payload_tree).as_posix()
        if path.is_symlink():
            payload_entries.append(rel)
            assert manifest[rel] == sha256_bytes(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            payload_entries.append(rel)
            assert manifest[rel] == sha256_bytes(path.read_bytes())

    assert sorted(payload_entries) == list(manifest)

    build_info = build_info_path.read_text(encoding="utf-8")
    assert "EPOCH=946684800" in build_info
    assert "PAYLOAD_COMPRESSOR=zstd -19 --long --no-check --single-thread" in build_info
    assert "META_COMPRESSOR=zstd -19 --long --no-check --single-thread" in build_info


def test_archives_store_numeric_owner_group_zero(tmp_path):
    build("946684800")

    payload_members = read_tar_headers(PAYLOAD, tmp_path / "payload-headers")
    meta_members = read_tar_headers(META, tmp_path / "meta-headers")

    assert payload_members
    assert meta_members

    for member in payload_members + meta_members:
        assert member.uid == 0
        assert member.gid == 0
        assert member.uname in {"", "root"}
        assert member.gname in {"", "root"}
