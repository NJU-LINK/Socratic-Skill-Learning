from collections import Counter
import hashlib
import os
import stat
import subprocess
import tempfile
from pathlib import Path


RELEASE = Path("/app/release.tar.zst")
SOURCE = Path("/app/src")
# Verified from this isolated variant with fresh container rebuilds.
EXPECTED_SEED_SHA256 = "0d8c648928b7192d5c85c437710190b50429e4bf4d9800b5f47fe54d700f2f5f"


def run_build():
    subprocess.run(["bash", "/app/build.sh"], check=True)
    assert RELEASE.exists(), "release archive was not created"
    return hashlib.sha256(RELEASE.read_bytes()).hexdigest()


def tar_list(*args: str) -> list[str]:
    result = subprocess.run(
        ["tar", "--zstd", *args, "-f", str(RELEASE)],
        check=True,
        text=True,
        capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def extract_archive(target: Path) -> None:
    subprocess.run(["tar", "--zstd", "-xf", str(RELEASE), "-C", str(target)], check=True)


def normalized_member_name(line: str) -> str:
    name = line.removesuffix("/")
    return name[2:] if name.startswith("./") else name


def member_names() -> list[str]:
    names = []
    for line in tar_list("-t"):
        name = normalized_member_name(line)
        names.append(name)
    return names


def member_counts() -> Counter[str]:
    return Counter(member_names())


def metadata_map() -> dict[str, str]:
    info = {}
    for line in tar_list("-tv", "--full-time", "--numeric-owner"):
        parts = line.split(maxsplit=5)
        name_field = parts[5].split(" -> ", 1)[0]
        name = normalized_member_name(name_field)
        info[name] = line
    return info


def stat_mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_solution_creates_executable_build_script():
    build_script = Path("/app/build.sh")
    assert build_script.exists(), "solution did not create /app/build.sh"
    assert os.access(build_script, os.X_OK), "/app/build.sh is not executable"


def test_build_is_reproducible_and_manifest_driven():
    original = SOURCE.joinpath(".release-times").read_text()
    first = run_build()
    second = run_build()
    assert first == EXPECTED_SEED_SHA256, "seeded source tree archive hash does not match"
    assert first == second, "repeated identical builds must match"

    changed = original.replace("src/main.c 1704067238", "src/main.c 1704067999")
    SOURCE.joinpath(".release-times").write_text(changed)
    try:
        third = run_build()
        fourth = run_build()
    finally:
        SOURCE.joinpath(".release-times").write_text(original)

    assert third == fourth, "changed manifest should still yield deterministic output"
    assert third != first, "changing manifest timestamps should change archive hash"


def test_archive_contents_metadata_and_normalization():
    run_build()
    archive_member_counts = member_counts()
    archive_members = set(archive_member_counts)

    assert all(count == 1 for count in archive_member_counts.values()), (
        f"archive contains duplicate members: {archive_member_counts}"
    )

    assert ".git" not in archive_members
    assert "node_modules" not in archive_members
    assert "tmp" not in archive_members
    assert ".cache" not in archive_members
    assert "src/__pycache__" not in archive_members
    assert "src/main.o" not in archive_members
    assert "keys/private.key" not in archive_members
    assert "secrets/db.conf" not in archive_members

    for expected in {
        ".release-times",
        "build.sh",
        "assets",
        "docs",
        "config",
        "keys",
        "secrets",
        "src/README",
        "src/passwd-link",
        "src/file with spaces.txt",
        "src/file$special!chars.py",
        "deeply/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/file.txt",
    }:
        assert expected in archive_members

    metadata = metadata_map()
    assert "2024-01-01 00:00:03" in metadata["build.sh"]
    assert "2024-01-01 00:00:40" in metadata["src/passwd-link"]
    assert "2024-01-01 00:00:43" in metadata["src/windows.py"]
    assert "2000-01-01 00:00:00" in metadata["keys"]
    assert "2000-01-01 00:00:00" in metadata["secrets"]
    assert " 0/0 " in metadata["build.sh"]

    with tempfile.TemporaryDirectory() as temp_dir:
        extract_root = Path(temp_dir)
        extract_archive(extract_root)

        assert stat_mode(extract_root / "build.sh") == 0o755
        assert stat_mode(extract_root / "src" / "unix.py") == 0o755
        assert stat_mode(extract_root / "src" / "main.c") == 0o644
        assert stat_mode(extract_root / "src") == 0o755
        assert stat_mode(extract_root / "keys") == 0o755

        readme = (extract_root / "docs" / "README.txt").read_bytes()
        windows_py = (extract_root / "src" / "windows.py").read_bytes()
        config = (extract_root / "config" / "settings.json").read_bytes()
        mixed = (extract_root / "src" / "mixed.dat").read_bytes()
        original_png = (SOURCE / "assets" / "red.png").read_bytes()
        extracted_png = (extract_root / "assets" / "red.png").read_bytes()

        assert b"\r\n" not in readme
        assert b"\r\n" not in windows_py
        assert b"\r\n" not in config
        assert b"\x00\x01\x02\x03" in mixed
        assert b"\r\n" in original_png
        assert extracted_png == original_png

        readme_link = extract_root / "src" / "README"
        passwd_link = extract_root / "src" / "passwd-link"
        assert readme_link.is_symlink()
        assert os.readlink(readme_link) == "../docs/README.txt"
        assert passwd_link.is_symlink()
        assert os.readlink(passwd_link) == "/etc/passwd"
