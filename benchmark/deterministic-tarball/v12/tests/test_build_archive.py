import hashlib
import os
import pathlib
import re
import subprocess
import tempfile
from datetime import datetime, timezone


ARCHIVE = pathlib.Path("/app/release.tar.zst")
BUILD_SCRIPT = pathlib.Path("/app/build.sh")
EPOCH_FILE = pathlib.Path("/app/build-metadata/epoch.txt")
SOURCE_ROOT = pathlib.Path("/app/src")


def run(cmd, *, env=None):
    merged_env = os.environ.copy()
    merged_env.setdefault("TZ", "UTC")
    if env:
        merged_env.update(env)
    return subprocess.run(cmd, check=True, capture_output=True, env=merged_env)


def run_build():
    subprocess.run([str(BUILD_SCRIPT)], check=True)
    assert ARCHIVE.exists(), "build script did not create the archive"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_timestamp(epoch_text):
    return datetime.fromtimestamp(int(epoch_text.strip()), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def tar_entries():
    result = run(
        [
            "tar",
            "--zstd",
            "--list",
            "--verbose",
            "--full-time",
            "--numeric-owner",
            "-f",
            str(ARCHIVE),
        ]
    )
    lines = result.stdout.decode().splitlines()
    pattern = re.compile(
        r"^(?P<mode>\S+)\s+(?P<owner>\d+)/(?P<group>\d+)\s+"
        r"(?P<size>\d+)\s+(?P<date>\d{4}-\d{2}-\d{2})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<name>.*)$"
    )
    entries = []
    for line in lines:
        match = pattern.match(line)
        assert match, f"unparsed tar listing line: {line!r}"
        info = match.groupdict()
        raw_name = info["name"]
        link_target = None
        if info["mode"].startswith("l") and " -> " in raw_name:
            raw_name, link_target = raw_name.split(" -> ", 1)
        entries.append(
            {
                "mode": info["mode"],
                "owner": info["owner"],
                "group": info["group"],
                "size": int(info["size"]),
                "timestamp": f"{info['date']} {info['time']}",
                "name": raw_name.rstrip("/"),
                "link_target": link_target,
            }
        )
    return entries


def entry_map():
    return {entry["name"]: entry for entry in tar_entries()}


def archive_bytes(path_in_archive):
    result = run(["tar", "--zstd", "-xOf", str(ARCHIVE), path_in_archive])
    return result.stdout


def extracted_member_names():
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_root = pathlib.Path(temp_dir) / "extract"
        extract_root.mkdir()
        run(["tar", "--zstd", "-xf", str(ARCHIVE), "-C", str(extract_root)])

        names = []
        for current_root, dirnames, filenames in os.walk(extract_root, topdown=True, followlinks=False):
            root_path = pathlib.Path(current_root)
            rel_root = root_path.relative_to(extract_root)
            for dirname in sorted(dirnames):
                names.append((rel_root / dirname).as_posix())
            for filename in sorted(filenames):
                names.append((rel_root / filename).as_posix())
        return sorted(names)


def expected_member_names():
    names = []

    for current_root, dirnames, filenames in os.walk(SOURCE_ROOT, topdown=True, followlinks=False):
        root_path = pathlib.Path(current_root)
        rel_root = root_path.relative_to(SOURCE_ROOT)

        pruned_dirnames = []
        for dirname in sorted(dirnames):
            rel_dir = (rel_root / dirname).as_posix()
            if dirname in {".git", "node_modules", "cache", "credentials", "__pycache__"}:
                continue
            if "__pycache__" in pathlib.PurePosixPath(rel_dir).parts:
                continue
            pruned_dirnames.append(dirname)
            names.append(rel_dir)
        dirnames[:] = pruned_dirnames

        for filename in sorted(filenames):
            rel_file = (rel_root / filename).as_posix()
            if filename.endswith((".pyc", ".o", ".bak")):
                continue
            if "__pycache__" in pathlib.PurePosixPath(rel_file).parts:
                continue
            source_path = SOURCE_ROOT / rel_file
            if source_path.is_symlink() and not source_path.exists():
                continue
            names.append(rel_file)

    return sorted(names)


def is_text_file(path):
    result = run(["file", "--brief", "--mime-encoding", str(path)])
    return result.stdout.decode().strip() != "binary"


def has_shebang(path):
    with path.open("rb") as handle:
        return handle.read(2) == b"#!"


def normalized_bytes(path):
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n") if is_text_file(path) else data


def build_reference_archive(destination):
    epoch = EPOCH_FILE.read_text().strip()

    with tempfile.TemporaryDirectory() as temp_dir:
        stage_root = pathlib.Path(temp_dir) / "stage"
        stage_root.mkdir()

        for relative_name in expected_member_names():
            source_path = SOURCE_ROOT / relative_name
            staged_path = stage_root / relative_name

            if source_path.is_dir():
                staged_path.mkdir(parents=True, exist_ok=True)
                os.chmod(staged_path, 0o750)
                continue

            staged_path.parent.mkdir(parents=True, exist_ok=True)

            if source_path.is_symlink():
                os.symlink(os.readlink(source_path), staged_path)
                continue

            staged_path.write_bytes(normalized_bytes(source_path))

            if relative_name.startswith("config/"):
                mode = 0o640
            elif os.access(source_path, os.X_OK) or has_shebang(source_path):
                mode = 0o555
            else:
                mode = 0o444
            os.chmod(staged_path, mode)

        for directory in sorted(path for path in stage_root.rglob("*") if path.is_dir()):
            os.chmod(directory, 0o750)

        members = sorted(path.relative_to(stage_root).as_posix() for path in stage_root.rglob("*"))
        members_blob = b"".join(member.encode() + b"\0" for member in members)

        tar_result = subprocess.run(
            [
                "tar",
                "--null",
                "--no-recursion",
                f"--directory={stage_root}",
                "--format=gnu",
                "--sort=name",
                "--owner=0",
                "--group=0",
                "--numeric-owner",
                f"--mtime=@{epoch}",
                "--files-from=-",
                "-cf",
                "-",
            ],
            input=members_blob,
            check=True,
            capture_output=True,
            env={**os.environ, "TZ": "UTC"},
        )
        subprocess.run(
            ["zstd", "-q", "-T1", "-10", "-o", str(destination)],
            input=tar_result.stdout,
            check=True,
            capture_output=True,
            env={**os.environ, "TZ": "UTC"},
        )


def test_build_is_reproducible_and_epoch_driven():
    assert BUILD_SCRIPT.exists(), "/app/build.sh is missing"
    assert os.access(BUILD_SCRIPT, os.X_OK), "/app/build.sh is not executable"

    original_epoch = EPOCH_FILE.read_text()

    run_build()
    first_hash = sha256(ARCHIVE)
    first_entries = tar_entries()
    assert first_entries, "archive is empty"
    expected_first_timestamp = expected_timestamp(original_epoch)
    assert all(entry["timestamp"] == expected_first_timestamp for entry in first_entries)

    run_build()
    assert sha256(ARCHIVE) == first_hash, "archive is not reproducible across reruns"

    new_epoch = f"{int(original_epoch.strip()) + 1}\n"
    EPOCH_FILE.write_text(new_epoch)
    try:
        run_build()
        second_hash = sha256(ARCHIVE)
        assert second_hash != first_hash, "changing the epoch did not change the archive hash"
        expected_second_timestamp = expected_timestamp(new_epoch)
        assert all(entry["timestamp"] == expected_second_timestamp for entry in tar_entries())
    finally:
        EPOCH_FILE.write_text(original_epoch)


def test_archive_matches_canonical_expected_output():
    run_build()

    with tempfile.TemporaryDirectory() as temp_dir:
        expected_archive = pathlib.Path(temp_dir) / "expected.tar.zst"
        build_reference_archive(expected_archive)
        assert ARCHIVE.read_bytes() == expected_archive.read_bytes(), (
            "archive bytes differ from the canonical GNU tar + zstd -10 deterministic output"
        )


def test_archive_contents_modes_normalization_and_full_member_set():
    run_build()
    entries = tar_entries()
    names = extracted_member_names()
    mapping = entry_map()

    assert names == expected_member_names(), "archive member set does not match the full expected tree"
    assert names == sorted(names), "archive entries are not sorted deterministically"
    assert all(entry["owner"] == "0" and entry["group"] == "0" for entry in entries)

    excluded_prefixes = [".git", "node_modules", "cache", "credentials", "src/__pycache__"]
    for name in names:
        assert not any(name == prefix or name.startswith(prefix + "/") for prefix in excluded_prefixes)
        assert not name.endswith((".pyc", ".o", ".bak"))
    assert "src/broken-link" not in mapping

    assert mapping["config/service.yaml"]["mode"] == "-rw-r-----"
    assert mapping["config/pipeline.yaml"]["mode"] == "-rw-r-----"
    assert mapping["src/unix.py"]["mode"] == "-r-xr-xr-x"
    assert mapping["scripts/deploy.sh"]["mode"] == "-r-xr-xr-x"
    assert mapping["src/main.c"]["mode"] == "-r--r--r--"
    assert mapping["docs/README.txt"]["mode"] == "-r--r--r--"
    assert mapping["assets/red.png"]["mode"] == "-r--r--r--"
    assert mapping["src"]["mode"] == "drwxr-x---"
    assert mapping["config"]["mode"] == "drwxr-x---"
    deep_dirs = [name for name in names if name.startswith("deeply/") and mapping[name]["mode"].startswith("d")]
    assert deep_dirs, "expected deeply nested directories in archive"
    assert all(mapping[name]["mode"] == "drwxr-x---" for name in deep_dirs)

    assert mapping["src/readme-link"]["mode"].startswith("l")
    assert mapping["src/readme-link"]["link_target"] == "../docs/README.txt"
    assert mapping["src/hosts-link"]["mode"].startswith("l")
    assert mapping["src/hosts-link"]["link_target"] == "/etc/hosts"

    readme_bytes = archive_bytes("docs/README.txt")
    windows_bytes = archive_bytes("src/windows.py")
    assert b"\r" not in readme_bytes
    assert b"\r" not in windows_bytes

    assert archive_bytes("assets/red.png") == (SOURCE_ROOT / "assets/red.png").read_bytes()
    assert archive_bytes("src/mixed.dat") == (SOURCE_ROOT / "src/mixed.dat").read_bytes()

    assert any("very_long_filename_that_exceeds_two_hundred_characters_" in name for name in names)
